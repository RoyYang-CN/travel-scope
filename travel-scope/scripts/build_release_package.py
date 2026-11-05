"""Build and verify the deterministic Travel-Scope Skill ZIP.

The release inventory deliberately excludes product-origin.json because a file
cannot contain its own digest.  An installable package still needs that file so
verify_product.py can run after extraction.  The package authority is therefore
exactly: product-origin.json::inventory plus product-origin.json itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

try:
    from verify_product import verify
except ImportError:  # pragma: no cover - module execution from repository root
    from scripts.verify_product import verify


ROOT = Path(__file__).resolve().parents[1]
SCOPE_PATH = ROOT / "references" / "release-scope.json"
ORIGIN_NAME = "product-origin.json"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class PackageError(ValueError):
    pass


def _json(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8"))


def package_members(root: Path = ROOT) -> list[str]:
    origin = _json(root / ORIGIN_NAME)
    inventory = list(origin.get("inventory") or [])
    if ORIGIN_NAME in inventory:
        raise PackageError("product-origin.json must not self-register in inventory")
    if len(inventory) != len(set(inventory)):
        raise PackageError("product-origin.json inventory contains duplicate paths")
    return sorted(inventory + [ORIGIN_NAME])


def expected_archive_names(root: Path = ROOT) -> list[str]:
    scope = _json(root / "references" / "release-scope.json")
    prefix = str((scope.get("packaging") or {}).get("package_root") or "")
    if not prefix or not prefix.endswith("/"):
        raise PackageError("packaging.package_root must be a non-empty trailing-slash path")
    return [prefix + rel for rel in package_members(root)]


def _excluded_hits(names: list[str], scope: dict) -> list[str]:
    forbidden = list((scope.get("packaging") or {}).get("exclude_match_substrings") or [])
    return sorted(name for name in names if any(token in name for token in forbidden))


def verify_archive(path: Path, root: Path = ROOT) -> dict:
    scope = _json(root / "references" / "release-scope.json")
    expected = expected_archive_names(root)
    prefix = scope["packaging"]["package_root"]
    with zipfile.ZipFile(path, "r") as archive:
        names = sorted(item.filename for item in archive.infolist() if not item.is_dir())
        if names != expected:
            raise PackageError("ZIP member set differs from inventory + product-origin.json")
        hits = _excluded_hits(names, scope)
        if hits:
            raise PackageError("ZIP contains excluded paths: %s" % hits[:4])
        mismatches = []
        for name in names:
            rel = name[len(prefix):]
            if archive.read(name) != (root / rel).read_bytes():
                mismatches.append(rel)
        if mismatches:
            raise PackageError("ZIP bytes differ from release tree: %s" % mismatches[:4])
    return {
        "status": "PASS",
        "files": len(expected),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        "bytes": path.stat().st_size,
    }


def build(out: Path, root: Path = ROOT) -> dict:
    verify(root)
    scope = _json(root / "references" / "release-scope.json")
    prefix = scope["packaging"]["package_root"]
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=out.name + ".", suffix=".tmp", dir=out.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=9) as archive:
            for rel in package_members(root):
                info = zipfile.ZipInfo(prefix + rel, FIXED_ZIP_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (0o100644 & 0xFFFF) << 16
                archive.writestr(info, (root / rel).read_bytes(), compress_type=zipfile.ZIP_DEFLATED,
                                 compresslevel=9)
        verify_archive(temp_path, root)
        os.replace(temp_path, out)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return verify_archive(out, root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic Travel-Scope release ZIP")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if bool(args.out) == bool(args.verify):
        parser.error("choose exactly one of --out or --verify")
    if args.verify:
        result = verify_archive(args.verify)
    else:
        scope = _json(SCOPE_PATH)
        out = args.out or ROOT.parents[1] / scope["packaging"]["zip_name"]
        result = build(out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
