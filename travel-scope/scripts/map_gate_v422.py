# -*- coding: utf-8 -*-
"""v4.2.2 V4 — 地图发布门禁（严重性分类 + §8.1/§8.2 一致性 + 零调用账本）。

分工只有一条：**校验器说事实，门禁说严重性**。
`data_model.validate_map_targets` 继续负责发现哪条声明没有依据；本模块负责回答
「这件事是该整批阻断，还是该逐项暴露」。§8.3 的边界写死在
`references/map-gate-v422.json`，且名单由 AST 现场解析比对得出——校验器新增一个 code
而没在这里登记严重性，`load_gate()` 直接报错，不会悄悄落进第三类。

零调用四项（billable calls / keys used / scrape attempts / paid fallback）只能来自
`zero_call_sentinel` 的执行期账本；哨兵没装齐时本模块拒绝输出 0（§11 V4 明令不得只扫源码）。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_FILE = ROOT / "references" / "map-gate-v422.json"

try:  # v4.2.2 V5-A：落盘的门禁报告必须带产出者身份（V0-L17）
    import gate_producer
except ImportError:  # pragma: no cover
    import scripts.gate_producer as gate_producer

PRODUCING_CODE = ("scripts/map_gate_v422.py", "scripts/gate_producer.py", "scripts/data_model.py",
                  "scripts/map_link_selector.py")
PRODUCING_CONFIG = ("references/map-gate-v422.json", "references/map-link-selection.json",
                    "references/data-model.json")
FIELDS_TOKEN = re.compile(r"\|fields=([A-Za-z0-9_,]*)")
# 「这一格不存在」的哨兵：alias 指纹要把 absent 与 present-but-empty 分成两种状态，
# 所以不能再用 `x or ""` 把 None / {} / [] / "" 全折成同一个空串。
_ABSENT = object()

REQUIRED_GATE_KEYS = [
    "gate_version", "contract_ref", "severity", "classification", "hard_conflict_invariants",
    "zero_call_gate", "consistency_checks", "reporting",
]
VALID_SEVERITIES = ("blocking", "exposed")
# §11 V4 逐字点名的四项零调用指标。名单在登记文件里，但「必须有这四项」是合同条款，
# 写在代码里才拦得住「把 required_metrics 删短一项就当门通过了」这条路径。
CONTRACT_ZERO_CALL_METRICS = ("google_billable_api_calls", "google_api_keys_used",
                              "google_maps_scrape_attempts", "paid_fallback_attempts")
CONTRACT_HOST_BUCKETS = ("billable_hosts", "scrape_hosts", "paid_fallback_hosts",
                         "loopback_hosts")
# 第五道牙：真正想离开本机的尝试次数（total−loopback，哨兵里派生）。§11 只点名四项，
# 但四项之外还必须有一条「任何非回环网络尝试」的硬零，否则「没打 Google，但打了别处」无人看见。
CONTRACT_DERIVED_ZERO_METRICS = ("external_network_attempts",)
# §8.2 点名必须逐项进报告的清单。登记文件删一行就等于把那一类目标从分母里抹掉，
# 所以「必须 produce 这几张表」写在代码里，跟零调用指标同一手法。
CONTRACT_ITEMIZED_LISTS = ("NONE", "AMBIGUOUS", "CONFLICT", "UNRESOLVED", "exposed")


class MapGateConfigError(RuntimeError):
    """门禁登记不完整或自相矛盾。"""


def _source_codes(path: Path) -> set[str]:
    """从源码里解析出所有 `CODE|...` 形态的 finding code（含动态拼接的前缀段）。

    动态段的形态是 f"IDENTITY_VERIFIED_WITHOUT_{gate.upper()}|…"：AST 里那一段常量的值就是
    `IDENTITY_VERIFIED_WITHOUT_`（大括号是源码语法，不进 AST），所以判定标准是
    「以 _ 结尾 + 后面紧跟一个插值」，而不是去找不存在的 '{'。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            head = ""
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    head += part.value
                else:
                    break
            if not head:
                continue
            hit = re.match(r"([A-Z][A-Z0-9_]{3,})\|", head)
            if hit:
                found.add(hit.group(1))
            elif re.match(r"^[A-Z][A-Z0-9_]{3,}_$", head) and len(node.values) > 1:
                found.add(head)          # 动态拼接前缀：IDENTITY_VERIFIED_WITHOUT_
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            hit = re.match(r"([A-Z][A-Z0-9_]{3,})\|", node.value)
            if hit:
                found.add(hit.group(1))
    return found


def emitted_finding_codes() -> dict[str, set[str]]:
    """门禁必须能解释它可能看到的每一个 code——来源是本仓库源码，不是记忆。"""
    return {
        "scripts/data_model.py": _source_codes(ROOT / "scripts" / "data_model.py"),
        "scripts/map_gate_v422.py": _source_codes(Path(__file__)),
    }


def severity_of(code: str, gate: dict) -> str | None:
    """返回 blocking / exposed / split（按字段分级）/ None（未登记）。"""
    cls = gate["classification"]
    for severity in VALID_SEVERITIES:
        if code in (cls.get(severity + "_exact") or []):
            return severity
    for severity in VALID_SEVERITIES:
        for prefix in cls.get(severity + "_prefixes") or []:
            if code.startswith(prefix):
                return severity
    if code in (cls.get("split_codes") or []):
        return "split"
    return None


