"""Structured domestic POI enrichment from AMap and Baidu.

The module deliberately keeps provider fields separate.  It never treats one
provider's score as another provider's score and never invents missing photos
or ratings.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests


AMAP_SEARCH_URL = "https://restapi.amap.com/v3/place/text"
BAIDU_SEARCH_URL = "https://api.map.baidu.com/place/v2/search"
BAIDU_DETAIL_URL = "https://api.map.baidu.com/place/v2/detail"

FACILITY_TOKENS = (
    "公交站", "停车场", "管理局", "管理处", "管理委员会", "管委会", "检察院", "法院",
    "联络点", "游客中心", "售票处", "服务区", "充电站", "公共厕所", "派出所", "警务室",
    "卫生院", "政府", "委员会", "办事处"
)
NAME_DECORATIONS = ("国家地质公园", "国家公园", "风景区", "景区", "观景台", "旅游区", "景点")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> str:
    value = _text(value)
    return value if re.fullmatch(r"\d+(?:\.\d+)?", value) else ""


def _cache_key(provider: str, name: str, city: str) -> str:
    return f"{provider}|{city}|{name}".lower()


def canonical_poi_name(name: Any) -> str:
    value = re.sub(r"[\s·（）()\-—_、，,。.:：/]+", "", _text(name)).lower()
    changed = True
    while changed:
        changed = False
        for token in NAME_DECORATIONS:
            if value.endswith(token):
                value = value[: -len(token)]
                changed = True
    return value


def is_non_visit_poi(name: Any, poi_type: Any = "") -> bool:
    text = _text(name) + _text(poi_type)
    return any(token in text for token in FACILITY_TOKENS)


def poi_matches_city(poi: dict[str, Any], expected_city: str) -> bool:
    if not expected_city:
        return True
    expected = re.sub(r"[市县区旗盟]", "", _text(expected_city)).lower()
    if not expected:
        return True
    fields = " ".join(_text(poi.get(k)) for k in ("cityname", "adname", "address", "citycode")).lower()
    if not fields:
        return True
    return expected in re.sub(r"[市县区旗盟]", "", fields)


def dedupe_poi_candidates(pois: list[dict[str, Any]], expected_city: str = "", exclude_facilities: bool = False) -> list[dict[str, Any]]:
    """Filter facilities, reject obvious wrong-city matches and collapse nested POI names."""
    kept: list[dict[str, Any]] = []
    seen_canonical: set[str] = set()
    for poi in pois:
        name = _text(poi.get("name"))
        if not name or not _text(poi.get("location")):
            continue
        if exclude_facilities and is_non_visit_poi(name, poi.get("type")):
            continue
        if not poi_matches_city(poi, expected_city):
            continue
        canonical = canonical_poi_name(name)
        if not canonical or canonical in seen_canonical:
            continue
        # A longer provider label such as “景区-神钟山” must not coexist with
        # the canonical “神钟山” record in the same search batch.
        if any(canonical in existing or existing in canonical for existing in seen_canonical):
            continue
        seen_canonical.add(canonical)
        kept.append(poi)
    return kept


class DomesticPoiSources:
    """AMap primary + Baidu secondary structured POI provider."""

    def __init__(self, cache_path: str | Path | None = None):
        self.amap_key = _text(os.environ.get("TRAVEL_SCOPE_AMAP_KEY"))
        self.baidu_key = _text(os.environ.get("TRAVEL_SCOPE_BAIDU_KEY"))
        self.baidu_mode = _text(os.environ.get("TRAVEL_SCOPE_BAIDU_MODE", "core")) or "core"
        self.baidu_core_names = {x.strip() for x in os.environ.get("TRAVEL_SCOPE_BAIDU_CORE_NAMES", "").split(",") if x.strip()}
        self.baidu_max_points = int(os.environ.get("TRAVEL_SCOPE_BAIDU_MAX_POINTS", "50"))
        self.baidu_points_seen = 0
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache: dict[str, Any] = {}
        if self.cache_path and self.cache_path.exists():
            self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def amap_search(self, name: str, city: str) -> dict[str, Any] | None:
        if not self.amap_key:
            raise RuntimeError("缺少 TRAVEL_SCOPE_AMAP_KEY，不能执行高德结构化 POI 查询")
        key = _cache_key("amap", name, city)
        if key in self.cache:
            return self.cache[key]
        data = requests.get(AMAP_SEARCH_URL, params={
            "key": self.amap_key, "keywords": name, "city": city,
            "offset": 5, "page": 1, "extensions": "all",
        }, timeout=25).json()
        pois = data.get("pois") or []
        result = pois[0] if pois else None
        if result:
            self.cache[key] = result
            self._save()
        time.sleep(0.12)
        return result

    def baidu_search(self, name: str, city: str) -> dict[str, Any] | None:
        if self.baidu_mode in {"deferred", "skip"}:
            return None
        if self.baidu_mode == "core":
            if self.baidu_core_names and name not in self.baidu_core_names:
                return None
            if not self.baidu_core_names and self.baidu_points_seen >= self.baidu_max_points:
                return None
            self.baidu_points_seen += 1
        if not self.baidu_key:
            raise RuntimeError("缺少 TRAVEL_SCOPE_BAIDU_KEY，不能执行百度结构化 POI 查询")
        key = _cache_key("baidu", name, city)
        if key in self.cache:
            return self.cache[key]
        data = requests.get(BAIDU_SEARCH_URL, params={
            "ak": self.baidu_key, "query": name, "region": city,
            "output": "json", "scope": 2, "page_size": 10,
        }, timeout=25).json()
        if data.get("status") not in (0, "0"):
            raise RuntimeError(f"百度地点检索失败：status={data.get('status')}，message={data.get('message', '')}")
        results = data.get("results") or []
        result = self._best_baidu_match(name, city, results)
        if result and result.get("uid"):
            detail = requests.get(BAIDU_DETAIL_URL, params={
                "ak": self.baidu_key, "uid": result["uid"],
                "output": "json", "scope": 2,
            }, timeout=25).json()
            if detail.get("status") not in (0, "0"):
                raise RuntimeError(f"百度地点详情失败：status={detail.get('status')}，message={detail.get('message', '')}")
            result["detail_response"] = detail
            self.cache[key] = result
            self._save()
        time.sleep(0.12)
        return result

    @staticmethod
    def _best_baidu_match(name: str, city: str, results: list[dict[str, Any]]) -> dict[str, Any] | None:
        target = re.sub(r"\s+", "", name).lower()
        candidates = []
        for item in results:
            item_name = re.sub(r"\s+", "", _text(item.get("name"))).lower()
            if not item_name:
                continue
            score = 0
            if item_name == target:
                score += 5
            elif target in item_name or item_name in target:
                score += 3
            if city and city in _text(item.get("address")):
                score += 1
            candidates.append((score, item))
        if not candidates or candidates[0][0] < 3:
            return None
        return max(candidates, key=lambda x: x[0])[1]

    def enrich(self, name: str, city: str) -> dict[str, Any]:
        amap = self.amap_search(name, city)
        baidu = self.baidu_search(name, city)
        amap_ext = (amap or {}).get("biz_ext") or {}
        baidu_detail = (baidu or {}).get("detail_response") or {}
        detail_info = baidu_detail.get("result", {}).get("detail_info", {}) if isinstance(baidu_detail, dict) else {}
        return {
            "amap": {
                "poi_id": _text((amap or {}).get("id")),
                "name": _text((amap or {}).get("name")),
                "address": _text((amap or {}).get("address")),
                "location": _text((amap or {}).get("location")),
                "rating": _number(amap_ext.get("rating")),
                "review_count": _text(amap_ext.get("rating_num") or amap_ext.get("comment_num")),
                "price": _text(amap_ext.get("cost")),
                "photos": [_text(x.get("url")) for x in ((amap or {}).get("photos") or []) if _text(x.get("url"))],
            },
            "baidu": {
                "uid": _text((baidu or {}).get("uid")),
                "name": _text((baidu or {}).get("name")),
                "address": _text((baidu or {}).get("address")),
                "location": (baidu or {}).get("location") or {},
                "rating": _number((baidu or {}).get("detail_info", {}).get("overall_rating")),
                "review_count": _text((baidu or {}).get("detail_info", {}).get("comment_num")),
                "price": _text((baidu or {}).get("detail_info", {}).get("price")),
                "photos": [_text(x.get("url") if isinstance(x, dict) else x) for x in (detail_info.get("photo") or detail_info.get("photos") or []) if _text(x.get("url") if isinstance(x, dict) else x)],
                "match_status": "matched" if baidu else "not_found",
            },
        }
