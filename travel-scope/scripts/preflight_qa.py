"""Interactive, low-cost technical preflight for Travel-Scope v4.0.5.

This asks for planning choices only. It never asks for or prints API keys and
does not make network requests. The selected values can be saved beside a run
and reviewed before expensive research begins.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from intake_contract import load_policy, validate_intake

REQUIRED_INTAKE = {question["id"] for question in load_policy()["questions"]}


def validate_values(values: dict) -> None:
    required = {"mode", "branch", "map_mode", "route_granularity", "scope_review", "intake"}
    missing = sorted(required - set(values))
    if missing:
        raise ValueError(f"前置 QA 缺少字段: {missing}")
    intake = values.get("intake") or {}
    missing_intake = sorted(key for key in REQUIRED_INTAKE if not str(intake.get(key, "")).strip())
    if missing_intake:
        raise ValueError(f"前置 QA 缺少 Q0-Q8 原始需求: {missing_intake}")
    validate_intake(intake)
    if values.get("mode") not in {"1", "2"} or values.get("scope_review") not in {"1", "2"}:
        raise ValueError("前置 QA 的运行模式或范围确认值无效")


def ask(label: str, choices: list[tuple[str, str]], default: str, *, use_defaults: bool) -> str:
    print(f"\n{label}")
    for key, text in choices:
        print(f"  {key}. {text}")
    if use_defaults:
        print(f"选择 [{default}]：{default}")
        return default
    while True:
        value = input(f"选择 [{default}]：").strip() or default
        if value in {key for key, _ in choices}:
            return value
        print("请输入列表中的选项。")


def main() -> int:
    parser = argparse.ArgumentParser(description="Travel-Scope interactive preflight QA")
    parser.add_argument("--output", required=False, default="", help="JSON file to save the selected preflight values")
    parser.add_argument("--defaults", action="store_true", help="Use safe defaults without prompting")
    parser.add_argument("--validate", default="", help="Validate an existing preflight JSON without prompting")
    parser.add_argument("--intake", default="", help="Q0-Q8 intake JSON to embed without re-asking the route choice")
    args = parser.parse_args()

    if args.validate:
        values = json.loads(Path(args.validate).read_text(encoding="utf-8"))
        try:
            validate_values(values)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps({"status": "PASS", "preflight": args.validate}, ensure_ascii=False))
        return 0
    if not args.output:
        parser.error("--output is required unless --validate is used")
    if not args.intake:
        parser.error("--intake is required; Q0-Q8 must be captured once before technical preflight")
    intake = json.loads(Path(args.intake).read_text(encoding="utf-8"))
    missing_intake = sorted(key for key in REQUIRED_INTAKE if not str(intake.get(key, "")).strip())
    if missing_intake:
        parser.error(f"--intake missing Q0-Q8 fields: {missing_intake}")
    try:
        validate_intake(intake)
    except ValueError as exc:
        parser.error(str(exc))

    live_credentials = {
        "TRAVEL_SCOPE_AMAP_KEY": bool(os.environ.get("TRAVEL_SCOPE_AMAP_KEY", "").strip()),
        "TRAVEL_SCOPE_BAIDU_KEY": bool(os.environ.get("TRAVEL_SCOPE_BAIDU_KEY", "").strip()),
        "TRAVEL_SCOPE_GOOGLE_PLACES_KEY": bool(os.environ.get("TRAVEL_SCOPE_GOOGLE_PLACES_KEY", "").strip()),
    }
    print("\n运行前凭证说明（只显示是否存在，不显示 Key 内容）")
    print("  Live 真实数据研究与普通网页地图跳转：不需要 Key")
    print("  实时地图增强或经明确授权的供应商 API：才需要相应 Key 和调用台账")
    print("  Demo：不需要 Key，但不得因缺少 Key 自动切换为 Demo")
    available = [name for name, present in live_credentials.items() if present]
    default_mode = "1"

    values = {
        "schema_version": 1,
        "mode": ask("运行模式", [("1", "Live（真实数据）"), ("2", "Demo（脱敏离线演示）")], default_mode, use_defaults=args.defaults),
        "branch": ask("目的地分支", [("1", "自动识别国内/海外"), ("2", "国内：高德/百度网页跳转"), ("3", "海外：Google Maps/Apple Maps 网页跳转")], "1", use_defaults=args.defaults),
        "map_mode": ask("基础地图模式", [("1", "普通网页跳转 + 本地路线示意"), ("2", "启用实时地图增强（需要后续显式提供 Key）")], "1", use_defaults=args.defaults),
        "route_granularity": ask("路线粒度", [("1", "每天一个主要目的地/大区域"), ("2", "仅保留路线节点，不生成日内多点地图连线")], "1", use_defaults=args.defaults),
        "scope_review": ask("范围确认", [("1", "先做国家/区域发现和经典走廊审计"), ("2", "用户已明确限定范围，按限定范围执行")], "1", use_defaults=args.defaults),
        "intake": intake,
    }
    values["live_map_enabled"] = values["map_mode"] == "2"
    values["ordinary_web_navigation"] = True
    values["created_by"] = "travel-scope-v4.0.5-preflight"
    values["available_credentials"] = available

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n已保存前置 QA：", output)
    print(json.dumps(values, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
