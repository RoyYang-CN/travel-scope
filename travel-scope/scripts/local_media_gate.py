"""Offline file/manifest gates. Recorded human review is not independently proven.

v4.2.2 R3（业主 2026-11-03 裁 finding_4 选 A）：来源身份核验改读**验证快照**，本模块顶层不再导入
requests——网络只在显式导出快照那一趟（--export-source-snapshot）里由生产者函数内部延迟导入。
这样生成期与门禁期任何一处想「顺手回源」都会撞 NameError，而不是安静地发一个请求把正式构建判红。
"""
import base64
import hashlib
import argparse
import json
import re
import math
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import urllib.parse
from PIL import Image

MEDIA_POLICY = json.loads((Path(__file__).resolve().parents[1] / "references/media-policy.json").read_text(encoding="utf-8"))

# v4.2.2 V5-A（V0-L17）：媒体审计报告也是一次门禁结论，必须带产出者身份。
try:
    import gate_producer
except ImportError:  # pragma: no cover
    import scripts.gate_producer as gate_producer

# v4.2.2 V6-C：交付档与交付预算只在 single-file-delivery-policy.json 里，这里按同一登记复核。
try:
    import single_file_policy
except ImportError:  # pragma: no cover
    import scripts.single_file_policy as single_file_policy

PRODUCING_CODE = ('scripts/local_media_gate.py', 'scripts/gate_producer.py',
                  'scripts/image_assets.py', 'scripts/single_file_policy.py')
PRODUCING_CONFIG = ('references/media-policy.json',
                    'references/single-file-delivery-policy.json')

MODULE_CATEGORIES = {
    'hotels': 'accommodation', 'restaurants': 'food', 'cafes': 'food',
    'attractions': 'sights', 'dive_sites': 'sights',
}

# §5.4.3: how far a delivered picture may drift from its source aspect ratio before it counts as
# distorted. 2% absorbs integer rounding on a resize; the 1000x650 squash was 460%.
ASPECT_TOLERANCE = 0.02


def _url_path(value) -> str:
    """身份比较只看规范化后的路径：去 query／fragment、百分号解码、域名小写。

    实拍依据（SOURCE_VERIFICATION_SURVEY.json）：清单里 `File:Bohol%27s_Chocolate_Hills.jpg`
    与 API 返回的同一页面写法不同（%27 与 '）；不归一就会把「同一个页面」判成身份不符——
    那是尺子坏，不是数据坏。域名或路径段真的不同仍然会报。
    """
    parts = urlsplit(str(value or ""))
    if not parts.netloc and not parts.path:
        return ""
    return parts.netloc.lower() + urllib.parse.unquote(parts.path)


def _same_text(left, right) -> bool:
    """登记文本与 API 文本的比较只归一空白：清单里有个手打的双空格不该被读成「作者换了人」。"""
    return re.sub(r"\s+", " ", str(left or "").strip()) == re.sub(r"\s+", " ", str(right or "").strip())


def _default_local_original(entry: dict) -> str:
    """本地原图的默认位置＝media_prepared/originals/<local_file 文件名>（登记在 media-policy 同一格）。

    生产者与核验者共用这一个函数：路径规则写两遍，就会有一遍先过期。
    """
    name = Path(str(entry.get("local_file") or "")).name
    return (Path("media_prepared") / "originals" / name).as_posix() if name else ""


def commons_asset_rows(manifest: dict) -> list:
    """需要来源身份的资产行——选择规则只有这一处，生产者与核验者共用。"""
    return [entry for entry in manifest.get('assets', [])
            if entry.get('source_provider') == 'wikimedia_commons'
            or entry.get('source_file_title')
            or 'commons.wikimedia.org/' in str(entry.get('source_page'))]


# 登记块里代码必须读到的字段。分两组是因为 historical_revision_addressing_verified 这类格子
# 的合法值就是 False——按「非空」筛会把登记正常的假值读成「登记缺失」，那是尺子坏。
SNAPSHOT_POLICY_KEYS = ("run_manifest_path_field", "snapshot_fields_required", "record_fields_required",
                        "complete_status_value", "max_age_days", "blocking_codes", "api_endpoint",
                        "producer_version", "batch_size", "user_agent", "schema_version_supported",
                        "record_key", "asset_row_id_rule", "lineage_sections", "status_closed_set",
                        "status_meanings", "acquisition_to_prepared_rule", "prepared_to_delivered_replay",
                        "revision_identity_note", "local_original_path_rule", "path_rule",
                        "identity_url_normalization", "identity_text_normalization",
                        "no_original_digest_equality", "authorized_by", "row_key_rule",
                        "request_throttle_seconds", "thumb_width_snapping_measured",
                        # R3D 裁示 1：退避参数与归一参数都必须有登记处，代码里不许留字面量
                        "source_fetch_policy", "acquisition_normalize",
                        # R3E（业主 2026-11-04）：定位符逐字核对的权威字段名单与形状阈值都住登记面
                        "source_url_verbatim_rule", "source_url_query_shape",
                        # R3F（业主 2026-11-04）：可解析路径的 run 相对布局、禁串与豁免名单同样住登记面
                        "run_relative_path_rule")
SNAPSHOT_POLICY_PRESENT_KEYS = ("historical_revision_addressing_verified", "status_unbound_is_blocking",
                                "no_network_in_generation", "no_fallback_to_stale_snapshot",
                                "expiry_clock")
# 采集→prepared 这一跳今天登记两种可离线复算的配方（业主 2026-11-03 R3D 裁示 1）：
# ① 取回档逐字落盘；② 只认 API 给的 thumburl，取回后按登记参数做一次确定性归一。
# 别的写法（自行拼 /1600px-、先下原图再本地缩放却无可复算实现）仍然禁止，必须先量通再入登记。
BRIDGE_RECIPE_NONCE = "COMMONS_RENDITION_STORED_VERBATIM"
BRIDGE_RECIPE_NORMALIZED = "COMMONS_API_THUMB_FETCHED_THEN_NORMALIZED"
BRIDGE_RECIPES = (BRIDGE_RECIPE_NONCE, BRIDGE_RECIPE_NORMALIZED)
BRIDGE_RECIPE_KEY = "transform_recipe"
# 采集字节要在盘上留一份，否则「归一前那一串」只剩摘要、离线复算无从下手。
ACQUISITION_DIR = "media_prepared/acquisitions"


def source_snapshot_policy() -> dict:
    """判据只住 references/media-policy.json::source_verification_snapshot；这里不留内置默认值。"""
    block = MEDIA_POLICY.get("source_verification_snapshot")
    if not isinstance(block, dict):
        raise ValueError("MEDIA_SNAPSHOT_POLICY_UNREGISTERED|references/media-policy.json 里没有 "
                         "source_verification_snapshot 块⇒ 核验没有登记处，代码不许靠自己猜判据继续放行")
    missing = [key for key in SNAPSHOT_POLICY_KEYS if not block.get(key)]
    absent = [key for key in SNAPSHOT_POLICY_PRESENT_KEYS if key not in block]
    if missing or absent:
        raise ValueError("MEDIA_SNAPSHOT_POLICY_INCOMPLETE|登记块缺字段 %s／格子不存在 %s"
                         % (missing, absent))
    unknown = sorted(set(block["blocking_codes"]) - set(SNAPSHOT_BLOCKING_CODES))
    if unknown:
        raise ValueError("MEDIA_SNAPSHOT_POLICY_CODES_UNREGISTERED|登记了代码表里没有的码 %s" % unknown)
    unspoken = sorted(set(SNAPSHOT_BLOCKING_CODES) - set(block["blocking_codes"]))
    if unspoken:
        raise ValueError("MEDIA_SNAPSHOT_POLICY_CODES_UNREGISTERED|代码里有登记面没定义的码 %s"
                         "⇒ 发出去读者查不到这句话是谁说的" % unspoken)
    return block


# ── R3D（业主 2026-11-03 裁「三条来源侧码＋退避参数写进 media-policy，禁止硬编码」）──────────
# 远端答不好（HTTP／429／答体不是 JSON）与本地快照读不成（MEDIA_SNAPSHOT_UNREADABLE）是两件事，
# 混在一句里就会把「Commons 今天没答」写成「我们的账坏了」。次数与预算只住登记面，这里不写字面量。
def source_fetch_policy(policy: dict) -> dict:
    block = policy.get("source_fetch_policy") or {}
    required = ("max_attempts", "max_total_wait_seconds", "retry_after_header",
                "http_error_code", "rate_limited_code", "unreadable_response_code")
    gaps = [key for key in required if not block.get(key)]
    if gaps:
        raise ValueError("MEDIA_SNAPSHOT_POLICY_INCOMPLETE|source_fetch_policy 缺 %s ⇒ 退避没有登记处，"
                         "代码不许自己定次数或秒数" % gaps)
    if int(block["max_attempts"]) < 1 or int(block["max_total_wait_seconds"]) < 1:
        raise ValueError("MEDIA_SNAPSHOT_POLICY_INCOMPLETE|source_fetch_policy 的次数或预算不是正整数")
    return block


def plan_wait(fetch: dict, attempt: int, used_seconds: float, response) -> float:
    """这一次失败后该等多久：先听对端的 Retry-After，再被剩余预算钳住；没有可用头就按剩余预算线性摊。

    对端开 10 万秒也不许真等——预算用完直接断，这是「有界」两个字的含义。
    """
    budget = int(fetch["max_total_wait_seconds"])
    remaining = budget - float(used_seconds)
    if remaining <= 0:
        return 0.0
    header = None
    if response is not None:
        try:
            header = response.headers.get(fetch["retry_after_header"])
        except AttributeError:
            header = None
    try:
        requested = float(header)
    except (TypeError, ValueError):
        attempts = int(fetch["max_attempts"])
        requested = remaining / (attempts * (attempts + 1) / 2.0) * attempt
    return min(max(requested, 0.0), remaining)


def _source_request(session, url, params, policy, *, kind, timeout=60, sleep=None, now=None):
    """带登记退避的取数核心；kind="json" 还要求答体可解析。成功返回 (值, None)，失败返回 (None, 带码的话)。"""
    import time as _clock_module
    fetch = source_fetch_policy(policy)
    attempts = int(fetch["max_attempts"])
    sleeper = sleep or _clock_module.sleep
    clock = now or _clock_module.monotonic
    codes = {"http": str(fetch["http_error_code"]), "rate": str(fetch["rate_limited_code"]),
             "unreadable": str(fetch["unreadable_response_code"])}
    started = clock()
    used = 0.0
    last = ""
    for attempt in range(1, attempts + 1):
        response = None
        try:
            response = (session.get(url, params=params, timeout=timeout) if params is not None
                        else session.get(url, timeout=timeout))
        except Exception as exc:                 # 连不上也是「远端没答好」，不许把 socket 异常冒给调用方
            last = "%s|请求没做成：%s" % (codes["http"], str(exc)[:120])
        if response is not None and response.status_code == 200:
            if kind != "json":
                return response.content, None
            try:
                return response.json(), None
            except Exception as exc:
                last = "%s|2xx 但答体不是可解析 JSON：%s（前 60 字 %r）" % (
                    codes["unreadable"], exc, (getattr(response, "text", "") or "")[:60])
        elif response is not None and response.status_code == 429:
            last = "%s|远端限流 429：%s" % (codes["rate"], (getattr(response, "text", "") or "")[:80])
        elif response is not None:
            last = "%s|远端 HTTP %s：%s" % (codes["http"], response.status_code,
                                          (getattr(response, "text", "") or "")[:80])
        if attempt >= attempts:
            break
        wait = plan_wait(fetch, attempt, used, response)
        if wait <= 0:
            break
        sleeper(wait)
        used += wait
    return None, "%s（登记尝试上限 %d 次／累计等待上限 %d 秒，本趟实际等待 %.1f 秒）⇒ " \
                 "整体中止：不写半份快照、不改正式 run、不回退旧缓存" % (
        last, attempts, int(fetch["max_total_wait_seconds"]), max(clock() - started, used))


def fetch_source_json(session, url, params, policy, **kwargs):
    value, error = _source_request(session, url, params, policy, kind="json", **kwargs)
    if error:
        raise ValueError(error)
    return value


def fetch_source_bytes(session, url, policy, **kwargs):
    value, error = _source_request(session, url, None, policy, kind="bytes", **kwargs)
    if error:
        raise ValueError(error)
    return value


# 代码这边也留一张名字表：登记面写了个永远不会被发出的码，等于给将来的「这条路被走过」留假证据。
SNAPSHOT_BLOCKING_CODES = (
    "MEDIA_SNAPSHOT_PATH_UNDECLARED", "MEDIA_SNAPSHOT_MISSING", "MEDIA_SNAPSHOT_UNREADABLE",
    "MEDIA_SNAPSHOT_SCHEMA_UNSUPPORTED", "MEDIA_SNAPSHOT_FIELD_MISSING", "MEDIA_SNAPSHOT_INCOMPLETE",
    "MEDIA_SNAPSHOT_NOT_COMPLETE", "MEDIA_SNAPSHOT_SELF_DIGEST_MISMATCH",
    "MEDIA_SNAPSHOT_MANIFEST_DIGEST_MISMATCH", "MEDIA_SNAPSHOT_EXPIRED",
    "MEDIA_SNAPSHOT_ASSET_MISSING", "MEDIA_SNAPSHOT_IDENTITY_MISMATCH",
    "MEDIA_SNAPSHOT_LOCAL_DIGEST_MISSING", "MEDIA_SNAPSHOT_DIGEST_CHANGED",
    "MEDIA_SNAPSHOT_SOURCE_DIGEST_CONFLICT",
    # v4.2.2 R3 裁示一：三段行级血缘（业主 2026-11-03 第二轮裁「不接受 identity_plus_local_digest」）
    "MEDIA_SNAPSHOT_ROW_KEY_UNAVAILABLE", "MEDIA_LINEAGE_ROW_UNBOUND",
    "MEDIA_LINEAGE_STATUS_UNREGISTERED", "MEDIA_LINEAGE_SECTION_FIELD_MISSING",
    "MEDIA_LINEAGE_REVISION_IDENTITY_MISSING", "MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING",
    "MEDIA_LINEAGE_DERIVATION_CHAIN_BROKEN", "MEDIA_LINEAGE_DELIVERED_DIGEST_MISMATCH",
    "MEDIA_LINEAGE_TITLE_AGGREGATION_FORBIDDEN", "MEDIA_LINEAGE_HISTORICAL_BOUND_NOT_PROVABLE",
    # v4.2.2 R3D 裁示 1：远端答不好与本地快照读不成是两件事，各给自己的码，不许挤在 MEDIA_SNAPSHOT_UNREADABLE 里
    "MEDIA_SOURCE_HTTP_ERROR", "MEDIA_SOURCE_RATE_LIMITED", "MEDIA_SOURCE_RESPONSE_UNREADABLE",
    # v4.2.2 R3E（业主 2026-11-04 现场复核）：身份路径判据去 query 后只比路径，看不见被追加的第二段追踪查询；
    # 来源定位符要逐字对齐快照，形状自己也要能招供是拼接产物——这两格补的就是那条盲区。
    "MEDIA_SOURCE_URL_NOT_VERBATIM", "MEDIA_SOURCE_URL_QUERY_DUPLICATED",
    "MEDIA_FACE_SOURCE_URL_DIVERGED",
    # v4.2.2 R3F（业主 2026-11-04 窄修复第 4 条）：交付 run 里可解析的路径必须 run 相对且落在 run 根内。
    # 一条要求一条码，各测各的：绝对／反斜杠／指向 run 外（.temp／candidate_runs）／含 ..／
    # 解析后出根／目标文件不在／目标字节与登记摘要不等——混成一条就没法证明坏样本是被自己那条码拦下的。
    "MEDIA_RUN_PATH_EMPTY", "MEDIA_RUN_PATH_ABSOLUTE", "MEDIA_RUN_PATH_SEPARATOR",
    "MEDIA_RUN_PATH_FORBIDDEN_ROOT", "MEDIA_RUN_PATH_TRAVERSES_OUT", "MEDIA_RUN_PATH_OUTSIDE_RUN_ROOT",
    "MEDIA_RUN_PATH_TARGET_MISSING", "MEDIA_RUN_PATH_TARGET_NOT_THE_RECORDED_BYTES",
    "MEDIA_RUN_PATH_LAYOUT_MISMATCH")


def api_payload(value, context: str) -> dict:
    """API 答 200 却带着 error 对象＝答体不是可用响应 ⇒ 归 MEDIA_SOURCE_RESPONSE_UNREADABLE。

    这里绝不用 MEDIA_SNAPSHOT_UNREADABLE：那一码专指「盘上那份快照读不成 JSON」。
    2026-11-03 试点实测抓到一条真缺陷——prop=revisions 带多标题时不许配 rvlimit，
    API 直接回 invalidparammix 的 error 对象，旧代码没检查就往下走，于是每一行的修订号都成了 -1，
    「页是存在的、采集也确实取回了字节」却被记成取不到版本。归因写错，比报错更糟。
    """
    if not isinstance(value, dict):
        raise ValueError("MEDIA_SOURCE_RESPONSE_UNREADABLE|%s 的响应不是 JSON 对象（拿到 %s）⇒ 不能当答复用"
                         % (context, type(value).__name__))
    if "error" in value:
        raise ValueError("MEDIA_SOURCE_RESPONSE_UNREADABLE|%s 的 API 返回错误对象：%s ⇒ 这一趟没有可用答复，"
                         "整体不写快照、不改正式 run、不回退旧缓存"
                         % (context, json.dumps(value["error"], ensure_ascii=False)[:240]))
    return value


def commons_acquisition_probe(session, policy: dict, title: str, requested_width: int,
                              timeout: int) -> tuple[dict, str]:
    """按声明宽度问 API「这一行该从哪个 URL 取字节」——唯一实现，生产者与试点共用，不另写一份。

    只许用 API 自己给的 thumburl（业主 R3D：禁止自行拼 /1600px-...，实测那种写法今天直接 400）。
    返回 (imageinfo 那一格, 采集 URL)；URL 取不到时交回空串，由调用方按登记的规则决定是否回落到原图。
    """
    payload = api_payload(fetch_source_json(session, policy["api_endpoint"], {
        "action": "query", "format": "json", "redirects": "1", "prop": "imageinfo",
        "titles": title, "iiprop": "url|size", "iiurlwidth": requested_width}, policy, timeout=timeout),
        "iiurlwidth 探针(%s)" % title)
    for page in (payload.get("query", {}).get("pages", {}) or {}).values():
        infos = page.get("imageinfo") or [{}]
        thumb = infos[0]
        return thumb, str(thumb.get("thumburl") or "")
    return {}, ""


def commons_page_revision(session, policy: dict, title: str, timeout: int) -> dict:
    """一页一条请求取「这一页的当前修订」：rvlimit 只能配单页，多标题批量在这里是非法组合。"""
    payload = api_payload(fetch_source_json(session, policy["api_endpoint"], {
        "action": "query", "format": "json", "redirects": "1", "prop": "revisions",
        "titles": title, "rvlimit": "1", "rvprop": "ids|timestamp|user"}, policy, timeout=timeout),
        "revisions(%s)" % title)
    for page in payload.get("query", {}).get("pages", {}).values():
        revisions = page.get("revisions") or []
        if revisions:
            return revisions[0]
    return {}


# ── R3B（业主 2026-11-03 裁「采用现有 designed_no_photo_state，不再发明第二套无图机制」）──────
# 表示法与判据的唯一登记处是 references/media-policy.json::designed_no_photo_state。这里只留名字表，
# 因为「登记了却没代码 emit」和「代码 emit 了却没登记」都必须被同一把尺子抓到。
NO_PHOTO_POLICY_KEYS = ("allowed_fields", "reason_code_closed_set", "evidence_field",
                        "field_set_rule", "blocking_codes", "policy_readiness_codes", "dom",
                        "media_gap_rule", "manifest_rule", "forbidden_value_rule")
