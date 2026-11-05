"""Render and validate the Travel-Scope Q0-Q8 conversational intake contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import re

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "references" / "intake-policy.json"


def load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def parse_custom_budget_range(value: str) -> tuple[int | None, int | None] | None:
    """Parse custom budget range like '¥500-1000/晚', '350~900', '每晚不超过800元', '800以上'."""
    text = str(value or "").strip()
    if not text:
        return None
    # Match range pattern like 350-900, 350~900, 350至900, 350到900
    m_range = re.search(r"(?:[¥￥$])?\s*(\d{2,6})\s*(?:[-~～—至到]|\s+to\s+)\s*(?:[¥￥$])?\s*(\d{2,6})", text)
    if m_range:
        low, high = int(m_range.group(1)), int(m_range.group(2))
        return (min(low, high), max(low, high))
    # Match upper limit pattern like 不超过800, 800以下, 800以内
    m_max = re.search(r"(?:不超过|小于|以下|以内)\s*(?:[¥￥$])?\s*(\d{2,6})|(?:[¥￥$])?\s*(\d{2,6})\s*(?:以下|以内)", text)
    if m_max:
        val = int(m_max.group(1) or m_max.group(2))
        return (0, val)
    # Match lower limit pattern like 超过800, 大于800, 800以上, 800起
    m_min = re.search(r"(?:超过|大于|起码|至少)\s*(?:[¥￥$])?\s*(\d{2,6})|(?:[¥￥$])?\s*(\d{2,6})\s*(?:以上|起)", text)
    if m_min:
        val = int(m_min.group(1) or m_min.group(2))
        return (val, None)
    return None


def render_questionnaire(known: dict | None = None) -> str:
    known = known or {}
    lines = ["请确认或补充本次行程的规划参数："]
    for question in load_policy()["questions"]:
        value = str(known.get(question["id"], "")).strip()
        if value:
            prompt = value
        elif question["kind"] == "choice":
            opt_strs = []
            for option in question["options"]:
                label = option["cn"]
                if "price_range_cn" in option:
                    label += f"（{option['price_range_cn']}）"
                opt_strs.append(label)
            prompt = " / ".join(opt_strs)
            if question.get("allow_custom_range"):
                prompt += "（支持直接输入自定义区间如 ¥500-900/晚）"
        else:
            prompt = question["hint_cn"]
        lines.append(f"- {question['number']}【{question['label_cn']}】：{prompt}")
    return "\n".join(lines)


def _matches_choice(value: str, question: dict) -> bool:
    candidate = value.strip().casefold()
    for option in question["options"]:
        for alias in (option["value"], option["cn"], *option.get("aliases", [])):
            normalized = str(alias).strip().casefold()
            if candidate == normalized:
                return True
            if question.get("allow_detail_suffix") and candidate.startswith(normalized):
                suffix = candidate[len(normalized):].lstrip()
                if suffix.startswith(("（", "(", "[", "【", "-", "—")):
                    return True
    if question.get("allow_custom_range") and parse_custom_budget_range(value):
        return True
    return False


def validate_intake(intake: dict) -> None:
    # V4.0.9: Normalize nested intake if caller provided {"intake": {...}}
    if isinstance(intake.get("intake"), dict):
        merged = dict(intake["intake"])
        for k, v in intake.items():
            if k != "intake" and k not in merged:
                merged[k] = v
        intake = merged

    errors = []
    for question in load_policy()["questions"]:
        value = str(intake.get(question["id"], "")).strip()
        if not value:
            errors.append(f"{question['number']} 缺少回答")
        elif question["kind"] == "choice" and not _matches_choice(value, question):
            allowed = " / ".join(option["cn"] for option in question["options"])
            errors.append(f"{question['number']} 选项无效，应为：{allowed}")
    if errors:
        raise ValueError("；".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description="Render or validate the Travel-Scope Q0-Q8 intake")
    parser.add_argument("--known", default="", help="Optional JSON containing already-known Q0-Q8 values")
    parser.add_argument("--validate", action="store_true", help="Validate the JSON instead of rendering the questionnaire")
    args = parser.parse_args()
    known = json.loads(Path(args.known).read_text(encoding="utf-8")) if args.known else {}
    if args.validate:
        validate_intake(known)
        print(json.dumps({"status": "PASS"}, ensure_ascii=False))
    else:
        print(render_questionnaire(known))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
