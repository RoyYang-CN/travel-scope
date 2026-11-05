"""SQLite cache and usage ledger for provider requests.

The cache is intentionally provider/operation/key based so repeated runs can
reuse the same successful response without contacting a paid API again.
Secrets are never written to this database.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApiCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=10000")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS response_cache (
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                request_key TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT NOT NULL,
                PRIMARY KEY (provider, operation, request_key)
            );
            CREATE TABLE IF NOT EXISTS api_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                request_key TEXT NOT NULL,
                status TEXT NOT NULL,
                cache_hit INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage_estimates (
                run_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                estimated_calls INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (run_id, provider, operation)
            );
            CREATE TABLE IF NOT EXISTS translation_cache (
                source_text TEXT NOT NULL,
                source_lang TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (source_text, source_lang, target_lang)
            );
            CREATE INDEX IF NOT EXISTS idx_api_calls_created_at ON api_calls(created_at);
            CREATE TABLE IF NOT EXISTS asset_manifest (
                asset_path TEXT PRIMARY KEY,
                identity_hash TEXT NOT NULL,
                provider TEXT NOT NULL,
                poi_name TEXT NOT NULL,
                category TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                status TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS asset_usage (
                asset_path TEXT NOT NULL,
                poi_name TEXT NOT NULL,
                category TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (asset_path, poi_name, category)
            );
            CREATE INDEX IF NOT EXISTS idx_asset_usage_asset ON asset_usage(asset_path);
            CREATE INDEX IF NOT EXISTS idx_asset_usage_poi ON asset_usage(poi_name);
            """
        )
        self._db.commit()

    def get(self, provider: str, operation: str, request_key: str) -> Any | None:
        with self._lock:
            row = self._db.execute(
                "SELECT response_json FROM response_cache WHERE provider=? AND operation=? AND request_key=?",
                (provider, operation, request_key),
            ).fetchone()
            if not row:
                return None
            self._db.execute(
                "UPDATE response_cache SET last_used_at=? WHERE provider=? AND operation=? AND request_key=?",
                (_now(), provider, operation, request_key),
            )
            self._db.execute(
                "INSERT INTO api_calls(provider, operation, request_key, status, cache_hit, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (provider, operation, request_key, "cache_hit", 1, _now()),
            )
            self._db.commit()
            return json.loads(row[0])

    def put(self, provider: str, operation: str, request_key: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self._db.execute(
                "INSERT INTO response_cache(provider, operation, request_key, response_json, created_at, last_used_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(provider, operation, request_key) DO UPDATE SET response_json=excluded.response_json, last_used_at=excluded.last_used_at",
                (provider, operation, request_key, encoded, _now(), _now()),
            )
            self._db.commit()

    def start_call(self, provider: str, operation: str, request_key: str,
                   daily_limit: int, monthly_limit: int = 0) -> int:
        with self._lock:
            now = datetime.now(timezone.utc)
            day_prefix = now.date().isoformat()
            month_prefix = now.strftime("%Y-%m")
            day_row = self._db.execute(
                "SELECT COUNT(*) FROM api_calls WHERE provider=? AND operation=? AND status IN ('success','in_flight') AND cache_hit=0 AND created_at LIKE ?",
                (provider, operation, day_prefix + "%"),
            ).fetchone()
            month_row = self._db.execute(
                "SELECT COUNT(*) FROM api_calls WHERE provider=? AND operation=? AND status IN ('success','in_flight') AND cache_hit=0 AND created_at LIKE ?",
                (provider, operation, month_prefix + "%"),
            ).fetchone()
            if daily_limit > 0 and int(day_row[0] if day_row else 0) >= daily_limit:
                return 0
            if monthly_limit > 0 and int(month_row[0] if month_row else 0) >= monthly_limit:
                return 0
            self._db.execute(
                "INSERT INTO api_calls(provider, operation, request_key, status, cache_hit, created_at) VALUES (?, ?, ?, 'in_flight', 0, ?)",
                (provider, operation, request_key, _now()),
            )
            call_id = int(self._db.execute("SELECT last_insert_rowid()").fetchone()[0])
            self._db.commit()
            return call_id

    def finish_call(self, call_id: int, status: str, error: str = "") -> None:
        with self._lock:
            self._db.execute("UPDATE api_calls SET status=?, error=? WHERE id=?", (status, error[:500], call_id))
            self._db.commit()

    def record(self, provider: str, operation: str, request_key: str, status: str, error: str = "") -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO api_calls(provider, operation, request_key, status, cache_hit, error, created_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
                (provider, operation, request_key, status, error[:500], _now()),
            )
            self._db.commit()

    def paid_calls_today(self, provider: str, operation: str) -> int:
        prefix = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM api_calls WHERE provider=? AND operation=? AND status='success' AND cache_hit=0 AND created_at LIKE ?",
                (provider, operation, prefix + "%"),
            ).fetchone()
        return int(row[0] if row else 0)

    def usage_counts(self, provider: str, operation: str) -> tuple[int, int]:
        """Return (paid calls today, paid calls this month) for a provider operation."""
        now = datetime.now(timezone.utc)
        with self._lock:
            day = self._db.execute(
                "SELECT COUNT(*) FROM api_calls WHERE provider=? AND operation=? AND status IN ('success','in_flight') AND cache_hit=0 AND created_at LIKE ?",
                (provider, operation, now.date().isoformat() + "%"),
            ).fetchone()
            month = self._db.execute(
                "SELECT COUNT(*) FROM api_calls WHERE provider=? AND operation=? AND status IN ('success','in_flight') AND cache_hit=0 AND created_at LIKE ?",
                (provider, operation, now.strftime('%Y-%m') + "%"),
            ).fetchone()
        return int(day[0] if day else 0), int(month[0] if month else 0)

    def record_estimate(self, run_id: str, provider: str, operation: str, estimated_calls: int) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO usage_estimates(run_id, provider, operation, estimated_calls, created_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id, provider, operation) DO UPDATE SET estimated_calls=excluded.estimated_calls, created_at=excluded.created_at",
                (run_id, provider, operation, int(estimated_calls), _now()),
            )
            self._db.commit()

    def get_translation(self, source_text: str, source_lang: str = "zh", target_lang: str = "en") -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT translated_text FROM translation_cache WHERE source_text=? AND source_lang=? AND target_lang=?",
                (source_text, source_lang, target_lang),
            ).fetchone()
        return str(row[0]) if row else None

    def put_translation(self, source_text: str, translated_text: str, source_lang: str = "zh", target_lang: str = "en") -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO translation_cache(source_text, source_lang, target_lang, translated_text, created_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(source_text, source_lang, target_lang) DO UPDATE SET translated_text=excluded.translated_text, created_at=excluded.created_at",
                (source_text, source_lang, target_lang, translated_text, _now()),
            )
            self._db.commit()

    def register_asset(self, asset_path: str, identity_hash: str, provider: str,
                       poi_name: str, category: str, source_ref: str,
                       status: str, mime_type: str, byte_size: int,
                       content_hash: str) -> None:
        """Record a local image asset without storing provider credentials."""
        with self._lock:
            self._db.execute(
                "INSERT INTO asset_manifest(asset_path, identity_hash, provider, poi_name, category, source_ref, status, mime_type, byte_size, content_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(asset_path) DO UPDATE SET identity_hash=excluded.identity_hash, provider=excluded.provider, poi_name=excluded.poi_name, category=excluded.category, source_ref=excluded.source_ref, status=excluded.status, mime_type=excluded.mime_type, byte_size=excluded.byte_size, content_hash=excluded.content_hash",
                (asset_path, identity_hash, provider, poi_name, category, source_ref, status, mime_type, int(byte_size), content_hash, _now()),
            )
            self._db.execute(
                "INSERT OR IGNORE INTO asset_usage(asset_path, poi_name, category, created_at) VALUES (?, ?, ?, ?)",
                (asset_path, poi_name, category, _now()),
            )
            self._db.commit()

    def close(self) -> None:
        self._db.close()


def default_cache_path(output: str | Path) -> Path:
    configured = os.environ.get("TRAVEL_SCOPE_CACHE_DB", "").strip()
    if configured:
        return Path(configured)
    # A stable user-level default lets independent country/version runs reuse
    # the same cache. Deployments that need isolation can still set the env var.
    return Path.home() / ".travel-scope" / "travel_scope_cache.sqlite3"
