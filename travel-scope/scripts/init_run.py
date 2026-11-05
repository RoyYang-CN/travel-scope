#!/usr/bin/env python3
"""Travel-Scope 运行环境安全初始化脚本 (v5.0.0)
用途: 按照规范自动化创建新的运行目录，严禁手动复制造成历史版本/交付证据残留串版。
"""

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


def _current_version() -> str:
    origin = Path(__file__).resolve().parents[1] / "product-origin.json"
    data = json.loads(origin.read_text(encoding="utf-8"))
    version = str(data.get("version") or "").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"product-origin.json 缺少有效版本号: {version or '空'}")
    return version


def _validate_artifact_slug(value: str) -> str:
    slug = str(value or "").strip()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError("artifact_slug 必须是 ASCII lowercase kebab-case")
    return slug


def _expected_artifacts(country: str, artifact_slug: str, delivery_profile: str) -> list[str]:
    spa = f"{artifact_slug}-travel-guide.html"
    research = f"{artifact_slug}-travel-research.xlsx"
    if delivery_profile == "reader":
        return [spa]
    if delivery_profile == "review":
        return [spa, research]
    return [
        spa,
        research,
        f"{country}旅行攻略-地图标记.html",
        f"{country}旅行攻略-地图标记-en.html",
        f"{country}旅行攻略-双语.html",
        f"{country}旅行攻略大全.xlsx",
        f"{country}旅行攻略大全-en.xlsx",
        f"{country}旅行攻略大全.md",
        f"{country}旅行攻略大全-en.md",
    ]


def init_run(
    country: str,
    run_id: str,
    runs_dir: Path,
    *,
    artifact_slug: str,
    delivery_profile: str = "reader",
    template_data_path: Path | None = None,
):
    artifact_slug = _validate_artifact_slug(artifact_slug)
    if delivery_profile not in {"reader", "review", "full_audit"}:
        raise ValueError(f"未知 delivery_profile: {delivery_profile}")
    run_dir = runs_dir / run_id
    if run_dir.exists():
        raise FileExistsError(f"Run directory already exists: {run_dir}")

    # 1. 建立基础目录结构
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence").mkdir(exist_ok=True)
    (run_dir / "outputs").mkdir(exist_ok=True)
    (run_dir / "assets").mkdir(exist_ok=True)
    (run_dir / "assets" / "editorial").mkdir(exist_ok=True)
    (run_dir / "assets" / "section").mkdir(exist_ok=True)

    # 2. 生成规范的 manifest.json (干净版本，无历史命令残留)
    #    版本从 product-origin.json 读取，避免硬编码旧版本；created_at 用真实时间，避免串版。
    version = _current_version()
    manifest = {
        "run_id": run_id,
        "country": country,
        "skill_version": version,
        "target_version": version,
        "delivery_profile": delivery_profile,
        "artifact_slug": artifact_slug,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "intake": {
            "q0_destination": country,
            "q1_mode": "free_travel",
            "q2_days": 12,
            "q7_depth": "deep"
        },
        "generation_command": (
            f"python travel-scope-v{version}/travel-scope/scripts/gen_travel_scope.py "
            f"--mode live --data {run_dir}/dataset.json --output-dir {run_dir}/outputs "
            f"--map-platform google --language both --country {country} --expected-days 12 "
            f"--delivery-profile {delivery_profile} --artifact-slug {artifact_slug}"
        ),
        "artifacts_expected": _expected_artifacts(country, artifact_slug, delivery_profile),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3. 如果提供了模板数据，干净复制并重置证据
    if template_data_path and template_data_path.exists():
        shutil.copy2(template_data_path, run_dir / "dataset.json")
        print(f"Copied dataset template from {template_data_path}")
        
        # 复制 assets
        src_assets = template_data_path.parent / "assets"
        if src_assets.exists():
            for item in src_assets.glob("**/*"):
                if item.is_file():
                    rel = item.relative_to(src_assets)
                    dest_f = run_dir / "assets" / rel
                    dest_f.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_f)
            print("Copied assets pool successfully.")

    print(f"Successfully initialized clean run directory for v{version}: {run_dir}")
    return run_dir

def main():
    parser = argparse.ArgumentParser(description="Initialize clean Travel-Scope run directory.")
    parser.add_argument("--country", required=True, help="Target country (e.g. philippines, indonesia)")
    parser.add_argument("--run-id", required=True, help="Unique run ID (e.g. travel_scope_run_202702_philippines_v414_001)")
    parser.add_argument("--artifact-slug", required=True, help="ASCII lowercase kebab-case delivery filename prefix")
    parser.add_argument("--delivery-profile", default="reader", choices=["reader", "review", "full_audit"])
    parser.add_argument(
        "--runs-dir",
        default=None,
        help="Base runs directory (default: ./runs under the current working directory)",
    )
    parser.add_argument("--template-dataset", default=None, help="Optional path to dataset.json template")
    args = parser.parse_args()

    template_path = Path(args.template_dataset) if args.template_dataset else None
    init_run(
        args.country,
        args.run_id,
        Path(args.runs_dir) if args.runs_dir else Path.cwd() / "runs",
        artifact_slug=args.artifact_slug,
        delivery_profile=args.delivery_profile,
        template_data_path=template_path,
    )

if __name__ == "__main__":
    main()