NO_PHOTO_BLOCKING_CODES = (
    "SECTION_NO_PHOTO_FIELDS_UNREGISTERED", "SECTION_NO_PHOTO_IMAGE_NOT_EMPTY",
    "SECTION_NO_PHOTO_REASON_CODE_UNREGISTERED", "SECTION_NO_PHOTO_EVIDENCE_MISSING",
    "SECTION_NO_PHOTO_IMAGE_SOURCE_PRESENT", "SECTION_NO_PHOTO_ASSET_ROW_PRESENT",
    "SECTION_NO_PHOTO_ROLE_LEVEL_DISAGREE", "SECTION_NO_PHOTO_MEDIA_GAP_CONTRADICTION")
# 登记面自己不成立时报的码：它们说的是「尺子没了」，不是「这行数据不合格」，所以另立一组，
# 但同样要双向核对——测试扫代码行时会把两组并起来比。
NO_PHOTO_POLICY_ERROR_CODES = ("SECTION_NO_PHOTO_POLICY_UNREGISTERED",
                               "SECTION_NO_PHOTO_POLICY_INCOMPLETE",
                               "SECTION_NO_PHOTO_POLICY_CODES_UNREGISTERED")
NO_PHOTO_STATE_VALUE = "designed_no_photo_state"
# 值里出现这些形状就说明该行还在「带一张图」，与键名无关（业主：换个键名继续带旧图路径也是违规）。
IMAGE_VALUE_PATTERNS = ("/", "assets/", "media_prepared/", "renditions/", "data:image")


def no_photo_policy() -> dict:
    """读登记面；缺块、缺字段、码表双向不符都当场抛，不许退回到内置默认判据。"""
    block = MEDIA_POLICY.get("designed_no_photo_state")
    if not isinstance(block, dict):
        raise ValueError("SECTION_NO_PHOTO_POLICY_UNREGISTERED|references/media-policy.json 里没有 "
                         "designed_no_photo_state 块⇒ 无图状态没有登记处，代码不许自己猜表示法")
    missing = [key for key in NO_PHOTO_POLICY_KEYS if not block.get(key)]
    if missing:
        raise ValueError("SECTION_NO_PHOTO_POLICY_INCOMPLETE|登记块缺字段 %s" % missing)
    dom = block["dom"]
    for field in ("attribute", "attribute_value", "visible_label", "carrier_class"):
        if not dom.get(field):
            raise ValueError("SECTION_NO_PHOTO_POLICY_INCOMPLETE|dom 缺字段 %s" % field)
    registered = set(block["blocking_codes"]) | set(block["policy_readiness_codes"])
    implemented = set(NO_PHOTO_BLOCKING_CODES) | set(NO_PHOTO_POLICY_ERROR_CODES)
    unknown = sorted(registered - implemented)
    unspoken = sorted(implemented - registered)
    if unknown or unspoken:
        raise ValueError("SECTION_NO_PHOTO_POLICY_CODES_UNREGISTERED|登记多 %s／代码少 %s"
                         % (unknown, unspoken))
    if NO_PHOTO_STATE_VALUE not in (MEDIA_POLICY.get("selection_levels") or []):
        raise ValueError("SECTION_NO_PHOTO_POLICY_INCOMPLETE|selection_levels 闭集里没有 designed_no_photo_state"
                         "⇒ 词表与表示法分家了")
    return block


def is_no_photo_row(item: dict) -> bool:
    """一行的「正式无图」身份只有一个判法：selection_level 或 asset_role 命中登记值。

    渲染层与门禁都调这里；任何一处自己再写一遍 `== 'designed_no_photo_state'` 就是第二套判据。
    """
    if not isinstance(item, dict):
        return False
    return (str(item.get("selection_level") or "").strip() == NO_PHOTO_STATE_VALUE
            or str(item.get("asset_role") or "").strip() == NO_PHOTO_STATE_VALUE)


def section_slot_denominator(section_media) -> tuple:
    """无图占比的分母＝展开后的 (destination, module) 槽位数，不是「当前声明了几行」。

    登记出处：media-policy.json::designed_no_photo_state.ratio_lock.rule（「删掉一行就能把 10% 洗成 0%」）
    ＋业主 2026-11-04 裁示 B（复用＝一行覆盖多个同类别 module，分母仍是 20 个槽位）。
    以前 formal_data_gate 用 len(section_media) 当分母：三组同类别槽位按裁示 B 合并成一行之后，
    行数 20→17，2 个无图槽位被量成 11.8%，反而「因为做了复用而更像缺图」。
    分子与分母用同一个展开，无图身份仍只由 is_no_photo_row 判——不留第二把尺子。
    """
    slots = no_photo_slots = 0
    for item in section_media or []:
        if not isinstance(item, dict):
            continue
        modules = item.get("modules")
        # 一行至少占一个槽位：没有 modules 元数据的行（夹具、或元数据没写全的行）按 1 计，
        # 不能按 0 计——按 0 计会让「无图但没写模块」的行从分子分母同时消失，把门洗白。
        count = len(modules) if isinstance(modules, (list, tuple)) and modules else 1
        slots += count
        if count and is_no_photo_row(item):
            no_photo_slots += count
    return slots, no_photo_slots


def no_photo_section_slots(section_media: list) -> list[tuple[str, str]]:
    """无图槽位清单（destination, primary_module）——比例锁与 DOM 逐槽位核对都吃这一个口径。"""
    out = []
    for item in section_media or []:
        if is_no_photo_row(item):
            out.append((str(item.get("destination") or ""), str(item.get("primary_module") or "")))
    return out


def _image_bearing_values(item: dict) -> list[str]:
    """字段值里还留着图片字节位置的项（键名无关）。返回「键=值」串供点名。"""
    hits = []
    for key, value in item.items():
        text = str(value if isinstance(value, str) else "") if not isinstance(value, (list, dict)) else ""
        if not text:
            continue
        low = text.strip().lower()
        if (low.startswith(("assets/", "media_prepared/", "http://", "https://", "data:image"))
                or "/renditions/" in low or low.endswith((".jpg", ".jpeg", ".png", ".webp"))):
            hits.append("%s=%s" % (key, text[:80]))
    return hits


def asset_row_id(entry: dict) -> str:
    """行锚＝清单行的 local_file（登记在 asset_row_id_rule）。标题不是锚，它会把三行折叠成一行。"""
    rel = str(entry.get("local_file") or "").strip().replace("\\", "/")
    return rel


def row_anchor_index(rows: list, policy: dict) -> tuple[dict, list]:
    """按行锚建索引；空锚或同锚多行都点名返回，调用方把它们当成阻断而不是「取第一条」。"""
    index: dict = {}
    errors: list[str] = []
    seen: dict = {}
    for entry in rows:
        row_id = asset_row_id(entry)
        seen[row_id] = seen.get(row_id, 0) + 1
    for entry in rows:
        row_id = asset_row_id(entry)
        if not row_id:
            errors.append("MEDIA_SNAPSHOT_ROW_KEY_UNAVAILABLE|清单行 %s（%s）没有可用的 local_file ⇒ "
                          "登记的行锚规则（asset_row_id_rule）取不到值，这一行没有血缘锚"
                          % (entry.get("source_file_title"), policy["record_key"]))
            continue
        if seen[row_id] > 1:
            errors.append("MEDIA_SNAPSHOT_ROW_KEY_UNAVAILABLE|%s 在清单里出现 %d 次 ⇒ 行锚不唯一，"
                          "按锚取哪一条都是猜；猜不出来就不给发布级来源证明" % (row_id, seen[row_id]))
            continue
        index[row_id] = entry
    return index, errors


def prepared_original_file(base_dir, entry: dict) -> Path | None:
    """prepared 档位置：清单行自带的 local_original_path 优先，否则按登记的默认规则推。"""
    rel = str(entry.get("local_original_path") or "") or _default_local_original(entry)
    if base_dir is None or not rel:
        return None
    return Path(base_dir) / rel


def acquisition_file(base_dir, row_id: str) -> Path | None:
    """归一桥那串「归一前字节」在 run 里的位置：<run>/media_prepared/acquisitions/<文件名>。

    业主 R3D 要求采集／prepared／delivered 三段摘要闭合且可离线重放两次——归一这一步在中间，
    不留归一前的字节就只剩一串摘要，谁都复算不了。逐字存盘的桥不需要这份件（prepared 就是它）。
    """
    if base_dir is None or not row_id:
        return None
    return Path(base_dir) / ACQUISITION_DIR / Path(row_id).name


def store_acquisition_bytes(base_dir, row_id: str, blob: bytes) -> Path:
    target = acquisition_file(base_dir, row_id)
    if target is None:
        raise ValueError("MEDIA_SNAPSHOT_LOCAL_DIGEST_MISSING|没有 run 根目录，归一前的采集字节无处可存")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    return target


def _normalize_import():
    try:
        import prepare_media
    except ImportError:                       # 以包路径被调用时（装机件）走这一支
        import scripts.prepare_media as prepare_media   # noqa: F811
    return prepare_media


def bridge_from_acquisition(blob: bytes, declared_width: int, live_prepared: str, policy: dict) -> dict:
    """给「这一行的采集字节」找桥：先试逐字存盘（VERBATIM），不成再按登记参数做一次确定性归一。

    返回 {"recipe", "prepared_sha256", "error"}。找不着桥时错误里带上三段摘要——「差在哪」是判断
    该重派生还是该改登记的第一手依据，口头声称「差不多」不算桥。
    归一的唯一实现是 prepare_media.normalize_acquisition；参数唯一持有人是
    media-policy.json::source_verification_snapshot.acquisition_normalize（这里不留默认值）。
    """
    acquisition_digest = hashlib.sha256(blob).hexdigest().lower()
    if acquisition_digest == str(live_prepared or "").lower():
        return {"recipe": BRIDGE_RECIPE_NONCE, "prepared_sha256": acquisition_digest, "error": ""}
    params = policy.get("acquisition_normalize") or {}
    for key in ("resampling", "quality", "subsampling", "never_upscale"):
        if key not in params:
            raise ValueError("MEDIA_SNAPSHOT_POLICY_INCOMPLETE|acquisition_normalize 缺 %s ⇒ "
                             "归一桥没有登记参数，代码不许自己定" % key)
    try:
        normalized, recipe = _normalize_import().normalize_acquisition(blob, int(declared_width), params)
    except ValueError as exc:
        return {"recipe": "", "prepared_sha256": "", "error": str(exc)}
    digest = hashlib.sha256(normalized).hexdigest().lower()
    full_recipe = "%s|%s" % (BRIDGE_RECIPE_NORMALIZED, recipe)
    if digest != str(live_prepared or "").lower():
        return {"recipe": full_recipe, "prepared_sha256": digest,
                "error": "MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|现取字节 %s 按登记配方归一得 %s，"
                         "在盘 prepared 是 %s ⇒ 这一行今天没有可复算的桥（UNBOUND_LEGACY）："
                         "要么按当前修订重采重派（prepared 与 delivered 一起重建），要么走已登记无图状态，"
                         "不能靠标题相同领别人的血缘"
                         % (acquisition_digest[:16], digest[:16], str(live_prepared)[:16])}
    return {"recipe": full_recipe, "prepared_sha256": digest, "error": ""}


def replay_prepared_from_acquisition(acquisition_blob: bytes, record: dict, entry: dict,
                                     policy: dict) -> tuple[str, str, str]:
    """离线复算第一跳：拿快照记的配方把采集字节再走一遍，看是否得到在盘 prepared。

    返回 (prepared 摘要, 配方, 错误)。配方对不上（比如账上写归一、代码只会逐字存盘）直接抛码。
    """
    recipe = str(_record_field(record, BRIDGE_RECIPE_KEY) or "")
    if recipe == BRIDGE_RECIPE_NONCE:
        digest = hashlib.sha256(acquisition_blob).hexdigest().lower()
        return digest, recipe, ""
    if not recipe.startswith(BRIDGE_RECIPE_NORMALIZED + "|"):
        return "", recipe, ("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|记录的采集→prepared 配方 %r 不在登记闭集 %s 里 ⇒ "
                            "这一跳没有可离线复算的实现" % (recipe[:60], list(BRIDGE_RECIPES)))
    declared = int(entry.get("source_width") or 0)
    result = bridge_from_acquisition(acquisition_blob, declared, str(_record_field(record, "prepared_sha256") or ""),
                                     policy)
    if result["error"]:
        return "", recipe, result["error"]
    if result["recipe"] != recipe:
        return "", recipe, ("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|快照记的归一配方与今天重算的不一致（%r ≠ %r）⇒ "
                            "登记参数或实现变了，这一行的账要重验" % (recipe[:70], result["recipe"][:70]))
    return result["prepared_sha256"], result["recipe"], ""


def replay_delivered_from_prepared(prepared_file: Path, entry: dict, policy: dict) -> tuple[str, str, str]:
    """派生链第二跳的离线重放：用产图那一份实现（登记的 prepared_to_delivered_replay.authority）重算交付档。

    返回 (重放摘要, 重放配方, 错误码)。这里不自己写 PIL 缩放——第二把尺子迟早和第一把漂移，
    漂移的结果就是「门绿着，图却是别的字节」。
    """
    replay = policy["prepared_to_delivered_replay"]
    if str(replay.get("authority") or "") != "scripts/prepare_media.py::prepare_asset":
        return "", "", ("MEDIA_SNAPSHOT_POLICY_INCOMPLETE|登记把重放责任交给了 %r，代码只认 "
                        "scripts/prepare_media.py::prepare_asset 这一份实现⇒ 换实现要人来裁"
                        % replay.get("authority"))
    try:
        import prepare_media
    except ImportError:  # pragma: no cover
        import scripts.prepare_media as prepare_media
    import tempfile
    try:
        slot = prepare_media.slot_for(entry)
        with tempfile.TemporaryDirectory(prefix="media_lineage_replay_") as tmp:
            report = prepare_media.prepare_asset(prepared_file, Path(tmp), slot=slot)
        primary = prepare_media.primary_rendition(report["renditions"])
    except ValueError as exc:
        return "", "", ("MEDIA_LINEAGE_DERIVATION_CHAIN_BROKEN|prepared %s 过不了登记的交付档梯：%s"
                        % (prepared_file.name, str(exc)[:200]))
    return str(primary.get("delivered_sha256") or "").lower(), str(primary.get("transform") or ""), ""


def _digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().lower()


def _source_url_rules(policy: dict) -> tuple:
    """读两块登记；缺格就点名 POLICY_INCOMPLETE，不让它变成 KeyError 或静默放行。"""
    rule = policy.get("source_url_verbatim_rule")
    shape = policy.get("source_url_query_shape")
    if not isinstance(rule, dict) or not isinstance(shape, dict):
        raise ValueError("MEDIA_SNAPSHOT_POLICY_INCOMPLETE|登记面缺 source_url_verbatim_rule 或 "
                         "source_url_query_shape（现在分别=%r／%r）⇒ 定位符核对没有权威口径可执行，"
                         "代码里不许自带内置默认值凑一份" % (rule, shape))
    return rule, shape


def source_url_shape_errors(value, policy: dict, row_id: str, field: str) -> list:
    """定位符自身的形状（业主 2026-11-04 R3E 裁）：第二段查询串自己会招供。

    阈值不住在这段代码里，全部读 media-policy.json::source_url_query_shape；这里只负责按形状判定。
    """
    shape = _source_url_rules(policy)[1]
    text = str(value or "")
    errors: list[str] = []
    if not text:
        return errors
    marks = text.count("?")
    if marks > int(shape["max_query_segments"]):
        errors.append("MEDIA_SOURCE_URL_QUERY_DUPLICATED|%s 的 %s 里 ? 出现 %d 次，登记最多 %d 段 ⇒ "
                      "这一串是被追加出来的（原文：%s）" % (row_id, field, marks,
                                                        int(shape["max_query_segments"]), text[:170]))
        return errors
    if shape["duplicate_param_keys_blocks"] and "?" in text:
        keys = [seg.split("=", 1)[0] for seg in text.split("?", 1)[1].split("&") if seg.strip()]
        dup = sorted({k for k in keys if keys.count(k) > 1})
        if dup:
            errors.append("MEDIA_SOURCE_URL_QUERY_DUPLICATED|%s 的 %s 参数键重复 %s ⇒ "
                          "同一个键出现两次不是来源自己的写法，是拼接留下的痕迹（原文：%s）"
                          % (row_id, field, dup, text[:170]))
    limit = int(shape.get("max_marker_hits", 1))
    for marker in shape["repeat_marker_substrings"]:
        hits = text.count(marker)
        if hits > limit:
            errors.append("MEDIA_SOURCE_URL_QUERY_DUPLICATED|%s 的 %s 里 %r 命中 %d 次，登记上限 %d ⇒ "
                          "追踪查询被写了两遍（原文：%s）" % (row_id, field, marker, hits, limit, text[:170]))
    return errors


def source_url_verbatim_errors(entry: dict, record: dict, policy: dict, row_id: str) -> list:
    """清单 source_asset_url ⇄ 快照 original_url **逐字**相等（业主 2026-11-04 R3E 裁示第 2／4 条）。

    这一条补的是身份判据的盲区：identity_url_normalization 去 query/fragment 只比路径，
    判「是不是同一个 Commons 文件」对，但同一路径上被追加的第二段追踪查询它天生看不见——
    R3D 那 7 行换源就是这个形状，清单两遍 utm、快照一遍，门全绿。
    """
    rule = _source_url_rules(policy)[0]
    field = str(rule["manifest_field"])
    authority_fields = [str(k) for k in rule["authority_fields"]]
    declared = str(entry.get(field) or "")
    authorities = {k: str(_record_field(record, k) or "") for k in authority_fields}
    errors = source_url_shape_errors(declared, policy, row_id, field)
    errors += source_url_shape_errors(entry.get("source_page"), policy, row_id, "source_page")
    if not any(authorities.values()):
        errors.append("MEDIA_LINEAGE_SECTION_FIELD_MISSING|%s 的快照两条权威定位符 %s 全为空 ⇒ "
                      "清单那一格没有可对齐的对象，缺检不等于通过" % (row_id, authority_fields))
    elif declared not in [v for v in authorities.values() if v]:
        errors.append("MEDIA_SOURCE_URL_NOT_VERBATIM|%s 的清单 %s 不逐字等于快照记的任何一条权威定位符："
                      "清单=%s／权威候选=%s ⇒ 身份路径可能仍然相同（那是另一条判据），"
                      "但出货的定位符不是核验过的那一串"
                      % (row_id, field, declared[:150],
                         {k: v[:150] for k, v in authorities.items() if v}))
    return errors


def source_url_face_errors(base_dir, manifest: dict, policy: dict) -> list:
    """派生面孔 ⇄ 根清单的同一格必须逐字相同（业主 R3E 第 3 条：不能手改两份形成第二套来源）。

    这一条管的是「面孔之间」，与快照无关：outputs 那份由构建投影、media_prepared 那份由重派生复制，
    历史上谁都可能带着一份旧定位符出货。缺件也算这一码——缺了当没事就是静悄悄少一格。
    """
    rule = _source_url_rules(policy)[0]
    faces = rule.get("derived_faces") or {}
    if not isinstance(faces, dict) or not faces or base_dir is None:
        return []
    field = str(rule["manifest_field"])
    root_rows = {str(row.get("local_file") or ""): str(row.get(field) or "")
                 for row in (manifest.get("assets") or [])}
    errors: list[str] = []
    for rel in sorted(faces):
        path = Path(base_dir) / rel
        if not path.is_file():
            errors.append("MEDIA_FACE_SOURCE_URL_DIVERGED|%s 不在盘上（登记 derived_faces 点名它）⇒ "
                          "这张面孔没法证明它和根清单同源，缺检不等于通过" % rel)
            continue
        try:
            face = json.loads(path.read_bytes().decode("utf-8"))
        except Exception as exc:
            errors.append("MEDIA_FACE_SOURCE_URL_DIVERGED|%s 读不成 JSON：%s" % (rel, str(exc)[:120]))
            continue
        items = (face.get("assets") if rel.startswith("outputs/") else face.get("entries")) or []
        for item in items:
            row_id = str(item.get("local_file") or "")
            if row_id not in root_rows:
                continue
            declared = str(item.get(field) or "")
            if declared != root_rows[row_id]:
                errors.append("MEDIA_FACE_SOURCE_URL_DIVERGED|%s 行的 %s 在 %s 里是 %s，根清单是 %s ⇒ "
                              "两张面孔指的不是同一个定位符，读哪张出货是两回事"
                              % (row_id, field, rel, declared[:120], root_rows[row_id][:120]))
    return errors


