"""Detect substituted/modified releases. Never automatically reseal."""
import hashlib
import json
from pathlib import Path


def release_file_paths(root: Path) -> set[str]:
    """Single source of truth for what counts as release content.

    verify() and reseal_product.py must agree exactly, or a controlled reseal can
    freeze a different file set than verification checks.
    """
    root = Path(root).resolve()
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "product-origin.json"
        and "__pycache__" not in path.parts
        and not any(part.startswith(".temp") for part in path.relative_to(root).parts)
        and "outputs" not in path.relative_to(root).parts
        and path.suffix != ".pyc"
        and ".pytest_cache" not in path.parts
    }


def verify(root=None):
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    manifest = json.loads((root / "product-origin.json").read_text(encoding="utf-8"))
    contract = json.loads((root / "references/renderer-contract.json").read_text(encoding="utf-8"))
    version_policy = json.loads((root / "references/version-policy.json").read_text(encoding="utf-8"))
    provenance_policy = json.loads((root / "references/provenance-policy.json").read_text(encoding="utf-8"))
    versions = {
        "product-origin.json": manifest.get("version"),
        "renderer-contract.json": contract.get("version"),
        "version-policy.json": version_policy.get("current_version"),
        "provenance-policy.json": provenance_policy.get("target_version"),
    }
    if len(set(versions.values())) != 1:
        raise ValueError(f"Version policy mismatch across release files: {versions}")
    if manifest["product"] != "Travel-Scope" or manifest["renderer_id"] != contract["renderer_id"]:
        raise ValueError("Travel-Scope product/renderer identity mismatch")
    expected = set(manifest["inventory"])
    if expected != set(manifest["sha256"]):
        raise ValueError("Product inventory and digest list differ")
    actual = release_file_paths(root)
    if actual != expected:

        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(f"Product inventory mismatch; missing={missing}; unexpected={unexpected}")
    for relative, digest in manifest["sha256"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"Missing or unsafe product file: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Product changed; review release provenance: {relative}")
    return manifest


if __name__ == "__main__":
    result = verify()
    print(f"Travel-Scope {result['version']} / {result['renderer_id']}: integrity verified")