def load_gate(path: Path | None = None) -> dict:
    gate_path = path or GATE_FILE
    if not gate_path.is_file():
        raise MapGateConfigError("缺少 %s：v4.2.2 不允许回退到代码内默认严重性表" % gate_path.name)
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_GATE_KEYS if key not in gate]
    if missing:
        raise MapGateConfigError("门禁登记缺键 %s" % missing)
    cls = gate["classification"]
    for key in ("blocking_exact", "exposed_exact"):
        if not isinstance(cls.get(key), list) or not cls[key]:
            raise MapGateConfigError("classification.%s 必须是非空列表" % key)
    overlap = set(cls["blocking_exact"]) & set(cls["exposed_exact"])
    if overlap:
        raise MapGateConfigError("同一 code 同时被登记为整批阻断与逐项暴露：%s" % sorted(overlap))
    unknown_severity = [code for code in set(cls["blocking_exact"]) | set(cls["exposed_exact"])
                        if severity_of(code, gate) is None]
    if unknown_severity:
        raise MapGateConfigError("名单里的 code 解析不出严重性（配置自相矛盾）：%s"
                                 % sorted(unknown_severity))
    # 闭集牙齿：源码里能吐出的每一个 code 都必须有归属，且前缀兜住的动态段也要登记
    unclassified = {}
    for source, codes in emitted_finding_codes().items():
        loose = sorted(code for code in codes
                       if severity_of(code.rstrip("_"), gate) is None
                       and severity_of(code, gate) is None)
        if loose:
            unclassified[source] = loose
    if unclassified:
        raise MapGateConfigError("这些 code 没有登记严重性（不允许静默第三类）：%s" % unclassified)
    ruleless = sorted(set(cls.get("split_codes") or [])
                      - set((cls.get("field_split_codes") or {}).keys()))
    if ruleless:
        raise MapGateConfigError("split_codes 里没有分级规则：%s" % ruleless)
    # 反方向的牙齿：登记了却谁都吐不出来的 code，等于报告里永远为 0 的假可观测项（同 V1R 的
    # reason code 规则）。经注册表供给的 code 必须真的在注册表里写着，两边少一边都报错。
    emittable = set().union(*emitted_finding_codes().values())
    dynamic_prefixes = sorted(token for token in emittable if token.endswith("_"))

    def can_emit(code: str) -> bool:
        return code in emittable or any(code.startswith(prefix) for prefix in dynamic_prefixes)

    via_registry = set(cls.get("emitted_via_registry") or [])
    data_model_path = ROOT / "scripts" / "data_model.py"
    policy_blob = json.loads((ROOT / "references" / "data-model.json").read_text(encoding="utf-8"))
    supplied = {str((policy_blob.get("required_location_role_applicability") or {})
                    .get("unknown_category", {}).get("finding") or "")}
    for code in via_registry - supplied:
        raise MapGateConfigError("emitted_via_registry 说 %s 由 data-model 供给，但注册表里写的不是它"
                                 % code)
    dead = sorted(code for code in set(cls["blocking_exact"]) | set(cls["exposed_exact"])
                  if not can_emit(code) and code not in via_registry)
    if dead:
        raise MapGateConfigError("登记了严重性却没有任何代码会吐出这些 code（假可观测项）：%s" % dead)
    if not data_model_path.is_file():
        raise MapGateConfigError("找不到 %s：无法核对 code 闭集" % data_model_path.name)
    for code, rule in (cls.get("field_split_codes") or {}).items():
        if code in set(cls["blocking_exact"]) | set(cls["exposed_exact"]):
            raise MapGateConfigError("%s 既登记为按字段分级又登记为固定严重性：两处答案迟早分叉"
                                     % code)
        if code not in (cls.get("split_codes") or []):
            raise MapGateConfigError("%s 有字段分级规则但没进 classification.split_codes" % code)
        blocking = set(rule.get("blocking_when_missing_fields") or [])
        exposed = set(rule.get("exposed_when_missing_fields") or [])
        if blocking & exposed:
            raise MapGateConfigError("%s 的字段分级重叠：%s" % (code, sorted(blocking & exposed)))
        policy = json.loads((ROOT / "references" / "data-model.json").read_text(encoding="utf-8"))
        required = set(policy.get("map_target_required_fields") or [])
        unsorted = sorted(required - blocking - exposed)
        if unsorted:
            raise MapGateConfigError("%s：必填字段里没有分级的字段 %s——门禁会把它按未知严重性处理，"
                                     "这是不允许的" % (code, unsorted))
    zero = gate["zero_call_gate"]
    if not zero.get("must_all_be_zero") or zero.get("evidence_source") != "execution_interceptor":
        raise MapGateConfigError("零调用门必须要求全部为 0 且证据来源是执行期拦截器（§11 V4）")
    if not zero.get("refuse_when_not_armed"):
        raise MapGateConfigError("哨兵未装齐时必须拒绝出账，不许报空账好看")
    # §11 V4 点名的四项一个都不能少：登记文件自己删短了也要在这里被拦住，
    # 否则「少登记一项」会变成「那一项永远为 0」的假通过（同 V1R 的 reason code 牙齿）。
    declared = [str(item) for item in (zero.get("required_metrics") or [])]
    short = sorted(set(CONTRACT_ZERO_CALL_METRICS) - set(declared))
    if short:
        raise MapGateConfigError("zero_call_gate.required_metrics 少了 §11 V4 点名的指标 %s" % short)
    extra_missing = sorted(set(CONTRACT_DERIVED_ZERO_METRICS)
                           - {str(item) for item in (zero.get("hard_zero_extra_metrics") or [])})
    if extra_missing:
        raise MapGateConfigError("zero_call_gate.hard_zero_extra_metrics 少了派生硬零指标 %s："
                                 "四项之外的网络尝试没人判定，0 就只覆盖 Google" % extra_missing)
    if not [item for item in (zero.get("required_interceptors") or []) if str(item)]:
        raise MapGateConfigError("zero_call_gate.required_interceptors 为空：没有拦截器就没有账本")
    buckets = zero.get("host_classification") or {}
    empty = sorted(name for name in CONTRACT_HOST_BUCKETS if not buckets.get(name))
    if empty:
        raise MapGateConfigError("host_classification 缺名单 %s：分类不能靠猜" % empty)
    lists = [str(item) for item in ((gate["reporting"].get("itemized_lists_required") or []))]
    absent = sorted(set(CONTRACT_ITEMIZED_LISTS) - set(lists))
    if absent:
        raise MapGateConfigError("reporting.itemized_lists_required 少了 §8.2 点名的 %s："
                                "少登记一类就是把它从分母里抹掉" % absent)
    # §8.1 的 DOM 对账名单也要能自证：登记了却发不出的 code＝报告里永远为 0 的假可观测项
    dom_codes = [str(item) for item in
                 ((gate["consistency_checks"].get("dataset_vs_dom") or {}).get("codes") or [])]
    for code in dom_codes:
        if severity_of(code, gate) != "blocking":
            raise MapGateConfigError("%s 是 §8.1 一致性 code，必须整批阻断，不能只暴露" % code)
    loose_dom_codes = sorted(code for code in dom_codes if not can_emit(code))
    if loose_dom_codes:
        raise MapGateConfigError("dataset_vs_dom.codes 登记了发不出的 code：%s" % loose_dom_codes)
    emittable_dom = sorted(code for code in emittable
                           if code.startswith("GATE_DOM_") and code not in dom_codes)
    if emittable_dom:
        raise MapGateConfigError("dom_findings 会发但这些 code 没在 §8.1 名单里：%s" % emittable_dom)
    return gate


