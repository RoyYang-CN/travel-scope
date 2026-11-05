"""Collect-stage prose translation bridge (checklist SS2.2.2, owner decision: machine-translate
and store in the sealed input, so the build never invents English at render time).

Two subcommands, deliberately split:

  --export  list every Chinese fragment the English product needs, with a stable id
  --apply   fold a translation table back into dataset.json (prose_en), refusing partial work

The table is authored by the model and is NOT externally verified; provenance is recorded so
the owner can spot-check before release. A fragment with no entry is a hard error, never a
silent Chinese fallback.

MT-C (owner ruling 2026-11-01) turned that last sentence into code: provenance must be a
structured object with every registered field filled, entries must be complete against the
fragment set recomputed from the dataset (missing / stale / duplicate all block), the table
digest excludes its own digest field, and the write is bytes-only with a post-write SHA
recompute. Nothing is written unless the whole table passes — 「半份英文」比「整页 pending」更坏。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

CNCJK = re.compile(r"[\u4e00-\u9fff]")
NOTE_PREFIX = re.compile(r"^(?P<label>【[^】]*】)?\s*(?P<body>.*)$", re.S)
PRICE_BODY = re.compile(
    r"^约?\s*[¥￥$]?[\d.,]+\s*(?:美元|元|人民币)?\s*(?:/\s*(?:晚|人|间|夜|房))?\s*"
    r"(?:\(\s*折合约?\s*[¥￥$]?[\d.,]+\s*(?:元|美元)\s*(?:/\s*(?:晚|人|间|夜|房))?\s*\))?\s*。\s*")
FREE_BODY = re.compile(r"^(?P<free>免费[^。]*|\([^)]*Free[^)]*\))\s*。\s*")
POI_NOTE_ADDRESS = re.compile(r"^(hotels|restaurants|cafes|attractions|dive_sites)\[(\d+)\]\.note$")
LABEL_EN = {
    "人均参考": "Per person", "价格参考": "Reference price", "门票参考": "Admission",
    "参考预算": "Budget", "人均": "Per person",
}

# block -> {column index: fragment kind}. Each entry is a column assets/spa-layout.js prints in
# the English page; name/coordinate/status/date/url columns are deliberately absent because the
# renderer resolves those through the bilingual pairs, the lexicon or enMetrics.
# MT-B4：键可以是**下标**（位置数组行）或**字段名**（对象行）。两棵候选的载荷形状不同是实测事实
# （同一列在审计输入里是数组格、在交付载荷里可能已是对象格），采集器以前遇到对象行直接 `continue`，
# 于是那一列无论登记与否都收不到——这是「列明明读了却报没登记」的第二个成因。
# 目前**没有**需要按 prose 登记的对象列：transport_nodes 的对象形状里 type 归类别词根通道、
# place 归专名显示通道（见 references/category-lexicon.json::category_columns 与
# references/display-name-channel.json），都不该在翻译表里再建一个第二个来源。
RENDERED_COLUMNS: dict[str, dict] = {
    "budget": {2: "day_theme"},
    "routes": {4: "route_mode", 6: "route_desc"},
    "destinations": {2: "dest_region", 3: "dest_experience", 4: "dest_days",
                     5: "dest_season", 6: "dest_arrival", 7: "dest_in_route"},
    "worth_it": {3: "worth_desc", 4: "worth_audience", 5: "worth_duration",
                 6: "worth_timing", 7: "worth_access", 8: "worth_tip"},
    "local_chains": {3: "chain_type", 4: "chain_desc", 5: "chain_use",
                     6: "chain_price", 7: "chain_coverage"},
    "packing": {0: "packing_group", 3: "packing_where", 6: "packing_note"},
    "practical": {0: "practical_title", 1: "practical_body"},
    "transport": {0: "leg_title", 1: "leg_mode", 5: "leg_schedule", 9: "leg_buffer",
                  10: "leg_guide", 11: "leg_source", 15: "leg_warning"},
    "transport_nodes": {0: "node_region", 3: "node_type", 5: "node_desc"},
}


SCRIPTS = Path(__file__).resolve().parent
LAYOUT_JS = SCRIPTS.parent / "assets" / "spa-layout.js"
# 渲染层拼进 DOM 的连接符：定位缺口时先剥掉它们再回数据里找，否则「DOM 文本」永远对不上
# 「数据单元格」，就会被误记成渲染层字面量（见 locate_gaps 的 unregistered/literal 分流）。
# MT-1（业主 2026-10-31）把 / 从这里删掉：它确实是若干渲染组合的分隔符，但同时也是地址、路线名
# 与专名里的正文字符——/中文名/ 一旦能匹配 中文名，就是把两条不同的数据格混成一条。
# 通用拆分只留 · 与 | （见 COMPOSITE_SPLIT）；/ 两种角色都不许靠剥边来消歧。
JOINERS = "·| \u3000"
# 判定闭集：verdict 只允许这七个值，登记见 data-model.json::english_gap_verdicts。
# MT-B（2026-10-31）补的两档不是「新缺口」，而是**换了负责面的旧缺口**：
#   proper_name   —— 专名显示面（references/display-name-channel.json 的 tier1 名对 / tier2 机器翻译
#                    显示名）负责，不进翻译表；写进 prose_en 就是让散文表冒充专名来源。
#   money_scaffold —— 渲染层格式化器（money() 的登记金额语法 + enMetrics() 的度量语法）负责，
#                    业主 REVISE 第 5 条点名的「菲律宾七条价格不是 prose 问题」就是这一档。
VERDICTS = ("dataset_cell", "dataset_cell_unregistered", "render_composite",
            "renderer_literal", "unattributed", "proper_name", "money_scaffold")

# 格式化器槽：地址 → 负责它的渲染层函数。翻译表对这些格子一律 applicable=false。
FORMATTER_SLOTS = {("transport", 3): "money() 登记金额语法 + enMetrics() 度量兜底"}
ADDRESS_SLOT = re.compile(r"^dataset\['(?P<block>[a-z_]+)'\]\[\d+\]")
ADDRESS_KEY = re.compile(r"^\[(?:(?P<idx>\d+)|'(?P<field>[^']+)')\]")

# ---------------------------------------------------------------------------------------------
# MT-C：翻译表 provenance 强制合同。字段清单、占位串闭集、摘要自排除规则、禁绕路面
# 全部住在 references/prose-translation-contract.json，这里只是**唯一实现**（双向闭合测试
# scripts/test_v422_prose_translation_contract.py 保证登记的字段真在被校验、用的字段真在册）。
#
# 为什么这一层必须存在（实测，不是预防性加码）：旧 apply_table 的取法是
#     report["provenance"] = (table_raw.get("provenance") ...) or "unlabelled translation table"
# 而 gen_travel_scope.py:453 只在 `isinstance(payload.get("prose_en_provenance"), dict)` 时才把它
# 并进载荷——字符串来源被构建侧**静默丢弃**。也就是说：读者页可以带着整套没有出处的英文散文出货，
# 台账上一片安静，而合同里那句「provenance 为空时 --apply 自己报错」当时是纸面话。
CONTRACT_PATH = SCRIPTS.parent / "references" / "prose-translation-contract.json"

# collect_fragments 会产出的 kind 全集（本表只接 collect_fragments 的 fragment，专名归 display-name-channel）。
def registered_kinds() -> set:
    kinds = {str(kind) for columns in RENDERED_COLUMNS.values() for kind in columns.values()}
    return kinds | {"poi_note", "itin", "coverage_desc"}


def contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _blank(value) -> bool:
    """字段算不算没填：None / 空串 / 纯空白 / 空容器都算没填（数字 0 与 false 不算）。"""
    if value is None:
        return True
    if isinstance(value, (str, int, float, bool)):
        return not str(value).strip()
    if isinstance(value, (list, tuple, dict, set)):
        return not value
    return not str(value).strip()


def _as_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def placeholder_re() -> re.Pattern:
    patterns = contract()["placeholder_rejection"]["patterns"]
    return re.compile("|".join("(?:%s)" % item for item in patterns), re.IGNORECASE)


def _field_problems(obj: dict, required: list, findings: list, code_missing: str,
                   code_placeholder: str = "") -> None:
    """必填字段：缺失与「填了个占位串」同等阻断（分两码报，处置话术不一样）。

    code_placeholder 传空＝这一组字段不做占位串检查（只用于 entry 的结构字段本身，
    它们的空值已由 missing 码覆盖；provenance 一律两套都查）。
    """
    missing = [field for field in required if _blank(obj.get(field))]
    if missing:
        findings.append({"code": code_missing, "detail": ",".join(missing)})
    if not code_placeholder:
        return
    pattern = placeholder_re()
    placeholder = [field for field in required
                   if field in obj and not _blank(obj[field])
                   and pattern.match(_as_text(obj[field]).strip())]
    if placeholder:
        findings.append({"code": code_placeholder, "detail": ",".join(placeholder)})


def self_digest_keys() -> tuple:
    """自摘要字段名从登记面读（digest_rule.excluded_keys），代码里不留第二份。"""
    keys = contract()["digest_rule"].get("excluded_keys") or ["table_sha256"]
    return tuple(keys)


def _strip_self_digest(node, keys=None):
    """按**键名**逐层剔除自摘要字段，不按位置——在 provenance 里再塞一个同名字段也绕不过去。"""
    keys = keys if keys is not None else self_digest_keys()
    if isinstance(node, dict):
        return {key: _strip_self_digest(value, keys) for key, value in node.items()
                if key not in keys}
    if isinstance(node, list):
        return [_strip_self_digest(item, keys) for item in node]
    return node


def digest_of_table(payload: dict) -> str:
    """翻译表摘要＝canonical JSON 的 SHA-256，且**排除摘要字段自身**（业主 2026-11-01 明令）。"""
    canonical = json.dumps(_strip_self_digest(payload), ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()


ENTRY_ID_SHAPE = re.compile(r"^f[0-9a-f]{10}$")


def duplicate_entry_ids(text: str) -> list[str]:
    """在**解析前**抓 entries 里重复的键：json.loads 会静默保留最后一条，重复就此隐身。

    检测面是「id 形状的键」——357 行手写/生成表里最可能的多余项形态。其它键名重复不在本码覆盖面内，
    这一条限制写在合同 completeness_rule 里，不冒充全量。
    """
    marks: list[list] = []

    def hook(pairs):
        keys = [key for key, _ in pairs]
        dupes = sorted({key for key in keys
                        if ENTRY_ID_SHAPE.match(str(key)) and keys.count(key) > 1})
        if dupes:
            marks.append(dupes)
        return dict(pairs)

    json.loads(text, object_pairs_hook=hook)
    return sorted({str(key) for group in marks for key in group})


def validate_table(dataset: dict, table_raw, *, run_name: str = "",
                   source_dataset_sha256: str = "", fragments: list | None = None,
                   duplicate_ids: list | None = None) -> dict:
    """把一张翻译表放到 MT-C 合同下量一遍，返回**逐条阻断项**，不写任何东西。

    判据顺序是设计的一部分：先结构与来源（表本身站不站得住），再逐条 entry，最后才是
    完整性对照（缺项/陈旧项/多余项）。完整性放到最后，是因为它要拿 collect_fragments 现算的分母
    来比——那个分母才是权威，表自带的计数一律不作数。
    """
    reg = contract()
    findings: list[dict] = []
    raw = list(fragments) if fragments is not None else collect_fragments(dataset, skip_covered=False)
    ownership = classify_fragment_ownership(dataset, raw)
    worklist = ownership["worklist"]
    # 形状核验跟着进表门：判定与写盘必须是同一套口径，否则「所有权坏了但表照写」这条路还开着。
    for item in ownership["shape"]["blocking"]:
        findings.append({"code": "dataset_shape_blocked",
                         "detail": "%s｜形状不成立就不校验、不写盘：按错位的主人写 prose_en "
                                   "比整页继续 pending 更糟" % item["detail"]})
    work_ids = {fragment["id"] for fragment in worklist}
    blocked_by_outcome = ownership["blocked_ids"]
    blocked_of = {ident: outcome for outcome, ids in blocked_by_outcome.items() for ident in ids}
    by_id = {fragment["id"]: fragment for fragment in raw}
    entries_raw = table_raw.get("entries") if isinstance(table_raw, dict) else None
    report = {"contract": CONTRACT_PATH.name, "schema_version_expected":
              reg["table_shape"]["schema_version_value"], "fragments": len(raw),
              "findings": findings, "missing": [], "stale_ids": [], "duplicate_ids": [],
              "entry_records": {}, "status": "FAIL", "blocking": len(reg["blocking_findings"]),
              "ownership": ownership["accounting"], "shape": ownership["shape"],
              "worklist": worklist, "blocked_of": blocked_of}
    if not isinstance(table_raw, dict):
        findings.append({"code": "table_not_object", "detail": type(table_raw).__name__})
        report["missing"] = [{"id": f["id"], "cn": f["cn"][:60], "kind": f["kind"]}
                             for f in worklist]
        return report

    for field in reg["table_shape"]["required_top_level_fields"]:
        if field not in table_raw:
            findings.append({"code": "missing_top_level_field", "detail": field})
    if str(table_raw.get("schema_version") or "") != reg["table_shape"]["schema_version_value"]:
        findings.append({"code": "schema_version_mismatch",
                         "detail": "%r != %r" % (table_raw.get("schema_version"),
                                                 reg["table_shape"]["schema_version_value"])})

    provenance = table_raw.get("provenance")
    table_provenance = provenance if isinstance(provenance, dict) else {}
    allowed = reg["identity_and_lineage_rule"]["review_status_allowed"]
    required_status = str(reg["identity_and_lineage_rule"]
                          ["review_status_value_now_required"]).strip()
    if not isinstance(provenance, dict):
        findings.append({"code": "provenance_not_object",
                         "detail": "实测类型 %s：字符串占位（例如 \"machine translation\"）与缺失同等阻断"
                                   % type(provenance).__name__})
    else:
        _field_problems(provenance, reg["table_provenance_required_fields"], findings,
                        "provenance_missing_fields", "provenance_placeholder_fields")
        status = str(provenance.get("review_status") or "").strip()
        if status and status not in allowed:
            findings.append({"code": "review_status_not_allowed",
                             "detail": "%r 不在闭集 %s" % (status, ",".join(allowed))})
        elif status != required_status:
            # 光有闭集挡不住我自己：owner_reviewed 也在闭集里。放开这一格必须是业主改登记面，
            # 不是写表的人顺手改一个字段——357 条翻完不等于业主复核完成。
            findings.append({"code": "review_status_not_allowed",
                             "detail": "表级 review_status=%r，当前登记要求 %r（业主复核未完成前不许自称 reviewed）"
                                       % (status, required_status)})
        if run_name:
            for key, value in (("run", table_raw.get("run")),
                               ("provenance.run_dir", provenance.get("run_dir"))):
                text = _as_text(value).strip().rstrip("/\\")
                if text and Path(text).name != run_name:
                    findings.append({"code": "run_dir_mismatch",
                                     "detail": "%s=%s 与被写的 run（%s）不是同一棵"
                                               % (key, text, run_name)})
            if _blank(provenance.get("run_dir")):
                findings.append({"code": "run_dir_mismatch", "detail": "provenance.run_dir 空"})
        if source_dataset_sha256:
            recorded = _as_text(provenance.get("source_dataset_sha256")).strip().upper()
            if recorded != source_dataset_sha256:
                findings.append({"code": "source_dataset_sha256_mismatch",
                                 "detail": "表登记 %s，现场重算 %s：这张表不是为这份输入导出的，"
                                           "套上来就是把译文配错原句" % (recorded or "空",
                                                                     source_dataset_sha256)})

    if not isinstance(entries_raw, dict):
        findings.append({"code": "entries_not_object", "detail": type(entries_raw).__name__})
        report["missing"] = [{"id": f["id"], "cn": f["cn"][:60], "kind": f["kind"]}
                             for f in worklist]
        return report

    required_entry = reg["entry_required_fields"]
    required_entry_prov = reg["entry_provenance_required_fields"]
    kinds = registered_kinds()
    # MT-D2 第 6 步接线：结构事实对账的尺子住在 scripts/prose_reconcile.py +
    # references/prose-glossary.json，这里只调用一次面（实体名/目的地名从既有登记面读），
    # 逐条 entry 复用。以前 MT-C 把这一层写进 no_new_facts.enforced_by 时两个文件都不存在——
    # 「登记了却没执行」正是本项目反复出事的形状，现在它真的在门里跑了。
    # 码名不在本文件 blocking_findings 里重复登记：一个事实一个出处
    # （prose-glossary.json::finding_codes，由 test_v422_prose_glossary.py 双向闭合）。
    import prose_reconcile
    reconcile = prose_reconcile.checker(dataset)
    seen_cn: dict[str, str] = {}
    for ident, entry in entries_raw.items():
        if not isinstance(entry, dict):
            findings.append({"code": "entry_shape_not_object",
                             "detail": "%s 是 %s：bare 字符串 entries 形态不再接受（答不了谁翻的、"
                                        "按哪份输入翻的、复核过没有）" % (ident, type(entry).__name__)})
            continue
        record = dict(entry)
        record.setdefault("id", ident)
        _field_problems(record, required_entry, findings, "entry_missing_fields", "")
        if str(record.get("id") or "") != ident:
            findings.append({"code": "entry_missing_fields",
                             "detail": "%s 的 entry.id=%r 与键不一致" % (ident, record.get("id"))})
        cn = _as_text(record.get("cn"))
        if _digest(cn) != ident:
            findings.append({"code": "entry_id_digest_mismatch",
                             "detail": "%s != f+sha256(cn)[:10]＝稳定 id 与原文互推不上（译文可能挂在别的句子上）"
                                       % ident})
        fragment = by_id.get(ident)
        if fragment and fragment["cn"] != cn:
            findings.append({"code": "entry_cn_mismatch",
                             "detail": "%s 表里原文与数据集原文不等：%r vs %r"
                                        % (ident, cn[:40], fragment["cn"][:40])})
        # MT-D 第 6/7 条的牙齿：被 block 的内容不许靠「顺手也翻一条」进表。
        # prose_en 按内容键、渲染优先级高于类别与专名面，一条 blocked 译文进了表就是把别的通道的
        # 来源换成散文表（第二来源）；owner_unprovenanced_blocked 那批更糟——tr() 实测
        # en_text_replacements 抢在 prose_en 上面，写进去既不会到读者眼前，又多一条查不到来源的英文。
        if ident in blocked_of:
            findings.append({"code": "entry_for_blocked_fragment",
                             "detail": "%s 的所有权判定是 %s，仍被写进翻译表：%r——"
                                       "被 block 的条目留在它自己的通道里等处置，不降级进表"
                                       % (ident, blocked_of[ident], cn[:40])})
        kind = _as_text(record.get("kind"))
        if kind not in kinds:
            findings.append({"code": "entry_kind_unregistered",
                             "detail": "%s 的 kind=%r 不是 collect_fragments 会产出的任何一类"
                                       % (ident, kind)})
        addresses = record.get("addresses")
        if not isinstance(addresses, list) or not addresses:
            findings.append({"code": "entry_addresses_empty",
                             "detail": "%s 没有地址：这条译文找不到落点，只能算猜" % ident})
        english = _as_text(record.get("en")).strip()
        if not english:
            findings.append({"code": "entry_en_empty", "detail": ident})
        elif CNCJK.search(english):
            findings.append({"code": "entry_en_contains_cjk",
                             "detail": "%s 的 en 仍含汉字：%r——含汉字的「英文」就是把没翻的原文当翻过了"
                                        % (ident, english[:40])})
        else:
            # MT-D2 第 6 步：结构事实对账（数字/日期/币种/URL/实体名/目的地/固定措辞/单位制式）。
            findings.extend(reconcile(cn, english))
        if cn in seen_cn and seen_cn[cn] != ident:
            findings.append({"code": "duplicate_entry_cn",
                             "detail": "同一原文 %r 落在 %s 与 %s 两条 entry 上"
                                       % (cn[:40], seen_cn[cn], ident)})
        seen_cn.setdefault(cn, ident)
        entry_provenance = record.get("provenance")
        if not isinstance(entry_provenance, dict):
            findings.append({"code": "entry_provenance_not_object",
                             "detail": "%s 是 %s" % (ident, type(entry_provenance).__name__)})
        else:
            _field_problems(entry_provenance, required_entry_prov, findings,
                            "entry_provenance_missing_fields",
                            "entry_provenance_placeholder_fields")
            recorded_sha = _as_text(entry_provenance.get("source_fragment_sha256")).strip().upper()
            live_sha = hashlib.sha256(cn.encode("utf-8")).hexdigest().upper()
            if recorded_sha and recorded_sha != live_sha:
                findings.append({"code": "entry_provenance_missing_fields",
                                 "detail": "%s 的 source_fragment_sha256=%s 与现场重算 %s 不等"
                                            % (ident, recorded_sha[:12], live_sha[:12])})
            entry_status = str(entry_provenance.get("review_status") or "").strip()
            if entry_status and entry_status != required_status:
                findings.append({"code": "review_status_not_allowed",
                                 "detail": "%s 的 review_status=%r，当前登记要求 %r"
                                            % (ident, entry_status, required_status)})
            drift = [field for field in ("engine", "engine_version", "language_direction",
                                         "glossary_version")
                     if field in table_provenance and field in entry_provenance
                     and _as_text(entry_provenance.get(field)).strip()
                     != _as_text(table_provenance.get(field)).strip()]
            if drift:
                findings.append({"code": "entry_provenance_inconsistent_with_table",
                                 "detail": "%s 的 %s 与表级 provenance 不等：一张表里混进另一台引擎/"
                                           "另一版术语表产出的条目，就必须按两张表分别登记来源"
                                           % (ident, ",".join(drift))})
        report["entry_records"][ident] = record

    # 缺项按**通过校验的 entry** 算，不按文件里出现过这个 id 算：entries 写成裸字符串时
    # id 是在的，但它答不了任何一问，把它当「有译文」就是假完整。
    # 分母是 MT-D 的 worklist（PROSE_REQUIRED 那批），不是原始清册也不是旧的文本相减结果：
    # 被 block 的条目本来就不该有 prose 译文，拿它们算缺项等于把「别的通道没做好」写成「翻译表缺行」。
    report["missing"] = [{"id": f["id"], "cn": f["cn"][:60], "kind": f["kind"]}
                         for f in worklist if f["id"] not in report["entry_records"]]
    for item in report["missing"]:
        findings.append({"code": "fragment_missing_from_table",
                         "detail": "%s (%s) %r" % (item["id"], item["kind"], item["cn"][:40])})
    report["stale_ids"] = sorted(str(ident) for ident in entries_raw if ident not in by_id)
    for ident in report["stale_ids"]:
        findings.append({"code": "stale_entry_id",
                         "detail": "%s 不在今天由 collect_fragments 现算的 fragment 集合里："
                                   "数据变了，这张表是旧数据的产物，不许「多余的那条留着不管」" % ident})
    for ident in duplicate_ids or []:
        findings.append({"code": "duplicate_entry_id",
                         "detail": "%s 在表的 entries 里出现了不止一次：json.loads 会静默保留最后一条，"
                                   "于是「以为翻了两条、其实只剩一条」，而键在、缺项查不到" % ident})
    recomputed = digest_of_table(table_raw)
    recorded_digest = _as_text(table_raw.get("table_sha256")).strip().upper()
    if recorded_digest != recomputed:
        findings.append({"code": "table_sha256_mismatch",
                         "detail": "文件值 %s，复算值 %s（复算已排除 table_sha256 自身）"
                                   % (recorded_digest or "空", recomputed)})
    report["table_sha256_recomputed"] = recomputed
    report["status"] = "PASS" if not findings else "FAIL"
    return report



def _digest(text: str) -> str:
    return "f" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def dataset_value_index(dataset: dict) -> dict[str, list[str]]:
    """每一个数据字符串值 → 它在数据集里的地址；同一句带连接符的 DOM 形态也一起登记。

    只做结构遍历，不判断哪一列「该翻」——那条合同是 RENDERED_COLUMNS，仍然只有它自己一处定义。
    本索引回答的是更窄的一个问题：这句话到底在不在数据里。以前答不了，就把答不上的都算成
    「渲染层字面量」，等于用工具的盲区替业主下结论。
    """
    index: dict[str, list[str]] = {}

    def put(text: str, address: str) -> None:
        value = str(text or "").strip()
        if not value or not CNCJK.search(value):
            return
        for key in {value, value.strip(JOINERS).strip()}:
            if key:
                index.setdefault(key, [])
                if address not in index[key]:
                    index[key].append(address)

    def walk(node, address: str) -> None:
        if isinstance(node, str):
            put(node, address)
        elif isinstance(node, dict):
            for key, item in node.items():
                walk(item, "%s[%r]" % (address, key))
        elif isinstance(node, (list, tuple)):
            for position, item in enumerate(node):
                walk(item, "%s[%d]" % (address, position))

    walk(dataset, "dataset")
    return index


def layout_js_text() -> str:
    """渲染层字面量的唯一出处：assets/spa-layout.js 的真实字节，量不到就当没这回事。"""
    return LAYOUT_JS.read_text(encoding="utf-8") if LAYOUT_JS.is_file() else ""


def note_price_prefix(cn_note: str) -> tuple[str, str]:
    """Split a generated note into its money scaffolding and the prose that needs translation."""
    match = NOTE_PREFIX.match(str(cn_note or "").strip())
    if not match:
        return "", str(cn_note or "").strip()
    label = (match.group("label") or "").strip("【】")
    body = match.group("body").strip()
    price = PRICE_BODY.match(body)
    head_bits = []
    if label:
        head_bits.append(LABEL_EN.get(label, label))
    if price:
        amount = re.search(r"[¥￥$]?[\d.,]+\s*(?:美元|元|人民币)?", price.group(0))
        conv = re.search(r"折合约?\s*[¥￥$]?([\d.,]+)", body[:price.end()])
        money = (amount.group(0).strip() if amount else "")
        money = money.replace("美元", " USD").replace("人民币", " CNY").replace("元", " CNY")
        if not money.startswith("$") and not money.startswith("¥"):
            money = "$" + money if label in ("人均参考", "价格参考") else money
        bit = money
        if conv:
            # 'Y' is not a currency anyone recognises; the source note says 折合约 ¥1044 元, so the
            # renminbi keeps the renminbi sign and the reader can tell the two numbers apart.
            bit += f" (≈¥{conv.group(1)})"
        head_bits.append(bit)
        body = body[price.end():]
    else:
        free = FREE_BODY.match(body)
        if free:
            head_bits.append("Free entry")
            body = body[free.end():]
    prefix = (", ".join(b for b in head_bits if b))
    return (prefix + ". " if prefix else ""), body


def renderable_names(dataset: dict) -> set[str]:
    """Names the SPA already resolves from evidence or bilingual pairs, so they must not be
    duplicated here: a second wording for the same POI is a new way to contradict the source.

    MT-B2/B3 之后这条规则覆盖面更大：**别的通道已经负责**的字符串都不该进翻译表——
      · D.category_en（词根组合出的类别标签）；
      · D.name_pairs / D.machine_translated_display_name（专名显示面，带来源）；
      · 金额与度量骨架（由 money()/enMetrics() 的登记语法出）走的是判定分流，不在这份名单里，
        因为它们是「这一格归格式化器」而不是「这个字符串已有英文」。
    把它们当 prose fragment，等于给同一条文本建两个来源，两边迟早互相打脸。
    """
    names: set[str] = set()
    for key, target in (dataset.get("map_targets") or {}).items():
        tail = str(key).split("|")[-1].strip()
        if tail:
            names.add(tail)
        if isinstance(target, dict) and target.get("display_name_cn"):
            names.add(str(target["display_name_cn"]).strip())
    for rows in (dataset.get("destinations") or [], dataset.get("routes") or [],
                 dataset.get("destination_coverage") or []):
        for row in rows:
            if isinstance(row, list) and row and row[0]:
                names.add(str(row[0]).strip())
    for table in ("category_en", "name_pairs", "machine_translated_display_name"):
        names |= {str(k).strip() for k in (dataset.get(table) or {}) if str(k).strip()}
    return names


def collect_fragments(dataset: dict, *, skip_covered: bool = True) -> list[dict]:
    """Every Chinese fragment the English product renders, excluding what rules already cover.

    RENDERED_COLUMNS is the contract between the renderer and this collector: a column the SPA
    prints must appear here, or the EN page falls back to '(translation pending)'. It lists only
    columns spa-layout.js actually reads, derived from the browser ledger — not every column in
    the dataset — so the table stays the size of the reader-facing text.
    """
    fragments: dict[str, dict] = {}

    def add(kind: str, text: str, address: str) -> None:
        value = str(text or "").strip()
        if not value or not CNCJK.search(value):
            return
        head, tail = (note_price_prefix(value) if kind == "poi_note" else ("", value))
        if not tail:
            return
        key = _digest(tail)
        entry = fragments.setdefault(key, {"id": key, "cn": tail, "kind": kind, "addresses": []})
        entry["addresses"].append(address)

    for cat in ("hotels", "restaurants", "cafes", "attractions", "dive_sites"):
        for index, row in enumerate(dataset.get(cat) or []):
            if not isinstance(row, list):
                continue
            if len(row) > 10:
                add("poi_note", row[10], f"{cat}[{index}].note")
    for block_key, columns in RENDERED_COLUMNS.items():
        for index, row in enumerate(dataset.get(block_key) or []):
            for column, kind in sorted(columns.items(), key=lambda kv: str(kv[0])):
                if isinstance(row, list) and isinstance(column, int):
                    if len(row) > column:
                        add(kind, row[column], f"{block_key}[{index}][{column}]")
                elif isinstance(row, dict) and isinstance(column, str):
                    add(kind, row.get(column), "%s[%d]['%s']" % (block_key, index, column))
    for index, item in enumerate(dataset.get("itinerary") or []):
        if isinstance(item, list):
            for column in (4, 5):
                if len(item) > column and isinstance(item[column], str):
                    add("itin", item[column], f"itinerary[{index}][{column}]")
    for index, row in enumerate(dataset.get("destination_coverage") or []):
        if isinstance(row, list) and len(row) > 1:
            add("coverage_desc", row[1], f"destination_coverage[{index}]")
    if skip_covered:
        resolved = renderable_names(dataset)
        fragments = {k: v for k, v in fragments.items() if v["cn"] not in resolved}
    return sorted(fragments.values(), key=lambda f: (f["kind"], f["cn"]))


def normalized_forms(text: str) -> list[str]:
    """一条文本在 DOM 里可能呈现的全部规范化形态（顺序＝优先级，去重后返回）。

    MT-1 只承认两种规范化，都是实测出来的、不是猜测：
      * 渲染层用 JOINERS 把多列拼成一句 ⇒ 读者看到的可能是剥掉首尾连接符之后的那半句；
      * poi_note 在 DOM 里是「价格脚手架 + 正文」形态 ⇒ 采集时剥掉的 head 会重新出现在文本里，
        所以正文形态（note_price_prefix 的 tail）也是同一条已登记 fragment。
    """
    value = str(text or "").strip()
    out = [value]
    stripped = value.strip(JOINERS).strip()
    if stripped:
        out.append(stripped)
    _, tail = note_price_prefix(value)
    tail = str(tail or "").strip(JOINERS).strip()
    if tail:
        out.append(tail)
    return list(dict.fromkeys([item for item in out if item]))


def registered_fragment_forms(fragments: list[dict]) -> dict[str, list[dict]]:
    """已登记 fragment 的全部可匹配形态 → **该形态回指到的所有 fragment**（按 id 去重）。

    值必须是列表：形态相同但落在两条不同 fragment 上＝多义，调用方要拒绝下结论，
    而不是取第一条（业主 2026-10-31 REVISE 第 1 条：每个片段必须唯一回指 fragment）。
    """
    forms: dict[str, list[dict]] = {}
    for fragment in fragments:
        for key in normalized_forms(fragment["cn"]):
            bucket = forms.setdefault(key, [])
            if not any(existing["id"] == fragment["id"] for existing in bucket):
                bucket.append(fragment)
    return forms


COMPOSITE_SPLIT = re.compile(r"\s*[·|]\s*")   # 只按实测的连接符切；'/' 属于内容，不切


# 对外口径只有一套名字（业主 2026-10-31）：内部状态叫 single，正式统计里它叫
# whole_row_normalized。内部枚举留着是因为 composite_components 还要靠它分流，
# 但任何写进报告/证据的 matched_form 都必须先过这张表。
STATUS_REPORT_LABEL = {"single": "whole_row_normalized"}


def report_status(status: str) -> str:
    return STATUS_REPORT_LABEL.get(status, status)


def composite_components(text: str, forms: dict[str, list[dict]]) -> dict:
    """把一行 DOM 文本切成片段，逐片段回指已登记 fragment，返回**全覆盖判定**。

    status 只有五种，判定是实测出来的，不是「看起来像」：
      single    —— 整行的规范化形态唯一命中一条已登记 fragment；
      complete  —— 两个以上片段、每个含中文的片段都唯一命中（这才允许判 dataset_cell）；
      partial   —— 有片段命中、有片段命不中（只能判 render_composite，不许 --apply）；
      ambiguous —— 整行的规范化形态回指多条 fragment，或某一片段回指多条：**无条件阻断**，
                   不许靠组件拆分把它重新变绿（业主 REVISE 第 2 条）；
      none      —— 一个都不命中：这行根本不在登记面上，交回 unregistered / literal / unattributed。
    ` / ` 不做任何通用拆分：2026-10-31 实测两地残留 18 行里没有一行需要它，而地址、路线名、
    专名里的 `/` 一拆就丢原义。将来真出现「同一 transport_nodes[n] 记录被渲染成 A / B」的形态，
    必须先量到那一处渲染组合、并证明各片段回指同一行，才允许加窄规则。

    先整行、后拆片段（MT-1 实测补正）：`·` 既是渲染层的连接符，也是数据格里的正文标点
    （`洛杉矶提车·I-5内陆北上硅谷中半岛` 就是一整格 budget[2]）。只看拆完的片段会把这种
    「整行本来就是一条已登记 fragment」误判成片段级未覆盖，所以整行的规范化命中优先。
    """
    segments = [s.strip() for s in COMPOSITE_SPLIT.split(text) if s.strip()] or [text.strip()]
    cjk = [s for s in segments if CNCJK.search(s)]
    whole_hits: list[dict] = []
    for key in normalized_forms(text):
        if key in forms:
            whole_hits = forms[key]
            break
    if len(whole_hits) == 1:
        fragment = whole_hits[0]
        return {"status": "single", "segments": [text.strip()], "cjk_segments": 1,
                "components": [{"segment": text.strip(), "fragment_id": fragment["id"],
                                "kind": fragment["kind"], "addresses": fragment["addresses"],
                                "matched_form": "whole_row_form"}],
                "unresolved_parts": [], "ambiguous_parts": [], "collision_fragment_ids": [],
                "component_coverage": 1.0}
    if len(whole_hits) > 1:
        # 业主 REVISE 第 2 条：整行的规范化形态回指多条 fragment ⇒ 无条件 ambiguous，
        # 不许再靠把它拆成组件、凑出「全覆盖」来把自己变绿。
        return {"status": "ambiguous", "segments": segments, "cjk_segments": len(cjk),
                "components": [], "unresolved_parts": [],
                "ambiguous_parts": [text.strip()],
                "collision_fragment_ids": sorted(f["id"] for f in whole_hits),
                "component_coverage": 0.0}
    components: list[dict] = []
    unresolved: list[str] = []
    ambiguous: list[str] = []
    collisions: list[str] = []
    for segment in cjk:
        hits = None
        matched_form = None
        for key in normalized_forms(segment):
            if key in forms:
                hits = forms[key]
                matched_form = ("exact_form" if key == segment.strip() else "normalized_form")
                break
        if not hits:
            unresolved.append(segment)
        elif len(hits) > 1:
            ambiguous.append(segment)
            collisions.extend(hit["id"] for hit in hits)
        else:
            fragment = hits[0]
            components.append({"segment": segment, "fragment_id": fragment["id"],
                               "kind": fragment["kind"], "addresses": fragment["addresses"],
                               "matched_form": matched_form if len(segments) == 1
                               else "composite_part"})
    if not cjk:
        status = "none"
    elif ambiguous:
        status = "ambiguous"
    elif components and unresolved:
        status = "partial"
    elif components:
        status = "single" if len(cjk) == 1 else (
            "complete" if len(components) == len(cjk) else "partial")
    else:
        status = "none"      # 一个组件都没命中：不是「复合没覆盖」，是这行根本不在登记面上，
                             # 继续往下走 unregistered / renderer_literal / unattributed
    return {"status": status, "segments": segments, "cjk_segments": len(cjk),
            "components": components, "unresolved_parts": unresolved, "ambiguous_parts": ambiguous,
            "collision_fragment_ids": sorted(set(collisions)),
            "component_coverage": (len(components) / len(cjk)) if cjk else 0.0}


def slot_of_address(address: str):
    """`dataset['transport'][0][3]` → ('transport', 3)；`…['type']` → ('transport_nodes', 'type')。

    只用来判断「这一格归谁负责」，不参与任何文本匹配；解析不出来就返回 None，不猜。
    位置数组用下标，对象行用字段名——两棵候选的载荷两种形状都有，所以两式都要认。
    """
    text = str(address or "")
    match = ADDRESS_SLOT.match(text)
    if not match:
        return None
    key = ADDRESS_KEY.match(text[match.end():])
    if not key:
        return None
    value = key.group("idx")
    return (match.group("block"), int(value) if value is not None else key.group("field"))


def proper_name_keys(dataset: dict) -> tuple[dict, set]:
    """(显示面已认识的中文名 → 来源, 撞名集合)。

    列清单与档位语义都住在 references/display-name-channel.json，判定只调 display_names，
    这里不复制第二份列下标——复制了就又会变成「翻译表什么都能接」的老路。
    撞名（同一个中文名在同一列对到两个英文）单独返回：它仍是专名列的活，但要的是人工裁决，
    不是机器显示名，也不是「挑一条看起来顺眼的」。
    """
    import display_names

    pairs, conflicts = display_names.read_pairs(dataset)
    keys = {cn: "tier1_dataset_pair:%s" % item["address"] for cn, item in pairs.items()}
    for cn in (dataset.get("name_pairs") or {}):
        keys.setdefault(cn, "tier1_dataset_pair:payload")
    machine, _rejected = display_names.read_machine_display_names(dataset)
    for cn in machine:
        keys.setdefault(cn, "tier2_machine_translated_display_name")
    collided = {str(item["cn"]) for item in conflicts}
    for cn in collided:
        keys.pop(cn, None)                           # 撞名：显示面不给，缺口账也必须承认给不了
    return keys, collided


def display_name_slots() -> set:
    """显示面认领的列集合（(block, 中文侧 key)），来自 references/display-name-channel.json。"""
    import display_names

    return set(display_names.name_columns())


# ---------------------------------------------------------------------------------------------
# MT-D（业主 2026-11-01 分母裁决）：所有权按**地址**判，不按中文文本做集合相减。
#
# 为什么旧口径不够（实测，不是推测）：collect_fragments(skip_covered=True) 一直在用
# renderable_names(dataset) 的**文本集合**决定「这条要不要翻」。文本相减答的是「这句别处有没有英文」，
# 不是「这一格归谁」——它会把「同文不同格」（同一串既出现在 prose 列、又出现在类别/专名/金额列）
# 整个抹掉，既不留账也不阻断；而 prose_en 是按内容键、渲染优先级又高于类别与专名面，
# 一旦被这种文本填进去，就是把别的通道的来源换成散文表，第二来源重新长出来。
#
# 所以这里只做一件事：给每个 fragment 的**每个地址**登记 owner，四类结果互斥且穷尽，
# 并且 --export / validate_table / apply_table 读的是同一份 worklist。
# collect_fragments 的采集语义一字不动（skip_covered 的默认值也不动，既有审计面继续按原口径）。
OWNER_VOCABULARY = ("PROSE_TABLE", "CATEGORY_LEXICON", "DISPLAY_NAME", "MONEY_FORMATTER",
                    "REGISTERED_EN_REPLACEMENT")
OUTCOME_VOCABULARY = ("PROSE_REQUIRED", "OWNED_NON_PROSE", "MIXED_OWNER_BLOCKED",
                      "OWNER_UNRESOLVED_BLOCKED")
# 迁移清册的结果词表：四个 owner 名**从 OWNER_VOCABULARY 拼出来**，不在这里重抄一遍——
# 加一个 owner（或改名）时，清册要么自动跟上，要么在闭集断言里红给人看。
# 两个 BLOCKED 名与 fragment 四桶同名同义；UNLOCATABLE_NO_ADDRESS 是清册独有的那一格：
# legacy 表里查不到任何数据地址的键不成 fragment，所以它进不了四桶，只能在这份账里显式站着。
LEGACY_INVENTORY_OUTCOMES = OWNER_VOCABULARY + ("MIXED_OWNER_BLOCKED",
                                                 "OWNER_UNRESOLVED_BLOCKED",
                                                 "UNLOCATABLE_NO_ADDRESS")
# 迁移桶的「兑现」状态闭集。为什么还要第二套词：迁给一个拼不出英文的 owner 不等于交付，
# 只写 outcome 就会让「已迁移」在报表里读成「已覆盖」。served_states 不在闭集内直接抛——
# 常量因此不是注释，它被判定自己核对一遍。
LEGACY_SERVED_STATES = ("served", "cannot_serve", "tier2_candidate", "blocked_by_collision",
                        "pending_mt_e", "render_side_unmeasured", "not_migrated")
# 判定顺序＝登记的一部分（合同 ownership.precedence）。两条 BLOCKED 之间先报哪条不是风格问题：
# 「没有来源的 replacement」是**已知有人在抢这格**，「地址没有任何登记」是**没人认领**，
# 前者的处置是补来源，后者的处置是补列登记，混在一起报就会把两类不同的活写成一类。
UNPROVENANCED_CLAIM = "owner_unprovenanced_blocked"
NO_OWNER_ADDRESS = "no_registered_owner_for_address"
MIXED_OWNER = "mixed_owner_for_content_id"

ADDRESS_NORMALIZE = re.compile(r"^dataset\['(?P<prefix>[a-z_]+)'\]")
ADDRESS_TAIL_INDEX = re.compile(r"^\[(?P<idx>\d+)\]$")
ADDRESS_TAIL_FIELD = re.compile(r"^\['(?P<field>[^']+)'\]$")
ADDRESS_TAIL_DOT = re.compile(r"^\.(?P<field>[a-z_]+)$")


def normalize_address(address: str) -> tuple:
    """两种地址写法归一成 (block, slot)：采集器给 `budget[0][2]`/`hotels[3].note`，
    值索引给 `dataset['transport'][1][3]`；`destination_coverage[5]` 这种不带列的返回 slot=None。

    解析不出来返回 (None, None)——**不猜**。猜出来的 (block, slot) 会把一格的归属算到另一格头上，
    而这份判定决定的是「这条进不进翻译表」。
    """
    text = str(address or "").strip()
    head = ADDRESS_NORMALIZE.match(text)
    if head:
        text = head.group("prefix") + text[head.end():]
    match = re.match(r"^(?P<block>[a-z_]+)\[\d+\]", text)
    if not match:
        return None, None
    block, tail = match.group("block"), text[match.end():]
    if not tail:
        return block, None
    for pattern, group in ((ADDRESS_TAIL_INDEX, "idx"), (ADDRESS_TAIL_FIELD, "field"),
                           (ADDRESS_TAIL_DOT, "field")):
        found = pattern.match(tail)
        if found:
            value = found.group(1)
            return block, int(value) if group == "idx" else value
    return block, tail


def non_prose_column_registry() -> dict:
    """(block, 中文侧 key) → 通道名。列清单一律从各自登记面读，本函数不复制任何下标。

    MT-D2 之后这里多一步：`references/dataset-shape-alias.json` 证明过的 index↔field 对应，
    会把**字段侧**的通道认领同时挂到**位置侧**的下标上。没有这一步，CA（位置数组）的类别列与专名列
    会被判给 prose，而 PH（对象）同一列判给类别/专名——同一张页面两套主人，是两套登记面各说各话。
    """
    import category_lexicon
    import display_names

    cache_key = ("columns", hashlib.sha256((
        category_lexicon.LEXICON_PATH.read_bytes()
        + display_names.CHANNEL_PATH.read_bytes()
        + repr(sorted(FORMATTER_SLOTS.items())).encode("utf-8")
        + SHAPE_ALIAS_PATH.read_bytes())).hexdigest())
    if cache_key in _REGISTRY_CACHE:
        return _REGISTRY_CACHE[cache_key]
    registry: dict = {}
    for col in category_lexicon.LEXICON.get("_category_columns") or []:
        key = col.get("field") if col.get("field") is not None else col.get("index")
        registry[(str(col.get("dataset")), key)] = "CATEGORY_LEXICON"
    for (block, key) in display_names.name_columns():
        registry[(str(block), key)] = "DISPLAY_NAME"
    for (block, key), owner in FORMATTER_SLOTS.items():
        registry[(str(block), key)] = "MONEY_FORMATTER"
    for (block, slot), field in alias_field_by_slot().items():
        claimed = registry.get((block, field))
        if claimed:
            registry.setdefault((block, slot), claimed)
    _REGISTRY_CACHE[cache_key] = registry
    return registry


SHAPE_ALIAS_PATH = SCRIPTS.parent / "references" / "dataset-shape-alias.json"
# 登记面按**内容摘要**缓存：分类要对每条 fragment 的每个地址查表，逐地址重读 JSON 会把一次判定
# 变成几百次磁盘解析；摘要变了缓存就换，所以这不是「读一次就永久相信」。
_REGISTRY_CACHE: dict = {}


def shape_alias_document() -> dict:
    return json.loads(SHAPE_ALIAS_PATH.read_text(encoding="utf-8"))


def shape_alias_registrations() -> dict:
    return dict(shape_alias_document().get("datasets") or {})


def alias_field_by_slot() -> dict:
    """(block, 位置下标) → 字段名。别名表是唯一的对应关系出处，代码不另存一份。

    按**文件字节**缓存：分类要对每条 fragment 的每个地址查它，逐条重读 JSON 会把一次判定变成几百次
    磁盘解析；而缓存键用内容摘要而不是「读一次就永久缓存」，改了别名表下一轮就生效。
    """
    text = SHAPE_ALIAS_PATH.read_text(encoding="utf-8")
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if key not in _REGISTRY_CACHE:
        out: dict = {}
        for block, spec in (json.loads(text).get("datasets") or {}).items():
            for alias in spec.get("aliases") or []:
                out[(str(block), int(alias["index"]))] = str(alias["field"])
        _REGISTRY_CACHE[key] = out
    return _REGISTRY_CACHE[key]


def alias_proven_slots() -> set:
    return set(alias_field_by_slot())


def shape_adapter(dataset: dict) -> dict:
    """唯一适配器：把别名表对着**在盘数据**验一遍，返回版本、别名与逐行阻断项。

    为什么必须现场验而不是「登记了就信」：别名一旦与数据脱节（长度不够、字段换位、对象与数组混杂），
    按位置判的所有权就会指到错误的格上——那比不判更糟。这里任何一条 block_when 成立，
    上游（classify → worklist → validate → apply）都必须停，而不是退回旧的「猜一个」。
    禁止按值猜字段：本函数只看行长、键名与行形状，从不读单元格内容来决定谁是 place/type。
    """
    blocking: list = []
    aliases = alias_field_by_slot()
    for block, spec in sorted(shape_alias_registrations().items()):
        rows = dataset.get(block) or []
        if not rows:
            continue
        kinds = {type(row).__name__ for row in rows}
        if len(kinds) > 1:
            blocking.append({"code": "mixed_row_shapes_in_one_dataset",
                             "detail": "%s 同时出现 %s 两种行形状：别名表只能对一种形状成立，"
                                       "混着判就是把同一列算给两个主人" % (block, sorted(kinds))})
            continue
        indexes = sorted(int(alias["index"]) for alias in spec.get("aliases") or [])
        fields = sorted(str(alias["field"]) for alias in spec.get("aliases") or [])
        arity = spec.get("array_arity")
        for position, row in enumerate(rows):
            if isinstance(row, list):
                if indexes and len(row) <= max(indexes):
                    blocking.append({"code": "array_row_shorter_than_max_alias_index",
                                     "detail": "%s[%d] 长 %d，别名表最大下标 %d：这一格根本不存在"
                                               % (block, position, len(row), max(indexes))})
                if arity is not None and len(row) != int(arity):
                    blocking.append({"code": "array_row_arity_mismatch",
                                     "detail": "%s[%d] 长 %d，登记 arity %d：长度变了就说明列被插过或删过，"
                                               "位置对应不再成立" % (block, position, len(row), int(arity))})
            elif isinstance(row, dict):
                missing = [field for field in fields if field not in row]
                if missing:
                    blocking.append({"code": "dict_row_missing_aliased_field",
                                     "detail": "%s[%d] 缺字段 %s：别名表声称的下标在这一行没有对应物"
                                               % (block, position, ",".join(missing))})
        unclaimed = sorted((block, index) for index, field in
                           [(i, alias_field_by_slot().get((block, i))) for i in indexes]
                           if field and not _channel_claims_field(block, field))
        for slot in unclaimed:
            blocking.append({"code": "alias_field_not_registered_in_any_channel",
                             "detail": "%s[%s] 的字段 %r 没有任何通道认领：别名只能把已有认领换形，"
                                       "不能凭空造一个 owner" % (slot[0], slot[1], aliases.get(slot))})
    duplicated = _duplicate_alias_slots()
    for detail in duplicated:
        blocking.append({"code": "alias_index_double_claimed", "detail": detail})
    return {"alias_table_version": shape_alias_document().get("alias_table_version"),
            "aliases": {"%s[%s]=%s" % (block, slot, field)
                        for (block, slot), field in sorted(aliases.items(), key=lambda kv: str(kv))},
            "rows_checked": {block: len(dataset.get(block) or [])
                             for block in sorted(shape_alias_registrations())},
            "blocking": blocking,
            "clean": not blocking}


def _field_keys_for_block(block: str) -> set:
    """该 block 在**语义通道登记面**里用字段名认领的键集合（类别/专名/金额三处并起来）。"""
    import category_lexicon
    import display_names

    keys = {key for (name, key) in display_names.name_columns() if str(name) == block}
    keys |= {col.get("field") for col in category_lexicon.LEXICON.get("_category_columns") or []
             if str(col.get("dataset")) == block and col.get("field") is not None}
    keys |= {key for (name, key), _ in FORMATTER_SLOTS.items()
             if str(name) == block and isinstance(key, str)}
    return keys


def _channel_claims_field(block: str, field: str) -> bool:
    return field in _field_keys_for_block(block)


def _duplicate_alias_slots() -> list:
    """同一个 (block, slot) 被两条别名认领＝别名表自己坏了，与数据无关。"""
    seen: dict = {}
    out: list = []
    for block, spec in shape_alias_registrations().items():
        for alias in spec.get("aliases") or []:
            key = (block, int(alias["index"]))
            field = str(alias["field"])
            if key in seen and seen[key] != field:
                out.append("%s[%s] 同时映射到 %s 与 %s" % (block, key[1], seen[key], field))
            seen[key] = field
    return out


def alias_adjudication(block: str, slot, columns: dict | None = None) -> str:
    """该**位置下标**是否有已证明的语义主人（别名表 + 该字段确有通道认领）。没有就返回空串。

    只认整数下标：对象行本来就按字段名登记，不需要换形；在这里给字段名再算一次别名是重复劳动，
    也是「两套换算各写一遍」的老路。
    """
    if not isinstance(slot, int):
        return ""
    if (block, slot) not in alias_field_by_slot():
        return ""
    registry = columns if columns is not None else non_prose_column_registry()
    return registry.get((block, slot)) or ""



LEGACY_OWNER_CLAIMS = "owner_claim"        # 旧档位：整表当一个 owner 来抢（业主 MT-D2 已撤）
LEGACY_CANDIDATE_ONLY = "candidate_only"   # 现档位：只作 MT-E 的翻译对照候选，不作 owner


def legacy_replacement_mode() -> str:
    """处置档位从登记面读，不写在代码记忆里。

    业主 2026-11-01 MT-D2 第 1 条把这张表降成 legacy 候选资料，理由是它**不是一个语义通道**，
    而是混装了完整散文、路线标题、类别词、专名、金额/时长/日期与行程交通说明——
    给整表补一份统一 provenance 就是把「历史上已有一段英文」冒充成「来源已核验」，那是伪血缘。
    撤掉它的 owner 身份是一次裁决，所以它留在登记面上（`legacy_en_text_replacements.disposition`），
    不留在函数名的注释里；档位取值不在闭集内直接抛，不许默默按旧行为跑。
    """
    mode = str((contract().get("ownership") or {})
               .get("legacy_en_text_replacements", {})
               .get("disposition") or LEGACY_OWNER_CLAIMS).strip()
    if mode not in (LEGACY_OWNER_CLAIMS, LEGACY_CANDIDATE_ONLY):
        raise ValueError("ownership.legacy_en_text_replacements.disposition=%r 不在闭集 %s"
                         % (mode, [LEGACY_OWNER_CLAIMS, LEGACY_CANDIDATE_ONLY]))
    return mode


def replacement_claim(dataset: dict, text: str) -> dict:
    """`en_text_replacements` 里**有这句**只算一条待证的 owner 主张，不算排除理由（业主第 4 条）。

    要成为 owner，必须同时给出 owner contract、英文值和来源三样，来源住在
    `dataset['en_text_replacement_provenance'][cn]`（与 tier2 显示名同构的结构化对象）。
    这里还把**渲染优先级**照实登记进判定：spa-layout.js::tr() 实测顺序是
    显式 en 格 → en_text_replacements → prose_en → category_en → CATEGORY_DICT → enEntityName →
    enMetrics → pending，也就是说 replacement 抢在 prose_en **上面**。
    所以「这格只有 replacement、我们却给它写 prose_en」= 表里的译文永远到不了读者眼前，
    还多出一个查不到的第二来源。这一条是本判定把它记成 BLOCKED 而不是 PROSE_REQUIRED 的工程理由，
    不是引规则压人。

    MT-D2 之后（`disposition=candidate_only`）不成证的句子**不再抢 owner、也不再因此被卡**：
    它按自己的地址归真实通道，那段旧英文只登记成对照候选。账上不丢「这里曾有英文」这件事，
    但正式译文必须重新过 MT-E 的 provenance 与复核链——见 ownership.legacy_en_text_replacements。
    """
    table = dataset.get("en_text_replacements") or {}
    if text not in table:
        return {"claimed": False}
    english = str(table.get(text) or "")
    provenance = (dataset.get("en_text_replacement_provenance") or {}).get(text)
    fields = contract()["ownership"]["owners"]["REGISTERED_EN_REPLACEMENT"][
        "provenance_required_fields"]
    entry = provenance if isinstance(provenance, dict) else {}
    missing = [field for field in fields if _blank(entry.get(field))]
    value_drift = bool(entry) and _as_text(entry.get("en_value")).strip() != english.strip()
    provenanced = bool(entry) and not missing and not value_drift
    disposition = legacy_replacement_mode()
    acts_as_owner = provenanced
    acts_as_candidate = not provenanced
    return {"claimed": True, "en_value": english, "candidate_english": english,
            "provenanced": provenanced, "disposition": disposition,
            "acts_as_owner": acts_as_owner, "acts_as_candidate": acts_as_candidate,
            "missing_fields": missing, "en_value_drift": value_drift,
            "provenance_is_object": isinstance(provenance, dict)}


def address_owners(address: str, prose_addresses: dict, columns: dict) -> list:
    """一个地址的全部 owner 主张。同一地址被两个通道认领＝地址级双主张，也要如实列出来。"""
    owners: list = []
    if address in prose_addresses:
        owners.append("PROSE_TABLE")
    block, slot = normalize_address(address)
    claimed = columns.get((block, slot)) if block is not None else None
    if claimed:
        owners.append(claimed)
    return sorted(set(owners))


def prose_address_set(dataset: dict) -> set:
    """PROSE_TABLE 的地址全集：唯一出处是**采集器本身**，不是任何传进来的清单。

    单列一个函数是因为迁移清册（legacy_migration_inventory）也要问同一个问题。以前它住在
    classify 的局部变量里，第二处要么复制那份集合推导（两份 prose 地址＝两份分母），
    要么反过来依赖 classify 的返回值（把所有权判定拖进一次只问地址的遍历）。
    """
    return {address for fragment in collect_fragments(dataset, skip_covered=False)
            for address in fragment["addresses"]}


def legacy_entry_is_served(dataset: dict, cn: str, outcome: str) -> dict:
    """迁过去的 owner **今天到底能不能发英文**——迁移不许只是改个名字。

    业主 2026-11-01 MT-D2 第 4 条要的是「把旧表拆入真实 owner」。真实的意思是落点能兑现：
    把一条字符串判给 CATEGORY_LEXICON，而词根组合拼不出英文，那这条字符串在渲染层拆除旧表之后
    就直接掉回 (translation pending)——账上「已迁完」，读者页上少一句英文。所以每个迁移桶都配
    一条 served 账，并且把兑现不了的名字显式发 `migrated_owner_cannot_serve`。
    PROSE_TABLE 与 MONEY_FORMATTER 各有一种「这里量不到」：前者本来就要等 MT-E 重翻，
    后者住在渲染层 money() 里（本轮不在 Python 侧假装复现它）。两者都如实写进 state，不留空。
    """
    if outcome == "PROSE_TABLE":
        return {"state": "pending_mt_e", "served": False,
                "note": "散文由 MT-E 重翻并补 provenance；旧英文只作对照，不算已兑现"}
    if outcome == "MONEY_FORMATTER":
        return {"state": "render_side_unmeasured", "served": None,
                "note": "金额/度量在渲染层 money() 里解析，Python 侧不冒充复现它；拆除旧表前须由两地重建验证"}
    if outcome == "CATEGORY_LEXICON":
        import category_lexicon
        gloss, missing = category_lexicon.compose(cn)
        return {"state": "served" if gloss else "cannot_serve", "served": bool(gloss),
                "english": gloss[:80], "uncovered_cjk": missing[:6]}
    if outcome in ("DISPLAY_NAME", "REGISTERED_EN_REPLACEMENT"):
        import display_names
        pairs, conflicts = display_names.read_pairs(dataset)
        machine, machine_conflicts = display_names.read_machine_display_names(dataset)
        if cn in pairs:
            return {"state": "served", "served": True,
                    "english": str(pairs[cn]["english"])[:80], "tier": pairs[cn]["tier"]}
        if cn in machine:
            return {"state": "tier2_candidate", "served": False,
                    "note": "机器显示名是候选，不是带来源的英文名：拆除旧表前要业主逐条确认"}
        if conflicts or machine_conflicts:
            return {"state": "blocked_by_collision", "served": False,
                    "note": "同名两条英文相撞，谁都不许用（display_names.collision_rule）"}
        return {"state": "cannot_serve", "served": False,
                "english": "", "uncovered_cjk": [cn[:20]]}
    return {"state": "not_migrated", "served": None,
            "note": "%s 桶的处置是补来源或补登记，不是给英文" % outcome}


def legacy_migration_inventory(dataset: dict, classification: dict | None = None) -> dict:
    """MT-D2 第 3～4 步：把 `en_text_replacements` 逐条按**它自己的地址槽位**迁到真实 owner。

    业主 2026-11-01 对 #99 的裁决第 1 条拒绝了两件事：不给整张表批量补 provenance——它不是一个
    语义通道，而是混装了完整散文／路线标题／类别词／专名／金额时长日期／行程交通说明，统一补一份
    来源就是把「历史上已有一段英文」冒充成「来源已核验」（伪血缘）；也不整表粗暴删除——PH 的英文
    今天确实由它在发，删了就只剩「曾经有英文」而没有任何账。这里的处置是**逐地址改判主人**：
    类别→CATEGORY_LEXICON、专名→DISPLAY_NAME、金额/度量→MONEY_FORMATTER、真正散文→PROSE_TABLE，
    落在多主人或查不到地址的一律留「无法确认」，不替它们编一个 owner。

    两张账的分母不同，必须一起看，否则四桶归零会被读成「这张表已经清完」：
      · classify 的分母是 **fragment**（数据里被采集到的中文串），四桶恒等式管的是翻译表收谁；
      · 本清册的分母是 **legacy 表的键**（历史英文串）。不成 fragment 的键进不了四桶，
        只能在这份清册里记账——`UNLOCATABLE_NO_ADDRESS` 才是「无法确认」真正住的地方。
    槽位判定复用 prose_address_set / address_owners / alias_adjudication 与同一份
    non_prose_column_registry；本函数不写第二套换算，也不写任何东西。
    """
    table = dataset.get("en_text_replacements") or {}
    provenance_face = dataset.get("en_text_replacement_provenance") or {}
    index = dataset_value_index(dataset)
    prose_addresses = prose_address_set(dataset)
    columns = non_prose_column_registry()
    if classification is None:
        classification = classify_fragment_ownership(dataset)
    owner_by_text = {row["cn"]: row for row in classification["rows"]}
    disposition = legacy_replacement_mode()
    rows: list = []
    buckets: dict = {outcome: [] for outcome in LEGACY_INVENTORY_OUTCOMES}
    findings: list = []
    # 形状坏了就不迁：别名是这次迁移的一半依据，别名与数据脱节时「这一格归谁」本身不可信，
    # 迁出来的桶数会变成一份看起来很齐的假账。与 classify 同一个口径，同一个适配器。
    if not classification["shape"]["clean"]:
        for item in classification["shape"]["blocking"]:
            findings.append({"code": "dataset_shape_blocked",
                             "detail": "迁移清册｜%s｜%s" % (item["code"], item["detail"])})
        return {"legacy_entries": len(table), "provenance_entries": len(provenance_face),
                "disposition": disposition, "shape_blocked": True, "rows": [],
                "counts": {key: 0 for key in LEGACY_INVENTORY_OUTCOMES},
                "buckets": {key: [] for key in LEGACY_INVENTORY_OUTCOMES},
                "findings": findings, "identity_holds": False,
                "outcomes": list(LEGACY_INVENTORY_OUTCOMES)}
    for cn in sorted(table):
        english = str(table.get(cn) or "")
        claim = replacement_claim(dataset, cn)
        fragment = owner_by_text.get(cn)
        locations = list(index.get(str(cn).strip()) or [])
        if fragment is not None:
            # 这条 legacy 键**就是**一个 fragment：直接复用它已经判好的逐地址 owner（那套判定走过
            # 登记面 + 槽位迁移 + 四桶优先级），不在这里再算第二遍。两份算法一旦分叉，
            # 「四桶归零」和「迁移清册」就会各说一套，而这两张账是要一起交给业主的。
            # 桶名不在这里翻译第二遍：下面那一段唯一的归桶逻辑同时管两类来源，避免同一事实两种说法。
            owners = list(fragment["owners"])
            basis = "fragment"
            address_detail = fragment["address_detail"]
            addresses = [item["address"] for item in address_detail if "address" in item]
        else:
            # 不成 fragment 的键只能由数据侧回答它在不在数据里：PROSE_TABLE 的主张权在采集器手里
            # （「prose 地址」＝「被采集器收进 fragment 的地址」），这里不许凭空给它一个散文主人。
            addresses = locations
            per_address = []
            owners = []
            for address in locations:
                claimed = address_owners(address, prose_addresses, columns)
                block, slot = normalize_address(address)
                adjudicated = alias_adjudication(block, slot, columns) if block else ""
                if adjudicated and adjudicated in claimed and "PROSE_TABLE" in claimed:
                    claimed = [adjudicated]
                owners.extend(claimed)
                per_address.append({"address": address, "owners": claimed,
                                    "slot": [block, slot]})
            if claim.get("acts_as_owner"):
                owners.append("REGISTERED_EN_REPLACEMENT")
            address_detail = per_address
            basis = "value_index" if locations else "none"
        owner_union = set(owners)
        if not locations and fragment is None:
            owner_union = set()
        if not owner_union:
            outcome = ("UNLOCATABLE_NO_ADDRESS" if fragment is None and not locations
                       else "OWNER_UNRESOLVED_BLOCKED")
        elif len(owner_union) > 1:
            outcome = "MIXED_OWNER_BLOCKED"
        else:
            outcome = next(iter(owner_union))
        buckets[outcome].append(cn)
        served = legacy_entry_is_served(dataset, cn, outcome)
        if served["state"] not in LEGACY_SERVED_STATES:
            raise ValueError("迁移兑现状态 %r 不在登记闭集 %s：多一个状态就得先在合同里写清它凭什么"
                             % (served["state"], list(LEGACY_SERVED_STATES)))
        rows.append({"cn": cn, "legacy_en": english[:120], "outcome": outcome,
                     "owners": sorted(owner_union), "addresses": addresses,
                     "address_count": len(addresses), "address_detail": address_detail,
                     "address_basis": basis, "served": served,
                     "reference_only": bool(claim.get("acts_as_candidate")),
                     "provenanced": bool(claim.get("provenanced")),
                     "disposition": disposition,
                     "fragment_id": (fragment or {}).get("id"),
                     "fragment_outcome": (fragment or {}).get("outcome")})
    total = sum(len(items) for items in buckets.values())
    if total != len(table) or len({c for items in buckets.values() for c in items}) != len(table):
        findings.append({"code": "legacy_inventory_accounting_mismatch",
                         "detail": ("迁移清册的分母对不上：桶合计 %d ≠ 表键 %d（或有同一键落两桶）"
                                    % (total, len(table)))})
    for row in rows:
        if row["outcome"] == "UNLOCATABLE_NO_ADDRESS":
            findings.append({"code": "legacy_entry_unlocatable",
                             "detail": "%r 在数据里查不到任何地址（曾由 %r 发英文）：无法确认，"
                                       "不许默认它是散文，也不许当它已经迁完"
                                       % (row["cn"][:60], row["legacy_en"][:60])})
        # 兑现检查只针对「已经判给某个 owner」的条目：BLOCKED 桶本来就不该有英文落点。
        # tier2_candidate 与 blocked_by_collision 也发这条码——它们同样是「拆掉旧表后这里没有
        # 权威英文」，只是处置不同（前者等业主确认，后者等同名两条英文人工裁决）。
        if row["served"]["served"] is False and row["outcome"] in (
                "CATEGORY_LEXICON", "DISPLAY_NAME", "REGISTERED_EN_REPLACEMENT"):
            findings.append({"code": "migrated_owner_cannot_serve",
                             "detail": "%r 已迁给 %s，但该通道今天给不出可交付英文（state=%s，"
                                       "未覆盖词根 %s）：拆除旧渲染来源前必须先补齐，"
                                       "否则读者页掉回 pending"
                                       % (row["cn"][:60], row["outcome"], row["served"]["state"],
                                          ",".join(row["served"].get("uncovered_cjk") or [])[:60])})
    served_states: dict = {}
    for row in rows:
        state = row["served"]["state"]
        served_states[state] = served_states.get(state, 0) + 1
    return {"legacy_entries": len(table),
            "provenance_entries": len(provenance_face),
            "disposition": disposition,
            "shape_blocked": False,
            "served_states": served_states,
            "counts": {key: len(value) for key, value in buckets.items()},
            "buckets": {key: value for key, value in buckets.items()},
            "rows": rows, "findings": findings,
            "identity": "legacy_entries = 各迁移桶之和（互斥且穷尽）",
            "identity_holds": total == len(table),
            "outcomes": list(LEGACY_INVENTORY_OUTCOMES),
            "adjudication_reused_from": "address_owners + alias_adjudication + "
                                        "non_prose_column_registry（本函数不写第二套槽位换算）"}


# ── MT-E1：按**身份绑定**迁移槽位 owner（业主 2026-11-02 执行顺序第 2 步）─────────────────
# 业主禁止的形状：把整个 `itinerary[*][4]` 列批量改成 DISPLAY_NAME。实测那一列同时住着
# 237 个真身份标签格与 32 个真散文标题格，按列翻就把 32 条散文从读者眼前拿走。
# 允许的判据只有一条，且**逐 fragment 复现**：本格中文与它所属记录自己的 map_target 标签逐字相同，
# 且该 target 的 coords 在这条记录的格子里逐字出现——唯一命中才算标签槽。这是渲染器
# `mapLinks(label, coords, …)` 用来画按钮的同一组事实，不是我新发明的相似度。
IDENTITY_MIGRATION_KEY = "slot_identity_migration_2026_11_02"
ADDRESS_ROW_SHORT = re.compile(r"^(?P<block>[a-z_]+)\[(?P<row>\d+)\]")
ADDRESS_ROW_CANON = re.compile(r"^dataset\['(?P<block>[a-z_]+)'\]\[(?P<row>\d+)\]")
# 坐标形状只认 dataset 里 `map_targets[*].coords` 的写法：`纬度,经度`、十进制、小数位数由数据源决定
# （实测 CA 用 7 位、PH 用 6 位；把上限写死成 6 会让 CA 那 154 个真标签格全部读成 no_coord）。
# 仍然不用「像不像数字」这种宽判据：宽了就等于用格式猜测代替身份。
COORD_SHAPE = re.compile(r"^-?\d+\.\d+,-?\d+\.\d+$")
IDENTITY_VERDICTS = ("unique", "ambiguous", "label_without_coord", "no_binding", "no_coord",
                     "address_unparsable", "row_out_of_range")
PROSE_SUBCLASS_VOCABULARY = ("PROSE_SLOT_CLEAN", "PROSE_SLOT_WITH_INJECTED_NAME")
DISPLAY_NAME_SHAPE_PENDING = "display_name_proper_name_variant"


def identity_migration_rule() -> dict:
    """迁移配置面（合同 `ownership.slot_identity_migration_2026_11_02`）；形状不对就抛码，不猜默认。

    为什么把「哪些槽位有资格被身份绑定重新认领」写进合同而不是写死在代码里：业主裁的是
    **地址语义**驱动，登记面要能被独立审；为什么绑定判据本身不放进配置：那是事实比对
    （逐字标签＋逐字坐标），配置化成可调参数就等于给了一个能把 32 条散文一并抹掉的旋钮。
    """
    rule = ((contract().get("ownership") or {}).get(IDENTITY_MIGRATION_KEY))
    if not isinstance(rule, dict):
        raise ValueError("ownership_identity_rule_unregistered")
    for field in ("status", "eligible_slots", "migrate_only_when", "owner_after_claim",
                  "identity_verdicts", "min_registered_english_len"):
        if field not in rule:
            raise ValueError("ownership_identity_rule_field_missing:%s" % field)
    if rule["status"] not in ("ENROLLED", "DISABLED"):
        raise ValueError("ownership_identity_rule_status_unknown:%s" % rule["status"])
    if list(rule["identity_verdicts"]) != list(IDENTITY_VERDICTS):
        raise ValueError("ownership_identity_verdict_vocabulary_drift")
    if rule["migrate_only_when"] != ["unique"]:
        raise ValueError("ownership_identity_migrate_condition_not_unique_only")
    if rule["owner_after_claim"] != "DISPLAY_NAME":
        raise ValueError("ownership_identity_owner_not_registered")
    slots = rule["eligible_slots"]
    if not isinstance(slots, list) or not slots:
        raise ValueError("ownership_identity_eligible_slots_empty")
    keys = set()
    for item in slots:
        if not isinstance(item, dict) or "block" not in item or "slot" not in item \
                or not str(item.get("why") or "").strip():
            raise ValueError("ownership_identity_eligible_slot_incomplete")
        key = (str(item["block"]), str(item["slot"]))
        if key in keys:
            raise ValueError("ownership_identity_eligible_slot_duplicate")
        keys.add(key)
    if not isinstance(rule["min_registered_english_len"], int) or rule["min_registered_english_len"] < 2:
        raise ValueError("ownership_identity_min_english_len_invalid")
    return rule


def identity_eligible_slots(rule: dict) -> set:
    return {(str(item["block"]), str(item["slot"])) for item in rule["eligible_slots"]}


def address_row_parts(address: str):
    """(block, 列键, 行号)；行号只从两种在册写法里取。列键可能为 None（整行地址没写列）。

    `normalize_address` 给的是 (block, 列)——它会丢掉行号，所以这里自己取行号，
    并且两处的 block 必须互相印证；印不上就当不可解析，不猜。
    """
    block, column = normalize_address(address)
    text = str(address or "").strip()
    match = ADDRESS_ROW_SHORT.match(text) or ADDRESS_ROW_CANON.match(text)
    if block is None or not match or match.group("block") != block:
        return None
    return block, column, int(match.group("row"))


def identity_binding(dataset: dict, address: str, text: str, rule: dict) -> tuple:
    """这一格是不是它所属那条记录自己的身份标签（闭集 verdict，逐字比较，永不取第一条）。"""
    parts = address_row_parts(address)
    if parts is None:
        return "address_unparsable", []
    block, _column, row_index = parts
    rows = dataset.get(block) or []
    if row_index >= len(rows):
        return "row_out_of_range", []
    row = rows[row_index]
    cells = row if isinstance(row, list) else list(row.values())
    coords = {str(cell).strip() for cell in cells
              if isinstance(cell, str) and COORD_SHAPE.match(str(cell).strip())}
    if not coords:
        return "no_coord", []
    strict, loose = [], []
    for key, target in (dataset.get("map_targets") or {}).items():
        if not isinstance(target, dict) or str(key).split("|")[-1].strip() != text:
            continue
        match_kind = "coords+label" if str(target.get("coords") or "").strip() in coords else "label_only"
        (strict if match_kind == "coords+label" else loose).append(
            {"target_key": key, "match": match_kind})
    if len(strict) == 1:
        return "unique", strict
    if len(strict) > 1:
        return "ambiguous", strict
    if loose:
        return "label_without_coord", loose
    return "no_binding", []


def registered_english_index(dataset: dict, rule: dict) -> dict:
    """登记面英文名 → 它的中文名集合（tier1 名对＋tier2 机读名，都从 display_names 唯一实现读）。"""
    import display_names

    cache_key = ("registered_english", id(dataset), rule["min_registered_english_len"])
    if cache_key in _REGISTRY_CACHE:
        return _REGISTRY_CACHE[cache_key]
    index: dict = {}
    min_len = int(rule["min_registered_english_len"])
    for reader in (display_names.read_pairs, display_names.read_machine_display_names):
        for cn, rec in reader(dataset)[0].items():
            english = str(rec.get("english") or "").strip()
            if len(english) >= min_len:
                index.setdefault(english, set()).add(cn)
    _REGISTRY_CACHE[cache_key] = index
    return index


def borrowed_display_names(english: str, chinese: str, index: dict) -> list:
    """英文里逐字出现登记面英文名、而本格中文并没有写那个中文名 ⇒ 散文里借了具体名称。

    只认整串命中（带非字母数字边界的 lookaround），不做前缀／近似：业主裁的是「借品牌名不等于
    显示名槽」，这一档宁少不多——判不准就不迁移，继续留在 prose 里等语义复核。
    """
    text = str(english or "")
    hits = []
    for name, chines in sorted(index.items()):
        if not re.search(r"(?<![A-Za-z0-9&'.\-])%s(?![A-Za-z0-9])" % re.escape(name), text):
            continue
        if any(cn in (chinese or "") for cn in chines):
            continue
        hits.append({"borrowed_english": name, "registered_chinese": sorted(chines)})
    return hits


def display_name_registered_english(dataset: dict, cn_label: str):
    """迁移到 DISPLAY_NAME 之后，这一格的英文**由登记面发**：取那条登记的英文名，不是译文。"""
    import display_names

    for reader in (display_names.read_pairs, display_names.read_machine_display_names):
        rec = reader(dataset)[0].get(cn_label)
        if rec and str(rec.get("english") or "").strip():
            return str(rec["english"]).strip(), reader.__name__
    return "", ""


def prose_slot_subclass(dataset: dict, cn: str, en: str, index: dict | None = None,
                        rule: dict | None = None) -> tuple:
    """留在 prose 的行按**英文面**再分两桶：借了具体名称（INJECTED）／干净（CLEAN）。

    为什么这一步不放进 classify：两桶的区别要看这一行实际发出去的英文（草稿或 legacy 值），
    而 fragment 只有中文。把 owner 判定与译文质量判定分开，分类器就不会「等译文出来再决定这格归谁」
    ——那等于把所有权交给译文，正是业主否决的按文本猜测。
    """
    rule = rule or identity_migration_rule()
    index = index if index is not None else registered_english_index(dataset, rule)
    borrowed = borrowed_display_names(en, cn, index)
    return ("PROSE_SLOT_WITH_INJECTED_NAME" if borrowed else "PROSE_SLOT_CLEAN"), borrowed


def classify_fragment_ownership(dataset: dict, fragments: list | None = None) -> dict:

    """MT-D 的唯一判定实现：原始清册 → 逐地址 owner → 四类互斥结果 → 逐地址清单 + 分桶恒等式。

    返回 `worklist`（PROSE_REQUIRED 那批）给 --export / validate_table / apply_table 共用，
    并返回 `accounting`（CA/PH 各自一条恒等式）与 `findings`。本函数**不写任何东西**。
    """
    raw = collect_fragments(dataset, skip_covered=False) if fragments is None else list(fragments)
    # PROSE_TABLE 的地址全集来自**采集器本身**（不是传进来的那份清单）：
    # 否则「传一条 fragment」就能自证它是 prose 的，判定就退化成先看谁开口、后看谁登记。
    prose_addresses = prose_address_set(dataset)
    columns = non_prose_column_registry()
    adapter = shape_adapter(dataset)
    rule = identity_migration_rule()
    eligible = identity_eligible_slots(rule) if rule["status"] == "ENROLLED" else set()
    rows: list = []
    buckets: dict = {outcome: [] for outcome in OUTCOME_VOCABULARY}
    findings: list = []
    # 形状不成立时**不判所有权**：别名与数据一旦脱节（行长变了、字段换位、对象与数组混杂），
    # 按位置判出来的主人可能指在错误的格上，那比不判更糟。上游 validate/apply 会因这些 finding 停住。
    for item in adapter["blocking"]:
        findings.append({"code": "dataset_shape_blocked",
                         "detail": "%s｜%s" % (item["code"], item["detail"])})
    for fragment in raw:
        per_address = []
        owner_union: set = set()
        unresolved_reasons: list = []
        migrated: list = []
        for address in fragment["addresses"]:
            owners = address_owners(address, prose_addresses, columns)
            block, slot = normalize_address(address)
            adjudicated = alias_adjudication(block, slot, columns) if block else ""
            # 业主 2026-11-01 MT-D2 第 2 条：别名证明「这一格就是类别/专名列」时，主人是那个语义通道；
            # RENDERED_COLUMNS 里那条位置登记**不撤销**（撤了就把已知结构伪装成未登记数据），
            # 但它在这里让位。没有别名证明的双主张仍然是 MIXED，不靠这一步消解。
            if adjudicated and adjudicated in owners and "PROSE_TABLE" in owners:
                owners = [adjudicated]
                migrated.append({"address": address, "slot": [block, slot],
                                 "alias_field": alias_field_by_slot().get((block, slot)),
                                 "owner_after_migration": adjudicated})
            # MT-E1：别名之后**仍然是 prose** 的地址，才有资格试身份绑定。顺序不能倒——
            # 别名证明的是「这一格本来就是类别/专名列」，那是列级事实；身份绑定证明的是
            # 「这一格的内容就是它所属记录的名字标签」，那是行级事实。两者都成立时列级先走。
            identity = None
            if owners == ["PROSE_TABLE"] and (str(block), str(slot)) in eligible:
                verdict, evidence = identity_binding(dataset, address, fragment["cn"], rule)
                identity = {"verdict": verdict, "evidence": evidence,
                            "eligible_slot": [str(block), str(slot)]}
                if verdict == "unique":
                    owners = [rule["owner_after_claim"]]
                    migrated.append({"address": address, "slot": [block, slot],
                                     "basis": "identity_binding_unique",
                                     "identity_evidence": evidence,
                                     "owner_after_migration": rule["owner_after_claim"]})
            if not owners:
                unresolved_reasons.append(NO_OWNER_ADDRESS)
            owner_union |= set(owners)
            entry = {"address": address, "owners": owners,
                     "slot": list(normalize_address(address))}
            if identity is not None:
                entry["identity_binding"] = identity["verdict"]
                entry["identity_evidence"] = identity["evidence"]
            per_address.append(entry)
        claim = replacement_claim(dataset, fragment["cn"])
        detail = list(per_address)
        if claim["claimed"]:
            if claim["acts_as_owner"]:
                # 成证的 replacement 主张按**该 fragment 的每个地址**记 owner：它是按整格原文取值的，
                # 所以它答的是「这一格的英文在哪」，不只是「这句别处有没有英文」。
                owner_union.add("REGISTERED_EN_REPLACEMENT")
                unresolved_reasons = [item for item in unresolved_reasons
                                      if item != NO_OWNER_ADDRESS]
                for item in detail:
                    if "address" in item and not item["owners"]:
                        item["owners"] = ["REGISTERED_EN_REPLACEMENT"]
            elif claim["disposition"] == LEGACY_OWNER_CLAIMS:
                unresolved_reasons.append(UNPROVENANCED_CLAIM)
            # candidate_only 档位下不成证的句子既不抢 owner 也不卡桶：它按自己的地址归真实通道，
            # 旧英文只登记成 MT-E 的对照候选（账上留着「这里曾有一段英文」，但它不是来源）。
            detail.append({"text_claim": "en_text_replacements",
                           "en_value": claim["en_value"][:80],
                           "provenanced": claim["provenanced"],
                           "disposition": claim["disposition"],
                           "acts_as_owner": claim["acts_as_owner"],
                           "legacy_candidate": claim["acts_as_candidate"],
                           "missing_fields": claim["missing_fields"],
                           "en_value_drift": claim["en_value_drift"],
                           "provenance_is_object": claim["provenance_is_object"]})
        # 四条顺序＝合同 ownership.precedence，写在判定里是因为两桶 BLOCKED 的处置话术不同：
        # 缺来源要去补来源，缺登记要去补列登记，混判要业主裁决谁负责。
        if UNPROVENANCED_CLAIM in unresolved_reasons:
            outcome, reasons = "OWNER_UNRESOLVED_BLOCKED", [UNPROVENANCED_CLAIM]
        elif NO_OWNER_ADDRESS in unresolved_reasons:
            outcome, reasons = "OWNER_UNRESOLVED_BLOCKED", [NO_OWNER_ADDRESS]
        elif not owner_union:
            outcome, reasons = "OWNER_UNRESOLVED_BLOCKED", [NO_OWNER_ADDRESS]
        elif len(owner_union) > 1:
            outcome, reasons = "MIXED_OWNER_BLOCKED", [MIXED_OWNER]
        elif owner_union == {"PROSE_TABLE"}:
            outcome, reasons = "PROSE_REQUIRED", []
        else:
            outcome, reasons = "OWNED_NON_PROSE", []
        # 迁移到 DISPLAY_NAME 之后，这一格的英文**由登记面发**（read_pairs／tier2 机读名）。
        # 所以专名形状门要对「中文标签 ↔ 登记英文名」再跑一次：owner 换了不等于配对好了。
        # 不在这里发，它就会在换 owner 那一瞬间从账上消失——业主明令不许那样收场。
        display_name_shape = []
        if outcome == "OWNED_NON_PROSE" and owner_union == {rule["owner_after_claim"]} and any(
                item.get("basis") == "identity_binding_unique" for item in migrated):
            import prose_reconcile
            dn_en, dn_reader = display_name_registered_english(dataset, fragment["cn"])
            if dn_en:
                display_name_shape = [{"registered_english": dn_en, "registry_reader": dn_reader,
                                       "addresses": [item["address"] for item in migrated
                                                     if item.get("basis") == "identity_binding_unique"],
                                       "conflicts": prose_reconcile.proper_name_conflicts(
                                           fragment["cn"], dn_en,
                                           prose_reconcile.proper_name_rule())}]
        buckets[outcome].append(fragment["id"])
        rows.append({"id": fragment["id"], "cn": fragment["cn"], "kind": fragment["kind"],
                    "outcome": outcome, "reasons": reasons,
                    "owners": sorted(owner_union), "address_detail": detail,
                    "slot_migration": migrated, "display_name_shape": display_name_shape})
    total = sum(len(ids) for ids in buckets.values())
    if total != len(raw) or len({f for ids in buckets.values() for f in ids}) != len(raw):
        findings.append({"code": "ownership_accounting_mismatch",
                         "detail": ("分桶合计 %d ≠ 原始清册 %d，或桶间有同一 id（互斥性破了）："
                                    "判定实现自己错了，任何 worklist 数字都不许用"
                                    % (total, len(raw)))})
    # 这里的 findings 是**所有权账**（每条被 block 的 fragment 都得有人去处置），不是 MT-C 的表门：
    # validate_table 只取 worklist/blocked_ids，不会因为这些条目存在就判表不合格。
    # 码名逐条写死在 append 里（不写成 `{"code": reason}`）：双向闭合测试靠扫常量名解析码，
    # 让码值流经一个变量就会「登记了却扫不到」，那是判据的洞而不是门失效。
    for row in rows:
        detail_text = "%s (%s) %r ⇒ %s" % (row["id"], row["kind"], row["cn"][:40], row["outcome"])
        if UNPROVENANCED_CLAIM in row["reasons"]:
            findings.append({"code": UNPROVENANCED_CLAIM,
                             "detail": "%s｜en_text_replacements 里有这句但给不出 contract/en 值/来源："
                                       "既不许据此剔除，也不许写进散文表" % detail_text})
        if NO_OWNER_ADDRESS in row["reasons"]:
            findings.append({"code": NO_OWNER_ADDRESS,
                             "detail": "%s｜有地址没被任何通道认领：先补列登记或类别/专名注册，"
                                       "默认算 prose 就是替业主认领所有权" % detail_text})
        if row["outcome"] == "MIXED_OWNER_BLOCKED":
            findings.append({"code": MIXED_OWNER,
                             "detail": "%s｜主张落在 %s：prose_en 按内容键且优先级高于类别/专名面，"
                                       "进表就覆盖别的通道" % (detail_text, ",".join(row["owners"]))})
        # 显示名通道的形状缺陷：**跟着 owner 走**，不留在散文账上重复计一次，也不许凭空消失。
        for item in row.get("display_name_shape") or []:
            for conflict in item["conflicts"]:
                findings.append({"code": "display_name_proper_name_variant",
                                 "detail": "%s｜这格已换给 DISPLAY_NAME，英文由登记面 %s 发（%r），"
                                           "但中文里的 %r 与登记英文里的 %r 编辑距离 %d ⇒ 中英两面对不上；"
                                           "要修的是那条登记（或按来源裁谁作准），把它退回散文表不算处置"
                                           % (detail_text, item["registry_reader"],
                                              item["registered_english"], conflict["cn_token"],
                                              conflict["en_token"], conflict["distance"])})
    accounting = {"raw_fragments": len(raw),
                  "prose_required": len(buckets["PROSE_REQUIRED"]),
                  "owned_non_prose": len(buckets["OWNED_NON_PROSE"]),
                  "mixed_owner_blocked": len(buckets["MIXED_OWNER_BLOCKED"]),
                  "unresolved_owner_blocked": len(buckets["OWNER_UNRESOLVED_BLOCKED"]),
                  "identity_holds": len(raw) == total,
                  "identity": "raw_fragments = prose_required + owned_non_prose + "
                              "mixed_owner_blocked + unresolved_owner_blocked",
                  "cross_run_dedup": False}
    return {"fragments": len(raw), "worklist": [f for f in raw
                                                if f["id"] in set(buckets["PROSE_REQUIRED"])],
            "shape": {"alias_table_version": adapter["alias_table_version"],
                      "aliases": sorted(adapter["aliases"]),
                      "rows_checked": adapter["rows_checked"],
                      "blocking": adapter["blocking"], "clean": adapter["clean"]},
            "slot_migrated_rows": sum(1 for row in rows if row["slot_migration"]),
            "blocked_ids": {key: list(value) for key, value in buckets.items()
                            if key != "PROSE_REQUIRED"},
            "counts": {key: len(value) for key, value in buckets.items()},
            "rows": rows, "accounting": accounting, "findings": findings,
            "slot_identity_migration": {
                "rule_status": rule["status"],
                "eligible_sites_checked": len([item for row in rows for item in row["address_detail"]
                                               if "identity_binding" in item]),
                "verdict_counts": {verdict: sum(1 for row in rows for item in row["address_detail"]
                                                if item.get("identity_binding") == verdict)
                                   for verdict in IDENTITY_VERDICTS},
                "migrated_row_ids": sorted(row["id"] for row in rows if
                                           row["outcome"] == "OWNED_NON_PROSE" and any(
                                               item.get("basis") == "identity_binding_unique"
                                               for item in row["slot_migration"])),
                # 部分绑定：同一句中文在一个地址唯一绑定、在另一个地址绑不上 ⇒ 整行判 MIXED，
                # 谁也没迁走。它**不进** migrated_row_ids（迁走＝这一行真的换了主人），
                # 但要单独点名：否则「同文不同地址」这种形状在账上就与成功迁移长得一样。
                "partial_binding_blocked_ids": sorted(
                    row["id"] for row in rows if row["outcome"] == "MIXED_OWNER_BLOCKED" and any(
                        item.get("basis") == "identity_binding_unique" for item in row["slot_migration"])),
                "display_name_corrections": [
                    {"id": row["id"], "cn": row["cn"],
                     "registered_english": item["registered_english"],
                     "registry_reader": item["registry_reader"],
                     "addresses": item["addresses"],
                     "conflicts": item["conflicts"]}
                    for row in rows for item in row["display_name_shape"] if item["conflicts"]],
                "prose_subclass_vocabulary": list(PROSE_SUBCLASS_VOCABULARY)},
            "owner_vocabulary": list(OWNER_VOCABULARY), "outcomes": list(OUTCOME_VOCABULARY),
            "registry": "references/prose-translation-contract.json::ownership"}


def prose_translation_worklist(dataset: dict) -> list:
    """唯一取数口：该进翻译表的 fragment＝PROSE_REQUIRED 那批。

    被 block 的条目**留在它自己的通道里等处置**，不降级进表（业主第 7 条）：类别词根解析失败
    是类别缺陷，靠机器散文翻译绕过＝把「通道没做好」改写成「翻译表多一条」，两件事都不是真相。
    """
    return classify_fragment_ownership(dataset)["worklist"]


def locate_gaps(dataset: dict, gaps: list[str]) -> list[dict]:
    """Answer "which dataset cell produced this untranslated string" for every EN gap.

    The contract is locatability, not translation volume (§2.2.2 amendment): a gap the owner can
    find by address is worth more than a gap that was machine-filled to make a counter read zero.

    七种 verdict，闭集见 VERDICTS；分流的根据只有一条实测：这句在不在数据里、在不在渲染层文件里、
    在不在专名显示面或格式化器槽里。
    旧版本只有三种，把「登记表没覆盖这一列」直接写成「字符串在 spa-layout.js 里」——2026-10-31 对
    两棵候选实测：CA 204 条、PH 9 条被这样标成的字面量，逐条回数据里查，204/204 与 9/9 都是数据集
    里的真实单元格（剥掉渲染层连接符后逐字命中），没有一条真的躺在 assets/spa-layout.js 里。
    现在这类改判 dataset_cell_unregistered 并给出地址；renderer_literal 只在渲染层文件里量到才发；
    两边都量不到的进 unattributed（承认定位不了，不许冒充「渲染层缺陷」）。

    MT-1（2026-10-31）再补一层规范化：`unregistered` 的实测里有一批行其实落在**已登记列**上，
    差别只在 DOM 形态带了前导连接符或价格脚手架（CA 审计面 14 条 `budget[*][2]` 就是这个形态，
    `assets/spa-layout.js` 的 d-theme 槽写的是 `'| ' + planStr`）。这类现在判 `dataset_cell` 并带
    `matched_form`，因为把它们记成「列没登记」会把一条只需要补英文来源的行误导成要先改渲染契约。
    """
    fragments = collect_fragments(dataset)
    forms = registered_fragment_forms(fragments)
    index = dataset_value_index(dataset)
    display_keys, display_collisions = proper_name_keys(dataset)
    layout = layout_js_text()
    rows = []
    for gap in gaps:
        text = str(gap or "").strip()
        if not text:
            continue
        exact = [f for f in fragments if f["cn"] == text]
        collisions = sorted({f["id"] for key in normalized_forms(text) for f in forms.get(key, [])})
        if len(exact) == 1:
            # 业主 REVISE 第 1 条：精确原文优先，但规范化碰撞必须一起报出来，不许静默隐藏——
            # 「原文」与「| 原文 |」是导出表里两条不同的 fragment，两条都要有译文才允许写盘。
            fragment = exact[0]
            rows.append({"cn": text, "verdict": "dataset_cell", "kind": fragment["kind"],
                         "addresses": fragment["addresses"],
                         "fragment_ids": [fragment["id"]],
                         "normalized_collision_fragment_ids":
                             [i for i in collisions if i != fragment["id"]],
                         "component_matches": [{"segment": text, "fragment_id": fragment["id"],
                                                "kind": fragment["kind"],
                                                "addresses": fragment["addresses"],
                                                "matched_form": "exact_original"}],
                         "component_coverage": 1.0, "matched_form": "exact_original",
                         "fix": "补这条列的英文来源（translate_prose --apply）"})
            continue
        if len(exact) > 1:
            rows.append({"cn": text, "verdict": "render_composite", "kind": "composite",
                         "composite_reason": "ambiguous_original",
                         "collision_fragment_ids": sorted(f["id"] for f in exact),
                         "normalized_collision_fragment_ids": collisions,
                         "component_matches": [], "component_coverage": 0.0,
                         "unresolved_parts": [], "ambiguous_parts": [text], "applicable": False,
                         "fix": "同一原文逐字落在 %d 条 fragment 上：%s——挑一条就是替业主编答案，"
                                "整行阻断（不静默取第一条）" % (
                                    len(exact), ",".join(sorted(f["id"] for f in exact)))})
            continue
        # MT-1 REVISE（业主 2026-10-31）：复合文本一律走**全覆盖**判定。任一片段没命中或多义，
        # 整行都不许判 dataset_cell——「已登记片段 · 未登记片段」若算成可 --apply，就是假可翻译计数。
        components = composite_components(text, forms)
        if components["status"] in ("single", "complete"):
            hits = components["components"]
            rows.append({"cn": text, "verdict": "dataset_cell",
                         "kind": hits[0]["kind"] if len(hits) == 1 else "composite",
                         "addresses": sorted({address for hit in hits for address in hit["addresses"]}),
                         "fragment_ids": [hit["fragment_id"] for hit in hits],
                         "normalized_collision_fragment_ids": components["collision_fragment_ids"],
                         "component_matches": hits,
                         "component_coverage": components["component_coverage"],
                         "matched_form": report_status(components["status"]),
                         "fix": "全部含中文片段都唯一回指已登记 fragment：这条现在就能 --apply。"})
            continue
        if components["status"] in ("partial", "ambiguous"):
            reason = ("ambiguous_form" if components["status"] == "ambiguous" or
                      components["ambiguous_parts"] else "partial_coverage")
            rows.append({"cn": text, "verdict": "render_composite", "kind": "composite",
                         "composite_reason": reason,
                         "addresses": sorted({address for hit in components["components"]
                                              for address in hit["addresses"]}),
                         "component_matches": components["components"],
                         "component_coverage": components["component_coverage"],
                         "unresolved_parts": components["unresolved_parts"],
                         "ambiguous_parts": components["ambiguous_parts"],
                         "unresolved_in_data": [part for part in components["unresolved_parts"]
                                                if part not in index],
                         "applicable": False,
                         "fix": ("同一规范化形态回指多条 fragment（" + "、".join(components["ambiguous_parts"][:3]) +
                                 "）：挑一条就是替业主编答案，整行阻断" if reason == "ambiguous_form" else
                                 "多列拼成一句，但只有部分片段能唯一回指已登记 fragment："
                                 "整行不可 --apply（缺的那段会被冒充成已覆盖），要逐段翻译后拼接")})
            continue
        bare = text.strip(JOINERS).strip()
        addresses = index.get(text) or index.get(bare) or []
        if addresses:
            slots = {slot_of_address(a) for a in addresses}
            if slots and None not in slots and all(slot in FORMATTER_SLOTS for slot in slots):
                rows.append({"cn": text, "verdict": "money_scaffold", "kind": "formatter_slot",
                             "addresses": sorted(addresses),
                             "formatter": sorted({FORMATTER_SLOTS[slot] for slot in slots}),
                             "applicable": False,
                             "joiner_stripped": bare != text,
                             "fix": "这一格由渲染层的登记格式化器负责（%s），不进翻译表；"
                                    "格式化器也认不出时它才显示 (translation pending) 并留在缺口账上。"
                                    "把它塞进 prose_en 就是让散文翻译表冒充金额规则。"
                                    % "、".join(sorted({FORMATTER_SLOTS[s] for s in slots}))})
                continue
            owner = display_keys.get(text) or display_keys.get(bare)
            if owner:
                rows.append({"cn": text, "verdict": "proper_name", "kind": "display_only_name",
                             "addresses": sorted(addresses), "display_source": owner,
                             "channel_state": "resolved_by_channel",
                             "applicable": False, "joiner_stripped": bare != text,
                             "fix": "专名显示面（%s）负责这一格：tier1 用数据里已有的英文名，"
                                    "tier2 只放行 provenance 完整的机器翻译显示名。"
                                    "不得写回 canonical identity、地图查询、evidence 或 VERIFIED；"
                                    "也不得靠类别词根拼一个看起来权威的英文名。" % owner})
                continue
            name_slot = display_name_slots()
            owned = [a for a in addresses if slot_of_address(a) in name_slot]
            if owned:
                collided = text in display_collisions or bare in display_collisions
                rows.append({"cn": text, "verdict": "proper_name", "kind": "display_only_name",
                             "addresses": sorted(owned), "display_source": None,
                             "channel_state": "blocked_by_collision" if collided
                             else "awaiting_tier2_provenance",
                             "applicable": False, "joiner_stripped": bare != text,
                             "fix": ("这一格在专名列里，但同一个中文名对到两个不同英文（实测两条都在数据里）："
                                     "要的是人工裁决哪一个才是它，不是挑一条、也不是补一个机器显示名盖过去。"
                                     if collided else
                                     "这一格住在专名显示面认领的列里（display-name-channel），"
                                     "但同行没有英文格：只有 provenance 完整的 machine_translated_display_name "
                                     "能让它显示，来源不齐就继续 pending。它不是「没人负责的未登记列」，"
                                     "也不是 prose 翻译表的活；更不许拿 canonical identity/地图查询/VERIFIED 当来源。")})
                continue
            rows.append({"cn": text, "verdict": "dataset_cell_unregistered",
                         "kind": "unregistered_column", "addresses": sorted(addresses),
                         "joiner_stripped": bare != text,
                         "applicable": False,
                         "fix": "数据里就有这句（addresses 是它的地址），但 RENDERED_COLUMNS 没登记"
                                "这一列：先补列登记才能 --apply。这是数据缺口，不是渲染层缺陷"})
            continue
        if text in layout or (bare and bare in layout):
            rows.append({"cn": text, "verdict": "renderer_literal", "kind": "literal",
                         "addresses": [], "in_layout_js": True,
                         "layout_js_bytes": len(layout.encode("utf-8")),
                         "fix": "assets/spa-layout.js 实测含此串（本条按文件字节判定）：补 I18N/词根，"
                                "别在数据侧硬塞"})
            continue
        rows.append({"cn": text, "verdict": "unattributed", "kind": "unlocated", "addresses": [],
                    "in_layout_js": False,
                    "fix": "数据里、assets/spa-layout.js 里都量不到这句：定位口径有洞，"
                           "记成任何一侧的缺陷都是假归因——先补测量口径再谈修"})
    return rows


def read_gap_list(path: Path) -> list[str]:
    """Accept either a visual-qa report, its per-check field, or a bare list of strings."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        # A bare pending list ships as strings; the located-report form ships as rows with "cn".
        return [str(item) if isinstance(item, str) else str(item.get("cn", ""))
                for item in payload if item]
    if isinstance(payload, dict) and "checks" in payload:
        found: list[str] = []
        for check in payload["checks"]:
            for gap in check.get("en_translation_pending_list") or []:
                if gap not in found:
                    found.append(gap)
        return found
    if isinstance(payload, dict) and "pending" in payload:
        return [str(g) for g in payload["pending"]]
    raise ValueError("--locate-gaps 需要 visual-qa 报告、{pending:[…]} 或字符串数组")


