"""Configuration-driven release provenance and anti-contamination contract for Travel-Scope runs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def load_provenance_policy(root: Path | None = None) -> dict[str, Any]:
    policy_root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    policy_file = policy_root / "references/provenance-policy.json"
    if not policy_file.is_file():
        raise FileNotFoundError(f"Missing provenance policy: {policy_file}")
    return json.loads(policy_file.read_text(encoding="utf-8"))


def _scan_obj_for_banned_patterns(obj: Any, patterns: list[re.Pattern], path_prefix: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(obj, str):
        for pattern in patterns:
            if pattern.search(obj):
                errors.append(f"字段 '{path_prefix}' 包含违规历史版本/串版标识: '{obj}' (匹配模式 {pattern.pattern})")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            curr_path = f"{path_prefix}.{k}" if path_prefix else k
            errors.extend(_scan_obj_for_banned_patterns(v, patterns, curr_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            curr_path = f"{path_prefix}[{idx}]"
            errors.extend(_scan_obj_for_banned_patterns(item, patterns, curr_path))
    return errors


def _scan_obj_for_escaping_paths(obj: Any, run_dir: Path, path_prefix: str = "") -> list[str]:
    errors: list[str] = []
    run_dir_resolved = run_dir.resolve()
    if isinstance(obj, str) and (":\\" in obj or ":/" in obj or (obj.startswith("/") and len(obj) > 1)):
        try:
            target_path = Path(obj).resolve()
            # If it's a file path pointing to evidence or runs
            if "runs" in target_path.parts or "evidence" in target_path.parts:
                try:
                    target_path.relative_to(run_dir_resolved)
                except ValueError:
                    errors.append(f"路径 '{path_prefix}' 越界指向外部运行目录: '{obj}' (当前目录: '{run_dir_resolved}')")
        except Exception:
            pass
    elif isinstance(obj, dict):
        for k, v in obj.items():
            curr_path = f"{path_prefix}.{k}" if path_prefix else k
            errors.extend(_scan_obj_for_escaping_paths(v, run_dir, curr_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            curr_path = f"{path_prefix}[{idx}]"
            errors.extend(_scan_obj_for_escaping_paths(item, run_dir, curr_path))
    return errors


def audit_run_provenance(run_dir: Path, manifest: dict[str, Any] | None = None, root: Path | None = None) -> list[str]:
    policy = load_provenance_policy(root)
    run_dir = run_dir.resolve()
    errors: list[str] = []

    # 1. Disallowed legacy duplicate gate reports
    disallowed = policy.get("disallowed_legacy_gate_reports", [])
    for rel in disallowed:
        legacy_file = run_dir / rel
        if legacy_file.is_file():
            errors.append(f"发现历史残留交付报告 '{rel}'，违背单源发布原则；必须清理该文件，只保留单一权威 'outputs/delivery-gate.json'")

    # 2. Check manifest
    manifest_file = run_dir / "manifest.json"
    if manifest is None and manifest_file.is_file():
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    if manifest:
        expected_version = policy.get("target_version")
        manifest_ver = manifest.get("skill_version") or manifest.get("version")
        if expected_version and manifest_ver != expected_version:
            errors.append(f"Manifest 版本号 ({manifest_ver}) 与当前生产版本 ({expected_version}) 不一致")

        banned_patterns = [re.compile(p, re.IGNORECASE) for p in policy.get("banned_path_patterns", [])]
        errors.extend(_scan_obj_for_banned_patterns(manifest, banned_patterns, "manifest"))

        if policy.get("strict_self_containment", True):
            errors.extend(_scan_obj_for_escaping_paths(manifest, run_dir, "manifest"))

    # 3. Check evidence files
    evidence_dir = run_dir / "evidence"
    if evidence_dir.is_dir():
        banned_patterns = [re.compile(p, re.IGNORECASE) for p in policy.get("banned_path_patterns", [])]
        for ef in sorted(evidence_dir.glob("*.json")):
            try:
                data = json.loads(ef.read_text(encoding="utf-8"))
                errors.extend(_scan_obj_for_banned_patterns(data, banned_patterns, f"evidence/{ef.name}"))
                if policy.get("strict_self_containment", True):
                    errors.extend(_scan_obj_for_escaping_paths(data, run_dir, f"evidence/{ef.name}"))
            except Exception:
                pass

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Travel-Scope run provenance and self-containment.")
    parser.add_argument("--run-dir", required=True, help="Path to run root directory")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    errors = audit_run_provenance(run_dir)
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", "errors": []}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
