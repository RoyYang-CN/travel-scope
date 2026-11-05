"""Seal the inputs of a Travel-Scope run at generation time and replay the build.

v4.2.1 §13.2. Before this module, `manifest.input_sha256` and
`manifest.product_fingerprint` were filled in *after* delivery by throwaway
`.temp/update_manifest_provenance.py` / `finalize_run.py` scripts that hashed
whatever dataset.json happened to contain at that moment. The seal therefore
attested the current state instead of the generated state, so an out-of-band edit
to dataset.json was invisible to all four validation layers.

Rules enforced here:
  * only the generator may seal, and it seals *before* rendering;
  * a seal records the input bytes, the collect-stage evidence set, the release
    identity and the exact command line;
  * re-sealing is allowed but appends an auditable history entry with a reason;
  * `replay_build.py` re-renders from the sealed input and compares artifact
    digests, which is what actually proves nobody edited the shipped file.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess

import pyc_hygiene as pyc
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SEAL_SCHEMA = 1
COLLECT_EVIDENCE_GLOBS = (
    "scope.json",
    "route_corridors.json",
    "asset-manifest.json",
    "evidence/*.json",
)
REPLAY_ENV = "TRAVEL_SCOPE_REPLAY"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def collect_digest(run_dir: Path) -> dict:
    """Hash the collect-stage evidence set as one anchor.

    This is the independent anchor the old chain lacked: evidence files are written
    by the research stages and are not recomputed from the delivered dataset.
    """
    run_dir = Path(run_dir).resolve()
    files: dict[str, str] = {}
    for pattern in COLLECT_EVIDENCE_GLOBS:
        for path in sorted(run_dir.glob(pattern)):
            if path.is_file():
                files[path.relative_to(run_dir).as_posix()] = file_sha256(path)
    payload = "\n".join(f"{name}\t{digest}" for name, digest in sorted(files.items()))
    return {"sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(), "files": files}


def load_manifest(manifest_path: Path) -> dict:
    path = Path(manifest_path)
    if not path.is_file():
        raise ValueError(f"运行 manifest 不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(manifest_path: Path, manifest: dict) -> None:
    path = Path(manifest_path)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def seal_inputs(manifest_path: Path, dataset_path: Path, run_dir: Path, generation_command: str,
                skill_version: str, renderer_id: str, spa_renderer_id: str,
                reason: str = "", allow_reseal: bool = False, generation_argv: list[str] | None = None,
                product_fingerprint: str = "") -> dict:
    """Freeze the exact bytes the renderer is about to consume."""
    manifest_path = Path(manifest_path)
    dataset_path = Path(dataset_path)
    manifest = load_manifest(manifest_path)
    previous = manifest.get("seal") or {}
    new_input = file_sha256(dataset_path)
    new_collect = collect_digest(run_dir)

    if previous and (previous.get("input_sha256") != new_input or previous.get("collect_digest") != new_collect["sha256"]):
        if not allow_reseal:
            raise ValueError(
                "已存在不同的输入封存。输入变化必须显式重新封存并写明原因（--allow-reseal --reason），"
                f"旧 input_sha256={previous.get('input_sha256', '')[:12]} 新={new_input[:12]}，"
                f"旧 collect={previous.get('collect_digest', '')[:12]} 新={new_collect['sha256'][:12]}"
            )
        if not reason.strip():
            raise ValueError("重新封存必须提供 --reason 说明输入为何变化")

    history = manifest.setdefault("seal_history", [])
    if previous:
        entry = dict(previous)
        entry["superseded_at"] = _now()
        entry["supersede_reason"] = reason.strip() or "未说明"
        history.append(entry)

    seal = {
        "schema": SEAL_SCHEMA,
        "sealed_at": _now(),
        "sealed_by": "gen_travel_scope.py",
        "skill_version": skill_version,
        "renderer_id": renderer_id,
        "spa_renderer_id": spa_renderer_id,
        "generation_command": generation_command,
        "generation_argv": list(generation_argv or []),
        "dataset_relpath": dataset_path.resolve().relative_to(Path(run_dir).resolve()).as_posix()
        if Path(dataset_path).resolve().is_relative_to(Path(run_dir).resolve())
        else str(dataset_path.resolve()),
        "input_sha256": new_input,
        "collect_digest": new_collect["sha256"],
        "collect_files": new_collect["files"],
        "product_fingerprint": product_fingerprint,
        "reseal_reason": reason.strip(),
        "build": {},
    }
    manifest["seal"] = seal
    # Keep the legacy fields populated and consistent so older consumers do not
    # silently read a stale value; they are now derived from the seal, not patched.
    manifest["skill_version"] = skill_version
    manifest["target_version"] = skill_version
    # The manifest line that claims "how this artifact was produced" is now written by
    # the build itself, so it can no longer describe some earlier generation.
    manifest["generation_command"] = generation_command
    manifest["input_sha256"] = new_input
    # v4.2.1: the release fingerprint is written by the build too. Until now the field carried
    # whatever the previous run had put there, so delivery_gate's "product_fingerprint 与当前
    # 发布指纹不一致" could never be satisfied by a legitimate rebuild -- and a stale value was
    # the only evidence that some product version rendered this artifact.
    if product_fingerprint:
        manifest["product_fingerprint"] = product_fingerprint
    write_manifest(manifest_path, manifest)
    return seal


def record_build(manifest_path: Path, artifacts: dict[str, Path]) -> dict:
    """Store the digest of every artifact exactly as written by this build."""
    manifest_path = Path(manifest_path)
    manifest = load_manifest(manifest_path)
    seal = manifest.get("seal")
    if not isinstance(seal, dict) or not seal.get("input_sha256"):
        raise ValueError("生成前未封存输入，拒绝记录产物指纹（seal 缺失说明构建绕过了标准入口）")
    seal["build"] = {name: file_sha256(path) for name, path in sorted(artifacts.items()) if Path(path).is_file()}
    seal["built_at"] = _now()
    write_manifest(manifest_path, manifest)
    return seal


def verify_seal(run_dir: Path, manifest: dict) -> list[str]:
    """Check the delivered state against the seal. Returns human-readable errors."""
    run_dir = Path(run_dir).resolve()
    errors: list[str] = []
    seal = manifest.get("seal")
    if not isinstance(seal, dict):
        return ["缺少 manifest.seal 输入封存记录（v4.2.1 起为必需，历史 run 需按 §13.2 重建）"]
    dataset_path = run_dir / seal.get("dataset_relpath", "dataset.json")
    if not dataset_path.is_file():
        return [f"封存指向的输入文件不存在: {dataset_path}"]
    actual_input = file_sha256(dataset_path)
    if actual_input != seal.get("input_sha256"):
        errors.append(
            f"dataset.json 在封存后被改动: seal={str(seal.get('input_sha256'))[:12]} actual={actual_input[:12]}"
            "（禁止用重算指纹的方式追认，必须重新采集或显式重新封存）"
        )
    # Only the files frozen at seal time are compared. Gate reports written after the seal
    # (visual_qa.json, media_audit.json) are outputs of a check, not inputs the build read, so
    # re-globbing evidence/*.json turned every honest re-run into a tamper alarm -- and hid the
    # real question, which is whether a frozen input moved.
    recorded = seal.get("collect_files") or {}
    if not recorded:
        errors.append("封存记录里没有逐文件证据摘要 (collect_files 缺失)，无法判定采集证据是否被改动")
    changed: list[str] = []
    missing: list[str] = []
    for name, digest in sorted(recorded.items()):
        path = run_dir / name
        if not path.is_file():
            missing.append(name)
        elif file_sha256(path) != digest:
            changed.append(f"{name} (在盘={file_sha256(path)[:12]}, 封存={str(digest)[:12]})")
    if changed:
        errors.append("采集阶段证据在封存后被改动: " + ", ".join(changed[:8]))
    if missing:
        errors.append("采集阶段证据文件缺失: " + ", ".join(missing[:8]))
    build = seal.get("build") or {}
    if not build:
        errors.append("封存记录里没有产物指纹（构建未调用 record_build）")
    output_dir = run_dir / "outputs"
    for name, digest in build.items():
        candidate = output_dir / name if (output_dir / name).is_file() else run_dir / name
        if not candidate.is_file():
            errors.append(f"封存记录的产物已不存在: {name}")
        elif file_sha256(candidate) != digest:
            errors.append(f"产物在封存后被改动: {name} seal={digest[:12]} actual={file_sha256(candidate)[:12]}")
    return errors


def replay(run_dir: Path, skill_root: Path, dataset_path: str | None = None, timeout: int = 900) -> dict:
    """Re-render from the sealed input into a scratch dir and compare digests."""
    run_dir = Path(run_dir).resolve()
    skill_root = Path(skill_root).resolve()
    manifest = load_manifest(run_dir / "manifest.json")
    seal = manifest.get("seal") or {}
    report: dict = {"run_dir": str(run_dir), "seal_present": bool(seal), "mismatches": [], "errors": []}
    if not seal:
        report["errors"].append("无 seal 记录，无法重放")
        return report

    report["seal_errors"] = verify_seal(run_dir, manifest)
    dataset = dataset_path or str((run_dir / seal.get("dataset_relpath", "dataset.json")).resolve())
    argv = [str(item) for item in (seal.get("generation_argv") or [])]
    generation_command = str(seal.get("generation_command") or "")
    if not argv:
        report["errors"].append("seal 中没有 generation_argv，无法安全重放（拒绝按空格拆分命令行）"
                                f"；command={generation_command[:120]}")
        return report

    with tempfile.TemporaryDirectory(prefix="travel-scope-replay-") as scratch:
        replay_dir = Path(scratch) / "outputs"
        replay_dir.mkdir(parents=True)
        parts = [sys.executable] + argv
        # Rewrite the recorded command so it renders into the scratch directory,
        # reading the sealed dataset and every other flag unchanged.
        engine = Path(parts[1]).resolve() if len(parts) > 1 else None
        if engine is None or not engine.is_file():
            report["errors"].append(f"封存里的生成脚本不可用: {parts[1] if len(parts) > 1 else '(空)'}")
            return report
        if engine.parent.parent != skill_root:
            report["errors"].append(
                f"重放被拒绝：seal 由 {engine.parent.parent.name} 生成，当前发布版本是 {skill_root.name}；"
                "跨版本重放不构成对当前产物的证明"
            )
            return report
        for index, token in enumerate(parts):
            if token == "--output-dir":
                parts[index + 1] = str(replay_dir)
        env = dict(os.environ)
        env[REPLAY_ENV] = "1"
        env["TRAVEL_SCOPE_SEAL_SEALED_AT"] = str(seal.get("sealed_at") or "")
        env["TRAVEL_SCOPE_RUN_MANIFEST"] = str(run_dir / "manifest.json")
        completed = subprocess.run(pyc.interpreter(parts), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", cwd=str(run_dir),
                                   env=pyc.env(env), timeout=timeout)
        report["generator_exit"] = completed.returncode
        if completed.returncode != 0:
            report["errors"].append("重放生成失败: " + (completed.stdout.strip() or completed.stderr.strip())[-800:])
            return report
        expected = seal.get("build") or {}
        for name, digest in expected.items():
            produced = replay_dir / Path(name).name
            if not produced.is_file():
                produced = min(replay_dir.glob(f"*{Path(name).name}"), key=lambda p: len(p.name), default=None)
            if produced is None or not produced.is_file():
                report["mismatches"].append(f"{name}: 重放未产出同名文件")
                continue
            actual = file_sha256(produced)
            if actual != digest:
                report["mismatches"].append(f"{name}: 重放产物 {actual[:12]} != 封存 {digest[:12]}")
        report["replayed_dataset_sha256"] = file_sha256(Path(dataset))
        report["dataset_matches_seal"] = report["replayed_dataset_sha256"] == seal.get("input_sha256")
    report["replay_clean"] = not report["mismatches"] and not report.get("seal_errors") and not report["errors"]
    return report


if __name__ == "__main__":
    print(__doc__)
