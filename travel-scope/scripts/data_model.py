"""Configuration-driven normalized record contract for Travel-Scope outputs."""

from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

# W2R2 第 4 条：占位名判定不再看词根/后缀。旧写法
#   (?:^|[\s,_])(?:[A-Za-z .'\-]*\s)?(?:Venue|Location|Place|Point|Spot)\s*(?:,|$)
# 会把 "Alfred Coffee Melrose Place"（Melrose Place 是洛杉矶街名）和
# "Ragged Point Vista Point" 这类真实名称判成模板串。现在只拒绝两类值：通用占位词，
# 以及 references/data-model.json::name_placeholder_policy 里明确登记过的旧模板值
# （California Venue 就在其中，仍然继续拒绝）。清单是配置，判定方式是精确匹配——
# 既不许按店名建白名单，也不许在别处再写第二份判定。
NAME_SEGMENT_SPLIT_RE = re.compile(r"[,，、;；]")
NAME_SPACE_RE = re.compile(r"\s+")
PLACEHOLDER_POLICY_KEY = "name_placeholder_policy"
# W2R：数字残片 = 整串只有数字与分隔符（'39'、'17'、'518'、'17, 20'）。
# 旧写法 ^\s*\d{1,4}\s*(?:$|[,\s]) 只要"数字开头 + 后随空白或逗号"就判残片，误伤了
# '2 Story Kitchen'、'7-Eleven'、'21 Choices' 这类真实以数字开头的店名；按 W2R 要求改的是
# 正式规则本身，不是在下游加店名白名单。含字母（含汉字）的名称不再仅因数字前缀被拒。
NUMERIC_RESIDUE_RE = re.compile(r"^\s*\d+(?:[\s.,、\-–—]*\d+)*[\s.,、]*\s*$")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def load_policy() -> dict[str, Any]:
    return json.loads((Path(__file__).parent.parent / "references" / "data-model.json").read_text(encoding="utf-8"))


def normalize_name_segment(value: Any) -> str:
    return NAME_SPACE_RE.sub(" ", str(value or "")).strip().casefold()


def _read_policy_file() -> dict[str, Any]:
    """按字节读策略文件。

    用 read_bytes 而不是 read_text 有两个实测理由：一是负样本测试会全局 patch
    Path.read_text（返回 resolver 假数据），二是 Windows 下 read_text 会做换行翻译；
    判定表若在那些环境里重新读盘，就会报"配置缺失"——这是假失败，不是配置真的缺。
    """
    return json.loads((Path(__file__).parent.parent / "references" / "data-model.json")
                      .read_bytes().decode("utf-8"))


def _build_placeholder_registry(source: dict[str, Any]) -> tuple[frozenset, frozenset]:
    block = source.get(PLACEHOLDER_POLICY_KEY)
    if not isinstance(block, dict):
        raise ValueError("配置缺失：%s 里没有 %s，占位名判定无法执行（不得回退到词根正则）"
                         % ("references/data-model.json", PLACEHOLDER_POLICY_KEY))
    exact = frozenset(normalize_name_segment(v)
                      for v in block.get("exact_placeholder_values") or [])
    legacy = frozenset(normalize_name_segment(v)
                       for v in block.get("legacy_template_values") or [])
    if not exact or not legacy:
        raise ValueError("%s 的 exact_placeholder_values / legacy_template_values 不能为空；"
                         "空清单等于取消判定" % PLACEHOLDER_POLICY_KEY)
    return exact, legacy


# 判定表在模块导入时建立一次：清单来自正式 policy，产品完整性由 product-origin.json 封存守护。
_PLACEHOLDER_EXACT, _PLACEHOLDER_LEGACY = _build_placeholder_registry(_read_policy_file())


def placeholder_value_sets(policy: dict[str, Any] | None = None) -> tuple[frozenset, frozenset]:
    """(通用占位值, 已登记旧模板值)。显式传 policy 时用传进来的那份，否则用导入期缓存。"""
    if policy is None:
        return _PLACEHOLDER_EXACT, _PLACEHOLDER_LEGACY
    return _build_placeholder_registry(policy)


def is_placeholder_name(value: Any, policy: dict[str, Any] | None = None) -> bool:
    """逗号/顿号/分号分段后精确命中清单才算占位名。分段是为了拒绝逗号拼接的旧模板串。"""
    exact, legacy = placeholder_value_sets(policy)
    text = str(value or "").strip()
    if not text:
        return False
    segments = NAME_SEGMENT_SPLIT_RE.split(text)
    return any(normalize_name_segment(seg) in exact or normalize_name_segment(seg) in legacy
               for seg in segments)


def is_manufactured_name(value: Any, policy: dict[str, Any] | None = None) -> bool:
    """占位模板名或数字残片——两处判定（data_model / map_contract）必须共用这一个函数。"""
    text = str(value or "").strip()
    if not text:
        return False
    return bool(is_placeholder_name(text, policy) or NUMERIC_RESIDUE_RE.match(text))



def validate_records(records: list[dict[str, Any]]) -> list[str]:
    policy = load_policy()
    required = policy["required_fields"]
    allowed = set(policy["kinds"])
    errors: list[str] = []
    seen: set[str] = set()
    for index, record in enumerate(records, 1):
        missing = [field for field in required if not str(record.get(field, "")).strip()]
        if missing:
            errors.append(f"normalized record {index} missing: {missing}")
        if record.get("kind") not in allowed:
            errors.append(f"normalized record {index} has invalid kind: {record.get('kind')}")
        record_id = str(record.get("record_id", "")).strip()
        if record_id and record_id in seen:
            errors.append(f"normalized record id duplicated: {record_id}")
        seen.add(record_id)
        if record.get("kind") in set(policy["image_kinds"]):
            images = record.get("image_refs") or []
            if not isinstance(images, list):
                errors.append(f"normalized record {index} image_refs is not a list")
    return errors


# ------------------------------------------------------------------ §17 map target contract

_ENUMS = {
    "identity_status": "identity_status",
    "coordinate_status": "coordinate_status",
    "link_mode": "link_mode",
    "google_resolution_status": "google_resolution_status",
    "address_status": "address_status",
    "criticality": "criticality",
    "entity_type": "map_entity_types",
    # V4-A：required_location_role 不再是无条件必填字段，但取值合法性仍必须有人管——
    # 由这张全局枚举表负责（MAP_ENUM_INVALID）。类别矩阵只回答「这一类必须有角色吗」。
    "required_location_role": "required_location_role",
}


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, tuple)):
        return len(value) == 0
    return not str(value).strip()


def evidence_members(target: dict[str, Any], key: str = "") -> tuple[list[dict[str, Any]], list[str]]:
    """W1R-A ④：非对象成员必须逐项报错，不能被过滤器静默丢掉。

    The old comprehension kept only dicts, so `evidence: ["see website", null, 7]` looked like
    "no evidence rows to validate" and passed every evidence rule while the dataset still carries junk.
    """
    problems: list[str] = []
    evidence = target.get("evidence")
    if evidence is None:
        return [], []
    if isinstance(evidence, dict):
        return [evidence], []
    if isinstance(evidence, list):
        rows: list[dict[str, Any]] = []
        for index, item in enumerate(evidence, 1):
            if isinstance(item, dict):
                rows.append(item)
            else:
                problems.append(
                    f"EVIDENCE_MEMBER_NOT_OBJECT|{key} evidence[{index}] 是 "
                    f"{type(item).__name__}（{str(item)[:40]!r}），证据必须是对象；"
                    f"非对象成员不会被静默忽略（§17.3.1）")
        return rows, problems
    problems.append(f"EVIDENCE_CONTAINER_INVALID|{key} evidence 必须是对象列表"
                    f"（或合同允许的单对象），实为 {type(evidence).__name__}")
    return [], problems


def _evidence_rows(target: dict[str, Any]) -> list[dict[str, Any]]:
    rows, _ = evidence_members(target)
    return rows


# ------------------------------------------------------------------ W1R-B1 typed classifier
#
# W1R-B1 classifier (the version string is contract data, never code). One classifier, one
# output tuple: provider + kind + canonical_locator +
# reason_code (plus host / scheme / adapter / detail). Every hostname, path prefix, pattern,
# source adapter and precedence step lives in references/data-model.json -> url_reference_classifier;
# nothing is hard-coded in this file, because the finding that started W1R was two hand-written
# judgments (evidence vs link) drifting apart.
#
# W1R-B1 closed the six semantic holes the independent audit measured in the W1R-B version:
#  ① coordinates are anchored on a complete path segment or a complete query value, only the FIRST
#     `@` token counts, trailing garbage or a second `@` after an unparseable token is invalid, an
#     out-of-domain pair is invalid, and kind=coordinate is never returned without a non-empty
#     in-domain canonical_locator;
#  ② entity selectors are read over ALL values, path and query together, and unregistered family
#     combinations are refused, so `?cid=good&cid=bad` cannot pass in one order and fail in another;
#  ③ only node/way/relation are places on OSM -- user and changeset pages are objects, not places;
#  ④ a non-provider host is an entity page only through a registered source adapter; unregistered
#     hosts, unregistered paths and known non-evidence surfaces (privacy/login/robots/…) are refused
#     instead of defaulting to "any non-root path long enough is an entity";
#  ⑤ the evidence origin is classified by this same judgment and a dataset origin needs a registered
#     dataset id, so `source_type` alone can no longer endorse a reference;
#  ⑥ publisher-scoped namespaces are explicitly registered and matched against the exact normalized
#     origin host, never against the last two labels of a hostname.

_URL_FORM_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def classifier_config(policy: dict[str, Any]) -> dict[str, Any]:
    return policy.get("url_reference_classifier") or {}


def _blank_ref(value: Any) -> str:
    return str(value or "").strip()