def _split_code(finding: str) -> tuple[str, str]:
    head, _, rest = finding.partition("|")
    return head.strip(), rest


def classify(findings: list[str], gate: dict) -> dict:
    blocking, exposed, unclassified = [], [], []
    cls = gate["classification"]
    splits = cls.get("field_split_codes") or {}
    for finding in findings:
        code, rest = _split_code(finding)
        severity = severity_of(code, gate)
        rule = splits.get(code)
        if rule:
            hit = FIELDS_TOKEN.search(finding)
            names = [item for item in (hit.group(1).split(",") if hit else []) if item]
            if names:
                blocking_fields = set(rule["blocking_when_missing_fields"])
                severity = "blocking" if set(names) & blocking_fields else "exposed"
        if severity == "blocking":
            blocking.append(finding)
        elif severity == "exposed":
            exposed.append(finding)
        else:
            unclassified.append(finding)
    return {"blocking": blocking, "exposed": exposed, "unclassified": unclassified,
            "counts": {"blocking": len(blocking), "exposed": len(exposed),
                       "unclassified": len(unclassified)}}


def hard_conflict_findings(map_targets: dict, gate: dict, selection: dict) -> list[str]:
    """§8.1：CONFLICT / WRONG_ENTITY / 已知错链既必须无按钮，也必须整批阻断。"""
    out = []
    identity_blocking = set(gate["hard_conflict_invariants"]["identity_status_blocking"])
    resolution_blocking = set(gate["hard_conflict_invariants"]["resolution_status_blocking"])
    quarantine_blocking = set(selection["known_bad_link_markers"]
                              .get("blocking_quarantine_reason_codes") or [])
    for key, target in sorted(map_targets.items()):
        if not isinstance(target, dict):
            continue
        link_mode = str(target.get("link_mode") or "")
        conflict = (str(target.get("identity_status") or "") in identity_blocking
                    or str(target.get("google_resolution_status") or "") in resolution_blocking
                    or {str(row.get("reason_code") or "") for row in
                       (target.get("quarantine") or []) if isinstance(row, dict)}
                    & quarantine_blocking)
        if conflict:
            # 业主 2026-10-29 指令 §5：CONFLICT / WRONG_ENTITY / 已知跨城市 / 错误分店 / 错误终端
            # ⇒「无按钮并整批阻断」。所以「已经老实地不给按钮」并不把这一条降级成暴露项：
            # 地图门在这里说 FAIL，是否继续交付由 delivery gate 按 §8.3 就行程可执行性单独裁决。
            out.append("GATE_HARD_CONFLICT_STATE|%s identity=%s resolution=%s link_mode=%s"
                       "（§8.1/§8.3：已知冲突必须无按钮并整批阻断，不得用搜索按钮把冲突伪装成解决）"
                       % (key, target.get("identity_status"),
                          target.get("google_resolution_status"), link_mode))
        if conflict and link_mode != "NONE":
            out.append("GATE_HARD_CONFLICT_HAS_BUTTON|%s identity=%s resolution=%s link_mode=%s"
                       "（§8.1：已知冲突不得给按钮，且这一条整批阻断）"
                       % (key, target.get("identity_status"),
                          target.get("google_resolution_status"), link_mode))
    return out


def coordinate_button_findings(map_targets: dict) -> list[str]:
    """§8.1：命名实体的读者链接不得是纯坐标。"""
    out = []
    for key, target in sorted(map_targets.items()):
        if not isinstance(target, dict) or str(target.get("entity_type")) != "named_entity":
            continue
        if str(target.get("link_mode")) != "COORDINATE":
            continue
        out.append("GATE_NAMED_ENTITY_COORDINATE_LINK|%s 命名实体拿到坐标按钮（§8.1 必须为 0）" % key)
    return out


def coverage_findings(map_targets: dict, selection: dict) -> list[str]:
    """§8.2：100% 目标必须有四维状态与选择原因。"""
    out = []
    dimensions = ("identity_status", "coordinate_status", "link_mode",
                  "google_resolution_status")
    for key, target in sorted(map_targets.items()):
        if not isinstance(target, dict):
            continue
        absent = [field for field in dimensions if not str(target.get(field) or "")]
        if absent:
            out.append("GATE_DIMENSIONS_INCOMPLETE|%s 缺 %s（§8.2 要求 100%%）" % (key, absent))
        elif not str(target.get("link_selection_reason") or ""):
            out.append("GATE_SELECTION_REASON_MISSING|%s link_mode=%s 没有选择原因"
                       % (key, target.get("link_mode")))
    return out


def dataset_vs_report_findings(map_targets: dict, report_rows: list[dict],
                              selection: dict) -> list[str]:
    """§8.1：dataset 的单值 link 字段必须等于逐 target 报告里主 provider 那一行。"""
    out = []
    primary = selection["ui"]["primary_provider"]
    fields = list(json.loads((ROOT / "references" / "data-model.json")
                             .read_text(encoding="utf-8"))["map_link_output_fields"]["fields"])
    by_target = {}
    for row in report_rows:
        if str(row.get("provider")) == primary:
            by_target[str(row.get("target_id"))] = row
    expected_targets = len(map_targets)
    if len(by_target) != expected_targets:
        out.append("GATE_REPORT_DENOMINATOR_MISMATCH|主 provider 报告行 %d != target 数 %d"
                   "（§9 分母固定，不得过滤失败行）" % (len(by_target), expected_targets))
    for key, target in sorted(map_targets.items()):
        row = by_target.get(key)
        if row is None:
            out.append("GATE_TARGET_MISSING_FROM_REPORT|%s 在逐 target 报告里没有 %s 行"
                       % (key, primary))
            continue
        after = row.get("after") or {}
        for field in fields:
            left, right = target.get(field), after.get(field)
            if field in ("map_link_by_provider",):
                continue
            if left is not None and right is not None and left != right:
                out.append("GATE_DATASET_REPORT_DIFFER|%s 字段 %s 在 dataset=%r 报告=%r（§8.1）"
                           % (key, field, str(left)[:40], str(right)[:40]))
    return out


