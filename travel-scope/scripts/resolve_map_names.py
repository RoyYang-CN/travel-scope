"""Collect-stage resolver: write the verified English map names into dataset.json.

v4.2.1 §11.5 + §13.2.6. The v4.2.0 patch script fixed names at the *output* stage by
deleting characters, so the sealed input and the delivered artifact disagreed and every
validator was looking at the dirty copy. This tool moves the fix to the only legal place:
the input, before it is sealed, driven by collect-stage evidence rather than by guesswork.

It never invents a name. Every recovered value is copied verbatim from
evidence/map_verification.json#resolved_name, matched by coordinate (the evidence keys use
the English name while map_targets keys use the Chinese name, so a name join silently
misses). Anything that cannot be recovered is degraded to the contract tier
`unnamed_coordinate`, which the renderer must label as coordinate-located.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from map_contract import resolve_overseas_targets, usable_entity_name
    from run_seal import file_sha256
except ImportError:  # pragma: no cover
    from scripts.map_contract import resolve_overseas_targets, usable_entity_name
    from scripts.run_seal import file_sha256

EVIDENCE_NAME = "map_verification.json"


def destination_english_map(data: dict) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in data.get("destinations") or []:
        if isinstance(row, list) and len(row) > 1:
            english = usable_entity_name(row[1])
            if english:
                mapping[str(row[0]).strip()] = english
    return mapping


def resolve(run_dir: Path, dataset_path: Path, evidence_path: Path, write: bool) -> dict:
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    before = json.dumps(data.get("map_targets") or {}, ensure_ascii=False, sort_keys=True)
    report = resolve_overseas_targets(data.get("map_targets") or {}, evidence,
                                      destination_english_map(data))
    after = json.dumps(data.get("map_targets") or {}, ensure_ascii=False, sort_keys=True)
    levels: dict[str, int] = {}
    for target in (data.get("map_targets") or {}).values():
        if isinstance(target, dict):
            levels[str(target.get("target_level"))] = levels.get(str(target.get("target_level")), 0) + 1
    result = {
        "changed": before != after,
        "input_sha256_before": file_sha256(dataset_path),
        "levels": levels,
        **{key: value for key, value in report.items() if key != "unrecovered_keys"},
        "unrecovered_keys": sorted(report["unrecovered_keys"])[:20],
        "evidence_file": str(evidence_path),
    }
    if write and before != after:
        dataset_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["input_sha256_after"] = file_sha256(dataset_path)
    elif write:
        result["input_sha256_after"] = result["input_sha256_before"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve overseas map names from collect evidence into dataset.json")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--data", default="", help="默认 <run-dir>/dataset.json")
    parser.add_argument("--evidence", default="", help=f"默认 <run-dir>/evidence/{EVIDENCE_NAME}")
    parser.add_argument("--dry-run", action="store_true", help="只报告，不写回")
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    dataset_path = Path(args.data) if args.data else run_dir / "dataset.json"
    evidence_path = Path(args.evidence) if args.evidence else run_dir / "evidence" / EVIDENCE_NAME
    if not dataset_path.is_file():
        print(json.dumps({"status": "FAIL", "error": f"dataset 不存在: {dataset_path}"}, ensure_ascii=False))
        return 2
    if not evidence_path.is_file():
        print(json.dumps({"status": "FAIL",
                          "error": f"缺少 {evidence_path}；没有采集证据就只能伪造名称或退回坐标档，前者被明令禁止"},
                         ensure_ascii=False))
        return 2
    report = resolve(run_dir, dataset_path, evidence_path, write=not args.dry_run)
    status = "PASS" if report["no_coordinate"] == 0 else "FAIL"
    print(json.dumps({"status": status, "mode": "dry-run" if args.dry_run else "write", **report},
                     ensure_ascii=False, indent=2))
    if status == "FAIL":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
