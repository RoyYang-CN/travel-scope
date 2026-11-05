#!/usr/bin/env python3
# Version: V5.0.0
"""v4.2.2 诚实地图链接选择器（V4.2.2_ITERATION_CHECKLIST.md §4/§5/§6 的唯一实现）。

为什么存在
----------
v4.2.1 的 W2 迁移把 403 个 target 全部记成 ``link_mode=NONE``：那时"没有已核验实体落点就
不发布按钮"是合同要求，结果是读者手上一个地图按钮都没有。v4.2.2 改的是产品承诺——名称可用
且没有已知错误时给"搜索此地点（落点未核验）"，已知错误或冲突时仍然不给按钮。

本模块是判断的唯一权威：dataset、门禁报告、渲染 DOM 与最终 href 必须复用这里的输出，
渲染层不得再自行拼 URL 或判断主机（§9）。它只写链接侧字段，永远不改
``identity_status`` / ``coordinate_status`` / ``google_resolution_status``（§3.1/§3.4）。

设计约束
--------
* 规则顺序、reason code、文案、URL 模板全部来自 ``references/map-link-selection.json``；
  配置缺失或出现未知原语即 ``SelectionConfigError``，不回退到代码内默认值。
* 查询串只用有来源的字段，禁止字符级删名、禁止城市/州/国家/走廊级伪目标（§4 禁止动作）。
* Place ID/CID 一律不生成、不猜测、不正则"验证"（§4、§6.2）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import data_model  # noqa: E402  (reuses the single reference classifier)
import map_contract  # noqa: E402

SELECTION_FILE = ROOT / "references" / "map-link-selection.json"

REQUIRED_CONFIG_KEYS = (
    "selection_version", "config_strictness", "providers", "query_field_priority",
    "query_rules", "identity_status_allowed_for_named_search",
    "resolution_status_blocking_named_search", "multivalue_notice_states",
    "known_bad_link_markers", "state_machine", "reason_codes", "no_promotion", "ui",
    "dom_attributes", "dom_consistency", "release_gate_non_goals",
    "reader_payload_projection",
)
# 读者载荷投影的字段种类闭集：登记里有、这里没有＝渲染器不会执行；
# 这里有、登记里没有＝渲染器自创了一条没人批准剔除的字段规则。两个方向都必须炸。
PROJECTION_FIELD_KINDS = (
    "map_link_container_entry",          # map_link_by_provider.{provider}
    "provider_url_field",                # {provider}_url（legacy 单值 URL，永不进 href）
    "classifier_verdict_entry",          # classifier_verdicts.{provider}_url
    "quarantine_provider_rows",          # quarantine[] 里归属该 provider 的行
    "isolated_link_url_provider_host",   # isolated_link_url 的宿主属于该 provider
)
# V6-P（业主 2026-10-30 Q1 裁决）：provider-neutral 的「过程记录」也按同一口径投影。
# 判据从「这条数据归属哪个 provider」换成「渲染器读不读它」——逐字段核过 assets/spa-layout.js
# 与 assets/split-layout.js，下面每一字段两个渲染器都不读。名单是闭集：登记与实现双向核对，
# 少一条就是「登记了却没人执行」，多一条就是「渲染器自己扩大了剔除面」。
#
# 为什么只有这 4 条：§17.2.5/§8.2 的可判状态合同（policy_version / evaluated_at / resolver_used /
# lineage_group / address_status / link_builder_version / link_selection_version 等）是**对交付物
# 本身**要求的——map_gate_v422 以 payload_kind="reader" 检查的就是读者拿到的那份载荷，缺字段就报
# MAP_FIELD_MISSING / RESOLVER_USED_NOT_EXPLICIT / MAP_FIELD_NOT_EXPLICIT / LINK_CONTEXT_MISSING /
# IDENTITY_VERIFIED_WITHOUT_POLICY_VERSION。把它们剔掉等于用「读者状态未知」换字节，方向错了。
# 这 4 条是纯过程记录，没有任何门禁要求它们出现在读者载荷里；审计面（dataset.json +
# link_selection_report.jsonl）照旧一条不减。字节实测：CA 2,686,780B / PH 2,224,705B 已足够
# 把加州成品从超围栏 124,182B 拉回登记围栏内。
PROCESS_RECORD_FIELDS = (
    "migration", "unresolved_fields", "quarantine", "classifier_verdicts",
)
REQUIRED_PROJECTION_KEYS = (
    "authority", "rule", "implemented_by", "enforced_by", "audit_only_field_kinds",
    "process_record_fields", "not_projected", "non_goals",
)
REQUIRED_PROCESS_KEYS = ("field", "kind", "why_reader_does_not_consume",
                         "audit_surface_kept", "measured")
# 选择器只允许写这些字段；写别的即违反"搜索 URL 不得升级状态"（§3.1/§3.4）。
WRITABLE_FIELDS = ("link_mode", "link_provider", "link_builder_version",
                   "link_selection_reason", "link_selection_version", "map_link_url",
                   "query_fields_used", "link_notices", "isolated_link_url",
                   "map_query_name_source", "selection_signals")


class SelectionConfigError(RuntimeError):
    """配置缺失/不一致——按 §11 V1「配置缺失即阻断」处理，不得静默降级。"""


class Selection:
    """一次 target × provider 的选择结果（只含链接侧字段）。"""

    def __init__(self, target_id: str, provider: str, selection_version: str) -> None:
        self.target_id = target_id
        self.provider = provider
        self.selection_version = selection_version
        self.link_mode = "NONE"
        self.reason_code = "SELECT_BLOCKED_NO_HONEST_ENTRY"
        self.rule_id = ""
        self.url = ""
        self.query_fields_used: list[str] = []
        self.name_source_field = ""
        self.signals: list[str] = []
        self.notices: list[str] = []
        self.isolated_url = ""
        self.evidence: dict[str, Any] = {}

    def as_record(self) -> dict[str, Any]:
        return {
            "link_mode": self.link_mode,
            "link_provider": self.provider if self.link_mode != "NONE" else None,
            "link_builder_version": self.selection_version if self.link_mode != "NONE" else None,
            "link_selection_version": self.selection_version,
            "link_selection_reason": "%s|%s" % (self.rule_id or "R8", self.reason_code),
            "map_link_url": self.url,
            "query_fields_used": list(self.query_fields_used),
            "link_notices": list(self.notices),
            "isolated_link_url": self.isolated_url,
            "map_query_name_source": self.name_source_field,
            "selection_signals": list(self.signals),
        }

    def writable_keys(self) -> tuple[str, ...]:
        return WRITABLE_FIELDS


def load_selection(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or SELECTION_FILE
    if not cfg_path.is_file():
        raise SelectionConfigError("缺少 %s：v4.2.2 链接选择合同不允许回退到代码内默认值" % cfg_path)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_CONFIG_KEYS if key not in cfg]
    if missing:
        raise SelectionConfigError("配置缺键 %s（%s）" % (missing, cfg_path.name))
    for provider, spec in cfg["providers"].items():
        for key in ("registered", "search_url_template", "query_separator"):
            if key not in spec:
                raise SelectionConfigError("provider %s 缺 %s" % (provider, key))
    seen = set()
    for rule in cfg["state_machine"]:
        for bucket in ("when_all", "when_any"):
            for cond in rule.get(bucket, []):
                if cond.get("primitive") not in PRIMITIVES:
                    raise SelectionConfigError("规则 %s 使用未知原语 %r" % (rule.get("rule_id"), cond.get("primitive")))
        seen.add(str(rule.get("rule_id")))
        then = rule.get("then") or {}
        if then.get("reason_code") not in cfg["reason_codes"]:
            raise SelectionConfigError("规则 %s 的 reason_code %r 未登记" % (rule.get("rule_id"), then.get("reason_code")))
        for override in rule.get("reason_code_overrides", []):
            if override.get("if", {}).get("primitive") not in PRIMITIVES:
                raise SelectionConfigError("规则 %s 的 override 使用未知原语" % rule.get("rule_id"))
            if override["reason_code"] not in cfg["reason_codes"]:
                raise SelectionConfigError("规则 %s 的 override reason_code 未登记" % rule.get("rule_id"))
    if "R8" not in seen:
        raise SelectionConfigError("状态机缺少兜底规则 R8")
    local_rule_modes = [str((rule.get("then") or {}).get("link_mode"))
                        for rule in cfg["state_machine"]
                        if any(cond.get("primitive") == "name_state_is_local_only"
                               for bucket in ("when_all", "when_any")
                               for cond in rule.get(bucket) or [])]
    allow_local = bool(cfg["query_rules"].get("allow_sourced_local_name_in_query"))
    if allow_local and not _norm(cfg["query_rules"].get("local_name_query_ratified_by")):
        raise SelectionConfigError(
            "allow_sourced_local_name_in_query=true 必须先由业主在 `local_name_query_ratified_by` "
            "登记裁决依据与日期；境外搜索串写入本地语言名会掩盖 V0-L02/V0-L06，实施方不得自行放开")
    if allow_local and "NAMED_SEARCH" not in local_rule_modes:
        raise SelectionConfigError("配置与状态机不一致：allow_sourced_local_name_in_query=true "
                                   "却没有任何规则给本地名 NAMED_SEARCH")
    if not allow_local and local_rule_modes and set(local_rule_modes) != {"NONE"}:
        raise SelectionConfigError("配置与状态机不一致：allow_sourced_local_name_in_query=false "
                                   "但本地名规则会给按钮（%s）" % local_rule_modes)
    # reason code 只有一个生效权威：状态机里的 then/override 引用，登记处只有 reason_codes。
    # 配置别处再写 `reason_code` 字段都是不被读取的游离副本（V1 前 name_residue_rules 与
    # join_ambiguity_signals 各有一份，前者还没登记），一律报错。
    reachable = {str((rule.get("then") or {}).get("reason_code")) for rule in cfg["state_machine"]}
    for rule in cfg["state_machine"]:
        for override in rule.get("reason_code_overrides", []) or []:
            reachable.add(str(override.get("reason_code")))
    floating = sorted(set(_iter_reason_code_fields(cfg)))
    if floating:
        raise SelectionConfigError("状态机之外出现 reason code 字段：%s——它不会被任何代码读取，"
                                   "是第二套权威；请改成 implemented_by 指向规则" % floating)
    unreachable = sorted(set(cfg["reason_codes"]) - reachable)
    if unreachable:
        raise SelectionConfigError("reason code 已登记但状态机走不到：%s——报告里这一项永远是 0，"
                                   "等于虚假可观测性" % unreachable)
    _validate_reader_projection(cfg)
    return cfg


def _validate_process_record_fields(block: dict[str, Any]) -> None:
    """过程记录剔除面：登记字段名与渲染器实现必须一模一样。

    三条牙齿都不可省：
    * 闭集双向核对——登记了没实现＝读者照样下载；实现了没登记＝剔除面被人偷偷扩大。
    * 每个字段必须写「渲染器为什么不消费」＋「审计面在哪一条仍然看得见」，否则这条剔除
      只是渲染器里的一句注释，审计时无从复核。
    * 每个字段必须带实测字节（两棵 run 各一条），因为这条规则的代价是用读者下载的字节量的。
    """
    rows = block["process_record_fields"]
    if not isinstance(rows, list) or not rows:
        raise SelectionConfigError("process_record_fields 必须是非空列表：V6-P 的剔除面由登记给出，"
                                   "不能由渲染器自己列")
    names = [str(row.get("field") or "") for row in rows]
    if len(names) != len(set(names)):
        raise SelectionConfigError("process_record_fields 字段名重复：%s" % names)
    unregistered = sorted(set(PROCESS_RECORD_FIELDS) - set(names))
    if unregistered:
        raise SelectionConfigError("渲染器会剔的字段 %s 没有登记，禁止静默生效" % unregistered)
    unknown = sorted(set(names) - set(PROCESS_RECORD_FIELDS))
    if unknown:
        raise SelectionConfigError("登记了渲染器不会剔的字段 %s——登记与实现必须双向核对" % unknown)
    for row in rows:
        missing = [key for key in REQUIRED_PROCESS_KEYS if key not in row]
        if missing:
            raise SelectionConfigError("过程记录字段 %s 缺键 %s" % (row.get("field"), missing))
        if not str(row.get("why_reader_does_not_consume") or "").strip():
            raise SelectionConfigError("字段 %s 必须写明渲染器为什么不消费它" % row.get("field"))
        if not str(row.get("audit_surface_kept") or "").strip():
            raise SelectionConfigError("字段 %s 必须写明审计面仍在哪里保留完整记录："
                                       "投影是剔除读者字节，不是删审计记录" % row.get("field"))
        measured = row.get("measured")
        if not isinstance(measured, dict) or not measured:
            raise SelectionConfigError("字段 %s 没有 measured 数字：这条剔了多少字节必须实测过"
                                       % row.get("field"))
        for run_row in measured.values():
            if not isinstance(run_row, dict) or "rows" not in run_row or "utf8_bytes" not in run_row:
                raise SelectionConfigError("字段 %s 的 measured 行必须是 {rows, utf8_bytes}"
                                           % row.get("field"))


def _validate_reader_projection(cfg: dict[str, Any]) -> None:
    """读者载荷投影必须是登记过的字段种类闭集，且只能指向未渲染的 provider。

    为什么这里是硬门而不是可选项：投影决定读者拿到哪些字节，也决定门禁看不见哪些字段。
    规则若写在渲染器里，改代码就能改口径；写在登记里但种类不闭集，就会出现「登记了五条、
    渲染器只执行两条」——剩下一条永远测不到，等于给读者载荷留了个没人守着的洞。
    """
    block = cfg["reader_payload_projection"]
    if not isinstance(block, dict):
        raise SelectionConfigError("reader_payload_projection 必须是对象")
    missing = [key for key in REQUIRED_PROJECTION_KEYS if key not in block]
    if missing:
        raise SelectionConfigError("reader_payload_projection 缺键 %s" % missing)
    rows = block["audit_only_field_kinds"]
    if not isinstance(rows, list) or not rows:
        raise SelectionConfigError("audit_only_field_kinds 必须是非空列表：没有它，"
                                   "渲染器只能自己猜哪些字段属于未渲染 provider")
    kinds = [str(row.get("kind")) for row in rows]
    if len(kinds) != len(set(kinds)):
        raise SelectionConfigError("audit_only_field_kinds 有重复 kind：%s" % kinds)
    unknown = sorted(set(kinds) - set(PROJECTION_FIELD_KINDS))
    if unknown:
        raise SelectionConfigError("登记了渲染器不会执行的字段种类 %s——登记与实现必须双向核对，"
                                   "否则这一条只是文档" % unknown)
    unregistered = sorted(set(PROJECTION_FIELD_KINDS) - set(kinds))
    if unregistered:
        raise SelectionConfigError("渲染器支持的字段种类 %s 没有登记，禁止静默生效" % unregistered)
    for row in rows:
        if "{provider}" not in str(row.get("field") or ""):
            raise SelectionConfigError("字段模式 %r 必须含 {provider} 占位符："
                                       "写死 provider 名就是第二套硬编码" % row.get("field"))
        if not isinstance(row.get("measured"), dict):
            raise SelectionConfigError("字段种类 %s 没有 measured 数字，登记必须来自实测" % row.get("kind"))
    rendered = set(cfg["ui"].get("rendered_providers") or [])
    _validate_process_record_fields(block)
    neutral = block["not_projected"].get("provider_neutral_audit_fields") or []
    clash = sorted(set(str(name).replace("{provider}", "") for name in neutral)
                   & {str(name) for name in rendered})
    if clash:
        raise SelectionConfigError("not_projected 与 rendered_providers 冲突：%s" % clash)
    if neutral and not _norm(block["not_projected"].get("why_untouched")):
        raise SelectionConfigError("不投影的 provider-neutral 审计字段必须有 why_untouched 说明："
                                   "它们是读者载荷里最大的一块死重，不解释就等于默认放行")


def quarantine_row_attributed(row: dict[str, Any], provider: str) -> bool:
    """这条隔离记录归属哪个 provider——只看登记过的归属面，不按文案关键字猜。

    唯一实现放在合同模块：渲染器剔字段、门禁反查泄漏，两边必须用同一个判据，
    否则「剔了但门禁查不出来」和「门禁误伤 rendered provider 的隔离行」都会静默发生。
    """
    if not isinstance(row, dict):
        return False
    if str(row.get("kind") or "") == "%s_url" % provider:
        return True
    classifiers = row.get("classifier")
    if isinstance(classifiers, dict):
        for verdict in classifiers.values():
            if isinstance(verdict, dict) and str(verdict.get("provider") or "") == provider:
                return True
    return False


def reader_payload_projection(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """投影规则的唯一读取入口：渲染器和门禁都从这里取，不许各自再算一遍。"""
    cfg = cfg or load_selection()
    block = cfg["reader_payload_projection"]
    rendered = sorted(set(cfg["ui"].get("rendered_providers") or []))
    audit_only = sorted(set(cfg["providers"]) - set(rendered))
    hosts = {provider: sorted(set(spec.get("entity_hosts") or []))
             for provider, spec in cfg["providers"].items()}
    return {"authority": block["authority"],
            "implemented_by": block["implemented_by"],
            "enforced_by": list(block["enforced_by"]),
            "rendered_providers": rendered,
            "audit_only_providers": audit_only,
            "entity_hosts": hosts,
            "field_kinds": {str(row["kind"]): str(row["field"]) for row in
                            block["audit_only_field_kinds"]},
            "process_record_fields": sorted(str(row["field"]) for row in
                                            block["process_record_fields"]),
            "process_record_measured": {str(row["field"]): row["measured"]
                                        for row in block["process_record_fields"]},
            "not_projected": list(block["not_projected"].get("provider_neutral_audit_fields") or [])}


def _iter_reason_code_fields(node: Any) -> Any:
    """产出状态机与登记表之外的所有 `reason_code` 字符串值。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("state_machine", "reason_codes"):
                continue
            if key == "reason_code" and isinstance(value, str):
                yield value
            else:
                yield from _iter_reason_code_fields(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_reason_code_fields(item)


# ---------------------------------------------------------------- 名称与查询串

def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()


def _forbidden_literal(value: str, cfg: dict[str, Any]) -> bool:
    return value in set(cfg["query_rules"].get("forbid_literals") or [])


def query_segments(target: dict[str, Any], lookup: dict[str, Any] | None,
                   sel: dict[str, Any]) -> dict[str, str]:
    """具名查询串可用的有来源字段。

    只取数据集里已登记的名称/地址/目的地/国家；目的地优先用登记表给出的英文形式，没有英文形式
    时可用有来源的本地写法（它是搜索串的组成段，永远不允许单独成串——单独的城市/州/国家串就是
    §4 禁止的伪目标）。绝不现场翻译、绝不删字符造英文名（§4）。
    本地语言名是否进入搜索串由 `query_rules.allow_sourced_local_name_in_query` 决定；
    本版为 false，所以 `local_only` 的名称在这里直接不给 name（代码与配置同向，不是硬编码兜底）。
    """
    lookup = lookup or {}
    out: dict[str, str] = {}
    state = _name_state(target, sel)
    raw_name, name_field = authoritative_name(target)
    allow_local = bool(sel["query_rules"].get("allow_sourced_local_name_in_query"))
    if raw_name and (state == "usable" or (state == "local_only" and allow_local)):
        out["name"] = raw_name
        out["name_source_field"] = name_field
    scope = _norm(target.get("destination_scope") or target.get("destination"))
    if scope:
        english_dest = _norm((lookup.get("destinations") or {}).get(scope, ""))
        if english_dest and not data_model.CJK_RE.search(english_dest):
            out["destination"] = english_dest
        elif scope and not data_model.CJK_RE.search(scope):
            # 登记表里没有，但 scope 自己就是有来源的拉丁写法（V2 实测：CA 205 条里 191 条
            # destination_scope 直接是 "California"）。先前只认登记表，把这 187 条的目的地段
            # 整段丢了，搜索串退化成「名字 + 国家」——不是诚实降级，是实现漏分支。
            out["destination"] = scope
        elif state == "local_only":
            out["destination"] = scope  # 本地名与本地目的地同源同语言，可以同串
    country = _norm(target.get("country_code"))
    english_country = _norm((lookup.get("countries") or {}).get(country, ""))
    if english_country and not data_model.CJK_RE.search(english_country):
        out["country"] = english_country
    elif country and re.fullmatch(r"[A-Za-z]{2,3}", country):
        out["country"] = country  # ISO 码是有来源字段的 ASCII 形式，不是翻译
    address = _norm(target.get("address") or target.get("street_address") or target.get("full_address"))
    if address and str(target.get("address_status") or "") in ("VERIFIED", "SOURCED"):
        if state == "usable" and not data_model.CJK_RE.search(address):
            out["address"] = address
        elif state == "local_only":
            out["address"] = address
    qualifier = _norm(target.get("location_qualifier") or target.get("terminal") or target.get("branch"))
    if qualifier and (state == "local_only" or not data_model.CJK_RE.search(qualifier)):
        out["qualifier"] = qualifier
    return out


def build_query(target: dict[str, Any], cfg: dict[str, Any],
                lookup: dict[str, Any] | None) -> tuple[str, list[str], dict[str, str]]:
    """按 §6.1 的优先级拼具名查询串，返回 (query, 用到的字段名, 有来源字段快照)。"""
    seg = query_segments(target, lookup, cfg)
    name = seg.get("name") or ""
    if not name:
        return "", [], seg
    mapping = {
        "sourced_canonical_name": [name],
        "sourced_branch_or_terminal_qualifier": [seg.get("qualifier", "")],
        "sourced_street_address": [seg.get("address", "")],
        "sourced_destination": [seg.get("destination", "")],
        "sourced_country": [seg.get("country", "")],
    }
    parts: list[str] = []
    used: list[str] = []
    sep = cfg["providers"]["google"]["query_separator"]
    for field in cfg["query_field_priority"]:
        if field not in mapping:
            raise SelectionConfigError("query_field_priority 出现未知字段 %r" % field)
        for value in mapping[field]:
            value = _norm(value)
            if not value or _forbidden_literal(value, cfg):
                continue
            if value in parts:  # 去重（§6.1）
                continue
            parts.append(value)
            used.append(field)
    query = sep.join(parts)
    limit = int(cfg["providers"]["google"].get("max_query_chars") or 0)
    if limit and len(query) > limit:
        query = query[:limit].rstrip()
    return query, used, seg


def build_url(provider: str, cfg: dict[str, Any], query: str = "", coordinate: str = "") -> str:
    """只按配置模板生成 URL：具名搜索用 query 模板，坐标地标用坐标模板，其余一律不生成。

    模板里若出现被禁止的参数（`query_place_id`、`ll` 等），本函数直接抛错而不是悄悄生成——
    这让"合成 Place ID / 把搜索伪装成实体直达"在结构上不可能发生（§4 禁止动作、§6.2）。
    """
    from urllib.parse import quote
    spec = cfg["providers"].get(provider)
    if not spec or not spec.get("registered"):
        return ""  # 未登记 provider 不生成按钮（§6.3）
    if query:
        rendered = spec["search_url_template"].replace("{QUERY}", quote(query, safe=","))
        for banned in spec.get("forbid_params_on_named_search") or []:
            if re.search(r"[?&]%s(=|&|$)" % re.escape(banned), rendered):
                raise SelectionConfigError(
                    "具名搜索模板 %s 混入禁止参数 %r：搜索入口不得伪装成实体直达" % (provider, banned))
        return rendered
    if coordinate:
        return spec["coordinate_url_template"].replace("{COORDINATE}", coordinate)
    return ""


# ---------------------------------------------------------------- 原语（唯一判定处）

def _quarantine_rows(target: dict[str, Any]) -> list[dict[str, Any]]:
    """W2 迁移留下的 quarantine 是对象列表：kind + reason_code + 被隔离的原值。"""
    rows = target.get("quarantine") or []
    if isinstance(rows, dict):
        rows = [rows]
    return [row for row in rows if isinstance(row, dict)]


def _quarantine_codes(target: dict[str, Any]) -> set[str]:
    return {str(row.get("reason_code") or "") for row in _quarantine_rows(target)}


def _unresolved_codes(target: dict[str, Any]) -> set[str]:
    rows = target.get("unresolved_fields") or []
    return {str(row.get("reason_code") or "") for row in rows if isinstance(row, dict)}


def _target_flags(target: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    markers = set(cfg["known_bad_link_markers"]["target_flags"])
    flags = target.get("flags") or target.get("link_block_flags") or []
    if isinstance(flags, str):
        flags = [item.strip() for item in flags.split(",") if item.strip()]
    blocking = set(cfg["known_bad_link_markers"].get("blocking_quarantine_reason_codes") or [])
    present = {str(item) for item in list(flags) + sorted(_quarantine_codes(target))}
    return sorted((present & markers) | (present & blocking))


def _join_ambiguity_signal(target: dict[str, Any], sel: dict[str, Any]) -> bool:
    signals = sel.get("join_ambiguity_signals") or {}
    q_hits = _quarantine_codes(target) & set(signals.get("quarantine_reason_codes") or [])
    u_hits = _unresolved_codes(target) & set(signals.get("unresolved_reason_codes") or [])
    return bool(q_hits or u_hits)


def _name_residue_detected(target: dict[str, Any], sel: dict[str, Any]) -> bool:
    return bool(is_deletion_residue(target))


def _publisher_link_ok(target: dict[str, Any], provider: str, policy: dict[str, Any],
                       sel: dict[str, Any]) -> dict[str, Any]:
    """R2 的四项资格判定，完全复用 data_model 的 classifier 与 publisher 规则。

    分成四个可独立断言的布尔位，是为了让配置里的四条 when_all 条件各自真的是一个条件，
    而不是同一个判断换三个名字（那样门禁形同虚设）。
    """
    rule = policy.get("publisher_entity_link") or {}
    source_types = {str(item).casefold() for item in rule.get("required_evidence_source_types") or []}
    required_fields = list(rule.get("required_evidence_fields") or [])
    detail = {"qualified_row": False, "url_is_entity": False, "provider_matches": False,
              "origin_is_entity_page": False, "ok": False, "url": "", "why": ""}
    rows = target.get("evidence") or []
    if not isinstance(rows, list):
        detail["why"] = "EVIDENCE_NOT_A_LIST"
        return detail
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("source_type") or "").casefold() not in source_types:
            continue
        if any(data_model._blank(row.get(field)) for field in required_fields):
            continue
        declared = _norm(row.get("declared_link_url"))
        declared_provider = str(row.get("link_url_provider") or "").casefold()
        if declared == _norm(row.get("source_url_or_ref")):
            continue  # 出处就是链接自己，不构成凭据（§17.3.1）
        detail["qualified_row"] = True
        detail["provider_matches"] = declared_provider == provider.casefold()
        found = data_model.classify_reference(declared, policy, field="declared_link_url",
                                             required_provider=provider)
        detail["url_is_entity"] = bool(found.get("provider")) and found.get("kind") == "entity"
        origin = data_model.classify_reference(_norm(row.get("source_url_or_ref")), policy,
                                               purpose="identity")
        detail["origin_is_entity_page"] = (not origin.get("provider")) and bool(
            data_model.reference_is_identity_qualifying(origin))
        if all(detail[key] for key in ("qualified_row", "url_is_entity", "provider_matches",
                                       "origin_is_entity_page")):
            detail["ok"] = True
            detail["url"] = declared
            return detail
        detail["why"] = ",".join(key for key in ("url_is_entity", "provider_matches",
                                                 "origin_is_entity_page") if not detail[key])
    if not detail["why"]:
        detail["why"] = "NO_PUBLISHER_SOURCE_TYPE_ROW"
    return detail


def _coordinate_pair(target: dict[str, Any]) -> str:
    lat, lng = target.get("lat"), target.get("lng")
    pair = map_contract.parse_coords("%s,%s" % (lat, lng)) if lat is not None and lng is not None else None
    if pair is None:
        pair = map_contract.parse_coords(target.get("coords"))
    return "%s,%s" % pair if pair else ""


def _alnum(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "", value or "")


def _local_name(target: dict[str, Any]) -> tuple[str, str]:
    names = target.get("names") if isinstance(target.get("names"), dict) else {}
    cn = _norm(names.get("cn"))
    if cn:
        return cn, "names.cn"
    disp = _norm(target.get("display_name"))
    return (disp, "display_name") if disp else ("", "")


def is_deletion_residue(target: dict[str, Any]) -> bool:
    """英文名是不是"把本地名里的汉字删掉剩下的残片"或整体括号片段（§4 禁止动作）。

    这不是相似度判断：只有两种可复核的结构形态——与去 CJK 残片逐字符相同，或整串被括号包住
    且括号外没有任何内容。像 'Cebu Port Pier 1'（本地名 宿务港1号码头）这种是独立英文名，不会被误判。
    """
    names = target.get("names") if isinstance(target.get("names"), dict) else {}
    en = _norm(names.get("en"))
    cn = _norm(names.get("cn"))
    if not en:
        return False
    if re.fullmatch(r"[（(\[【].+[)）\]】]", en):
        return True
    if cn and data_model.CJK_RE.search(cn) and _alnum(en) and _alnum(en) == _alnum(data_model.CJK_RE.sub("", cn)):
        return True
    return False


def authoritative_name(target: dict[str, Any]) -> tuple[str, str]:
    """按 data-model 的权威顺序取规范名称：names.en → display_name → canonical_name。

    若英文名被判为删字符残留，则改用有来源的本地正式名称（§4：不猜英文名，保留本地正式名称）。
    同时返回它来自哪个字段，供逐项报告证明"名称有来源"而不是渲染层现场拼的。
    """
    names = target.get("names") if isinstance(target.get("names"), dict) else {}
    en = _norm(names.get("en"))
    if en and not is_deletion_residue(target):
        return en, "names.en"
    if en and is_deletion_residue(target):
        local, field = _local_name(target)
        if local:
            return local, field + "(after_residue)"
    for field in ("display_name", "canonical_name"):
        raw = _norm(target.get(field))
        if raw:
            return raw, field
    return "", ""


def _name_state(target: dict[str, Any], sel: dict[str, Any]) -> str:
    """usable / local_only / placeholder / numeric_residue / corridor / absent 之一。"""
    raw, _field = authoritative_name(target)
    if not raw:
        return "absent"
    if data_model.is_placeholder_name(raw):
        return "placeholder"
    if re.fullmatch(r"[\d\s\-./]+", raw):
        return "numeric_residue"
    if re.search(r"→|->|\s+-\s+|—", raw):
        return "corridor"
    if data_model.is_manufactured_name(raw):
        return "placeholder"
    if data_model.CJK_RE.search(raw):
        return "local_only"
    return "usable"


def _primitive(name: str, cond: dict[str, Any], ctx: dict[str, Any]) -> bool:
    target, sel, provider, policy = ctx["target"], ctx["sel"], ctx["provider"], ctx["policy"]
    if name == "known_bad_link":
        return bool(_target_flags(target, sel)) or str(target.get("google_resolution_status")) == "WRONG_ENTITY"
    if name == "identity_status_in":
        return str(target.get("identity_status") or "") in [str(v) for v in cond.get("values") or []]
    if name == "identity_status_is":
        return str(target.get("identity_status") or "") == str(cond.get("value"))
    if name == "resolution_status_in":
        return str(target.get("google_resolution_status") or "") in [str(v) for v in cond.get("values") or []]
    if name == "resolution_status_is":
        return str(target.get("google_resolution_status") or "") == str(cond.get("value"))
    if name == "resolution_status_not_blocking":
        return str(target.get("google_resolution_status") or "") not in sel["resolution_status_blocking_named_search"]
    if name == "resolution_status_blocking":
        return str(target.get("google_resolution_status") or "") in sel["resolution_status_blocking_named_search"]
    if name == "identity_status_in_configured_allow_list":
        return str(target.get("identity_status") or "") in sel["identity_status_allowed_for_named_search"]
    if name == "entity_type_is":
        return str(target.get("entity_type") or "") == str(cond.get("value"))
    if name == "coordinate_status_is":
        return str(target.get("coordinate_status") or "") == str(cond.get("value"))
    if name == "name_usable_for_search":
        return _name_state(target, sel) == "usable"
    if name == "name_state_is_local_only":
        return _name_state(target, sel) == "local_only"
    if name == "join_ambiguity_signal":
        return _join_ambiguity_signal(target, sel)
    if name == "name_residue_detected":
        return _name_residue_detected(target, sel)
    if name == "name_unusable_because_placeholder":
        return _name_state(target, sel) == "placeholder"
    if name == "name_unusable_because_numeric_residue":
        return _name_state(target, sel) == "numeric_residue"
    if name == "name_unusable_because_corridor":
        return _name_state(target, sel) == "corridor"
    if name == "name_absent":
        return _name_state(target, sel) in ("absent",)
    if name == "publisher_entity_evidence_qualified":
        return bool(ctx["publisher"].get("qualified_row"))
    if name == "declared_link_url_classifies_entity":
        return bool(ctx["publisher"].get("url_is_entity"))
    if name == "provider_matches_button_provider":
        return bool(ctx["publisher"].get("provider_matches"))
    if name == "publisher_origin_is_entity_page":
        return bool(ctx["publisher"].get("origin_is_entity_page"))
    if name == "fallback":
        return True
    raise SelectionConfigError("未知原语 %r" % name)


PRIMITIVES = (
    "known_bad_link", "identity_status_in", "identity_status_is", "resolution_status_in",
    "resolution_status_is", "resolution_status_not_blocking",
    "identity_status_in_configured_allow_list", "entity_type_is", "coordinate_status_is",
    "name_usable_for_search", "name_state_is_local_only", "join_ambiguity_signal",
    "name_residue_detected", "name_unusable_because_placeholder",
    "name_unusable_because_numeric_residue", "name_unusable_because_corridor", "name_absent",
    "publisher_entity_evidence_qualified", "declared_link_url_classifies_entity",
    "provider_matches_button_provider", "publisher_origin_is_entity_page",
    "resolution_status_blocking", "fallback",
)


def notices_for(target: dict[str, Any], link_mode: str, sel: dict[str, Any],
                reason_code: str = "") -> list[str]:
    out: list[str] = []
    if link_mode == "NAMED_SEARCH" and str(target.get("criticality") or "") == "CRITICAL_ITINERARY":
        out.append("key_target_unverified")
    ident_multi = set(sel["multivalue_notice_states"]["identity_status"])
    reso_multi = set(sel["multivalue_notice_states"]["google_resolution_status"])
    if (str(target.get("identity_status") or "") in ident_multi
            or str(target.get("google_resolution_status") or "") in reso_multi
            or (link_mode == "NAMED_SEARCH" and _join_ambiguity_signal(target, sel))):
        if link_mode == "NAMED_SEARCH":
            out.append("ambiguous_multiple_results")
    for key in list(out):
        if key not in (sel.get("ui") or {}).get("notices", {}):
            raise SelectionConfigError("提示键 %r 未在 ui.notices 登记文案" % key)
    return out


def select(target_id: str, target: dict[str, Any], provider: str = "google",
           sel: dict[str, Any] | None = None, policy: dict[str, Any] | None = None,
           lookup: dict[str, Any] | None = None) -> Selection:
    sel = sel if sel is not None else load_selection()
    policy = policy if policy is not None else data_model.load_policy()
    result = Selection(target_id, provider, sel["selection_version"])
    if provider not in sel["providers"]:
        result.reason_code = "SELECT_BLOCKED_NO_HONEST_ENTRY"
        result.rule_id = "R0"
        result.evidence["unregistered_provider"] = provider
        return result
    publisher = _publisher_link_ok(target, provider, policy, sel)
    ctx = {"target": target, "sel": sel, "provider": provider, "policy": policy,
           "publisher": publisher}
    for rule in sel["state_machine"]:
        matched = _rule_matches(rule, ctx)
        if not matched:
            continue
        then = rule["then"]
        result.rule_id = str(rule.get("rule_id"))
        result.link_mode = str(then["link_mode"])
        result.reason_code = str(then["reason_code"])
        for override in rule.get("reason_code_overrides", []):
            if _primitive(override["if"]["primitive"], override["if"], ctx):
                result.reason_code = str(override["reason_code"])
                break
        result.evidence["matched_rule"] = result.rule_id
        result.signals = sorted({
            "join_ambiguity" if _join_ambiguity_signal(target, sel) else "",
            "name_residue_fallback" if _name_residue_detected(target, sel) else "",
            "local_name_only" if _name_state(target, sel) == "local_only" else "",
            "critical_target" if str(target.get("criticality") or "") == "CRITICAL_ITINERARY" else "",
        } - {""})
        if rule.get("isolate_existing_url"):
            legacy = _norm(target.get("google_url") if provider == "google" else target.get("apple_url"))
            if legacy:
                result.isolated_url = legacy
        if result.link_mode == "PUBLISHER_ENTITY_LINK":
            result.url = publisher.get("url", "")
        elif result.link_mode in ("NAMED_SEARCH", "COORDINATE"):
            if result.link_mode == "NAMED_SEARCH":
                query, used, seg = build_query(target, sel, lookup)
                if not query:
                    result.link_mode = "NONE"
                    result.reason_code = "SELECT_BLOCKED_NO_HONEST_ENTRY"
                    result.rule_id = "R8"
                else:
                    result.query_fields_used = used
                    result.name_source_field = seg.get("name_source_field", "")
                    result.url = build_url(provider, sel, query)
            else:
                pair = _coordinate_pair(target)
                result.url = build_url(provider, sel, "", pair) if pair else ""
                if not result.url:
                    result.link_mode = "NONE"
                    result.reason_code = "SELECT_BLOCKED_NO_HONEST_ENTRY"
                    result.rule_id = "R8"
        result.notices = notices_for(target, result.link_mode, sel, result.reason_code)
        return result
    return result


def select_all_providers(target_id: str, target: dict[str, Any],
                         sel: dict[str, Any] | None = None,
                         policy: dict[str, Any] | None = None,
                         lookup: dict[str, Any] | None = None,
                         providers: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """§3.3/§4 前言：逐 provider 独立执行，装配 dataset 的 `map_link_by_provider` 容器。

    这是该容器**唯一的装配点**（登记在 data-model.json::map_link_per_provider_container.writer）。
    生成器与渲染层都只读它的输出：不许自己拼 provider 列表、不许自己拼 URL、不许把某个 provider
    的证据复制给另一个 provider。请求一个未登记的 provider 直接报错——静默少一个按钮比报错更难查。
    """
    sel = sel if sel is not None else load_selection()
    registered = list(sel["providers"])
    chosen = list(providers) if providers else registered
    unknown = sorted(set(chosen) - set(registered))
    if unknown:
        raise SelectionConfigError("未登记的 provider 不得进入链接装配（§6.3）：%s" % unknown)
    container: dict[str, dict[str, Any]] = {}
    for provider in chosen:
        container[provider] = select(target_id, target, provider, sel,
                                     policy=policy, lookup=lookup).as_record()
    return container


def _rule_matches(rule: dict[str, Any], ctx: dict[str, Any]) -> bool:
    alls = rule.get("when_all") or []
    anys = rule.get("when_any") or []
    if alls and not all(_primitive(cond["primitive"], cond, ctx) for cond in alls):
        return False
    if anys and not any(_primitive(cond["primitive"], cond, ctx) for cond in anys):
        return False
    if not alls and not anys:
        return False
    return True


RECONCILE_REQUIRED_KEYS = ("ratified_by", "rule", "implemented_by", "name_source_priority",
                           "downgrade_only_fields", "level_vocabulary_after",
                           "verification_status_after", "self_attestation_reason_code",
                           "template_name_reason_code", "provenance_kept",
                           "selection_rederivation")


def _reconcile_config(sel: dict[str, Any]) -> dict[str, Any]:
    cfg = sel.get("legacy_state_reconciliation") or {}
    missing = [key for key in RECONCILE_REQUIRED_KEYS if not cfg.get(key)]
    if missing:
        raise SelectionConfigError(
            "legacy_state_reconciliation 缺键 %s：降级规则必须由登记驱动，不能在代码里临场决定"
            "把哪个字段改成什么" % missing)
    return cfg


def reconcile_legacy_state(target_id: str, target: dict[str, Any], *,
                           sel: dict[str, Any] | None = None,
                           policy: dict[str, Any] | None = None,
                           lookup: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """把与四维诚实状态矛盾的 legacy 声明降到一致，并接回该行自己有来源的名字。

    业主 2026-10-30 裁决（V6-D 正式生成逼出的问题）：加州 151 条 canonical_name 仍是 v4.2.0 造的
    'California Venue'，同一行却写着 verification_status=verified / target_level=verified_coordinate，
    而 identity_status=UNVERIFIED。旧门禁读的是 legacy 字段，于是 403 条目标一条也出不去；改数据不是
    为了让门禁闭嘴，而是让文件里不再同时存在两套相反的说法。

    三条硬边界：只做**降级**（绝不把 UNVERIFIED 升成 VERIFIED、绝不把档位升高）；名字只从该行已有
    字段接回（零外部查询，不做任何字符级修补）；原值留在 migration.legacy_state_reconciliation，
    W2 的 quarantine / unresolved_fields 一条都不删。入参永不被修改。
    """
    sel = sel or load_selection()
    cfg = _reconcile_config(sel)
    row = dict(target)
    actions: list[dict[str, str]] = []

    def record(field: str, before: Any, after: Any, reason: str,
               allowed: tuple[str, ...] = (), provenance: tuple[Any, Any] | None = None) -> None:
        whitelist = tuple(cfg["downgrade_only_fields"]) + tuple(allowed)
        if field not in whitelist:
            raise SelectionConfigError(
                "reconcile 试图改不在登记白名单里的字段 %s" % field)
        ledger_before, ledger_after = (before, after) if provenance is None else provenance
        migration = row.setdefault("migration", {})
        if not isinstance(migration, dict):
            migration = {}
            row["migration"] = migration
        ledger = migration.setdefault("legacy_state_reconciliation",
                                      {"rule": "legacy_state_reconciliation",
                                       "ratified_by": cfg["ratified_by"], "fields": {}})
        ledger["fields"][field] = {"before": ledger_before, "after": ledger_after,
                                   "reason": reason}
        row[field] = after
        actions.append({"field": field, "before": str(before or "")[:160],
                        "after": str(after or "")[:160], "reason": reason})

    identity = str(row.get("identity_status") or "").upper()
    verdict = select(target_id, row, "google", sel=sel, policy=policy,
                     lookup=lookup).as_record()
    mode = str(verdict.get("link_mode") or "")

    current_name = str(row.get("canonical_name") or "").strip()
    if data_model.is_manufactured_name(current_name):
        candidate, source = authoritative_name(row)
        allowed = [str(item) for item in cfg["name_source_priority"]]
        if candidate and not data_model.is_manufactured_name(candidate) \
                and any(source == item or source.startswith(item + "(") for item in allowed):
            record("canonical_name", current_name, candidate,
                   "RELINK_FROM_%s" % source.split("(")[0].upper().replace(".", "_"))
        elif candidate and candidate != current_name:
            record("canonical_name", current_name, candidate, "RELINK_FROM_UNLISTED_SOURCE_"
                   + source.upper())

    if mode != "PUBLISHER_ENTITY_LINK" and identity in {"UNVERIFIED", "UNRESOLVED", "AMBIGUOUS"}:
        level = str(row.get("target_level") or "")
        downgraded = str(cfg["level_vocabulary_after"].get(
            "named_search" if mode == "NAMED_SEARCH" else "none") or "")
        if level in map_contract.VERIFIED_LEVELS and downgraded and level != downgraded:
            record("target_level", level, downgraded, "DOWGRADE_TO_HONEST_LEVEL")
        if str(row.get("verification_status") or "") == "verified":
            record("verification_status", row.get("verification_status"),
                   cfg["verification_status_after"], "DOWGRADE_LEGACY_VERIFICATION_CLAIM")

    source_url = str(row.get("source_url") or "").strip()
    google_url = str(row.get("google_url") or "").strip()
    if source_url and source_url == google_url \
            and _quarantine_codes(row) & {cfg["self_attestation_reason_code"]}:
        record("source_url", source_url, "", "DROP_SELF_ATTESTED_SOURCE_URL")

    rederive = cfg.get("selection_rederivation") or {}
    if rederive.get("after_downgrade"):
        registered = list(rederive.get("fields") or [])
        # V6-N：`{provider}_url` 是容器值的 legacy 单值镜像，必须一起重建。V6-L 只重建了
        # map_link_url + 容器，于是 V6-D 端到端实测里 403/403 行的 google_url 仍然不等于读者
        # 实际点到的那条 href——审计面存着两套 URL，视觉门按 legacy 那套报「5 个 URL 被多个 POI
        # 共用」，而那根本不是交付形态。镜像对齐后，同一目标在任何一面都只有一个答案。
        mirrors = sorted("%s_url" % name for name in (sel.get("providers") or {}))
        expected = list(WRITABLE_FIELDS) + ["map_link_by_provider"] + mirrors
        if sorted(registered) != sorted(expected):
            raise SelectionConfigError(
                "selection_rederivation.fields 与选择器实际可写字段不一致（登记 %s / 实现 %s）："
                "重建清单必须由同一处定义，否则改向时会漏重建一个字段"
                % (sorted(registered), sorted(expected)))
        container = select_all_providers(target_id, row, sel=sel, policy=policy, lookup=lookup)
        primary = str(sel.get("primary_provider") or "google")
        rec = dict(container.get(primary) or {})
        for field in WRITABLE_FIELDS:
            if field in rec and row.get(field) != rec[field]:
                record(field, row.get(field), rec[field], "REBUILD_LINK_STATE",
                       allowed=tuple(registered))
        if row.get("map_link_by_provider") != container:
            def summary_of(container_value):
                return {name: {"link_mode": str((item or {}).get("link_mode") or ""),
                               "reason": str((item or {}).get("link_selection_reason") or ""),
                               "url": str((item or {}).get("map_link_url") or "")}
                        for name, item in (container_value or {}).items()}
            # 台账存摘要、字段存完整容器：把摘要写进字段本身会让下一次重建又看到「容器不同」，
            # 一个不幂等的收口等于给重放埋雷。
            record("map_link_by_provider", container, container, "REBUILD_LINK_STATE",
                   allowed=tuple(registered),
                   provenance=(summary_of(row.get("map_link_by_provider")),
                               summary_of(container)))
        for name in sorted(sel.get("providers") or {}):
            mirror = "%s_url" % name
            if mirror not in row:
                continue            # 不为了对齐而凭空造字段：这一行本来没有这个镜像就跳过
            value = str((container.get(name) or {}).get("map_link_url") or "")
            if str(row.get(mirror) or "") != value:
                record(mirror, row.get(mirror), value, "REBUILD_LEGACY_URL_MIRROR",
                       allowed=tuple(registered))
    return row, actions