def _run_path_rules(policy: dict) -> dict:
    """读 run_relative_path_rule；缺格就点名 POLICY_INCOMPLETE，代码里不留布局字面量。

    布局（media_prepared/originals/{file}、assets/renditions/{file}）、禁串（.temp／candidate_runs）、
    要判的字段名单、以及摘要配对的字段名，全部住 references/media-policy.json——
    业主 R3F 第 4 条的每一项都要能在登记面指到出处，不然就是「工具自己有一套规则」的第二张面孔。
    """
    rules = policy.get("run_relative_path_rule")
    if (not isinstance(rules, dict) or not isinstance(rules.get("applies_to_faces"), dict)
            or not isinstance(rules.get("must"), dict) or not rules.get("forbid_substrings")):
        raise ValueError("MEDIA_SNAPSHOT_POLICY_INCOMPLETE|登记面缺 run_relative_path_rule（现在=%r）"
                         "⇒ run 内相对路径没有可执行口径；不许在代码里自带 media_prepared/originals "
                         "这类布局凑一份" % (type(rules).__name__,))
    return rules


def _path_shape_errors(text: str, run_root: Path, rules: dict, where: str, field: str) -> list:
    """业主 R3F 第 4 条逐条对应一条码；一条不合格不遮另一条，也不许只报第一条。"""
    must = rules["must"]
    errors: list[str] = []
    if not str(text).strip():
        return ["MEDIA_RUN_PATH_EMPTY|%s 的 %s 是空串 ⇒ 没有定位符就没有字节出处，空串不是豁免"
                % (where, field)]
    raw = str(text)
    posix = raw.replace("\\", "/")
    if must.get("no_drive_letter") and re.match(r"^[A-Za-z]:", posix):
        errors.append("MEDIA_RUN_PATH_ABSOLUTE|%s 的 %s 带盘符：%r ⇒ 这份 run 只在这台机器的这个位置能用"
                      % (where, field, raw[:120]))
    elif must.get("no_leading_slash") and posix.startswith("/"):
        errors.append("MEDIA_RUN_PATH_ABSOLUTE|%s 的 %s 是前导 / 的绝对路径：%r" % (where, field, raw[:120]))
    if must.get("posix_separators") and "\\" in raw:
        errors.append("MEDIA_RUN_PATH_SEPARATOR|%s 的 %s 用反斜杠分隔：%r ⇒ 值是本机拼出来的，"
                      "不是 run 内可移植的定位符" % (where, field, raw[:120]))
    for needle in rules.get("forbid_substrings") or []:
        if str(needle).lower() in posix.lower():
            errors.append("MEDIA_RUN_PATH_FORBIDDEN_ROOT|%s 的 %s 含登记禁串 %r：%r ⇒ 指向 run 外的另一棵树，"
                          "今天能解析只因为旧目录还在本机" % (where, field, needle, raw[:120]))
    if must.get("no_parent_traversal") and ".." in posix.split("/"):
        errors.append("MEDIA_RUN_PATH_TRAVERSES_OUT|%s 的 %s 含 .. 段：%r ⇒ 写法自己承认要跳出 run 根"
                      % (where, field, raw[:120]))
    return errors


def inside_run_root(target: Path, root: Path) -> bool:
    """解析后是否仍落在 run 根内（业主 R3F 第 4 条最后一项）。

    单独一把尺子是因为「没有 ..」不等于「在里面」：符号链接／junction 能把相对值指到根外，
    而复制走的那份 run 里根本没有那一头——今天能读、换机就断，正是本轮要拦的形状。
    """
    try:
        Path(target).resolve().relative_to(Path(root).resolve())
        return True
    except Exception:
        return False


def resolve_run_path(value, run_root: Path) -> Path:
    """读侧解析（gen_travel_scope／delivery_gate 用这一把尺子，不各写一份）。

    相对值按 run 根解析；绝对值照旧返回——这是**读取兼容**，不是放行：run_relative_path_rule
    的 reader_tolerance 登记了理由（菲律宾正式 run 与 candidate run 仍带绝对路径，本轮不动它们，
    读侧硬拒绝会把「那条 run 今天什么形状」改成另一件事）。阻断出货的是 run_path_containment_errors。
    """
    text = str(value or "")
    posix = text.replace("\\", "/")
    if re.match(r"^[A-Za-z]:", posix) or posix.startswith("/"):
        return Path(posix)
    return Path(run_root) / posix


def _field_path_parts(expr: str) -> list:
    return [p for p in re.split(r"\[\]\.", str(expr)) if p]


def _collect_by_expr(node, parts: list) -> list:
    """按登记点名的字段路径取标量：["entries","source"] 或 ["entries","renditions","relpath"]。

    路径由登记面写、这里按结构走，不用正则去猜 JSON 里的键——「扫了个空」和「扫到但合格」
    必须能分开，所以返回三元组里带上持有该格的 dict 与最近一层带 local_file 的行 dict。
    """
    found: list = []

    def rec(cur, idx, row):
        if idx >= len(parts) or not isinstance(cur, dict):
            return
        key = parts[idx]
        leaf = idx == len(parts) - 1
        row_now = cur if cur.get("local_file") else row
        value = cur.get(key)
        if leaf:
            if isinstance(value, str):
                found.append((cur, row_now, value))
            elif key not in cur:
                found.append((cur, row_now, ""))       # 缺格也算空定位符：没有这一格就没有字节出处
            return
        if isinstance(value, list):
            for item in value:
                rec(item, idx + 1, row_now)

    rec(node, 0, None)
    return found


def run_path_face_layout(policy: dict | None = None, face_rel: str = "media_prepared/media-manifest.json",
                         field: str | None = None):
    """把登记的布局模板交出去（生产者与门共用一份，谁都不许自己抄一遍字面量）。

    field=None 返回该面孔的全部 {字段路径: 模板}；给了 field 就返回那一格的模板字符串。
    """
    rules = _run_path_rules(policy or source_snapshot_policy())
    faces = rules["applies_to_faces"]
    spec = faces.get(face_rel)
    if not isinstance(spec, dict) or not isinstance(spec.get("fields"), (dict, list)):
        raise ValueError("MEDIA_SNAPSHOT_POLICY_INCOMPLETE|run_relative_path_rule.applies_to_faces 里"
                         "没有 %r 或它没有 fields（现在=%r）" % (face_rel, spec))
    fields = spec["fields"]
    if field is None:
        return dict(fields) if isinstance(fields, dict) else list(fields)
    if not isinstance(fields, dict) or field not in fields:
        raise ValueError("MEDIA_SNAPSHOT_POLICY_INCOMPLETE|%s 的字段 %r 不在登记布局里（登记=%s）"
                         % (face_rel, field, sorted(fields)))
    return str(fields[field])


def run_path_containment_errors(base_dir, policy: dict, run_manifest: dict | None = None,
                                faces: dict | None = None) -> tuple:
    """判「交付 run 里可解析的路径必须 run 相对且落在 run 根内」（业主 R3F 第 4／6 条）。

    逐格收集，一条都不折：26 条 candidate_runs 绝对 source、1 条空 source、27 条 .temp relpath
    要各自被点名，否则「7 行折成一条 abort 文本」那种点名失败会在这里重演。
    面孔缺件不在这条码里——media_prepared/media-manifest.json 与 outputs/asset-manifest.json
    的存在性由 R3E 的 source_url_verbatim_rule.derived_faces 那条门管（缺了就报
    MEDIA_FACE_SOURCE_URL_DIVERGED），这里只判已在盘面孔里的路径形状。
    """
    rules = _run_path_rules(policy)
    if base_dir is None:
        return [], {"run_path_faces_scanned": 0, "run_path_fields_checked": 0,
                    "run_path_findings": 0, "note": "没给 base_dir：无法按 run 根判相对，本格不计通过"}
    root = Path(base_dir)
    errors: list[str] = []
    checked = 0
    scanned = 0
    identity = rules.get("byte_identity") or {}
    digest_field_by_leaf = {str(parts[-1]): str(identity.get(f) or "")
                            for parts, f in ((["entries", "source"], "source_digest_field"),
                                             (["entries", "renditions", "relpath"], "relpath_digest_field"))}
    supplied = set(faces or {})
    if isinstance(run_manifest, dict):
        # 调用方把 run 自己的输入声明当对象交进来时，它也算「交给你的那张面孔」；
        # 否则下面那道人写的过滤会把 manifest.json 先跳过，run_manifest 参数形同虚设。
        supplied.add("manifest.json")
    for face_rel in sorted(rules["applies_to_faces"]):
        if faces is not None and face_rel not in supplied:
            continue          # 调用方给了 faces＝「只判我交给你的这几张面孔」：生产者写自己那张时，
                              # 不该被另一张还没改过的面孔挡住（整 run 的复判由门在落盘后再跑一遍）。
        spec = rules["applies_to_faces"][face_rel] or {}
        face_path = root / str(face_rel).replace("\\", "/")
        scanned += 1
        if str(face_rel) == "manifest.json":
            face = (faces or {}).get(face_rel)
            if not isinstance(face, dict):
                face = run_manifest if isinstance(run_manifest, dict) else (
                    json.loads(face_path.read_bytes().decode("utf-8")) if face_path.is_file() else None)
            if face is None:
                continue
            for field in spec.get("fields") or []:
                checked += 1
                value = str(face.get(field) or "")
                shape = _path_shape_errors(value, root, rules, "manifest.json", field)
                if shape:
                    errors += shape
                    continue
                posix = value.replace("\\", "/")
                target = root / posix
                if not target.is_file():
                    errors.append("MEDIA_RUN_PATH_TARGET_MISSING|manifest.json 的 %s=%r 在 run 内没有这个文件"
                                  " ⇒ 构建与交付门就从这一格取输入，换机即断" % (field, posix[:120]))
                elif not inside_run_root(target, root):
                    errors.append("MEDIA_RUN_PATH_OUTSIDE_RUN_ROOT|manifest.json 的 %s=%r 解析后落在 run 根外"
                                  % (field, posix[:120]))
            continue
        provided = (faces or {}).get(face_rel)
        if provided is not None:
            face = provided          # 生产者写盘之前先用同一把尺子判内存里那份，不留下半成品
        elif not face_path.is_file():
            continue
        else:
            try:
                face = json.loads(face_path.read_bytes().decode("utf-8"))
            except Exception as exc:
                errors.append("MEDIA_RUN_PATH_ABSOLUTE|%s 读不成 JSON：%s ⇒ 形状判不了，不能当通过"
                              % (face_rel, str(exc)[:120]))
                continue
        fields = spec.get("fields") or {}
        for expr in sorted(fields):
            parts = _field_path_parts(expr)
            template = str(fields[expr] or "")
            hits = _collect_by_expr(face, parts)
            if not hits:
                errors.append("MEDIA_RUN_PATH_EMPTY|%s 里没有任何格走到登记路径 %r ⇒ 门扫了个空，"
                              "等于没验；面孔形状换了要人来裁，不许静默通过" % (face_rel, expr))
                continue
            for (owner, row, value) in hits:
                checked += 1
                where = "%s 的 %s（行 %s）" % (face_rel, expr, (row or {}).get("local_file") or "(无行名)")
                shape = _path_shape_errors(value, root, rules, where, expr)
                if shape:
                    errors += shape
                    continue
                posix = value.replace("\\", "/")
                if rules["must"].get("layout_template_must_match") and template:
                    want = template.replace("{file}", posix.split("/")[-1])
                    if posix != want:
                        errors.append("MEDIA_RUN_PATH_LAYOUT_MISMATCH|%s=%r 不在登记点名的位置 %r ⇒ "
                                      "字节在 run 里的哪儿也是合同，下一个人按登记找实物"
                                      % (where, posix[:120], want))
                        continue
                target = root / posix
                if not target.is_file():
                    errors.append("MEDIA_RUN_PATH_TARGET_MISSING|%s=%r 在 run 内没有这个文件 ⇒ "
                                  "本机 dangling=0 不能替代跨目录可解析" % (where, posix[:120]))
                    continue
                if not inside_run_root(target, root):
                    errors.append("MEDIA_RUN_PATH_OUTSIDE_RUN_ROOT|%s=%r 解析后落在 run 根外"
                                  % (where, posix[:120]))
                    continue
                digest_field = digest_field_by_leaf.get(parts[-1], "")
                recorded = str(owner.get(digest_field) or "") if digest_field else ""
                if recorded:
                    actual = hashlib.sha256(target.read_bytes()).hexdigest()
                    if actual.lower() != recorded.lower():
                        errors.append("MEDIA_RUN_PATH_TARGET_NOT_THE_RECORDED_BYTES|%s=%r 解析到的字节摘要 "
                                      "%s…≠该行登记的 %s %s… ⇒ 改路径时把字节也换了"
                                      % (where, posix[:120], actual[:12], digest_field, recorded[:12]))
    return errors, {"run_path_faces_scanned": scanned,
                    "run_path_fields_checked": checked, "run_path_findings": len(errors)}


def to_run_relative_path(value, run_root, *, field: str = "", rules: dict | None = None) -> str:
    """把运行期／历史遗留的绝对路径收敛成 run 相对 POSIX（业主 R3F 第 5 条的唯一转换器）。

    先收敛再判形状：绝对值里带盘符／反斜杠本来就是「改之前的病」，如果拿这些病先拒绝，
    就没有任何东西能被修好。所以这里只判**收敛之后的结果**——它必须是纯 POSIX 相对、
    不含登记禁串、不含 ..，并且解析后仍在 run 根内。落在 run 外的实物不「凑」成相对值，
    直接 MEDIA_RUN_PATH_OUTSIDE_RUN_ROOT 阻断：把外面的字节说成 run 内的实物，
    比留一个绝对路径更糟——后者至少说实话。
    """
    root = Path(run_root).resolve()
    if rules is None:
        rules = _run_path_rules(source_snapshot_policy())
    text = str(value or "")
    where = "to_run_relative_path(%s)" % (field or "路径")
    if not text.strip():
        raise ValueError("MEDIA_RUN_PATH_EMPTY|%s 的 %s 是空串 ⇒ 空格不能被「相对化」变出一个实物"
                         % (where, field or "路径"))
    posix = text.replace("\\", "/")
    if re.match(r"^[A-Za-z]:", posix) or posix.startswith("/"):
        target = Path(posix).resolve()
        try:
            relative = target.relative_to(root).as_posix()
        except Exception:
            raise ValueError("MEDIA_RUN_PATH_OUTSIDE_RUN_ROOT|%s 的值 %r 解析后是 %s，不在 run 根 %s 之内 ⇒ "
                             "这份字节不属于本 run，不能靠相对化算作它的实物"
                             % (where, posix[:160], str(target).replace("\\", "/")[:160],
                                str(root).replace("\\", "/")))
    else:
        relative = posix
    shape = _path_shape_errors(relative, root, rules, where, field or "路径")
    if shape:
        raise ValueError("; ".join(shape))
    if not inside_run_root(root / relative, root):
        raise ValueError("MEDIA_RUN_PATH_OUTSIDE_RUN_ROOT|%s 收敛成 %r 之后解析仍出 run 根"
                         % (where, relative))
    return relative


def reroot_into_run(value, run_root: Path, *, field: str = "", exc: str = "") -> str:
    """把指向 run 外的绝对声明改指到 run 内那份**逐字节相同**的实物上。

    唯一的找法：同文件名 + 同摘要，且在 run 内唯一。两份都同名同摘要（例如根清单与构建投影
    恰好等字节）时报歧义而不是随便挑一份——挑错就等于把输入指到另一张面孔上。
    """
    outside = Path(str(value).replace("\\", "/"))
    if not outside.is_file():
        raise ValueError(exc)
    digest = hashlib.sha256(outside.read_bytes()).hexdigest().upper()
    name = outside.name
    hits = [p for p in Path(run_root).rglob(name)
            if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest().upper() == digest]
    if not hits:
        raise ValueError("MEDIA_RUN_PATH_TARGET_MISSING|%s 指向 run 外（%s），而本 run 内没有逐字节相同的 %r "
                         "⇒ 先把它落进 run 再改声明，指着一台机器上的别处不算自包含"
                         % (field or "路径", str(value)[:120], name))
    if len(hits) > 1:
        raise ValueError("MEDIA_RUN_PATH_LAYOUT_MISMATCH|本 run 里有 %d 份与 %r 同名的相同字节：%s ⇒ "
                         "选哪份都是猜，先让登记唯一" % (len(hits), name,
                                                    [str(h.relative_to(run_root)).replace("\\", "/")
                                                     for h in hits[:6]]))
    return hits[0].resolve().relative_to(Path(run_root).resolve()).as_posix()


def run_manifest_relative_face(run_root, run_manifest: dict, policy: dict | None = None) -> dict:
    """把 run 自己的输入声明（manifest.json 那几格）收敛成 run 相对，并逐格核实物。

    只改登记点名的字段；seal／seal_history／generation_command／derived_from 那几格是
    「那一次跑的记录」，按登记的 record_exempt 原样留着。收敛前后必须还是同一份字节：
    旧绝对值若还在盘上，先量它的摘要，与新指向的 run 内实物比对，不等就阻断——
    「改路径」与「换了输入」不能混在一次写入里。返回新字典，不改调用方的对象。
    """
    rules = _run_path_rules(policy or source_snapshot_policy())
    fields = None
    for face_rel, spec in (rules.get("applies_to_faces") or {}).items():
        if str(face_rel) == "manifest.json":
            fields = (spec or {}).get("fields") or []
    if not fields:
        raise ValueError("MEDIA_SNAPSHOT_POLICY_INCOMPLETE|登记没有 manifest.json 的字段名单，"
                         "输入声明这一孔没有口径可执行")
    out = json.loads(json.dumps(run_manifest, ensure_ascii=False))
    rewritten = {}
    for field in fields:
        current = str(out.get(field) or "")
        if not current:
            continue
        try:
            relative = to_run_relative_path(current, run_root, field="manifest.json::%s" % field,
                                            rules=rules)
        except ValueError as exc:
            if not str(exc).startswith("MEDIA_RUN_PATH_OUTSIDE_RUN_ROOT|"):
                raise
            # 绝对值指向别的树（本 run 复制自哪儿、上一轮的临时工作区在哪儿）时不硬判「在外面」就完事：
            # 本 run 里可能本来就有一份逐字节相同的实物——找到它、验摘要、改指它，这才叫自包含。
            # 找不到或有二义就照原样阻断；「指哪儿」这一步永远要有摘要证据，不许靠同名猜。
            relative = reroot_into_run(current, Path(run_root), field=field, exc=str(exc))
        target = Path(run_root) / relative
        if not target.is_file():
            raise ValueError("MEDIA_RUN_PATH_TARGET_MISSING|manifest.json 的 %s 改写后是 %r，"
                             "run 内没有这个文件 ⇒ 声明不能指到没落进 run 的字节" % (field, relative))
        if not inside_run_root(target, Path(run_root)):
            raise ValueError("MEDIA_RUN_PATH_OUTSIDE_RUN_ROOT|manifest.json 的 %s 改写后 %r 仍不在 run 根内"
                             % (field, relative))
        old_target = Path(current.replace("\\", "/"))
        same_bytes = None
        if old_target.is_file():
            old_digest = hashlib.sha256(old_target.read_bytes()).hexdigest().upper()
            new_digest = hashlib.sha256(target.read_bytes()).hexdigest().upper()
            if old_digest != new_digest:
                raise ValueError("MEDIA_RUN_PATH_TARGET_NOT_THE_RECORDED_BYTES|manifest.json 的 %s 从 %r 收敛到 "
                                 "%r 时指的字节也变了（%s… vs %s…）⇒ 一次写入只能改路径"
                                 % (field, current[:120], relative, old_digest[:12], new_digest[:12]))
            same_bytes = old_digest
        rewritten[field] = {"to": relative,
                            "was_absolute": bool(re.match(r"^[A-Za-z]:", current.replace("\\", "/"))
                                                 or current.startswith("/")),
                            "same_bytes_verified": same_bytes is not None}
        out[field] = relative
    out["run_relative_paths_2026_11_04"] = {
        "authority": "references/media-policy.json::source_verification_snapshot.run_relative_path_rule",
        "rewritten": rewritten,
        "before_values_live_in": "见本轮证据件 .temp/v422_honest_map/ZH_RELEASE_3/"
                                 "R3F_RUN_PATH_FIX_applied.json（那是登记本，不是 run 内的实物指针）",
        "not_rewritten_note": "seal／seal_history／generation_command／derived_from 等格是"
                              "「那一次运行的真实记录」，按登记的 record_exempt 保持原样"}
    return out


