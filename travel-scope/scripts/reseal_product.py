"""Controlled resealing of the Travel-Scope release seal.

v4.2.1 §15.1.3. Before this script existed, every version bump was resealed by an
ad-hoc `.temp/reseal_product.py` copy that had drifted (it still pointed at
travel-scope-v4.0.5 and used a weaker file-exclusion set than verify_product.py).
An uncontrolled reseal path is what pushes release governance into throwaway
scripts, so this module is the only authorized way to change the seal.

`verify_product.verify()` stays read-only: this script never runs automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    from verify_product import release_file_paths, verify
except ImportError:  # pragma: no cover
    from scripts.verify_product import release_file_paths, verify

PRODUCT = "Travel-Scope"
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.match(value or "")
    if not match:
        raise ValueError(f"版本号格式非法: {value!r}（应为 x.y.z）")
    parts = tuple(int(group) for group in match.groups())
    if parts[2] > 99:
        raise ValueError(f"补丁号超出 0-99 规则: {value}")
    return parts  # type: ignore[return-value]


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sync_policy_versions(root: Path, version: str) -> list[str]:
    """Keep the four version-bearing release files in lockstep before sealing."""
    touched: list[str] = []
    contract_path = root / "references/renderer-contract.json"
    version_policy_path = root / "references/version-policy.json"
    provenance_path = root / "references/provenance-policy.json"
    for path, key in ((contract_path, "version"), (version_policy_path, "current_version"), (provenance_path, "target_version")):
        if not path.is_file():
            raise ValueError(f"发布文件缺失: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get(key) != version:
            payload[key] = version
            _write_json(path, payload)
            touched.append(path.relative_to(root).as_posix())
    return touched


def reseal(root: Path, version: str, approval: str, renderer_id: str | None = None, dry_run: bool = False,
           allow_same_version: bool = False) -> dict:
    origin_path = root / "product-origin.json"
    previous = json.loads(origin_path.read_text(encoding="utf-8")) if origin_path.is_file() else {}
    previous_version = previous.get("version", "")
    if previous_version:
        comparison = _version_tuple(version) <= _version_tuple(previous_version)
        same_version = _version_tuple(version) == _version_tuple(previous_version)
        if comparison and not (same_version and allow_same_version):
            raise ValueError(
                f"版本号必须递增: {previous_version} -> {version}"
                + ("" if not same_version else "（同一版本重封需显式 --allow-same-version，仅限发布前修正）")
            )
    else:
        _version_tuple(version)
    if len(approval.strip()) < 8:
        raise ValueError("--approve 必须写明本次发布改动摘要（不少于 8 个字符），无摘要不得重封")

    chosen_renderer = renderer_id or previous.get("renderer_id")
    if not chosen_renderer:
        raise ValueError("缺少 renderer_id（首封必须显式提供 --renderer-id）")

    inventory = sorted(release_file_paths(root))
    digests = {relative: hashlib.sha256((root / relative).read_bytes()).hexdigest() for relative in inventory}
    manifest = {
        "product": PRODUCT,
        "version": version,
        "renderer_id": chosen_renderer,
        "source_basis": approval.strip(),
        "inventory": inventory,
        "sha256": digests,
    }
    if dry_run:
        return {"dry_run": True, "files": len(inventory), "version": version, "renderer_id": chosen_renderer}

    # Policy versions must be updated before the digests are frozen, otherwise the
    # freshly sealed file immediately contradicts one of its own entries.
    touched = sync_policy_versions(root, version)
    inventory = sorted(release_file_paths(root))
    digests = {relative: hashlib.sha256((root / relative).read_bytes()).hexdigest() for relative in inventory}
    manifest["inventory"] = inventory
    manifest["sha256"] = digests
    _write_json(origin_path, manifest)
    result = verify(root)
    return {
        "dry_run": False,
        "version": result["version"],
        "renderer_id": result["renderer_id"],
        "sealed_files": len(inventory),
        "policy_files_synced": touched,
        "seal_sha256": hashlib.sha256(origin_path.read_bytes()).hexdigest(),
        "approved_by": approval.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reseal product-origin.json for an approved Travel-Scope release")
    parser.add_argument("--skill-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--version", required=True)
    parser.add_argument("--approve", required=True, help="本次发布的改动摘要（写进 source_basis，必填）")
    parser.add_argument("--renderer-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-same-version", action="store_true",
                        help="发布前对同一版本反复修正时重封；已发布版本禁止使用")
    args = parser.parse_args()
    try:
        report = reseal(Path(args.skill_root).resolve(), args.version, args.approve, args.renderer_id,
                        args.dry_run, args.allow_same_version)
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": "PASS", **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
