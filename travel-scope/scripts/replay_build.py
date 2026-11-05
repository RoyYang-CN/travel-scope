"""Re-render a sealed Travel-Scope run and compare the artifact digests.

v4.2.1 §13.2.3. This is the check that replaces "trust the fingerprint we recomputed
afterwards": the input bytes and the artifact bytes were frozen by the generator
before rendering, so any out-of-band edit to dataset.json, evidence/*.json or the
delivered HTML now fails here instead of passing all four gates.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from run_seal import replay
except ImportError:  # pragma: no cover
    from scripts.run_seal import replay


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a sealed Travel-Scope build and compare digests")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--skill-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--report", default="", help="Optional JSON report path (outside the run dir)")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    report = replay(Path(args.run_dir).resolve(), Path(args.skill_root).resolve(), timeout=args.timeout)
    problems = list(report.get("errors") or []) + list(report.get("seal_errors") or []) + list(report.get("mismatches") or [])
    report["status"] = "PASS" if report.get("replay_clean") else "FAIL"
    report["problems"] = problems
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(payload, encoding="utf-8")
    print(payload if report["status"] == "PASS" else json.dumps(
        {"status": "FAIL", "problems": problems, "generator_exit": report.get("generator_exit")},
        ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
