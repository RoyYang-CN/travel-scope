"""Deterministic map-target validation and URL construction for Travel-Scope.
Version: V5.0.0
"""
from __future__ import annotations

import json

import math
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_model  # noqa: E402  单一实现：名称判定只有 data_model 那一份（W2R2 第 4 条）

# v4.2.1 §14.4.1: Google place ids are base64 of a fixed-width protobuf id, so the
# alphabet excludes "_". The previous class accepted ChIJ_shangrila_mactan style
# hand-made slugs, which is how 4119 of 5228 cache rows passed as "verified".
PLACE_ID_RE = re.compile(r"^ChIJ[0-9A-Za-z-]{20,27}$")
SYNTHETIC_PLACE_ID_RE = re.compile(r"^ChIJ_")
# W2R2 第 4 条：这里原有第二套 PLACEHOLDER_NAME_RE（词根后缀式）、NUMERIC_RESIDUE_RE
# （^\d{1,4}$）与 CJK_NAME_RE（只认汉字）。三份都不等价于 data_model 的对应判定：
# "Unnamed" 只被这里拒、"17, 20" 只被 data_model 拒、"日本語カフェ" 在这里算可用拉丁名、
# 在 data_model 算含 CJK——同一个名字两处相反结论。全部删掉，名称判定只留
# data_model 一份（占位清单是配置驱动的，见 references/data-model.json::name_placeholder_policy）。

LEVELS = {"verified_platform_url", "verified_place_id", "verified_coordinate",
          "unnamed_coordinate", "search_candidate"}
VERIFIED_LEVELS = LEVELS - {"search_candidate"}
ENTITY_TYPES = {"named_entity", "coordinate_landmark"}
GOOGLE_HOSTS = {"google.com", "www.google.com", "maps.google.com", "maps.app.goo.gl"}
APPLE_HOSTS = {"maps.apple.com"}
ROOT = Path(__file__).resolve().parents[1]
_POLICY_FILE = ROOT / "references/run-quality-policy.json"
POLICY = json.loads(_POLICY_FILE.read_text(encoding="utf-8")) if _POLICY_FILE.is_file() else {}
# v4.2.1 §11.6.4: the tier list used to exist only inside this validator, so the
# renderer contract could (and did) disagree with the shipped data silently. The
# contract is now the authority and drift is a hard error.
_CONTRACT_FILE = ROOT / "references/renderer-contract.json"
CONTRACT_MAP_LEVELS = set()
if _CONTRACT_FILE.is_file():
    try:
        _contract = json.loads(_CONTRACT_FILE.read_text(encoding="utf-8"))
        CONTRACT_MAP_LEVELS = set(_contract.get("presentation", {}).get("map_target_levels") or [])
    except json.JSONDecodeError:
        CONTRACT_MAP_LEVELS = set()
if CONTRACT_MAP_LEVELS and CONTRACT_MAP_LEVELS != LEVELS:
    raise ValueError(
        f"renderer-contract 与 map_contract 的地图档位不一致: "
        f"contract={sorted(CONTRACT_MAP_LEVELS)} validator={sorted(LEVELS)}"
    )


def haversine_distance_km(coord1: tuple[float, float], coord2: tuple[float, float]) -> float:
    lat1, lng1 = math.radians(coord1[0]), math.radians(coord1[1])
    lat2, lng2 = math.radians(coord2[0]), math.radians(coord2[1])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    c = 2 * math.asin(math.sqrt(min(1.0, max(0.0, a))))
    return 6371.0 * c


def parse_coords(value: Any) -> tuple[float, float] | None:
    try:
        lat_text, lng_text = [part.strip() for part in str(value or "").split(",")]
        lat, lng = float(lat_text), float(lng_text)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def _is_coordinate_query_url(value: str) -> bool:
    val_str = str(value or "").strip()
    if not val_str:
        return False
    parsed = urlsplit(val_str)
    query = parse_qs(parsed.query)
    primary_values: list[str] = []
    for key in ("q", "query", "location", "destination"):
        for item in query.get(key, []):
            primary_values.append(str(item).strip())
            if parse_coords(item):
                return True
    if any(primary_values):
        return False
    for key in ("ll", "position", "center"):
        if any(parse_coords(item) for item in query.get(key, [])):
            return True
    return False


