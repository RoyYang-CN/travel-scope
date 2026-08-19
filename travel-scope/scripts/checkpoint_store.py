#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crash-tolerant checkpoint storage for Travel-Scope deep research runs."""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


CATEGORIES = ("hotels", "restaurants", "attractions", "evidence", "dynamic_info")
STATUS_VALUES = ("pending", "running", "completed", "failed")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_name(value):
    cleaned = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", value.strip())
    return cleaned.strip("_") or "unnamed"


def atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def load_manifest(run_dir):
    path = Path(run_dir) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"manifest.json not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(run_dir, manifest):
    manifest["updated_at"] = now_iso()
    atomic_write_json(Path(run_dir) / "manifest.json", manifest)


def destination_entry(manifest, destination):
    destinations = manifest.setdefault("destinations", {})
    if destination not in destinations:
        destinations[destination] = {
            "safe_name": safe_name(destination),
            "status": "pending",
            "categories": {category: 0 for category in CATEGORIES},
            "updated_at": now_iso(),
        }
    return destinations[destination]


def init_run(args):
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or datetime.now().strftime("travel_scope_run_%Y%m%d_%H%M%S")
    run_dir = root / run_id
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    (run_dir / "destinations").mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "country": args.country,
        "mode": args.mode,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "status": "running",
        "destinations": {},
    }
    atomic_write_json(run_dir / "manifest.json", manifest)
    print(json.dumps({"run_dir": str(run_dir), "run_id": run_id}, ensure_ascii=False))


def append_record(args):
    run_dir = Path(args.run_dir).resolve()
    manifest = load_manifest(run_dir)
    if args.category not in CATEGORIES:
        raise ValueError(f"unsupported category: {args.category}")
    record = json.loads(args.record_json)
    if not isinstance(record, dict):
        raise ValueError("record-json must be a JSON object")
    record_key = args.record_id or record.get("record_id") or record.get("id")
    if record_key:
        record["record_id"] = str(record_key)
    entry = destination_entry(manifest, args.destination)
    destination_dir = run_dir / "destinations" / entry["safe_name"]
    destination_dir.mkdir(parents=True, exist_ok=True)
    path = destination_dir / f"{args.category}.jsonl"
    if record_key and path.exists():
        for existing in read_jsonl(path):
            if str(existing.get("record_id", "")) == str(record_key):
                print(json.dumps({"destination": args.destination, "category": args.category, "record_id": str(record_key), "skipped": "duplicate"}, ensure_ascii=False))
                return
    record.setdefault("checkpointed_at", now_iso())
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    entry["categories"][args.category] = entry["categories"].get(args.category, 0) + 1
    entry["updated_at"] = now_iso()
    save_manifest(run_dir, manifest)
    print(json.dumps({"destination": args.destination, "category": args.category, "count": entry["categories"][args.category]}, ensure_ascii=False))


def mark_destination(args):
    run_dir = Path(args.run_dir).resolve()
    manifest = load_manifest(run_dir)
    if args.status not in STATUS_VALUES:
        raise ValueError(f"unsupported status: {args.status}")
    entry = destination_entry(manifest, args.destination)
    entry["status"] = args.status
    entry["note"] = args.note
    entry["updated_at"] = now_iso()
    save_manifest(run_dir, manifest)
    print(json.dumps({"destination": args.destination, "status": args.status}, ensure_ascii=False))


def show_status(args):
    manifest = load_manifest(Path(args.run_dir).resolve())
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def read_jsonl(path):
    records = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
    return records


def merge_run(args):
    run_dir = Path(args.run_dir).resolve()
    manifest = load_manifest(run_dir)
    if args.require_completed:
        incomplete = [name for name, entry in manifest.get("destinations", {}).items() if entry.get("status") != "completed"]
        if incomplete:
            raise ValueError(f"incomplete destinations: {', '.join(incomplete)}")
    merged = {
        "schema_version": manifest.get("schema_version", 1),
        "run_id": manifest["run_id"],
        "country": manifest.get("country", ""),
        "mode": manifest.get("mode", ""),
        "merged_at": now_iso(),
        "destinations": {},
    }
    for destination, entry in manifest.get("destinations", {}).items():
        destination_dir = run_dir / "destinations" / entry["safe_name"]
        merged_destination = {"status": entry.get("status", "pending")}
        for category in CATEGORIES:
            path = destination_dir / f"{category}.jsonl"
            merged_destination[category] = read_jsonl(path) if path.exists() else []
        merged["destinations"][destination] = merged_destination
    atomic_write_json(args.output, merged)
    print(json.dumps({"output": str(Path(args.output).resolve()), "destinations": len(merged["destinations"])}, ensure_ascii=False))


def build_parser():
    parser = argparse.ArgumentParser(description="Travel-Scope checkpoint store")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--root", default=".temp")
    init.add_argument("--country", required=True)
    init.add_argument("--mode", default="deep", choices=("shallow", "medium", "deep", "super_deep", "custom"))
    init.add_argument("--run-id")
    init.set_defaults(func=init_run)

    append = sub.add_parser("append")
    append.add_argument("--run-dir", required=True)
    append.add_argument("--destination", required=True)
    append.add_argument("--category", required=True, choices=CATEGORIES)
    append.add_argument("--record-json", required=True)
    append.add_argument("--record-id", help="Stable id used to make retries idempotent")
    append.set_defaults(func=append_record)

    mark = sub.add_parser("mark")
    mark.add_argument("--run-dir", required=True)
    mark.add_argument("--destination", required=True)
    mark.add_argument("--status", required=True, choices=STATUS_VALUES)
    mark.add_argument("--note", default="")
    mark.set_defaults(func=mark_destination)

    status = sub.add_parser("status")
    status.add_argument("--run-dir", required=True)
    status.set_defaults(func=show_status)

    merge = sub.add_parser("merge")
    merge.add_argument("--run-dir", required=True)
    merge.add_argument("--output", required=True)
    merge.add_argument("--require-completed", action="store_true")
    merge.set_defaults(func=merge_run)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, FileExistsError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