def expected_dom_links(map_targets: dict, selection: dict,
                       alias_by_id: dict[str, str] | None = None) -> dict:
    """读者页应当出现的按钮：(target_id, provider) → 选择器写在 dataset 里的那条记录。

    只认 `ui.rendered_providers`（§7 最小 reader 范围）；link_mode=NONE 或没有 URL 的目标
    本来就不该有按钮，所以不进期望集——它们的「无按钮」由 `GATE_DOM_HREF_UNEXPECTED` 反向保护。

    `alias_by_id` 只接受 `resolve_aliases` 现算现校验后剩下的配对：把 alias 行的期望按钮改记到
    canonical 行名下（205 行 ⇒ 200 个渲染身份）。不传就等于不豁免——默认严格，漏传不会把缺口洗白。
    """
    rendered = [str(provider) for provider in selection["ui"]["rendered_providers"]]
    primary = str(selection["ui"]["primary_provider"])
    expected: dict[tuple[str, str], dict] = {}
    for key, target in sorted((map_targets or {}).items()):
        if not isinstance(target, dict):
            continue
        target_id = str(target.get("target_id") or key)
        target_id = str((alias_by_id or {}).get(target_id, target_id))
        container = target.get("map_link_by_provider")
        container = container if isinstance(container, dict) else {}
        for provider in rendered:
            record = container.get(provider)
            if record is None and provider == primary:
                record = {field: target.get(field) for field in
                          ("link_mode", "map_link_url", "link_notices",
                           "link_selection_reason")}
            if not isinstance(record, dict):
                continue
            if str(record.get("link_mode") or "NONE") == "NONE":
                continue
            if not str(record.get("map_link_url") or ""):
                continue
            expected[(target_id, provider)] = record
    return expected


def dom_findings(map_targets: dict, dom_rows: list[dict], gate: dict,
                 selection: dict, country: str = "") -> list[str]:
    """§8.1「dataset/DOM/report/href/link mode 不一致 = 0」——判据是浏览器抓回来的行。

    浏览器侧只做取值（href / data-* / 可见文案），比对一律在这里做：QA 层不再持有第二套
    主机名单（§9 禁止渲染/QA 层维护自己的 provider 规则）。文案按登记的中英两种形态比对，
    切语言不改变「文案必须等于登记值」这条判据。
    """
    rendered = {str(provider) for provider in selection["ui"]["rendered_providers"]}
    copy_registry = selection["ui"]["button_copy"]
    alias_by_id, alias_findings = resolve_aliases(map_targets, gate, selection, country)
    expected = expected_dom_links(map_targets, selection, alias_by_id)
    by_target = {str(target.get("target_id") or key): target
                 for key, target in sorted((map_targets or {}).items())
                 if isinstance(target, dict)}
    seen: dict[tuple[str, str], dict] = {}
    out: list[str] = list(alias_findings)
    for row in dom_rows or []:
        provider = str(row.get("provider") or "")
        if provider not in rendered:
            out.append("GATE_DOM_PROVIDER_UNREGISTERED|DOM 出现 provider=%r，不在 "
                       "ui.rendered_providers=%s（§7：读者页按钮集合由登记决定，不由渲染层决定）"
                       % (provider, sorted(rendered)))
            continue
        if not str(row.get("targetId") or ""):
            out.append("GATE_DOM_TARGET_ID_MISSING|%s 按钮没有 data-target-id，无法与 dataset "
                       "对账（§7 八项属性之一缺位）" % provider)
            continue
        pair = (str(row.get("targetId")), provider)
        prior = seen.get(pair)
        if prior is not None:
            # 同一个目标在页面里出现多次本身是合法的（酒店同时出现在住宿清单和每日行程里），
            # 但两次必须长得一模一样：真实数据实测 PH 198 个目标渲染出 265 颗按钮，
            # 若这里只做「后写覆盖」，同目标不同 href 就会被掩盖过去。
            differing = [field for field in ("href", "linkMode", "identityStatus",
                                             "coordinateStatus", "resolutionStatus")
                         if str(prior.get(field) or "") != str(row.get(field) or "")]
            if differing:
                out.append("GATE_DOM_DUPLICATE_CONFLICT|%s/%s 同一目标在页面里出现两次且 %s 不一致"
                           "（%r vs %r）：读者点哪个都不一样，§8.1 视为不一致"
                           % (pair[0], provider, differing,
                              [str(prior.get(f))[:40] for f in differing],
                              [str(row.get(f))[:40] for f in differing]))
            continue
        seen[pair] = row
    for target_id, provider in sorted(set(expected) - set(seen)):
        out.append("GATE_DOM_HREF_MISSING|%s/%s dataset 里 link_mode=%s 有 URL，DOM 没有对应按钮"
                   "（§8.1：不一致 = 0）"
                   % (target_id, provider, expected[(target_id, provider)].get("link_mode")))
    for target_id, provider in sorted(set(seen) - set(expected)):
        out.append("GATE_DOM_HREF_UNEXPECTED|%s/%s DOM 出现了 dataset 里没有的按钮 href=%r"
                   "（渲染层自己造链接＝第二套规则）"
                   % (target_id, provider, str(seen[(target_id, provider)].get("href"))[:120]))
    for pair in sorted(set(expected) & set(seen)):
        row, record = seen[pair], expected[pair]
        target_id, provider = pair
        if str(row.get("href") or "") != str(record.get("map_link_url") or ""):
            out.append("GATE_DOM_HREF_DIFFERS|%s/%s DOM=%r dataset=%r（§8.1 href 必须逐字等于"
                       "选择器写下的 URL）"
                       % (target_id, provider, str(row.get("href"))[:120],
                          str(record.get("map_link_url"))[:120]))
        if str(row.get("linkMode") or "") != str(record.get("link_mode") or ""):
            out.append("GATE_DOM_LINK_MODE_DIFFERS|%s/%s DOM data-link-mode=%r dataset=%r"
                       % (target_id, provider, row.get("linkMode"), record.get("link_mode")))
        spec = copy_registry.get(str(record.get("link_mode") or "")) or {}
        allowed_text = {str(spec.get("cn") or ""), str(spec.get("en") or "")} - {""}
        visible = str(row.get("text") or "").strip()
        if allowed_text and visible not in allowed_text:
            out.append("GATE_DOM_COPY_DIFFERS|%s/%s 按钮文案=%r 不等于登记文案 %s"
                       "（§7：文案只从 map-link-selection.json 取）"
                       % (target_id, provider, visible[:60], sorted(allowed_text)))
        target = by_target.get(target_id, {})
        for attribute, field in (("identityStatus", "identity_status"),
                                 ("coordinateStatus", "coordinate_status"),
                                 ("resolutionStatus", "google_resolution_status"),
                                 ("entityType", "entity_type"),
                                 ("criticality", "criticality")):
            if str(row.get(attribute) or "") != str(target.get(field) or ""):
                out.append("GATE_DOM_STATUS_DIFFERS|%s/%s DOM %s=%r 与 dataset %s=%r 不一致"
                           "（§3.4：状态在链接路径上被改写就是升级）"
                           % (target_id, provider, attribute, row.get(attribute), field,
                              target.get(field)))
    return out