def _row_identity_errors(entry: dict, record: dict, policy: dict, row_id: str) -> list:
    """第一段：清单声明的身份 ⇄ 快照记的 Commons 修订身份，逐行比，标题不参与聚合。"""
    errors: list[str] = []
    title = str(entry.get("source_file_title") or "")
    if not title.startswith("File:"):
        errors.append("MEDIA_LINEAGE_REVISION_IDENTITY_MISSING|%s（%s）的清单来源不是精确 File: 标题（现为 %r）"
                      "⇒ 精确标题是身份核验的分母，模糊标题进不了血缘" % (row_id, title, title))
    if not _same_text(record.get("source_file_title"), title):
        errors.append("MEDIA_LINEAGE_REVISION_IDENTITY_MISSING|%s 的标题快照=%r 清单=%r" % (row_id, record.get("source_file_title"), title))
    for label, rec_key, row_key in (("pageid", "source_page_id", "source_page_id"),):
        try:
            same = int(_record_field(record, rec_key)) == int(entry.get(row_key, -2))
        except (TypeError, ValueError):
            same = False
        if not same:
            errors.append("MEDIA_LINEAGE_REVISION_IDENTITY_MISSING|%s 的 %s 快照=%r 清单=%r"
                          "⇒ 修订身份指认的不是同一个页面" % (row_id, label, record.get(rec_key), entry.get(row_key)))
    for label, rec_key, row_key in (("作者", "author", "author"), ("许可", "license_short_name", "license")):
        if not _same_text(record.get(rec_key), entry.get(row_key)):
            errors.append("MEDIA_SNAPSHOT_IDENTITY_MISMATCH|%s 的%s 快照=%r 清单=%r"
                          "⇒ 授权面在核验之后变过（或从来就是错的），这一行要重新采集并重新登记"
                          % (row_id, label, record.get(rec_key), entry.get(row_key)))
    allowed_paths = {_url_path(record.get("source_page_url")), _url_path(record.get("original_url"))}
    allowed_paths.discard("")
    declared_paths = {"source_page": _url_path(entry.get("source_page")),
                      "source_asset_url": _url_path(entry.get("source_asset_url"))}
    for field, path in sorted(declared_paths.items()):
        # 两个声明各判各的。以前写的是「任一对得上就放行」，于是把 source_asset_url 落到另一份文件
        # （清单里 /4/4e/ 而 Commons 现取是 /c/ce/）的那一行，靠同一行里那条正确的 source_page
        # 蒙了过去——Twin Peaks 酒店行就是这个形状，所以「任一对得上」本身就是漏检。
        if path and allowed_paths and path not in allowed_paths:
            errors.append("MEDIA_SNAPSHOT_IDENTITY_MISMATCH|%s 的清单 %s=%s 不属于快照记的 Commons 身份路径 %s"
                          "⇒ 同标题不同文件（或不同命名空间）是在这一行上被抓出来的，不是被别的行盖掉的"
                          % (row_id, field, path, sorted(allowed_paths)))
    errors += source_url_verbatim_errors(entry, record, policy, row_id)
    return errors


def _row_lineage_errors(entry: dict, record: dict, policy: dict, row_id: str, base_dir) -> list:
    """第二、三段：采集桥梁与派生链，逐行复算在盘字节。"""
    errors: list[str] = []
    # 第二段接第三段的第一跳有两条合法桥（业主 2026-11-03 R3D 裁「允许 API 返回 1920 后本地确定性归一」）：
    # 逐字桥上采集摘要＝prepared 摘要；归一桥上这两个数本来就该不等，差额由「归一前那串字节」的复算来担保。
    acquisition = str(_record_field(record, "acquisition_sha256") or "").lower()
    prepared_claim = str(_record_field(record, "prepared_sha256") or "").lower()
    delivered_claim = str(_record_field(record, "delivered_sha256") or "").lower()
    recipe = str(_record_field(record, BRIDGE_RECIPE_KEY) or "")
    normalized_bridge = recipe.startswith(BRIDGE_RECIPE_NORMALIZED + "|")
    if recipe != BRIDGE_RECIPE_NONCE and not normalized_bridge:
        errors.append("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|%s 的采集→prepared 配方=%r，登记只认 %s 及其归一展开式 ⇒ "
                      "这一跳没有可离线复算的实现，不能口头声称字节来自那一版"
                      % (row_id, recipe[:70], list(BRIDGE_RECIPES)))
    if not normalized_bridge and acquisition and prepared_claim and acquisition != prepared_claim:
        errors.append("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|%s 采集摘要 %s 与 prepared 摘要 %s 不等 ⇒ "
                      "在盘那份不是这一趟取回的字节" % (row_id, acquisition[:16], prepared_claim[:16]))
    declared_source = str(entry.get("source_sha256") or "").lower()
    if prepared_claim and declared_source and prepared_claim != declared_source:
        errors.append("MEDIA_SNAPSHOT_SOURCE_DIGEST_CONFLICT|%s 清单声明 prepared=%s，快照记 %s ⇒ "
                      "清单与血缘账指的是两份字节" % (row_id, declared_source[:16], prepared_claim[:16]))
    prepared_file = prepared_original_file(base_dir, entry)
    if prepared_file is None or not prepared_file.is_file():
        errors.append("MEDIA_SNAPSHOT_LOCAL_DIGEST_MISSING|%s 的 prepared 档 %s 不在盘上 ⇒ "
                      "采集桥梁与派生链都无从复算，缺检不等于通过"
                      % (row_id, prepared_file if prepared_file else "(没给相对路径)"))
        return errors
    live_prepared = _digest_of(prepared_file)
    if prepared_claim and live_prepared != prepared_claim:
        errors.append("MEDIA_SNAPSHOT_DIGEST_CHANGED|%s 的 prepared %s 现算 %s，快照记 %s ⇒ "
                      "在盘字节与验过的那份不是同一份" % (row_id, prepared_file.name, live_prepared[:16],
                                                       prepared_claim[:16]))
    if normalized_bridge:
        artifact = acquisition_file(base_dir, row_id)
        if artifact is None or not artifact.is_file():
            errors.append("MEDIA_SNAPSHOT_LOCAL_DIGEST_MISSING|%s 记的是归一桥，但盘上没有归一前的采集字节"
                          "（应在 %s/%s）⇒ 三段里最前面那段只剩一个数，离线复算无从下手"
                          % (row_id, ACQUISITION_DIR, Path(row_id).name))
        else:
            artifact_digest = _digest_of(artifact)
            if acquisition and artifact_digest != acquisition:
                errors.append("MEDIA_SNAPSHOT_DIGEST_CHANGED|%s 的采集字节现算 %s，快照记 %s ⇒ "
                              "归一前那串字节被换过，后面的 prepared 就不是这一趟取回的派生"
                              % (row_id, artifact_digest[:16], acquisition[:16]))
            replay_digest, _replay_recipe, replay_error = replay_prepared_from_acquisition(
                artifact.read_bytes(), record, entry, policy)
            if replay_error:
                errors.append("%s|%s" % (row_id, replay_error))
            elif live_prepared != replay_digest:
                errors.append("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|%s 按登记归一配方从采集字节重算得 %s，"
                              "在盘 prepared 是 %s ⇒ 归一这一步今天复算不出来（登记参数或实现与验过的那次不同）"
                              % (row_id, replay_digest[:16], live_prepared[:16]))
    elif acquisition and live_prepared != acquisition:
        errors.append("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|%s 的 prepared 现算 %s ≠ 采集摘要 %s ⇒ "
                      "「从 Commons 取回的那串字节」和「盘上这串字节」之间没有桥"
                      % (row_id, live_prepared[:16], acquisition[:16]))
    # 采集声明的形状 ⇄ 实物形状：取回的宽高必须是那批字节真的是那个宽高。
    for key in ("returned_width", "returned_height"):
        try:
            int(_record_field(record, key))
        except (TypeError, ValueError):
            errors.append("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|%s 的 %s=%r 不是整数 ⇒ "
                          "采集记录没把自己取回的东西说清" % (row_id, key, record.get(key)))
    try:
        from PIL import Image as _Image
        with _Image.open(prepared_file) as img:
            live_size = (int(img.width), int(img.height))
    except Exception as exc:
        errors.append("MEDIA_SNAPSHOT_LOCAL_DIGEST_MISSING|%s 的 prepared %s 打不开量不了尺寸：%s"
                      % (row_id, prepared_file.name, str(exc)[:120]))
        live_size = None
    if live_size:
        # 归一桥上 returned_* 描述的是「取回那一档的实物」（比如 1920），不是归一后的 prepared（比如 1600）；
        # 逐字桥上两者本来就是同一串字节。拿 prepared 去核对归一桥的采集账＝把合法派生判成缺陷（R3D-P2 实跑到才抓到）。
        compare_size, compare_label = live_size, "prepared 实物"
        if normalized_bridge:
            artifact = acquisition_file(base_dir, row_id)
            if artifact is None or not artifact.is_file():
                compare_size, compare_label = None, "采集实物（不在盘上，已在本段前面点名）"
            else:
                try:
                    with _Image.open(artifact) as acquired_image:
                        compare_size = (int(acquired_image.width), int(acquired_image.height))
                    compare_label = "采集实物"
                except Exception as exc:
                    errors.append("MEDIA_SOURCE_RESPONSE_UNREADABLE|%s 的采集件 %s 打不开量不了尺寸：%s"
                                  % (row_id, artifact.name, str(exc)[:120]))
                    compare_size = None
        if compare_size:
            for key, idx in (("returned_width", 0), ("returned_height", 1)):
                value = _record_field(record, key)
                if value in (None, "") or int(value) == compare_size[idx]:
                    continue
                if compare_label == "prepared 实物":
                    errors.append("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|%s 记的 %s=%s 与 prepared 实物 %dx%d 不符"
                                  "⇒ 采集账描述的字节与在盘字节不同" % (row_id, key, value, *compare_size))
                else:
                    errors.append("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|%s 记的 %s=%s 与采集实物 %dx%d 不符"
                                  "（归一后的 prepared 是 %dx%d，那是两件事）⇒ 采集账对不上自己取回的那一档"
                                  % (row_id, key, value, *compare_size, *live_size))
    # 第三段：交付字节 ⇄ 派生链重放。四份摘要必须逐字相同。
    delivered_file = Path(base_dir) / row_id if base_dir else None
    if delivered_file is None or not delivered_file.is_file():
        errors.append("MEDIA_SNAPSHOT_LOCAL_DIGEST_MISSING|%s 的交付档 %s 不在盘上 ⇒ 无法复算派生链末端"
                      % (row_id, row_id))
        return errors
    live_delivered = _digest_of(delivered_file)
    claimed = str(entry.get("delivered_sha256") or "").lower()
    if delivered_claim and claimed and delivered_claim != claimed:
        errors.append("MEDIA_LINEAGE_DELIVERED_DIGEST_MISMATCH|%s 快照记 delivered=%s，清单记 %s ⇒ "
                      "验的与出货的不是同一份" % (row_id, delivered_claim[:16], claimed[:16]))
    if live_delivered != delivered_claim:
        errors.append("MEDIA_LINEAGE_DELIVERED_DIGEST_MISMATCH|%s 的交付档现算 %s，快照记 %s ⇒ "
                      "读者拿到的是没被血缘验过的那串字节" % (row_id, live_delivered[:16], delivered_claim[:16]))
    replay_digest, replay_transform, replay_error = replay_delivered_from_prepared(
        prepared_file, entry, policy)
    if replay_error:
        errors.append(replay_error)
    else:
        if replay_digest and replay_digest != live_delivered:
            errors.append("MEDIA_LINEAGE_DERIVATION_CHAIN_BROKEN|%s 从 prepared 重放交付档得 %s，在盘是 %s ⇒ "
                          "这一行的字节不是登记梯子的产物（多半是别的行/别的批次蒙过来的）"
                          % (row_id, replay_digest[:16], live_delivered[:16]))
        row_transform = str(entry.get("transform") or "")
        if replay_transform and row_transform and replay_transform != row_transform:
            errors.append("MEDIA_LINEAGE_DERIVATION_CHAIN_BROKEN|%s 清单记配方=%r，重放配方=%r ⇒ "
                          "出货时用的梯子和登记的不是一条" % (row_id, row_transform[:80], replay_transform[:80]))
    return errors


