# -*- coding: utf-8 -*-
"""v4.2.2 V5-B — 汇率契约的唯一登记处（V0-L05）。

V0 记的是「PH run 缺 budget_meta.rates.USD，SPA 无汇率可换算」。现场比这更糟：

* `assets/spa-layout.js` 里写着 `return 7.15`（USD 兜底）和 `return 0.125`（PHP 兜底），
  注释还写着「确保英文模式永远不输出半成品未核验免责声明」——也就是**故意**让页面在
  没有任何登记汇率时也给出一个 `$` 数字；
* `scripts/gen_travel_scope.py` 在 budget_meta 缺失或没有 USD 时直接注入 `{"USD": 0.14}`，
  并同时写 `rate_verified: True`、`rate_date: "2026-10"`——一个没有来源的数字被标成「已核验」
  写进 dataset，再被封存成 run 的事实。

英文模式读者看到的 `$3,597` 全部来自这两个常数。这不是换算缺数据，是**编数据被当成核验**。

本模块把规则收回单一登记处：

1. `rate_status` 只有 `VERIFIED` / `UNREGISTERED` 两种；判 VERIFIED 必须同时给
   `rates` + `rate_source` + `rate_date`，缺一就按 UNREGISTERED 报错，不自称已核验。
2. 换算因子一律从登记数值推导（`factor = rates[to] / rates[from]`），代码里不得留任何数字兜底；
   拿不到因子就是 null，UI 必须显示原币种并挂上「汇率未登记」提示。
3. 读者载荷只投影 `budget_fx`（状态、因子、提示文案），JS 不再自己写文案，也不再做币种判断
   ——与 §9「渲染层不得维护第二套规则」同一条纪律。
4. `banned_fallback_literals()` 把「不许再塞常数」变成可检查的事实：门禁和测试都按它扫产物 JS。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_FILE = ROOT / "references" / "budget-policy.json"
SPA_JS = ROOT / "assets" / "spa-layout.js"
GEN_PY = ROOT / "scripts" / "gen_travel_scope.py"

REQUIRED_SECTIONS = ("policy_version", "contract_ref", "rate_status", "currency_units",
                     "derivation_rule", "ui", "reason_codes", "non_goals")
STATUS_KEY = "rate_status"
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class BudgetPolicyError(ValueError):
    """登记文件自己不合法时直接报错——和 map-link-selection 一样的纪律。"""


def load_policy(path: Path | None = None) -> dict:
    policy = json.loads((path or POLICY_FILE).read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise BudgetPolicyError("budget-policy.json 必须是对象")
    missing = [key for key in REQUIRED_SECTIONS if key not in policy]
    if missing:
        raise BudgetPolicyError("budget-policy.json 缺少段落：%s" % ", ".join(missing))
    status = policy[STATUS_KEY]
    allowed = status.get("allowed")
    if allowed != ["VERIFIED", "UNREGISTERED"]:
        raise BudgetPolicyError("rate_status.allowed 必须恰好是 [\"VERIFIED\", \"UNREGISTERED\"]，收到 %r"
                                % (allowed,))
    if status.get("default_when_absent") not in allowed:
        raise BudgetPolicyError("rate_status.default_when_absent 必须在 allowed 内")
    requires = status.get("verified_requires")
    if not isinstance(requires, list) or not requires:
        raise BudgetPolicyError("rate_status.verified_requires 必须是非空列表：VERIFIED 不能自我声明")
    for field in ("rate_source", "rate_date"):
        if field not in requires:
            raise BudgetPolicyError("verified_requires 必须包含 %s，否则「已核验」没有出处" % field)
    banned = policy["derivation_rule"].get("banned_fallbacks")
    if not isinstance(banned, list) or not banned:
        raise BudgetPolicyError("derivation_rule.banned_fallbacks 必须非空：兜底常数是本项契约的起因")
    ui = policy["ui"]
    for key in ("state_attribute", "notice_unregistered", "notice_verified_prefix", "reader_payload"):
        if key not in ui:
            raise BudgetPolicyError("budget-policy.json::ui 缺少 %s" % key)
    for key in ("notice_unregistered", "notice_verified_prefix"):
        copy = ui[key]
        if not (isinstance(copy, dict) and copy.get("cn") and copy.get("en")):
            raise BudgetPolicyError("ui.%s 必须同时给出 cn 与 en" % key)
        if CJK_RE.search(copy["en"]):
            raise BudgetPolicyError("ui.%s 的 en 文案含汉字：读者英文态会看到中英混排" % key)
    return policy


def _positive(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


def declared_status(budget: dict, policy: dict) -> tuple[str, list[str]]:
    """返回 (状态,  reasons)；reasons 是登记过的 code，不夹自由文本。"""
    codes: list[str] = []
    if not isinstance(budget, dict) or not budget:
        return "UNREGISTERED", ["FX_BUDGET_META_MISSING"]
    status = budget.get("rate_status")
    if status is None:
        codes.append("FX_RATE_STATUS_MISSING")
        status = policy[STATUS_KEY]["default_when_absent"]
    elif status not in policy[STATUS_KEY]["allowed"]:
        codes.append("FX_RATE_STATUS_UNKNOWN")
        status = "UNREGISTERED"
    rates = budget.get("rates") if isinstance(budget.get("rates"), dict) else {}
    if status == "VERIFIED":
        requires = policy[STATUS_KEY]["verified_requires"]
        problems = []
        if "rates" in requires and not any(_positive(v) for v in rates.values()):
            problems.append("FX_VERIFIED_WITHOUT_USABLE_RATE")
        if "rate_source" in requires and not str(budget.get("rate_source") or "").strip():
            problems.append("FX_VERIFIED_WITHOUT_PROVENANCE")
        if "rate_date" in requires and not str(budget.get("rate_date") or "").strip():
            problems.append("FX_VERIFIED_WITHOUT_PROVENANCE")
        codes += problems
        if problems:
            status = "UNREGISTERED"   # 自称已核验却给不出出处：按未登记处理，并如实报错
    elif any(_positive(v) for v in rates.values()):
        # 自称未登记却仍留着数值：UI 迟早会用它换算，状态与数据互相打脸。
        codes.append("FX_UNREGISTERED_WITH_RATES")
    if budget.get("rate_verified") is True and status != "VERIFIED":
        # 旧形状的「已核验」布尔：没有 rate_source 的 self-claim，正是 V0-L05 的根。
        codes.append("FX_LEGACY_RATE_CLAIM")
    return status, codes


def factor(rates: dict, base_currency: str, from_ccy: str, to_ccy: str) -> float | None:
    """1 单位 from_ccy = ? to_ccy；只从登记数值推导，拿不到就是 None（绝不兜底）。"""
    if not isinstance(rates, dict):
        return None

    def value(ccy: str):
        if ccy not in rates:
            # 只有「这个键根本没登记」时才用基准货币恒为 1 的语义补位；
            # 键在场但值是 0／负数／字符串，是登记错了，不得被静默修成一个能换算的数。
            return 1.0 if ccy == base_currency else None
        return _positive(rates.get(ccy))

    src, dst = value(from_ccy), value(to_ccy)
    if src is None or dst is None or src <= 0:
        return None
    return dst / src


def reader_projection(budget: dict, policy: dict | None = None) -> dict:
    """投影进读者载荷的唯一形状；JS 只读它，不再自己判断币种与文案。"""
    policy = policy or load_policy()
    status, codes = declared_status(budget if isinstance(budget, dict) else {}, policy)
    ui = policy["ui"]
    rates = budget.get("rates") if isinstance(budget, dict) and isinstance(budget.get("rates"), dict) else {}
    base = str((budget or {}).get("base_currency") or "") if isinstance(budget, dict) else ""
    projection = {
        "policy_version": policy["policy_version"],
        "rate_status": status,
        "state_attribute": ui["state_attribute"],
        "notice_unregistered": dict(ui["notice_unregistered"]),
        "notice_verified_prefix": dict(ui["notice_verified_prefix"]),
        "currency_units": dict(policy["currency_units"]),
        "factors": {},
        "rate_source": "",
        "rate_date": "",
        "declined_codes": codes,
    }
    if status == "VERIFIED":
        cny_usd = factor(rates, base, "CNY", "USD")
        php_cny = factor(rates, base, "PHP", "CNY")
        if cny_usd:
            projection["factors"]["CNY_USD"] = cny_usd
        if php_cny:
            projection["factors"]["PHP_CNY"] = php_cny
        projection["rate_source"] = str(budget.get("rate_source") or "")
        projection["rate_date"] = str(budget.get("rate_date") or "")
    return projection


def findings(budget: dict, policy: dict | None = None) -> list[str]:
    """dataset 侧的登记问题；全部 blocking（钱上的字不能「暴露」了继续发）。"""
    policy = policy or load_policy()
    _status, codes = declared_status(budget if isinstance(budget, dict) else {}, policy)
    return sorted(set(codes))


def banned_fallback_literals(policy: dict | None = None) -> list[str]:
    policy = policy or load_policy()
    return list(policy["derivation_rule"]["banned_fallbacks"])


def _code_lines(source: str) -> str:
    """只留下可能被执行的那几行。

    注释里写「旧实现曾在此 return 7.15」是交代缺陷史，不是重新埋一个兜底；可执行行里出现
    同一个常数才是违约。所以这里只跳「行首注释」，不做花哨的字符串识别——宁可漏一行藏在
    行尾注释里的数字，也不把扫描器复杂化到没人敢改。测试用真兜底行证明这条过滤没磨平牙齿。
    """
    kept = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("//", "#", "*", "/*", '"""')):
            continue
        kept.append(line)
    return "\n".join(kept)