def provider_container_findings(targets: dict, selection: dict, payload_kind: str) -> list[str]:
    """§3.3 + V3R：审计面必须有全部已登记 provider；读者载荷必须恰好是 rendered_providers。

    两个面不能混为一谈：V2R 的 dataset 文件是审计面（apple 必须在），
    单文件 HTML 里的载荷是读者面（apple 已被投影剔掉）。用错口径就会把合规当违规。
    """
    if payload_kind == "reader":
        expected = set(selection["ui"]["rendered_providers"])
    elif payload_kind == "audit":
        expected = set(selection["providers"])
    else:
        raise MapGateConfigError("payload_kind 只认 audit / reader，收到 %r" % payload_kind)
    out = []
    for key, target in sorted((targets or {}).items()):
        container = (target or {}).get("map_link_by_provider")
        if not isinstance(container, dict):
            continue
        if set(container) != expected:
            out.append("GATE_PROVIDER_SET_DIFFERS|%s %s 面 provider=%s != 登记 %s"
                       % (key, payload_kind, sorted(container), sorted(expected)))
    return out


def zero_call_findings(ledger: dict | None, gate: dict) -> list[str]:
    zero = gate["zero_call_gate"]
    if ledger is None:
        return ["GATE_ZERO_CALL_LEDGER_ABSENT|零调用计数必须来自执行期拦截器（§11 V4），"
                "没有账本就不出 0，也不许用源码扫描代替"]
    armed = set(ledger.get("interceptors_armed") or [])
    missing = sorted(set(zero["required_interceptors"]) - armed)
    out = []
    if missing:
        out.append("GATE_ZERO_CALL_SENTINEL_NOT_ARMED|哨兵缺少拦截器 %s——账本不可信，"
                   "按 §8.1 视同系统级违规" % missing)
    counts = ledger.get("counts") or {}
    # 登记的硬零名单（含 hard_zero_extra_metrics）一律要有读数且必须为 0：
    # 只在报告里列名而不判定，等于给「network 层面真的出去过」留了一条没人看的缝。
    for metric in list(zero["required_metrics"]) + list(zero.get("hard_zero_extra_metrics") or []):
        value = counts.get(metric)
        if value is None:
            out.append("GATE_ZERO_CALL_METRIC_UNMEASURED|%s 在账本里没有读数（不许填 0 凑数）"
                       % metric)
        elif value:
            out.append("GATE_ZERO_CALL_METRIC_NONZERO|%s=%s（§8.1 要求为 0）" % (metric, value))
    loopback = counts.get("local_loopback_attempts") or 0
    if loopback and not str(ledger.get("loopback_explanation") or "").strip():
        out.append("GATE_ZERO_CALL_LOOPBACK_UNEXPLAINED|本机回环尝试 %s 次却没有说明——"
                   "回环不是违规，但用它去宣称『零 socket』就是假话（哨兵文档明写）" % loopback)
    return out


def applicability(dataset: dict, selection: dict) -> dict:
    """门禁只对「声明了本版血缘」的 dataset 行使强制力。

    v4.2.1 的历史/夹具数据不带 `map_link_selection.selection_version`，用 v4.2.2 规则去判它们
    会产出一堆「它们本来就不可能满足」的错误，把真正的信号埋掉——这与角色矩阵那次失误同源。
    所以本版血缘就是开关：带且等于本版 ⇒ 全面强制；带但不是本版 ⇒ 拒绝判定并说清楚；
    完全不带 ⇒ 不适用（登记为 NOT_V422_MIGRATED，供 V6/V7 追踪，不当成通过）。
    """
    block = dataset.get("map_link_selection") if isinstance(dataset, dict) else None
    declared = str((block or {}).get("selection_version") or "")
    current = str(selection.get("selection_version") or "")
    targets = (dataset.get("map_targets") or {}) if isinstance(dataset, dict) else {}
    if not targets:
        return {"enforced": False, "reason": "NO_MAP_TARGETS"}
    if not declared:
        return {"enforced": False, "reason": "NOT_V422_MIGRATED_NO_SELECTION_PROVENANCE",
                "declared_selection_version": "", "current": current,
                "follow_up": "V6 端到端候选 run 必须带本版血缘；不适用不等于通过"}
    if declared != current:
        return {"enforced": False, "reason": "SELECTION_VERSION_MISMATCH",
                "declared_selection_version": declared, "current": current}
    return {"enforced": True, "reason": "DECLARED_CURRENT",
            "declared_selection_version": declared, "current": current}


def selection_provenance_gate(gate: dict) -> dict:
    return (gate.get("consistency_checks") or {}).get("selection_provenance_gate") or {}


