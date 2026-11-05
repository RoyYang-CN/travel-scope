"""Report SQLite provider usage and enforce daily/monthly safety thresholds."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def build_report(db_path: str | Path, daily_limit: int, monthly_limit: int) -> tuple[dict, bool]:
    db = sqlite3.connect(db_path)
    db.execute(
        "CREATE TABLE IF NOT EXISTS usage_estimates (run_id TEXT NOT NULL, provider TEXT NOT NULL, operation TEXT NOT NULL, estimated_calls INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (run_id, provider, operation))"
    )
    db.commit()
    now = datetime.now(timezone.utc)
    day_prefix = now.date().isoformat() + "%"
    month_prefix = now.strftime("%Y-%m") + "%"
    rows = db.execute(
        "SELECT provider, operation, status, cache_hit, COUNT(*) FROM api_calls "
        "WHERE status IN ('success','in_flight','error') GROUP BY provider, operation, status, cache_hit"
    ).fetchall()
    estimates = db.execute(
        "SELECT provider, operation, SUM(estimated_calls) FROM usage_estimates GROUP BY provider, operation"
    ).fetchall()
    daily = db.execute(
        "SELECT COUNT(*) FROM api_calls WHERE status IN ('success','in_flight') AND cache_hit=0 AND created_at LIKE ?",
        (day_prefix,),
    ).fetchone()[0]
    monthly = db.execute(
        "SELECT COUNT(*) FROM api_calls WHERE status IN ('success','in_flight') AND cache_hit=0 AND created_at LIKE ?",
        (month_prefix,),
    ).fetchone()[0]
    db.close()
    alerts = []
    if daily_limit > 0 and daily >= daily_limit:
        alerts.append(f"daily paid-call limit reached: {daily}/{daily_limit}")
    if monthly_limit > 0 and monthly >= monthly_limit:
        alerts.append(f"monthly paid-call limit reached: {monthly}/{monthly_limit}")
    report = {
        "generated_at": now.isoformat(),
        "database": str(db_path),
        "paid_calls_today": daily,
        "paid_calls_this_month": monthly,
        "daily_limit": daily_limit,
        "monthly_limit": monthly_limit,
        "alerts": alerts,
        "breakdown": [
            {"provider": p, "operation": o, "status": s, "cache_hit": bool(h), "count": n}
            for p, o, s, h, n in rows
        ],
        "estimates": [
            {"provider": p, "operation": o, "estimated_calls": int(n)}
            for p, o, n in estimates
        ],
    }
    return report, not alerts


def main() -> int:
    parser = argparse.ArgumentParser(description="Report Travel-Scope API cache usage")
    parser.add_argument("--db", required=True)
    parser.add_argument("--daily-limit", type=int, default=33)
    parser.add_argument("--monthly-limit", type=int, default=1000)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    report, safe = build_report(args.db, args.daily_limit, args.monthly_limit)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if safe else 2


if __name__ == "__main__":
    raise SystemExit(main())