def _literal_hits(source: str, literals) -> list[str]:
    code = _code_lines(source)
    hits = []
    for literal in literals:
        escaped = re.escape(literal)
        patterns = (r"return\s+%s\b" % escaped,          # JS 兜底：return 7.15
                    r"[:=]\s*%s\b" % escaped,            # 常量赋值/字典值："USD": 0.14
                    r"\b%s\s*[;)]" % escaped,            # 裸数字参与表达式后被丢弃
                    r"[\"']%s[\"']\s*:" % escaped)       # 字符串形态的键
        if any(re.search(pattern, code) for pattern in patterns):
            hits.append(literal)
    return hits


def artifact_findings(root: Path | None = None, policy: dict | None = None) -> list[str]:
    """扫描发布产物：兜底常数一旦回到 JS 或生成器，就是契约被改回去的证据。"""
    root = Path(root or ROOT)
    policy = policy or load_policy()
    literals = banned_fallback_literals(policy)
    out = []
    for path, label in ((root / "assets" / "spa-layout.js", "assets/spa-layout.js"),
                        (root / "scripts" / "gen_travel_scope.py", "scripts/gen_travel_scope.py")):
        if not path.is_file():
            out.append("FX_FALLBACK_LITERAL_IN_ASSET|%s 不存在，无法证明没有兜底常数" % label)
            continue
        hits = _literal_hits(path.read_text(encoding="utf-8"), literals)
        if hits:
            out.append("FX_FALLBACK_LITERAL_IN_ASSET|%s 重新出现了兜底汇率常数：%s "
                       "（缺登记必须显示原币种，不许补一个看起来合理的数字）"
                       % (label, ", ".join(hits)))
    return out


def findings_for(dataset: dict, root: Path | None = None, policy: dict | None = None) -> list[str]:
    """门禁入口：dataset 声明问题 + 发布产物兜底扫描，一次给全。"""
    policy = policy or load_policy()
    budget = dataset.get("budget_meta") if isinstance(dataset, dict) else None
    return sorted(set(findings(budget, policy)) | set(artifact_findings(root, policy)))


if __name__ == "__main__":  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(description="复算一个 dataset 的汇率登记状态")
    ap.add_argument("--dataset", required=True)
    args = ap.parse_args()
    data = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    print(json.dumps({"findings": findings_for(data),
                      "projection": reader_projection(data.get("budget_meta") or {})},
                     ensure_ascii=False, indent=2))