def is_formal_run(gate: dict) -> bool:
    """正式/live run 的判定只有一条来源：登记在门禁配置里的那个环境变量。

    「formal」不能由调用方随口声明，也不能看 dataset 的 demo_mode——历史 v4.2.0 成品也写着
    demo_mode=false，拿它当正式标志会把兼容路径判成违规（业主 V6-R §2 只要求正式路径阻断）。
    """
    marker = selection_provenance_gate(gate)
    name = str(marker.get("formal_env_var") or "")
    want = str(marker.get("formal_env_value") or "1")
    return bool(name) and os.environ.get(name, "") == want


def provenance_findings(dataset: dict, selection: dict, gate: dict,
                        formal: bool | None = None) -> list[str]:
    """§8.1 的开关本身也要有牙齿：正式 run 缺血缘或带错版本 ⇒ 整批阻断。

    以前缺版本只是 `enforced:false`，读起来像「不适用所以通过」；两轮候选页就是这么过去的。
    非正式兼容路径（历史数据、夹具）仍然允许 NOT_APPLICABLE，不拿本版规则去判上一版数据。
    """
    if formal is None:
        formal = is_formal_run(gate)
    if not formal:
        return []
    block = dataset.get("map_link_selection") if isinstance(dataset, dict) else None
    declared = str((block or {}).get("selection_version") or "")
    current = str(selection.get("selection_version") or "")
    if not declared:
        return ["GATE_DOM_PROVENANCE_MISSING_FORMAL|正式 run 的载荷不带 map_link_selection."
                "selection_version：§8.1 的适用性开关无法成立，一致性对账会变成「没量过的 0」。"
                "期望版本 %s（登记见 selection_provenance_gate.codes）" % current]
    if declared != current:
        return ["GATE_DOM_PROVENANCE_VERSION_STALE|正式 run 载荷声明 selection_version=%r，"
                "当前登记是 %r：版本不匹配时对账要么不跑、要么用错规则跑，两种都不许放行"
                % (declared, current)]
    return []


def alias_contract(gate: dict) -> dict:
    block = ((gate.get("consistency_checks") or {}).get("dataset_vs_dom") or {})
    contract = block.get("alias_contract") or {}
    return contract if isinstance(contract, dict) else {}


def _targets_by_key(map_targets: dict) -> dict:
    return {str(key): row for key, row in sorted((map_targets or {}).items())
            if isinstance(row, dict)}


def provider_link_view(target: dict, providers: list[str], selection: dict) -> dict:
    """逐 provider 的 (link_mode, map_link_url) 视图：容器缺失时退回该行自己的单值字段。

    退回规则必须和 `expected_dom_links` 用的是同一份（primary provider 才允许退回），
    否则 alias 与 canonical 的比对会和期望集各说各话。
    """
    primary = str(selection["ui"]["primary_provider"])
    container = target.get("map_link_by_provider")
    container = container if isinstance(container, dict) else {}
    view = {}
    for provider in providers:
        record = container.get(provider)
        if not isinstance(record, dict) and provider == primary:
            record = {"link_mode": target.get("link_mode"),
                      "map_link_url": target.get("map_link_url")}
        view[provider] = {key: str((record or {}).get(key) or "")
                          for key in ("link_mode", "map_link_url")}
    return view


def normalized_field_value(value) -> str:
    """把一个字段值折成可比较、可哈希的规范文本——alias 合同里唯一的规范化实现。

    对象/数组一律 `json.dumps(sort_keys=True)`：`names` 是 dict，`link_notices` 与 `evidence` 是
    list，用 `str(dict)` 会把**键的写入顺序**当成值的一部分（同一份数据换个顺序就换指纹），嵌套
    结构还会「内容相同、repr 不同」被误判成不一致。数组顺序在这里是有语义的（`link_notices` 的次序
    就是读者看到提示的次序），所以只规范对象键序，不打乱数组。
    「这格不存在」与「存在但是空」是两种状态：absent 折成不带引号的 `absent`，present 一律 JSON
    编码（字符串带引号、空容器是 `[]`/`{}`、None 是 `null`），两者不可能撞车。
    """
    if value is _ABSENT:
        return "absent"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def alias_identity(alias: dict, canonical: dict, compared: list[str], providers: list[str],
                   selection: dict) -> tuple[bool, list[str], str]:
    """alias 与 canonical 是否「业务字段完全一致」——唯一实现，工具与门禁共用。

    返回 (是否一致, 不一致的字段, 指纹)。指纹把两侧字段视图与逐 provider 视图一起哈希，
    登记里存的必须是同一个函数算出来的值，否则「登记过一致」这句话就只是文字。

    V6-R1（业主 2026-10-31）把 `canonical_name / display_name / names / link_notices / evidence`
    也纳进指纹。判据只许收紧不许放松：这三类值都是对象/数组，所以比较走
    `normalized_field_value`，不允许 `str(dict)` 那种「碰巧能比」的写法（有测试钉住）。
    """
    differing = [field for field in compared
                 if normalized_field_value(alias.get(field, _ABSENT))
                 != normalized_field_value(canonical.get(field, _ABSENT))]
    view_alias = provider_link_view(alias, providers, selection)
    view_canonical = provider_link_view(canonical, providers, selection)
    if view_alias != view_canonical:
        differing = differing + sorted("providers.%s.%s" % (provider, key)
                                       for provider, keys in view_alias.items()
                                       for key, value in keys.items()
                                       if value != view_canonical.get(provider, {}).get(key))
    blob = {"alias": {field: normalized_field_value(alias.get(field, _ABSENT))
                      for field in compared},
            "canonical": {field: normalized_field_value(canonical.get(field, _ABSENT))
                          for field in compared},
            "providers_alias": view_alias, "providers_canonical": view_canonical}
    digest = hashlib.sha256(json.dumps(blob, ensure_ascii=False, sort_keys=True)
                            .encode("utf-8")).hexdigest().upper()
    return (not differing), differing, digest