def _is_generic_search_url(value: str) -> bool:
    val_str = str(value or "").strip()
    if not val_str:
        return False
    parsed = urlsplit(val_str)
    path = parsed.path.lower().rstrip("/")
    query = parse_qs(parsed.query)
    host = (parsed.hostname or "").lower()
    if any(h in host for h in ("google", "apple")):
        if "/search" in path or path == "" or path == "/maps":
            has_entity_id = any(k in query for k in ("query_place_id", "place_id", "cid", "ftid"))
            if not has_entity_id and "/place/" not in path:
                return True
    return False


def _has_coordinate_hint_url(value: str) -> bool:
    parsed = urlsplit(str(value or ""))
    query = parse_qs(parsed.query)
    return any(
        parse_coords(item)
        for key in ("ll", "position", "center")
        for item in query.get(key, [])
    )


def target_key(destination: Any, name: Any) -> str:
    return f"{str(destination or '').strip()}|{str(name or '').strip()}"


def usable_entity_name(value: Any) -> str:
    """Return a Latin entity name, or empty. Never repair a name by deleting characters.

    v4.2.0 manufactured 151 "California Venue" placeholders exactly by stripping CJK
    from pure-Chinese POI names, so character-level repair is banned here: an unusable
    name must degrade to the coordinate tier, not be rewritten.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    # CJK 判定也统一走 data_model（它覆盖汉字/假名/谚文），本模块原来只认汉字，
    # 于是 "日本語カフェ" 这类名字一处算可用拉丁名、另一处算含汉字——反向结论。
    if data_model.CJK_RE.search(text):
        return ""
    if data_model.is_manufactured_name(text):
        return ""
    return text


def is_manufactured_name(value: Any) -> bool:
    """直接转发 data_model：占位模板名与数字残片在两处必须是同一个答案。"""
    return data_model.is_manufactured_name(value)


def evidence_index(evidence: Any) -> dict[str, dict[str, Any]]:
    """Index map-verification records by coordinate, which is the only key that joins.

    map_verification.json is keyed "destination|EnglishName" while map_targets is keyed
    "destination|ChineseName", so a name join silently fails; the coordinates match
    exactly in all 205 records of the audited run.
    """
    records = evidence.get("targets") if isinstance(evidence, dict) and isinstance(evidence.get("targets"), dict) else evidence
    index: dict[str, dict[str, Any]] = {}
    if not isinstance(records, dict):
        return index
    for key, record in records.items():
        if not isinstance(record, dict):
            continue
        coords = parse_coords(record.get("coords"))
        if not coords:
            continue
        entry = dict(record)
        entry.setdefault("evidence_key", key)
        index[f"{coords[0]},{coords[1]}"] = entry
    return index


def resolve_overseas_targets(targets: dict[str, Any], evidence: Any,
                            destination_english: dict[str, str] | None = None) -> dict[str, Any]:
    """Recover the verified English name for every overseas map target.

    Returns a report so the caller can fail loudly on what could not be recovered;
    nothing here invents a name.
    """
    index = evidence_index(evidence)
    claimed: dict[str, str] = {}
    report = {"total": 0, "recovered": 0, "already_named": 0, "already_unnamed": 0, "degraded_unnamed": 0,
              "no_coordinate": 0, "coordinate_collisions": [], "unrecovered_keys": []}
    if not isinstance(targets, dict):
        return report
    for key, target in targets.items():
        if not isinstance(target, dict):
            continue
        report["total"] += 1
        if str(target.get("target_level") or "") == "unnamed_coordinate":
            # A degraded tier recorded in the input is a decision, not a gap: re-deriving
            # it here would re-open coordinates that the resolver already found ambiguous.
            if not str(target.get("display_name_cn") or "").strip():
                target["display_name_cn"] = str(key).split("|")[-1]
            report["already_unnamed"] += 1
            continue
        if destination_english:
            raw_dest = str(target.get("destination") or "").strip()
            mapped = usable_entity_name(destination_english.get(raw_dest))
            if mapped:
                target["destination"] = mapped
        name = str(target.get("canonical_name") or "").strip()
        usable = usable_entity_name(name)
        if usable and not is_manufactured_name(name):
            target["canonical_name"] = usable
            report["already_named"] += 1
            continue
        coords = parse_coords(target.get("coords"))
        point = f"{coords[0]},{coords[1]}" if coords else ""
        record = index.get(point) if point else None
        if record is not None and point in claimed:
            # Two POIs pinned to one coordinate cannot both claim the same verified
            # name; the second one is a data defect, not a naming problem.
            report["coordinate_collisions"].append(f"{key} (与 {claimed[point]} 同坐标)")
            record = None
        resolved = usable_entity_name((record or {}).get("resolved_name") or (record or {}).get("landing_name"))
        if resolved:
            target["canonical_name"] = resolved
            target["target_level"] = str(record.get("target_level") or "verified_coordinate")
            target["entity_type"] = "named_entity"
            source_url = str((record or {}).get("landing_url") or "").strip()
            if source_url.startswith("https://"):
                target["source_url"] = source_url
            target["name_provenance"] = "evidence/map_verification.json#resolved_name"
            claimed[point] = key
            report["recovered"] += 1
            continue
        if coords:
            target["canonical_name"] = ""
            target["target_level"] = "unnamed_coordinate"
            target["entity_type"] = "coordinate_landmark"
            target["unnamed_reason"] = "no_verified_english_name"
            report["degraded_unnamed"] += 1
            report["unrecovered_keys"].append(key)
        else:
            target["target_level"] = "search_candidate"
            target["entity_type"] = "coordinate_landmark"
            report["no_coordinate"] += 1
            report["unrecovered_keys"].append(key)
    return report


def _https_platform_url(value: str, hosts: set[str]) -> bool:
    parsed = urlsplit(str(value or ""))
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in hosts and (parsed.path not in {"", "/"} or bool(parsed.query))


def _quarantined_reason(target: dict[str, Any], reason_code: str) -> bool:
    """W2 迁移把某些旧缺陷逐条隔离在案（quarantine 列表）。这里只问「有没有登记过」，不重复判定。"""
    for row in (target.get("quarantine") or []):
        if isinstance(row, dict) and str(row.get("reason_code") or "") == reason_code:
            return True
    return False


def _v422_selection_errors(key: str, target: dict[str, Any]) -> list[str]:
    """v4.2.2 选择状态存在时，可出货性由登记的 link_mode 决定，而不是 legacy target_level。

    这条是业主 2026-10-30 裁决（『按 V1R 收窄旧规则』）与窄指令第 3 条的落地：诚实四维里
    identity_status=UNVERIFIED 的具名搜索按钮（「搜索此地点（落点未核验）」）本来就是要出货的
    状态，而旧门禁只认 verified_* 档位——于是 403 条里没有一条能过正式生成，地图改向被 v4.2.1
    门禁屏蔽（窄指令第 6 条禁止的就是这种屏蔽）。

    收窄不等于放松，本函数同时把断言加严：
      · 行里存的结论必须与当场重算一致（漂移即错误，旧 URL 不能借一次改向悄悄出货）；
      · 模式必须在登记的可出货集合里，否则必须是无按钮态且带隔离记录；
      · 命中已知错链标记一律不得有按钮；
      · 出货 URL 必须是 map_link_url，不是 legacy google_url（后者是 compat-only）。
    """
    import map_link_selector  # 延迟导入：selector 模块级导入本模块，顶层互导会成环
    try:
        sel = map_link_selector.load_selection()
    except Exception as exc:
        return ["地图目标 %s 的选择配置不可用，无法按 v4.2.2 合同判定: %s" % (key, exc)]
    stored_mode = str(target.get("link_mode") or "")
    if stored_mode not in {"PUBLISHER_ENTITY_LINK", "NAMED_SEARCH", "NONE", "AMBIGUOUS"}:
        return []                      # 没有 v4.2.2 选择状态：仍走 legacy 判定
    fresh = map_link_selector.select(key, target, "google", sel=sel).as_record()
    fresh_mode = str(fresh.get("link_mode") or "")
    deliverable = set((sel.get("deliverable_link_modes") or {}).get("modes") or [])
    if not deliverable:
        return ["地图目标 %s 的可出货模式集合未登记（deliverable_link_modes 缺失）" % key]
    errors: list[str] = []
    if fresh_mode != stored_mode:
        errors.append("地图目标 %s 的 link_mode 与当场重算不一致：行里 %s，现在算出 %s（选择状态漂移）"
                      % (key, stored_mode, fresh_mode))
    elif stored_mode in deliverable:
        # 只看行里存的 URL：当场能重算出来不代表渲染层会用到它。用重算值替空字段兜底，
        # 等于把「读者点下去没有地址」这类缺陷藏进门禁自己的好意里。
        shipped = str(target.get("map_link_url") or "")
        if not shipped.startswith("https://"):
            errors.append("地图目标 %s 标为可出货模式 %s 却没有 https 出货 URL" % (key, stored_mode))
        elif shipped != str(fresh.get("map_link_url") or ""):
            errors.append("地图目标 %s 的 map_link_url 与当场重建的 URL 不同，禁止沿用旧 URL" % key)
        markers = (sel.get("known_bad_link_markers") or {}).get("target_flags") or []
        flags = {str(item) for item in (target.get("target_flags") or [])}
        hit = sorted(flags & set(markers))
        if hit:
            errors.append("地图目标 %s 命中已知错链标记 %s，必须无按钮而不是给出搜索入口" % (key, hit))
    else:
        quarantine = target.get("quarantine")
        if not isinstance(quarantine, list) or not quarantine:
            errors.append("地图目标 %s 的模式 %s 不在登记可出货集合里，却没有隔离记录" % (key, stored_mode))
    return errors


def _target_errors(key: str, target: dict[str, Any], *, require_exact: bool, base_dir: str | Path | None = None, is_international: bool = False) -> list[str]:
    errors: list[str] = []
    entity_type = str(target.get("entity_type") or "")
    if entity_type not in ENTITY_TYPES:
        errors.append(f"地图目标 {key} 缺少或使用了无效 entity_type: {entity_type or '空'}")
    level = str(target.get("target_level") or "")
    if level not in LEVELS:
        return [f"地图目标 {key} 的 target_level 无效: {level or '空'}"]
    if CONTRACT_MAP_LEVELS and level not in CONTRACT_MAP_LEVELS:
        return [f"地图目标 {key} 的 target_level {level!r} 不在 renderer-contract 声明的档位里"]
    v422_state = str(target.get("link_mode") or "") in {
        "PUBLISHER_ENTITY_LINK", "NAMED_SEARCH", "NONE", "AMBIGUOUS"}
    if require_exact and level not in VERIFIED_LEVELS and not v422_state:
        if level == "unnamed_coordinate" and entity_type == "coordinate_landmark":
            # v4.2.1 §11.5: an explicitly labelled coordinate-only target is deliverable,
            # but it is never counted as verified and never carries a manufactured name.
            pass
        else:
            errors.append(f"地图目标 {key} 仍是搜索候选，不能作为正式跳转 (level={level or '空'})")
    elif v422_state:
        errors.extend(_v422_selection_errors(key, target))
        if str(target.get("verification_status") or "") == "verified" and level in VERIFIED_LEVELS \
                and str(target.get("identity_status") or "") in {"UNVERIFIED", "UNRESOLVED"}:
            # 诚实维度说没核验过，legacy 字段却自称 verified：这不是「旧字段没人读就行」，
            # 而是一条会被任何按 legacy 字段行事的下游读成已核验的假声明。
            errors.append("地图目标 %s 的 legacy 状态自相矛盾：identity_status=%s 却写 "
                          "verification_status=verified / target_level=%s（改向不得留下假声明）"
                          % (key, target.get("identity_status"), level))
    if level in VERIFIED_LEVELS and target.get("verification_status") != "verified":
        errors.append(f"地图目标 {key} 未完成实体级核验")
    name = str(target.get("canonical_name") or "").strip()
    if is_manufactured_name(name) and not _quarantined_reason(target, "LEGACY_TEMPLATE_NAME"):
        errors.append(f"地图目标 {key} 的 canonical_name 是伪造/残留串 {name!r}，必须接回核验名或降级为 unnamed_coordinate")
    elif is_manufactured_name(name):
        # W2 已把这批旧模板名逐条隔离（LEGACY_TEMPLATE_NAME，handling=不做字符级修补）。隔离在案的
        # 假名不等于可以出货：它必须留在审计面、不得进读者载荷，由
        # map-link-selection.json::reader_payload_projection 与 visual_qa 的泄漏扫描负责；
        # 出货用的名字由 map_link_selector.authoritative_name 取 dataset 里的有来源字段。
        pass
    if level == "unnamed_coordinate":
        if name:
            errors.append(f"地图目标 {key} 标为 unnamed_coordinate 却仍带名字 {name!r}，档位与数据不符")
        if entity_type != "coordinate_landmark":
            errors.append(f"地图目标 {key} 的 unnamed_coordinate 必须标 entity_type=coordinate_landmark")
        if not parse_coords(target.get("coords")):
            errors.append(f"地图目标 {key} 降级为 unnamed_coordinate 但没有可用坐标")
        if not str(target.get("display_name_cn") or "").strip():
            errors.append(f"地图目标 {key} unnamed_coordinate 缺少 display_name_cn，读者界面会空白")
        if not str(target.get("unnamed_reason") or "").strip():
            errors.append(f"地图目标 {key} unnamed_coordinate 未说明降级原因")
    if level != "unnamed_coordinate" and (not name or not str(target.get("destination") or "").strip()):
        errors.append(f"地图目标 {key} 缺少 canonical_name/destination")
    google_url = str(target.get("google_url") or "")
    # v4.2.1 §6.3.3「海外地图 URL 严禁汉字」已被 v4.2.2 合同撤回：
    # references/map-link-selection.json::query_rules.local_name_query_decision 登记原话是
    # 「海外地图 URL 含本地文字自 v4.2.2 起不再是地图错误」，而清册 §4 禁止动作第 2 条
    # （「不删除中文/本地文字后猜英文名；没有可信英文名时保留有来源的本地正式名称」）正是那条旧规则
    # 唯一允许的替代做法。业主 2026-10-30 裁决按 V1R 收窄本规则，删除点保留在此说明，
    # 避免下一个读者把它当成漏实现的守卫。名字来源、删字残片与英文 UI 泄漏各有自己的门禁：
    # 见 map_link_selector 的 R4/R5/残片规则与 visual_qa 的 EN 文本导出。
    map_rules = POLICY.get("map_rules", {})
    if (
        entity_type == "named_entity"
        and map_rules.get("require_named_entity_page_for_pois", True)
        and map_rules.get("disallow_coordinate_query_as_platform_url", True)
        and _is_coordinate_query_url(google_url)
    ):
        errors.append(f"具名地图目标 {key} 的 google_url 为纯坐标查询，必须使用实体页、Place ID 或具名查询")
    if level in {"verified_coordinate", "verified_place_id"} and not parse_coords(target.get("coords")):
        errors.append(f"地图目标 {key} 缺少有效核验坐标")
    if level in {"verified_coordinate", "verified_place_id"}:
        # V4.1.4: a verified coordinate/place-id target must not store a bare search URL
        # without its verified coordinate (&ll). Such a link lands on a fuzzy search result
        # page ("查无此店") and contradicts the coordinate-level verification.
        apple_url = str(target.get("apple_url") or "")
        if google_url and _is_generic_search_url(google_url) and not (_is_coordinate_query_url(google_url) or _has_coordinate_hint_url(google_url)):
            errors.append(f"地图目标 {key} 标为 {level}，但其 google_url 为无坐标的普通搜索链接 (maps/search 无 &ll)，落地会查无此店，应提供实体 Place 页、带 &ll 坐标的链接或降级为 search_candidate")
    if level == "verified_place_id":
        place_id = str(target.get("google_place_id") or "")
        if SYNTHETIC_PLACE_ID_RE.match(place_id):
            errors.append(f"地图目标 {key} 的 Google Place ID 是 ChIJ_ 人工 slug，不是供应商返回值: {place_id[:32]}")
        elif not PLACE_ID_RE.fullmatch(place_id):
            errors.append(f"地图目标 {key} 的 Google Place ID 形状不合法（ChIJ + 20-27 位 base64 字母表）: {place_id[:32]}")
        if not str(target.get("id_provenance") or "").strip():
            errors.append(f"地图目标 {key} 缺少 Place ID 合规来源说明")
    if level == "verified_platform_url":
        apple_url = str(target.get("apple_url") or "")
        if not (_https_platform_url(google_url, GOOGLE_HOSTS) or _https_platform_url(apple_url, APPLE_HOSTS)):
            errors.append(f"地图目标 {key} 缺少允许平台的 HTTPS 精确链接")
        if _is_coordinate_query_url(google_url) or _is_coordinate_query_url(apple_url):
            errors.append(f"地图目标 {key} 的平台链接属于纯经纬度坐标查询，未形成具名地点实体页，严禁标为 verified_platform_url")
        if _is_generic_search_url(google_url) or _is_generic_search_url(apple_url):
            errors.append(f"地图目标 {key} 的平台链接为普通搜索候选链接 (maps/search)，未落地到具名地点实体页/CID/PlaceID，只能算 search_candidate，严禁标为 verified_platform_url")
    if level == "unnamed_coordinate":
        if not _is_coordinate_query_url(google_url) and not _has_coordinate_hint_url(google_url):
            errors.append(f"坐标档 {key} 的 google_url 必须落在坐标上 (query=lat,lng 或带 &ll)，当前为具名/泛搜链接")
        if re.search(r"[\u4e00-\u9fa5]", str(target.get("apple_url") or "")):
            errors.append(f"坐标档 {key} 的 apple_url 含汉字")
    if level in VERIFIED_LEVELS:
        if not str(target.get("source_url") or "").startswith("https://"):
            errors.append(f"地图目标 {key} 缺少核验来源 URL")
        elif str(target.get("source_url") or "").strip() == google_url.strip():
            errors.append(f"地图目标 {key} 的 source_url 与 google_url 完全相同，属自证循环，不构成外部证据")
        qa_evidence = str(target.get("qa_evidence") or "").strip()
        if not str(target.get("checked_at") or "").strip() or not qa_evidence:
            errors.append(f"地图目标 {key} 缺少 checked_at/qa_evidence")
        else:
            resolved_path = None
            if base_dir:
                candidate = Path(base_dir) / qa_evidence
                if candidate.is_file():
                    resolved_path = candidate
            if resolved_path is None and Path(qa_evidence).is_file():
                resolved_path = Path(qa_evidence)
            if resolved_path is None and base_dir is not None:
                errors.append(f"地图目标 {key} 的 QA 证据文件不存在: {qa_evidence}")
            elif resolved_path is not None and resolved_path.is_file():
                try:
                    qa_data = json.loads(resolved_path.read_text(encoding="utf-8"))
                    targets_dict = qa_data.get("targets") if isinstance(qa_data.get("targets"), dict) else qa_data
                    if isinstance(targets_dict, dict):
                        # Key match: exact key or canonical_name
                        c_name = str(target.get("canonical_name") or "")
                        rec = targets_dict.get(key) or targets_dict.get(c_name)
                        if not rec:
                            errors.append(f"地图 QA 文件 {qa_evidence} 缺少点位 {key} 的实际物理核验记录")
                        elif isinstance(rec, dict):
                            # V4.0.8: Physical landing verification
                            res_name = str(rec.get("resolved_name") or rec.get("landing_name") or "").strip()
                            res_addr = str(rec.get("resolved_address") or rec.get("landing_address") or "").strip()
                            if not res_name or not res_addr:
                                errors.append(f"地图 QA 点位 {key} 缺少第三方实际落地名称(resolved_name)或物理地址(resolved_address)")
                            
                            # V4.0.10: Disallow coordinate query as landing_url and coordinate string as resolved_name
                            landing_url = str(rec.get("landing_url") or rec.get("platform_url") or "").strip()
                            if _is_coordinate_query_url(landing_url):
                                errors.append(f"地图 QA 点位 {key} 的落地链接 landing_url 为纯坐标搜索，未核验到具名实体页")
                            if parse_coords(res_name) or re.search(r"^\d+°\d+['\"]", res_name):
                                errors.append(f"地图 QA 点位 {key} 的落地名称 resolved_name 为坐标数字/度分秒，未落地到具名实体: {res_name}")

                            # V4.0.11: Disallow template fake addresses (e.g. Premises, Coast Rd, Cebu 6000)
                            if re.search(r"\bPremises\b.*?\bCoast\s*Rd\b", res_addr, re.IGNORECASE) or re.search(r"\bPremises\b.*?\b6000\b", res_addr, re.IGNORECASE):
                                errors.append(f"地图 QA 点位 {key} 的物理地址命中批量模板伪造特征 ({res_addr})，禁止通过")

                            # V4.0.11: For verified_platform_url, require landing_url not to be a generic search URL
                            if level == "verified_platform_url":
                                res_url = str(rec.get("resolved_url") or rec.get("landing_url") or rec.get("platform_url") or "").strip()
                                if not res_url or _is_generic_search_url(res_url):
                                    errors.append(f"地图 QA 点位 {key} 落地链接为普通搜索链接，缺少具体实体落地页 (resolved_url)")
                                pid = str(rec.get("platform_id") or rec.get("place_id") or rec.get("google_place_id") or rec.get("cid") or "").strip()
                                if not pid and not ("/place/" in res_url or "cid=" in res_url or "query_place_id=" in res_url):
                                    errors.append(f"地图 QA 点位 {key} 缺少真实平台标识 (platform_id/place_id/cid)")

                            # V4.0.9: Disallow self-cloning fake verification (copying POI name as resolved_name without external metadata)
                            platform_meta = (
                                rec.get("place_id") or rec.get("google_place_id") or
                                rec.get("amap_id") or rec.get("baidu_uid") or
                                rec.get("landing_url") or rec.get("platform_url") or
                                rec.get("formatted_address")
                            )
                            # If resolved_name is identical to input canonical_name and address is generic or identical, require external platform metadata
                            if res_name == c_name and not platform_meta:
                                errors.append(f"地图 QA 点位 {key} 疑似自体克隆假核验: resolved_name 与输入名称完全一致且缺少平台实际落地凭据 (place_id/uid/landing_url)")

                            qa_coords = parse_coords(rec.get("verified_coords") or rec.get("coords"))
                            target_c = parse_coords(target.get("coords"))
                            if qa_coords and target_c:
                                drift = max(abs(qa_coords[0] - target_c[0]), abs(qa_coords[1] - target_c[1]))
                                if drift > 0.001:
                                    errors.append(f"地图 QA 点位 {key} 落地坐标与目标坐标漂移过大: {drift:.5f} > 0.001度")
                except Exception as exc:
                    errors.append(f"地图 QA 证据文件 {qa_evidence} 无法解析: {exc}")
    return errors



def audit_map_targets(data: dict[str, Any], *, base_dir: str | Path | None = None, require_exact: bool = True) -> tuple[list[str], dict[str, Any]]:
    targets = data.get("map_targets") or {}
    if not isinstance(targets, dict):
        return ["map_targets 必须是以 destination|name 为键的对象"], {"required": 0, "verified": 0}
    required: set[str] = set()
    canonical_coords: dict[str, Any] = {}
    for module, coord_index in (("hotels", 7), ("restaurants", 7), ("cafes", 7), ("attractions", 6), ("dive_sites", 6)):
        for row in data.get(module) or []:
            if isinstance(row, list) and len(row) > 1:
                key = target_key(row[0], row[1])
                required.add(key)
                canonical_coords[key] = row[coord_index] if len(row) > coord_index else ""
    transport_node_keys: set[str] = set()
    for row in data.get("transport_nodes") or []:
        if isinstance(row, dict):
            key = target_key(row.get("place"), row.get("name"))
            required.add(key)
            transport_node_keys.add(key)
            canonical_coords[key] = row.get("coords")
        elif isinstance(row, list) and len(row) > 1:
            key = target_key(row[0], row[1])
            required.add(key)
            transport_node_keys.add(key)
            canonical_coords[key] = row[4] if len(row) > 4 else ""

    dest_coords: dict[str, list[tuple[float, float]]] = {}
    for key, c_str in canonical_coords.items():
        c = parse_coords(c_str)
        if c:
            dest = key.split("|")[0]
            dest_coords.setdefault(dest, []).append(c)

    dest_centers: dict[str, tuple[float, float]] = {}
    for dest, c_list in dest_coords.items():
        if len(c_list) >= 3:
            lats = sorted(c[0] for c in c_list)
            lngs = sorted(c[1] for c in c_list)
            dest_centers[dest] = (lats[len(lats) // 2], lngs[len(lngs) // 2])

    max_dist_limit = float(POLICY.get("map_rules", {}).get("max_distance_to_destination_center_km", 75))

    errors: list[str] = []
    for key in sorted(required):
        target = targets.get(key)
        if not isinstance(target, dict):
            errors.append(f"缺少正式地图目标: {key}")
            continue
        is_intl = (
            data.get("map_region") == "international"
            or data.get("domestic_destination") is False
            or (bool(data.get("country_en")) and str(data.get("country_en")).strip().lower() not in {"china", "cn", "中国"})
        )
        errors.extend(_target_errors(key, target, require_exact=require_exact, base_dir=base_dir, is_international=is_intl))
        entity_type = str(target.get("entity_type") or "")
        level = str(target.get("target_level") or "")
        # v4.2.1 §11.5: a POI the collector could not attach a verified English name to is
        # *allowed* to ship as an explicitly labelled coordinate target (user decision
        # "坐标直连 + 显式标注"). That is the only legal way out of the named_entity rule;
        # _target_errors already demands display_name_cn + unnamed_reason + coordinates for it.
        degraded_by_decision = level == "unnamed_coordinate" and entity_type == "coordinate_landmark"
        if entity_type != "named_entity" and not degraded_by_decision:
            errors.append(f"POI/交通节点地图目标 {key} 必须标记为 named_entity")
        data_coords, target_coords = parse_coords(canonical_coords.get(key)), parse_coords(target.get("coords"))
        if data_coords and target_coords and (abs(data_coords[0] - target_coords[0]) > 0.00005 or abs(data_coords[1] - target_coords[1]) > 0.00005):
            errors.append(f"地图目标 {key} 与 POI 坐标不一致")

        # G1: Distance-to-center fence check
        if target_coords:
            dest = key.split("|")[0]
            c_name = str(target.get("canonical_name") or "")
            if dest in dest_centers:
                dist = haversine_distance_km(target_coords, dest_centers[dest])
                is_gateway = any(kw in c_name.lower() for kw in ("机场", "港", "码头", "站", "airport", "port", "harbor", "pier", "station", "terminal", "ferry")) or (key in transport_node_keys)
                allowed_dist = 160.0 if is_gateway else max_dist_limit
                if dist > allowed_dist:
                    errors.append(f"地图目标 {key} 坐标距目的地中心过远 ({dist:.1f}km > {allowed_dist:.0f}km)，疑似跨区域漂移或同名误采: {target.get('coords')}")
    return errors, {"required": len(required), "verified": sum(isinstance(targets.get(key), dict) and targets[key].get("target_level") in VERIFIED_LEVELS and targets[key].get("verification_status") == "verified" for key in required)}


def map_urls(target: dict[str, Any], *, international: bool = True) -> dict[str, str]:
    """Build deterministic URLs; search candidates remain explicitly labelled by callers."""
    name = str(target.get("canonical_name") or "").strip()
    destination = str(target.get("destination") or "").strip()
    country = str(target.get("country") or "").strip()
    identity = ", ".join(dict.fromkeys(item for item in (name, destination, country) if item))
    coords = parse_coords(target.get("coords"))
    level = str(target.get("target_level") or "search_candidate")
    entity_type = str(target.get("entity_type") or "")
    if international:
        if level == "unnamed_coordinate":
            if not coords:
                raise ValueError(f"坐标档目标缺少可用坐标，禁止回落到名称检索: {identity or '(无名)'}")
            point = f"{coords[0]},{coords[1]}"
            return {
                "google": f"https://www.google.com/maps/search/?api=1&query={point}",
                "apple": f"https://maps.apple.com/?q={point}&ll={point}&zoom=17",
            }
        google = str(target.get("google_url") or "") if level == "verified_platform_url" else ""
        if entity_type == "named_entity" and _is_coordinate_query_url(google):
            google = ""
        apple = str(target.get("apple_url") or "") if level == "verified_platform_url" else ""
        if not google:
            google = "https://www.google.com/maps/search/?api=1&query=" + quote(identity)
            if level == "verified_place_id":
                google += "&query_place_id=" + quote(str(target.get("google_place_id") or ""))
            elif coords:
                google += f"&ll={coords[0]},{coords[1]}"
        if not apple:
            apple = "https://maps.apple.com/?q=" + quote(identity)
            if coords:
                apple += f"&ll={coords[0]},{coords[1]}"
        return {"google": google, "apple": apple}
    query = quote(identity)
    if coords and level in VERIFIED_LEVELS:
        lat, lng = coords[0], coords[1]
        amap = f"https://uri.amap.com/marker?position={lng},{lat}&name={quote(name or identity)}&coordinate=wgs84&callnative=0"
        baidu = f"https://api.map.baidu.com/marker?location={lat},{lng}&title={quote(name or identity)}&content={query}&output=html&coord_type=wgs84"
        return {"amap": amap, "baidu": baidu}
    return {"amap": "https://uri.amap.com/search?keyword=" + query, "baidu": "https://map.baidu.com/search/" + query}
