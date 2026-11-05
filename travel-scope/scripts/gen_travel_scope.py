#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Travel Guide Builder - Generate Excel + HTML + Markdown travel guide files.
Version: V5.0.0

Usage:
    python gen_travel_scope.py --mode live --data <dataset.json> --output-dir <dir> --language both

Live runs load verified, run-local data through --data. Installed source constants
are not a production data-entry surface.
"""

import argparse
import base64
import hashlib
import html as html_mod
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path

try:
    from formal_data_gate import audit as audit_formal_data
except ImportError:  # pragma: no cover
    from scripts.formal_data_gate import audit as audit_formal_data
try:
    from map_contract import map_urls
except ImportError:  # pragma: no cover
    from scripts.map_contract import map_urls
from cafe_contract import validate_cafes
from data_model import validate_records
from api_cache import ApiCache, default_cache_path
from travel_renderer import combine_bilingual_html, render_travel_scope_html
try:
    from spa_renderer import render_spa_document
except ImportError:  # pragma: no cover
    from scripts.spa_renderer import render_spa_document
from verify_product import verify as verify_product
from run_seal import REPLAY_ENV, file_sha256, record_build, seal_inputs
from local_media_gate import validate as validate_local_media, validate_section_media, validate_source_identities
# R3F（业主 2026-11-04）：run manifest 里的输入路径按登记口径写成 run 相对 POSIX，读侧统一走
# resolve_run_path（相对值以 run 根解析、绝对值照旧能用）。解析只有一把尺子，别处不许再拼一遍。
from local_media_gate import resolve_run_path
DATA_ROOT = None
ROUTE_BUDGETS = {}
BUDGET_META = {}
DURATION_DAYS = None
ALLOW_PARTIAL_TRANSLATION = False
# ZH-RELEASE-2 步1（业主 2026-11-03 裁 finding_1）：读者来源面板的机器面 source_evidence_meta
# 只能由**正式输入 dataset** 携带进来。None＝输入里根本没有这一面（与「带了但是空列表」分开记，
# 两者的处置不同：前者是没账，后者是有账但零行）；构建器绝不从十列位置面 source_evidence
# 反推它，也绝不在缺失时造一个空列表顶上去——那正是 #113 假统计的形状。
SOURCE_EVIDENCE_META = None
RUNTIME_INPUT_SHA256 = ""
RUNTIME_INPUT_PATH = ""
# ZH-RELEASE-2 步6c：正式构建那一段的零调用账本要在 main 之外也拿得到「写到哪、绑了哪些字节」，
# 所以由 main 记一次、窗口关掉后读一次。账本的**形状**（文件名／档位／绑定字段／回环解释）
# 全部读合同 renderer-contract.json::zero_call_build_window，这里不内置任何一个字符串。
BUILD_WINDOW_STATE: dict = {"output_dir": "", "artifacts": [], "argv": []}
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
from urllib.parse import quote as url_quote, urlsplit

try:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    print("ERROR: openpyxl not installed. Run: pip install openpyxl")
    sys.exit(1)


# ============================================================
# COORDINATE TRANSFORMATION (WGS84 <-> GCJ02 <-> BD09)
# ============================================================

_A = 6378245.0  # Semi-major axis
_EE = 0.00669342162296594323  # Eccentricity squared
_X_PI = math.pi * 3000.0 / 180.0


def _transform_lat(lng, lat):
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * math.pi) + 40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320.0 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng, lat):
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * math.pi) + 40.0 * math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 * math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat, lng):
    """WGS84 -> GCJ02 (Mars coordinates). For China mainland only."""
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * math.pi)
    mglat = lat + dlat
    mglng = lng + dlng
    return mglat, mglng


def gcj02_to_bd09(lat, lng):
    """GCJ02 -> BD09. For China mainland only."""
    z = math.sqrt(lng * lng + lat * lat) + 0.00002 * math.sin(lat * _X_PI)
    theta = math.atan2(lat, lng) + 0.000003 * math.cos(lng * _X_PI)
    bd_lng = z * math.cos(theta) + 0.0065
    bd_lat = z * math.sin(theta) + 0.006
    return bd_lat, bd_lng


def wgs84_to_bd09(lat, lng):
    """WGS84 -> BD09 (via GCJ02)."""
    gcj_lat, gcj_lng = wgs84_to_gcj02(lat, lng)
    return gcj02_to_bd09(gcj_lat, gcj_lng)


# ============================================================
# MAP URI GENERATORS
# ============================================================

def parse_coords(coord_str):
    """Parse 'lat,lng' string. Returns (lat, lng) floats."""
    parts = coord_str.split(",")
    if len(parts) != 2:
        return None, None
    try:
        return float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None, None


def _map_search_identity(name="", context=""):
    """Build a human-readable, disambiguated map search target."""
    values = []
    for value in (name, context, COUNTRY):
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)
    return ", ".join(values)


def gen_google_maps_uri(lat, lng, name="", place_id="", context=""):
    """Generate a Google Maps URI using identity and geographic context."""
    identity = _map_search_identity(name, context)
    query = url_quote(identity) if identity else f"{lat},{lng}"
    uri = f"https://www.google.com/maps/search/?api=1&query={query}"
    if place_id and not str(place_id).startswith("osm:"):
        uri += f"&query_place_id={url_quote(place_id)}"
    return uri


def gen_amap_uri(lat, lng, name="", context=""):
    """Generate Amap URI. Domestic markers use converted coordinates."""
    encoded_name = url_quote(_map_search_identity(name, context)) if name else ""
    if not DOMESTIC_DESTINATION:
        keyword = encoded_name or url_quote(f"{lat},{lng}")
        return f"https://uri.amap.com/search?keyword={keyword}"
    gcj_lat, gcj_lng = wgs84_to_gcj02(lat, lng)
    return f"https://uri.amap.com/marker?position={gcj_lng},{gcj_lat}&name={encoded_name}"


def gen_baidu_maps_uri(lat, lng, name="", content="", context=""):
    """Generate Baidu Maps URI. Domestic markers use converted coordinates."""
    title = url_quote(_map_search_identity(name, context)) if name else ""
    if not DOMESTIC_DESTINATION:
        keyword = title or url_quote(f"{lat},{lng}")
        return f"https://map.baidu.com/search/{keyword}/"
    bd_lat, bd_lng = wgs84_to_bd09(lat, lng)
    content_enc = url_quote(content) if content else ""
    return f"https://api.map.baidu.com/marker?location={bd_lat},{bd_lng}&title={title}&content={content_enc}&output=html&src=webapp.travelGuide"


def gen_apple_maps_uri(lat, lng, name="", context=""):
    """Generate an Apple Maps web link using identity plus coordinates."""
    identity = _map_search_identity(name, context)
    query = url_quote(identity) if identity else f"{lat},{lng}"
    return f"https://maps.apple.com/?q={query}&ll={lat},{lng}"


def gen_map_uri(platform, lat, lng, name="", content="", place_id="", context=""):
    """Generate map URI for the specified platform."""
    if platform == "google":
        return gen_google_maps_uri(lat, lng, name, place_id, context)
    elif platform == "amap":
        return gen_amap_uri(lat, lng, name, context)
    elif platform == "baidu":
        return gen_baidu_maps_uri(lat, lng, name, content, context)
    elif platform == "apple":
        return gen_apple_maps_uri(lat, lng, name, context)
    return gen_google_maps_uri(lat, lng, name, place_id, context)


# ============================================================
# DATA SECTION
# LLM: Replace the sample data below with real data collected for the target country.
# ============================================================

COUNTRY = ""  # Required from a run-local dataset or explicit CLI override.
COUNTRY_EN = ""
TRAVEL_MODE = ""  # Standard Q4: 自驾 / 非自驾
DOMESTIC_DESTINATION = False  # Set by domestic builders; overseas always audits required transport
OUTPUT_LANG = "cn"  # cn / en; the --language=both mode generates both artifacts
DEMO_MODE = False
TRANSLATION_CACHE = None

# Provider-verified identity/media supplied by the upstream Live data builder.
GOOGLE_PLACE_IDS = {}
PROVIDER_POI_IDS = {}
MAP_TARGETS = {}
# v4.2.2 §8.1 的适用性开关读的就是这个块（map_gate_v422.applicability → dataset
# ["map_link_selection"]["selection_version"]）。它以前只活在审计面：load_demo_fixture 不 hydrate、
# export_runtime_dataset 不输出，于是读者页永远判「不适用」，§8.1「dataset/DOM/href/link mode
# 不一致 = 0」只在测试里成立，交付物上那句「不一致 = 0」没有任何东西在数。门禁自己的 follow_up
# 写得很清楚：「V6 端到端候选 run 必须带本版血缘；不适用不等于通过」。994B 换一条真正执行的门。
MAP_LINK_SELECTION = {}
GOOGLE_IMAGES = {}
GOOGLE_PLACE_LOCATIONS = {}
IMAGE_COLLECTION = {}
EDITORIAL_MEDIA = []
SECTION_MEDIA = []
LOCAL_APPS = []
HERO_IMAGE = ""
HERO_VIDEO = ""
HERO_CREDIT_CN = ""
HERO_CREDIT_EN = ""
CAFE_COVERAGE = []
CAFE_CLASSIFICATION = {}
GOOGLE_MAPS_KEY = ""
LIVE_MAP_REQUESTED = False


def provider_identity_key(name, context=""):
    return f"{str(context or '').strip()}|{str(name or '').strip()}" if str(context or "").strip() else str(name or "").strip()


def provider_value(mapping, name, context="", default=None):
    scoped = provider_identity_key(name, context)
    return mapping.get(scoped, mapping.get(str(name or "").strip(), default))


def google_place_id_for(name, context=""):
    value = provider_value(GOOGLE_PLACE_IDS, name, context, "")
    return str(value).strip() if value else ""


def google_images_for(name, row, img1_idx, img2_idx, context=""):
    """Return POI-level Google images, never a global template fallback."""
    mapped = provider_value(GOOGLE_IMAGES, name, context, [])
    if isinstance(mapped, (list, tuple)) and len(mapped) >= 2:
        return str(mapped[0] or ""), str(mapped[1] or "")
    if len(row) > max(img1_idx, img2_idx):
        return str(row[img1_idx] or ""), str(row[img2_idx] or "")
    return "", ""


def authenticated_google_image_url(url):
    """Attach the runtime Google key to Places media URLs when required.

    The upstream collector normally writes the key. This closes the gap for
    payloads where a builder stripped the query string before generation.
    The key is never stored in source code; it only comes from the runtime
    command argument/environment.
    """
    value = str(url or "").strip()
    parsed = urlsplit(value)
    if parsed.netloc == 'places.googleapis.com':
        raise ValueError('Paid Places media URLs are disabled; supply verified local assets')
    return value


def image_identity(url):
    """Compare the actual image resource, ignoring cache-busting query strings."""
    value = str(url or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path}" if parsed.scheme and parsed.netloc else value


def is_synthetic_image_url(url):
    """Detect the known placeholder Unsplash ID pattern used by old builders."""
    value = str(url or "").strip()
    return bool(re.search(r"images\.unsplash\.com/photo-151000000\d+-000000000\d+", value))


def verify_remote_image(url):
    """Remote image probing is disabled in the recovered no-API generator."""
    raise ValueError('Remote image verification disabled; use local media evidence')


def validate_provider_contract():
    """Require local, source-bound assets without prescribing a paid provider."""
    if DEMO_MODE:
        return
    categories = [("HOTELS", HOTELS, 8, 9), ("RESTAURANTS", RESTAURANTS, 8, 9),
                  ("CAFES", CAFES, 8, 9),
                  ("ATTRACTIONS", effective_attractions(), 7, 8),
                  ("DIVE_SITES", effective_dive_sites(), 7, 8)]
    validate_local_media(DATA_ROOT, categories, require_complete=bool(IMAGE_COLLECTION.get("require_complete", False)))
    section_coverage = [
        ("hotels", HOTELS), ("restaurants", RESTAURANTS), ("cafes", CAFES),
        ("attractions", effective_attractions()), ("dive_sites", effective_dive_sites()),
    ]
    validate_section_media(
        DATA_ROOT, SECTION_MEDIA, section_coverage,
        require_complete=bool(IMAGE_COLLECTION.get("section_media_required", False)),
        editorial_media=EDITORIAL_MEDIA,
    )
    # 业主 2026-11-03 裁 finding_4 选 A：生成期完全离线。来源身份改读固化快照（路径由本 run 的
    # manifest 声明），这一段不再发任何网络请求；快照缺失／过期／身份不符／本地图摘要变化都在
    # local_media_gate.validate_source_identities 里按命名码阻断，构建期 external_network_attempts 仍须为 0。
    validate_source_identities(json.loads((DATA_ROOT / "asset-manifest.json").read_text(encoding="utf-8")),
                               base_dir=DATA_ROOT)


def apply_provider_overrides():
    """Hydrate the shared rows so HTML, route JSON and Excel use provider media/coordinates."""
    categories = [
        ("hotels", "HOTELS", 7, 8, 9),
        ("restaurants", "RESTAURANTS", 7, 8, 9),
        ("cafes", "CAFES", 7, 8, 9),
        ("attractions", "ATTRACTIONS", 6, 7, 8),
        ("dive_sites", "DIVE_SITES", 6, 7, 8),
    ]
    for _, global_name, coord_index, img1_index, img2_index in categories:
        rows = globals().get(global_name, []) or []
        for row in rows:
            if not isinstance(row, list) or len(row) <= img2_index or len(row) <= 1:
                continue
            name = str(row[1]).strip()
            context = str(row[0]).strip() if row else ""
            mapped_images = provider_value(GOOGLE_IMAGES, name, context, [])
            if isinstance(mapped_images, (list, tuple)) and len(mapped_images) >= 2:
                row[img1_index], row[img2_index] = authenticated_google_image_url(mapped_images[0]), authenticated_google_image_url(mapped_images[1])
            mapped_coords = provider_value(GOOGLE_PLACE_LOCATIONS, name, context, "")
            if mapped_coords and len(row) > coord_index:
                row[coord_index] = mapped_coords


def validate_image_integrity(require_images=True, verify_remote=False):
    """Reject template/media reuse before any HTML or Excel is written."""
    categories = [
        ("HOTELS", HOTELS, 8, 9),
        ("RESTAURANTS", RESTAURANTS, 8, 9),
        ("CAFES", CAFES, 8, 9),
        ("ATTRACTIONS", effective_attractions(), 7, 8),
        ("DIVE_SITES", effective_dive_sites(), 7, 8),
    ]
    seen = {}
    errors = []
    for label, rows, img1_idx, img2_idx in categories:
        for row_number, row in enumerate(rows, 1):
            name = str(row[1] if len(row) > 1 else "").strip()
            context = str(row[0]).strip() if row else ""
            mapped = provider_value(GOOGLE_IMAGES, name, context, [])
            urls = [row[img1_idx] if len(row) > img1_idx else "", row[img2_idx] if len(row) > img2_idx else ""]
            if isinstance(mapped, (list, tuple)) and len(mapped) >= 2:
                urls = [mapped[0], mapped[1]]
            identities = [identity for identity in (image_identity(url) for url in urls) if identity]
            if any(is_synthetic_image_url(url) for url in urls):
                errors.append(f"{label}[{row_number}] {name} 使用虚构图片URL，必须重新采集")
            if require_images and len(identities) < 2:
                continue
            if not identities:
                continue
            if len(set(identities)) < len(identities):
                errors.append(f"{label}[{row_number}] {name} 的两张图片实际为同一资源")
            for identity in identities:
                previous = seen.get(identity)
                if previous and previous != (label, name):
                    errors.append(f"图片跨点位/类别复用: {previous[0]}:{previous[1]} 与 {label}:{name}")
                else:
                    seen[identity] = (label, name)
    if errors:
        raise ValueError("图片完整性校验失败（已阻断错误HTML/Excel输出）：\n- " + "\n- ".join(errors[:40]) + (f"\n- ...另有 {len(errors)-40} 项" if len(errors) > 40 else ""))
    if verify_remote:
        urls = [str(row[index]).strip() for _, rows, img1, img2 in categories for row in rows
                for index in (img1, img2) if len(row) > index and str(row[index]).strip()
                and str(row[index]).strip().startswith(("http://", "https://"))]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(verify_remote_image, urls))
        failed = sum(not result[0] for result in results)
        if failed:
            raise ValueError(f"图片远程可用性校验失败：{failed}/{len(urls)} 未返回 HTTP 2xx image/*")


def extract_source_ledger_face(payload, raw_input, source_path):
    """从**已读入的输入字节＋已解析的对象**里取出机读台账面，并钉下这份字节的摘要。

    业主 2026-11-03 裁 finding_1 的两条禁令在这一个函数里落地，而且是可以单独检的：
      * 它只读 `source_evidence_meta` 这一个键——没有 SOURCE_EVIDENCE（十列位置面）参与，
        所以「从位置面重新推一遍」这条路在结构上就不存在（有 AST 源码测试钉住）；
      * 输入里没有这个键时返回 None，而不是 `[]`——「没带这一面」与「带了但是空账」
        是两种状态，回退成空列表就是把缺失伪装成「面板正常，只是没有来源」。
    形状校验（每条记录长什么样）只住在 scripts/source_projection.py；这里只管这一面在不在。

    返回 `(机器面或 None, 输入文件 SHA-256, 输入路径)`。
    """
    digest = hashlib.sha256(raw_input).hexdigest()
    face = payload.get("source_evidence_meta") if isinstance(payload, dict) else None
    if face is None:
        return None, digest, source_path
    if not isinstance(face, list):
        raise ValueError("SOURCE_LEDGER_FACE_NOT_LIST：dataset.source_evidence_meta 必须是记录列表，"
                         "收到 %r（来自 %s）；读者来源面的机器面不接受任何其他形状"
                         % (type(face).__name__, source_path))
    return list(face), digest, source_path


def load_demo_fixture(path):
    """Load a sanitized, offline fixture without touching provider APIs."""
    global COUNTRY, COUNTRY_EN, TRAVEL_MODE, DOMESTIC_DESTINATION
    global DATA_ROOT
    DATA_ROOT = Path(path).resolve().parent
    global CAFE_COVERAGE, CAFE_CLASSIFICATION, CAFES
    global DESTINATIONS, DESTINATION_COVERAGE, SOURCE_EVIDENCE, DYNAMIC_INFO
    global MAP_LINK_SELECTION
    global ROUTES, HOTELS, RESTAURANTS, CAFES, TRANSPORT, TRANSPORT_NODES, ATTRACTIONS, DIVE_SITES
    global BUDGET, PRACTICAL, WORTH_IT, LOCAL_CHAINS, PACKING, LOCAL_KNOWLEDGE, ITINERARY, GOOGLE_PLACE_IDS, PROVIDER_POI_IDS, MAP_TARGETS, GOOGLE_IMAGES, GOOGLE_PLACE_LOCATIONS, IMAGE_COLLECTION, EDITORIAL_MEDIA, SECTION_MEDIA, HERO_IMAGE, HERO_VIDEO, HERO_CREDIT_CN, HERO_CREDIT_EN, LOCAL_APPS
    global SOURCE_EVIDENCE_META, RUNTIME_INPUT_SHA256, RUNTIME_INPUT_PATH
    # 输入摘要钉在这里：先按字节读一次，哈希与解析用的是**同一份字节**——后面血缘自证指的
    # 就是这些字节，不是「盘上这会儿的样子」。
    RUNTIME_INPUT_PATH = str(Path(path).resolve())
    raw_input = Path(path).resolve().read_bytes()
    RUNTIME_INPUT_SHA256 = hashlib.sha256(raw_input).hexdigest()
    payload = json.loads(raw_input.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Demo fixture must be a JSON object")
    if not payload.get('country') or not payload.get('destinations') or not payload.get('itinerary'):
        raise ValueError('Input requires country, destinations and itinerary')
    COUNTRY = payload.get("country", COUNTRY)
    COUNTRY_EN = payload.get("country_en", COUNTRY_EN)
    TRAVEL_MODE = payload.get("travel_mode", "非自驾")
    if type(payload.get('domestic_destination')) is not bool:
        raise ValueError('domestic_destination must be an explicit boolean')
    DOMESTIC_DESTINATION = payload['domestic_destination']
    GOOGLE_PLACE_IDS = payload.get("google_place_ids", {}) or {}
    PROVIDER_POI_IDS = payload.get("provider_poi_ids", {}) or {}
    MAP_TARGETS = payload.get("map_targets", {}) or {}
    # 血缘块只带版本/哈希/实现位置，不带任何逐 target 的状态；类型不对就拒绝生成，
    # 而不是静默丢掉它——静默丢掉正是 §8.1 在交付物上空转了两轮的成因。
    raw_link_selection = payload.get("map_link_selection")
    if raw_link_selection is not None and not isinstance(raw_link_selection, dict):
        raise ValueError("map_link_selection 必须是对象（链接选择的血缘块），收到 %r"
                         % type(raw_link_selection).__name__)
    MAP_LINK_SELECTION = dict(raw_link_selection or {})
    GOOGLE_IMAGES = payload.get("google_images", {}) or {}
    GOOGLE_PLACE_LOCATIONS = payload.get("google_place_locations", {}) or {}
    IMAGE_COLLECTION = payload.get("image_collection", {}) or {}
    EDITORIAL_MEDIA = payload.get("editorial_media", []) or []
    SECTION_MEDIA = payload.get("section_media", []) or []
    LOCAL_APPS = payload.get("local_apps", []) or []
    # 机器面按输入原样携带（None＝输入里根本没有这一面；空列表＝有账但零行，两者处置不同）。
    SOURCE_EVIDENCE_META, RUNTIME_INPUT_SHA256, RUNTIME_INPUT_PATH = extract_source_ledger_face(
        payload, raw_input, str(Path(path).resolve()))
    HERO_IMAGE = str(payload.get("hero_image", "") or "")
    HERO_VIDEO = str(payload.get("hero_video", "") or "")
    HERO_CREDIT_CN = str(payload.get("hero_credit_cn", "") or "")
    HERO_CREDIT_EN = str(payload.get("hero_credit_en", "") or "")
    CAFES = payload.get('cafes', [])
    CAFE_COVERAGE = payload.get('cafe_coverage', [])
    CAFE_CLASSIFICATION = payload.get('cafe_classification', {})
    for key in (
        "destinations", "destination_coverage", "source_evidence", "dynamic_info",
        "routes", "hotels", "restaurants", "cafes", "transport", "transport_nodes", "attractions",
        "dive_sites", "budget", "practical", "worth_it", "local_chains", "packing", "local_knowledge", "itinerary",
    ):
        globals()[{
                "destinations": "DESTINATIONS", "destination_coverage": "DESTINATION_COVERAGE",
                "source_evidence": "SOURCE_EVIDENCE", "dynamic_info": "DYNAMIC_INFO",
                "routes": "ROUTES", "hotels": "HOTELS", "restaurants": "RESTAURANTS", "cafes": "CAFES",
                "transport": "TRANSPORT", "transport_nodes": "TRANSPORT_NODES", "attractions": "ATTRACTIONS", "dive_sites": "DIVE_SITES",
                "budget": "BUDGET", "practical": "PRACTICAL", "worth_it": "WORTH_IT", "local_chains": "LOCAL_CHAINS", "packing": "PACKING", "local_knowledge": "LOCAL_KNOWLEDGE", "itinerary": "ITINERARY",
            }[key]] = payload.get(key, [])
    for glob_name in ("HOTELS", "RESTAURANTS", "CAFES"):
        rows = globals().get(glob_name, [])
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, list) and len(row) > 11 and not str(row[10] or "").strip() and str(row[11] or "").strip():
                    row[10] = row[11]
                    row[11] = ""
    if "en_text_replacements" in payload and isinstance(payload["en_text_replacements"], dict):
        EN_TEXT_REPLACEMENTS.update(payload["en_text_replacements"])
    global PROSE_EN, PROSE_EN_PROVENANCE
    if isinstance(payload.get("prose_en"), dict):
        PROSE_EN.update(payload["prose_en"])
    if isinstance(payload.get("prose_en_provenance"), dict):
        PROSE_EN_PROVENANCE.update(payload["prose_en_provenance"])
    # MT-B3 tier2：显示专名表跟着输入载荷走；不在这里判断 provenance 是否合格，
    # 判定只住在 scripts/display_names.py（一处规则），构建末尾 annotate 时统一执行。
    global MACHINE_DISPLAY_NAMES, DISPLAY_NAME_PROVENANCE
    if isinstance(payload.get("machine_translated_display_name"), dict):
        MACHINE_DISPLAY_NAMES.update(payload["machine_translated_display_name"])
    if isinstance(payload.get("display_name_provenance"), dict):
        DISPLAY_NAME_PROVENANCE.update(payload["display_name_provenance"])
    global ROUTE_BUDGETS, DURATION_DAYS, BUDGET_META
    BUDGET_META = payload.get("budget_meta", {}) or {}
    # v4.2.2 V5-B（V0-L05）：这里原来会在缺汇率时直接写死 {"USD": 0.14} 并标
    # rate_verified=True——一个没有来源的常数被盖上「已核验」写进 dataset，再由英文页换算成
    # 读者看到的 $ 金额。现在生成器不做任何汇率判断：run 登记了什么就带什么，没登记就如实
    # 标 UNREGISTERED，由 budget_contract/门禁决定读者页能不能出 $。
    if not isinstance(BUDGET_META, dict):
        BUDGET_META = {}
    if "rate_status" not in BUDGET_META:
        BUDGET_META = dict(BUDGET_META)
        BUDGET_META["rate_status"] = "UNREGISTERED"
        BUDGET_META.setdefault("rate_note_cn", "本 run 未登记带来源的汇率；页面按记录币种原样显示。")
        BUDGET_META.setdefault("rate_note_en", "No sourced exchange rate registered for this run; "
                                              "amounts are shown in their recorded currency.")
    global ROUTE_BUDGETS, DURATION_DAYS
    ROUTE_BUDGETS = payload.get("route_budgets", {}) or {}
    DURATION_DAYS = payload.get("duration_days")
    apply_provider_overrides()


def effective_route_budgets():
    """V4.1.1: Return {route_name: int_total} aligned with SPA requirements."""
    res = {}
    raw = ROUTE_BUDGETS or {}
    for r in ROUTES:
        if not isinstance(r, (list, tuple)) or not r:
            continue
        name = str(r[0]).strip()
        if name in raw and isinstance(raw[name], (int, float)):
            res[name] = int(raw[name])
        elif name in raw and isinstance(raw[name], list):
            try:
                res[name] = int(sum(float(row[-1]) for row in raw[name] if isinstance(row, (list, tuple)) and row and str(row[-1]).replace(".", "", 1).isdigit()))
            except Exception:
                res[name] = 0
        if name not in res:
            val = str(r[5] if len(r) > 5 else "")
            digits = re.findall(r"\d+", val)
            res[name] = int(digits[0]) if digits else 0
    return res


def effective_duration_days():
    """V4.1.1: Return integer days duration for the journey."""
    if isinstance(DURATION_DAYS, (int, float)) and DURATION_DAYS > 0:
        return int(DURATION_DAYS)
    for r in ROUTES:
        if not isinstance(r, (list, tuple)):
            continue
        for cell in (r[1] if len(r) > 1 else "", r[3] if len(r) > 3 else ""):
            m = re.search(r"(\d+)\s*(?:天|days?)", str(cell), re.I)
            if m:
                return int(m.group(1))
    if isinstance(ITINERARY, dict) and ITINERARY:
        first_route = next(iter(ITINERARY.values()), {})
        if isinstance(first_route, dict):
            return len(first_route)
    elif isinstance(ITINERARY, list) and ITINERARY:
        days = {str(row[1]).strip() for row in ITINERARY if isinstance(row, (list, tuple)) and len(row) > 1}
        if days:
            return len(days)
    return 7


def display_name(cn, en="", lang=None):
    """Return a traveller-facing name while retaining Chinese for wayfinding."""
    lang = lang or OUTPUT_LANG
    cn, en = str(cn or "").strip(), str(en or "").strip()
    if en and en.casefold() == cn.casefold():
        return cn or en
    if lang == "en" and en:
        return f"{en} ({cn})"
    return f"{cn} ({en})" if en and lang != "en" else (cn or en)


def format_route_for_table(r):
    """Normalize route tuple into canonical [name, days, corridor, highlights, audience, budget, transport, en_name]."""
    if not isinstance(r, (list, tuple)) or not r:
        return r
    row = list(r)
    # Detect 7-element dataset format where row[3] is duration and row[1] is English name
    if len(row) >= 7 and not re.search(r"\d+\s*(?:天|days?)", str(row[1]), re.I) and re.search(r"\d+\s*(?:天|days?)", str(row[3]), re.I):
        cn_name = row[0]
        en_name = row[1]
        corridor = row[2]
        days = row[3]
        transport = row[4]
        budget = row[5]
        highlights = row[6]
        audience = row[7] if len(row) > 7 and row[7] else "深度体验 / 全景探索"
        return [cn_name, days, corridor, highlights, audience, budget, transport, en_name]
    # Legacy 8-element format where row[1] is duration
    cn_name = row[0]
    days = row[1] if len(row) > 1 else ""
    corridor = row[2] if len(row) > 2 else ""
    highlights = row[3] if len(row) > 3 else ""
    audience = row[4] if len(row) > 4 else ""
    budget = row[5] if len(row) > 5 else ""
    transport = row[6] if len(row) > 6 else ""
    en_name = row[7] if len(row) > 7 else cn_name
    return [cn_name, days, corridor, highlights, audience, budget, transport, en_name]


def format_destination_for_table(d):
    """Normalize destination tuple into canonical [cn_name, en_name, region, experience, days, season, arrival, in_route]."""
    if not isinstance(d, (list, tuple)) or not d:
        return d
    row = list(d)
    if len(row) > 8 and parse_coords(row[3])[0] is not None:
        cn_name = row[0]
        en_name = row[1]
        region = row[2]
        experience = row[5] if len(row) > 5 and row[5] else row[2]
        days = "2-3天"
        season = row[9] if len(row) > 9 and row[9] else "全年适宜"
        arrival = row[10] if len(row) > 10 and row[10] else (row[4] if len(row) > 4 else "航班/渡轮")
        in_route = "是"
        return [cn_name, en_name, region, experience, days, season, arrival, in_route]
    while len(row) < 8:
        row.append("")
    return row[:8]


HEADER_EN = {
    "中文名": "Chinese Name", "英文名": "English Name", "区域": "Region",
    "核心体验": "Key Experiences", "建议天数": "Suggested Days", "最佳季节": "Best Season",
    "到达方式": "Arrival", "是否纳入环线": "Included in Route",
    "目的地": "Destination", "状态": "Status", "是否进路线": "In Route",
    "排除/待验证原因": "Exclusion / Verification Reason", "后续动作": "Next Action", "核验日期": "Verified Date",
    "方案名称": "Route Option", "天数": "Days", "路线": "Route", "特色": "Highlights",
    "适合人群": "Best For", "预算(元,不含机票)": "Budget (CNY, flights excluded)", "交通方式": "Transport",
    "酒店名称(中文)": "Hotel (Chinese)", "酒店名称(英文)": "Hotel (English)", "类型": "Type",
    "参考价(元/晚)": "Reference Price (CNY/night)", "评分(搜索补充)": "Rating (search supplement)",
    "评价数(旧字段)": "Review Count (legacy)", "经纬度(WGS84)": "Coordinates (WGS84)",
    "Google图片1": "Google Image 1", "Google图片2": "Google Image 2", "Google Place ID": "Google Place ID",
    "特色描述": "Highlights", "餐厅名称(中文)": "Restaurant (Chinese)", "餐厅名称(英文)": "Restaurant (English)",
    "特色菜品": "Signature Dishes", "人均(元)": "Average Spend (CNY)", "地址/位置": "Address / Location",
    "咖啡馆名称(中文)": "Café (Chinese)", "咖啡馆名称(英文)": "Café (English)", "类型/特色": "Type / Highlights",
    "景点名称(中文)": "Attraction (Chinese)", "景点名称(英文)": "Attraction (English)",
    "门票/价格(元)": "Ticket / Price (CNY)", "建议门票(元)": "Suggested Ticket (CNY)", "推荐游玩时间": "Suggested Time", "描述": "Description",
    "运营公司": "Operator", "参考票价(元)": "Reference Fare (CNY)", "行程时间": "Travel Time",
    "班次频率": "Frequency", "出发地坐标": "Origin Coordinates", "目的地坐标": "Destination Coordinates",
    "备注": "Notes", "项目": "Item", "内容": "Details", "类别": "Category", "名称(中文)": "Name (Chinese)",
    "名称(英文)": "Name (English)", "经纬度": "Coordinates", "地图链接": "Map Link", "地图链接(Google Maps)": "Map Link (Google Maps)", "高德地图链接": "Amap Link", "百度地图链接": "Baidu Maps Link", "日序": "Day",
    "序号": "Sequence", "类型": "Type", "地点名称": "Place Name", "日期": "Date", "行程": "Plan",
    "住宿(元)": "Lodging (CNY)", "餐饮(元)": "Food (CNY)", "交通(元)": "Transport (CNY)",
    "活动/门票(元)": "Activities / Tickets (CNY)", "其他(元)": "Other (CNY)", "日合计(元)": "Daily Total (CNY)",
    "点位ID": "Place ID", "点位名称": "Place Name", "来源URL": "Source URL", "来源类型": "Source Type",
    "支持事实": "Supported Facts", "是否独立来源": "Independent Source", "冲突或疑问": "Conflict / Question",
    "信息ID": "Information ID", "目的地/路线": "Destination / Route", "最后核验日期": "Last Verified Date",
    "动态等级": "Change Level", "出发前复核": "Recheck Before Departure",
    "高德POI ID": "Amap POI ID", "高德评分": "Amap Rating", "高德评价数": "Amap Review Count",
    "百度UID": "Baidu UID", "百度匹配名称": "Baidu Matched Name", "百度地址": "Baidu Address",
    "百度纬度": "Baidu Latitude", "百度经度": "Baidu Longitude", "百度评分": "Baidu Rating",
    "百度评价数": "Baidu Review Count", "百度价格": "Baidu Price", "百度图片1": "Baidu Image 1",
    "百度图片2": "Baidu Image 2", "百度匹配状态": "Baidu Match Status", "高德图片1": "Amap Image 1",
    "高德图片2": "Amap Image 2", "AI推荐分": "AI Recommendation Score",
    "评价数": "Review Count", "评分": "Rating", "图片1": "Image 1", "图片2": "Image 2",
    "适合等级": "Suitable Level", "预算": "Budget", "全程": "Full Trip",
    "是否需预约": "Reservation Required", "来源/核验状态": "Source / Verification Status",
    "出发地": "Origin", "预计耗时": "Estimated Duration", "距离": "Distance", "注意事项": "Notes",
    "出发节点": "Origin Node", "到达节点": "Arrival Node", "是否适合自驾": "Suitable for Self-drive",
    "特殊风险": "Special Risks", "班次状态": "Schedule Status",
    "时刻表有效期": "Timetable Effective Period", "班次查询日期": "Schedule Checked Date",
    "官方时刻表URL": "Official Timetable URL", "官方查询/预订URL": "Official Search / Booking URL",
    "去程班次": "Outbound Departures", "返程班次": "Return Departures",
    "纳入理由": "Why It Is Included", "建议停留": "Suggested Stay", "季节/限制": "Season / Constraints",
    "预约要求": "Booking Requirement", "体力要求": "Fitness Requirement", "品牌(中文)": "Brand (Chinese)",
    "品牌(英文)": "Brand (English)", "品牌特点": "Brand Strengths", "适用场景": "Best Use Case", "附近位置": "Nearby Locations",
    "携带/当地购买": "Bring / Buy Locally", "目的地类型": "Destination Type", "准备时点": "When to Prepare",
    "复核主题": "Recheck Topic", "当地要点": "Local Notes", "出发前复核": "Pre-departure Recheck",
    "所属目的地": "Destination", "节点名称(中文)": "Node Name (Chinese)",
    "节点名称(英文)": "Node Name (English)", "节点类型": "Node Type",
    "潜点名称(中文)": "Dive Site (Chinese)", "潜点名称(英文)": "Dive Site (English)",
    "价格(元)": "Price (CNY)", "价格": "Price", "物品(中文)": "Item (Chinese)",
    "物品(英文)": "Item (English)", "说明": "Notes", "路线方案": "Route Option",
    "分类": "Category", "名称": "Name", "英文名称": "English Name", "优先级": "Priority",
    "适用目的地": "Destinations", "核心用途": "Use Cases", "覆盖范围": "Coverage",
    "当前状态": "Status", "关键限制与说明": "Limitations & Notes", "官方网站": "Official Website",
    "App Store": "App Store", "Google Play": "Google Play",
}

SHEET_EN = {
    "目的地总览": "Destinations", "目的地覆盖": "Destination Coverage", "来源证据": "Source Evidence",
    "动态信息": "Dynamic Information", "路线方案": "Route Options", "住宿推荐": "Accommodation",
    "美食推荐": "Food & Restaurants", "咖啡馆推荐": "Cafés", "交通信息": "Transport", "景点活动": "Attractions & Activities",
    "潜水活动": "Diving", "交通节点": "Transport Nodes", "预算汇总": "Budget Summary", "实用信息": "Practical Information",
    "坐标汇总": "Coordinates", "每日行程": "Daily Itinerary", "核心体验": "Key Experiences",
    "当地连锁与便捷选择": "Local Chains & Convenience", "行前准备": "Pre-trip Checklist", "当地旅行要点": "Local Travel Essentials",
    "常用APP": "Local Apps",
}


def localize_headers(headers):
    localized = [HEADER_EN.get(h, h) if OUTPUT_LANG == "en" else h for h in headers]
    if OUTPUT_LANG == "en":
        untranslated = [str(header) for header in localized if re.search(r"[\u3400-\u9fff]", str(header))]
        if untranslated:
            raise ValueError("English Excel output blocked; untranslated headers: " + ", ".join(untranslated))
    return localized


def localize_sheet_name(name):
    return SHEET_EN.get(name, name) if OUTPUT_LANG == "en" else name


# Stable labels used by the structured data layer.  These are deliberately
# explicit rather than an online machine-translation dependency so EN exports
# remain reproducible and do not silently invent factual translations.
# v4.2.1 SS2.2.2: English prose folded into the sealed input by scripts/translate_prose.py.
PROSE_EN: dict[str, str] = {}
PROSE_EN_PROVENANCE: dict = {}

# MT-B3（2026-10-31）：tier2「机器翻译显示名」表。显示名与它的逐条 provenance 都从输入载荷带进来
# （表由 MT-E 产出、provenance 由 MT-C 校验），档位语义与「不许升级身份」的禁用在
# references/display-name-channel.json 一处登记，这里不复制规则。
MACHINE_DISPLAY_NAMES: dict[str, str] = {}
DISPLAY_NAME_PROVENANCE: dict = {}

EN_TEXT_REPLACEMENTS = {
    "全年示例": "Year-round demo",
    "棉兰老东北外岛": "Northeastern Mindanao outer islands",
    "政府机构及社会团体": "Government and social organizations",
    "政府机关": "Government office", "政府机关相关": "Government-related",
    "自然/文化体验": "Nature / Culture experience", "自然/文化": "Nature / Culture",
    "历史文化": "History & culture", "历史遗迹": "Historic site",
    "风景名胜": "Scenic attraction", "旅游景点": "Tourist attraction",
    "国际料理": "International cuisine",
    "特色菜": "Signature dish", "特色描述": "Highlights", "描述": "Description",
    "购物": "Shopping", "潜水": "Diving", "景点": "Attraction", "美食": "Food", "餐厅": "Restaurant", "咖啡馆": "Café", "咖啡": "Coffee",
    "酒店": "Hotel", "住宿": "Accommodation", "交通节点": "Transport node", "交通": "Transport",
    "航班": "Flight", "轮船": "Ferry", "快艇": "Speedboat", "公交": "Bus", "出发": "Departure", "出发地": "Origin", "到达": "Arrival", "目的地": "Destination",
    "直飞": "Direct flight", "免签入境口岸": "Visa-free entry port",
    "入境口岸": "Entry port", "每天": "Daily", "班": "services",
    "正式纳入": "Included", "候选但排除": "Candidate but excluded", "待验证": "Pending verification", "待补充具体车站/港口": "Specific station/port pending",
    "待复核": "Pending review", "是": "Yes", "否": "No", "自驾": "Self-drive", "非自驾": "Non-self-drive",
    "高": "High", "中": "Medium", "低": "Low", "免费": "Free",
    "价格待出发前核验": "Price to be verified before departure",
    "门票/现场规则待出发前核验": "Ticket / on-site rules to be verified before departure",
    "日期": "Date", "行程": "Itinerary", "行程时间": "Travel time", "备注": "Notes",
    "示例": "Demo", "示范": "Demo", "演示": "Demo", "城市": "City", "全程": "Full trip", "小时": "hours", "天": "days",
    "元/晚": "CNY/night", "元": "CNY", "人均": "per person", "次": "times", "分钟": "mins",
    "海景精品度假村": "Seaview Boutique Resort", "悬崖独栋泳池别墅": "Cliffside Pool Villa",
    "热带花园精品酒店": "Tropical Garden Boutique Hotel", "生态海景潜水度假村": "Eco Marine Dive Resort",
    "海滨木屋度假村": "Beachfront Bungalow Resort", "豪华海滩度假村": "Luxury Beach Resort",
    "极简现代设计酒店": "Minimalist Design Hotel", "雨林悬崖生态庄园": "Rainforest Cliff Eco Estate",
    "悬崖海景酒店": "Cliffside Oceanfront Hotel", "精品设计酒店": "Boutique Design Hotel",
    "奢华度假村": "Luxury Resort", "海滩度假村": "Beach Resort", "精品度假村": "Boutique Resort",
    "度假酒店": "Resort Hotel", "海滨度假酒店": "Seaside Resort Hotel", "悬崖度假村": "Cliff Resort",
    "商务与机场酒店": "Airport & Business Hotel", "机场中转酒店": "Airport Transit Hotel",
    "海景奢华酒店": "Luxury Oceanview Hotel", "历史遗产酒店": "Historic Heritage Hotel",
    "山林野奢度假村": "Mountain Wilderness Resort", "亲子度假酒店": "Family Resort",
    "海边平价旅馆": "Seaside Budget Inn", "青年旅舍与胶囊": "Hostel & Capsule", "汽车旅馆": "Motel",
}


def translate_excel_text(value):
    """Translate controlled labels in an EN workbook without touching URLs/numbers."""
    if OUTPUT_LANG != "en" or not isinstance(value, str) or not value.strip():
        return value
    # Run-supplied authoritative mappings must override older cache entries
    if value in EN_TEXT_REPLACEMENTS:
        return EN_TEXT_REPLACEMENTS[value]
    if TRANSLATION_CACHE is not None:
        cached = TRANSLATION_CACHE.get_translation(value)
        if cached is not None:
            return cached

    # V4.0.7: Avoid destructive partial substring replacement on general prose/sentences
    # Only perform sub-replacement for short phrases (<= 15 chars) or multi-hop arrows
    translated = value
    if len(value) <= 15 or "→" in value or "至" in value:
        for source, target in sorted(EN_TEXT_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
            if len(source) >= 2 and source in translated:
                # Do not substitute short generic terms like "景点", "日", "月" inside longer words
                if source in {"景点", "日", "月", "天", "高", "中", "低"} and len(translated) > len(source) * 2:
                    continue
                translated = translated.replace(source, target)
    translated = translated.replace("→", " -> ").replace("至", " to ")
    if TRANSLATION_CACHE is not None:
        TRANSLATION_CACHE.put_translation(value, translated)
    return translated



def destination_name_en(name):
    for row in DESTINATIONS:
        if isinstance(row, dict) and row.get("name") == name:
            return row.get("name_en") or name
        if row and row[0] == name:
            return row[1] if len(row) > 1 and row[1] else name
    return translate_excel_text(name)


def poi_name_en(name):
    for rows in (HOTELS, RESTAURANTS, CAFES, ATTRACTIONS, DIVE_SITES):
        for row in rows:
            if len(row) > 2 and row[1] == name:
                return row[2] or name
    return translate_excel_text(name)


def route_name_en(name):
    for row in ROUTES:
        if isinstance(row, dict) and row.get("name") == name:
            return row.get("name_en") or name
        if row and row[0] == name:
            if len(row) > 7 and row[7]:
                return row[7]
            if len(row) > 1 and row[1] and not re.search(r"\d+\s*(?:天|days?)", str(row[1]), re.I):
                return row[1]
            return translate_excel_text(name)
    return translate_excel_text(name)


def effective_transport_nodes():
    """Return distinct, map-ready transport nodes with a backward-compatible fallback.

    New live/demo payloads should provide named terminals in TRANSPORT_NODES.
    Older edge-only payloads are still rendered, but their endpoint names are
    explicitly marked as needing terminal-level verification.
    """
    nodes = []
    source = TRANSPORT_NODES or []
    for row in source:
        if isinstance(row, dict):
            node = {
                "place": str(row.get("place", row.get("destination", ""))).strip(),
                "name": str(row.get("name", row.get("name_cn", ""))).strip(),
                "name_en": str(row.get("name_en", "")).strip(),
                "type": str(row.get("type", "交通节点")).strip(),
                "coords": str(row.get("coords", "")).strip(),
                "source_status": str(row.get("source_status", row.get("status", "待核验"))).strip(),
            }
        else:
            values = list(row or [])
            node = {
                "place": str(values[0] if len(values) > 0 else "").strip(),
                "name": str(values[1] if len(values) > 1 else "").strip(),
                "name_en": str(values[2] if len(values) > 2 else "").strip(),
                "type": str(values[3] if len(values) > 3 else "交通节点").strip(),
                "coords": str(values[4] if len(values) > 4 else "").strip(),
                "source_status": str(values[5] if len(values) > 5 else "待核验").strip(),
            }
        if node["place"] and node["name"] and parse_coords(node["coords"])[0] is not None:
            nodes.append(node)

    if not nodes:
        for row in TRANSPORT:
            route = str(row[0] if row else "").strip()
            origin, separator, destination = route.partition("→")
            endpoints = [(origin.strip(), row[6] if len(row) > 6 else "", "出发地"),
                         (destination.strip(), row[7] if len(row) > 7 else "", "目的地")] if separator else [(route, row[6] if len(row) > 6 else "", "交通节点")]
            for place, coords, node_type in endpoints:
                if place and parse_coords(str(coords))[0] is not None:
                    nodes.append({"place": place, "name": place, "name_en": "", "type": node_type,
                                  "coords": str(coords), "source_status": "待补充具体车站/港口"})

    unique = {}
    for node in nodes:
        unique[(node["place"], node["name"], node["coords"])] = node
    return list(unique.values())


def transport_nodes_for_edge(route_name):
    """Resolve one TRANSPORT edge to its separately mappable endpoint nodes."""
    route = str(route_name or "").strip()
    origin, separator, destination = route.partition("→")
    if not separator:
        return []
    origin, destination = origin.strip(), destination.strip()
    nodes = effective_transport_nodes()
    linked_names = ("", "")
    for row in TRANSPORT:
        if str(row[0] if row else "").strip() == route:
            linked_names = (str(row[12] if len(row) > 12 else "").strip(),
                            str(row[13] if len(row) > 13 else "").strip())
            break
    resolved = []
    for index, place in enumerate((origin, destination)):
        linked_name = linked_names[index]
        matches = [node for node in nodes if node["place"] == place and (not linked_name or node["name"] == linked_name)]
        if matches:
            resolved.append(matches[0])
    if len(resolved) == 2:
        return resolved
    for row in TRANSPORT:
        if str(row[0] if row else "").strip() != route:
            continue
        return [
            {"place": origin, "name": origin, "name_en": "", "type": "出发地", "coords": str(row[6]), "source_status": "待补充具体车站/港口"},
            {"place": destination, "name": destination, "name_en": "", "type": "目的地", "coords": str(row[7]), "source_status": "待补充具体车站/港口"},
        ]
    return []


def localize_excel_rows(kind, rows):
    """Return EN Excel rows; Chinese-name columns remain intentionally available for wayfinding."""
    if OUTPUT_LANG != "en":
        return rows
    result = []
    for source in rows:
        row = list(source)
        if kind == "destinations":
            if row: row[0] = destination_name_en(row[0])
            row[2:] = [translate_excel_text(v) for v in row[2:]]
        elif kind == "coverage":
            if row: row[0] = destination_name_en(row[0])
            row[1:] = [translate_excel_text(v) for v in row[1:]]
        elif kind == "evidence":
            if len(row) > 1: row[1] = destination_name_en(row[1])
            if len(row) > 2: row[2] = poi_name_en(row[2])
            for index in (4, 6, 7, 8, 9):
                if len(row) > index: row[index] = translate_excel_text(row[index])
        elif kind == "dynamic":
            if len(row) > 1: row[1] = destination_name_en(row[1])
            for index in range(2, len(row)):
                row[index] = translate_excel_text(row[index])
        elif kind == "routes":
            if row: row[0] = route_name_en(row[0])
            row[1:] = [translate_excel_text(v) for v in row[1:]]
        elif kind in {"hotels", "restaurants", "cafes"}:
            if row: row[0] = destination_name_en(row[0])
            if len(row) > 1: row[1] = row[2] or poi_name_en(row[1])
            if len(row) > 2: row[2] = row[2] or poi_name_en(row[1])
            skip = {1, 2, 4, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25}
            for index, value in enumerate(row):
                if index not in skip: row[index] = translate_excel_text(value)
        elif kind in {"attractions", "dives"}:
            if row: row[0] = destination_name_en(row[0])
            if len(row) > 1: row[1] = row[2] or poi_name_en(row[1])
            if len(row) > 2: row[2] = row[2] or poi_name_en(row[1])
            skip = {1, 2, 6, 7, 8, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25}
            for index, value in enumerate(row):
                if index not in skip: row[index] = translate_excel_text(value)
        elif kind == "transport":
            if row: row[0] = translate_excel_text(row[0])
            if len(row) > 18 and str(row[18]).strip():
                row[17] = row[18]
            for index in range(1, len(row)):
                row[index] = translate_excel_text(row[index])
        elif kind == "transport_nodes":
            if row: row[0] = destination_name_en(row[0])
            if len(row) > 1: row[1] = row[2] or translate_excel_text(row[1])
            if len(row) > 2: row[2] = row[2] or translate_excel_text(row[1])
            for index in (3, 5):
                if len(row) > index: row[index] = translate_excel_text(row[index])
        elif kind == "budget":
            for index in (0, 1, 2):
                if len(row) > index: row[index] = translate_excel_text(row[index])
        elif kind == "practical":
            row = [translate_excel_text(value) for value in row]
        elif kind == "coords":
            if row: row[0] = translate_excel_text(row[0])
            if len(row) > 1: row[1] = destination_name_en(row[1])
            if len(row) > 2: row[2] = row[3] or poi_name_en(row[2])
            if len(row) > 3: row[3] = row[3] or poi_name_en(row[2])
        elif kind == "itinerary":
            if row: row[0] = route_name_en(row[0])
            if len(row) > 3: row[3] = translate_excel_text(row[3])
            if len(row) > 4: row[4] = poi_name_en(row[4])
        elif kind == "local_knowledge":
            if len(row) > 0: row[0] = row[1] or translate_excel_text(row[0])
            if len(row) > 2: row[2] = row[3] or translate_excel_text(row[2])
            if len(row) > 4: row[4] = row[5] or translate_excel_text(row[4])
            if len(row) > 6: row[6] = translate_excel_text(row[6])
            row = [value for index, value in enumerate(row) if index not in {1, 3, 5}]
        elif kind == "worth_it":
            if row: row[0] = destination_name_en(row[0])
            if len(row) > 1: row[1] = row[2] or poi_name_en(row[1])
            for index in range(3, len(row)):
                row[index] = translate_excel_text(row[index])
        elif kind == "local_chains":
            if row: row[0] = destination_name_en(row[0])
            if len(row) > 1: row[1] = row[2] or translate_excel_text(row[1])
            for index in range(3, len(row)):
                row[index] = translate_excel_text(row[index])
        elif kind == "packing":
            if row: row[0] = translate_excel_text(row[0])
            if len(row) > 1: row[1] = row[2] or translate_excel_text(row[1])
            for index in range(3, len(row)):
                row[index] = translate_excel_text(row[index])
        elif kind == "local_apps":
            if row:
                row[0] = translate_excel_text(row[0])
                if len(row) > 1: row[1] = row[2] or row[1]
                if len(row) > 4:
                    dest_items = [destination_name_en(d.strip()) for d in str(row[4]).split(",") if d.strip()]
                    row[4] = ", ".join(dest_items)
                if len(row) > 6: row[6] = translate_excel_text(row[6])
                if len(row) > 7: row[7] = translate_excel_text(row[7])
        result.append(row)
    return result


def assert_english_excel_rows(rows_by_kind):
    """Fail the EN build if a non-Chinese-name delivery cell still contains CJK."""
    if OUTPUT_LANG != "en":
        return
    cjk = re.compile(r"[\u3400-\u9fff]")
    problems = []
    for kind, rows in rows_by_kind.items():
        for row_number, row in enumerate(rows, 2):
            for index, value in enumerate(row):
                if kind == "destinations" and index == 0:
                    continue
                if kind in {"hotels", "restaurants", "cafes", "attractions", "dives"} and index == 1:
                    continue
                if kind in {"hotels", "restaurants", "cafes", "attractions", "dives"} and index == 2:
                    continue
                if kind == "transport_nodes" and index in {1, 2}:
                    continue
                if kind == "coords" and index == 2:
                    continue
                if kind in {"worth_it", "local_chains", "packing"} and index in {1, 2}:
                    continue
                if kind == "local_apps" and index in {1, 2, 4}:
                    continue
                if isinstance(value, str) and not value.startswith("http") and cjk.search(value):
                    problems.append(f"{kind}!{row_number}:{index + 1}")
    if problems:
        if ALLOW_PARTIAL_TRANSLATION or os.environ.get("TRAVEL_SCOPE_ALLOW_RESEARCH_EN") == "1":
            print(f"[WARNING] English Excel output contains untranslated dynamic cells ({len(problems)}): " + ", ".join(problems[:10]))
            return
        raise ValueError("English Excel output blocked; untranslated dynamic cells: " + ", ".join(problems[:20]))

def destination_display(name):
    for row in DESTINATIONS:
        if isinstance(row, dict) and row.get("name") == name:
            return display_name(row.get("name", ""), row.get("name_en", ""))
        if row and row[0] == name:
            return display_name(row[0], row[1] if len(row) > 1 else "")
    return name


def route_display(name):
    """Localize route labels while keeping the Chinese route key stable."""
    for row in ROUTES:
        if isinstance(row, dict) and row.get("name") == name:
            return display_name(row.get("name", ""), row.get("name_en", ""))
        if row and row[0] == name:
            return display_name(row[0], row[7] if len(row) > 7 else "")
    return name


def poi_display_html(item):
    """Render English first while retaining Chinese for wayfinding."""
    cn = html_mod.escape(str(item.get("cn", "")))
    en = html_mod.escape(str(item.get("en", "")))
    if OUTPUT_LANG == "en" and en:
        return f"{en} <span class=\"cn\">({cn})</span>"
    return f"{cn} <span class=\"en\">{en}</span>" if en else cn


def validate_english_dynamic_labels(destination_names):
    """Block incomplete EN output instead of silently publishing Chinese labels."""
    if OUTPUT_LANG != "en":
        return
    destination_en = {}
    for row in DESTINATIONS:
        if isinstance(row, dict):
            destination_en[row.get("name", "")] = row.get("name_en", "")
        elif row:
            destination_en[row[0]] = row[1] if len(row) > 1 else ""
    missing_destinations = [name for name in destination_names if not str(destination_en.get(name, "")).strip()]
    missing_routes = []
    for row in ROUTES:
        if not row:
            continue
        route_name = row.get("name", "") if isinstance(row, dict) else row[0]
        has_english = row.get("name_en", "") if isinstance(row, dict) else (row[7] if len(row) > 7 else "")
        if not str(has_english).strip():
            missing_routes.append(str(route_name))
    if missing_destinations or missing_routes:
        problems = []
        if missing_destinations:
            problems.append("destinations missing name_en: " + ", ".join(missing_destinations[:20]))
        if missing_routes:
            problems.append("routes missing name_en: " + ", ".join(missing_routes[:20]))
        if ALLOW_PARTIAL_TRANSLATION or os.environ.get("TRAVEL_SCOPE_ALLOW_RESEARCH_EN") == "1":
            print(f"[WARNING] English output incomplete: " + "; ".join(problems))
            return
        raise ValueError("English output blocked: " + "; ".join(problems))


def country_display(lang=None):
    return COUNTRY_EN if (lang or OUTPUT_LANG) == "en" and COUNTRY_EN else COUNTRY


def visual_theme():
    """Select the visual system from the majority of route/content signals.

    Theme rules and source fields are external configuration. An explicit
    TRAVEL_SCOPE_THEME remains available for controlled preview runs, while
    normal generation uses all route and module data instead of only the
    country/destination names.
    """
    config_path = Path(__file__).resolve().parents[1] / "references" / "theme-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    themes = config.get("themes", {})
    requested = os.environ.get("TRAVEL_SCOPE_THEME", "auto").strip().lower()
    if requested in themes:
        return requested, themes[requested].get("label", requested), {"mode": "explicit", "scores": {requested: 1}}

    source_values = {
        "country": [COUNTRY, COUNTRY_EN],
        "destinations": DESTINATIONS,
        "itinerary": ITINERARY,
        "attractions": effective_attractions(),
        "dive_sites": effective_dive_sites(),
        "transport_nodes": effective_transport_nodes(),
        "restaurants": RESTAURANTS,
        "cafes": CAFES,
        "local_knowledge": LOCAL_KNOWLEDGE,
        "worth_it": WORTH_IT,
    }
    scores = {name: 0 for name in themes}
    matched = {name: [] for name in themes}
    for name, data in themes.items():
        sources = data.get("match_sources", list(source_values))
        corpus = " ".join(
            str(value)
            for source in sources
            for value in source_values.get(source, [])
        ).lower()
        for keyword in data.get("keywords", []):
            hits = corpus.count(str(keyword).lower())
            if hits:
                scores[name] += hits
                matched[name].append({"keyword": str(keyword), "hits": hits})
    selected = max(scores, key=scores.get) if scores and max(scores.values()) > 0 else config.get("default", "ocean")
    evidence = {
        "mode": "auto",
        "scores": scores,
        "matched_keywords": matched,
        "selected": selected,
        "rule": "select the highest-scoring theme from configured route and module fields",
    }
    return selected, themes.get(selected, {}).get("label", selected), evidence


def visual_theme_media(theme_name):
    config_path = Path(__file__).resolve().parents[1] / "references" / "theme-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return dict(config.get("themes", {}).get(theme_name, {}))

def effective_travel_mode():
    """Normalize missing/invalid Q4 conservatively to non-self-drive."""
    return TRAVEL_MODE if TRAVEL_MODE in {"自驾", "非自驾"} else "非自驾"


def validate_transport_mode_contract(domestic=None, travel_mode=None):
    """Return deterministic transport-branch errors from external policy."""
    policy_path = Path(__file__).parent.parent / "references" / "transport-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    domestic = DOMESTIC_DESTINATION if domestic is None else bool(domestic)
    travel_mode = effective_travel_mode() if travel_mode is None else str(travel_mode).strip()
    key = ("domestic" if domestic else "international") + "_" + ("self_drive" if travel_mode == "自驾" else "non_self_drive")
    if key not in policy["modes"]:
        return [f"交通分支不存在配置: {key}"]
    if travel_mode not in {"自驾", "非自驾"}:
        return [f"交通模式无效: {travel_mode}"]
    if not TRANSPORT:
        return []
    if DEMO_MODE:
        return []
    yes_values = set(policy["boolean_values"]["yes"])
    no_values = set(policy["boolean_values"]["no"])
    schedule_policy = policy["schedule"]
    schedule_indexes = schedule_policy["field_indexes"]
    allowed_schedule_statuses = set(schedule_policy["statuses"])
    errors = []
    for index, row in enumerate(TRANSPORT, 1):
        if len(row) < 24:
            errors.append(f"TRANSPORT[{index}] 缺少24字段，无法核验交通方式与班次状态")
            continue
        if str(row[14]).strip() not in yes_values | no_values:
            errors.append(f"TRANSPORT[{index}] 是否适合自驾必须明确为是/否")
        if travel_mode == "自驾":
            if not str(row[15]).strip():
                errors.append(f"TRANSPORT[{index}] 自驾分支缺少特殊风险")
        else:
            for field_index, label in ((1, "交通方式"), (4, "预计耗时"), (5, "班次频率"), (10, "是否需预约"), (12, "出发节点"), (13, "到达节点")):
                if not str(row[field_index]).strip():
                    errors.append(f"TRANSPORT[{index}] {key} 缺少{label}")
        status = str(row[schedule_indexes["status"]]).strip()
        if status not in allowed_schedule_statuses:
            errors.append(f"TRANSPORT[{index}] 班次状态无效: {status}")
            continue
        if not str(row[schedule_indexes["checked_at"]]).strip():
            errors.append(f"TRANSPORT[{index}] 班次状态缺少查询日期")
        effective_cn = str(row[schedule_indexes["effective_period_cn"]]).strip()
        effective_en = str(row[schedule_indexes["effective_period_en"]]).strip()
        timetable_url = str(row[schedule_indexes["timetable_url"]]).strip()
        outbound = str(row[schedule_indexes["outbound_departures"]]).strip()
        return_times = str(row[schedule_indexes["return_departures"]]).strip()
        if status in {"exact_date_verified", "published_reference"} and (not effective_cn or not effective_en or not timetable_url):
            errors.append(f"TRANSPORT[{index}] 已发布班次缺少双语有效期或官方时刻表URL")
        if status == "exact_date_verified" and not outbound:
            errors.append(f"TRANSPORT[{index}] 指定日期已核验但未记录去程班次")
        if status in {"future_unpublished", "unverified", "on_demand"} and (outbound or return_times):
            errors.append(f"TRANSPORT[{index}] {status} 不得填入冒充的确定班次")
    return errors

# Sheet 1: 目的地总览
# [中文名, 英文名, 区域, 核心体验, 建议天数, 最佳季节, 到达方式, 是否纳入环线]
DESTINATIONS = [
    ["演示城市", "Demo City", "演示区域", "历史文化/本地美食/城市漫步", "2天", "示例季节", "示例交通", "是"],
    # ... (LLM: add all destinations here)
]

# Sheet: 目的地覆盖
# [目的地, 状态, 是否进路线, 排除/待验证原因, 后续动作, 核验日期]
# 状态: 正式纳入 / 候选但排除 / 待验证
DESTINATION_COVERAGE = [
    ["演示城市", "正式纳入", "是", "与主线顺路", "收集酒店/餐厅/景点", ""],
    # ... (LLM: add every discovered major destination; do not silently omit candidates)
]

# Sheet: 来源证据
# [点位ID, 目的地, 点位名称, 来源URL, 来源类型, 核验日期, 支持事实, 是否独立来源, 冲突或疑问, 状态]
# 来源类型: 官方 / 地图平台 / 攻略 / 点评 / 新闻 / 交通运营方
# 支持事实: 存在 / 地址 / 营业 / 评分 / 价格 / 图片 / 坐标
SOURCE_EVIDENCE = [
    ["hotel-001", "演示城市", "示例酒店", "https://example.com/source", "地图平台", "", "存在/地址", "是", "", "待复核"],
    # ... (LLM: retain the full evidence ledger for every verified point)
]

# Sheet: 动态信息
# [信息ID, 目的地/路线, 项目, 内容, 最后核验日期, 动态等级, 出发前复核, 来源URL, 状态]
# 动态等级: 低 / 中 / 高；出发前复核: 是 / 否
DYNAMIC_INFO = [
    ["dynamic-001", "演示城市", "景点开放时间", "待核验", "", "高", "是", "https://example.com/source", "待复核"],
    # ... (LLM: add prices, schedules, hours, visa, safety and other changing facts)
]

# Sheet: 路线方案
# [方案名, 天数, 路线, 特色, 适合人群, 预算(元,不含机票), 交通方式, 英文方案名]
ROUTES = [
    ["方案A: 示例环线", "12天", "目的地A→目的地B→目的地C→目的地A", "特色描述", "适合人群", "5,000-7,000", "交通方式"],
    # ... (LLM: add all routes here)
]

# Sheet: 住宿推荐
# [目的地, 酒店名称(中文), 酒店名称(英文), 类型, 参考价(元/晚), 评分, 评价数, 经纬度, 图片URL1, 图片URL2, 特色描述]
# 评分格式(国内): 高德结构化评分；百度/搜索/AI字段独立保存
# 评分格式(海外): "Google:4.3"
# 正式 POI 密度由 references/run-quality-policy.json 的 Q7 规则统一控制。
HOTELS = [
    ["演示城市", "示例酒店", "Example Hotel", "4星酒店", "500", "示例评分", "1000", "39.9000,116.4000", "", "", "特色描述"],
    # ... (schema example only; live rows come from the run-local dataset)
]
AI_RECOMMENDATIONS = {}

# Sheet: 美食推荐
# [目的地, 餐厅名称(中文), 餐厅名称(英文), 特色菜品, 人均(元), 评分, 评价数, 经纬度, 图片URL1, 图片URL2, 地址/位置]
RESTAURANTS = [
    ["演示城市", "示例餐厅", "Example Restaurant", "特色菜", "50-80", "示例评分", "500", "39.9100,116.4100", "", "", "地址"],
    # ... (schema example only; live rows come from the run-local dataset)
]

# Sheet: 交通信息
# [路线, 交通方式, 运营公司, 参考票价(元), 行程时间, 班次频率, 出发地坐标,
# 目的地坐标, 备注, 距离, 是否需预约, 来源/核验状态, 出发节点, 到达节点,
# 是否适合自驾, 特殊风险, 班次状态, 有效期(中文), 有效期(英文), 查询日期,
# 官方时刻表URL, 官方查询/预订URL, 去程班次(|分隔), 返程班次(|分隔)]
# 班次状态来自 references/transport-policy.json。未来日期尚未发布时保留空班次，
# 不得把当前或历史时刻表冒充为指定日期班次。
TRANSPORT = [
    ["城市A→城市B", "航班", "Example Airlines", "100-400", "1.5h", "每天5班", "10.0,123.0", "9.0,120.0", "备注"],
    # ... (LLM: add all transport routes here)
]

# Sheet: 景点活动
# [目的地, 景点名称(中文), 景点名称(英文), 类型, 门票/价格(元), 评分, 经纬度, 图片URL1, 图片URL2, 推荐游玩时间, 描述]
ATTRACTIONS = [
    ["演示城市", "示例景点", "Example Attraction", "历史遗迹", "免费", "示例评分", "39.9200,116.4200", "", "", "1小时", "描述"],
    # ... (schema example only; live rows come from the run-local dataset)
]

# Sheet: 潜水活动 (如有)
# [目的地, 潜点名称(中文), 潜点名称(英文), 类型, 价格(元), 评分, 经纬度, 图片URL1, 图片URL2, 适合等级, 描述]
DIVE_SITES = [
    # ... (LLM: add dive sites if applicable)
]

# Sheet: 咖啡馆推荐（仅在有可靠结果时生成；不强行补齐每个目的地）
# [目的地, 咖啡馆名称(中文), 咖啡馆名称(英文), 类型/特色, 人均(元), 评分, 评价数, 经纬度, 图片URL1, 图片URL2, 地址/位置]
CAFES = []

# Optional transport-node layer.  Each node is independently searchable and
# mappable; TRANSPORT above remains the detailed route-edge table.
# [所属目的地, 节点名称(中文), 节点名称(英文), 节点类型, 经纬度, 来源/核验状态]
TRANSPORT_NODES = []


TRUE_DIVE_TERMS = (
    "潜水", "浮潜", "水肺", "潜点", "scuba", "snorkel", "diving", "dive site"
)


def is_true_dive(row):
    """Return True only for actual diving/snorkelling records, not generic water activities."""
    if not row:
        return False
    text = " ".join(str(value or "") for value in row[:4] + row[9:])
    lowered = text.casefold()
    return any(term in lowered for term in TRUE_DIVE_TERMS)


def effective_dive_sites():
    return [row for row in DIVE_SITES if is_true_dive(row)]


def effective_attractions():
    """Merge non-diving records mistakenly supplied in DIVE_SITES into attractions."""
    moved = []
    for row in DIVE_SITES:
        if is_true_dive(row):
            continue
        if len(row) >= 12:
            suggested_time = row[9]
            description = f"{row[10]} | {row[11]}"
        else:
            suggested_time = ""
            description = f"{row[9]} | {row[10]}"
        moved.append([
            row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8],
            suggested_time, description
        ])
    return list(ATTRACTIONS) + moved


def effective_itinerary():
    """Reclassify water activities in routes when they are not actual dives."""
    non_dive_names = {row[1] for row in DIVE_SITES if not is_true_dive(row)}
    normalized = []
    for item in ITINERARY:
        row = list(item)
        if len(row) > 4 and row[4] in non_dive_names and str(row[3]).strip() == "潜水":
            row[3] = "景点"
        normalized.append(row)
    return normalized


def validate_content_modules():
    """Validate optional modules without inventing content when they are empty."""
    policy_path = Path(__file__).parent.parent / "references" / "content-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    invalid = set(policy.get("invalid_statuses", []))
    errors = []
    for module_name, config in policy["modules"].items():
        rows = globals().get(module_name, []) or []
        for index, row in enumerate(rows, 1):
            if not isinstance(row, list) or len(row) < int(config["length"]):
                errors.append(f"{module_name}[{index}] 字段数量不足")
                continue
            for field_index in config.get("required_indexes", []):
                if not str(row[field_index]).strip():
                    errors.append(f"{module_name}[{index}] 必填字段为空: {field_index}")
            status_index = int(config["length"]) - 1
            if str(row[status_index]).strip() in invalid:
                errors.append(f"{module_name}[{index}] 来源/核验状态不合格")
        topic_groups = config.get("required_topic_groups", [])
        if topic_groups and rows:
            available_topics = " ".join(
                " ".join(str(value).strip() for value in row[:2])
                for row in rows if isinstance(row, list)
            ).lower()
            for group in topic_groups:
                if not any(str(keyword).lower() in available_topics for keyword in group):
                    errors.append(f"{module_name} 缺少必需主题: {'/'.join(group[:2])}")
        required_keywords = config.get("required_keywords_anywhere", [])
        if required_keywords and rows:
            available_content = " ".join(
                " ".join(str(value).strip() for value in row)
                for row in rows if isinstance(row, list)
            ).lower()
            for group in required_keywords:
                if not any(str(keyword).lower() in available_content for keyword in group):
                    errors.append(f"{module_name} 缺少必需内容: {'/'.join(group[:2])}")
    return errors

# Sheet: 预算汇总 (示例路线)
# [天数, 日期, 行程, 住宿(元), 餐饮(元), 交通(元), 活动/门票(元), 其他(元), 日合计(元)]
BUDGET = [
    ["Day 1", "日期", "行程", 500, 80, 100, 0, 30, 710],
    # ... (LLM: add budget for the recommended route, numeric values as int, NOT string)
    ["合计", "N天", "全程", "=SUM(D2:D13)", "=SUM(E2:E13)", "=SUM(F2:F13)", "=SUM(G2:G13)", "=SUM(H2:H13)", "=SUM(I2:I13)"],
]

# Sheet: 实用信息
# [项目, 内容]
PRACTICAL = [
    ["签证政策", "签证信息"],
    ["汇率", "汇率信息"],
    ["SIM卡", "SIM卡信息"],
    ["最佳季节", "季节信息"],
    ["安全提示", "安全信息"],
    ["紧急联系", "紧急联系方式"],
    # ... (LLM: add all practical info here)
]

# Optional content modules. Empty means no reliable records were collected;
# the generator must not invent rows merely to create a section.
# WORTH_IT: [destination, name_cn, name_en, why, best_for, stay_time, season, booking, effort, source_status]
WORTH_IT = []
# LOCAL_CHAINS: [destination, brand_cn, brand_en, type, strengths, use_case, price, nearby_locations, source_status]
LOCAL_CHAINS = []
# PACKING: [category, item_cn, item_en, bring_or_buy, destination_type, timing, notes, source_status]
PACKING = []
# LOCAL_KNOWLEDGE: [topic_cn, topic_en, notes_cn, notes_en, recheck_cn,
# recheck_en, source_status]. Empty means no reliable local-notes records.
LOCAL_KNOWLEDGE = []

# Sheet: 每日行程 (用于地图路线连线, 仅推荐1-2条主路线)
# [方案名, 日序, 序号, 点位类型, 点位名称, 经纬度]
# 方案名: 对应ROUTES中的方案名
# 日序: "Day 1", "Day 2", ...
# 序号: 1, 2, 3, ... (每天内部的访问顺序)
# 点位类型: 景点/餐厅/酒店/交通
# 点位名称: 必须与HOTELS/RESTAURANTS/ATTRACTIONS中的名称一致(用于关联图片)
# 经纬度: WGS84格式 "纬度,经度"
ITINERARY = [
    # ["推荐路线", "Day 1", 1, "景点", "示例景点", "10.2935,123.9010"],
    # ["推荐路线", "Day 1", 2, "餐厅", "示例餐厅", "10.3000,123.9000"],
    # ["推荐路线", "Day 1", 3, "酒店", "示例酒店", "10.2913,123.9494"],
]

# Sheet: 每日行程 (用于地图路线连线, 仅推荐1-2条主路线)
# [方案名, 日序, 序号, 点位类型, 点位名称, 经纬度]
# 方案名: 对应ROUTES中的方案名
# 日序: "Day 1", "Day 2", ...
# 序号: 1, 2, 3, ... (每天内部的访问顺序)
# 点位类型: 景点/餐厅/酒店/交通
# 点位名称: 必须与HOTELS/RESTAURANTS/ATTRACTIONS中的名称一致(用于关联图片)
# 经纬度: WGS84格式 "纬度,经度"
ITINERARY = [
    # ["推荐路线", "Day 1", 1, "景点", "示例景点", "10.2935,123.9010"],
    # ["推荐路线", "Day 1", 2, "餐厅", "示例餐厅", "10.3000,123.9000"],
    # ["推荐路线", "Day 1", 3, "酒店", "示例酒店", "10.2913,123.9494"],
]


# ============================================================
# EXCEL GENERATION
# ============================================================

def _normalize_xlsx_bytes(path, stamp):
    """Freeze the workbook container so a replay reproduces the exact bytes.

    openpyxl overwrites dcterms:modified with datetime.now() during save, and the
    zip local headers carry the wall clock. Both make the delivered workbook
    un-attestable by replay_build.py, so the container is rewritten to a single
    seal-derived timestamp.
    """
    import io
    import zipfile
    path = Path(path)
    date_time = (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, max(0, stamp.second))
    rendered = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = path.read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as source:
        infos = source.infolist()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
            for info in infos:
                data = source.read(info.filename)
                if info.filename == "docProps/core.xml":
                    text = data.decode("utf-8")
                    text = re.sub(r"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                                  lambda m: m.group(1) + rendered + m.group(2), text)
                    text = re.sub(r"(<dcterms:created[^>]*>)[^<]*(</dcterms:created>)",
                                  lambda m: m.group(1) + rendered + m.group(2), text)
                    data = text.encode("utf-8")
                frozen = zipfile.ZipInfo(info.filename, date_time=date_time)
                frozen.compress_type = info.compress_type or zipfile.ZIP_DEFLATED
                frozen.external_attr = info.external_attr
                frozen.internal_attr = info.internal_attr
                frozen.create_system = info.create_system
                target.writestr(frozen, data)
    path.write_bytes(buffer.getvalue())


SEAL_TIMESTAMP_ENV = "TRAVEL_SCOPE_SEAL_SEALED_AT"


def _seal_timestamp():
    """Workbook timestamp pinned to the input seal so a replay reproduces bytes."""
    from datetime import datetime
    raw = os.environ.get(SEAL_TIMESTAMP_ENV, "").strip()
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            raise ValueError(f"{SEAL_TIMESTAMP_ENV} 不是合法 ISO 时间: {raw!r}")
    return datetime.now().astimezone().replace(tzinfo=None)


def generate_excel(output_path, include_research=True):
    """Generate a research or delivery workbook from the shared data section."""
    wb = openpyxl.Workbook()
    # openpyxl stamps wall-clock time by default, which makes the workbook
    # irreproducible and therefore un-attestable by replay_build.py.
    wb.properties.created = _seal_timestamp()
    wb.properties.modified = _seal_timestamp()
    excel_rows = {}

    header_font = Font(name='Microsoft YaHei', bold=True, size=11, color='FFFFFF')
    header_fill = PatternFill(start_color='1A73E8', end_color='1A73E8', fill_type='solid')
    cell_font = Font(name='Microsoft YaHei', size=10)
    wrap_align = Alignment(wrap_text=True, vertical='top')
    thin_border = Border(
        left=Side(style='thin', color='D0D0D0'),
        right=Side(style='thin', color='D0D0D0'),
        top=Side(style='thin', color='D0D0D0'),
        bottom=Side(style='thin', color='D0D0D0')
    )

    def _coerce_numeric(val):
        if isinstance(val, (int, float)):
            return val
        if isinstance(val, str):
            s = val.strip()
            if not s or any(ch in s for ch in (",", "-", "/", ":", "°", "¥", "$", "元", "比索", "RM", "IDR")):
                return val
            if re.fullmatch(r"^-?\d+$", s) and (len(s) == 1 or not s.startswith("0")):
                try:
                    return int(s)
                except ValueError:
                    pass
            elif re.fullmatch(r"^-?\d+\.\d+$", s):
                try:
                    return float(s)
                except ValueError:
                    pass
        return val

    def write_sheet(ws, headers, data, col_widths=None):
        ws.title = localize_sheet_name(ws.title)
        headers = localize_headers(headers)
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = thin_border
        for row_idx, row_data in enumerate(data, 2):
            for col_idx, value in enumerate(row_data, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=_coerce_numeric(value))
                cell.font = cell_font
                cell.alignment = wrap_align
                cell.border = thin_border
        if col_widths:
            for col_idx, width in enumerate(col_widths, 1):
                ws.column_dimensions[get_column_letter(col_idx)].width = width
        ws.freeze_panes = 'A2'

    overseas_output = _is_overseas()

    def clean_score(val):
        s = str(val or "").strip()
        if any(w in s.lower() for w in ("booking", "agoda", "tripadvisor", "dive_center")):
            return "—"
        return s or "—"

    def clean_review_count(val):
        s = str(val or "").strip()
        if not s or s in ("0", "None"):
            return "—"
        return s

    def international_poi_rows(rows, img1_idx, img2_idx, desc_idx):
        enriched = []
        for row in rows:
            name = row[1] if len(row) > 1 else ""
            context = row[0] if row else ""
            img1, img2 = google_images_for(name, row, img1_idx, img2_idx, context)
            pid = google_place_id_for(name, context)
            dest = row[0] if len(row) > 0 else ""
            cn = row[1] if len(row) > 1 else ""
            en = row[2] if len(row) > 2 else ""
            sub_type = row[3] if len(row) > 3 else ""
            price = row[4] if len(row) > 4 else ""
            rating = clean_score(row[5] if len(row) > 5 else "")
            count = clean_review_count(row[6] if len(row) > 6 else "")
            coords = row[7] if len(row) > 7 else ""
            desc = row[desc_idx] if len(row) > desc_idx else ""
            if not str(desc).strip() and len(row) > desc_idx + 1 and str(row[desc_idx + 1]).strip():
                desc = row[desc_idx + 1]
            enriched.append([dest, cn, en, sub_type, price, rating, count, coords, img1, img2, desc, pid])
        return enriched

    def international_attraction_rows(rows):
        enriched = []
        for row in rows:
            name = row[1] if len(row) > 1 else ""
            context = row[0] if row else ""
            img1, img2 = google_images_for(name, row, 7, 8, context)
            pid = google_place_id_for(name, context)
            dest = row[0] if len(row) > 0 else ""
            cn = row[1] if len(row) > 1 else ""
            en = row[2] if len(row) > 2 else ""
            sub_type = row[3] if len(row) > 3 else ""
            price = row[4] if len(row) > 4 else ""
            rating = clean_score(row[5] if len(row) > 5 else "")
            coords = row[6] if len(row) > 6 else ""
            duration = row[9] if len(row) > 9 else ""
            desc = row[10] if len(row) > 10 else ""
            enriched.append([dest, cn, en, sub_type, price, rating, coords, img1, img2, duration, desc, pid])
        return enriched

    def provider_rows(rows, img1_idx, img2_idx):
        if not overseas_output:
            normalized = []
            for row in rows:
                r = list(row)
                if len(r) > 11 and not str(r[10] or "").strip() and str(r[11] or "").strip():
                    r[10] = r[11]
                    r[11] = ""
                normalized.append(r)
            return normalized
        enriched = []
        for row in rows:
            name = row[1] if len(row) > 1 else ""
            context = row[0] if row else ""
            img1, img2 = google_images_for(name, row, img1_idx, img2_idx, context)
            enriched.append(list(row) + [''] * max(0, 26 - len(row)) + [img1, img2, google_place_id_for(name, context)])
        return enriched

    def provider_headers(headers):
        return list(headers) + (["Google图片1", "Google图片2", "Google Place ID"] if overseas_output else [])

    # Sheet 1: 目的地总览
    ws1 = wb.active
    ws1.title = '目的地总览'
    excel_rows['destinations'] = localize_excel_rows('destinations', [format_destination_for_table(d) for d in DESTINATIONS])
    write_sheet(ws1,
        ['中文名', '英文名', '区域', '核心体验', '建议天数', '最佳季节', '到达方式', '是否纳入环线'],
        [r[:8] for r in excel_rows['destinations']], [12, 18, 12, 30, 8, 14, 22, 12])

    if include_research:
        # Research Sheet 2: 目的地覆盖
        ws2 = wb.create_sheet('目的地覆盖')
        excel_rows['coverage'] = localize_excel_rows('coverage', DESTINATION_COVERAGE)
        write_sheet(ws2,
            ['目的地', '状态', '是否进路线', '排除/待验证原因', '后续动作', '核验日期'],
            excel_rows['coverage'], [20, 16, 12, 36, 28, 14])

        # Research Sheet 3: 来源证据
        ws3 = wb.create_sheet('来源证据')
        excel_rows['evidence'] = localize_excel_rows('evidence', SOURCE_EVIDENCE)
        write_sheet(ws3,
            ['点位ID', '目的地', '点位名称', '来源URL', '来源类型', '核验日期', '支持事实', '是否独立来源', '冲突或疑问', '状态'],
            excel_rows['evidence'], [16, 16, 24, 60, 18, 14, 26, 14, 30, 14])

        # Research Sheet 4: 动态信息
        ws4 = wb.create_sheet('动态信息')
        excel_rows['dynamic'] = localize_excel_rows('dynamic', DYNAMIC_INFO)
        write_sheet(ws4,
            ['信息ID', '目的地/路线', '项目', '内容', '最后核验日期', '动态等级', '出发前复核', '来源URL', '状态'],
            excel_rows['dynamic'], [16, 20, 22, 42, 16, 12, 14, 60, 14])

    # Delivery/Research next sheet: 路线方案
    ws5 = wb.create_sheet('路线方案')
    excel_rows['routes'] = localize_excel_rows('routes', [format_route_for_table(r) for r in ROUTES])
    write_sheet(ws5,
        ['方案名称', '天数', '路线', '特色', '适合人群', '预算(元,不含机票)', '交通方式'],
        [r[:7] for r in excel_rows['routes']], [20, 14, 40, 28, 18, 16, 14])

    # Sheet 6: 住宿推荐
    ws6 = wb.create_sheet('住宿推荐')
    if overseas_output:
        hotel_headers = ['目的地', '酒店名称(中文)', '酒店名称(英文)', '类型', '参考价(元/晚)', '评分', '评价数', '经纬度(WGS84)', 'Google图片1', 'Google图片2', '特色描述', 'Google Place ID']
        excel_rows['hotels'] = localize_excel_rows('hotels', international_poi_rows(HOTELS, 8, 9, 10))
        write_sheet(ws6, hotel_headers, excel_rows['hotels'], [12, 22, 30, 12, 14, 12, 12, 18, 30, 30, 35, 24])
    else:
        hotel_headers = ['目的地', '酒店名称(中文)', '酒店名称(英文)', '类型', '参考价(元/晚)', '评分(搜索补充)', '评价数(旧字段)', '经纬度(WGS84)', '高德图片1', '高德图片2', '特色描述', '高德POI ID', '高德评分', '高德评价数', '百度UID', '百度匹配名称', '百度地址', '百度纬度', '百度经度', '百度评分', '百度评价数', '百度价格', '百度图片1', '百度图片2', '百度匹配状态', 'AI推荐分']
        excel_rows['hotels'] = localize_excel_rows('hotels', provider_rows(HOTELS, 8, 9))
        write_sheet(ws6, provider_headers(hotel_headers), excel_rows['hotels'], [12, 22, 30, 12, 14, 22, 12, 18, 30, 30, 35, 18, 12, 12, 22, 22, 35, 12, 12, 12, 12, 12, 30, 30, 16, 12])

    # Sheet 7: 美食推荐
    ws7 = wb.create_sheet('美食推荐')
    if overseas_output:
        restaurant_headers = ['目的地', '餐厅名称(中文)', '餐厅名称(英文)', '特色菜品', '人均(元)', '评分', '评价数', '经纬度(WGS84)', 'Google图片1', 'Google图片2', '地址/位置', 'Google Place ID']
        excel_rows['restaurants'] = localize_excel_rows('restaurants', international_poi_rows(RESTAURANTS, 8, 9, 10))
        write_sheet(ws7, restaurant_headers, excel_rows['restaurants'], [12, 20, 30, 22, 10, 12, 12, 18, 30, 30, 35, 24])
    else:
        restaurant_headers = ['目的地', '餐厅名称(中文)', '餐厅名称(英文)', '特色菜品', '人均(元)', '评分(搜索补充)', '评价数(旧字段)', '经纬度(WGS84)', '高德图片1', '高德图片2', '地址/位置', '高德POI ID', '高德评分', '高德评价数', '百度UID', '百度匹配名称', '百度地址', '百度纬度', '百度经度', '百度评分', '百度评价数', '百度价格', '百度图片1', '百度图片2', '百度匹配状态', 'AI推荐分']
        excel_rows['restaurants'] = localize_excel_rows('restaurants', provider_rows(RESTAURANTS, 8, 9))
        write_sheet(ws7, provider_headers(restaurant_headers), excel_rows['restaurants'], [12, 20, 30, 22, 10, 22, 12, 18, 30, 30, 35, 18, 12, 12, 22, 22, 35, 12, 12, 12, 12, 12, 30, 30, 16, 12])

    # Sheet 8: 咖啡馆推荐（无可靠结果时不创建空分类）
    if CAFES:
        ws_cafes = wb.create_sheet('咖啡馆推荐')
        if overseas_output:
            cafe_headers = ['目的地', '咖啡馆名称(中文)', '咖啡馆名称(英文)', '类型/特色', '人均(元)', '评分', '评价数', '经纬度(WGS84)', 'Google图片1', 'Google图片2', '地址/位置', 'Google Place ID']
            excel_rows['cafes'] = localize_excel_rows('cafes', international_poi_rows(CAFES, 8, 9, 10))
            write_sheet(ws_cafes, cafe_headers, excel_rows['cafes'], [12, 22, 30, 24, 12, 12, 12, 18, 30, 30, 35, 24])
        else:
            cafe_headers = ['目的地', '咖啡馆名称(中文)', '咖啡馆名称(英文)', '类型/特色', '人均(元)', '评分(搜索补充)', '评价数(旧字段)', '经纬度(WGS84)', '高德图片1', '高德图片2', '地址/位置', '高德POI ID', '高德评分', '高德评价数', '百度UID', '百度匹配名称', '百度地址', '百度纬度', '百度经度', '百度评分', '百度评价数', '百度价格', '百度图片1', '百度图片2', '百度匹配状态', 'AI推荐分']
            excel_rows['cafes'] = localize_excel_rows('cafes', provider_rows(CAFES, 8, 9))
            write_sheet(ws_cafes, provider_headers(cafe_headers), excel_rows['cafes'], [12, 22, 30, 24, 12, 22, 12, 18, 30, 30, 35, 18, 12, 12, 22, 22, 35, 12, 12, 12, 12, 12, 30, 30, 16, 12])

    # Sheet 9: 交通信息
    ws8 = wb.create_sheet('交通信息')
    transport_rows = []
    for row in TRANSPORT:
        route = str(row[0]) if row else ''
        origin, separator, destination = route.partition('→')
        transport_rows.append([
            origin.strip() if separator else route,
            destination.strip() if separator else '',
            row[1] if len(row) > 1 else '',
            row[2] if len(row) > 2 else '',
            row[3] if len(row) > 3 else '',
            row[4] if len(row) > 4 else '',
            row[9] if len(row) > 9 else '',
            row[5] if len(row) > 5 else '',
            row[6] if len(row) > 6 else '',
            row[7] if len(row) > 7 else '',
            row[10] if len(row) > 10 else '',
            row[8] if len(row) > 8 else '',
            row[11] if len(row) > 11 else '',
            row[12] if len(row) > 12 else '',
            row[13] if len(row) > 13 else '',
            row[14] if len(row) > 14 else '',
            row[15] if len(row) > 15 else '',
            row[16] if len(row) > 16 else '',
            (row[18] if OUTPUT_LANG == 'en' else row[17]) if len(row) > 18 else '',
            row[19] if len(row) > 19 else '',
            row[20] if len(row) > 20 else '',
            row[21] if len(row) > 21 else '',
            row[22] if len(row) > 22 else '',
            row[23] if len(row) > 23 else '',
        ])
    excel_rows['transport'] = localize_excel_rows('transport', transport_rows)
    write_sheet(ws8,
        ['出发地', '目的地', '交通方式', '运营公司', '参考票价(元)', '预计耗时', '距离', '班次频率', '出发地坐标', '目的地坐标', '是否需预约', '注意事项', '来源/核验状态', '出发节点', '到达节点', '是否适合自驾', '特殊风险', '班次状态', '时刻表有效期', '班次查询日期', '官方时刻表URL', '官方查询/预订URL', '去程班次', '返程班次'],
        excel_rows['transport'], [18, 18, 18, 24, 16, 16, 14, 22, 18, 18, 16, 38, 28, 24, 24, 20, 38, 22, 22, 18, 34, 34, 32, 32])

    # Sheet 10: 交通节点（HTML仅展示这一层；Excel保留节点明细）
    ws9 = wb.create_sheet('交通节点')
    transport_node_rows = []
    for node in effective_transport_nodes():
        transport_node_rows.append([node['place'], node['name'], node['name_en'], node['type'], node['coords'], node['source_status']])
    excel_rows['transport_nodes'] = localize_excel_rows('transport_nodes', transport_node_rows)
    write_sheet(ws9,
        ['所属目的地', '节点名称(中文)', '节点名称(英文)', '节点类型', '经纬度', '来源/核验状态'],
        excel_rows['transport_nodes'], [18, 24, 30, 16, 18, 28])

    # Sheet 11: 景点活动
    ws10 = wb.create_sheet('景点活动')
    if overseas_output:
        attraction_headers = ['目的地', '景点名称(中文)', '景点名称(英文)', '类型', '门票/价格(元)', '评分', '经纬度(WGS84)', 'Google图片1', 'Google图片2', '推荐游玩时间', '描述', 'Google Place ID']
        excel_rows['attractions'] = localize_excel_rows('attractions', international_attraction_rows(effective_attractions()))
        write_sheet(ws10, attraction_headers, excel_rows['attractions'], [12, 22, 30, 12, 14, 12, 18, 30, 30, 14, 35, 24])
    else:
        attraction_headers = ['目的地', '景点名称(中文)', '景点名称(英文)', '类型', '门票/价格(元)', '评分(搜索补充)', '经纬度(WGS84)', '高德图片1', '高德图片2', '推荐游玩时间', '描述', '高德POI ID', '高德评分', '高德评价数', '百度UID', '百度匹配名称', '百度地址', '百度纬度', '百度经度', '百度评分', '百度评价数', '百度价格', '百度图片1', '百度图片2', '百度匹配状态', 'AI推荐分']
        excel_rows['attractions'] = localize_excel_rows('attractions', provider_rows(effective_attractions(), 7, 8))
        write_sheet(ws10, provider_headers(attraction_headers), excel_rows['attractions'], [12, 22, 30, 12, 14, 22, 18, 30, 30, 12, 35, 18, 12, 12, 22, 22, 35, 12, 12, 12, 12, 12, 30, 30, 16, 12])

    # Sheet 11: 潜水活动（仅在存在真实潜水记录时生成）
    effective_dives = effective_dive_sites()
    if effective_dives:
        ws10 = wb.create_sheet('潜水活动')
        excel_rows['dives'] = localize_excel_rows('dives', effective_dives)
        write_sheet(ws10,
            ['目的地', '潜点名称(中文)', '潜点名称(英文)', '类型', '价格(元)', '评分', '经纬度', '图片1', '图片2', '适合等级', '描述'],
            excel_rows['dives'], [12, 20, 28, 14, 14, 18, 16, 30, 30, 14, 30])

    # Sheet 12: 预算汇总
    ws11 = wb.create_sheet('预算汇总')
    excel_rows['budget'] = localize_excel_rows('budget', BUDGET)
    write_sheet(ws11,
        ['天数', '日期', '行程', '住宿(元)', '餐饮(元)', '交通(元)', '活动/门票(元)', '其他(元)', '日合计(元)'],
        excel_rows['budget'], [8, 8, 22, 10, 10, 10, 14, 10, 10])

    # Sheet 13: 实用信息
    ws12 = wb.create_sheet('实用信息')
    excel_rows['practical'] = localize_excel_rows('practical', PRACTICAL)
    write_sheet(ws12, ['项目', '内容'], excel_rows['practical'], [14, 80])

    if WORTH_IT:
        ws = wb.create_sheet('核心体验')
        excel_rows['worth_it'] = localize_excel_rows('worth_it', WORTH_IT)
        write_sheet(ws, ['目的地', '名称(中文)', '名称(英文)', '纳入理由', '适合人群', '建议停留', '季节/限制', '预约要求', '体力要求', '来源/核验状态'], excel_rows['worth_it'], [18, 22, 28, 42, 24, 14, 28, 22, 16, 28])
    if LOCAL_CHAINS:
        ws = wb.create_sheet('当地连锁与便捷选择')
        excel_rows['local_chains'] = localize_excel_rows('local_chains', LOCAL_CHAINS)
        write_sheet(ws, ['目的地', '品牌(中文)', '品牌(英文)', '类型', '品牌特点', '适用场景', '价格', '附近位置', '来源/核验状态'], excel_rows['local_chains'], [18, 20, 26, 16, 36, 28, 14, 30, 28])
    if PACKING:
        ws = wb.create_sheet('行前准备')
        excel_rows['packing'] = localize_excel_rows('packing', PACKING)
        write_sheet(ws, ['类别', '物品(中文)', '物品(英文)', '携带/当地购买', '目的地类型', '准备时点', '说明', '来源/核验状态'], excel_rows['packing'], [16, 22, 26, 18, 18, 18, 42, 28])
    if LOCAL_KNOWLEDGE:
        ws = wb.create_sheet('当地旅行要点')
        excel_rows['local_knowledge'] = localize_excel_rows('local_knowledge', LOCAL_KNOWLEDGE) if OUTPUT_LANG == 'en' else [[row[0], row[2], row[4], row[6]] for row in LOCAL_KNOWLEDGE]
        write_sheet(ws, ['复核主题', '当地要点', '出发前复核', '来源/核验状态'], excel_rows['local_knowledge'], [22, 56, 36, 28])

    # Sheet 14: 坐标汇总
    coords = []
    for h in HOTELS:
        if overseas_output:
            c = parse_coords(h[7])
            coords.append(["住宿", h[0], h[1], h[2], h[7], gen_google_maps_uri(*c, h[1], google_place_id_for(h[1], h[0]), h[0]) if c else ""])
        else:
            urls = map_urls({"canonical_name": h[1], "destination": h[0], "country": "中国", "target_level": "verified_coordinate", "coords": h[7]}, international=False)
            coords.append(["住宿", h[0], h[1], h[2], h[7], urls["amap"], urls["baidu"]])
    for r in RESTAURANTS:
        if overseas_output:
            c = parse_coords(r[7])
            coords.append(["美食", r[0], r[1], r[2], r[7], gen_google_maps_uri(*c, r[1], google_place_id_for(r[1], r[0]), r[0]) if c else ""])
        else:
            urls = map_urls({"canonical_name": r[1], "destination": r[0], "country": "中国", "target_level": "verified_coordinate", "coords": r[7]}, international=False)
            coords.append(["美食", r[0], r[1], r[2], r[7], urls["amap"], urls["baidu"]])
    for c in CAFES:
        if overseas_output:
            cp = parse_coords(c[7])
            coords.append(["咖啡馆", c[0], c[1], c[2], c[7], gen_google_maps_uri(*cp, c[1], google_place_id_for(c[1], c[0]), c[0]) if cp else ""])
        else:
            urls = map_urls({"canonical_name": c[1], "destination": c[0], "country": "中国", "target_level": "verified_coordinate", "coords": c[7]}, international=False)
            coords.append(["咖啡馆", c[0], c[1], c[2], c[7], urls["amap"], urls["baidu"]])
    for a in effective_attractions():
        if overseas_output:
            cp = parse_coords(a[6])
            coords.append(["景点", a[0], a[1], a[2], a[6], gen_google_maps_uri(*cp, a[1], google_place_id_for(a[1], a[0]), a[0]) if cp else ""])
        else:
            urls = map_urls({"canonical_name": a[1], "destination": a[0], "country": "中国", "target_level": "verified_coordinate", "coords": a[6]}, international=False)
            coords.append(["景点", a[0], a[1], a[2], a[6], urls["amap"], urls["baidu"]])
    for node in effective_transport_nodes():
        if overseas_output:
            cp = parse_coords(node['coords'])
            coords.append(["交通节点", node['place'], node['name'], node['name_en'], node['coords'], gen_google_maps_uri(*cp, node['name']) if cp else ""])
        else:
            urls = map_urls({"canonical_name": node['name'], "destination": node['place'], "country": "中国", "target_level": "verified_coordinate", "coords": node['coords']}, international=False)
            coords.append(["交通节点", node['place'], node['name'], node['name_en'], node['coords'], urls["amap"], urls["baidu"]])

    ws13 = wb.create_sheet('坐标汇总')
    excel_rows['coords'] = localize_excel_rows('coords', coords)
    if overseas_output:
        write_sheet(ws13,
            ['类别', '目的地', '名称(中文)', '名称(英文)', '经纬度', '地图链接(Google Maps)'],
            excel_rows['coords'], [10, 12, 22, 30, 18, 60])
    else:
        write_sheet(ws13,
            ['类别', '目的地', '名称(中文)', '名称(英文)', '经纬度', '高德地图链接', '百度地图链接'],
            excel_rows['coords'], [10, 12, 22, 30, 18, 55, 55])

    # Sheet 15: 每日行程
    ws14 = wb.create_sheet('每日行程')
    excel_rows['itinerary'] = localize_excel_rows('itinerary', ITINERARY)
    write_sheet(ws14,
        ['路线方案', '日序', '序号', '类型', '地点名称', '经纬度'],
        excel_rows['itinerary'], [22, 8, 6, 8, 22, 18])

    # Sheet 16: 常用APP (Local Apps)
    apps_data = []
    eligible_apps = [a for a in LOCAL_APPS if include_research or a.get("availability_status") not in ("retired", "pending")]
    for a in eligible_apps:
        use_cases = ", ".join(a.get("use_cases_en" if OUTPUT_LANG == "en" else "use_cases_cn") or [])
        limits = "; ".join(a.get("limitations_en" if OUTPUT_LANG == "en" else "limitations_cn") or [])
        dest_str = ", ".join(a.get("destinations") or [])
        cat_str = a.get("category", "")
        row = [
            cat_str,
            a.get("name_en" if OUTPUT_LANG == "en" else "name", ""),
            a.get("name_en", ""),
            a.get("priority", ""),
            dest_str,
            use_cases,
            a.get("coverage_status", ""),
            a.get("availability_status", ""),
            limits,
            a.get("official_url", ""),
            a.get("ios_url", ""),
            a.get("android_url", ""),
            a.get("verified_at", "")
        ]
        apps_data.append(row)

    ws_apps = wb.create_sheet('常用APP')
    excel_rows['local_apps'] = localize_excel_rows('local_apps', apps_data)
    write_sheet(ws_apps,
        ['分类', '名称', '英文名称', '优先级', '适用目的地', '核心用途', '覆盖范围', '当前状态', '关键限制与说明', '官方网站', 'App Store', 'Google Play', '核验日期'],
        excel_rows['local_apps'], [14, 18, 18, 10, 16, 26, 12, 14, 30, 26, 26, 26, 12])

    assert_english_excel_rows(excel_rows)

    wb.save(output_path)
    _normalize_xlsx_bytes(output_path, _seal_timestamp())
    print(f"Excel saved: {output_path}")
    print(f"Sheets: {len(wb.sheetnames)}")
    for name in wb.sheetnames:
        ws = wb[name]
        print(f"  {name}: {ws.max_row}r x {ws.max_column}c")
    return coords


# ============================================================
# HTML GENERATION (by destination, multi-map-platform)
# ============================================================

DEST_EMOJIS_DEFAULT = {}
CAT_EMOJIS = {"住宿": "🏨", "美食": "🍽", "咖啡馆": "☕", "景点": "📍", "潜水": "🤿", "交通": "🚌"}

MAP_PLATFORM_NAMES = {
    "google": "Google Maps",
    "apple": "Apple Maps",
    "amap": "高德地图",
    "baidu": "百度地图",
}
MAP_BTN_COLORS = {
    "google": "#1a73e8",
    "apple": "#111827",
    "amap": "#008dfd",
    "baidu": "#2932e1",
}


def _is_overseas():
    """Use the confirmed branch, never a bounding box around China."""
    return not DOMESTIC_DESTINATION


def _prepare_itinerary_json():
    """Build one map anchor per day from ITINERARY.

    The detailed itinerary remains available to Excel and the card view. The
    map view intentionally uses daily destination anchors only, so it does not
    draw a misleading hotel -> restaurant -> attraction chain.

    Newer itinerary rows may append [daily_destination, daily_destination_en,
    daily_destination_coords]. Older six-column rows remain compatible and use
    the first non-transport point as the daily anchor.
    """
    if not ITINERARY:
        return json.dumps({})

    # Build name->images lookup
    img_lookup = {}
    for h in HOTELS:
        img_lookup[h[1]] = {"img1": h[8], "img2": h[9]}
    for r in RESTAURANTS:
        img_lookup[r[1]] = {"img1": r[8], "img2": r[9]}
    for c in CAFES:
        img_lookup[c[1]] = {"img1": c[8], "img2": c[9]}
    for a in effective_attractions():
        img_lookup[a[1]] = {"img1": a[7], "img2": a[8]}
    for d in effective_dive_sites():
        img_lookup[d[1]] = {"img1": d[7], "img2": d[8]}

    day_rows = {}
    for item in effective_itinerary():
        r_name, day, seq, ptype, pname, coords = item[0], item[1], item[2], item[3], item[4], item[5]
        explicit_destination = str(item[6]).strip() if len(item) > 6 and item[6] else ""
        explicit_destination_en = str(item[7]).strip() if len(item) > 7 and item[7] else ""
        explicit_destination_coords = str(item[8]).strip() if len(item) > 8 and item[8] else ""
        day_rows.setdefault(r_name, {}).setdefault(day, []).append({
            "name": explicit_destination or pname,
            "name_en": explicit_destination_en,
            "type": "目的地",
            "coords": explicit_destination_coords or coords,
            "seq": seq,
            "img1": "",
            "img2": "",
            "explicit": bool(explicit_destination),
            "source_type": str(ptype).strip(),
        })

    routes_data = {}
    for r_name, days in day_rows.items():
        routes_data[r_name] = {}
        for day, candidates in days.items():
            explicit = [x for x in candidates if x["explicit"]]
            non_transport = [x for x in candidates if x["source_type"] != "交通"]
            anchor = (explicit or non_transport or candidates)[0]
            anchor = dict(anchor)
            anchor.pop("explicit", None)
            anchor.pop("source_type", None)
            anchor["map_scope"] = "daily_destination"
            routes_data[r_name][day] = [anchor]

    return json.dumps(routes_data, ensure_ascii=False)


def _write_asset_manifests(output_dir):
    """Write a portable JSON asset ledger; no database is needed for local runs."""
    output = Path(output_dir)
    assets = []
    root_manifest = DATA_ROOT / "asset-manifest.json"
    if root_manifest.is_file():
        try:
            root_data = json.loads(root_manifest.read_text(encoding="utf-8"))
            if isinstance(root_data, dict) and root_data.get("assets"):
                assets = list(root_data["assets"])
        except Exception:
            pass
    if not assets:
        for category, rows, image_index in (
            ("accommodation", HOTELS, 8),
            ("food", RESTAURANTS, 8),
            ("cafe", CAFES, 8),
            ("attraction", effective_attractions(), 7),
            ("dive", effective_dive_sites(), 7),
        ):
            for row in rows:
                poi_name = str(row[1] if len(row) > 1 else "").strip()
                for slot in (0, 1):
                    index = image_index + slot
                    source_url = str(row[index]).strip() if len(row) > index else ""
                    if not source_url:
                        continue
                    identity = hashlib.sha256(source_url.split("?")[0].encode("utf-8")).hexdigest()[:24]
                    is_remote = source_url.startswith(("http://", "https://"))
                    local_file = source_url if not is_remote else ""
                    assets.append({
                        "asset_id": identity,
                        "poi_name": poi_name,
                        "category": category,
                        "slot": slot + 1,
                        "source_url": source_url,
                        "local_file": local_file,
                        "status": "remote_only" if is_remote else "local_reference",
                        "verification": "not_downloaded" if is_remote else "reference_only",
                    })
    manifest = {
        "schema_version": "1.0",
        "storage": "assets/ + asset-manifest.json",
        "api_free_local_run": True,
        "assets": assets,
    }
    (output / "asset-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fetch_report = {
        "status": "metadata_only",
        "remote_assets": sum(item.get("status") == "remote_only" for item in assets),
        "local_assets": sum(item.get("status") == "local_reference" for item in assets),
        "note": "No remote download was attempted during ordinary HTML generation.",
    }
    (output / "asset-fetch-report.json").write_text(json.dumps(fetch_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preflight = {
        "status": "PASS" if assets else "WARN",
        "unique_asset_ids": len({item.get("asset_id", item.get("local_file", idx)) for idx, item in enumerate(assets)}),
        "total_references": len(assets),
        "cross_category_reuse": sorted({item["asset_id"] for item in assets if "asset_id" in item and sum(x.get("asset_id") == item["asset_id"] for x in assets) > 1}),
    }
    (output / "MEDIA_PREFLIGHT.json").write_text(json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


MAP_RESOLUTION_REPORT: dict = {}


def _overseas_target_display_names():
    """Yield (display, chinese_name, map_target_key) so the UI can label unnamed targets.

    The display name is the *reader-facing* Chinese name; it is never used to build an
    overseas query string.
    """
    from map_contract import target_key as _key
    rows = []
    for module in (HOTELS, RESTAURANTS, CAFES, ATTRACTIONS, DIVE_SITES):
        for row in module:
            if isinstance(row, list) and len(row) > 1:
                rows.append((row[0], row[1]))
    for row in effective_attractions():
        if isinstance(row, list) and len(row) > 1:
            rows.append((row[0], row[1]))
    for node in effective_transport_nodes():
        if isinstance(node, dict):
            if node.get("place") and node.get("name"):
                rows.append((str(node["place"]), str(node["name"])))
        elif isinstance(node, list) and len(node) > 1:
            rows.append((str(node[0]), str(node[1])))
    seen = set()
    for dest, name in rows:
        key = _key(dest, name)
        if key in seen:
            continue
        seen.add(key)
        yield dest, name, key


def assemble_source_ledger_face():
    """正式生成链的来源台账装配（ZH-RELEASE-2 步1 · 业主 2026-11-03 裁 finding_1）。

    返回 `(机器面, 血缘自证)`。两条禁令就落在这里，不在下游各自补判：
      * **不重新推导**：机器面只能是输入 dataset 带进来的那份 `source_evidence_meta`；
        十列位置面 `source_evidence` 不是它的来源（#113 就是按位取值取成空白条目的）；
      * **不回退空列表**：正式构建（合同 `reader_language.source_ledger_chain.formal_build.env`
        登记的那个信号）缺这一面、或带进来的是空账，都在生成阶段抛错阻断，
        而不是渲染一张空表再让门禁印「0 verified」。

    非正式构建（demo 夹具、临时生成）保持 None：那种产物没有正式输入字节可指，
    合同把它记成 smoke，不进交付证据。
    """
    import source_projection as ledger
    from spa_renderer import formal_build_declared
    formal_build = formal_build_declared()
    if SOURCE_EVIDENCE_META is None:
        if formal_build:
            raise ValueError(
                "SOURCE_LEDGER_FACE_MISSING：正式 run 的输入 dataset 没有 source_evidence_meta "
                "（读入面 %s，摘要 %s）。读者来源面板的机器面只能由正式输入携带，构建器不得从十列"
                "位置面 source_evidence 推导，也不得回退空列表；请补齐输入的台账面后重新封存生成。"
                % (RUNTIME_INPUT_PATH or "(未记录)", RUNTIME_INPUT_SHA256[:12] or "(无)"))
        return None, None
    if not SOURCE_EVIDENCE_META:
        if formal_build:
            raise ValueError(
                "SOURCE_LEDGER_FACE_EMPTY：正式 run 的输入 dataset 带了 source_evidence_meta 但是零行"
                "（读入面 %s，摘要 %s）。零行台账在读者页上就是「没有来源可发」，"
                "不得当作『面板正常』出货。" % (RUNTIME_INPUT_PATH, RUNTIME_INPUT_SHA256[:12]))
        return [], None
    face = list(SOURCE_EVIDENCE_META)
    provenance = ledger.build_provenance(face, RUNTIME_INPUT_SHA256)
    print("[SOURCE-LEDGER] 机器面随输入携带: rows=%d ledger_sha256=%s input_sha256=%s"
          % (provenance["dataset_rows"], provenance["ledger_sha256"][:12],
             provenance["input_sha256"][:12]))
    return face, provenance


def export_runtime_dataset(output_dir=None, map_platforms=None):
    modern_theme, modern_theme_label, modern_theme_evidence = visual_theme()
    theme_media = visual_theme_media(modern_theme)
    modern_hero_image = HERO_IMAGE or str(theme_media.get("hero_image") or "")
    modern_hero_video = HERO_VIDEO if HERO_IMAGE else str(theme_media.get("hero_video") or "")
    if output_dir is not None:
        output_dir = Path(output_dir).resolve()
        if DATA_ROOT is not None:
            for rows, indexes in ((HOTELS, (8,9)), (RESTAURANTS, (8,9)), (CAFES, (8,9)), (effective_attractions(), (7,8)), (effective_dive_sites(), (7,8))):
                for row in rows:
                    for index in indexes:
                        value = str(row[index] if len(row) > index else '')
                        if not value or urlsplit(value).scheme:
                            continue
                        source = (DATA_ROOT / value).resolve()
                        target = (output_dir / value).resolve()
                        if not source.is_relative_to(DATA_ROOT / 'assets') or not target.is_relative_to(output_dir / 'assets'):
                            raise ValueError('POI assets must remain inside assets/')
                        if not source.is_file():
                            raise FileNotFoundError(source)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if source != target:
                            shutil.copy2(source, target)
            for item in list(EDITORIAL_MEDIA) + list(SECTION_MEDIA):
                value = str(item.get("image", "") if isinstance(item, dict) else "")
                if not value or urlsplit(value).scheme:
                    continue
                source = (DATA_ROOT / value).resolve()
                target = (output_dir / value).resolve()
                if not source.is_relative_to(DATA_ROOT / "assets") or not target.is_relative_to(output_dir / "assets"):
                    raise ValueError("Editorial assets must remain inside assets/")
                if not source.is_file():
                    raise FileNotFoundError(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                if source != target:
                    shutil.copy2(source, target)
        for asset_kind, asset_value in (("image", modern_hero_image), ("video", modern_hero_video)):
            if not asset_value.startswith("assets/"):
                continue
            run_asset = (DATA_ROOT / asset_value).resolve() if DATA_ROOT is not None else None
            source_asset = run_asset if run_asset is not None and run_asset.is_file() else Path(__file__).resolve().parents[1] / asset_value
            if not source_asset.is_file():
                raise FileNotFoundError(f"Configured theme asset is missing: {source_asset}")
            target_asset = output_dir / asset_value
            target_asset.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_asset, target_asset)
            relative_asset = target_asset.relative_to(output_dir).as_posix()
            if asset_kind == "image":
                modern_hero_image = relative_asset
            else:
                modern_hero_video = relative_asset
        if not modern_hero_image:
            for image_rows, image_index in ((HOTELS, 8), (RESTAURANTS, 8), (ATTRACTIONS, 7)):
                for image_row in image_rows:
                    if len(image_row) > image_index and str(image_row[image_index]).startswith(("http://", "https://")):
                        modern_hero_image = str(image_row[image_index])
                        break
                if modern_hero_image:
                    break
        _write_asset_manifests(output_dir)
        Path(output_dir, "theme-selection.json").write_text(
            json.dumps({
                "theme": modern_theme,
                "label": modern_theme_label,
                "evidence": modern_theme_evidence,
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if map_platforms is None:
        map_platforms = ['google', 'apple'] if _is_overseas() else ['amap', 'baidu']
    # v4.2.1 §11.5/§14.4.3: overseas map targets are repaired by recovering the verified
    # English name from evidence/map_verification.json (keyed by coordinate, because the
    # evidence keys use the English name while map_targets keys use the Chinese name).
    # The v4.2.0 block instead deleted CJK characters and fell back to "Location", which
    # is how 151 "California Venue" placeholders reached the shipped artifact.
    if _is_overseas() and not DEMO_MODE:
        from map_contract import (map_urls as _map_urls,
                                  resolve_overseas_targets as _resolve_targets)
        evidence_payload = {}
        evidence_file = None
        for candidate in (DATA_ROOT / "evidence" / "map_verification.json" if DATA_ROOT else Path("."),
                          Path(os.environ.get("TRAVEL_SCOPE_RUN_MANIFEST", "x")).parent
                          / "evidence" / "map_verification.json"):
            if candidate and Path(candidate).is_file():
                evidence_file = Path(candidate)
                break
        if evidence_file is not None:
            try:
                evidence_payload = json.loads(evidence_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"地图目标无法接回英文名：{evidence_file} 解析失败: {exc}") from exc
        else:
            raise ValueError(
                "海外地图目标需要 evidence/map_verification.json 才能接回核验英文名；"
                "缺失时禁止生成，因为唯一的替代方案就是伪造名称"
            )
        destination_english = {}
        for row in DESTINATIONS:
            if isinstance(row, list) and len(row) > 1:
                english = str(row[1] or "").strip()
                if english and not re.search(r"[\u4e00-\u9fa5]", english):
                    destination_english[str(row[0]).strip()] = english
        resolution = _resolve_targets(MAP_TARGETS, evidence_payload, destination_english)
        for display_name, cn_name, key in _overseas_target_display_names():
            target = MAP_TARGETS.get(key)
            if isinstance(target, dict) and not str(target.get("display_name_cn") or "").strip():
                target["display_name_cn"] = cn_name or display_name
        rebuilt = 0
        for key, target in MAP_TARGETS.items():
            if not isinstance(target, dict):
                continue
            urls = _map_urls(target, international=True)
            if target.get("target_level") != "verified_platform_url":
                target["google_url"] = urls.get("google", "")
                target["apple_url"] = urls.get("apple", "")
                rebuilt += 1
            if str(target.get("canonical_name") or "").strip() and target.get("target_level") != "unnamed_coordinate":
                target["entity_type"] = "named_entity"
        MAP_RESOLUTION_REPORT = {
            "evidence_file": str(evidence_file),
            "rebuilt_urls": rebuilt,
            **{k: v for k, v in resolution.items() if k != "unrecovered_keys"},
            "unrecovered_keys": sorted(resolution["unrecovered_keys"])[:40],
            "unrecovered_total": len(resolution["unrecovered_keys"]),
            "coordinate_collisions": resolution["coordinate_collisions"],
        }
        print("[MAP] 英文名接回: " + json.dumps(
            {k: MAP_RESOLUTION_REPORT[k] for k in
             ("total", "already_named", "recovered", "degraded_unnamed", "no_coordinate",
              "coordinate_collisions")},
            ensure_ascii=False))
        blocking = [key for key in resolution["unrecovered_keys"]
                    if not isinstance(MAP_TARGETS.get(key), dict)
                    or MAP_TARGETS[key].get("target_level") != "unnamed_coordinate"]
        if blocking:
            raise ValueError(
                f"{len(blocking)} 个海外地图目标既接不到核验英文名也没有坐标，不能降级也不能伪造: "
                f"{sorted(blocking)[:5]}"
            )

    # v4.2.1 SS2.2.1 + MT-B2（2026-10-31）：英文类别标签在构建期由词根组合出来，不是样本字典。
    # 「哪些列是类别列」以前硬写在下面（只有五张 POI 表），transport_nodes 的枢纽类别因此从未
    # 进过 category_en，英文页只能给读者一个 pending 标记。现在列清单只住在
    # references/category-lexicon.json::category_columns，由 annotate_dataset 读；组合不出的一律
    # 进 category_unmapped（fail-closed），而不是让英文页悄悄漏中文（v4.2.0 的失效方式）。
    from category_lexicon import annotate_dataset as _annotate_categories
    from display_names import annotate_dataset as _annotate_display_names

    # _overseas_target_display_names is defined below in this module.
    # ZH-RELEASE-2 步1：来源台账的机器面与它的血缘自证在装配载荷的这一处一次决定，
    # 缺面/空账的正式构建在这里就停住（抛错），不等到门禁看见一张空表再补判。
    source_ledger_face, source_ledger_provenance = assemble_source_ledger_face()
    payload = {
        "language": OUTPUT_LANG,
        "country": COUNTRY,
        "country_en": COUNTRY_EN,
        "theme": modern_theme,
        "theme_label": modern_theme_label,
        "theme_evidence": modern_theme_evidence,
        "demo_mode": DEMO_MODE,
        "map_platforms": map_platforms,
        "is_overseas": _is_overseas(),
        "hero_image": modern_hero_image,
        "hero_video": modern_hero_video,
        "hero_credit_cn": HERO_CREDIT_CN,
        "hero_credit_en": HERO_CREDIT_EN,
        "theme_accent": theme_media.get("accent", ""),
        "routes": ROUTES,
        "route_budgets": effective_route_budgets(),
        "budget_meta": BUDGET_META,
        "map_region": "international" if _is_overseas() else "mainland_china",
        "domestic_destination": DOMESTIC_DESTINATION,
        "duration_days": effective_duration_days(),
        "editorial_media": EDITORIAL_MEDIA,
        "section_media": SECTION_MEDIA,
        "destinations": DESTINATIONS,
        "hotels": HOTELS,
        "restaurants": RESTAURANTS,
        "cafes": CAFES,
        "attractions": effective_attractions(),
        "dive_sites": effective_dive_sites(),
        "transport_nodes": effective_transport_nodes(),
        "transport": TRANSPORT,
        "itinerary": ITINERARY,
        "budget": BUDGET,
        "practical": PRACTICAL,
        "worth_it": WORTH_IT,
        "local_chains": LOCAL_CHAINS,
        "packing": PACKING,
        "local_knowledge": LOCAL_KNOWLEDGE,
        "source_evidence": SOURCE_EVIDENCE,
        "destination_coverage": DESTINATION_COVERAGE,
        "google_place_ids": GOOGLE_PLACE_IDS,
        "map_targets": MAP_TARGETS,
        # §8.1 的适用性开关必须活在读者那份载荷上：空对象＝本版血缘未声明，门禁据此显式判
        # 「不适用」并留下 reason，而不是拿着一个从未被检查过的页面对着「不一致 = 0」点头。
        "map_link_selection": MAP_LINK_SELECTION,
        "local_apps": LOCAL_APPS,
        "en_text_replacements": EN_TEXT_REPLACEMENTS,
        "machine_translated_display_name": dict(MACHINE_DISPLAY_NAMES),
        "display_name_provenance": dict(DISPLAY_NAME_PROVENANCE),
        "prose_en": dict(PROSE_EN),
        "prose_en_provenance": dict(PROSE_EN_PROVENANCE),
        "prose_en_required": bool(_is_overseas() and PROSE_EN),
        "media_renditions": _media_rendition_index(),
    }
    # 机器面只在「输入确实带了它」时进载荷；自证块只在拿到输入字节时进载荷。
    # 两者都不写占位值（空列表／空串），因为下游读到占位值就分不清「没有这一面」与「有但是空账」。
    if source_ledger_face is not None:
        payload["source_evidence_meta"] = source_ledger_face
    if source_ledger_provenance is not None:
        payload["source_ledger_meta"] = source_ledger_provenance
    _category_report = _annotate_categories(payload)
    print(f"[CATEGORY] 英文分类词根组合: mapped={len(payload['category_en'])}"
          f"/{_category_report['distinct']} unmapped={len(payload['category_unmapped'])}"
          + (f" :: {payload['category_unmapped'][:5]}" if payload["category_unmapped"] else ""))
    _display_report = _annotate_display_names(payload)
    print(f"[DISPLAY] 专名显示面: tier1名对={_display_report['tier1_pairs']} "
          f"tier2可用={_display_report['tier2_usable']} tier2剔除={_display_report['tier2_rejected']} "
          f"撞名剔出={_display_report['conflicts']}"
          + (f" :: {json.dumps([c['cn'] for c in payload['display_name_conflicts']][:3], ensure_ascii=False)}"
             if payload["display_name_conflicts"] else ""))
    return payload


def _media_rendition_index() -> dict:
    """Map each delivered image to the renditions the build may inline for it (§12 slot tiering).

    The manifest is the only place that knows which bytes came from where, so the renderer reads
    its tier list instead of guessing widths from filenames. Entries without a chain (no
    `delivered_sha256`) yield no tiers and the media gate reports them as unattested.
    """
    manifest_path = DATA_ROOT / "asset-manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"asset-manifest 无法解析，图片档位无从声明: {exc}") from exc
    items = data if isinstance(data, list) else data.get("assets", [])
    index: dict[str, list] = {}
    for item in items:
        local = str(item.get("local_file") or "").strip()
        tiers = item.get("renditions") or []
        if not local or not tiers:
            continue
        index[local] = [{
            "file": str(t.get("file") or ""), "label": str(t.get("label") or ""),
            "width": int(t.get("width") or 0), "height": int(t.get("height") or 0),
            "bytes": int(t.get("bytes") or 0), "sha256": str(t.get("sha256") or ""),
        } for t in tiers if t.get("file")]
        index[Path(local).name] = index[local]
    return index


def generate_html(output_path, map_platforms, amap_js_key='', amap_security='', google_maps_key=''): 
    """Generate HTML with dual-view: card list + map route (dual-engine: AMap JS API for domestic / Google Maps JS API for overseas)."""
    output_dir = Path(output_path).resolve().parent
    payload = export_runtime_dataset(output_dir=output_dir, map_platforms=map_platforms)
    render_travel_scope_html(output_path, payload)
    return
    # V4.1.1: Legacy inline HTML generator cleaned up in favor of travel_renderer.py & spa_renderer.py.


# ============================================================
# MARKDOWN GENERATION
# ============================================================

def generate_markdown_english(output_path):
    """Generate the EN Markdown from the same localized rows as the EN workbook."""
    rows = {
        "destinations": localize_excel_rows("destinations", [format_destination_for_table(d) for d in DESTINATIONS]),
        "routes": localize_excel_rows("routes", [format_route_for_table(r) for r in ROUTES]),
        "itinerary": localize_excel_rows("itinerary", effective_itinerary()),
        "hotels": localize_excel_rows("hotels", HOTELS),
        "restaurants": localize_excel_rows("restaurants", RESTAURANTS),
        "cafes": localize_excel_rows("cafes", CAFES),
        "transport": localize_excel_rows("transport", TRANSPORT),
        "attractions": localize_excel_rows("attractions", effective_attractions()),
        "dives": localize_excel_rows("dives", effective_dive_sites()),
        "budget": localize_excel_rows("budget", BUDGET),
        "practical": localize_excel_rows("practical", PRACTICAL),
        "worth_it": localize_excel_rows("worth_it", WORTH_IT),
        "local_chains": localize_excel_rows("local_chains", LOCAL_CHAINS),
        "packing": localize_excel_rows("packing", PACKING),
        "local_knowledge": localize_excel_rows("local_knowledge", LOCAL_KNOWLEDGE),
    }
    assert_english_excel_rows(rows)

    def clean(value):
        return str(value if value is not None else "").replace("|", "\\|").replace("\n", "<br>")

    md = [f"# {country_display()} Travel Guide", "", "> Planning guide for February 2027. Exact schedules, prices, operating status, weather, and sea conditions require pre-trip recheck.", ""]

    def table(title, headers, data, indexes=None):
        if not data:
            return
        md.extend([f"## {title}", "", "| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"])
        for row in data:
            chosen = [row[i] if i < len(row) else "" for i in indexes] if indexes is not None else list(row[:len(headers)])
            md.append("| " + " | ".join(clean(value) for value in chosen) + " |")
        md.extend(["", "---", ""])

    table("1. Destinations", ["Destination", "Region", "Key Experiences", "Suggested Days", "Best Season", "Arrival", "Included in Route"], rows["destinations"], [1,2,3,4,5,6,7])
    table("2. Route Options", ["Route Option", "Days", "Route", "Highlights", "Best For", "Budget (CNY)", "Transport"], rows["routes"], [0,1,2,3,4,5,6])
    table("Daily Itinerary", ["Route", "Day", "Sequence", "Type", "Place", "Coordinates"], rows["itinerary"])
    table("3. Accommodation", ["Destination", "Hotel", "Type", "Reference Price (CNY/night)", "Rating Status", "Coordinates", "Highlights"], rows["hotels"], [0,2,3,4,5,7,10])
    table("4. Food & Restaurants", ["Destination", "Restaurant", "Type", "Average Spend (CNY)", "Rating Status", "Coordinates", "Highlights"], rows["restaurants"], [0,2,3,4,5,7,10])
    table("5. Cafés", ["Destination", "Café", "Type", "Average Spend (CNY)", "Rating Status", "Coordinates", "Highlights"], rows["cafes"], [0,2,3,4,5,7,10])
    table("6. Transport", ["Route", "Mode", "Operator", "Reference Fare", "Travel Time", "Frequency", "Schedule Status", "Effective Period", "Checked Date", "Official Timetable", "Search / Booking", "Outbound Departures", "Return Departures", "Notes"], rows["transport"], [0,1,2,3,4,5,16,18,19,20,21,22,23,8])
    table("7. Attractions & Activities", ["Destination", "Attraction", "Type", "Ticket / Price", "Rating Status", "Coordinates", "Suggested Time", "Description"], rows["attractions"], [0,2,3,4,5,6,9,10])
    table("8. Diving", ["Destination", "Site", "Type", "Price", "Rating Status", "Coordinates", "Suitable Level", "Description"], rows["dives"], [0,2,3,4,5,6,9,10])
    table("9. Budget Summary", ["Day", "Date", "Plan", "Lodging", "Food", "Transport", "Activities", "Other", "Daily Total"], rows["budget"])
    table("10. Practical Information", ["Item", "Details"], rows["practical"])
    table("Key Experiences", ["Destination", "Name", "Why It Is Included", "Best For", "Suggested Stay", "Season / Constraints", "Booking Requirement", "Fitness Requirement", "Source / Verification Status"], rows["worth_it"], [0,2,3,4,5,6,7,8,9])
    table("Local Chains & Convenient Options", ["Destination", "Brand", "Type", "Brand Strengths", "Best Use Case", "Price", "Nearby Locations", "Source / Verification Status"], rows["local_chains"], [0,2,3,4,5,6,7,8])
    table("Pre-trip Checklist", ["Category", "Item", "Bring / Buy Locally", "Destination Type", "When to Prepare", "Notes", "Source / Verification Status"], rows["packing"], [0,2,3,4,5,6,7])
    table("Local Travel Essentials", ["Recheck Topic", "Local Notes", "Pre-departure Recheck", "Source / Verification Status"], rows["local_knowledge"])
    active_apps_en = [app for app in LOCAL_APPS if app.get("availability_status") not in ("retired", "pending")]
    if active_apps_en:
        md.extend(["## Local Toolkit", "", "> Recommended local mobility, food, communication, and emergency apps. Download and configure before departure.", ""])
        essential_apps = [a for a in active_apps_en if a.get("priority") == "essential"]
        if essential_apps:
            md.extend(["### Essential Apps (Install Before Departure)", ""])
            for app in essential_apps:
                name = app.get("name_en") or app.get("name")
                cat = app.get("category", "")
                uses = ", ".join(app.get("use_cases_en") or [])
                limits = "; ".join(app.get("limitations_en") or []) or "Standard availability"
                links = []
                if app.get("official_url"): links.append(f"[Official Website]({app['official_url']})")
                if app.get("ios_url"): links.append(f"[App Store]({app['ios_url']})")
                if app.get("android_url"): links.append(f"[Google Play]({app['android_url']})")
                link_str = " · ".join(links)
                dests = ", ".join(destination_name_en(d) for d in app.get("destinations", []))
                md.extend([
                    f"- **{name}** ({cat}): {uses}",
                    f"  - Scope: {dests} | Status: {app.get('availability_status')}",
                    f"  - Notes: {limits}",
                    f"  - Links: {link_str}",
                    ""
                ])
        other_apps = [a for a in active_apps_en if a.get("priority") != "essential"]
        if other_apps:
            md.extend(["### On-Demand & Specialized Local Apps", ""])
            for app in other_apps:
                name = app.get("name_en") or app.get("name")
                cat = app.get("category", "")
                uses = ", ".join(app.get("use_cases_en") or [])
                limits = "; ".join(app.get("limitations_en") or []) or "Standard availability"
                links = []
                if app.get("official_url"): links.append(f"[Official Website]({app['official_url']})")
                if app.get("ios_url"): links.append(f"[App Store]({app['ios_url']})")
                if app.get("android_url"): links.append(f"[Google Play]({app['android_url']})")
                link_str = " · ".join(links)
                dests = ", ".join(destination_name_en(d) for d in app.get("destinations", []))
                md.extend([
                    f"- **{name}** ({cat}): {uses}",
                    f"  - Scope: {dests} | Status: {app.get('availability_status')}",
                    f"  - Notes: {limits}",
                    f"  - Links: {link_str}",
                    ""
                ])
        md.extend(["---", ""])
    md.append(f"*{country_display()} Travel Guide*")
    Path(output_path).write_text("\n".join(md), encoding="utf-8")
    print(f"Markdown saved: {output_path}")


def generate_markdown(output_path):
    """Generate comprehensive Markdown travel guide."""
    if OUTPUT_LANG == "en":
        return generate_markdown_english(output_path)
    guide_title = f"{country_display()} Travel Guide" if OUTPUT_LANG == "en" else f"{COUNTRY}旅行攻略大全"
    md = []
    md.append(f"# {guide_title}")
    if DEMO_MODE:
        md.append("> **Demo fixture / 离线演示数据：** This guide is generated from sanitized sample data and is not live platform data.")
    md.append("")
    md.append("---")
    md.append("")

    # 1. 目的地总览
    md.append("## 1. 目的地总览")
    md.append("")
    md.append(f"共 **{len(DESTINATIONS)}** 个目的地：")
    md.append("")
    md.append("| 中文名 | 英文名 | 区域 | 核心体验 | 建议天数 | 最佳季节 | 到达方式 | 是否纳入环线 |")
    md.append("|---|---|---|---|---|---|---|---|")
    for d in DESTINATIONS:
        row = format_destination_for_table(d)
        md.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} | {row[6]} | {row[7]} |")
    md.append("")
    md.append("---")
    md.append("")

    # 2. 路线方案
    md.append("## 2. 路线方案")
    md.append("")
    md.append("| 方案名称 | 天数 | 路线 | 特色 | 适合人群 | 预算(元) | 交通方式 |")
    md.append("|---|---|---|---|---|---|---|")
    for r in ROUTES:
        row = format_route_for_table(r)
        md.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} | {row[6]} |")
    md.append("")
    md.append("---")
    md.append("")

    # 每日行程详情 (新增)
    if ITINERARY:
        md.append("## 每日行程详情")
        md.append("")
        md.append("> 仅展示推荐路线的每日行程点位顺序")
        md.append("")
        routes_itin = {}
        for item in effective_itinerary():
            r_name = item[0]
            if r_name not in routes_itin:
                routes_itin[r_name] = []
            routes_itin[r_name].append(item)
        for r_name, items in routes_itin.items():
            md.append(f"### {r_name}")
            md.append("")
            md.append("| 日序 | 序号 | 类型 | 地点 | 经纬度 |")
            md.append("|---|---|---|---|---|")
            for item in items:
                md.append(f"| {item[1]} | {item[2]} | {item[3]} | {item[4]} | {item[5]} |")
            md.append("")
        md.append("---")
        md.append("")

    # 3. 住宿推荐
    md.append("## 3. 住宿推荐")
    md.append("")
    md.append(f"共 **{len(HOTELS)}** 家酒店：")
    md.append("")
    for dest_name in [d[0] for d in DESTINATIONS]:
        dest_hotels = [h for h in HOTELS if h[0] == dest_name]
        if not dest_hotels:
            continue
        md.append(f"### {destination_display(dest_name)}")
        md.append("")
        md.append("| 酒店名称 | 类型 | 参考价(元/晚) | 评分 | 评价数 | 特色 |")
        md.append("|---|---|---|---|---|---|")
        for h in dest_hotels:
            md.append(f"| {display_name(h[1], h[2])} | {h[3]} | {h[4]} | ⭐{h[5]} | {h[6]} | {h[10]} |")
        md.append("")
    md.append("---")
    md.append("")

    # 4. 美食推荐
    md.append("## 4. 美食推荐")
    md.append("")
    md.append(f"共 **{len(RESTAURANTS)}** 家餐厅：")
    md.append("")
    for dest_name in [d[0] for d in DESTINATIONS]:
        dest_rest = [r for r in RESTAURANTS if r[0] == dest_name]
        if not dest_rest:
            continue
        md.append(f"### {destination_display(dest_name)}")
        md.append("")
        md.append("| 餐厅名称 | 特色菜品 | 人均(元) | 评分 | 位置 |")
        md.append("|---|---|---|---|---|")
        for r in dest_rest:
            md.append(f"| {display_name(r[1], r[2])} | {r[3]} | {r[4]} | ⭐{r[5]} | {r[10]} |")
        md.append("")
    md.append("---")
    md.append("")

    # 5. 咖啡馆推荐（仅在有可靠结果时输出）
    if CAFES:
        md.append("## 5. 咖啡馆推荐")
        md.append("")
        md.append(f"共 **{len(CAFES)}** 家咖啡馆：")
        md.append("")
        for dest_name in [d[0] for d in DESTINATIONS]:
            dest_cafes = [c for c in CAFES if c[0] == dest_name]
            if not dest_cafes:
                continue
            md.append(f"### {destination_display(dest_name)}")
            md.append("")
            md.append("| Café | Type / Highlights | Average Spend (CNY) | Rating | Location |" if OUTPUT_LANG == 'en' else "| 咖啡馆名称 | 类型/特色 | 人均(元) | 评分 | 位置 |")
            md.append("|---|---|---|---|---|")
            for c in dest_cafes:
                md.append(f"| {display_name(c[1], c[2])} | {translate_excel_text(c[3])} | {c[4]} | ⭐{c[5]} | {translate_excel_text(c[10])} |")
            md.append("")
        md.append("---")
        md.append("")

    # 6. 交通信息
    md.append("## 6. 交通信息")
    md.append("")
    md.append("| 路线 | 交通方式 | 运营公司 | 参考票价(元) | 行程时间 | 班次频率 | 班次状态 | 时刻表有效期 | 查询日期 | 官方时刻表 | 查询/预订 | 去程班次 | 返程班次 | 备注 |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for t in TRANSPORT:
        values = [t[i] if len(t) > i else "" for i in (0,1,2,3,4,5,16,17,19,20,21,22,23,8)]
        md.append("| " + " | ".join(str(value).replace("|", "<br>") for value in values) + " |")
    md.append("")
    md.append("---")
    md.append("")

    # 7. 景点活动
    md.append("## 7. 景点活动")
    md.append("")
    effective_attrs = effective_attractions()
    md.append(f"共 **{len(effective_attrs)}** 个景点/活动：")
    md.append("")
    for dest_name in [d[0] for d in DESTINATIONS]:
        dest_attr = [a for a in effective_attrs if a[0] == dest_name]
        if not dest_attr:
            continue
        md.append(f"### {destination_display(dest_name)}")
        md.append("")
        md.append("| 景点名称 | 类型 | 门票(元) | 评分 | 游玩时间 | 描述 |")
        md.append("|---|---|---|---|---|---|")
        for a in dest_attr:
            md.append(f"| {display_name(a[1], a[2])} | {a[3]} | {a[4]} | ⭐{a[5]} | {a[9]} | {a[10]} |")
        md.append("")
    md.append("---")
    md.append("")

    # 7. 潜水活动
    effective_dives = effective_dive_sites()
    if effective_dives:
        md.append("## 8. 潜水活动")
        md.append("")
        md.append("| 目的地 | 潜点名称 | 类型 | 价格(元) | 评分 | 适合等级 | 描述 |")
        md.append("|---|---|---|---|---|---|---|")
        for d in effective_dives:
            md.append(f"| {d[0]} | {d[1]}({d[2]}) | {d[3]} | {d[4]} | ⭐{d[5]} | {d[9]} | {d[10]} |")
        md.append("")
        md.append("---")
        md.append("")

    # 9. 预算汇总
    md.append("## 9. 预算汇总")
    md.append("")
    md.append("| 天数 | 日期 | 行程 | 住宿 | 餐饮 | 交通 | 活动 | 其他 | 日合计 |")
    md.append("|---|---|---|---|---|---|---|---|---|")
    for b in BUDGET:
        md.append(f"| {b[0]} | {b[1]} | {b[2]} | {b[3]} | {b[4]} | {b[5]} | {b[6]} | {b[7]} | {b[8]} |")
    md.append("")
    md.append("---")
    md.append("")

    # 10. 实用信息
    md.append("## 10. 实用信息")
    md.append("")
    for p in PRACTICAL:
        md.append(f"- **{p[0]}：** {p[1]}")
    md.append("")

    if WORTH_IT:
        md.append("## 核心体验")
        md.append("")
        md.append("| 目的地 | 名称 | 纳入理由 | 适合人群 | 建议停留 | 季节/限制 | 预约要求 |")
        md.append("|---|---|---|---|---|---|---|")
        for row in WORTH_IT:
            md.append(f"| {row[0]} | {display_name(row[1], row[2])} | {row[3]} | {row[4]} | {row[5]} | {row[6]} | {row[7]} |")
        md.append("")
    if LOCAL_CHAINS:
        md.append("## 当地连锁与便捷选择")
        md.append("")
        md.append("| 目的地 | 品牌 | 类型 | 品牌特点 | 适用场景 | 价格 | 附近位置 |")
        md.append("|---|---|---|---|---|---|---|")
        for row in LOCAL_CHAINS:
            md.append(f"| {row[0]} | {display_name(row[1], row[2])} | {row[3]} | {row[4]} | {row[5]} | {row[6]} | {row[7]} |")
        md.append("")
    if PACKING:
        md.append("## 行前准备")
        md.append("")
    if LOCAL_KNOWLEDGE:
        md.append("## 当地旅行要点")
        md.append("")
        md.append("| 复核主题 | 当地要点 | 出发前复核 | 来源/核验状态 |" if OUTPUT_LANG != "en" else "| Recheck Topic | Local Notes | Pre-departure Recheck | Source / Verification Status |")
        md.append("|---|---|---|---|")
        for row in LOCAL_KNOWLEDGE:
            if OUTPUT_LANG == "en":
                md.append(f"| {row[1]} | {row[3]} | {row[5]} | {row[6]} |")
            else:
                md.append(f"| {row[0]} | {row[2]} | {row[4]} | {row[6]} |")
        md.append("")
        md.append("| 类别 | 物品 | 携带/当地购买 | 目的地类型 | 准备时点 | 说明 |")
        md.append("|---|---|---|---|---|---|")
        for row in PACKING:
            md.append(f"| {row[0]} | {display_name(row[1], row[2])} | {row[3]} | {row[4]} | {row[5]} | {row[6]} |")
        md.append("")
    md.append("---")
    md.append("")

    # 在地工具
    active_apps_cn = [app for app in LOCAL_APPS if app.get("availability_status") not in ("retired", "pending")]
    if active_apps_cn:
        md.append("## 在地工具")
        md.append("")
        md.append("> 本地出行、美食外卖、通信与应急服务推荐工具。建议行前下载并配置好网络与支付。")
        md.append("")
        essential_apps = [a for a in active_apps_cn if a.get("priority") == "essential"]
        if essential_apps:
            md.append("### 出发前建议装好 (核心工具)")
            md.append("")
            for app in essential_apps:
                name = app.get("name", "")
                cat = app.get("category", "")
                uses = "、".join(app.get("use_cases_cn") or [])
                limits = "；".join(app.get("limitations_cn") or []) or "正常可用"
                links = []
                if app.get("official_url"): links.append(f"[官方网站]({app['official_url']})")
                if app.get("ios_url"): links.append(f"[App Store]({app['ios_url']})")
                if app.get("android_url"): links.append(f"[Google Play]({app['android_url']})")
                link_str = " · ".join(links)
                dests = "、".join(app.get("destinations", []))
                md.append(f"- **{name}** ({cat})：{uses}")
                md.append(f"  - 适用范围：{dests} | 状态：{app.get('availability_status')}")
                md.append(f"  - 限制与说明：{limits}")
                md.append(f"  - 官方入口：{link_str}")
                md.append("")
        other_apps = [a for a in active_apps_cn if a.get("priority") != "essential"]
        if other_apps:
            md.append("### 按需安装与场景工具")
            md.append("")
            for app in other_apps:
                name = app.get("name", "")
                cat = app.get("category", "")
                uses = "、".join(app.get("use_cases_cn") or [])
                limits = "；".join(app.get("limitations_cn") or []) or "正常可用"
                links = []
                if app.get("official_url"): links.append(f"[官方网站]({app['official_url']})")
                if app.get("ios_url"): links.append(f"[App Store]({app['ios_url']})")
                if app.get("android_url"): links.append(f"[Google Play]({app['android_url']})")
                link_str = " · ".join(links)
                dests = "、".join(app.get("destinations", []))
                md.append(f"- **{name}** ({cat})：{uses}")
                md.append(f"  - 适用范围：{dests} | 状态：{app.get('availability_status')}")
                md.append(f"  - 限制与说明：{limits}")
                md.append(f"  - 官方入口：{link_str}")
                md.append("")
        md.append("---")
        md.append("")

    md.append(f"*{guide_title}*")

    md_text = '\n'.join(md)
    if OUTPUT_LANG == "en":
        md_translations = {
            '咖啡馆推荐': 'Cafés', '家咖啡馆：': ' cafés:',
            "旅行攻略大全": "Travel Guide",
            "目的地总览": "Destinations", "共 **": "Total: **", "个目的地：": " destinations:",
            "路线方案": "Route Options", "每日行程详情": "Daily Itinerary", "仅展示推荐路线的每日行程点位顺序": "Daily itinerary for the recommended route",
            "住宿推荐": "Accommodation", "共 **": "Total: **", "家酒店：": " hotels:",
            "美食推荐": "Food & Restaurants", "家餐厅：": " restaurants:", "交通信息": "Transport",
            "景点活动": "Attractions & Activities", "个景点/活动：": " attractions/activities:",
            "潜水活动": "Diving", "预算汇总": "Budget Summary", "实用信息": "Practical Information",
            "中文名": "Chinese Name", "英文名": "English Name", "区域": "Region", "核心体验": "Key Experiences",
            "建议天数": "Suggested Days", "最佳季节": "Best Season", "到达方式": "Arrival", "是否纳入环线": "Included in Route",
        }
        md_translations.update({
            "| 方案名称 | 天数 | 路线 | 特色 | 适合人群 | 预算(元) | 交通方式 |": "| Route Option | Days | Route | Highlights | Best For | Budget (CNY) | Transport |",
            "| 酒店名称 | 类型 | 参考价(元/晚) | 评分 | 评价数 | 特色 |": "| Hotel | Type | Reference Price (CNY/night) | Rating | Reviews | Highlights |",
            "| 餐厅名称 | 特色菜品 | 人均(元) | 评分 | 位置 |": "| Restaurant | Signature Dishes | Average Spend (CNY) | Rating | Location |",
            "| 景点名称 | 类型 | 门票(元) | 评分 | 游玩时间 | 描述 |": "| Attraction | Type | Ticket (CNY) | Rating | Suggested Time | Description |",
            "| 路线 | 交通方式 | 运营公司 | 参考票价(元) | 行程时间 | 班次频率 | 备注 |": "| Route | Transport | Operator | Reference Fare (CNY) | Travel Time | Frequency | Notes |",
            "| 天数 | 日期 | 行程 | 住宿 | 餐饮 | 交通 | 活动 | 其他 | 日合计 |": "| Days | Date | Plan | Lodging | Food | Transport | Activities | Other | Daily Total |",
        })
        for source, target in md_translations.items():
            md_text = md_text.replace(source, target)
        for source, target in sorted(EN_TEXT_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
            md_text = md_text.replace(source, target)
        untranslated = sorted(set(re.findall(r"[\u3400-\u9fff]+", md_text)))
        if untranslated:
            raise ValueError("English Markdown output blocked; untranslated text: " + ", ".join(untranslated[:20]))
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(md_text)
    print(f"Markdown saved: {output_path}")


# ============================================================
# MAIN
# ============================================================

def validate_data_integrity(expected_days=None, require_images=True):
    """Fail before delivery when the data model would create a broken guide."""
    _require_formal_run_manifest()
    validate_cafes({'destinations': DESTINATIONS, 'cafes': CAFES,
                    'restaurants': RESTAURANTS, 'cafe_coverage': CAFE_COVERAGE,
                    'cafe_classification': CAFE_CLASSIFICATION,
                    'google_place_ids': GOOGLE_PLACE_IDS,
                    'provider_poi_ids': PROVIDER_POI_IDS,
                    'domestic_destination': DOMESTIC_DESTINATION})
    errors = []
    normalized_records = []
    for kind, rows, coord_index in (("hotel", HOTELS, 7), ("restaurant", RESTAURANTS, 7), ("cafe", CAFES, 7), ("attraction", effective_attractions(), 6), ("dive", effective_dive_sites(), 6)):
        for row in rows:
            normalized_records.append({
                "record_id": f"{kind}:{row[1] if len(row) > 1 else ''}",
                "kind": kind,
                "destination": row[0] if row else "",
                "name": row[1] if len(row) > 1 else "",
                "coords": row[coord_index] if len(row) > coord_index else "",
                "source_status": row[-1] if row else "",
                "image_refs": [row[coord_index + 1], row[coord_index + 2]] if len(row) > coord_index + 2 else [],
            })
    for node in effective_transport_nodes():
        normalized_records.append({
            "record_id": f"transport_node:{node.get('place')}:{node.get('name')}",
            "kind": "transport_node",
            "destination": node.get("place", ""),
            "name": node.get("name", ""),
            "coords": node.get("coords", ""),
            "source_status": node.get("source_status", ""),
            "image_refs": [],
        })
    errors.extend(validate_records(normalized_records))
    allowed_categories = {"景点", "餐厅", "咖啡馆", "酒店", "潜水", "交通"}
    validate_provider_contract()
    errors.extend(validate_content_modules())
    errors.extend(validate_transport_mode_contract())
    validate_image_integrity(require_images=require_images, verify_remote=False)
    for i, row in enumerate(TRANSPORT, 1):
        minimum_transport_fields = 9 if DEMO_MODE else 24
        if len(row) < minimum_transport_fields:
            errors.append(f"TRANSPORT[{i}] 字段数量不足，Live 必须包含24个交通与班次字段")
            continue
        if any(not str(row[idx]).strip() for idx in range(6)):
            errors.append(f"TRANSPORT[{i}] 缺少路线/方式/运营方/票价/耗时/班次字段")
    if not DEMO_MODE and TRANSPORT and not TRANSPORT_NODES:
        errors.append("Live 交通数据缺少 TRANSPORT_NODES；城市与汽车站/港口/机场必须分离记录")
    if TRANSPORT_NODES:
        node_keys = {(str(node["place"]).strip(), str(node["name"]).strip())
                     for node in effective_transport_nodes()}
        for i, row in enumerate(TRANSPORT, 1):
            route = str(row[0]).strip() if row else ""
            origin, separator, destination = route.partition("→")
            if not separator:
                errors.append(f"TRANSPORT[{i}] 路线必须使用出发地→目的地格式")
                continue
            linked_origin = str(row[12]).strip() if len(row) > 12 else ""
            linked_destination = str(row[13]).strip() if len(row) > 13 else ""
            if not linked_origin or not linked_destination:
                errors.append(f"TRANSPORT[{i}] 缺少出发节点/到达节点，不能只用城市名代替")
                continue
            if (origin.strip(), linked_origin) not in node_keys:
                errors.append(f"TRANSPORT[{i}] 出发节点未在 TRANSPORT_NODES 登记: {origin.strip()} / {linked_origin}")
            if (destination.strip(), linked_destination) not in node_keys:
                errors.append(f"TRANSPORT[{i}] 到达节点未在 TRANSPORT_NODES 登记: {destination.strip()} / {linked_destination}")
    poi_rows = [("HOTELS", HOTELS, 8, 9, 4), ("RESTAURANTS", RESTAURANTS, 8, 9, 4), ("CAFES", CAFES, 8, 9, 4), ("ATTRACTIONS", effective_attractions(), 7, 8, 4), ("DIVE_SITES", effective_dive_sites(), 7, 8, 4)]
    poi_names = set()
    for label, rows, img1_idx, img2_idx, price_idx in poi_rows:
        for i, row in enumerate(rows, 1):
            if len(row) <= max(img2_idx, price_idx):
                errors.append(f"{label}[{i}] 字段数量不足")
                continue
            name = str(row[1]).strip() if len(row) > 1 else ""
            if not name:
                errors.append(f"{label}[{i}] 点位名称为空")
            poi_names.add(name)
            price = str(row[price_idx]).strip()
            if not price or price in {"待核验", "待补充", "未知", "N/A"}:
                errors.append(f"{label}[{i}] {name or '未命名'} 价格仍是占位值")
            if require_images and (not str(row[img1_idx]).strip() or not str(row[img2_idx]).strip()):
                errors.append(f"{label}[{i}] {name or '未命名'} 缺少两张可访问图片URL")

    route_names = [str(r[0]).strip() for r in ROUTES if r and r[0]]
    itinerary_routes = {}
    for i, item in enumerate(effective_itinerary(), 1):
        if len(item) < 6:
            errors.append(f"ITINERARY[{i}] 字段数量不足")
            continue
        route, day, _, category, name, coords = item[:6]
        itinerary_routes.setdefault(str(route), set()).add(str(day))
        if str(category).strip() not in allowed_categories:
            errors.append(f"ITINERARY[{i}] 未知点位类型: {category}")
        if str(category).strip() == "交通":
            transport_names = {str(row[0]).strip() for row in TRANSPORT if row and row[0]}
            if str(name).strip() not in transport_names:
                errors.append(f"ITINERARY[{i}] 交通点 {name} 不存在于 TRANSPORT 数据")
        elif str(name).strip() not in poi_names:
            errors.append(f"ITINERARY[{i}] 点位 {name} 不存在于 POI 数据")
        if not parse_coords(str(coords))[0] is not None:
            errors.append(f"ITINERARY[{i}] 坐标格式错误: {coords}")

    expected = expected_days
    if expected is None and itinerary_routes:
        expected = max((int(d.replace("Day ", "")) for days in itinerary_routes.values() for d in days if str(d).startswith("Day ")), default=0)
    for route in route_names:
        days = itinerary_routes.get(route, set())
        if not days:
            errors.append(f"路线 {route} 没有每日行程数据")
            continue
        if expected:
            actual = {int(str(d).replace("Day ", "")) for d in days if str(d).startswith("Day ")}
            missing = set(range(1, expected + 1)) - actual
            if missing:
                errors.append(f"路线 {route} 缺少天数: {sorted(missing)}")

    global TRAVEL_MODE
    if TRAVEL_MODE not in {"自驾", "非自驾"}:
        TRAVEL_MODE = "非自驾"
    require_itinerary_transport = not (DOMESTIC_DESTINATION and effective_travel_mode() == "自驾")
    # TRANSPORT is not merely a separate worksheet. Every collected inter-city
    # edge must be visible in the daily itinerary so the map and route panel
    # explain how the traveller actually moves between destinations.
    transport_names = {str(row[0]).strip() for row in TRANSPORT if row and row[0]}
    itinerary_transport_names = {
        str(item[4]).strip() for item in effective_itinerary()
        if len(item) >= 6 and str(item[3]).strip() == "交通"
    }
    missing_transport = sorted(transport_names - itinerary_transport_names)
    if require_itinerary_transport and missing_transport:
        errors.append(f"TRANSPORT 中的交通边未进入 ITINERARY: {missing_transport}")
    if require_itinerary_transport and transport_names:
        for route in route_names:
            route_transport_count = sum(
                1 for item in effective_itinerary()
                if len(item) >= 6 and str(item[0]).strip() == route and str(item[3]).strip() == "交通"
            )
            if route_transport_count == 0:
                errors.append(f"路线 {route} 含跨目的地规划但没有每日交通节点")

    if errors:
        raise ValueError("数据完整性校验失败:\n- " + "\n- ".join(errors[:40]) + (f"\n- ...另有 {len(errors)-40} 项" if len(errors) > 40 else ""))
    return True

def _require_formal_run_manifest():
    """Prevent ad-hoc builders from producing delivery artifacts."""
    if os.environ.get("TRAVEL_SCOPE_FORMAL_RUN") != "1":
        raise ValueError("正式生成已阻断：缺少 TRAVEL_SCOPE_FORMAL_RUN=1；临时生成器不得直接产出攻略")
    manifest_path = os.environ.get("TRAVEL_SCOPE_RUN_MANIFEST", "").strip()
    if not manifest_path or not os.path.isfile(manifest_path):
        raise ValueError("正式生成已阻断：缺少运行 manifest，必须先完成标准 SOP 阶段")
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception as exc:
        raise ValueError(f"正式生成已阻断：运行 manifest 无法读取: {exc}") from exc
    required = {"destination_discovery", "route_exploration", "source_search", "source_audit", "section_media_collection", "section_media_contact_sheet_review", "qa"}
    stages = manifest.get("completed_stages") or []
    missing = sorted(required - set(stages))
    if missing:
        raise ValueError(f"正式生成已阻断：SOP 阶段未完成: {missing}")
    if manifest.get("source_audit_passed") is not True:
        raise ValueError("正式生成已阻断：数据源审计未通过")
    intake = manifest.get("intake") or {}
    required_intake = {"q0_destination", "q1_time", "q2_days", "q3_tier", "q4_transport", "q5_arrival", "q6_departure", "q7_depth", "q8_pace"}
    missing_intake = sorted(key for key in required_intake if not str(intake.get(key, "")).strip())
    if missing_intake:
        raise ValueError(f"正式生成已阻断：manifest 缺少 Q0-Q8 原始需求: {missing_intake}")
    evidence_path = manifest.get("source_evidence_path")
    # run 根＝这份 run manifest 自己所在的目录：相对值在这里解析，换机／换目录不用改 manifest 的写法。
    evidence_path = (str(resolve_run_path(evidence_path, Path(manifest_path).resolve().parent))
                     if evidence_path else evidence_path)
    if not evidence_path or not os.path.isfile(evidence_path):
        raise ValueError("正式生成已阻断：缺少来源证据台账")

def build_window_extra(out_dir: str = "") -> dict:
    """生成期账本的自证面（scope／档位／绑定字段）——emit 与 live 快照共用，避免两套写法。"""
    register = zero_call_build_window_register()
    out_dir = out_dir or BUILD_WINDOW_STATE.get("output_dir") or ""
    artifacts = [str(path) for path in BUILD_WINDOW_STATE.get("artifacts") or [] if os.path.isfile(path)]
    return {
        "scope": "%s:%s" % (register["scope_prefix"],
                            os.path.basename(os.path.normpath(out_dir)) if out_dir else "(未记录)"),
        "evidence_tier": register["evidence_tier"],
        "input_sha256": RUNTIME_INPUT_SHA256 or None,
        "input_path": RUNTIME_INPUT_PATH or None,
        "artifacts": [{"path": path, "sha256": file_sha256(Path(path))} for path in artifacts],
        "argv": list(BUILD_WINDOW_STATE.get("argv") or []),
        "loopback_explanation": str(register.get("loopback_explanation") or ""),
        "produced_by": "scripts/gen_travel_scope.py（正式构建窗口内）",
        "binding_fields_registered": list(register.get("binding_fields") or []),
    }


def zero_call_build_window_register() -> dict:
    from spa_renderer import zero_call_build_window
    return zero_call_build_window()


def live_build_window_ledger() -> dict | None:
    """把**此刻**的生成窗口账本交给内嵌的正式门禁（§11 V4 的强证据档 generation_phase）。

    formal_data_gate 的设计就是：调用方给了生成期账本就用它；没给且窗口没在跑才自己装一个弱窗口
    （self_check_window）。现在窗口由生成器装着（window_active 为真），门禁不会重复 arm
    （arm 会把计数清零＝丢掉证据），所以这一段必须自己把账交下去——不交就是
    GATE_ZERO_CALL_LEDGER_ABSENT，而不是「当作 0」。
    """
    from spa_renderer import formal_build_declared
    if not formal_build_declared():
        return None
    import zero_call_sentinel
    if not zero_call_sentinel.window_active():
        return None
    return zero_call_sentinel.ledger(build_window_extra())


def emit_build_window_ledger() -> dict:
    """把「这一段构建到底有没有往外走」写成执行期账本（ZH-RELEASE-2 步6c）。

    §11 V4 点名四项硬零必须来自执行期拦截器，不接受源码扫描；而此前树里只有两种窗口有账：
    门禁自己那一趟审计（formal_data_gate 报 self_check_window）与测试窗口
    （test_v422_map_execution 的 guarded scope）。**正式构建那一段一直没有账**，
    所以「生成时零 Google 计费／零密钥／零抓取」只是推论。这一条把它变成测量，
    并把账本钉在这段构建真读过的输入字节与真写出的产物字节上。

    smoke／demo 不产这份账：没有正式信号就没有「正式构建窗口」这件事，硬写一份等于伪造证据档位。
    """
    from spa_renderer import formal_build_declared
    if not formal_build_declared():
        return {}
    register = zero_call_build_window_register()
    out_dir = BUILD_WINDOW_STATE.get("output_dir") or ""
    if not out_dir:
        # 构建在记下输出目录之前就失败了：这一段没有可指的地方，就不写账——地图门会按
        # GATE_ZERO_CALL_LEDGER_ABSENT 阻断，那是正确处置，比一份指不到字节的绿账好。
        print("[ZERO-CALL-BUILD-LEDGER] SKIPPED：输出目录尚未记下，本段构建没有可交付的执行期账")
        return {}
    import zero_call_sentinel
    ledger = zero_call_sentinel.ledger(build_window_extra(out_dir))
    path = Path(out_dir) / str(register["outputs_relpath"])
    blob = json.dumps(ledger, ensure_ascii=False, indent=2).encode("utf-8")
    assert blob.count(b"\r\n") == 0, "账本注入 CRLF"
    path.write_bytes(blob)
    print("[ZERO-CALL-BUILD-LEDGER] %s armed=%s interceptors=%s counts=%s ledger_sha256_16=%s artifacts=%d"
          % (path, ledger["armed"], len(ledger["interceptors_armed"]),
             json.dumps(ledger["counts"], ensure_ascii=False),
             ledger["ledger_sha256_16"], len(ledger["artifacts"])))
    return ledger


def run_main_under_build_window() -> None:
    """正式构建＝把 main() 关进零调用哨兵窗口；账本在窗口关掉后写（记的是这一段真装过的拦截器）。

    构建自己失败（sys.exit(2) 之类）时账本照写、异常照抛：中断的正式构建更需要一份
    「这一段往外走过没有」的账，而不是让异常顺手把证据吃掉。
    """
    from spa_renderer import formal_build_declared, zero_call_build_window
    if not formal_build_declared():
        main()
        return
    import zero_call_sentinel
    register = zero_call_build_window()
    with zero_call_sentinel.guarded(str(register["scope_prefix"])):
        try:
            main()
        finally:
            emit_build_window_ledger()


def main():
    parser = argparse.ArgumentParser(description='Generate travel guide Excel + HTML + Markdown')
    parser.add_argument('--output-dir', default='.', help='Output directory')
    parser.add_argument('--map-platform', default='all',
                        choices=['google', 'apple', 'amap', 'baidu', 'all'],
                        help='Map platform for HTML navigation buttons')
    parser.add_argument('--country', default=None, help='Override country name for filenames')
    parser.add_argument('--amap-js-key', default='', help='AMap JS API key for map route view')
    parser.add_argument('--amap-security', default='', help='AMap JS API security code')
    parser.add_argument('--google-maps-key', default='', help='Google Maps JS API key for optional overseas live map')
    parser.add_argument('--enable-live-map', action='store_true', help='Explicitly enable provider JavaScript map; default is offline route + web navigation')
    parser.add_argument('--language', default='cn', choices=['cn', 'en', 'both'],
                        help='Output language: cn, en, or both (default: cn)')
    parser.add_argument('--delivery-profile', default='reader', choices=['reader', 'review', 'full_audit'],
                        help='Delivery profile: reader (SPA only), review (SPA + research xlsx), full_audit (all legacy artifacts)')
    parser.add_argument('--artifact-slug', default=None,
                        help='ASCII lowercase kebab-case slug for delivery filenames (e.g. island-guide, city-trip)')
    parser.add_argument('--include-legacy-renderer', action='store_true',
                        help='Explicitly output classic split-v1 HTML in addition to the formal SPA')
    parser.add_argument('--include-markdown', action='store_true',
                        help='Explicitly output Markdown documents')
    parser.add_argument('--mode', default='live', choices=['live', 'demo'],
                        help='live uses collected/provider data; demo uses offline fixture data')
    parser.add_argument('--fixture', default=None,
                        help='Demo fixture JSON path (defaults to fixtures/demo.json)')
    parser.add_argument('--data', default=None, help='Run-local verified JSON dataset for live mode')
    parser.add_argument('--expected-days', type=int, default=None, help='Expected trip days for strict itinerary validation')
    parser.add_argument('--no-strict-qa', action='store_true', help='Allow incomplete data; not recommended for delivery')
    parser.add_argument('--allow-partial-translation', action='store_true', help='Allow incomplete EN translation as research draft without blocking')
    parser.add_argument('--allow-reseal', action='store_true',
                        help='输入相对已封存状态发生变化时，允许显式重新封存（必须同时给出 --reseal-reason）')
    parser.add_argument('--reseal-reason', default='', help='重新封存的原因，会写入 manifest.seal_history')
    parser.add_argument('--reader-profile', default=None,
                        help='读者语言档位（references/renderer-contract.json::reader_language.profiles 的登记名）；'
                             '不给就取合同 formal_profile。ZH-RELEASE-1：正式构建必须落在登记为正式的档位上，'
                             '未登记档位直接报错，不做默认放宽。')
    args = parser.parse_args()
    verify_product()
    if args.fixture and args.mode != 'demo':
        parser.error('--fixture requires explicit --mode demo; use --data for live research')
    if args.data and args.mode != 'live':
        parser.error('--data is for live research, not demo fixtures')
    if args.mode == 'live' and not args.data:
        parser.error('Live mode requires --data; do not edit installed DATA constants')
    if args.enable_live_map:
        parser.error('The recovered split renderer supports ordinary web links only; live-map rendering is not implemented')

    global COUNTRY, OUTPUT_LANG, DEMO_MODE, GOOGLE_MAPS_KEY, LIVE_MAP_REQUESTED, TRANSLATION_CACHE, ALLOW_PARTIAL_TRANSLATION
    DEMO_MODE = args.mode == 'demo'
    GOOGLE_MAPS_KEY = args.google_maps_key.strip()
    LIVE_MAP_REQUESTED = bool(args.enable_live_map)
    ALLOW_PARTIAL_TRANSLATION = bool(args.allow_partial_translation)
    if DEMO_MODE or args.data:
        fixture_path = args.data or args.fixture or os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'demo.json')
        fixture_path = os.path.abspath(fixture_path)
        if not os.path.isfile(fixture_path):
            print(f"ERROR: Fixture not found: {fixture_path}")
            sys.exit(2)
        load_demo_fixture(fixture_path)
    if args.country:
        COUNTRY = args.country
    if not str(COUNTRY).strip():
        parser.error('Dataset must provide a non-empty country; no destination default is permitted')

    # Every builder, including country-specific builders, must hydrate the
    # shared rows through the same provider mapping before any QA or output.
    apply_provider_overrides()

    # Determine map platforms
    if args.map_platform == 'all':
        map_platforms = ['google', 'apple'] if _is_overseas() else ['amap', 'baidu']
    else:
        map_platforms = [args.map_platform]

    output_dir = os.path.abspath(args.output_dir)
    BUILD_WINDOW_STATE["output_dir"] = output_dir
    BUILD_WINDOW_STATE["argv"] = list(sys.argv[1:])
    os.makedirs(output_dir, exist_ok=True)
    # Ordinary local exports translate from the supplied in-memory dictionary.
    # Persistent/API caches are an explicit provider workflow, not a prerequisite.
    TRANSLATION_CACHE = None

    # Validate data
    if not DESTINATIONS or len(DESTINATIONS) < 1:
        print("ERROR: DESTINATIONS is empty. Supply a verified run-local dataset with --data.")
        print("Do not edit the installed generator's source constants.")
        sys.exit(1)

    if DEMO_MODE:
        print("[DEMO] Offline fixture mode: no provider APIs or API keys are used.")
        print("[DEMO] Formal production source-audit gate is not applicable to fixture output.")
        # Demo skips the formal source-audit gate, but never skips structural
        # media QA; bad category reuse must not be rendered as a valid sample.
        try:
            validate_image_integrity(require_images=True)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            print("修复 fixtures 或上游数据中的图片映射后再生成；不能用 --no-strict-qa 绕过图片门禁。")
            sys.exit(2)
    elif not args.no_strict_qa:
        # Basic offline route view and ordinary web navigation do not require
        # a provider JavaScript key. A key only enables the optional live map.
        if args.enable_live_map and _is_overseas() and not args.google_maps_key:
            print("ERROR: 已请求海外实时地图，但未提供 --google-maps-key；请关闭 --enable-live-map，或提供对应 Key。")
            sys.exit(2)
        if args.enable_live_map and not _is_overseas() and not args.amap_js_key:
            print("ERROR: 已请求国内实时地图，但未提供 --amap-js-key；请关闭 --enable-live-map，或提供对应 Key。")
            sys.exit(2)
        try:
            validate_data_integrity(
                expected_days=args.expected_days,
                require_images=bool(IMAGE_COLLECTION.get("require_complete", False)),
            )
            manifest_path = Path(os.environ["TRAVEL_SCOPE_RUN_MANIFEST"])
            manifest_value = json.loads(manifest_path.read_text(encoding="utf-8"))
            run_root = manifest_path.resolve().parent      # 相对输入路径的解析基准＝这份 manifest 所在的 run
            scope_path = resolve_run_path(manifest_value.get("scope_path", ""), run_root)
            corridors_path = resolve_run_path(manifest_value.get("route_corridors_path", ""), run_root)
            asset_path = resolve_run_path(manifest_value.get("asset_manifest_path", ""), run_root)
            if not all(path.is_file() for path in (scope_path, corridors_path, asset_path)):
                raise ValueError("正式生成缺少 scope、route_corridors 或 asset_manifest 证据")
            formal_result = audit_formal_data(
                json.loads(Path(args.data).read_text(encoding="utf-8")), manifest_value,
                json.loads(scope_path.read_text(encoding="utf-8")),
                json.loads(corridors_path.read_text(encoding="utf-8")),
                json.loads(asset_path.read_text(encoding="utf-8")),
                # 步6c：把此刻的生成窗口账本交下去（formal_data_gate 认这是 generation_phase 强证据；
                # 不给就是 GATE_ZERO_CALL_LEDGER_ABSENT，绝不按「当作 0」放行）。
                zero_call_ledger=live_build_window_ledger(),
            )
            if formal_result["errors"]:
                raise ValueError("正式数据门禁失败:\n- " + "\n- ".join(formal_result["errors"]))
        except ValueError as exc:
            print(f"ERROR: {exc}")
            print("Use --no-strict-qa only for an explicitly labelled research draft.")
            sys.exit(2)

    # Determine artifact slug (v4.1.8: required ASCII lowercase kebab-case)
    artifact_slug = args.artifact_slug
    if not artifact_slug and args.data:
        try:
            raw_data = json.loads(Path(args.data).read_text(encoding="utf-8"))
            artifact_slug = raw_data.get("artifact_slug") or raw_data.get("destination_slug")
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"Unable to read artifact_slug from dataset: {exc}")
    if not artifact_slug:
        parser.error("Formal artifact_slug is required via --artifact-slug or dataset.artifact_slug; no filename fallback is permitted")
    artifact_slug = str(artifact_slug).strip()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", artifact_slug):
        parser.error("artifact_slug must be ASCII lowercase kebab-case")

    # v4.2.1 §13.2.2: the seal is written by the generator, before a single byte of
    # output exists. Nothing downstream recomputes it, so an out-of-band edit to the
    # input now contradicts the manifest instead of being endorsed by it.
    release_root = Path(__file__).resolve().parents[1]
    seal_manifest_path = Path(os.environ.get("TRAVEL_SCOPE_RUN_MANIFEST", "").strip()) if not DEMO_MODE else None
    seal_active = bool(args.data and seal_manifest_path and seal_manifest_path.is_file()
                       and not os.environ.get(REPLAY_ENV))
    if seal_active:
        origin_manifest = json.loads((release_root / "product-origin.json").read_text(encoding="utf-8"))
        release_contract = json.loads((release_root / "references/renderer-contract.json").read_text(encoding="utf-8"))
        seal_argv = [str(Path(sys.argv[0]).resolve())] + list(sys.argv[1:])
        seal_command = "python " + " ".join(f'"{token}"' if " " in token else token for token in seal_argv)
        try:
            seal_inputs(
                manifest_path=seal_manifest_path,
                dataset_path=Path(args.data),
                run_dir=seal_manifest_path.parent,
                generation_command=seal_command,
                generation_argv=seal_argv,
                skill_version=origin_manifest["version"],
                renderer_id=origin_manifest["renderer_id"],
                spa_renderer_id=str(release_contract.get("spa_renderer_id") or release_contract.get("renderer_id") or ""),
                reason=args.reseal_reason,
                allow_reseal=args.allow_reseal,
                product_fingerprint=file_sha256(release_root / "product-origin.json"),
            )
        except ValueError as exc:
            print(f"ERROR: 输入封存失败，生成已阻断: {exc}")
            sys.exit(2)
        seal_record = json.loads(seal_manifest_path.read_text(encoding="utf-8"))["seal"]
        os.environ[SEAL_TIMESTAMP_ENV] = str(seal_record.get("sealed_at") or "")
        # ZH-RELEASE-2 步1：来源台账的血缘自证只能指向**被封存的那份字节**。封存值与装载值不一致
        # ＝输入在「读进来」与「钉死」之间动了（或 --data 与装载面不是同一份文件）。这时候带进
        # 产物的 input_sha256 就是假账，所以停在生成阶段，而不是让下游拿一个指不到字节的摘要出货。
        if str(seal_record.get("input_sha256") or "") != RUNTIME_INPUT_SHA256:
            raise SystemExit(
                "SOURCE_LEDGER_INPUT_SHA_DRIFT：封存记录 input_sha256=%s 与本次装载的输入字节摘要 %s "
                "不一致（装载面=%s，manifest=%s）。血缘自证指不到具体字节，正式生成已阻断；"
                "请确认 --data 就是被封存的那一份，或显式重新封存后再构建。"
                % (str(seal_record.get("input_sha256"))[:12], RUNTIME_INPUT_SHA256[:12],
                   RUNTIME_INPUT_PATH, seal_manifest_path))

    print(f"Generating travel guide for: {COUNTRY} (slug: {artifact_slug}, profile: {args.delivery_profile})")
    print(f"Map platforms: {', '.join(map_platforms)}")
    print(f"Output directory: {output_dir}")
    print()

    generated = []

    # 1. Authoritative SPA Generation (Single stage, always produced)
    # File name follows ASCII kebab-case: {artifact_slug}-travel-guide.html
    spa_path = os.path.join(output_dir, f"{artifact_slug}-travel-guide.html")
    canonical_dataset = export_runtime_dataset(output_dir=output_dir, map_platforms=map_platforms)
    canonical_dataset["artifact_slug"] = artifact_slug
    from spa_renderer import formal_reader_profile, reader_profile_spec
    declared_profile = args.reader_profile or formal_reader_profile()
    profile_spec = reader_profile_spec(declared_profile)          # 未登记档位 ⇒ 直接报错
    if profile_spec.get("shipping") is not True:
        raise SystemExit("%s 档位不允许出现在正式构建里（合同 shipping=false）；"
                         "审计档产物只写 .temp" % declared_profile)
    render_spa_document(spa_path, canonical_dataset,
                        run_asset_dir=(DATA_ROOT / "assets") if DATA_ROOT else None,
                        reader_profile=declared_profile)
    print("[READER-PROFILE] %s（合同 formal_profile=%s，允许出货=%s）"
          % (declared_profile, formal_reader_profile(), profile_spec.get("shipping")))
    generated.append(spa_path)

    # 2. Review Profile: Output unified research workbook
    if args.delivery_profile in ("review", "full_audit"):
        research_excel_path = os.path.join(output_dir, f"{artifact_slug}-travel-research.xlsx")
        OUTPUT_LANG = "cn"
        generate_excel(research_excel_path, include_research=True)
        generated.append(research_excel_path)

    # 3. Full Audit Profile or Explicit Flags: Legacy split HTML & Markdown
    if args.delivery_profile == "full_audit" or args.include_legacy_renderer:
        languages = ['cn', 'en'] if args.language == 'both' else [args.language]
        for lang in languages:
            OUTPUT_LANG = lang
            suffix = "" if lang == "cn" else "-en"
            excel_path = os.path.join(output_dir, f"{COUNTRY}旅行攻略大全{suffix}.xlsx")
            html_path = os.path.join(output_dir, f"{COUNTRY}旅行攻略-地图标记{suffix}.html")
            generate_excel(excel_path, include_research=False)
            html_amap_key = args.amap_js_key if args.enable_live_map else ''
            html_google_key = args.google_maps_key if args.enable_live_map else ''
            generate_html(html_path, map_platforms, html_amap_key, args.amap_security, html_google_key)
            generated.extend([excel_path, html_path])

        if args.language == "both":
            bilingual_path = os.path.join(output_dir, f"{COUNTRY}旅行攻略-双语.html")
            combine_bilingual_html(
                os.path.join(output_dir, f"{COUNTRY}旅行攻略-地图标记.html"),
                os.path.join(output_dir, f"{COUNTRY}旅行攻略-地图标记-en.html"),
                bilingual_path,
            )
            generated.append(bilingual_path)

    if args.delivery_profile == "full_audit" or args.include_markdown:
        languages = ['cn', 'en'] if args.language == 'both' else [args.language]
        for lang in languages:
            OUTPUT_LANG = lang
            suffix = "" if lang == "cn" else "-en"
            md_path = os.path.join(output_dir, f"{COUNTRY}旅行攻略大全{suffix}.md")
            generate_markdown(md_path)
            generated.append(md_path)

    print(f"\n=== SUMMARY ===")
    print(f"Country: {COUNTRY}")
    print(f"Mode: {'demo fixture' if DEMO_MODE else 'live/provider data'}")
    print(f"Destinations: {len(DESTINATIONS)}")
    print(f"Hotels: {len(HOTELS)}")
    print(f"Restaurants: {len(RESTAURANTS)}")
    print(f"Attractions: {len(effective_attractions())}")
    print(f"Dive Sites: {len(effective_dive_sites())}")
    print(f"Transport: {len(TRANSPORT)}")
    print(f"Practical Info: {len(PRACTICAL)}")
    print(f"Itinerary Items: {len(ITINERARY)}")
    print(f"Map platforms: {', '.join(map_platforms)}")
    if seal_active:
        record_build(seal_manifest_path, {Path(path).name: Path(path) for path in generated})

    # 步6c：账本要能指到「这一段真写出来的字节」，所以产物清单在这里交出去（存在才记，
    # 半途失败时清单就是空面，而不是把没写成的文件算进自证）。
    BUILD_WINDOW_STATE["artifacts"] = [path for path in generated if os.path.isfile(path)]

    print(f"\nFiles generated:")
    for index, path in enumerate(generated, 1):
        print(f"  {index}. {path}")
    if TRANSLATION_CACHE is not None:
        TRANSLATION_CACHE.close()


if __name__ == '__main__':
    # 步6c：正式构建（TRAVEL_SCOPE_FORMAL_RUN 由合同登记、由 spa_renderer 唯一判定）整段跑在
    # 零调用哨兵窗口里，退出时写 outputs/zero_call_ledger.json；smoke/demo 原样跑，不产这份账。
    run_main_under_build_window()