def resolve_aliases(map_targets: dict, gate: dict, selection: dict,
                    country: str = "") -> tuple[dict, list[str]]:
    """把登记的 alias 配对解析成 target_id → canonical target_id，逐条校验，不过就整批不豁免。

    校验四项（业主 V6-R §1）：目标存在、无环（含自指与链式）、逐 provider/href/link mode/状态
    完全一致、dataset 的 `alias_of` 与登记两处一致。任何一项不过，这条配对就不产生豁免——
    于是「DOM 没有那颗按钮」继续按 GATE_DOM_HREF_MISSING 阻断，宁红不假绿。

    `scope_field`（现用 country）决定一条登记适用于哪一份 dataset：菲律宾的 run 不该因为
    加州的配对不存在而报 5 条缺失。范围不明时**不豁免也不报错**——豁免必须被正面证明，
    而「这条配对不归本 run 管」不是缺陷。
    """
    contract = alias_contract(gate)
    entries = [row for row in (contract.get("entries") or []) if isinstance(row, dict)]
    compared = [str(field) for field in (contract.get("compared_fields") or [])]
    if not compared:
        return {}, []
    scope_field = str(contract.get("scope_field") or "country")
    here = str(country or "")
    registered_keys = {str(entry.get("alias_key") or "") for entry in entries}
    providers = [str(item) for item in selection["ui"]["rendered_providers"]]
    primary = str(selection["ui"]["primary_provider"])
    if primary not in providers:
        providers = providers + [primary]
    by_key = _targets_by_key(map_targets)
    findings: list[str] = []
    resolved: dict[str, str] = {}
    for entry in entries:
        if str(entry.get("scope") or "") and str(entry.get("scope") or "") != here:
            continue
        alias_key = str(entry.get("alias_key") or "")
        canonical_key = str(entry.get("canonical_key") or "")
        alias, canonical = by_key.get(alias_key), by_key.get(canonical_key)
        if alias is None or canonical is None:
            missing = alias_key if alias is None else canonical_key
            findings.append("GATE_DOM_ALIAS_TARGET_MISSING|登记的 alias 配对 %s→%s 里 %s 在 dataset 中"
                            "不存在：配对漂移了，alias 不获豁免（§8.1 逐条校验）"
                            % (alias_key, canonical_key, missing))
            continue
        if alias_key == canonical_key:
            findings.append("GATE_DOM_ALIAS_CYCLE|%s 指向自己：别名环从定义上就不成立" % alias_key)
            continue
        declared = str(alias.get("alias_of") or "")
        if declared != canonical_key:
            findings.append("GATE_DOM_ALIAS_NOT_DECLARED|%s 在登记里是 %s 的 alias，但 dataset 那行的 "
                            "alias_of=%r：两处必须同时改，单改一边就是漂移" % (alias_key, canonical_key,
                                                                                 declared))
            continue
        identical, differing, digest = alias_identity(alias, canonical, compared, providers, selection)
        if not identical:
            findings.append("GATE_DOM_ALIAS_CONFLICT|%s→%s 的业务字段不一致：%s——同址双键只有完全等价"
                            "才可以共用一颗按钮（§1：provider/href/link mode/状态完全一致）"
                            % (alias_key, canonical_key, differing[:8]))
            continue
        if str(entry.get("identical_fields_digest") or "") != digest:
            findings.append("GATE_DOM_ALIAS_CONFLICT|%s→%s 登记指纹 %s 与现算 %s 不符：字段集合后来"
                            "变过，配对必须重新测量登记" % (alias_key, canonical_key,
                                                            str(entry.get("identical_fields_digest"))[:12],
                                                            digest[:12]))
            continue
        alias_id = str(alias.get("target_id") or alias_key)
        resolved[alias_id] = str(canonical.get("target_id") or canonical_key)
    for key, row in by_key.items():
        declared = str(row.get("alias_of") or "")
        if declared and key not in registered_keys:
            findings.append("GATE_DOM_ALIAS_UNREGISTERED|%s 在 dataset 里声明 alias_of=%r，但登记里没有这一"
                            "条：alias 只能逐项登记，不接受运行时按坐标或名称推断（§1）" % (key, declared))
    for alias_id in sorted(resolved):
        if alias_id not in resolved:
            continue          # 前一条回环已经把整条链踢出豁免集，别再去取已被删掉的节点
        chain, current = {alias_id}, resolved[alias_id]
        while current in resolved:
            if current in chain:
                findings.append("GATE_DOM_ALIAS_CYCLE|%s 所在链出现回环（%s）：链式别名不在本合同内，"
                                "整条链不获豁免" % (alias_id, sorted(chain)))
                for node in chain:
                    resolved.pop(node, None)
                break
            chain.add(current)
            current = resolved[current]
    return resolved, findings


def itemized_lists(map_targets: dict, selection: dict, exposed: list[str]) -> dict:
    """§8.2：NONE / AMBIGUOUS / CONFLICT / UNRESOLVED 与全部暴露项逐条列名，一行都不许蒸发。

    这些名单来自 dataset 本身（不是 finding 文本），因为「没有按钮」是合规降级而不是错误——
    它不会出现在 findings 里，却必须出现在交付报告中，否则读者和审计都无法核对分母。
    """
    primary = str(selection["ui"]["primary_provider"])
    lists = {name: [] for name in CONTRACT_ITEMIZED_LISTS}
    lists["exposed"] = list(exposed)
    for key, target in sorted((map_targets or {}).items()):
        if not isinstance(target, dict):
            continue
        target_id = str(target.get("target_id") or key)
        container = target.get("map_link_by_provider")
        record = container.get(primary) if isinstance(container, dict) else None
        mode = str((record or {}).get("link_mode") or target.get("link_mode") or "NONE")
        if mode == "NONE":
            lists["NONE"].append(target_id)
        state = str(target.get("identity_status") or "")
        if state in lists:
            lists[state].append(target_id)
    return lists