def snapshot_canonical_digest(snapshot: dict) -> str:
    """自摘要＝除 snapshot_sha256 之外的全字段规范序列化；键序固定，不受落盘缩进影响。"""
    body = {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest().upper()


def _record_field(record: dict, key: str):
    value = record.get(key)
    if isinstance(value, str):
        return value.strip()
    return value


def resolve_source_snapshot(base_dir, run_manifest, policy, errors) -> tuple:
    """路径由 run manifest 声明；生成器与门禁都不猜默认位置。"""
    field = policy["run_manifest_path_field"]
    declared = ""
    if isinstance(run_manifest, dict):
        declared = str(run_manifest.get(field) or "").strip()
    if not declared:
        errors.append("MEDIA_SNAPSHOT_PATH_UNDECLARED|run manifest 没有 %s 这一格：正式构建必须有"
                      "一份固化的来源核验快照可读，缺声明就是缺输入，不许回退成『当场回源』" % field)
        return None, None
    path = Path(declared)
    if not path.is_absolute():
        if base_dir is None:
            errors.append("MEDIA_SNAPSHOT_PATH_UNDECLARED|%s 是相对路径 %s 但调用方没给 base_dir"
                          % (field, declared))
            return None, None
        path = Path(base_dir) / path
    if not path.is_file():
        errors.append("MEDIA_SNAPSHOT_MISSING|%s 指向 %s，文件不在盘上" % (field, path))
        return None, None
    try:
        snapshot = json.loads(path.read_bytes().decode("utf-8"))
    except Exception as exc:
        errors.append("MEDIA_SNAPSHOT_UNREADABLE|%s 读不成 JSON：%s" % (path.name, str(exc)[:160]))
        return None, None
    if not isinstance(snapshot, dict):
        errors.append("MEDIA_SNAPSHOT_UNREADABLE|%s 顶层不是对象（现在是 %s）"
                      % (path.name, type(snapshot).__name__))
        return None, None
    return path, snapshot


def validate_source_identities(manifest: dict, *, base_dir=None, run_manifest=None, snapshot=None,
                               manifest_bytes=None, as_of=None, collect=None) -> dict:
    """离线核验：按**清单行**逐行验「Commons 修订身份＋采集字节＋本地派生链」三段血缘。

    业主 2026-11-03 裁示一（第二轮）：identity_plus_local_digest 只证明了两件互不相干的事实，证不了
    「本地这串字节确实来自该 Commons 文件的某个具体修订」；聚合口径也不许再按 File: 标题折叠——
    「现在 Twin Peaks 的三行里，酒店行的错误被标题级汇总掩盖，intra_manifest_consistent=false 不足以
    替代逐行阻断」。本函数因此：① 行锚＝local_file，② 三段各自成立还要接起来，③ 每行的错只算在这一行头上，
    ④ 不发任何网络请求（裁 A），⑤ 快照缺失／过期／身份不匹配／摘要变化各自阻断。
    """
    policy = source_snapshot_policy()
    rows = commons_asset_rows(manifest)
    errors: list[str] = []
    if snapshot is None:
        if run_manifest is None and base_dir is not None:
            declared_manifest = Path(base_dir) / "manifest.json"
            if declared_manifest.is_file():
                try:
                    run_manifest = json.loads(declared_manifest.read_bytes().decode("utf-8"))
                except Exception as exc:
                    errors.append("MEDIA_SNAPSHOT_UNREADABLE|run manifest %s 读不出来：%s"
                                  % (declared_manifest.name, str(exc)[:160]))
        path, snapshot = resolve_source_snapshot(base_dir, run_manifest, policy, errors)
    else:
        path = None
    if errors:
        raise ValueError("; ".join(errors))
    if str(snapshot.get("schema_version")) != str(policy["schema_version_supported"]):
        errors.append("MEDIA_SNAPSHOT_SCHEMA_UNSUPPORTED|快照 schema_version=%r，登记只支持 %r"
                      "⇒ 形状换了要人来裁，不是代码自适应"
                      % (snapshot.get("schema_version"), policy["schema_version_supported"]))
    blank = [key for key in policy["snapshot_fields_required"] if _record_field(snapshot, key) in (None, "", [])]
    if blank:
        errors.append("MEDIA_SNAPSHOT_FIELD_MISSING|快照顶层缺/空字段 %s" % blank)
    if str(snapshot.get("producer_version") or "") != str(policy["producer_version"]):
        errors.append("MEDIA_SNAPSHOT_SCHEMA_UNSUPPORTED|快照由生产者 %r 产出，登记当前只认 %r ⇒ "
                      "旧口径（identity_plus_local_digest）的件不能靠改判据混进新合同"
                      % (snapshot.get("producer_version"), policy["producer_version"]))
    if errors:
        raise ValueError("; ".join(errors))
    if str(snapshot.get("status")) != policy["complete_status_value"]:
        errors.append("MEDIA_SNAPSHOT_NOT_COMPLETE|快照自报 status=%r，登记要求的 COMPLETE 之外一律阻断："
                      "半份核验表不能当全份用" % snapshot.get("status"))
    if snapshot_canonical_digest(snapshot) != str(snapshot.get("snapshot_sha256")).upper():
        errors.append("MEDIA_SNAPSHOT_SELF_DIGEST_MISMATCH|snapshot_sha256 与现算规范摘要不符"
                      "⇒ 这份账被手改过")
    manifest_digest = hashlib.sha256(manifest_bytes if manifest_bytes is not None
                                     else (Path(base_dir) / "asset-manifest.json").read_bytes()).hexdigest().upper()
    if str(snapshot.get("asset_manifest_sha256")).upper() != manifest_digest:
        errors.append("MEDIA_SNAPSHOT_MANIFEST_DIGEST_MISMATCH|快照是对清单 %s 验的，现在检的是 %s"
                      "⇒ 快照不是这一份清单的快照" % (str(snapshot.get("asset_manifest_sha256"))[:12],
                                                     manifest_digest[:12]))
    records = snapshot.get("records") or []
    if not isinstance(records, list):
        errors.append("MEDIA_SNAPSHOT_FIELD_MISSING|records 不是列表（现在是 %s）"
                      % type(records).__name__)
        records = []
    # 行锚：清单侧与快照侧各建一份索引；任何一侧锚不全，都不许退回标题认领。
    _, anchor_errors = row_anchor_index(rows, policy)
    errors.extend(anchor_errors)
    by_row: dict = {}
    manifest_row_ids = {asset_row_id(entry) for entry in rows}
    for record in records:
        row_id = str(_record_field(record, "asset_row_id") or "").strip().replace("\\", "/")
        record_title = str(_record_field(record, "source_file_title") or "")
        if not row_id:
            errors.append("MEDIA_SNAPSHOT_ROW_KEY_UNAVAILABLE|快照记录 %s 没有 %s ⇒ 这条记录只能按标题认领，"
                          "而标题聚合就是被否掉的口径" % (record_title, policy["record_key"]))
            continue
        if row_id == record_title:
            errors.append("MEDIA_SNAPSHOT_ROW_KEY_UNAVAILABLE|快照记录把 File: 标题当成了行锚（%r）⇒ "
                          "这正是被否掉的聚合口径：同一标题的多条资产会被折成一条 declared 对象" % row_id)
            continue
        if row_id not in manifest_row_ids:
            errors.append("MEDIA_SNAPSHOT_ROW_KEY_UNAVAILABLE|快照记的行锚 %s 不是今天清单里任何一行的 local_file"
                          "（登记规则见 asset_row_id_rule）⇒ 账与行对不上，谁替谁作保说不清" % row_id)
            continue
        if row_id in by_row:
            errors.append("MEDIA_SNAPSHOT_INCOMPLETE|快照里 %s 出现两次⇒ 一行两条账，取哪条都是猜" % row_id)
            continue
        by_row[row_id] = record
    expected = int(snapshot.get("records_expected") or -1)
    if len(records) != expected or len(by_row) != len(rows):
        errors.append("MEDIA_SNAPSHOT_INCOMPLETE|records=%d，records_expected=%s，清单需核验的行=%d ⇒ "
                      "三个数必须全等（血缘是按行记的，同一张图被三处复用就是三条血缘，不是一条）"
                      % (len(records), snapshot.get("records_expected"), len(rows)))
    # 标题聚合检测：同一标题在清单里有 N 行，快照就必须替这 N 行各记一条。
    rows_per_title: dict = {}
    for entry in rows:
        rows_per_title[str(entry.get("source_file_title") or "")] = \
            rows_per_title.get(str(entry.get("source_file_title") or ""), 0) + 1
    records_per_title: dict = {}
    for row_id, record in by_row.items():
        title = str(_record_field(record, "source_file_title") or "")
        records_per_title[title] = records_per_title.get(title, 0) + 1
    for title, row_count in sorted(rows_per_title.items()):
        record_count = records_per_title.get(title, 0)
        if row_count > 1 and record_count < row_count:
            errors.append("MEDIA_LINEAGE_TITLE_AGGREGATION_FORBIDDEN|%s 在清单里是 %d 行、快照只替 %d 行作保 ⇒ "
                          "折叠掉的那几行没有采集桥梁，别的行合格不能替它们说话"
                          % (title, row_count, record_count))
    try:
        verified_on = datetime.strptime(str(snapshot["verified_at_utc"])[:10], "%Y-%m-%d").date()
    except Exception as exc:
        errors.append("MEDIA_SNAPSHOT_FIELD_MISSING|verified_at_utc 不是可解析的 UTC 日期：%s（%s）"
                      % (snapshot.get("verified_at_utc"), exc))
        verified_on = None
    clock = as_of if isinstance(as_of, date) else (as_of or date.today())
    if isinstance(clock, datetime):
        clock = clock.date()
    age_days = (clock - verified_on).days if verified_on else None
    if age_days is not None and age_days > int(policy["max_age_days"]):
        errors.append("MEDIA_SNAPSHOT_EXPIRED|快照核验于 %s，基准日 %s 已 %d 天，超过登记上限 %d 天"
                      "⇒ 来源身份要重新验一遍，不许拿陈账出货"
                      % (verified_on, clock, age_days, int(policy["max_age_days"])))
    unbound = str(policy["status_unbound_is_blocking"])
    publishable = [s for s in policy["status_closed_set"] if s != unbound]
    counted = {"sections_checked": 0, "bridges_recomputed": 0, "chains_replayed": 0, "unbound_rows": 0}
    for entry in rows:
        row_id = asset_row_id(entry)
        if not row_id or by_row.get(row_id) is None and row_id not in by_row:
            if row_id:
                errors.append("MEDIA_SNAPSHOT_ASSET_MISSING|清单资产 %s（%s）在快照里没有任何记录 ⇒ "
                              "这一行从未被验过" % (row_id, entry.get("source_file_title")))
            continue
        record = by_row[row_id]
        status = str(_record_field(record, "status") or "")
        if status not in policy["status_closed_set"]:
            errors.append("MEDIA_LINEAGE_STATUS_UNREGISTERED|%s 的状态 %r 不在登记闭集 %s 里 ⇒ "
                          "词表被绕过就是没有这条血缘" % (row_id, status, policy["status_closed_set"]))
            continue
        if status == unbound:
            counted["unbound_rows"] += 1
            errors.append("MEDIA_LINEAGE_ROW_UNBOUND|%s 登记为 %s：拿不出采集桥梁 ⇒ 不给发布级来源证明"
                          "（业主裁：UNBOUND_LEGACY 阻断，不批量改信用行沿用未绑定旧字节）" % (row_id, status))
            continue
        if (status == "EXACT_HISTORICAL_REVISION_BOUND"
                and not policy["historical_revision_addressing_verified"]):
            errors.append("MEDIA_LINEAGE_HISTORICAL_BOUND_NOT_PROVABLE|%s 声称绑到某个历史修订，但登记面记着"
                          "「按历史修订取回该版字节」这条路今天没量通"
                          "（historical_revision_addressing_verified=false）⇒ 不许口头声称历史绑定" % row_id)
            continue
        # 逐段字段闭合：名单的唯一持有人是 lineage_sections，代码里不另写一份。
        for section, fields in sorted(policy["lineage_sections"].items()):
            gaps = [f for f in fields if _record_field(record, f) in (None, "", [])]
            if gaps:
                errors.append("MEDIA_LINEAGE_SECTION_FIELD_MISSING|%s 的 %s 段缺/空字段 %s ⇒ "
                              "三段少任一段就不叫来源血缘" % (row_id, section, gaps))
        if any(_record_field(record, f) in (None, "", []) for f in policy["record_fields_required"]):
            continue
        counted["sections_checked"] += 1
        row_errors = _row_identity_errors(entry, record, policy, row_id)
        row_errors.extend(_row_lineage_errors(entry, record, policy, row_id, base_dir))
        if row_errors:
            errors.extend(row_errors)
            continue
        counted["bridges_recomputed"] += 1
        counted["chains_replayed"] += 1
    errors.extend(source_url_face_errors(base_dir, manifest, policy))
    # R3F（业主 2026-11-04）：定位符逐字对上权威串之后，还要问「这串字节在 run 里的哪儿」。
    # 绝对路径／指到 .temp 或 candidate_runs／解析后出根／目标不在／换了字节，都算血缘账不成立——
    # 本机 dangling=0 只是因为旧目录还在，跨目录复制就断，所以这一条也走行级逐条收集。
    run_path_errors, run_path_metrics = run_path_containment_errors(base_dir, policy, run_manifest)
    errors.extend(run_path_errors)
    if errors and collect is None:
        raise ValueError("; ".join(errors))
    if errors:
        # V6-S 的同一把尺子用到血缘段：只有结构性异常才中止，行级结论逐条交给调用方落报告。
        # 否则 7 行定位符问题会被压成一条截断的 abort 文本，坏样本点名不了——点名不了就等于没验。
        collect.extend(errors)
    return {"commons_asset_rows": len(rows),
            "snapshot_records": len(records),
            "snapshot_verified_at_utc": snapshot.get("verified_at_utc"),
            "snapshot_age_days": age_days,
            "snapshot_max_age_days": int(policy["max_age_days"]),
            "lineage_rows_checked": counted["sections_checked"],
            "lineage_bridges_recomputed": counted["bridges_recomputed"],
            "lineage_chains_replayed": counted["chains_replayed"],
            "lineage_unbound_rows": counted["unbound_rows"],
            "lineage_aggregation_basis": policy["record_key"],
            "snapshot_producer_version": snapshot.get("producer_version"),
            "snapshot_sha256_16": str(snapshot.get("snapshot_sha256"))[:16],
            "snapshot_path": str(path) if path else "(由调用方直接传入)",
            "network_calls_performed": 0,
            "run_path_fields_checked": run_path_metrics["run_path_fields_checked"],
            "run_path_faces_scanned": run_path_metrics["run_path_faces_scanned"],
            "run_path_findings": run_path_metrics["run_path_findings"],
            "authority": "references/media-policy.json::source_verification_snapshot"}


def _extmeta_value(info: dict, name: str) -> str:
    """Commons 的 extmetadata 有两种落法：单值对象 {value:…} 或列表 [{value:…}]，两种都读。

    2026-11-03 实拍 pre-flight（.temp/v422_honest_map/ZH_RELEASE_3/COMMONS_IDENTITY_PREFLIGHT.json）
    定下这件事，第一版只按列表写会当场 AttributeError——解析外部响应必须先照实物形状，不能照想象。
    """
    node = (info.get("extmetadata") or {}).get(name)
    if isinstance(node, dict):
        value = node.get("value", "")
    elif isinstance(node, list) and node and isinstance(node[0], dict):
        value = node[0].get("value", "")
    else:
        return ""
    cleaned = re.sub(r"<[^>]+>", "", str(value or ""))
    return re.sub(r"\s+", " ", cleaned).strip()


def commons_row_lineage(session, policy: dict, entry: dict, page: dict, revision: dict, *,
                        base_dir, timeout: int = 60, store_acquisitions: bool = False) -> tuple[dict, list]:
    """取「这一行」的三段血缘：Commons 修订身份 → 实际采集字节 → 本地派生链。

    唯一实现，两个消费者：生产者（build_source_verification_snapshot）导全量快照时用它，
    重采某几行的 .temp 工具也用它。写第二份取数逻辑＝第二把尺子。
    返回 (record, errors)；errors 非空时 record 不可用。
    """
    errors: list[str] = []
    row_id = asset_row_id(entry)
    title = str(entry.get("source_file_title") or "")
    info = ((page or {}).get("imageinfo") or [{}])[0]
    record: dict = {"asset_row_id": row_id, "source_file_title": title,
                    "source_page_id": int(page.get("pageid") or -1) if page else -1,
                    "source_page_url": info.get("descriptionurl") or "",
                    "original_url": info.get("url") or "",
                    "revision_id": int(revision.get("revid") or -1) if revision else -1,
                    "revision_timestamp": (revision.get("timestamp") if revision else "") or "",
                    "file_timestamp": info.get("timestamp") or "",
                    "original_sha1": info.get("sha1") or "",
                    "original_width": int(info.get("width") or 0),
                    "original_height": int(info.get("height") or 0),
                    "author": _extmeta_value(info, "Artist"),
                    "license_short_name": _extmeta_value(info, "LicenseShortName"),
                    "license_url": _extmeta_value(info, "LicenseUrl")}
    # 第一段与清单声明的对照：差的是事实就报错，差的是写法就按登记规则归一后再比。
    if not page or "missing" in page or not info.get("url"):
        errors.append("MEDIA_LINEAGE_REVISION_IDENTITY_MISSING|%s（%s）在 Commons 上取不到当前修订 ⇒ "
                      "来源不存在，血缘不能记它存在" % (row_id, title))
        return record, errors
    if int(page.get("pageid") or -1) != int(entry.get("source_page_id", -2)):
        errors.append("MEDIA_LINEAGE_REVISION_IDENTITY_MISSING|%s 的 pageid 清单=%s 现取=%s ⇒ 页面被替换，"
                      "这一行的身份要重新测量重新登记" % (row_id, entry.get("source_page_id"), page.get("pageid")))
    for label, rec_key, row_key in (("作者", "author", "author"), ("许可", "license_short_name", "license")):
        if not _same_text(record.get(rec_key), entry.get(row_key)):
            errors.append("MEDIA_SNAPSHOT_IDENTITY_MISMATCH|%s 的%s 现取=%r 清单=%r ⇒ 信用行与 Commons 那一版不符；"
                          "按裁示只能重采或走已登记无图状态，不许改完信用行沿用未绑定的旧字节"
                          % (row_id, label, record.get(rec_key), entry.get(row_key)))
    live_paths = {_url_path(record.get("source_page_url")), _url_path(record.get("original_url"))}
    live_paths.discard("")
    for field in ("source_page", "source_asset_url"):
        path = _url_path(entry.get(field))
        if path and live_paths and path not in live_paths:
            errors.append("MEDIA_SNAPSHOT_IDENTITY_MISMATCH|%s 的清单 %s=%s 不属于现取的 Commons 身份路径 %s ⇒ "
                          "这一行声明的文件不是那张文件" % (row_id, field, path, sorted(live_paths)))
    if not record["revision_id"] or record["revision_id"] < 0 or not record["revision_timestamp"]:
        errors.append("MEDIA_LINEAGE_REVISION_IDENTITY_MISSING|%s 取不到该页当前修订号/时间戳（revid=%r ts=%r）⇒ "
                      "说不出「哪一版」就不许往下谈采集" % (row_id, record["revision_id"], record["revision_timestamp"]))
    if not record["original_sha1"]:
        errors.append("MEDIA_LINEAGE_REVISION_IDENTITY_MISSING|%s 的 API 没给原图 SHA-1 ⇒ 修订指纹缺失" % row_id)

    # 第二段：按清单声明的宽度取回那一档 rendition 的字节，摘要现算。
    requested = int(entry.get("source_width") or 0)
    record["requested_width"] = requested
    if requested <= 0:
        errors.append("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|%s 清单没声明 source_width ⇒ 请求宽度无从记录，"
                      "采集 URL 也无从构造" % row_id)
        return record, errors
    try:
        thumb, acquisition_url = commons_acquisition_probe(session, policy, title, requested, timeout)
    except ValueError as exc:            # 远端没答好也要点名是哪一行——只报码不报行，事后无从复盘
        errors.append("%s|%s" % (row_id, exc))
        return record, errors
    # 声明宽度等于原图宽度时，API 不给 thumb 路径而是直接给原图 URL；这一支同样是合法采集字节。
    acquisition_url = acquisition_url or str(info.get("url") or "")
    if not acquisition_url:
        errors.append("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|%s 按 %dpx 取不到采集 URL ⇒ 没有可记的下载来源"
                      % (row_id, requested))
        return record, errors
    try:
        blob = fetch_source_bytes(session, acquisition_url, policy, timeout=timeout)
    except ValueError as exc:
        errors.append("%s|%s" % (row_id, exc))
        return record, errors
    record["acquisition_url"] = acquisition_url
    record["acquisition_sha256"] = hashlib.sha256(blob).hexdigest().lower()
    record["retrieved_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record["bytes_returned"] = len(blob)
    try:
        import io
        with Image.open(io.BytesIO(blob)) as img:
            record["returned_width"], record["returned_height"] = int(img.width), int(img.height)
            record["returned_mime"] = (img.format or "").lower()
    except Exception as exc:
        errors.append("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|%s 取回的字节打不开（%s）⇒ 它不是图片，"
                      "不能当采集桥梁" % (row_id, str(exc)[:120]))
        return record, errors
    # 宽度这一跳的真实规律（实拍见 TWIN_PEAKS_LINEAGE_PROBE.json 与 ACQUISITION_URL_FORM_PROBE.json）：
    # iiurlwidth=1600 时 API 的 thumbwidth 回显 1600，但它给的 thumburl 路径写 1920px、实物就是 1920 宽
    # （另测得 640→960、1000→1280、2560→3840；自己拼 /1600px- 那种 URL 今天直接 400）。
    # 业主 2026-11-03 R3D 明确：不把「声明宽度必须是不动点」写成合同——权威是 API 实际返回的 URL、
    # 那次返回的实际尺寸与采集摘要；差额由 acquisition_normalize 那次确定性归一吸收（见下面的桥）。
    # requested_width 与 returned_width 仍分两格，是为了让「今天取回的是哪一档」可复盘。
    token = re.search(r"/(\d+)px-", acquisition_url)
    url_width = int(token.group(1)) if token else int(info.get("width") or 0)
    record["api_declared_thumbwidth"] = int(thumb.get("thumbwidth") or 0)
    record["url_token_width"] = url_width
    if url_width and record["returned_width"] != url_width:
        errors.append("MEDIA_LINEAGE_ACQUISITION_BRIDGE_MISSING|%s 采集 URL 承诺 %dpx，实物是 %dpx ⇒ "
                      "取回的字节不是那条 URL 说的字节" % (row_id, url_width, record["returned_width"]))

    # 第三段：采集 → prepared → delivered。两条合法桥：逐字存盘，或按登记参数做一次确定性归一。
    prepared_file = prepared_original_file(base_dir, entry)
    if prepared_file is None or not prepared_file.is_file():
        errors.append("MEDIA_SNAPSHOT_LOCAL_DIGEST_MISSING|%s 的 prepared 档 %s 不在盘上 ⇒ 这一行没有可绑的本地字节"
                      % (row_id, prepared_file if prepared_file else "(没给相对路径)"))
        return record, errors
    live_prepared = _digest_of(prepared_file)
    record["prepared_sha256"] = live_prepared
    bridge = bridge_from_acquisition(blob, int(requested), live_prepared, policy)
    if bridge["error"]:
        record["status"] = str(policy["status_unbound_is_blocking"])
        errors.append("%s|%s" % (row_id, bridge["error"]))
        return record, errors
    record["transform_recipe"] = bridge["recipe"]
    if store_acquisitions and bridge["recipe"] != BRIDGE_RECIPE_NONCE:
        # 归一桥必须留下归一前的那串字节，否则「采集摘要」只剩一个数，离线复算无从下手。
        store_acquisition_bytes(base_dir, row_id, blob)
    delivered_file = Path(base_dir) / row_id
    if not delivered_file.is_file():
        errors.append("MEDIA_SNAPSHOT_LOCAL_DIGEST_MISSING|%s 的交付档不在盘上 ⇒ 派生链末端无从复算" % row_id)
        return record, errors
    record["delivered_sha256"] = _digest_of(delivered_file)
    replay_digest, replay_transform, replay_error = replay_delivered_from_prepared(prepared_file, entry, policy)
    if replay_error:
        errors.append(replay_error)
        return record, errors
    if replay_digest != record["delivered_sha256"]:
        errors.append("MEDIA_LINEAGE_DERIVATION_CHAIN_BROKEN|%s 从 prepared 重放得 %s，在盘交付档是 %s ⇒ "
                      "交付字节不是这条派生链的产物，重采时必须一起重建"
                      % (row_id, replay_digest[:16], record["delivered_sha256"][:16]))
        return record, errors
    if str(entry.get("transform") or "") != replay_transform:
        errors.append("MEDIA_LINEAGE_DERIVATION_CHAIN_BROKEN|%s 清单配方与重放配方不一致（%r ≠ %r）"
                      % (row_id, str(entry.get("transform") or "")[:60], replay_transform[:60]))
        return record, errors
    record["status"] = "CURRENT_REVISION_RECOLLECTED"
    record["producer_version"] = policy["producer_version"]
    return record, errors


def build_source_verification_snapshot(manifest: dict, *, base_dir, manifest_bytes=None,
                                       timeout: int = 60) -> dict:
    """在线那一趟：逐**行**取回三段血缘并现场复算；任何一行不合格就整体不写快照。

    业主裁「不允许网络失败后回退旧缓存并继续」＋负测要求「一条不符时不生成可用 COMPLETE 快照」：
    部分快照一旦被落盘，下一趟就会把它当全份读，所以这里只有「全对」与「什么都不写」两种结果。
    """
    import time
    import requests  # 延迟导入：只有显式导出快照才碰网络

    policy = source_snapshot_policy()
    rows = commons_asset_rows(manifest)
    if not rows:
        raise ValueError("MEDIA_SNAPSHOT_INCOMPLETE|清单里没有需要来源身份的资产 ⇒ "
                         "为这份 run 导快照只能是空表，空表不构成交付证据")
    _, anchor_errors = row_anchor_index(rows, policy)
    if anchor_errors:
        raise ValueError("; ".join(anchor_errors))
    titles = sorted({str(entry.get("source_file_title") or "") for entry in rows})
    if any(not title.startswith("File:") for title in titles):
        raise ValueError("MEDIA_LINEAGE_REVISION_IDENTITY_MISSING|Commons 血缘要求精确 File: 标题；不合格：%s"
                         % [title for title in titles if not title.startswith("File:")][:5])
    session = requests.Session()
    session.headers.update({"User-Agent": policy["user_agent"]})
    batch = int(policy["batch_size"])
    throttle = float(policy["request_throttle_seconds"])
    pages: dict = {}
    revisions: dict = {}
    for start in range(0, len(titles), batch):
        chunk = titles[start:start + batch]
        payload = api_payload(fetch_source_json(session, policy["api_endpoint"], {
            "action": "query", "format": "json", "redirects": "1", "prop": "imageinfo",
            "titles": "|".join(chunk),
            "iiprop": "url|timestamp|size|mime|sha1|extmetadata"}, policy, timeout=timeout),
            "imageinfo 批次")
        for page in payload.get("query", {}).get("pages", {}).values():
            pages[page.get("title")] = page
        time.sleep(throttle)
        # 修订号一页一请求：多标题配 rvlimit 是非法组合，API 会回 error 对象（试点实测 invalidparammix）。
        for title in chunk:
            revisions[title] = commons_page_revision(session, policy, title, timeout)
            time.sleep(throttle)
    records: list = []
    failures: list[str] = []
    for entry in rows:
        title = str(entry.get("source_file_title") or "")
        record, errors = commons_row_lineage(session, policy, entry, pages.get(title),
                                             revisions.get(title), base_dir=base_dir, timeout=timeout,
                                             store_acquisitions=True)
        if errors:
            failures.extend(errors)
        else:
            blank = [key for key in policy["record_fields_required"] if _record_field(record, key) in (None, "", [])]
            if blank:
                failures.append("MEDIA_LINEAGE_SECTION_FIELD_MISSING|%s 的这些登记字段取不到值：%s"
                                % (record["asset_row_id"], blank))
            else:
                records.append(record)
        time.sleep(throttle)
    if failures:
        raise ValueError("; ".join(failures) + "|MEDIA_SNAPSHOT_NOT_COMPLETE|本趟 %d/%d 行通过，"
                                   "其余行见上面逐条点名 ⇒ 整体不写快照（半份表一旦被读就是假证据）"
                                   % (len(records), len(rows)))
    by_row = {record["asset_row_id"] for record in records}
    if len(records) != len(rows) or len(by_row) != len(records):
        raise ValueError("MEDIA_SNAPSHOT_INCOMPLETE|生产者自检就没过：%d 行 / %d 条记录 / %d 个行锚"
                         % (len(rows), len(records), len(by_row)))
    titles_in_records = len({record["source_file_title"] for record in records})
    snapshot = {"schema_version": str(policy["schema_version_supported"]),
                "producer": "scripts/local_media_gate.py::build_source_verification_snapshot",
                "producer_version": policy["producer_version"],
                "verified_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "api_endpoint": policy["api_endpoint"],
                "batch_size": batch,
                "user_agent": policy["user_agent"],
                "asset_manifest_sha256": hashlib.sha256(
                    manifest_bytes if manifest_bytes is not None
                    else (Path(base_dir) / "asset-manifest.json").read_bytes()).hexdigest().upper(),
                "records_expected": len(rows),
                "record_anchor": policy["record_key"],
                "row_anchor_rule": policy["asset_row_id_rule"],
                "aggregation_counterfactual": {"manifest_rows": len(rows), "distinct_titles": titles_in_records,
                                               "records": len(records),
                                               "note": "记录数按行不按标题：这两个数不等恰恰说明标题级汇总会把 "
                                                       "%d 行折成 %d 条，本合同禁止那种折叠" % (len(rows), titles_in_records)},
                "lineage_sections": policy["lineage_sections"],
                "lineage_basis": "修订身份＋采集字节＋派生链三段逐行成立并互相接上（业主 2026-11-03 裁示一）",
                "records": sorted(records, key=lambda row: row["asset_row_id"]),
                "status": policy["complete_status_value"],
                "network_calls_performed_in_producer": True}
    snapshot["snapshot_sha256"] = snapshot_canonical_digest(snapshot)
    if int(snapshot["records_expected"]) != len(snapshot["records"]):
        raise ValueError("MEDIA_SNAPSHOT_INCOMPLETE|生产者落盘前自检失败：%s 条声明 / %s 条实写"
                         % (snapshot["records_expected"], len(snapshot["records"])))
    return snapshot


def write_source_verification_snapshot(snapshot: dict, path: Path) -> Path:
    """落盘：LF-only、write_bytes、回读必须与内存对象一致，然后当场用同一份字节复验一次。"""
    blob = (json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    if blob.count(b"\r\n"):
        raise ValueError("MEDIA_SNAPSHOT_UNREADABLE|快照落盘字节含 CRLF ⇒ 必须 write_bytes + LF")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    back = json.loads(path.read_bytes().decode("utf-8"))
    if back != snapshot:
        raise ValueError("MEDIA_SNAPSHOT_UNREADABLE|回读的快照不等于写出的内存对象 ⇒ 序列化口径不成立")
    if snapshot_canonical_digest(back) != str(back.get("snapshot_sha256")).upper():
        raise ValueError("MEDIA_SNAPSHOT_SELF_DIGEST_MISMATCH|落盘后自摘要复算不符")
    return path


def check_image_authenticity(path: Path, entry: dict) -> tuple[bool, str]:
    role = str(entry.get("display_role") or entry.get("role") or "").strip()
    if role == "designed_no_photo_state":
        return True, "designed_no_photo_state"
    gate_cfg = MEDIA_POLICY.get("authenticity_gate", {})
    min_entropy = float(gate_cfg.get("min_color_entropy", 4.5))
    max_dom_ratio = float(gate_cfg.get("max_dominant_color_ratio", 0.40))
    with Image.open(path) as img:
        img = img.convert("RGB")
        small = img.resize((150, 100))
        if hasattr(small, "get_flattened_data"):
            pixels = list(small.get_flattened_data())
            if pixels and isinstance(pixels[0], int):
                pixels = [(pixels[i], pixels[i+1], pixels[i+2]) for i in range(0, len(pixels), 3)]
        else:
            pixels = list(small.getdata())
        total = len(pixels)
        if total == 0:
            return False, "Empty image data"
        color_counts: dict[int, int] = {}
        for p in pixels:
            q = ((p[0] >> 3) << 10) | ((p[1] >> 3) << 5) | (p[2] >> 3)
            color_counts[q] = color_counts.get(q, 0) + 1
        entropy = -sum((count / total) * math.log2(count / total) for count in color_counts.values())
        dom_ratio = max(color_counts.values()) / total
        if entropy < min_entropy:
            return False, f"Low color entropy {entropy:.2f} < {min_entropy} (synthetic wireframe / template placeholder forbidden)"
        if dom_ratio > max_dom_ratio:
            return False, f"High dominant color ratio {dom_ratio:.2f} > {max_dom_ratio} (solid / canvas placeholder forbidden)"
    # PASS 也要把量到的数字带出来：一条没有测量值的通过，事后没人能判断它是「稳稳过关」还是
    # 「离登记下限 0.001」。交付档换编码旗标时要靠这个数看余量，所以口径只能出自本函数。
    return True, ("PASS|color_entropy=%.4f|min_entropy=%s|dominant_ratio=%.4f"
                  % (entropy, min_entropy, dom_ratio))


def check_geographic_consistency(entry: dict, root: Path | None = None) -> tuple[bool, str]:
    """Validate that asset metadata does not carry obvious cross-country/cross-region contamination."""
    geo_cfg = MEDIA_POLICY.get("geographic_consistency", {})
    if not geo_cfg.get("enforce_country_boundary", True):
        return True, "PASS"

    country = ""
    if root is not None:
        intake_file = root / "intake.json"
        data_file = root / "dataset.json"
        preflight_file = root / "preflight.json"
        for candidate in (intake_file, data_file, preflight_file):
            if candidate.is_file():
                try:
                    loaded = json.loads(candidate.read_text(encoding="utf-8"))
                    country = str(loaded.get("country") or (loaded.get("intake") or {}).get("q0_destination") or "").strip()
                    if country:
                        break
                except Exception:
                    pass

    banned_map = geo_cfg.get("banned_cross_country_markers", {})
    matched_markers = []
    for country_key, markers in banned_map.items():
        if country and country_key.casefold() in country.casefold():
            matched_markers.extend(markers)

    if not matched_markers and country:
        for country_key, markers in banned_map.items():
            if country_key.casefold() in country.casefold() or country.casefold() in country_key.casefold():
                matched_markers.extend(markers)

    if not matched_markers:
        # Fallback default: if country mentions 中国/China
        if "中国" in country or "china" in country.casefold():
            matched_markers = banned_map.get("中国", []) or banned_map.get("china", [])
        elif "泰国" in country or "thailand" in country.casefold():
            matched_markers = banned_map.get("泰国", []) or banned_map.get("thailand", [])

    # Fields to check against cross-contamination markers, excluded destinations and purpose
    fields_to_check = [
        str(entry.get("source_file_title") or ""),
        str(entry.get("source_page") or ""),
        str(entry.get("source_asset_url") or ""),
        str(entry.get("caption") or ""),
        str(entry.get("caption_en") or ""),
        str(entry.get("poi_name") or ""),
    ]
    haystack = " ".join(fields_to_check).casefold()

    # Check 1: Cross-country contamination markers
    for marker in matched_markers:
        marker_cf = marker.casefold().strip()
        if not marker_cf:
            continue
        # Use regex boundary or space/dash delimiter to avoid accidental substring matches
        pattern = r"(?:\b|_|-)" + re.escape(marker_cf) + r"(?:\b|_|-)"
        if re.search(pattern, haystack):
            return False, f"Detected foreign/cross-country contamination marker '{marker}' in asset metadata for destination country '{country}'"

    # Check 2: Excluded destinations from scope.json (e.g. 阿尔山 / Aershan)
    if geo_cfg.get("enforce_destination_exclusion", True) and root is not None:
        scope_file = root / "scope.json"
        if scope_file.is_file():
            try:
                scope = json.loads(scope_file.read_text(encoding="utf-8"))
                for item in scope.get("selected_destinations", []):
                    if isinstance(item, dict) and "排除" in str(item.get("status", "")):
                        ex_name = str(item.get("name") or "").strip().casefold()
                        ex_en = str(item.get("name_en") or "").strip().casefold()
                        for ex in (ex_name, ex_en):
                            if ex and len(ex) >= 2 and ex in haystack:
                                return False, f"Asset metadata contains excluded destination '{ex}' (explicitly rejected in scope.json)"
            except Exception:
                pass

    # Check 3: Module purpose sanity (e.g. Accommodation cannot use railway station or bridge)
    if geo_cfg.get("module_purpose_checks", True):
        category = str(entry.get("category") or entry.get("module_category") or "").casefold()
        modules = entry.get("modules") or []
        if category == "accommodation" or "hotels" in modules:
            station_or_bridge = ["railway station", "train station", "火车站", "界河桥", "bridge"]
            for token in station_or_bridge:
                if token in haystack:
                    return False, f"Accommodation asset carries inappropriate infrastructure marker '{token}': {entry.get('source_file_title') or entry.get('poi_name')}"

    return True, "PASS"



def _validate_asset(root: Path, path: Path, entry: dict, value: str) -> None:
    required = ('source_page', 'license', 'author', 'retrieved_at', 'verification_evidence', 'sha256')
    if any(not entry.get(key) for key in required) or entry.get('verification_status') != 'verified':
        raise ValueError(f'Asset source/rights/separate visual review incomplete: {value}')
    evidence = (root / str(entry['verification_evidence'])).resolve()
    if evidence == path or not evidence.is_relative_to(root / 'evidence') or not evidence.is_file():
        raise ValueError(f'Visual-review evidence must be a separate file under evidence/: {value}')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != str(entry.get('sha256')):
        raise ValueError(f'Asset SHA256 mismatch: {value}')
    
    # Source URL check
    src_page = str(entry.get('source_page') or '').strip()
    parsed_src = urlsplit(src_page)
    if not parsed_src.scheme.startswith('http') or not parsed_src.hostname:
        raise ValueError(f'Invalid source page URL: {value} ({src_page})')
    if parsed_src.path in {'', '/'} and not parsed_src.query:
        raise ValueError(f'Source page cannot be domain root: {value} ({src_page})')
    if any(q in parsed_src.path.casefold() or q in parsed_src.query.casefold() for q in ('/search', 'query=', 'keyword=', 'q=')):
        raise ValueError(f'Source page cannot be a search page: {value} ({src_page})')

    # Author and licensing check
    author = str(entry.get('author') or '').strip()
    if ' / ' in author and ('Official' in author or 'Contributor' in author):
        raise ValueError(f'Vague combined authorship forbidden: {value} ({author})')

    # Visual review evidence check
    ev_text = evidence.read_text(encoding='utf-8', errors='replace')
    if re.search(r'^\s*Human Visual QA Audit Record\s*$', ev_text, re.M) and 'Integrity: PASS' in ev_text and len(ev_text.strip().splitlines()) <= 8:
        raise ValueError(f'Template boilerplate evidence rejected; requires verified contact sheet or specific review logs: {value}')

    # Authenticity check
    is_auth, auth_reason = check_image_authenticity(path, entry)
    if not is_auth:
        raise ValueError(f'Authenticity gate failed: {value} -> {auth_reason}')

    # Geographic consistency & cross-region contamination check
    geo_ok, geo_reason = check_geographic_consistency(entry, root=root)
    if not geo_ok:
        raise ValueError(f'Geographic consistency gate failed: {value} -> {geo_reason}')

    if entry.get('source_provider') == 'wikimedia_commons' or entry.get('source_file_title') or 'commons.wikimedia.org/' in str(entry.get('source_page')):
        commons_required = ('source_file_title', 'source_page_id', 'source_asset_url', 'source_verification_status', 'source_verification_method')
        if any(not entry.get(key) for key in commons_required) or entry.get('source_verification_status') != 'verified':
            raise ValueError(f'Commons exact-file source verification incomplete: {value}')
        if not str(entry.get('source_file_title')).startswith('File:') or 'commons.wikimedia.org/wiki/File:' not in str(entry.get('source_page')):
            raise ValueError(f'Commons source identity malformed: {value}')
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
        # V6-R：下限只有一个来源——交付档登记的 min_delivered_geometry。以前这里是两个裸数
        # (640/360)，产图侧看不见同一把尺子，于是等比缩档能产出 1000×333 再被这里拒掉。
        floor_width, floor_height = single_file_policy.delivered_geometry_floor()
        if width < floor_width or height < floor_height:
            raise ValueError(f'Photographic asset is too small: {value} ({width}x{height})')


def validate(root, categories, require_complete=True, collect=None,
           exclude_assets=None):
    # V6-S：`collect` 给了就是「逐张清点、不中断」，没给就保持历史 raise 语义（生成器等调用方
    # 一行不改）。默认值不是装饰：以前第一张坏图会让后面的图全部不查，报告只有一条，读者
    # 以为「就这一张」，实际还有十几张同类问题——这正是项目里反复出现的那种假干净。
    def _issue(message):
        if collect is None:
            raise ValueError(message)
        collect.append(str(message))

    if root is None:
        raise ValueError('A run-local dataset is required for asset validation')
    root=Path(root).resolve()
    manifest=json.loads((root/'asset-manifest.json').read_text(encoding='utf-8'))
    entries=manifest.get('assets', [])
    by_file={}
    for entry in entries:
        key=entry.get('local_file')
        if key in by_file:
            _issue(f'Duplicate asset manifest path: {key}')
            continue
        by_file[key]=entry
    for category, rows, first, second in categories:
        for row in rows:
            for index in (first,second):
                value=str(row[index] if len(row)>index else '')
                if exclude_assets and value in exclude_assets:
                    continue        # 已登记媒体缺口：逐张校验跳过，理由与「真的没进页面」另由
                                    # verify_media_gaps 复算，不在此处放行
                if not value and not require_complete:
                    continue
                if not value or urlsplit(value).scheme:
                    _issue(f'{row[1]} requires local image files, not remote/provider URLs')
                    continue
                path=(root/value).resolve()
                if not path.is_relative_to(root/'assets') or not path.is_file():
                    _issue(f'Missing or nonportable local image: {value}')
                    continue
                entry=by_file.get(value,{})
                if entry.get('poi_name')!=row[1] or entry.get('category')!=category:
                    _issue(f'Asset identity/category mismatch: {value}')
                try:
                    _validate_asset(root, path, entry, value)
                except Exception as exc:
                    _issue(str(exc))


def check_no_photo_row(item: dict, root: Path, slot_rows: list, policy: dict) -> list[str]:
    """一条正式无图行的全部判据（业主 R3B 七条里数据面那几条），一次点到名、不短路。

    这里返回问题串而不是抛第一条：调用方（validate_section_media）负责按 collect/raise 语义处置，
    这样「同时违反三条」的行会一次说完，不用改一条跑一遍（V6-S 的同一条教训）。
    """
    errors: list[str] = []
    place = str(item.get('destination') or '')
    module = str(item.get('primary_module') or '')
    label = '%s / %s' % (place, module)
    allowed = list(policy['allowed_fields'])
    extra = sorted(set(item) - set(allowed))
    absent = [key for key in allowed if key not in item]
    if extra or absent:
        errors.append('SECTION_NO_PHOTO_FIELDS_UNREGISTERED|%s 字段集合不等于登记闭集：多 %s／少 %s'
                      '⇒ 无图状态不是另一种图片资产，不能继续携带旧来源声明' % (label, extra, absent))
    if item.get('image') != policy['image_value']:
        errors.append("SECTION_NO_PHOTO_IMAGE_NOT_EMPTY|%s 声明正式无图，image 却是 %r"
                      "⇒「无图」与「有这张图」不能同时写进一行" % (label, item.get('image')))
    role, level = str(item.get('asset_role') or ''), str(item.get('selection_level') or '')
    if role != NO_PHOTO_STATE_VALUE or level != NO_PHOTO_STATE_VALUE:
        errors.append('SECTION_NO_PHOTO_ROLE_LEVEL_DISAGREE|%s asset_role=%r／selection_level=%r'
                      ' 两格必须同为 %r⇒「无图」这件事不能只由一格声明'
                      % (label, role, level, NO_PHOTO_STATE_VALUE))
    code = str(item.get('no_photo_reason_code') or '')
    if code not in list(policy['reason_code_closed_set']):
        errors.append('SECTION_NO_PHOTO_REASON_CODE_UNREGISTERED|%s 无图理由码 %r 不在闭集 %s 里'
                      '⇒ 新增理由码是一次登记修订，不在数据里随口造一个'
                      % (label, code, list(policy['reason_code_closed_set'])))
    evidence = str(item.get(policy['evidence_field']) or '')
    if not evidence or urlsplit(evidence).scheme:
        errors.append('SECTION_NO_PHOTO_EVIDENCE_MISSING|%s 的 %s=%r 不是 run 内相对路径'
                      '⇒ 无图声明必须能被查到出处' % (label, policy['evidence_field'], evidence))
    else:
        target = (root / evidence).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            errors.append('SECTION_NO_PHOTO_EVIDENCE_MISSING|%s 指向的证据文件不在 run 内或不在盘上（%s）'
                          '⇒ 先写证据再声明无图，不能反过来' % (label, evidence))
    bearing = _image_bearing_values(item)
    if bearing:
        errors.append('SECTION_NO_PHOTO_IMAGE_SOURCE_PRESENT|%s 字段值里仍带图片字节位置 %s'
                      '⇒ 换个键名继续带旧图路径也算违规，无图行不得留旧来源声明' % (label, bearing))
    if slot_rows:
        errors.append('SECTION_NO_PHOTO_ASSET_ROW_PRESENT|无图槽位 %s 在 asset-manifest 仍挂着资产行 %s'
                      '⇒ 清单说这份字节要交付、读者却拿不到，是死登记不是无图状态'
                      % (label, [str(row.get('local_file')) for row in slot_rows]))
    return errors


def validate_section_media(root, section_media, coverage, require_complete=False, editorial_media=None,
                           collect=None, exclude_assets=None):
    """Validate section-specific media without borrowing editorial imagery."""
    def _issue(message):
        # V6-S：同 validate()，给了 collect 就逐条清点到底，不给就保持历史语义。
        if collect is None:
            raise ValueError(message)
        collect.append(str(message))

    if root is None:
        raise ValueError('A run-local dataset is required for section-media validation')
    root = Path(root).resolve()
    manifest = json.loads((root / 'asset-manifest.json').read_text(encoding='utf-8'))
    by_file = {entry.get('local_file'): entry for entry in manifest.get('assets', [])}
    seen_slots, seen_bytes = set(), {}
    # R3B：词表不再在代码里抄一份——media-policy::display_roles / selection_levels 是唯一持有人，
    # 以前这两行 hardcode 与登记面各写各的，改词表要改两处（本项目反复出现的形状）。
    allowed_roles = set(MEDIA_POLICY.get('display_roles') or [])
    allowed_levels = set(MEDIA_POLICY.get('selection_levels') or [])
    if not allowed_roles or not allowed_levels:
        raise ValueError('media-policy 没有登记 display_roles／selection_levels ⇒ 门禁不许自己猜词表')
    no_photo_cfg = no_photo_policy()
    # 槽位→资产行索引：无图槽位若还挂着 SECTION_MEDIA 资产行，就是「清单说交付了、读者拿不到」的死登记。
    slot_rows: dict = {}
    for entry in manifest.get('assets', []):
        if str(entry.get('category') or '') != 'SECTION_MEDIA':
            continue
        slot_rows.setdefault((str(entry.get('destination') or ''),
                              str(entry.get('primary_module') or '')), []).append(entry)

    editorial_paths = {str(item.get('image') or '') for item in (editorial_media or []) if isinstance(item, dict)}
    editorial_hashes = {}
    for em_str in editorial_paths:
        if em_str:
            em_p = (root / em_str).resolve()
            if em_p.is_file():
                editorial_hashes[hashlib.sha256(em_p.read_bytes()).hexdigest()] = em_str
    for item in section_media or []:
        place = str(item.get('destination') or '').strip()
        modules = item.get('modules') or []
        category = str(item.get('module_category') or '')
        primary_module = str(item.get('primary_module') or modules[0] if modules else '')
        role = str(item.get('asset_role') or '')
        level = str(item.get('selection_level') or '')
        if not place or not isinstance(modules, list) or not modules:
            _issue('Section media requires destination and modules')
            continue
        if role not in allowed_roles or level not in allowed_levels:
            _issue(f'Invalid section-media role/selection level: {place}')
        if any(MODULE_CATEGORIES.get(module) != category for module in modules):
            _issue(f'Section media crosses module categories: {place} {modules}')
        if primary_module not in modules:
            _issue(f'Section media primary module is not covered: {place} / {primary_module}')
        duplicated_slot = None
        for module in modules:
            slot = (place, module)
            if slot in seen_slots:
                duplicated_slot = f'{place} / {module}'
            seen_slots.add(slot)
        if duplicated_slot:
            _issue(f'Duplicate section-media slot: {duplicated_slot}')
        image_value = str(item.get('image') or '')
        if exclude_assets and image_value in exclude_assets:
            seen_slots.update((place, module) for module in modules)
            continue                # 已登记缺口：不重复报资产异常，但槽位仍然算被声明过
        if is_no_photo_row(item):
            # 槽位已经在上面计入 seen_slots ⇒ 分母不因声明无图而缩小（业主：不得用删分母洗比例）。
            for message in check_no_photo_row(item, root,
                                              slot_rows.get((place, primary_module), []),
                                              no_photo_cfg):
                _issue(message)
            continue
        if not image_value or urlsplit(image_value).scheme or image_value in editorial_paths:
            _issue(f'Section media must be a dedicated local asset: {place} / {modules}')
            continue
        path = (root / image_value).resolve()
        if not path.is_relative_to(root / 'assets') or not path.is_file():
            _issue(f'Missing or unsafe section media: {image_value}')
            continue
        entry = by_file.get(image_value, {})
        if entry.get('category') != 'SECTION_MEDIA' or entry.get('destination') != place:
            _issue(f'Section-media manifest mismatch: {image_value}')
        if entry.get('modules') != modules or entry.get('module_category') != category or entry.get('primary_module') != primary_module:
            _issue(f'Section-media module/category mismatch: {image_value}')
        try:
            _validate_asset(root, path, entry, image_value)
        except Exception as exc:
            _issue(str(exc))
        if not re.fullmatch(r'\d{1,3}%\s+\d{1,3}%', str(item.get('focal_point') or '50% 50%')):
            _issue(f'Invalid section-media focal point: {image_value}')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen_bytes:
            _issue(f'Duplicate section-media bytes: {seen_bytes[digest]} and {image_value}')
        if digest in editorial_hashes:
            _issue(f'Section media duplicates editorial media image bytes: {editorial_hashes[digest]} and {image_value}')
        seen_bytes[digest] = image_value
    if require_complete:
        missing = []
        for module, rows in coverage:
            for place in sorted({str(row[0]) for row in rows if isinstance(row, list) and row}):
                if (place, module) not in seen_slots:
                    missing.append(f'{module}:{place}')
        if missing:
            _issue('Missing required section-media slots: ' + ', '.join(missing))


def validate_editorial_media(root: Path, editorial_media: list, routes: list,
                             collect=None, exclude_assets=None) -> None:
    def _issue(message):
        # V6-S：编辑轮播是读者页最大的一块字节，以前一张坏图就中断整段清点。
        if collect is None:
            raise ValueError(message)
        collect.append(str(message))

    if not editorial_media or len(editorial_media) < 3:
        _issue(f"Editorial carousel requires at least 3 authentic images, current: {len(editorial_media or [])}")
        if collect is not None:
            return
    manifest = json.loads((root / 'asset-manifest.json').read_text(encoding='utf-8'))
    by_file = {entry.get('local_file'): entry for entry in manifest.get('assets', [])}
    covered_routes = set()
    covered_destinations = set()
    for item in editorial_media:
        if not isinstance(item, dict):
            continue
        img = str(item.get('image') or '').strip()
        if exclude_assets and img in exclude_assets:
            route = str(item.get('route') or '').strip()
            if route:
                covered_routes.add(route)
            continue                # 已登记缺口：逐张校验跳过，路线覆盖仍按声明计
        if not img:
            _issue(f"Editorial media entry missing image: {item}")
            continue
        path = (root / img).resolve()
        if not path.is_relative_to(root / 'assets') or not path.is_file():
            _issue(f"Missing editorial image: {img}")
            continue
        entry = by_file.get(img, {})
        try:
            _validate_asset(root, path, entry, img)
        except Exception as exc:
            _issue(str(exc))
        route = str(item.get('route') or '').strip()
        dest = str(item.get('destination') or '').strip()
        if route:
            covered_routes.add(route)
        if dest:
            covered_destinations.add(dest)
    if routes and len(covered_routes) < min(2, len(routes)):
        _issue(f"Editorial media must cover multiple routes, covered: {covered_routes}")


DATA_URI_RE = re.compile(r"data:image/(jpeg|png|webp|gif);base64,([A-Za-z0-9+/=]{64,})")
LINKED_SRC_RE = re.compile(r"(?:src=[\"']|url\()[\"']?(assets/[A-Za-z0-9._/-]+\.(?:jpg|jpeg|png|webp))", re.I)


def provenance_chain_check(manifest: dict, root: Path) -> tuple[list[str], dict]:
    """§5.4.2/5.4.3: prove the two hops, and prove nobody squashed the picture.

    A single recorded digest cannot be verified once a transform sits between the source and the
    delivered file — which is exactly how 20 section covers shipped as a 1000x650 squash of an
    8.6:1 panorama. So the manifest must carry the upstream digest, the delivered digest and the
    declared transform, and the geometry must still match the source.
    """
    errors: list[str] = []
    entries = manifest.get("assets", []) or []
    metrics = {"chain_entries": len(entries), "chain_complete": 0,
               "chain_incomplete": 0, "aspect_checked": 0, "aspect_distorted": 0,
               "tier_ok": 0, "tier_missing": 0, "tier_hash_broken": 0}
    for entry in entries:
        rel = str(entry.get("local_file") or "")
        source_sha = str(entry.get("source_sha256") or "")
        delivered_sha = str(entry.get("delivered_sha256") or entry.get("sha256") or "")
        path = root / rel
        if not source_sha or not delivered_sha:
            metrics["chain_incomplete"] += 1
            errors.append(
                f"IMG_PROVENANCE_INCOMPLETE|{rel} 清单缺 "
                f"{'source_sha256' if not source_sha else ''}{'/' if not source_sha and not delivered_sha else ''}"
                f"{'delivered_sha256' if not delivered_sha else ''}，交付字节没有可核对的上游凭据")
            continue
        if not path.is_file():
            metrics["chain_incomplete"] += 1
            errors.append(f"IMG_DELIVERED_MISSING|{rel} 清单声明的交付文件不在盘上")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != delivered_sha:
            metrics["chain_incomplete"] += 1
            errors.append(f"IMG_HASH_BROKEN|{rel} 声明 delivered_sha256={delivered_sha[:12]}… "
                          f"与在盘字节 {actual[:12]}… 不一致，摘要链断裂")
            continue
        metrics["chain_complete"] += 1
        tiers = entry.get("renditions") or []
        declared = tiers[0] if tiers else {}
        width = int(entry.get("delivered_width") or declared.get("width") or 0)
        height = int(entry.get("delivered_height") or declared.get("height") or 0)
        if width and height:
            with Image.open(path) as image:
                real_w, real_h = image.size
            if (real_w, real_h) != (width, height):
                errors.append(f"IMG_GEOMETRY_MISMATCH|{rel} 清单声明 {width}x{height}，"
                              f"在盘实际 {real_w}x{real_h}，声明与字节不是同一张图")
        # Every tier the renderer may put in a srcset has to be on disk and be the bytes the
        # manifest says. A tier that exists only as a number in the manifest is how a "multi-tier"
        # delivery silently ships one file.
        for tier in tiers:
            tier_path = _resolve_declared_path(root, tier, rel)
            if tier_path is None:
                errors.append(
                    f"IMG_TIER_FILE_MISSING|{rel} 声明了 {tier.get('label')} 档 "
                    f"{tier.get('path') or tier.get('file')}，但该字节在盘上不存在，srcset 只能回落到单档")
                metrics["tier_missing"] += 1
                continue
            tier_digest = hashlib.sha256(tier_path.read_bytes()).hexdigest()
            if str(tier.get("sha256") or "") != tier_digest:
                errors.append(
                    f"IMG_TIER_HASH_BROKEN|{rel} {tier.get('label')} 档声明 "
                    f"sha256={str(tier.get('sha256'))[:12]}…，在盘 {tier_path.name} 实为 "
                    f"{tier_digest[:12]}…，档位字节没有摘要背书")
                metrics["tier_hash_broken"] += 1
                continue
            with Image.open(tier_path) as image:
                tier_w, tier_h = image.size
            if (tier_w, tier_h) != (int(tier.get("width") or 0), int(tier.get("height") or 0)):
                errors.append(
                    f"IMG_TIER_GEOMETRY_MISMATCH|{rel} {tier.get('label')} 档声明 "
                    f"{tier.get('width')}x{tier.get('height')}，在盘 {tier_w}x{tier_h}")
            metrics["tier_ok"] += 1
        source_w = int(entry.get("source_width") or 0)
        source_h = int(entry.get("source_height") or 0)
        if source_w and source_h:
            metrics["aspect_checked"] += 1
            with Image.open(path) as image:
                real_w, real_h = image.size
            drift = abs((real_w / real_h) - (source_w / source_h)) / (source_w / source_h)
            if drift > ASPECT_TOLERANCE:
                metrics["aspect_distorted"] += 1
                errors.append(
                    f"IMG_ASPECT_DISTORTED|{rel} 交付图宽高比 {real_w}:{real_h} 与源图 "
                    f"{source_w}:{source_h} 偏差 {drift * 100:.1f}%（上限 "
                    f"{ASPECT_TOLERANCE * 100:.0f}%），图片被拉伸或压框，不得作为实景交付")
    return errors, metrics


def _resolve_declared_path(root: Path, tier: dict, local_file: str) -> Path | None:
    """Find a declared rendition on disk the same way the renderer does, then prove it is that file."""
    name = Path(str(tier.get("file") or "")).name
    candidates = []
    declared = str(tier.get("path") or "").replace("\\", "/")
    if declared:
        candidates.append(root / declared)
    candidates.append(root / "assets" / "renditions" / name)
    candidates.append(root / "assets" / name)
    candidates.append(root / Path(declared or name).name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def delivery_coverage_check(data: dict, manifest: dict,
                            exclude_assets=None) -> tuple[list[str], dict]:
    """§5.4.4: the artifact may only ship pictures the manifest registered.

    The legacy validators raise on the first incomplete asset, so a run carrying two unregistered
    images reported one of them and looked half-clean. This sweep is total and independent: every
    image the dataset asks the renderer to draw must have a manifest row, and rows that nothing
    references are counted so the collection stage cannot quietly over-collect.
    """
    errors: list[str] = []
    entries = manifest.get("assets", []) or []
    by_file = {str(e.get("local_file") or ""): e for e in entries}
    referenced: list[str] = []
    hero = str(data.get("hero_image") or "").strip()
    if hero:
        referenced.append(hero)
    for key in ("editorial_media", "section_media"):
        for item in data.get(key) or []:
            img = str((item or {}).get("image") or "").strip()
            if img:
                referenced.append(img)
    missing = []
    # V6-O：dataset 仍然引用「已登记媒体缺口」的那些图（审计面一条不减），但读者页里没有它们的
    # 字节。剔除的理由与「真的没进页面」由 verify_media_gaps 复算；这里再拿 dataset 的引用去判
    # 「页面会渲染」就是拿审计面冒充交付面。
    excluded = set(exclude_assets or ())
    for img in dict.fromkeys(referenced):
        if img in excluded:
            continue
        entry = by_file.get(img)
        if entry is None:
            missing.append(img)
            errors.append(
                f"IMG_UNREGISTERED_IN_MANIFEST|页面会渲染 {img}，但 asset-manifest 里没有这一条：来源、"
                f"授权与视觉复核均无登记，等于向读者投放一张来源不明的图片")
            continue
        if not str(entry.get("source_sha256") or "") or not str(entry.get("delivered_sha256") or ""):
            errors.append(
                f"IMG_CHAIN_MISSING|页面会渲染 {img}，清单里有条目但缺 source_sha256/delivered_sha256，"
                f"交付字节无法回溯到声明的源图")
    unused = [rel for rel in by_file
              if rel and rel not in set(referenced) and rel not in excluded]
    metrics = {"referenced_images": len(set(referenced)),
               "referenced_unregistered": len(missing),
               "declared_gap_references": len([img for img in set(referenced)
                                                if img in excluded]),
               "manifest_unreferenced": len(unused),
               "manifest_unreferenced_files": unused[:12]}
    return errors, metrics


def asset_digest_sweep(manifest: dict, root: Path) -> list[dict]:
    """Compare every recorded digest with the bytes that actually ship, for all entries.

    v4.2.0 stopped at the first mismatch because each validator raised, so a run could carry
    13 more unverified images while the report named one. This sweep is total: no early exit.
    """
    rows: list[dict] = []
    for entry in manifest.get("assets", []) or []:
        rel = str(entry.get("local_file") or "")
        claimed = str(entry.get("sha256") or "")
        path = root / rel
        row = {"local_file": rel, "claimed_sha256": claimed, "on_disk_sha256": "", "on_disk": path.is_file()}
        if path.is_file():
            row["on_disk_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            row["matches_claim"] = bool(claimed) and row["on_disk_sha256"] == claimed
        else:
            row["matches_claim"] = False
        rows.append(row)
    return rows


def manifest_claim_map(manifest: dict) -> dict:
    """digest -> 这条 digest 在清单里是谁（主文件或某个 rendition）。

    v4.2.2 V5-D：交付字节对账（本文件 attest_delivered_images）与读者页 DOM 侧的
    『这张图有没有登记』（visual_qa.check_rendered_image_registration）必须问同一个问题、
    用同一份规则。只有带完整双跳链（source_sha256 + delivered_sha256）的条目才允许声明
    rendition 摘要——从别处抄来一个 digest 不算来源。
    """
    claims: dict[str, str] = {}
    entries = manifest.get("assets") or []
    for entry in entries:
        rel = str(entry.get("local_file") or "")
        digest = str(entry.get("sha256") or "")
        if digest:
            claims[digest] = rel
        if str(entry.get("source_sha256") or "") and str(entry.get("delivered_sha256") or ""):
            for tier in entry.get("renditions") or []:
                tier_digest = str(tier.get("sha256") or "")
                if tier_digest:
                    claims.setdefault(tier_digest, f"{rel}#{tier.get('label')}")
            if entry.get("delivered_sha256"):
                claims.setdefault(str(entry["delivered_sha256"]), rel)
    return claims


def attest_delivered_images(html_text: str, manifest: dict, root: Path) -> tuple[list[str], dict]:
    """Prove the bytes the reader receives are the bytes the manifest attests.

    Three states, deliberately not collapsed:
      attested        delivered digest == a manifest sha256            -> safe to ship
      stale_digest    delivered digest == bytes on disk, manifest lies -> provenance broken
      unattested      delivered digest matches nothing                -> orphan bytes
    """
    errors: list[str] = []
    entries = manifest.get("assets", []) or []
    claims = manifest_claim_map(manifest)
    on_disk: dict[str, str] = {}
    for entry in entries:
        rel = str(entry.get("local_file") or "")
        path = root / rel
        if path.is_file():
            on_disk[hashlib.sha256(path.read_bytes()).hexdigest()] = rel

    inline_counts: dict[str, int] = {}
    inline_sizes: dict[str, int] = {}
    for _mime, blob in DATA_URI_RE.findall(html_text):
        try:
            data = base64.b64decode(blob)
        except Exception as exc:
            errors.append(f"IMG_INLINE_UNDECODABLE|交付页面里有内联图片 base64 无法解码: {str(exc)[:80]}")
            continue
        digest = hashlib.sha256(data).hexdigest()
        inline_counts[digest] = inline_counts.get(digest, 0) + 1
        inline_sizes[digest] = len(data)

    attested = stale = orphan = 0
    for digest, count in sorted(inline_counts.items(), key=lambda kv: (-inline_sizes[kv[0]], kv[0])):
        kb = inline_sizes[digest] / 1024
        if count > 1:
            report_dup = (f"IMG_INLINE_DUPLICATE|同一张图片在单文件页面里内联了 {count} 次 "
                          f"(每次 {kb:.0f}KB，多出的 {(count - 1) * kb:.0f}KB 手机端要重复解码)")
            if report_dup not in errors:
                errors.append(report_dup)
        if digest in claims:
            attested += 1
            continue
        if digest in on_disk:
            stale += 1
            errors.append(
                f"IMG_MANIFEST_DIGEST_STALE|页面内联图 {kb:.0f}KB 的字节与在盘文件一致 ({on_disk[digest]})，"
                f"但 asset-manifest 记录的 sha256 对不上，交付字节没有任何摘要背书"
            )
            continue
        orphan += 1
        errors.append(
            f"IMG_DELIVERED_UNATTESTED|页面内联图 {kb:.0f}KB 的字节在 asset-manifest 和在盘文件中都找不到对应摘要，"
            f"等于向读者投放了一张来源未登记的图片 (digest={digest[:16]})"
        )

    linked_ok = linked_bad = 0
    for rel in sorted(set(m.group(1) if hasattr(m, "group") else m for m in LINKED_SRC_RE.findall(html_text))):
        path = root / rel
        entry = next((e for e in entries if str(e.get("local_file")) == rel), None)
        if not path.is_file() or entry is None:
            linked_bad += 1
            errors.append(f"IMG_LINKED_UNRESOLVED|页面引用了在盘或清单里都不存在的图片: {rel}")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != str(entry.get("sha256") or ""):
            linked_bad += 1
            errors.append(f"IMG_LINKED_DIGEST_STALE|页面外链图 {rel} 在盘字节与清单 sha256 不一致")
        else:
            linked_ok += 1

    metrics = {
        "inline_unique_images": len(inline_counts),
        "inline_bytes": sum(inline_sizes.get(d, 0) * c for d, c in inline_counts.items()),
        "inline_attested": attested,
        "inline_digest_stale": stale,
        "inline_unattested": orphan,
        "linked_ok": linked_ok,
        "linked_bad": linked_bad,
    }
    return errors, metrics


def check_delivered_rendition_budget(manifest: dict, root: Path) -> tuple[list[str], dict]:
    """交付图必须既「天生可内联」又「出自登记的档位」——单文件交付的两条前提。

    两条都只量在盘字节，不信任清单自报：
      IMG_DELIVERED_OVER_INLINE_CAP  单张 > default_max_inline_kb×1024。这种图进不了单文件，
                                     读者页要么留一个走文件的引用，要么被 error 兜底画成假封面
                                     （PH 现行 7 张 / 4 张假封面就是这么来的）。
      IMG_DELIVERED_LADDER_UNREGISTERED  transform 没写登记档位 id：字节可能是手工改的或旧档留下的，
                                     双跳摘要只能证明「这字节没被换过」，不能证明「它按现行档产出」。
    """
    budget = single_file_policy.rendition_ladder()
    per_image = int(budget["max_delivered_image_decoded_bytes"])
    errors: list[str] = []
    over_cap, ladder_mismatch, measured = [], [], 0
    for entry in manifest.get('assets', []) or []:
        rel = str(entry.get('local_file') or '')
        path = root / rel
        if not path.is_file():
            continue                                  # 缺文件由 asset_digest_sweep 负责报
        size = path.stat().st_size
        measured += size
        if size > per_image:
            over_cap.append('%s=%dB' % (rel, size))
        transform = str(entry.get('transform') or '')
        tiers = entry.get('renditions') or []
        if budget["ladder_id"] not in transform or any(
                budget["ladder_id"] not in str(tier.get('transform') or '') for tier in tiers):
            ladder_mismatch.append(rel)
    if over_cap:
        errors.append(
            f"IMG_DELIVERED_OVER_INLINE_CAP|{len(over_cap)} 张交付图超过登记单图上限 {per_image:,}B，"
            f"它们在单文件交付里注定进不了内联表: {over_cap[:5]}")
    if ladder_mismatch:
        errors.append(
            f"IMG_DELIVERED_LADDER_UNREGISTERED|{len(ladder_mismatch)} 条交付记录的 transform 没有声明"
            f"登记档位 {budget['ladder_id']}，无法证明字节是按现行档产出的: {ladder_mismatch[:5]}")
    return errors, {'delivered_image_bytes_total': measured,
                    'delivered_image_budget_total': budget['total_delivered_image_decoded_bytes_max'],
                    'delivered_image_budget_per_image': per_image,
                    'delivered_over_per_image_cap': len(over_cap),
                    'delivered_ladder_unregistered': len(ladder_mismatch)}


def payload_media_gaps(html_text: str) -> list[dict]:
    """读者页自己声明的媒体缺口（V6-Q：无证据/低于几何下限的图不进读者载荷，但必须显式登记）。

    唯一来源是交付物里的 `media_gaps`——不是审计文件，因为「剔了什么」这件事的权威答案就在
    读者真正拿到的那一份里；审计面留着完整的行，两边都由这里对账。
    """
    match = re.search(r'<script id="dataset" type="application/json">(.*?)</script>',
                      html_text, re.S)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    gaps = payload.get("media_gaps")
    return [gap for gap in gaps if isinstance(gap, dict)] if isinstance(gaps, list) else []


def no_photo_retired_assets(section_media: list, root: Path) -> dict:
    """无图行证据里登记的「已退役字节」：asset 相对路径 → 「 destination / module」。

    这一张表用来抓一种很具体的自相矛盾：数据层已经决定该槽位正式无图（并把旧字节登记为退役），
    读者载荷里却又出现「这张图被我扣下了」的媒体缺口——那就是 dataset 声称有图／renderer 临时扣留
    ／页面偶然少图三件事同时成立（业主 R3B 明令禁止的形状）。
    """
    retired: dict = {}
    field = no_photo_policy()['evidence_field']
    for item in section_media or []:
        if not is_no_photo_row(item):
            continue
        evidence = str(item.get(field) or '')
        slot = '%s / %s' % (str(item.get('destination') or ''), str(item.get('primary_module') or ''))
        if not evidence:
            continue
        path = (root / evidence).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        try:
            doc = json.loads(path.read_bytes().decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            continue
        for rel in doc.get('removed_from_run') or []:
            if isinstance(rel, str) and rel.strip():
                retired.setdefault(rel.strip().replace('\\', '/'), slot)
    return retired


def verify_media_gaps(gaps: list[dict], manifest: dict, root: Path,
                      html_text: str, section_media: list | None = None) -> tuple[list[str], dict]:
    """缺口必须「有理由、且真的没进页面」。

    只登记不核对，剔除就变成一句话：既可能把一张本来合规的图悄悄拿走（读者少看图，报告还说谎），
    也可能登记完却仍然内联着那 511KB 未登记字节（围栏照破）。
    """
    errors: list[str] = []
    by_file = {str(entry.get('local_file') or ''): entry for entry in manifest.get('assets', [])}
    inline_digests = {match.group(2)[:24] for match in DATA_URI_RE.finditer(html_text)}
    retired = no_photo_retired_assets(section_media or [], root)
    for gap in gaps:
        asset = str(gap.get('asset') or '')
        kind = str(gap.get('kind') or '')
        asset_norm = asset.replace('\\', '/')
        if asset_norm in retired:
            # 先判这条，再判缺口种类：负测要求「被自己点名的门拦下」，顺序倒了就等于别的门抢功。
            errors.append('SECTION_NO_PHOTO_MEDIA_GAP_CONTRADICTION|%s 以 %r 被记成媒体缺口，但 %s 这个槽位'
                          '已由数据层声明正式无图、该字节也已按 R3B 裁决退役隔离：无图行不产生缺口，'
                          '出现缺口就等于「dataset 声称有图／renderer 临时扣留／页面偶然少图」三件事同时成立'
                          % (asset, kind, retired[asset_norm]))
            continue
        if not asset or not kind:
            errors.append(f"MEDIA_GAP_MALFORMED|缺口记录缺 asset/kind：{gap}")
            continue
        justified = False
        if kind == 'MEDIA_UNREGISTERED_IN_MANIFEST':
            justified = asset not in by_file
            why = 'asset-manifest 里确实没有这条登记'
        elif kind == 'MEDIA_BELOW_GEOMETRY_FLOOR':
            entry = by_file.get(asset) or {}
            floor_w, floor_h = single_file_policy.delivered_geometry_floor()
            sizes = [(entry.get('delivered_width'), entry.get('delivered_height'))]
            sizes += [(tier.get('width'), tier.get('height'))
                      for tier in (entry.get('renditions') or []) if isinstance(tier, dict)]
            justified = any(width and height and (width < floor_w or height < floor_h)
                            for width, height in sizes)
            why = '交付档几何确实低于登记下限 %dx%d' % (floor_w, floor_h)
        else:
            justified = False
            why = '未登记的缺口种类'
        if not justified:
            errors.append(f"MEDIA_GAP_UNJUSTIFIED|{asset} 以 {kind} 被剔出读者页，但核对不成立（{why}）："
                          f"剔除必须有可复算的理由，否则就是随手删读者的图")
            continue
        path = (root / asset)
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest[:24] in inline_digests:
                errors.append(f"MEDIA_GAP_STILL_INLINE|{asset} 登记为媒体缺口，页面里却仍内联着它的"
                              f"字节（{gap.get('source_bytes', 0)}B）：缺口不能既声明又交付")
    return errors, {"declared_media_gaps": len(gaps),
                    "gap_assets": sorted(str(gap.get('asset') or '') for gap in gaps),
                    "no_photo_retired_assets_known": len(retired)}


def _load_run_manifest(root: Path, declared_path: str = "") -> dict:
    """run manifest 读不到就交 None，让核验者用自己的命名码说清楚——不在这里编一个第二套报错。"""
    path = Path(declared_path) if declared_path else (Path(root) / "manifest.json")
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_bytes().decode("utf-8"))
    except Exception as exc:
        raise ValueError("MEDIA_SNAPSHOT_UNREADABLE|run manifest %s 读不出来：%s"
                         % (path.name, str(exc)[:160]))
    return loaded if isinstance(loaded, dict) else None


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit run-local Travel-Scope media and section coverage')
    parser.add_argument('--run-root', required=True)
    parser.add_argument('--data', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--html', default='', help='Final single-file HTML; its delivered image bytes are attested against the manifest')
    parser.add_argument('--run-manifest', default='',
                        help='Run manifest declaring source_verification_snapshot_path；缺省取 <run-root>/manifest.json')
    parser.add_argument('--source-snapshot', default='',
                        help='显式指定核验快照路径（不给就按 run manifest 的登记字段解析）')
    parser.add_argument('--as-of', default='',
                        help='过期判定的基准日 YYYY-MM-DD；不给就用 UTC 今天。测试与重放必须显式给（seal-52 的教训）')
    parser.add_argument('--export-source-snapshot', default='',
                        help='在线核验那一趟：逐张问 Commons 并取回原图算 SHA-256，把结果固化成快照后退出。'
                             '任何一张验不过就整体不写。')
    args = parser.parse_args()
    root = Path(args.run_root).resolve()
    policy = source_snapshot_policy()
    manifest_for_snapshot = root / 'asset-manifest.json'
    if args.export_source_snapshot:
        if not manifest_for_snapshot.is_file():
            raise SystemExit("MEDIA_SNAPSHOT_MISSING|导出快照需要 %s 在场，盘上没有" % manifest_for_snapshot)
        raw = manifest_for_snapshot.read_bytes()
        snapshot = build_source_verification_snapshot(
            json.loads(raw.decode('utf-8')), base_dir=root, manifest_bytes=raw)
        written = write_source_verification_snapshot(snapshot, Path(args.export_source_snapshot))
        print(json.dumps({'snapshot': str(written).replace('\\', '/'),
                          'records': snapshot['records_expected'],
                          'verified_at_utc': snapshot['verified_at_utc'],
                          'snapshot_sha256': snapshot['snapshot_sha256'],
                          'producer_version': snapshot['producer_version'],
                          'manifest_sha256': snapshot['asset_manifest_sha256']},
                         ensure_ascii=False, indent=1))
        return 0
    data = json.loads(Path(args.data).read_text(encoding='utf-8'))
    report = {'status': 'PASS', 'errors': [], 'metrics': {}}
    manifest_path = root / 'asset-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else {'assets': []}
    # Fingerprints are written before anything can raise. v4.2.0 only recorded them on a clean
    # pass, so a failing report carried no fingerprint and delivery_gate could not tell a stale
    # report from a fresh one -- which is how an expired media audit kept being reused.
    report['data_sha256'] = hashlib.sha256(Path(args.data).read_bytes()).hexdigest()
    report['asset_manifest_sha256'] = (hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                                       if manifest_path.is_file() else '')
    # V6-S：资产清点改为「逐张到底 + 分段独立」。四段共用一个 try 时，第一张坏图会连带跳过
    # 编辑图/分区图/来源身份三段，一份只写了一条问题的报告读起来像「只有这一条问题」。
    asset_findings: list[str] = []
    # 血缘段的行级结论单独收，不混进 asset_findings：那是「逐张资产」的计数口径，
    # 混在一起会让 asset_findings_collected 这个数再也说不清点到了什么。
    lineage_findings: list[str] = []
    aborted_stages: list[str] = []
    # V6-O：读者页自己声明的媒体缺口（V6-Q 的产物）。缺口不是「放行」，是换一种判法：
    # 理由必须可复算、字节必须真的没进页面，然后才跳过那张图的逐张校验。
    html_text = Path(args.html).read_text(encoding='utf-8', errors='replace') if args.html else ''
    declared_gaps = payload_media_gaps(html_text) if html_text else []
    gap_errors, gap_metrics = verify_media_gaps(declared_gaps, manifest, root, html_text,
                                                section_media=data.get('section_media', []))
    excluded_assets = set(gap_metrics['gap_assets'])
    report['errors'].extend(gap_errors)
    if gap_errors:
        report['status'] = 'FAIL'
    # gap_metrics 在报告末尾再并入一次：中途有一次整表赋值会把它擦掉（V6-O 第一次实跑就丢了）
    categories = [('HOTELS', data.get('hotels', []), 8, 9), ('RESTAURANTS', data.get('restaurants', []), 8, 9),
                  ('CAFES', data.get('cafes', []), 8, 9), ('ATTRACTIONS', data.get('attractions', []), 7, 8),
                  ('DIVE_SITES', data.get('dive_sites', []), 7, 8)]
    coverage = [(key, data.get(key, [])) for key in ('hotels', 'restaurants', 'cafes', 'attractions', 'dive_sites')]
    require_complete = bool((data.get('image_collection') or {}).get('require_complete'))
    # 血缘那一段的度量原来被 CLI 丢掉（只留 collect 的逐条结论）。R3F 要把「扫了几格路径／
    # 点名几条」落进报告，所以这里接住返回值——不然报告里只有错误文本，读者分不清「扫过且干净」
    # 与「根本没扫」。
    lineage_metrics: dict = {}

    def _lineage_stage():
        lineage_metrics.update(validate_source_identities(
            manifest, base_dir=root, run_manifest=_load_run_manifest(root, args.run_manifest),
            snapshot=(json.loads(Path(args.source_snapshot).read_bytes().decode('utf-8'))
                      if args.source_snapshot else None),
            manifest_bytes=(manifest_path.read_bytes() if manifest_path.is_file() else None),
            as_of=(date.fromisoformat(args.as_of) if args.as_of else None),
            collect=lineage_findings))
        return lineage_metrics

    stages = [
        ('分类图资产', lambda: validate(root, categories, require_complete=require_complete,
                                   collect=asset_findings, exclude_assets=excluded_assets)),
        ('编辑轮播图', lambda: validate_editorial_media(root, data.get('editorial_media', []),
                                                   data.get('routes', []), collect=asset_findings,
                                                   exclude_assets=excluded_assets)),
        ('分区图', lambda: validate_section_media(
            root, data.get('section_media', []), coverage,
            require_complete=bool((data.get('image_collection') or {}).get('section_media_required')),
            editorial_media=data.get('editorial_media', []), collect=asset_findings,
            exclude_assets=excluded_assets)),
        ('来源身份快照核验', _lineage_stage),
    ]
    for stage_name, stage in stages:
        try:
            stage()
        except Exception as exc:
            aborted_stages.append("%s: %s" % (stage_name, exc))
    report['metrics']['asset_findings_collected'] = len(asset_findings)
    report['metrics']['lineage_findings_collected'] = len(lineage_findings)
    report['metrics']['stages_aborted'] = len(aborted_stages)
    # 逐条结论先落进报告，再补「哪一段仍被结构性异常中断」。顺序反过来的话，一条结构异常会把
    # 已经清点到手的十几条资产问题挤掉——那正是 V6-S 要修的毛病。
    report['errors'].extend(asset_findings)
    report['errors'].extend(lineage_findings)
    if lineage_findings:
        report['status'] = 'FAIL'
    if aborted_stages:
        report['status'] = 'FAIL'
        report['errors'].extend('LEGACY_VALIDATION_ABORTED|%s 段在结构性异常处停止：%s'
                                % (stage.split(': ', 1)[0], stage.split(': ', 1)[1][:200])
                                for stage in aborted_stages)
        if not asset_findings:
            report['errors'].append(
                'LEGACY_VALIDATION_ASSET_SWEEP_EMPTY|结构性异常发生在逐张清点之前，'
                '本报告的资产条目数不是完整清点（总额检查见 asset_digest/chain/coverage 三段）')
    # v4.2.1 section 5: the total sweeps run even when a legacy validator already raised, because
    # "first failure stops the report" is exactly what hid the other 13 stale digests.
    digest_rows = asset_digest_sweep(manifest, root)
    for row in digest_rows:
        if not row['matches_claim']:
            report['errors'].append(
                f"ASSET_DIGEST_STALE|清单 sha256 与在盘字节不一致: {row['local_file']} "
                f"(清单={row['claimed_sha256'][:12] or '空'}..., 在盘={(row['on_disk_sha256'] or '文件缺失')[:12]}...)")
    chain_errors, chain_metrics = provenance_chain_check(manifest, root)
    report['errors'].extend(chain_errors)
    budget_errors, budget_metrics = check_delivered_rendition_budget(manifest, root)
    report['errors'].extend(budget_errors)
    coverage_errors, coverage_metrics = delivery_coverage_check(data, manifest,
                                                         exclude_assets=excluded_assets)
    report['errors'].extend(coverage_errors)
    if args.html:
        img_errors, img_metrics = attest_delivered_images(html_text, manifest, root)
        report['errors'].extend(img_errors)
    else:
        img_metrics = {'html_attestation': 'NOT_RUN'}
        report['errors'].append('IMG_HTML_NOT_SCANNED|未提供 --html，交付页面的图片字节没有对账（没检查不等于通过）')
    report['metrics'] = {'manifest_assets': len(manifest.get('assets', []) or []),
                         'section_media': len(data.get('section_media', [])),
                         'editorial_media': len(data.get('editorial_media', [])),
                         # 这两格原来会被这次整表赋值擦掉（gap_metrics 的同一把老毛病）：
                         # 清点数留在最终 metrics 里，报告读起来才对得上「逐条点名了几行」。
                         'asset_findings_collected': len(asset_findings),
                         'lineage_findings_collected': len(lineage_findings),
                         # R3F：路径面扫了多少格、点名几条，落报告而不是只留错误文本——
                         # 「扫过且干净」与「根本没扫」必须在报告里分得开。
                         'run_path_fields_checked': lineage_metrics.get('run_path_fields_checked'),
                         'run_path_faces_scanned': lineage_metrics.get('run_path_faces_scanned'),
                         'run_path_findings': lineage_metrics.get('run_path_findings'),
                         'stages_aborted': len(aborted_stages),
                         'asset_digest_stale': sum(1 for r in digest_rows if not r['matches_claim']),
                         **chain_metrics,
                         **budget_metrics,
                         **coverage_metrics,
                         **img_metrics,
                         **gap_metrics}
    if report['errors']:
        report['status'] = 'FAIL'
    report = gate_producer.write_stamped_report(
        args.report, report, gate_role='local_media_gate', producing_code=list(PRODUCING_CODE),
        producing_config=list(PRODUCING_CONFIG),
        inputs=gate_producer.collect_inputs({
            'data': args.data, 'asset_manifest': str(root / 'asset-manifest.json'),
            'html': args.html}))['report']
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