def _query_map(query: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, values in urllib.parse.parse_qs(query, keep_blank_values=True).items():
        out[key.lower()] = values
    return out


def _coordinate_pair_state(value: Any, cfg: dict[str, Any]) -> tuple[str, str]:
    """('ok', 'coord:<lat6>,<lng6>') | ('none', '') | ('out_of_domain', '').

    The three states matter: "no pair here" and "a pair outside +-90 / +-180" are different bugs,
    and W1R-B1 ① forbids answering either of them with kind=coordinate.
    """
    match = re.match(cfg.get("coordinate_pair_re") or "(?!)", _blank_ref(value))
    if not match:
        return "none", ""
    lat, lng = float(match.group(1)), float(match.group(2))
    domain = cfg.get("coordinate_domain") or {}
    lat_range = domain.get("lat") or [-90.0, 90.0]
    lng_range = domain.get("lng") or [-180.0, 180.0]
    if not (float(lat_range[0]) <= lat <= float(lat_range[1])):
        return "out_of_domain", ""
    if not (float(lng_range[0]) <= lng <= float(lng_range[1])):
        return "out_of_domain", ""
    return "ok", "coord:%.6f,%.6f" % (lat, lng)


def _coord_pair(value: Any, cfg: dict[str, Any]) -> str:
    """Bare "lat,lng" normalized to six decimals, or "" -- the shape older call sites expect."""
    state, locator = _coordinate_pair_state(value, cfg)
    return locator[len("coord:"):] if state == "ok" else ""


def _starts_boundary(path: str, prefix: str) -> bool:
    """Boundary-aware prefix test: /search matches /search and /search/x, never /searchtags/x."""
    if not prefix:
        return False
    if prefix.endswith("/"):
        return path.startswith(prefix.lower())
    base = prefix.lower().rstrip("/")
    return path == base or path.startswith(base + "/")


def _provider_depth_tokens(spec: dict[str, Any]) -> dict[int, set]:
    depths: dict[int, set] = {}
    for group in ("home_paths", "entity_path_prefixes", "search_path_prefixes",
                  "coordinate_path_prefixes", "non_place_path_prefixes"):
        for prefix in spec.get(group) or []:
            for depth, token in enumerate([p for p in prefix.strip("/").split("/") if p]):
                depths.setdefault(depth, set()).add(token.lower())
    return depths


def _ref_result(provider: str = "", kind: str = "invalid", reason: str = "REF_PATH_NOT_IN_KNOWN_SHAPE",
                locator: str = "", host: str = "", scheme: str = "", detail: str = "",
                adapter: str = "", **extra: Any) -> dict[str, Any]:
    found = {"provider": provider, "kind": kind, "canonical_locator": locator,
             "reason_code": reason, "host": host, "scheme": scheme, "adapter": adapter,
             "detail": detail}
    found.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    return found


def _diagnose_extension(path: str, spec: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Tell an attacker-stretched registered token apart from a genuinely unknown provider path."""
    depths = _provider_depth_tokens(spec)
    for depth, segment in enumerate([p for p in path.split("/") if p]):
        registered = depths.get(depth) or set()
        if segment in registered:
            continue
        for item in sorted(registered, key=len, reverse=True):
            if segment.startswith(item) and not item.endswith("@"):
                return _ref_result(reason="REF_PATH_SMUGGLING",
                                   detail="seg%d=%s extends registered token %s"
                                          % (depth, segment, item))
        if depth == 0:
            return _ref_result(reason="REF_PATH_NOT_IN_KNOWN_SHAPE", detail=path or "/")
        return _ref_result(reason="REF_PATH_SMUGGLING",
                           detail="seg%d=%s is not a registered token at that depth"
                                  % (depth, segment))
    return _ref_result(reason="REF_PATH_NOT_IN_KNOWN_SHAPE", detail=path or "/")


def _coordinate_from_segments(path: str, cfg: dict[str, Any]) -> tuple[str, str]:
    """W1R-B1 ①: only the FIRST @-segment is a candidate and it must fill the whole segment.

    Searching further for a pair that *does* parse is what let `/maps/@evil/@10.3,123.9` through.
    """
    segment_re = cfg.get("coordinate_segment_re") or "(?!)"
    candidates = [p for p in path.split("/") if p and p.startswith("@")]
    if len(candidates) > 1:
        return "malformed", ""
    for segment in candidates:
        match = re.match(segment_re, segment)
        if not match:
            return "malformed", ""
        state, locator = _coordinate_pair_state("%s,%s" % (match.group(1), match.group(2)), cfg)
        if state == "ok":
            return "ok", locator
        return ("out_of_domain" if state == "out_of_domain" else "malformed"), ""
    return "none", ""


def _path_selector_family(spec: dict[str, Any], path: str) -> str:
    """Which selector family the path itself belongs to (W1R-B1 ②: path and query are one set)."""
    for group, family in (("entity_path_prefixes", "entity_query"),
                          ("search_path_prefixes", "search_query"),
                          ("coordinate_path_prefixes", "coordinate_query")):
        for prefix in spec.get(group) or []:
            if _starts_boundary(path, prefix):
                return family
    return ""


def _selector_family_hits(cfg: dict[str, Any], provider: str,
                          query: dict[str, list[str]]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for family, per_provider in (cfg.get("selector_families") or {}).items():
        keys = [key for key in (per_provider.get(provider) or []) if key in query]
        if keys:
            hits[family] = keys
    return hits


def _diagnose_coordinate(spec: dict[str, Any], path: str, fragment: str,
                         query: dict[str, list[str]], cfg: dict[str, Any]):
    """Coordinate surfaces outrank search surfaces: a pin page is not an entity page.

    Returns (locator, detail) for a readable coordinate surface, ("", reason_code) when a coordinate
    marker is present but cannot be read as an in-domain pair, and (None, "") when there is no
    coordinate marker at all. A locator is never returned empty together with kind=coordinate.
    """
    candidates: list[tuple[str, str]] = []
    for prefix in spec.get("coordinate_path_prefixes") or []:
        if prefix and path.startswith(prefix.lower()):
            state, locator = _coordinate_from_segments(path, cfg)
            if state == "ok":
                candidates.append((locator, "%s @-segment" % prefix))
                break
            return "", ("REF_COORDINATE_OUT_OF_DOMAIN" if state == "out_of_domain"
                         else "REF_COORDINATE_TOKEN_MALFORMED")
    marker = spec.get("coordinate_marker_pair_keys") or []
    if len(marker) == 2 and marker[0] in query and marker[1] in query:
        left, right = sorted(set(query[marker[0]])), sorted(set(query[marker[1]]))
        if len(left) != 1 or len(right) != 1:
            return "", "REF_COORDINATE_CONFLICT"
        state, locator = _coordinate_pair_state("%s,%s" % (left[0], right[0]), cfg)
        if state == "ok":
            candidates.append((locator, "%s+%s marker pair" % tuple(marker)))
        else:
            return "", ("REF_COORDINATE_OUT_OF_DOMAIN" if state == "out_of_domain"
                         else "REF_COORDINATE_TOKEN_MALFORMED")
    for key in spec.get("coordinate_query_keys") or []:
        if key in query and key not in marker:
            for value in sorted(set(query[key])):
                state, locator = _coordinate_pair_state(value, cfg)
                if state == "ok":
                    candidates.append((locator, "%s= pair" % key))
                else:
                    return "", ("REF_COORDINATE_OUT_OF_DOMAIN" if state == "out_of_domain"
                                 else "REF_COORDINATE_UNRESOLVED")
    for key in spec.get("coordinate_value_keys") or []:
        if key in query:
            for value in sorted(set(query[key])):
                state, locator = _coordinate_pair_state(value, cfg)
                if state == "ok":
                    candidates.append((locator, "%s= coordinate pair value" % key))
    fragment_re = spec.get("coordinate_fragment_re") or ""
    if fragment and fragment_re:
        match = re.fullmatch(fragment_re, fragment)
        if match:
            allowed_paths = {item.lower() for item
                             in spec.get("coordinate_fragment_path_allowlist") or []}
            if path not in allowed_paths:
                # a #map= fragment on an unrecognized path is smuggling: the path says we do not
                # know this page, so the fragment must not manufacture a coordinate verdict (①)
                return "", "REF_PATH_SMUGGLING"
            state, locator = _coordinate_pair_state(
                "%s,%s" % (match.group(1), match.group(2)), cfg)
            if state == "ok":
                candidates.append((locator, "#fragment map=/lat/lng on a registered viewer path"))
            else:
                return "", "REF_COORDINATE_OUT_OF_DOMAIN"
        elif fragment.startswith("map="):
            return "", "REF_COORDINATE_TOKEN_MALFORMED"
    locators = sorted({item[0] for item in candidates})
    if len(locators) > 1:
        return "", "REF_COORDINATE_CONFLICT"
    if candidates:
        return candidates[0]
    return None


def _classify_provider_url(host: str, scheme: str, parts: Any, provider: str,
                           spec: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """A registered provider host is judged only by its own registered shapes."""
    if parts.port not in (None, 443):
        return _ref_result(provider=provider, reason="REF_PORT_UNEXPECTED", host=host,
                           scheme=scheme, detail="port=%s" % parts.port)
    if host in {item.lower() for item in spec.get("shortlink_hostnames") or []}:
        return _ref_result(provider=provider, reason="REF_SHORT_LINK_UNRESOLVED", host=host,
                           scheme=scheme,
                           detail="short links resolve only from a frozen table, never live")
    path = (parts.path or "/").lower()
    fragment = parts.fragment or ""
    query = _query_map(parts.query)
    # W1R-B1 ②: every selector value -- in the query and in the path -- is read before any single
    # key decides, and the answer does not depend on the order the parameters were written in.
    families = _selector_family_hits(cfg, provider, query)
    path_family = _path_selector_family(spec, path)
    if path_family:
        families[path_family] = list(families.get(path_family) or []) + ["path:%s" % path]
    present = sorted(families)
    registered = {tuple(sorted(item)) for item in (spec.get("allowed_selector_combinations") or [])
                  if item and isinstance(item[0], str)}
    if len(present) > 1 and tuple(present) not in registered:
        return _ref_result(provider=provider, reason="REF_SELECTOR_COMBINATION", host=host,
                           scheme=scheme,
                           detail="selector families %s combined; only %s registered (%s)"
                                  % (present, sorted(registered) or "none", path or "/"))
    search_hits = [key for key in (families.get("search_query") or [])
                   if not str(key).startswith("path:")]
    for key in sorted(search_hits):
        values = sorted(set(query[key]))
        if len(values) > 1:
            return _ref_result(provider=provider, reason="REF_AMBIGUOUS_SEARCH_SELECTOR",
                               host=host, scheme=scheme,
                               detail="%s carries %d distinct search values; mixed name/coordinate "
                                      "semantics and order-dependent first-value selection are "
                                      "forbidden: %s" % (key, len(values), values))
    entity_hits = [key for key in (families.get("entity_query") or [])
                   if not str(key).startswith("path:")]
    distinct: dict[str, list[str]] = {}
    malformed: list[str] = []
    for key in entity_hits:
        rule = (spec.get("entity_query_keys") or {}).get(key) or {}
        values = query[key]
        for item in values:
            if not re.match(rule.get("id_re") or "(?!)", item):
                malformed.append("%s=%s" % (key, item[:24]))
        distinct[key] = sorted(set(values))
    if malformed:
        return _ref_result(provider=provider, reason="REF_MALFORMED_SELECTOR_VALUE", host=host,
                           scheme=scheme,
                           detail="entity selector values fail their own pattern: %s"
                                  % "; ".join(malformed))
    for key, values in sorted(distinct.items()):
        if len(values) > 1:
            return _ref_result(provider=provider, reason="REF_AMBIGUOUS_ENTITY_SELECTOR", host=host,
                               scheme=scheme,
                               detail="%s carries %d distinct values %s -- one URL may not name two "
                                      "entities" % (key, len(values), values))
    if len(distinct) > 1:
        canonical = []
        for key, values in sorted(distinct.items()):
            rule = (spec.get("entity_query_keys") or {}).get(key) or {}
            canonical.append((rule.get("locator") or "<value>").replace("<value>", values[0]))
        return _ref_result(provider=provider, reason="REF_AMBIGUOUS_ENTITY_SELECTOR", host=host,
                           scheme=scheme,
                           detail="multiple entity selector keys name distinct canonical namespaces; "
                                  "one URL may carry only one key: %s" % canonical)
    for key, values in sorted(distinct.items()):
        rule = (spec.get("entity_query_keys") or {}).get(key)
        allowed = {item.lower() for item in (rule or {}).get("allowed_paths") or []}
        if path not in allowed:
            return _ref_result(provider=provider, reason="REF_ID_INVALID", host=host, scheme=scheme,
                               detail="%s= present on unregistered path %s" % (key, path))
        return _ref_result(provider=provider, kind="entity", reason="OK",
                           locator=(rule or {})["locator"].replace("<value>", values[0]),
                           host=host, scheme=scheme, detail="%s= query form" % key)
    if path in {item.lower() for item in spec.get("home_paths") or []} and not query and not fragment:
        return _ref_result(provider=provider, kind="home", reason="REF_HOME_OR_ROOT_PATH",
                           locator="%s:%s" % (provider, path), host=host, scheme=scheme)
    for prefix in spec.get("entity_path_prefixes") or []:
        base = prefix.rstrip("/").lower()
        if base and path == base:
            return _ref_result(provider=provider, reason="REF_ENTITY_TOKEN_MISSING", host=host,
                               scheme=scheme, detail=prefix)
        if not _starts_boundary(path, prefix):
            continue
        tail = path[len(prefix):].strip("/")
        if not tail:
            return _ref_result(provider=provider, reason="REF_ENTITY_TOKEN_MISSING", host=host,
                               scheme=scheme, detail=prefix)
        if spec.get("entity_id_re"):
            obj = prefix.strip("/").split("/")[0]
            tail_parts = tail.split("/")
            ident = tail_parts[0]
            suffix = "/".join(tail_parts[1:])
            if suffix and suffix not in set(spec.get("entity_allowed_suffixes") or []):
                return _ref_result(provider=provider, reason="REF_ENTITY_PATH_TRAILING",
                                   host=host, scheme=scheme,
                                   detail="object path carries unregistered trailing segments: %s"
                                          % suffix[:60])
            if not re.fullmatch(spec["entity_id_re"], ident):
                return _ref_result(provider=provider, reason="REF_ID_INVALID", host=host,
                                   scheme=scheme, detail=tail)
            namespace = (spec.get("entity_namespaces") or {}).get(obj, provider)
            return _ref_result(provider=provider, kind="entity", reason="OK",
                               locator="%s:%s/%s" % (namespace, obj, ident), host=host,
                               scheme=scheme)
        slug = tail.split("/@")[0].strip("/")
        token = prefix.strip("/").split("/")[-1]
        if "@" in tail:
            # W1R-B1 ①: an @-token inside an entity path must be one complete in-domain coordinate.
            # Garbage after the place slug is a malformed URL, not a decorated place page.
            state, _locator = _coordinate_from_segments("/" + tail, cfg)
            if state != "ok":
                return _ref_result(provider=provider,
                                   reason="REF_COORDINATE_OUT_OF_DOMAIN" if state == "out_of_domain"
                                          else "REF_COORDINATE_TOKEN_MALFORMED",
                                   host=host, scheme=scheme,
                                   detail="entity path carries an @-token that is not a complete "
                                          "in-domain coordinate: %s" % tail[:60])
        return _ref_result(provider=provider, kind="entity", reason="OK",
                           locator="%s:%s/%s" % (provider, token, slug or tail), host=host,
                           scheme=scheme)
    for prefix in spec.get("non_place_path_prefixes") or []:
        if _starts_boundary(path, prefix):
            return _ref_result(provider=provider,
                               reason=spec.get("non_place_reason") or "REF_NOT_PLACE_ENTITY",
                               host=host, scheme=scheme,
                               detail="%s is an object on this provider but not a place (③)" % prefix)
    coordinate = _diagnose_coordinate(spec, path, fragment, query, cfg)
    if coordinate is not None:
        locator, detail = coordinate
        if not locator:
            reason = detail if str(detail).startswith("REF_") else "REF_COORDINATE_UNRESOLVED"
            return _ref_result(provider=provider, reason=reason, host=host, scheme=scheme,
                               detail="coordinate marker present without a readable in-domain "
                                      "pair; kind=coordinate requires a locator (①)")
        return _ref_result(provider=provider, kind="coordinate", reason="REF_COORDINATE_SHAPE",
                           locator=locator, host=host, scheme=scheme, detail=detail)
    for prefix in spec.get("search_path_prefixes") or []:
        if _starts_boundary(path, prefix):
            tail = path[len(prefix):].strip("/")
            for key in spec.get("search_query_keys") or []:
                if key in query:
                    return _ref_result(provider=provider, kind="search", reason="REF_SEARCH_SHAPE",
                                       locator="%s:search:%s=%s" % (provider, key,
                                                                    query[key][0][:40]),
                                       host=host, scheme=scheme)
            return _ref_result(provider=provider, kind="search", reason="REF_SEARCH_SHAPE",
                               locator="%s:search:%s" % (provider, tail or "path"), host=host,
                               scheme=scheme)
    for key in spec.get("search_query_keys") or []:
        if key in query:
            return _ref_result(provider=provider, kind="search", reason="REF_SEARCH_SHAPE",
                               locator="%s:search:%s=%s" % (provider, key, query[key][0][:40]),
                               host=host, scheme=scheme, detail=key)
    found = _diagnose_extension(path, spec, cfg)
    found.update({"provider": provider, "host": host, "scheme": scheme})
    return found


def _source_adapters(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return list(cfg.get("source_adapters") or [])


def _approval_is_identity_eligible(status: Any, cfg: dict[str, Any]) -> bool:
    return str(status or "") in set(cfg.get("identity_eligible_approval_statuses") or [])


def _classify_adapter_url(host: str, scheme: str, path: str, fragment: str,
                          query: dict[str, list[str]], cfg: dict[str, Any]) -> dict[str, Any]:
    """W1R-B1 ④: a non-provider host is an entity page only because a registered adapter says so.

    Order is part of the contract: root page -> search surface -> blocked non-evidence surface ->
    registered entity path -> unregistered path. The W1R-B version defaulted every non-root path of
    length >= 2 to `entity`, which handed whole domains to any string that looked like a URL.
    """
    adapters = [item for item in _source_adapters(cfg)
                if host in {name.lower() for name in item.get("hostnames") or []}]
    if not adapters:
        verdict = cfg.get("unregistered_verdict") or {}
        return _ref_result(reason=verdict.get("reason_code") or "REF_SOURCE_ADAPTER_UNREGISTERED",
                           host=host, scheme=scheme,
                           detail="host=%s 不在版本化批准来源清单（§17.3.9）" % host)
    adapter = adapters[0]
    approval = str(adapter.get("approval_status") or "")
    surface_allowed = set(cfg.get("surface_eligible_approval_statuses") or [])
    if approval not in surface_allowed:
        return _ref_result(reason="REF_SOURCE_APPROVAL_NOT_ELIGIBLE", adapter=adapter["id"],
                           host=host, scheme=scheme, approval_status=approval,
                           detail="adapter=%s approval_status=%r is not eligible for production "
                                  "classification" % (adapter["id"], approval))
    first_segment = [p for p in path.split("/") if p][:1]
    if path in ("/", "") and not query and not fragment:
        return _ref_result(kind="home", reason="REF_HOME_OR_ROOT_PATH", adapter=adapter["id"],
                           host=host, scheme=scheme, locator="%s:%s/" % (adapter["id"], host))
    search_keys = [key for key in (adapter.get("search_query_keys") or []) if key in query]
    if search_keys or first_segment == ["search"]:
        return _ref_result(kind="search", reason="REF_SEARCH_SHAPE", adapter=adapter["id"],
                           host=host, scheme=scheme, detail=",".join(search_keys) or "/search",
                           locator=("%s:search:%s=%s" % (adapter["id"], search_keys[0],
                                                           query[search_keys[0]][0][:40])
                                  if search_keys else "%s:search:path" % adapter["id"]))
    for pattern in adapter.get("blocklist_path_res") or []:
        if re.fullmatch(pattern, path):
            return _ref_result(reason="REF_SOURCE_BLOCKED_PATH", adapter=adapter["id"], host=host,
                               scheme=scheme,
                               detail="path=%s 命中 %s 声明的非凭据面（隐私/登录/robots/索引…）"
                                      % (path, pattern))
    for pattern in adapter.get("entity_path_res") or []:
        if re.fullmatch(pattern, path):
            return _ref_result(kind="entity", reason="OK", adapter=adapter["id"], host=host,
                               scheme=scheme, roles=list(adapter.get("roles") or []),
                               approval_status=approval,
                               locator="%s:%s%s" % (adapter["id"], host, path.rstrip("/")))
    verdict = cfg.get("unregistered_verdict") or {}
    return _ref_result(reason=verdict.get("reason_code_path") or "REF_SOURCE_PATH_UNREGISTERED",
                       adapter=adapter["id"], host=host, scheme=scheme,
                       detail="path=%s 未落在适配器 %s 登记的任何实体路径模式内（④：未登记形状不得"
                              "默认成实体页）" % (path, adapter["id"]))


def _classify_reference_url(value: str, cfg: dict[str, Any]) -> dict[str, Any]:
    text = _blank_ref(value)
    if not text or not _URL_FORM_RE.match(text):
        return _ref_result(reason="REF_NOT_HTTPS_URL", detail=text[:60] or "empty")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return _ref_result(reason="REF_URL_CONTROL_CHARACTER",
                           detail="raw URL contains a C0/DEL control character")
    try:
        parts = urllib.parse.urlsplit(text)
    except ValueError:
        return _ref_result(reason="REF_NOT_HTTPS_URL", detail="unparsable")
    try:
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError as exc:
        return _ref_result(reason="REF_PORT_INVALID", scheme=(parts.scheme or "").lower(),
                           detail=str(exc))
    scheme = (parts.scheme or "").lower()
    # host registration is resolved first: an http:// URL on a registered provider host is still
    # a provider host, and calling it "not registered" would send the reader to the wrong fix.
    registered: set = set()
    provider = ""
    for name, spec in (cfg.get("providers") or {}).items():
        names = {item.lower() for item in spec.get("hostnames") or []}
        registered |= names
        if host in names:
            provider = name
            break
    lookalike = ""
    if not provider:
        for item in sorted(registered, key=len, reverse=True):
            if host.startswith(item + "."):
                lookalike = item
                break
    if scheme not in {item.lower() for item in cfg.get("schemes") or []}:
        return _ref_result(provider=provider, reason="REF_SCHEME_NOT_ALLOWED" if scheme
                           else "REF_NOT_HTTPS_URL", host=host, scheme=scheme,
                           detail=scheme or "no scheme")
    if not host:
        return _ref_result(reason="REF_HOST_NOT_REGISTERED", scheme=scheme, detail="no host")
    if parts.username or parts.password:
        return _ref_result(provider=provider, reason="REF_USERINFO_PRESENT", host=host,
                           scheme=scheme, detail="netloc=%s" % parts.netloc)
    if lookalike:
        return _ref_result(reason="REF_PROVIDER_LOOKALIKE_HOST", host=host, scheme=scheme,
                           detail="%s extends registered host %s" % (host, lookalike))
    path = (parts.path or "/").lower()
    if "\\" in path:
        return _ref_result(provider=provider, reason="REF_PATH_RAW_SEPARATOR", host=host,
                           scheme=scheme, detail="raw path contains a backslash separator")
    decoded = urllib.parse.unquote(path)
    decoded_new_separator = (decoded.count("/") != path.count("/") or "\\" in decoded or
                             "?" in decoded or "#" in decoded or
                             any(ord(ch) < 32 or ord(ch) == 127 for ch in decoded))
    if decoded != path and decoded_new_separator:
        return _ref_result(provider=provider, reason="REF_PATH_DECODED_SEPARATOR", host=host,
                           scheme=scheme,
                           detail="percent-decoding introduces a separator or control character")
    for token in cfg.get("unsafe_path_tokens") or []:
        if token in path or token in decoded:
            return _ref_result(provider=provider, reason="REF_PATH_UNSAFE", host=host,
                               scheme=scheme, detail=token)
    query = _query_map(parts.query)
    for key in cfg.get("forbidden_query_keys") or []:
        if key in query:
            return _ref_result(provider=provider, reason="REF_QUERY_PARAM_CAN_REDIRECT", host=host,
                               scheme=scheme, detail="%s=%s" % (key, query[key][0][:40]))
    if not provider:
        return _classify_adapter_url(host, scheme, path, parts.fragment or "", query, cfg)
    return _classify_provider_url(host, scheme, parts, provider,
                                  (cfg.get("providers") or {})[provider], cfg)


def _origin_shape(row: Any, cfg: dict[str, Any]) -> dict[str, Any]:
    """The evidence row's own source value, judged by the same classifier and no other (⑤)."""
    origin = _blank_ref(row.get("source_url_or_ref") if isinstance(row, dict) else "")
    if not origin:
        return _ref_result(reason="REF_ORIGIN_UNCLASSIFIABLE",
                           detail="row carries no source_url_or_ref")
    if not _URL_FORM_RE.match(origin):
        if re.match(cfg.get("dataset_locator_re") or "(?!)", origin):
            return _ref_result(kind="entity", reason="OK", locator=origin,
                               reference_form="dataset_locator", detail="dataset locator")
        return _ref_result(reason="REF_ORIGIN_UNCLASSIFIABLE",
                           detail="source_url_or_ref=%r is neither an absolute URL nor a registered "
                                  "dataset locator" % origin[:60])
    return _classify_reference_url(origin, cfg)


def _origin_allowed(classes: list, origin: dict[str, Any], source_type: str,
                    cfg: dict[str, Any]) -> dict[str, Any]:
    """Three separate gates for the origin: it must be an entity, of an allowed class, and the row
    must claim a source_type the adapter (or the dataset registry) actually declares (⑤).

    A candidate class that does not match is *skipped*, not treated as the final answer -- an
    adapter serving several roles still gets its declared role matched. Then the dominant reason is
    chosen: an origin that cannot be read as a source at all reports its own code, a dataset origin
    whose id is not registered reports REF_ORIGIN_PENDING_REGISTRATION, anything else that is
    merely the wrong class reports REF_ORIGIN_UNPROVEN.
    """
    classes = list(classes or [])
    adapter_index = {item.get("id"): item for item in _source_adapters(cfg)}
    if origin.get("kind") != "entity":
        code = origin.get("reason_code") or ""
        diagnostic = code if code in (cfg.get("origin_diagnostic_codes") or []) else ""
        if diagnostic:
            return {"ok": False, "reason": diagnostic,
                    "detail": "证据行来源本身读不成来源：%s（%s）" % (diagnostic,
                                                                    origin.get("detail", ""))}
        return {"ok": False, "reason": "REF_ORIGIN_UNPROVEN",
                "detail": "origin kind=%s reason=%s 不是实体页；允许的类别=%s"
                          % (origin.get("kind"), code or "-", classes)}
    near_miss = ""
    for item in classes:
        if item == "osm_entity_url":
            if origin["kind"] == "entity" and origin["provider"] == "osm":
                accepted = ((cfg.get("providers") or {}).get("osm")
                            or {}).get("accepted_row_source_types") or []
                if source_type not in accepted:
                    return {"ok": False, "reason": "REF_ORIGIN_UNPROVEN",
                            "detail": "出处是 OSM 实体页，但证据行声明 source_type=%r；OSM 页面只在 %s "
                                      "下才算许可开放数据来源（⑤）" % (source_type, accepted)}
                return {"ok": True, "detail": "osm entity page (%s)" % origin["host"]}
            continue
        if str(item).startswith("adapter_role:"):
            role = item.split(":", 1)[1]
            adapter = adapter_index.get(origin.get("adapter") or "")
            if origin["kind"] != "entity" or not adapter:
                continue
            if role not in (adapter.get("roles") or []):
                near_miss = ("出处适配器 %s 未声明角色 %s（它只服务 %s）"
                             % (adapter.get("id"), role, adapter.get("roles")))
                continue
            if not _approval_is_identity_eligible(adapter.get("approval_status"), cfg):
                return {"ok": False, "reason": "REF_SOURCE_APPROVAL_PENDING",
                        "detail": "出处适配器 %s approval_status=%r 不在生产身份证据允许状态 %s"
                                  % (adapter.get("id"), adapter.get("approval_status"),
                                     cfg.get("identity_eligible_approval_statuses"))}
            if source_type != role:
                near_miss = ("出处适配器 %s 服务 %s，而证据行声明 source_type=%r"
                             % (adapter.get("id"), adapter.get("roles"), source_type))
                continue
            return {"ok": True, "detail": "adapter %s declares role %s"
                                          % (adapter.get("id"), role)}
        if str(item).startswith("dataset:"):
            dataset_id = item.split(":", 1)[1]
            rules = cfg.get("dataset_origin_rules") or {}
            dataset_types = cfg.get("dataset_source_types") or []
            if dataset_id not in (rules.get("registered_dataset_ids") or []):
                if origin.get("reference_form") == "dataset_locator" or source_type in dataset_types:
                    return {"ok": False, "reason": "REF_ORIGIN_PENDING_REGISTRATION",
                            "detail": "数据集 %s 本轮未登记（registered_dataset_ids=%s）：W3 必须登记 "
                                      "id、来源形式、locator 与 lineage 后才可放行（⑤）"
                                      % (dataset_id, rules.get("registered_dataset_ids"))}
                continue
            if source_type not in dataset_types:
                near_miss = "证据行 source_type=%r 不是数据集类型" % source_type
                continue
            if origin.get("reference_form") == "dataset_locator" and \
                    str(origin.get("canonical_locator") or "").split("#", 1)[0] != \
                    "dataset:%s" % dataset_id:
                near_miss = "dataset locator %s 与被登记的 %s 不是同一个数据集" % (
                    origin.get("canonical_locator"), dataset_id)
                continue
            return {"ok": True, "detail": "registered dataset %s" % dataset_id}
    return {"ok": False, "reason": "REF_ORIGIN_UNPROVEN",
            "detail": near_miss or "origin kind=%s provider=%s adapter=%s source_type=%r；允许="
                                   "%s" % (origin["kind"], origin["provider"] or "-",
                                           origin.get("adapter") or "-", source_type, classes)}


def _lineage_ok(items: list, canonical: str, origin: dict[str, Any], namespace: str,
                row: Any) -> dict[str, Any]:
    for item in items or []:
        if item == "never_accepted":
            return {"ok": False, "reason": "REF_NOT_IDENTITY_BEARING",
                    "detail": "coordinate and provider-internal ids are never identity evidence"}
        if item == "lineage_group_required" and \
                not _blank_ref((row or {}).get("lineage_group") if isinstance(row, dict) else ""):
            return {"ok": False, "reason": "REF_LINEAGE_REQUIRED",
                    "detail": "lineage_group blank: the reference cannot be counted as independent"}
        if item == "locator_must_equal_origin_url_locator":
            if origin.get("kind") == "entity" and origin.get("canonical_locator") and \
                    origin["canonical_locator"] != canonical:
                return {"ok": False, "reason": "REF_LINEAGE_CONTRADICTION",
                        "detail": "ref=%s but the row source URL is %s"
                                  % (canonical, origin["canonical_locator"])}
        if item == "namespace_must_equal_origin_host":
            # W1R-B1 ⑥: exact normalized host, never the last two labels of a hostname.
            if origin.get("host") != namespace:
                return {"ok": False, "reason": "REF_LINEAGE_CONTRADICTION",
                        "detail": "命名空间 %s 不等于出处的精确主机 %s"
                                  % (namespace, origin.get("host"))}
    return {"ok": True, "reason": "OK", "detail": ""}


def _classify_reference_form(value: str, field: str, cfg: dict[str, Any]):
    text = _blank_ref(value)
    if ":" not in text:
        bare = (cfg.get("ref_rules") or {}).get("osm") or {}
        if field in (bare.get("bare_allowed_fields") or []) and \
                re.match(bare.get("bare_re") or "(?!)", text.lower()):
            return "osm:" + text.lower(), bare
        return None
    namespace = text.split(":", 1)[0].lower()
    rules = cfg.get("ref_rules") or {}
    rule = rules.get(namespace)
    if rule is None:
        scoped = cfg.get("publisher_scoped_ref") or {}
        if not re.match(scoped.get("namespace_host_re") or "(?!)", namespace):
            return _ref_result(reason="REF_NAMESPACE_UNKNOWN", detail=text[:60], field=field,
                               namespace=namespace)
        # W1R-B1 ⑥: looking like a hostname is not enough. Publisher-scoped ids are accepted only
        # for explicitly registered namespaces, matched against the exact normalized host.
        if namespace not in {item.lower() for item in scoped.get("registered_namespaces") or []}:
            return _ref_result(reason="REF_NAMESPACE_UNKNOWN", field=field, namespace=namespace,
                               detail="%s 不在登记命名空间清单 %s（多级公共后缀与子域名不得自行推导）"
                                      % (namespace, scoped.get("registered_namespaces")))
        rule = {"canonical_re": r"^%s:%s$" % (re.escape(namespace),
                                              (scoped.get("id_re") or "")[1:-1]),
                "reference_form": scoped.get("reference_form"),
                "origin": list(scoped.get("origin") or []),
                "lineage": list(scoped.get("lineage") or [])}
    return "%s:%s" % (namespace, text.split(":", 1)[1]), rule


def classify_reference(value: Any, policy: dict[str, Any] | None = None, *,
                       field: str = "", required_provider: str = "", purpose: str = "surface",
                       row: Any = None) -> dict[str, Any]:
    """The one typed judgment used by identity evidence, publisher links, W4 hrefs and W5 DOM gates.

    Output is always provider + kind + canonical_locator + reason_code (+ host/scheme/adapter/detail).
    `kind` is one of entity/search/coordinate/home/invalid. `purpose="identity"` additionally refuses
    a reference that sits on a map provider's own domain, because our own link is not evidence of
    the place it points to (§17.1 / §17.3.3); `purpose="surface"` keeps the shape verdict, which is
    what the link renderer and the DOM gate need.
    """
    policy = policy or load_policy()
    cfg = classifier_config(policy)
    text = _blank_ref(value)
    if not text:
        return _ref_result(reason="REF_ID_INVALID", detail="empty reference", field=field)
    is_url = bool(_URL_FORM_RE.match(text))
    if is_url or field in ((cfg.get("reference_forms") or {}).get("url") or []):
        if not is_url:
            return _ref_result(reason="REF_NOT_HTTPS_URL", field=field,
                               detail="%s must hold an absolute URL, got %r" % (field, text[:40]))
        found = _classify_reference_url(text, cfg)
        found["field"] = field
        found["reference_form"] = "url"
        found["purpose"] = purpose
        if required_provider and found["kind"] and found["kind"] != "invalid":
            if found["provider"] != required_provider:
                found["reason_code"] = "REF_PROVIDER_MISMATCH"
                found["detail"] = "required provider=%s but the URL is %s (host=%s)" % (
                    required_provider, found["provider"] or "a non-provider host", found["host"])
        if purpose == "identity" and found["kind"] in (cfg.get("kind_identity_bearing") or []) \
                and found["provider"]:
            found["reason_code"] = "REF_ORIGIN_UNPROVEN"
            found["detail"] = ("identity cannot rest on a map provider's own domain (host=%s, "
                               "provider=%s); such a URL is only a link surface"
                               % (found["host"], found["provider"]))
        if purpose == "identity" and found.get("adapter") and found.get("kind") == "entity" and \
                not _approval_is_identity_eligible(found.get("approval_status"), cfg):
            found["reason_code"] = "REF_SOURCE_APPROVAL_PENDING"
            found["detail"] = ("adapter=%s approval_status=%r is not eligible for production "
                               "identity evidence" % (found.get("adapter"),
                                                       found.get("approval_status")))
        return found
    parsed = _classify_reference_form(text, field, cfg)
    if parsed is None:
        return _ref_result(reason="REF_NOT_A_REFERENCE_FORM", detail=text[:60], field=field)
    if isinstance(parsed, dict):
        parsed["field"] = field
        return parsed
    canonical, rule = parsed
    namespace = canonical.split(":", 1)[0]
    identifier = canonical.split(":", 1)[1]
    if rule.get("non_place_ids_re") and re.match(rule["non_place_ids_re"], canonical):
        return _ref_result(reason=rule.get("non_place_reason") or "REF_NOT_PLACE_ENTITY",
                           field=field, namespace=namespace,
                           detail="%s 上的 user/changeset 是对象但不是地点（③）" % namespace)
    forms = cfg.get("reference_forms") or {}
    allowed_fields = forms.get(rule.get("reference_form") or "", [])
    if field not in allowed_fields:
        return _ref_result(reason="REF_FIELD_NOT_ALLOWED_FOR_FORM", field=field,
                           namespace=namespace,
                           detail="%s is accepted only in %s"
                                  % (rule.get("reference_form"), allowed_fields or "no field"))
    if not re.match(rule["canonical_re"], canonical):
        return _ref_result(reason="REF_ID_INVALID", detail=canonical[:60], field=field,
                           namespace=namespace)
    if rule.get("range_check") and _coordinate_pair_state(identifier, cfg)[0] != "ok":
        return _ref_result(reason="REF_ID_INVALID", detail="%s is not an in-domain lat/lng pair"
                           % canonical, field=field, namespace=namespace)
    if not rule.get("identity_bearing", True):
        return _ref_result(reason="REF_NOT_IDENTITY_BEARING", field=field, namespace=namespace,
                           detail=rule.get("why_not_identity_bearing", "not identity bearing"),
                           locator=canonical)
    origin = _origin_shape(row, cfg)
    allowed = _origin_allowed(rule.get("origin") or [], origin,
                              _blank_ref((row or {}).get("source_type")
                                         if isinstance(row, dict) else ""), cfg)
    if not allowed["ok"]:
        return _ref_result(reason=allowed["reason"], field=field, namespace=namespace,
                           detail=allowed["detail"])
    lineage = _lineage_ok(rule.get("lineage") or [], canonical, origin, namespace, row)
    if not lineage["ok"]:
        return _ref_result(reason=lineage["reason"], field=field, namespace=namespace,
                           detail=lineage["detail"])
    return _ref_result(kind="entity", reason="OK", locator=canonical, namespace=namespace,
                       field=field, reference_form=rule.get("reference_form", ""),
                       origin_adapter=origin.get("adapter", ""),
                       origin_host=origin["host"])


def map_url_shape(url: Any, policy: dict[str, Any]) -> dict[str, Any]:
    """Compatibility view over the classifier: the W1R-A boolean shape, same single judgment.

    Kept only so older call sites and negative tests keep working; it must not grow rules of its
    own. `is_map_host` means "a registered provider host or a look-alike of one", `path_ok` means
    "the classifier recognized a registered shape", and both are derived from `classify_reference`.
    """
    cfg = classifier_config(policy)
    found = _classify_reference_url(url, cfg)
    recognized = found["kind"] in ("entity", "search", "coordinate", "home")
    return {"host": found["host"], "provider": found["provider"],
            "is_map_host": bool(found["provider"]),
            "lookalike_of_provider": found["reason_code"] == "REF_PROVIDER_LOOKALIKE_HOST",
            "path_ok": bool(found["provider"]) and recognized,
            "scheme": found["scheme"],
            "scheme_ok": found["reason_code"] != "REF_SCHEME_NOT_ALLOWED",
            "kind": found["kind"], "canonical_locator": found["canonical_locator"],
            "reason_code": found["reason_code"], "reason": found["detail"]}


def _is_generated_map_url(url: Any, policy: dict[str, Any] | None = None) -> bool:
    """A registered provider's own host is never evidence of a place, whatever path it carries."""
    policy = policy or load_policy()
    return bool(map_url_shape(url, policy)["is_map_host"])


def reference_is_identity_qualifying(found: dict[str, Any]) -> bool:
    """The single question identity and publisher-link rules ask the classifier."""
    return bool(found) and found.get("kind") == "entity" and \
        found.get("reason_code") == "OK" and bool(found.get("canonical_locator"))


def _coordinate_issues(lat: Any, lng: Any) -> list[str]:
    """Finite numeric domain only: garbage strings, NaN/Infinity and out-of-range values are refused."""
    problems: list[str] = []
    for label, value, limit in (("lat", lat, 90.0), ("lng", lng, 180.0)):
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append("%s=缺失" % label)
            continue
        number: float
        if isinstance(value, bool):
            problems.append(f"{label}={value!r} 是布尔值，不是坐标")
            continue
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            text = value.strip()
            if "," in text or " " in text:
                problems.append(f"{label}={value!r} 是字符串化的坐标对，不是单个数值")
                continue
            try:
                number = float(text)
            except ValueError:
                problems.append(f"{label}={value!r} 非数值")
                continue
            problems.append(f"{label}={value!r} 数值必须是数字类型而非字符串")
        else:
            problems.append(f"{label}={type(value).__name__} 类型不接受")
            continue
        if number != number:
            problems.append(f"{label}=NaN 非有限值")
            continue
        if number in (float("inf"), float("-inf")):
            problems.append(f"{label}={value!r} 为无穷值")
            continue
        if abs(number) > limit:
            problems.append(f"{label}={number:g} 超出 ±{limit:g}（越界或经纬顺序颠倒）")
    return problems


def address_shape_ok(source: dict[str, Any], policy: dict[str, Any],
                     target: dict[str, Any] | None = None) -> tuple[bool, str]:
    """An address separates same-name entities only if it is actually an address (W1R-B ③).

    The row states what the source said, so the address is read from the evidence row first and
    from the target record second; a claim of `supported_fields: ["address"]` with no address
    anywhere is a data defect, not a disambiguator.
    """
    rule = ((policy.get("identity_evidence_combination") or {})
            .get("address_field_shape") or {})
    length = int(rule.get("min_length") or 0)
    tokens = int(rule.get("min_tokens") or 0)
    if not length or not tokens:
        return True, ""
    source_fields = rule.get("source_fields") or ["address"]
    value = ""
    holder = ""
    for candidate in (source, target or {}):
        for field in source_fields:
            value = _blank_ref(candidate.get(field))
            if value:
                holder = "证据行.%s" % field if candidate is source else "记录.%s" % field
                break
        if value:
            break
    if not value:
        return False, "地址字段 %s 在证据行与记录上都为空" % source_fields
    if len(value) < length:
        return False, "地址 %r 短于 %d 字符，不足以区分同名实体（来自 %s）" % (value[:40],
                                                                            length, holder)
    parts = [item.strip() for item in re.split(rule.get("token_split") or "[,;]", value)
             if item.strip()]
    if len(parts) < tokens:
        return False, "地址 %r 只有 %d 段，要求至少 %d 段（门牌/街道/区域）" % (value[:40],
                                                                            len(parts), tokens)
    return True, ""


def _identity_origin_verdict(row: dict[str, Any], cfg: dict[str, Any]) -> tuple[bool, str]:
    """An address is useful only when its own source is a production-eligible entity source."""
    origin = _origin_shape(row, cfg)
    source_type = _blank_ref(row.get("source_type"))
    if origin.get("kind") != "entity":
        return False, "出处不是实体来源（%s/%s）" % (origin.get("kind"),
                                                    origin.get("reason_code"))
    if origin.get("provider") == "osm":
        accepted = (((cfg.get("providers") or {}).get("osm") or {})
                    .get("accepted_row_source_types") or [])
        return (source_type in accepted,
                "OSM 出处 source_type=%r 不在 %s" % (source_type, accepted))
    if origin.get("provider"):
        return False, "地图供应商自己的页面不能证明身份"
    if origin.get("adapter"):
        adapter = next((item for item in _source_adapters(cfg)
                        if item.get("id") == origin.get("adapter")), None)
        if not adapter:
            return False, "出处适配器未登记"
        if not _approval_is_identity_eligible(adapter.get("approval_status"), cfg):
            return False, "出处适配器 %s approval_status=%r 尚无生产身份证据资格" % (
                adapter.get("id"), adapter.get("approval_status"))
        if source_type not in (adapter.get("roles") or []):
            return False, "出处适配器 %s 不服务 source_type=%r" % (adapter.get("id"), source_type)
        return True, ""
    if origin.get("reference_form") == "dataset_locator":
        dataset_id = str(origin.get("canonical_locator") or "").split("#", 1)[0].split(":", 1)[-1]
        allowed = ((cfg.get("dataset_origin_rules") or {}).get("registered_dataset_ids") or [])
        return (dataset_id in allowed,
                "dataset=%r 未登记为生产来源" % dataset_id)
    return False, "出处没有可审计的 provider/adapter/dataset 身份"


def identity_row_verdict(row: dict[str, Any], policy: dict[str, Any],
                             target: dict[str, Any] | None = None
                             ) -> tuple[bool, list[str], list[dict[str, Any]]]:
    """Why a single evidence row can or cannot endorse `identity_status=VERIFIED` (W1R-A ③ / W1R-B).

    Requiring only "supported_fields hits some identity field" let a row that supports nothing but
    `country_code` (or `category`) certify an identity -- a country-level fact identifies nobody.
    W1R-B closes the second half: the disambiguator must itself be *validated*. A stable reference
    goes through the same typed classifier used for links, so a provider root page, a search page,
    a coordinate page, a garbage string, an unknown short link or a forged namespace cannot buy
    `identity_status=VERIFIED`.
    """
    reasons: list[str] = []
    refs: list[dict[str, Any]] = []
    cfg = classifier_config(policy)
    required = list(policy.get("evidence_required_fields") or [])
    gaps = [field for field in required if _blank(row.get(field))]
    if gaps:
        reasons.append("字段不全 %s" % gaps)
    usable = set(policy.get("evidence_status_usable") or [])
    if str(row.get("status")) not in usable:
        reasons.append("status=%r 不可用" % row.get("status"))
    supporting = set(policy.get("identity_supporting_source_types") or [])
    source_type = str(row.get("source_type") or "")
    if source_type not in supporting:
        reasons.append("source_type=%r 无身份证据资格" % source_type)
    origin_ok, origin_why = _identity_origin_verdict(row, cfg)
    if not origin_ok:
        reasons.append(origin_why)

    combo = policy.get("identity_evidence_combination") or {}
    name_any = set(combo.get("required_any") or [])
    also_any = set(combo.get("and_also_any") or [])
    stable_refs = set(combo.get("stable_entity_ref_fields") or [])
    supported = row.get("supported_fields")
    supported = supported if isinstance(supported, (list, tuple, set)) else [supported]
    supported = {str(item).strip() for item in supported if str(item).strip()}
    if not supported:
        reasons.append("supported_fields 为空")
    else:
        if name_any and not (supported & name_any):
            reasons.append("未覆盖实体名称字段 %s" % sorted(name_any))
        disambiguated: list[str] = []
        if "address" in also_any and bool(supported & {"address", "street_address"}):
            ok, why = address_shape_ok(row, policy, target)
            refs.append({"field": "address", "kind": "address",
                         "reason_code": "OK" if ok else "ADDRESS_SHAPE_INVALID",
                         "canonical_locator": _blank_ref(row.get("address")), "detail": why})
            if ok:
                disambiguated.append("address")
        rule = combo.get("stable_ref_classifier_rule") or {}
        for field in sorted(stable_refs):
            value = _blank_ref(row.get(field))
            if not value:
                continue
            required_provider = "" if field not in (rule.get("url_fields") or []) else \
                _blank_ref(row.get("link_url_provider"))
            found = classify_reference(value, policy, field=field, row=row,
                                       required_provider=required_provider, purpose="identity")
            refs.append(found)
            if reference_is_identity_qualifying(found):
                disambiguated.append(field)
        if also_any and not disambiguated:
            rejected = ["%s[%s/%s]" % (item.get("field"), item.get("kind"),
                                       item.get("reason_code")) for item in refs]
            reasons.append("无可**经过校验**的可区分字段或稳定实体引用 %s；已给出的候选被拒：%s"
                           % (sorted(also_any | stable_refs), ", ".join(rejected) or "无"))
    return (not reasons), reasons, refs


def _qualifying_identity_rows(rows: list[dict[str, Any]], policy: dict[str, Any],
                              target: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [row for row in rows if identity_row_verdict(row, policy, target)[0]]


def _location_role_findings(key: str, target: dict[str, Any],
                            policy: dict[str, Any]) -> list[str]:
    """§5.1/§5.3 + 业主 2026-10-29 指令 §5：required_location_role 按类别适用矩阵判定。

    V2R 之前它是无条件必填：278 条空角色的酒店/餐厅/景点全被判错，而真正要问的
    「机场到底哪个航站楼、码头到底哪个 Pier」反而埋在噪声里看不见了。两种情形都不许含糊：
    类别不在册 ⇒ 单独暴露（不猜它需不需要角色）；该类别强制且目标关键却没有角色 ⇒
    CRITICAL_ROLE_MISSING（暴露项，逐项进报告）。角色**取值**是否合法不由这张矩阵管，
    它走全局枚举 `required_location_role`（MAP_ENUM_INVALID，blocking）——
    V4-A 一开始想用 per-category allowed_roles 去限，结果把 11 条「码头里的餐厅/咖啡馆」
    判成错，那是把「哪个入口」的语义错当成「这类地点只能有哪些角色」。
    """
    matrix = policy.get("required_location_role_applicability") or {}
    by_category = matrix.get("by_category") or {}
    declared_empty = {str(item) for item in
                      (matrix.get("empty_role_means") if matrix.get("empty_role_means")
                       is not None else [""])}
    category = str(target.get("category") or "").strip()
    raw_role = target.get("required_location_role")
    role = str(raw_role or "").strip()
    is_empty = _blank(raw_role) or role in declared_empty
    findings: list[str] = []
    spec = by_category.get(category)
    if spec is None:
        if category:
            findings.append(
                f"ROLE_APPLICABILITY_CATEGORY_UNREGISTERED|{key} category={category!r} 不在 "
                f"required_location_role_applicability.by_category 里：适用性未知时既不猜它需要角色，"
                f"也不放它过")
        else:
            finding = str((matrix.get("unknown_category") or {}).get("finding")
                          or "ROLE_APPLICABILITY_CATEGORY_UNKNOWN")
            findings.append(f"{finding}|{key} category 为空，位置角色适用性无法判定"
                            f"（category 自身另有必填检查，这里不重复判）")
        return findings
    if is_empty and spec.get("role_required") and \
            str(target.get("criticality")) == "CRITICAL_ITINERARY":
        findings.append(
            f"CRITICAL_ROLE_MISSING|{key} {category} 属关键目标且该类别强制位置角色"
            f"（§5.1：哪个航站楼/哪个码头/哪个口会决定人去对地方）——逐项暴露进报告与行程正文，"
            f"整份攻略是否可交由 delivery gate 按 §8.3 单独裁决")
    return findings


def validate_map_targets(map_targets: Any,
                         policy: dict[str, Any] | None = None) -> list[str]:
    """Enforce checklist §17.2/§17.3 on every map target. Total sweep: nothing short-circuits.

    The old single `target_level` could not distinguish "we know who this is", "we know where",
    "this is the kind of link we ship" and "we watched Google resolve it" -- and every cross-version
    false claim came from reading one as the other. The four dimensions are validated separately and
    no value may be inferred from another.

    W1R hardened three structural holes found by independent review: a non-object inside a list used
    to crash before per-item validation could run, `identity_status=VERIFIED` could be endorsed by a
    regional-background evidence row, and `PUBLISHER_ENTITY_LINK` could be claimed by any source_type
    whose text happened to contain the word "publisher".
    """
    policy = policy or load_policy()
    cfg = classifier_config(policy)
    errors: list[str] = []
    rows: list[tuple[str, Any]] = []
    if isinstance(map_targets, dict):
        rows = list(map_targets.items())
    elif isinstance(map_targets, list):
        for index, item in enumerate(map_targets, 1):
            key = ""
            if isinstance(item, dict):
                key = str(item.get("target_id") or "").strip()
            rows.append((key or "#%d" % index, item))
    else:
        return [f"MAP_TARGETS_CONTAINER_INVALID|map_targets 必须是 dict 或 list，"
                f"实为 {type(map_targets).__name__}，无从逐项校验"]

    required = list(policy.get("map_target_required_fields") or [])
    evidence_required = list(policy.get("evidence_required_fields") or [])
    defaults = set((policy.get("coordinate_forbid") or {}).get("known_default_values") or [])
    names_schema = policy.get("names_schema") or {}
    allowed_name_keys = set(names_schema.get("allowed") or [])
    required_name_keys = set(names_schema.get("required") or [])
    known_source_types = set(policy.get("evidence_source_types") or [])
    publisher_rule = policy.get("publisher_entity_link") or {}
    publisher_source_types = {str(item).casefold()
                              for item in publisher_rule.get("required_evidence_source_types") or []}
    publisher_fields = list(publisher_rule.get("required_evidence_fields") or [])

    seen_ids: dict[str, str] = {}
    for key, target in rows:
        if not isinstance(target, dict):
            errors.append(f"MAP_TARGET_NOT_OBJECT|{key} 目标记录是 {type(target).__name__}，"
                          f"四维状态无从校验")
            continue
        missing = [field for field in required if _blank(target.get(field))]
        if missing:
            # `fields=` 是给门禁看的稳定片段（哪些字段缺要分级，见 map-gate-v422.json）；
            # 后面的中文列表给人看。两者必须来自同一个 missing，不允许各算各的。
            errors.append("MAP_FIELD_MISSING|%s|fields=%s 缺 §17.2.5 必填字段: %s"
                          % (key, ",".join(missing), missing))
        # V1R 条件字段语义：resolver_used 必须是显式布尔；resolver_version 只在 true 时才允许出现。
        if target.get("resolver_used") is not True:
            if not isinstance(target.get("resolver_used"), bool):
                errors.append(f"RESOLVER_USED_NOT_EXPLICIT|{key} resolver_used 必须显式写成 true/false；"
                              f"当前是 {target.get('resolver_used')!r}。正式链不使用 W3 resolver，"
                              f"要记 false，不是留空也不是编版本")
            if not _blank(target.get("resolver_version")):
                errors.append(f"RESOLVER_VERSION_WITHOUT_RESOLVER|{key} resolver_used 不为 true 却带着 "
                              f"resolver_version={str(target.get('resolver_version'))[:40]!r}；"
                              f"§2.2 已把 resolver 移出前置链，这条版本号是无来源的（禁止伪造血缘）")
        # evidence / lineage_group：缺键=状态未知（报错）；显式空=已确认没有（只封 VERIFIED）。
        explicit = policy.get("map_target_explicit_empty_fields") or {}
        for field in explicit.get("fields") or []:
            if field not in target:
                errors.append(f"MAP_FIELD_NOT_EXPLICIT|{key} {field} 键不存在：状态未知不等于没有，"
                              f"必须显式写成空列表/空串（§8.2 每项都要有可判状态）")
        declared_classifier = _blank_ref(target.get("classifier_version"))
        current_classifier = _blank_ref(cfg.get("classifier_version"))
        superseded = cfg.get("supersedes") or []
        superseded = [superseded] if isinstance(superseded, str) else list(superseded)
        if declared_classifier and current_classifier and declared_classifier != current_classifier:
            if declared_classifier in set(str(item) for item in superseded):
                errors.append(
                    f"CLASSIFIER_VERSION_STALE|{key} classifier_version={declared_classifier!r} "
                    f"已被当前 {current_classifier!r} 取代；必须按当前规则重新判定后才可写入新版本，"
                    f"不得机械改标签（W1R-B2 ④）")
            else:
                errors.append(
                    f"CLASSIFIER_VERSION_UNKNOWN|{key} classifier_version={declared_classifier!r} "
                    f"不等于当前 {current_classifier!r}，也不在 supersedes={superseded}；未知规则结果不得进入迁移")
        for field, policy_key in _ENUMS.items():
            allowed = set(policy.get(policy_key) or [])
            value = target.get(field)
            if not _blank(value) and allowed and str(value) not in allowed:
                errors.append(f"MAP_ENUM_INVALID|{key} {field}={value!r} 不在枚举 {sorted(allowed)} 内")

        # identity of the record itself (W1R ⑤): duplicate target_id and dict-key mismatch are data
        # defects, not cosmetics -- they are how one card silently overwrites another.
        declared_id = str(target.get("target_id") or "").strip()
        if declared_id:
            if declared_id in seen_ids:
                errors.append(f"MAP_TARGET_ID_DUPLICATE|{key} target_id={declared_id!r} 已被 "
                              f"{seen_ids[declared_id]} 使用，两条记录会互相覆盖")
            else:
                seen_ids[declared_id] = key
            if key and declared_id != key:
                errors.append(f"MAP_TARGET_ID_KEY_MISMATCH|字典键 {key} 与 target_id={declared_id!r} "
                              f"不一致，报告与 DOM 的 data-target-id 无法对齐")
        elif "target_id" not in missing:
            errors.append(f"MAP_TARGET_ID_MISSING|{key} 没有 target_id")

        # names is a frozen structure (W1R ⑤): en is the only string allowed to enter a URL
        names = target.get("names")
        if names is not None:
            if not isinstance(names, dict):
                errors.append(f"NAMES_STRUCTURE_INVALID|{key} names 必须是对象"
                              f"（{names_schema.get('type')}），实为 {type(names).__name__}")
            else:
                absent = sorted(required_name_keys - set(names))
                if absent:
                    errors.append(f"NAMES_KEY_MISSING|{key} names 缺必填键 {absent}")
                unknown = sorted(set(names) - allowed_name_keys)
                if unknown:
                    errors.append(f"NAMES_KEY_UNKNOWN|{key} names 含冻结结构之外的键 {unknown}")
                for name_key, name_value in names.items():
                    if not isinstance(name_value, str) or not name_value.strip():
                        errors.append(f"NAMES_VALUE_INVALID|{key} names.{name_key}={name_value!r} "
                                      f"必须是非空字符串")
                    elif name_key == "en" and CJK_RE.search(name_value):
                        errors.append(f"NAMES_EN_NOT_LATIN|{key} names.en 含汉字，无法用于构造 URL；"
                                      f"缺拉丁名应显式降级，不得删字（§17.4.2）")

        entity_type = str(target.get("entity_type") or "")
        link_mode = str(target.get("link_mode") or "")
        coordinate_status = str(target.get("coordinate_status") or "")
        rows_evidence, member_problems = evidence_members(target, key)
        errors.extend(member_problems)

        # evidence: minimum fields, eligibility, self-attestation
        for row in rows_evidence:
            gaps = [field for field in evidence_required if _blank(row.get(field))]
            if gaps:
                errors.append(f"EVIDENCE_INCOMPLETE|{key} 证据缺字段 {gaps}，不得支撑 identity_status")
            source_type = str(row.get("source_type") or "")
            if source_type and known_source_types and source_type not in known_source_types:
                errors.append(f"EVIDENCE_SOURCE_TYPE_UNKNOWN|{key} source_type={source_type!r} "
                              f"不在枚举内；类型字符串按精确成员判定，不做子串匹配")
            status = str(row.get("status") or "")
            if status and policy.get("evidence_status") and status not in set(policy["evidence_status"]):
                errors.append(f"EVIDENCE_STATUS_UNKNOWN|{key} status={status!r} 不在 "
                              f"{sorted(policy['evidence_status'])} 内")
            elif status and status not in set(policy.get("evidence_status_usable") or []):
                errors.append(f"EVIDENCE_STATUS_UNUSABLE|{key} 证据 status={status!r} 不可用于支撑声明")
            url = _blank_ref(row.get("source_url_or_ref"))
            # W1R-B: eligibility of a source URL is one classifier call, not a second set of regexes
            if url:
                # W1R-B1 ⑤: the origin is read by the *origin* judgment (URL shape or a registered
                # dataset locator), not by the generic reference-form path, so a `dataset:` source is
                # classified the way the lineage gate will later compare it.
                shape = _origin_shape(row, cfg)
                ineligible = (policy.get("evidence_ineligible_sources") or {})
                by_kind = ineligible.get("by_classifier_kind") or {}
                eligible = (cfg.get("evidence_eligibility_by_provider_host") or {})
                role = eligible.get(shape["provider"], "self_attestation") if shape["provider"] else ""
                if str(target.get("identity_status") or "") == "VERIFIED" and shape.get("adapter") \
                        and not _approval_is_identity_eligible(shape.get("approval_status"), cfg):
                    errors.append(
                        f"EVIDENCE_SOURCE_APPROVAL_PENDING|{key} 证据适配器={shape['adapter']} "
                        f"approval_status={shape.get('approval_status')!r} 只允许记录/发现，"
                        f"不在生产身份证据允许状态 {cfg.get('identity_eligible_approval_statuses')} 内")
                if shape["provider"] and role == "licensed_open_data_source":
                    pass  # an OSM object page is a licensed source with its own license and lineage
                elif shape["provider"] or shape["reason_code"] == "REF_PROVIDER_LOOKALIKE_HOST":
                    errors.append(f"EVIDENCE_SELF_ATTESTATION|{key} 证据引用了地图供应商主机"
                                  f"（或冒充它的主机名）上的 URL，它不能证明具体地点: "
                                  f"{shape['reason_code']}/{shape['host']}")
                elif shape["kind"] == "home" and "home" in by_kind:
                    errors.append(f"EVIDENCE_HOMEPAGE_ONLY|{key} 根页/门牌页不能证明具体地点"
                                  f"（classifier kind=home）: {url[:80]}")
                elif shape["kind"] == "search" and "search" in by_kind:
                    errors.append(f"EVIDENCE_SEARCH_URL|{key} 搜索页只能作为发现候选，不能作为身份证据"
                                  f"（classifier kind=search）: {url[:80]}")
                elif shape["kind"] == "invalid":
                    # W1R-B1 ⑤: a source the classifier cannot read at all used to fall through with
                    # no complaint at all, which is how `source_url_or_ref="garbage"` reached VERIFIED.
                    errors.append(
                        f"EVIDENCE_SOURCE_UNCLASSIFIABLE|{key} 证据 source_url_or_ref="
                        f"{url[:70]!r} 被判为 invalid（{shape['reason_code']}: "
                        f"{shape['detail'][:70]}）；出处读不成来源就不能背书任何声明，"
                        f"未登记域名/未登记路径/隐私登录 robots 一类面都属此列（§17.3.9 W1R-B1 ④⑤）")
                elif shape["kind"] == "coordinate":
                    errors.append(
                        f"EVIDENCE_COORDINATE_ONLY|{key} 出处是纯坐标页"
                        f"（canonical_locator={shape['canonical_locator']}）；坐标面不证明地点身份")
            # W1R-B1 ⑤: a stable reference that is present but refused must be reported even when
            # another field (usually address) already satisfies the identity combination. Silence here
            # is what let `source_entity_ref="wikidata:Q42"` with a garbage origin ride along.
            stable_rule = (policy.get("identity_evidence_combination") or
                           {}).get("stable_ref_classifier_rule") or {}
            recordable = set(stable_rule.get("recordable_reason_codes") or [])
            for field in [item for item in
                          (policy.get("identity_evidence_combination") or {}).get(
                              "stable_entity_ref_fields") or []
                          if item not in (stable_rule.get("url_fields") or [])]:
                value = _blank_ref(row.get(field))
                if not value:
                    continue
                found = classify_reference(value, policy, field=field, row=row,
                                           purpose="identity")
                if not reference_is_identity_qualifying(found) and \
                        found["reason_code"] not in recordable:
                    errors.append(
                        f"IDENTITY_STABLE_REF_INVALID|{key} 证据行 {field}={value[:60]!r} 被 "
                        f"classifier 判为 kind={found['kind']!r}/{found['reason_code']}"
                        f"（{found['detail'][:70]}）；记录在案的稳定引用必须解释得通，"
                        f"不能靠别的字段把它盖住（§17.2.3 W1R-B1 ⑤）")
        # §17.2.3: link context is mandatory for every link mode (W1R-A ②). NONE ships no URL, so only
        # the selection reason is required -- "why is there no entry point" must also be a decision.
        context_required = list((policy.get("link_context_required_by_mode") or {}).get(link_mode) or [])
        if link_mode:
            gaps = [field for field in context_required if _blank(target.get(field))]
            if gaps:
                errors.append(f"LINK_CONTEXT_MISSING|{key} link_mode={link_mode} 缺链接上下文 {gaps}"
                              f"（provider / URL 构造版本 / 选择原因，§17.2.3）")
            known_providers = set(classifier_config(policy).get("providers") or {})
            declared_provider = str(target.get("link_provider") or "").strip().casefold()
            if declared_provider and known_providers and declared_provider not in known_providers:
                errors.append(f"LINK_PROVIDER_UNKNOWN|{key} link_provider={declared_provider!r} "
                              f"不在已登记 provider {sorted(known_providers)} 内")

        if link_mode == "PUBLISHER_ENTITY_LINK":
            # exact membership only: a source_type that merely *reads like* "publisher-ish" must not
            # buy an entity link (W1R ③).
            backers = [row for row in rows_evidence
                       if str(row.get("source_type") or "").casefold() in publisher_source_types
                       and not any(_blank(row.get(field)) for field in publisher_fields)]
            if not backers:
                errors.append(
                    f"LINK_EVIDENCE_MISSING|{key} link_mode=PUBLISHER_ENTITY_LINK 需要至少一条 "
                    f"source_type 精确等于 {sorted(publisher_source_types)} 且带 "
                    f"{publisher_fields} 的证据；来源类型字符串的子串相似不构成凭据（§17.3.3）")
            want = str(target.get("link_provider") or "").strip().casefold()
            for row in backers:
                declared = _blank_ref(row.get("declared_link_url"))
                got = str(row.get("link_url_provider") or "").strip().casefold()
                if declared and declared == _blank_ref(row.get("source_url_or_ref")):
                    # fail-collect: the shape verdict is still reported, so the reader sees both
                    errors.append(
                        f"LINK_EVIDENCE_SELF_REFERENCE|{key} 该行的 source_url_or_ref 与 "
                        f"declared_link_url 是同一个值（{declared[:70]!r}）；出处就是链接自己，"
                        f"不构成发布方实体链凭据（§17.3.1 血缘独立性）")
                if want and got != want:
                    errors.append(f"LINK_EVIDENCE_PROVIDER_MISMATCH|{key} 按钮 provider={want!r} "
                                  f"而证据声明的 link_url_provider={got!r}；一个提供者的链接不得"
                                  f"把另一个提供者升级为实体直达（§17.4.5）")
                found = classify_reference(declared, policy, field="declared_link_url",
                                           required_provider=want)
                if not found["provider"]:
                    errors.append(
                        f"LINK_DECLARED_URL_INVALID|{key} declared_link_url={declared[:70]!r} "
                        f"不是登记 provider 主机上的链接（{found['reason_code']}: "
                        f"{found['detail'][:60]}）；URL 文本里出现供应商域名样式不等于它是地图链接（W1R-B ①）")
                    continue
                if found["kind"] == "invalid":
                    errors.append(f"LINK_DECLARED_URL_SHAPE_INVALID|{key} "
                                  f"declared_link_url 违规（{found['reason_code']}: "
                                  f"{found['detail'][:70]}）")
                    continue
                if found["kind"] != "entity":
                    errors.append(
                        f"LINK_DECLARED_URL_NOT_ENTITY|{key} declared_link_url 被判为 "
                        f"kind={found['kind']!r}（{found['reason_code']}）；发布方链接只在实体页上成立，"
                        f"provider 根页/搜索页/纯坐标页都不证明该发布方发布过这个地点（§17.3.3 W1R-B）")
                    continue
                if found["reason_code"] == "REF_PROVIDER_MISMATCH":
                    errors.append(f"LINK_DECLARED_URL_PROVIDER_MISMATCH|{key} declared_link_url "
                                  f"的主机名 {found['host']} 属于 provider={found['provider']!r}，"
                                  f"与按钮 provider={want!r} 不一致")
                    continue
                origin = classify_reference(_blank_ref(row.get("source_url_or_ref")), policy,
                                            purpose="identity")
                if origin["provider"] or not reference_is_identity_qualifying(origin):
                    errors.append(
                        f"LINK_EVIDENCE_PAGE_NOT_ENTITY|{key} 该链接的出处 source_url_or_ref="
                        f"{_blank_ref(row.get('source_url_or_ref'))[:70]!r} 判为 kind="
                        f"{origin['kind']!r}/{origin['reason_code']}；凭据必须来自生产批准状态下的发布方"
                        f"实体页，不能是 pending/fixture、根页、搜索页或地图供应商域名")

        # coordinate honesty: absent coordinates must be declared MISSING, present ones must be safe
        lat, lng = target.get("lat"), target.get("lng")
        present = [value for value in (lat, lng) if value is not None and str(value).strip()]
        coords_absent = not present
        coord_problems = _coordinate_issues(lat, lng) if present else []
        if coord_problems:
            errors.append(f"COORD_VALUE_INVALID|{key} " + "；".join(coord_problems)
                          + "（§17.2.2：坐标必须是有限数值且在 ±90 / ±180 内）")
        pair = f"{lat},{lng}"
        if coords_absent and coordinate_status != "MISSING":
            errors.append(f"COORD_ABSENT_BUT_CLAIMED|{key} 没有 lat/lng 却把 coordinate_status 记为 "
                          f"{coordinate_status!r}；缺失必须写 MISSING 并给原因（§17.2.2）")
        if not coords_absent and not coord_problems:
            if coordinate_status == "MISSING":
                errors.append(f"COORD_STATE_CONTRADICTION|{key} 有坐标却记 coordinate_status=MISSING")
            if pair in defaults:
                errors.append(f"COORD_DEFAULT_VALUE|{key} 坐标 {pair} 是已知默认值，不得充当该地点位置")
            if coordinate_status == "VERIFIED":
                context = {item: target.get(item) for item in
                           ("datum", "axis_order", "coordinate_source_ref", "precision_m")}
                gaps = [name for name, value in context.items() if _blank(value)]
                if gaps:
                    errors.append(f"COORD_CONTEXT_MISSING|{key} coordinate_status=VERIFIED 缺上下文 "
                                  f"{gaps}（WGS84/经纬顺序/来源/精度）")
        if link_mode == "COORDINATE":
            if entity_type == "named_entity":
                errors.append(f"LINK_NAMED_ENTITY_COORDINATE|{key} 命名实体不得渲染纯坐标按钮（§17.4.3）")
            if coordinate_status != "VERIFIED":
                errors.append(f"LINK_COORDINATE_UNVERIFIED|{key} link_mode=COORDINATE 要求 "
                              f"coordinate_status=VERIFIED，实为 {coordinate_status!r}")

        # identity claims need support, and stale/observed states must not be promoted
        if str(target.get("identity_status")) == "VERIFIED":
            if not rows_evidence:
                errors.append(f"IDENTITY_VERIFIED_WITHOUT_EVIDENCE|{key} identity_status=VERIFIED "
                              f"没有任何证据记录")
            elif not _qualifying_identity_rows(rows_evidence, policy, target):
                reasons = []
                thin = []
                for row in rows_evidence:
                    ok, why, refs = identity_row_verdict(row, policy, target)
                    if not ok:
                        reasons.append("%s: %s" % (str(row.get("source_url_or_ref") or "?")[:60],
                                                   "; ".join(why)))
                    for found in refs:
                        if found.get("reason_code") != "OK":
                            thin.append("%s[%s/%s:%s]" % (found.get("field"), found.get("kind"),
                                                          found.get("reason_code"),
                                                          str(found.get("detail") or "")[:60]))
                suffix = ""
                if thin:
                    errors.append(
                        f"IDENTITY_REF_KIND_NOT_ENTITY|{key} 用于区分同名的引用中没有一个是 "
                        f"classifier 认可的 entity（§17.2.3/§17.3.3；W1R-B）→ " + " | ".join(thin[:6]))
                errors.append(
                    f"IDENTITY_VERIFIED_WITHOUT_QUALIFYING_EVIDENCE|{key} 没有任何一条证据能支撑身份声明"
                    f"（须含实体名称字段 + 经过校验的可区分字段或稳定实体引用；仅 country_code、"
                    f"category、destination_scope，或 provider 根页/搜索页/纯坐标页/垃圾串/未知短链"
                    f"一律不合格）→ " + " | ".join(reasons) + suffix)
            for gate in ("policy_version", "evaluated_at"):  # V1R：resolver_version 不再计入 VERIFIED 门
                if _blank(target.get(gate)):
                    errors.append(f"IDENTITY_VERIFIED_WITHOUT_{gate.upper()}|{key} VERIFIED 必须引用"
                                  f"规则版本与时间，{gate} 为空")
        resolution = str(target.get("google_resolution_status") or "")
        if resolution and resolution != "NOT_OBSERVED":
            observation = target.get("google_observation") or {}
            if _blank(observation.get("environment")) or _blank(observation.get("observed_at")):
                errors.append(f"GOOGLE_OBSERVATION_UNSANCTIONED|{key} google_resolution_status="
                              f"{resolution} 属独立观察结果，必须记录观察环境与时间；正式自动链只能是 "
                              f"NOT_OBSERVED（§17.2.4）")

        # critical targets gate the itinerary, non-critical may degrade honestly
        # v4.2.2 §5.2/§8.3 + 业主 2026-10-29 指令 §5：这两条都是**暴露项**，不是整批阻断；
        # 分类住在 references/map-gate-v422.json，本函数只负责把事实说清楚。
        if str(target.get("criticality")) == "CRITICAL_ITINERARY":
            if str(target.get("identity_status")) != "VERIFIED":
                errors.append(f"CRITICAL_NOT_VERIFIED|{key} 不可替代目标的 identity_status="
                              f"{target.get('identity_status')!r}（v4.2.2 §5.2：不因缺落点核验阻断整份"
                              f"行程，但必须逐项进行程正文与交付报告）")
        errors.extend(_location_role_findings(key, target, policy))

        # names may be judged usable/unusable, never repaired by deleting characters
        display = str(target.get("display_name") or "")
        if display:
            # V1R（清册 §4 禁止动作第 2 条，line 102）：有来源的本地正式名称可以进搜索串，
            # 所以「display_name 含汉字」不再是错误。反删字保障没有放松：占位/数字残片/走廊串
            # 仍然拒绝，且删除字符造出的英文名由 is_manufactured_name 与选择器的残片判定拦住。
            if is_placeholder_name(display, policy) or NUMERIC_RESIDUE_RE.match(display):
                errors.append(f"NAME_PLACEHOLDER|{key} display_name={display[:40]!r} "
                              f"是模板串或数字残留，判为不可用名称")

        # legacy fields are compat reads only and must carry their migration trail
        legacy_present = [field for field in policy.get("map_target_legacy_fields_compat_only") or []
                          if field in target]
        if legacy_present:
            if _blank(target.get("migration")) or _blank((target.get("migration") or {}).get("reason_code")):
                errors.append(f"LEGACY_MIGRATION_UNDOCUMENTED|{key} 仍带旧字段 {legacy_present}，"
                              f"迁移必须保留原值并写 reason_code（§17.2.7）")
            for mapping in policy.get("legacy_migration", {}).get("forbidden_auto_mappings") or []:
                source = mapping.split(" -> ")[0]
                field, _, value = source.partition("=")
                if value and str(target.get(field.strip())) == value.strip() and \
                        str(target.get("identity_status")) == "VERIFIED":
                    errors.append(f"LEGACY_AUTO_MAPPING_FORBIDDEN|{key} 由 {mapping} 推出的 "
                                  f"VERIFIED 不成立")

        # Place ID is optional; a shape-only or unprovenanced ID is quarantined, never required
        place_id = str(target.get("google_place_id") or "").strip()
        if place_id and _blank(target.get("place_id_provenance")):
            errors.append(f"PLACE_ID_UNPROVENANCED_QUARANTINE|{key} 有 Place ID 但无来源说明，"
                          f"须隔离（不是缺失，也不是覆盖率缺陷）")
    return errors