def evaluate(dataset: dict, gate: dict, selection: dict, report_rows: list[dict] | None = None,
             ledger: dict | None = None, policy: dict | None = None,
             payload_kind: str = "audit", dom_rows: list[dict] | None = None) -> dict:
    import data_model

    policy = policy or json.loads((ROOT / "references" / "data-model.json").read_text(
        encoding="utf-8"))
    applic = applicability(dataset, selection)
    targets = dataset.get("map_targets") or {}
    base = data_model.validate_map_targets(targets, policy) if applic["enforced"] else []
    if not applic["enforced"]:
        base = [item for item in base
                if _split_code(item)[0] in ("MAP_TARGETS_CONTAINER_INVALID",
                                            "MAP_TARGET_NOT_OBJECT")]
    extra = []
    extra += provenance_findings(dataset, selection, gate)
    if applic["enforced"]:
        extra += hard_conflict_findings(targets, gate, selection)
        extra += coordinate_button_findings(targets)
        extra += coverage_findings(targets, selection)
        extra += provider_container_findings(targets, selection, payload_kind)
        if dom_rows is not None:
            extra += dom_findings(targets, dom_rows, gate, selection,
                                  str(dataset.get("country") or ""))
        if report_rows is not None:
            extra += dataset_vs_report_findings(targets, report_rows, selection)
    extra += zero_call_findings(ledger, gate)
    split = classify(list(base) + list(extra), gate)
    if split["unclassified"]:
        # 没有归属的 finding 一律按整批阻断处理：宁可门禁自己 FAIL 也不替它猜严重性
        split["blocking"] = split["blocking"] + [
            "GATE_UNCLASSIFIED_SEVERITY|%s" % item for item in split["unclassified"]]
        split["counts"]["blocking"] = len(split["blocking"])
    tallies: dict[str, int] = {}
    for finding in split["blocking"] + split["exposed"]:
        code, _rest = _split_code(finding)
        tallies[code] = tallies.get(code, 0) + 1
    itemized = itemized_lists(targets, selection, split["exposed"]) if applic["enforced"] else {}
    absent_lists = sorted(set(gate["reporting"]["itemized_lists_required"]) - set(itemized))
    if applic["enforced"] and absent_lists:
        # 登记了要逐项列名却产不出名单＝这类目标从报告里蒸发了（§8.2 的另一种作弊方式）
        split["blocking"] = split["blocking"] + [
            "GATE_ITEMIZED_LIST_ABSENT|%s 在册要求逐项列出但门禁没有产出（代码与登记漂移）"
            % name for name in absent_lists]
    return {
        "gate_version": gate["gate_version"],
        "contract_ref": gate["contract_ref"],
        "applicability": applic,
        "targets": len(targets),
        "findings_total": len(base) + len(extra),
        "counts": dict(split["counts"], findings_from_validator=len(base),
                       findings_from_gate=len(extra)),
        "blocking": split["blocking"],
        "exposed": split["exposed"],
        "unclassified": split["unclassified"],
        "code_tally": dict(sorted(tallies.items())),
        "itemized": itemized,
        "itemized_required_by_register": gate["reporting"]["itemized_lists_required"],
        "google_entity_card_hit_rate": "NOT MEASURED / NOT A RELEASE GATE（§8.2）",
        "batch_verdict": ("FAIL" if split["blocking"] or split["unclassified"] else
                          "PASS_WITH_EXPOSURES" if split["exposed"] else "PASS"),
        "enforced": applic["enforced"],
        "denominator_rule": gate["reporting"]["denominator_rule"],
        "zero_call": {"source": "execution_interceptor",
                      "present": ledger is not None,
                      "armed": bool((ledger or {}).get("armed")),
                      "interceptors_armed": sorted((ledger or {}).get("interceptors_armed") or []),
                      "counts": (ledger or {}).get("counts") or {},
                      "ledger_sha256_16": (ledger or {}).get("ledger_sha256_16"),
                      "scope": (ledger or {}).get("scope")},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Travel-Scope v5.0.0 地图发布门禁（继承 v4.2.2 V4 合同）")
    ap.add_argument("--dataset", required=True, help="含 map_targets 的 dataset JSON")
    ap.add_argument("--report", default="", help="link_selection_report.jsonl（可选，逐 target 报告）")
    ap.add_argument("--ledger", default="", help="zero_call_sentinel 执行期账本 JSON")
    ap.add_argument("--dom", default="", help="浏览器取回的 map 按钮行 JSON 数组"
                                              "（visual_qa.MAP_DOM_ROWS_JS 的产物；给了就按 §8.1 对账）")
    ap.add_argument("--out", default="", help="门禁报告 JSON 输出路径")
    ap.add_argument("--gate", default=str(GATE_FILE))
    ap.add_argument("--payload-kind", choices=("audit", "reader"), default="audit",
                    help="audit=dataset 文件（须含全部登记 provider）；reader=单文件 HTML 内嵌载荷（须恰好是 rendered_providers）")
    args = ap.parse_args()

    gate = load_gate(Path(args.gate))
    selection = json.loads((ROOT / "references" / "map-link-selection.json")
                           .read_text(encoding="utf-8"))
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    rows = None
    if args.report:
        rows = [json.loads(line) for line in Path(args.report).read_text(encoding="utf-8").splitlines()
                if line.strip()]
    ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8")) if args.ledger else None
    dom_rows = None
    if args.dom:
        dom_rows = json.loads(Path(args.dom).read_text(encoding="utf-8"))
        if not isinstance(dom_rows, list):
            raise MapGateConfigError("--dom 必须是浏览器取回的按钮数组，收到 %s"
                                     % type(dom_rows).__name__)
    result = evaluate(dataset, gate, selection, report_rows=rows, ledger=ledger,
                      dom_rows=dom_rows,
                        payload_kind=args.payload_kind)
    # 报告一旦落盘就是「一次可被引用的结论」，必须带产出者身份；纯内存调用（测试）不盖。
    if args.out:
        result = gate_producer.write_stamped_report(
            args.out, result, gate_role="map_gate_v422",
            producing_code=list(PRODUCING_CODE), producing_config=list(PRODUCING_CONFIG),
            inputs=gate_producer.collect_inputs({
                "dataset": args.dataset, "link_selection_report": args.report,
                "zero_call_ledger": args.ledger, "dom_rows": args.dom,
                "gate_register": args.gate}))["report"]
    blob = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(json.dumps({"batch_verdict": result["batch_verdict"],
                      "targets": result["targets"],
                      "counts": result["counts"],
                      "report_identity_sha256": ((result.get("producer") or {})
                                                 .get("identity_sha256") or "")[:16],
                      "report_digest_sha256": hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16].upper()},
                     ensure_ascii=False))
    return 1 if result["batch_verdict"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
