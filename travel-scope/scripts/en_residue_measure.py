# -*- coding: utf-8 -*-
"""v4.2.2 V5-C — 英文模式汉字残留的唯一可复现口径（V0-L06）。

v4.2.1 同时留着两个数字：§3.2.5 记 7.5%，§16.2 第 5 条记 2/7080（0.03%）。
复算后发现差异不止来自取样范围——发布树里有**四处**各算各的 CJK 计数：

* `visual_qa` 用 `len(re.findall([\\u4e00-\\u9fff], body))` 算 CN 态基线；
* `visual_qa` 又用同一行正则算 EN 态残留，分母是 `max(1, len(en_body))`；
* `delivery_gate._check_english_text` 自己算一份（分母 `max(1, len(text))`，还要 `cjk>5` 才报）；
* `delivery_gate._check_spa_english_mode` 再算一份（`SPA_CJK_RE`）。

四处都**没有排除语言切换按钮上那颗刻意保留的「中文」**。所以加州成品英文态实测
`cjk=2` 其实就是这两个字——按现行阈值它会算成 0.13% 的「残留」，而真正该被抓到的缺口
反而被噪声盖住。数字打架不是因为产物变了，是因为口径本来就有好几套。

本模块只定义一件事：**给定一段读者可见文本，怎么数汉字**。
判定阈值仍归 run-quality-policy.json，报错与否仍归门禁——口径与裁决分开，
但口径这一层从此只有一份实现（测试会扫发布树，禁止再出现第二份计数）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "references" / "run-quality-policy.json"

# 汉字（表意文字）：基本区 + 扩展 A + 兼容区。
CJK_IDEOGRAPHS = "\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff"
CJK_IDEOGRAPH_RE = re.compile("[" + CJK_IDEOGRAPHS + "]")
# 中文标点（、。「」）与全角符号不计入残留：它们是排版，不是「没翻译的正文」。
# 这条排除是显式的，并且单独计数，避免「排除了就不看得见」。
FULLWIDTH_PUNCTUATION = "\u3000-\u303f\uff00-\uffef"
FULLWIDTH_RE = re.compile("[" + FULLWIDTH_PUNCTUATION + "]")

# 给浏览器用的同一字类（JS 转义形式，源码里可读）。
# 下面那条自检保证它和 Python 字类**认的是同一批字符**：新增/删改范围时只能改一处，
# 另一处不跟着改就 import 失败——V5-C 的起因就是同一件事在四处各写了一套。
CJK_CLASS_JS = "\\u4e00-\\u9fff\\u3400-\\u4dbf\\uf900-\\ufaff"
_PROBE = ["一", "鿀", "㐀", "䶿", "豈", "﫿", "文", "龦", "a", "中", "鿿", "\u3400", "\u4dc0",
          "\u3002", "，"]


def _js_class_matches() -> bool:
    """把 JS 转义串还原成真实字符类，与 Python 类逐字符比对。"""
    js_range_chars = CJK_CLASS_JS.encode("utf-8").decode("unicode_escape")
    js_re = re.compile("[" + js_range_chars + "]")
    return all(bool(js_re.search(ch)) == bool(CJK_IDEOGRAPH_RE.search(ch)) for ch in _PROBE)


if not _js_class_matches():
    raise ValueError("CJK_CLASS_JS 与 CJK_IDEOGRAPH_RE 认的不是同一批字符：口径又分成两套了")


def load_definition(policy: dict | None = None) -> dict:
    policy = policy or json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    definition = policy.get("english_residue_measurement")
    if not isinstance(definition, dict):
        raise ValueError("run-quality-policy.json 缺少 english_residue_measurement 段："
                         "没有登记口径，任何汉字数字都不可复现")
    for key in ("scope", "counts_as_residue", "excluded_from_residue", "denominator",
                "intentional_cjk", "authoritative"):
        if key not in definition:
            raise ValueError("english_residue_measurement 缺少字段 %s" % key)
    if definition["authoritative"] is not True:
        raise ValueError("english_residue_measurement.authoritative 必须为 true，否则本模块不是唯一口径")
    # 登记处写的是 JSON 里的转义形式（人读得懂），比较前还原成真实字符；
    # 用相等而不是包含，避免「多登记了一段范围却没人发现」。
    registered = definition["counts_as_residue"].encode("utf-8").decode("unicode_escape")
    if registered != CJK_IDEOGRAPHS:
        raise ValueError("登记的字类 %r 与本模块实现 %r 不一致：改口径必须同时改代码与登记"
                         % (registered, CJK_IDEOGRAPHS))
    return definition


def intentional_spans(text: str, definition: dict) -> list[tuple[int, int, str]]:
    """刻意为之的汉字（语言切换标签等）：命中位置全部列出，不静默扣除。"""
    spans = []
    for token in definition["intentional_cjk"]:
        start = text.find(token)
        while start != -1:
            spans.append((start, start + len(token), token))
            start = text.find(token, start + 1)
    return spans


def measure(text: str, policy: dict | None = None) -> dict:
    """唯一的计数口径：raw → 扣除刻意项 → 残留；分母与逐槽定位一并给出。"""
    definition = load_definition(policy)
    text = text or ""
    covered = set()
    for start, end, _token in intentional_spans(text, definition):
        covered.update(range(start, end))
    raw_cjk = len(CJK_IDEOGRAPH_RE.findall(text))
    intentional_cjk = len([i for i, ch in enumerate(text)
                           if CJK_IDEOGRAPH_RE.match(ch) and i in covered])
    leaked_cjk = raw_cjk - intentional_cjk
    chars = len(text)
    # 全角/中文标点单独计数：它们不算残留，但也不能因为「不算」就从报告里消失。
    punctuation = len(FULLWIDTH_RE.findall(text))
    return {
        "scope": definition["scope"],
        "chars": chars,
        "raw_cjk": raw_cjk,
        "intentional_cjk": intentional_cjk,
        "intentional_tokens": sorted({token for _s, _e, token in
                                      intentional_spans(text, definition)}),
        "leaked_cjk": leaked_cjk,
        "ratio": (leaked_cjk / chars) if chars else 0.0,
        "ratio_unadjusted": (raw_cjk / chars) if chars else 0.0,
        "fullwidth_punctuation": punctuation,
        "leaked_samples": _leaked_samples(text, covered),
        "definition": definition,
    }


def _leaked_samples(text: str, covered: set) -> list[str]:
    """定位样本：同一处汉字只报一个窗口，否则「酒店」会变成两条几乎一样的串。"""
    out: list[str] = []
    claimed = set()
    for index, ch in enumerate(text):
        if not CJK_IDEOGRAPH_RE.match(ch) or index in covered or index in claimed:
            continue
        window = text[max(0, index - 8):index + 9]
        out.append(window)
        claimed.update(range(max(0, index - 8), min(len(text), index + 9)))
        if len(out) >= 8:
            break
    return out


def contains_cjk(text: str) -> bool:
    """逐元素判定也走同一字类：poi-sub / day summary / title 不得各写一份正则。"""
    return bool(CJK_IDEOGRAPH_RE.search(text or ""))


def verdict(measured: dict, policy: dict | None = None) -> dict:
    """口径在这里结束，判定交回门禁：本函数只复述登记阈值，不改规则。"""
    policy = policy or json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    rules = policy.get("translation_rules", {})
    limit = rules.get("max_cjk_ratio_in_english_artifacts")
    floor = rules.get("min_leaked_cjk_to_report", 1)
    if limit is None:
        raise ValueError("translation_rules.max_cjk_ratio_in_english_artifacts 未登记")
    leaked = measured["leaked_cjk"]
    breach = leaked >= floor and measured["ratio"] > limit
    return {"limit": limit, "floor": floor, "breach": breach,
            "basis": "leaked_cjk（已扣除登记的刻意汉字）/ chars",
            "ratio": round(measured["ratio"], 6),
            "ratio_unadjusted": round(measured["ratio_unadjusted"], 6)}


if __name__ == "__main__":  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(description="按唯一口径测量一段英文可见文本")
    ap.add_argument("--text-file", required=True)
    args = ap.parse_args()
    body = Path(args.text_file).read_text(encoding="utf-8", errors="replace")
    printed = measure(body)
    printed["verdict"] = verdict(printed)
    printed.pop("definition")
    print(json.dumps(printed, ensure_ascii=False, indent=2))