def apply_table(run_dir: Path, dataset_path: Path, table_path: Path, *, write: bool) -> dict:
    """MT-C：翻译表过合同 ⇒ 整份折进封存输入；任何一条阻断项 ⇒ 目标文件字节一字不变。

    三条不可让的动作纪律（都是本轮之前踩过的坑，写进 prose-translation-contract.json::write_discipline）：
      1. 只 write_bytes，不用 write_text——Windows 会把 LF 翻成 CRLF，整份 dataset 的哈希跟着变，
         而内容语义没变，那种「没人改过却哈希变了」的账最坑；
      2. 写完读回字节复算 SHA-256，与内存里将要写入的字节复算值比对；
      3. 重读后的 JSON 与内存对象逐键相等（round trip），防 ensure_ascii/键序之外的任何改写。
    """
    dataset_path = Path(dataset_path)
    raw_before = dataset_path.read_bytes()
    source_sha = hashlib.sha256(raw_before).hexdigest().upper()
    dataset = json.loads(raw_before.decode("utf-8"))
    table_text = Path(table_path).read_text(encoding="utf-8")
    table_raw = json.loads(table_text)
    duplicates = duplicate_entry_ids(table_text)
    fragments = collect_fragments(dataset, skip_covered=False)
    report = validate_table(dataset, table_raw, run_name=Path(run_dir).name,
                            source_dataset_sha256=source_sha, fragments=fragments,
                            duplicate_ids=duplicates)
    entries = report["entry_records"]
    worklist = report["worklist"]
    blocked_of = report["blocked_of"]
    report["translated"] = len(worklist) - len(report["missing"])
    prose_en: dict[str, str] = {}
    rebuilt = 0
    for fragment in worklist:
        english = _as_text((entries.get(fragment["id"]) or {}).get("en")).strip()
        if not english:
            continue
        # A fragment is keyed by content, so one wording can be a POI note in one row and a
        # chain description in another. Note addresses need the money prefix re-attached and are
        # keyed by the full cell; plain uses are keyed by the fragment text itself.
        plain = False
        for address in fragment["addresses"]:
            note_match = POI_NOTE_ADDRESS.match(address)
            if not note_match:
                plain = True
                continue
            cat, index = note_match.group(1), int(note_match.group(2))
            row = (dataset.get(cat) or [])[index]
            head, _ = note_price_prefix(str(row[10]))
            prose_en[str(row[10]).strip()] = head + english
            rebuilt += 1
        if plain or not fragment["addresses"]:
            prose_en[fragment["cn"]] = english
    provenance = table_raw.get("provenance") if isinstance(table_raw, dict) else None
    # 兜底断言（写盘前）：prose_en 的键**只能**来自 worklist。blocked 的中文混进来就是
    # 「不降级进表」这条被代码路径绕过，而绕过的后果要到读者页才看得见。
    blocked_texts = {fragment["cn"] for ident, outcome in blocked_of.items()
                     for fragment in fragments if fragment["id"] == ident}
    leaked = sorted(key for key in prose_en if key in blocked_texts)
    if leaked:
        raise ValueError("prose_en 里出现了所有权被 block 的原文（%d 条，样本 %s）："
                         "判定与写盘不是同一条路径，先修工具再谈翻译表"
                         % (len(leaked), [item[:30] for item in leaked[:3]]))
    report.update({
        "prose_entries_written": len(prose_en),
        "raw_fragments": len(fragments),
        "worklist_fragments": len(worklist),
        "notes_recomposed": rebuilt,
        "provenance": provenance,
        "provenance_is_object": isinstance(provenance, dict),
        "entries_in_table": len(entries),
        "run_dir": Path(run_dir).name,
        "dataset_before_sha256": source_sha,
        "dataset_bytes_before": len(raw_before),
        "written_by_this_run": False,
    })
    if write:
        if report["status"] != "PASS":
            codes = sorted({item["code"] for item in report["findings"]})
            raise ValueError("翻译表未过 MT-C 合同（%d 条阻断项，涉及 %s）："
                             "禁止部分写入封存输入——宁可整页继续 (translation pending)，"
                             "不可半份英文，也不可先写能写的" % (len(report["findings"]),
                                                           ",".join(codes[:8])))
        payload = dict(dataset)
        payload["prose_en"] = prose_en
        payload["prose_en_provenance"] = {
            "schema_version": table_raw.get("schema_version"),
            "table_sha256": report["table_sha256_recomputed"],
            "table_path": Path(table_path).name,
            "contract": contract()["registered_by_round"],
            "fragments": len(worklist),
            "raw_fragments": len(fragments),
            "ownership": report["ownership"],
            "entries": len(entries),
            "provenance": provenance,
        }
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if b"\r\n" in data:
            raise ValueError("将要写入的字节里出现 CRLF（合同 write_discipline 禁止）："
                             "%d 处，先查是不是哪一步用了 write_text 的换行习惯"
                             % data.count(b"\r\n"))
        dataset_path.write_bytes(data)
        raw_after = dataset_path.read_bytes()
        after_sha = hashlib.sha256(raw_after).hexdigest().upper()
        report.update({
            "dataset_after_sha256": after_sha,
            "dataset_bytes_after": len(raw_after),
            "crlf_in_written_file": raw_after.count(b"\r\n"),
            "written_by_this_run": True,
        })
        if after_sha != hashlib.sha256(data).hexdigest().upper():
            raise ValueError("写完复算不等（内存 %s / 磁盘 %s）：写入被改写，本轮不算数"
                             % (hashlib.sha256(data).hexdigest().upper(), after_sha))
        if json.loads(raw_after.decode("utf-8")) != payload:
            raise ValueError("round trip 不等：磁盘上的 dataset 与内存对象不是同一个东西")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect-stage prose translation bridge")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--dataset", default="")
    parser.add_argument("--export", default="", help="write the fragment list to this JSON file")
    parser.add_argument("--ownership-report", default="",
                        help="MT-D：把逐地址所有权矩阵写到这个 JSON 文件（四桶恒等式 + 处置清单）")
    parser.add_argument("--legacy-migration-report", default="",
                        help="MT-D2：把 en_text_replacements 的逐地址迁移清册写到这个 JSON 文件"
                             "（八个迁移桶 + 恒等式；与四桶账分母不同，两张都要看）")
    parser.add_argument("--table", default="", help="translation table to fold into the dataset")
    parser.add_argument("--apply", action="store_true", help="write prose_en into dataset.json")
    parser.add_argument("--locate-gaps", default="",
                        help="visual-qa 报告或 pending 清单，逐条回答是哪一格数据缺英文来源")
    parser.add_argument("--gap-report", default="", help="定位表输出路径（默认写 <run>/outputs/gates/en-gap.json）")
    args = parser.parse_args()
    run = Path(args.run_dir).resolve()
    dataset_path = Path(args.dataset) if args.dataset else run / "dataset.json"
    if args.locate_gaps:
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        rows = locate_gaps(dataset, read_gap_list(Path(args.locate_gaps)))
        target = Path(args.gap_report) if args.gap_report else run / "outputs" / "gates" / "en-gap.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        by_verdict: dict[str, int] = {}
        for row in rows:
            by_verdict[row["verdict"]] = by_verdict.get(row["verdict"], 0) + 1
        target.write_text(json.dumps({"source": str(args.locate_gaps), "gaps": len(rows),
                                      "by_verdict": by_verdict, "rows": rows},
                                     ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"gaps": len(rows), "by_verdict": by_verdict, "report": str(target)},
                         ensure_ascii=False))
        for row in rows[:20]:
            print("  %-17s %-46s %s" % (row["verdict"], row["cn"][:44],
                                        ",".join(row["addresses"][:2]) or row["fix"]))
        return 0
    if args.export or args.ownership_report:
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        ownership = classify_fragment_ownership(dataset)
        # --export 的形状不变（fragment 数组），但内容改成 worklist：MT-D 之后
        # 「要翻的清单」只有这一个取数口，导出、校验、写盘读的是同一批。
        if args.export:
            Path(args.export).write_text(json.dumps(ownership["worklist"], ensure_ascii=False,
                                                    indent=1) + "\n", encoding="utf-8")
        if args.ownership_report:
            report = {key: value for key, value in ownership.items() if key != "worklist"}
            report["worklist_size"] = len(ownership["worklist"])
            # 「--export 与 worklist 同源」不能靠注释声明：把导出文件读回来比一次字节。
            report["export_matches_worklist"] = (
                not args.export or json.loads(Path(args.export).read_text(encoding="utf-8"))
                == ownership["worklist"])
            Path(args.ownership_report).write_text(json.dumps(report, ensure_ascii=False,
                                                              indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"exported": len(ownership["worklist"]),
                          "by_kind": _counts(ownership["worklist"]),
                          "accounting": ownership["accounting"],
                          "blocking_codes": sorted({item["code"] for item in
                                                    ownership["findings"]}),
                          "ownership_report": args.ownership_report or None},
                         ensure_ascii=False, indent=1))
        return 0 if ownership["accounting"]["identity_holds"] else 2
    if args.legacy_migration_report:
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        ownership = classify_fragment_ownership(dataset)
        inventory = legacy_migration_inventory(dataset, ownership)
        payload = dict(inventory)
        # 逐条 owner 账留全量（业主点名要「每一条的地址与判定」），但 rows 与 buckets 是同一份
        # 账的两种写法：留两份就是把一个事实登记两次，改一处忘一处时两张表会互相打脸。
        payload["buckets_are_derived_from_rows"] = True
        payload.pop("buckets", None)
        payload["fragment_accounting"] = ownership["accounting"]
        payload["dataset_sha256"] = hashlib.sha256(dataset_path.read_bytes()).hexdigest().upper()
        blob = (json.dumps(payload, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        Path(args.legacy_migration_report).write_bytes(blob)
        if b"\r\n" in Path(args.legacy_migration_report).read_bytes():
            raise ValueError("清册文件被写成 CRLF：违反 write_discipline.line_endings")
        print(json.dumps({"legacy_entries": inventory["legacy_entries"],
                          "counts": inventory["counts"],
                          "identity_holds": inventory["identity_holds"],
                          "shape_blocked": inventory["shape_blocked"],
                          "blocking_codes": sorted({item["code"] for item in inventory["findings"]}),
                          "report": args.legacy_migration_report},
                         ensure_ascii=False, indent=1))
        return 0 if (inventory["identity_holds"] and not inventory["shape_blocked"]) else 2
    if not args.table:
        parser.error("--export 或 --table 至少给一个")
    report = apply_table(run, dataset_path, Path(args.table), write=args.apply)
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("missing", "findings", "entry_records", "worklist",
                                   "blocked_of")},
                     ensure_ascii=False, indent=1))
    codes: dict[str, int] = {}
    for item in report["findings"]:
        codes[item["code"]] = codes.get(item["code"], 0) + 1
    print(json.dumps({"blocking_codes": codes, "findings_total": len(report["findings"]),
                      "sample": report["findings"][:8]}, ensure_ascii=False, indent=1))
    for item in report["missing"][:20]:
        print("MISSING", item["id"], item["kind"], item["cn"][:60])
    for ident in report["stale_ids"][:20]:
        print("STALE", ident)
    return 0 if report["status"] == "PASS" else 2


def _counts(fragments: list[dict]) -> dict:
    out: dict[str, int] = {}
    for fragment in fragments:
        out[fragment["kind"]] = out.get(fragment["kind"], 0) + 1
    return out


if __name__ == "__main__":
    raise SystemExit(main())
