#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static delivery gate for Travel-Scope HTML/Excel outputs."""

import argparse
import html as html_lib
import json
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests


def fail(errors, message):
    errors.append(message)


def image_identity(url):
    parsed = urllib.parse.urlsplit(str(url or "").strip())
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path}" if parsed.scheme and parsed.netloc else str(url or "").strip()


def is_synthetic_image_url(url):
    return bool(re.search(r"images\.unsplash\.com/photo-151000000\d+-000000000\d+", str(url or "")))


def is_invalid_google_media_url(url):
    parsed = urllib.parse.urlsplit(str(url or "").strip())
    if parsed.netloc != "places.googleapis.com":
        return True
    if not re.search(r"^/v1/places/[^/]+/photos/[^/]+/media$", parsed.path):
        return True
    return bool(re.search(r"photo_\d+", parsed.path))


MAP_HOSTS = {
    "www.google.com": "google",
    "maps.google.com": "google",
    "maps.apple.com": "apple",
    "uri.amap.com": "amap",
    "api.map.baidu.com": "baidu",
    "map.baidu.com": "baidu",
}


def _valid_coordinate_pair(first, second, *, order="lat_lng"):
    try:
        lat_value = float(first)
        lng_value = float(second)
    except (TypeError, ValueError):
        return False
    if order == "lng_lat":
        lat_value, lng_value = lng_value, lat_value
    return -90 <= lat_value <= 90 and -180 <= lng_value <= 180


def _coordinate_from_query(query):
    values = urllib.parse.parse_qs(query)
    for key in ("ll", "location", "position"):
        raw = (values.get(key) or [""])[0]
        parts = [x.strip() for x in raw.split(",")]
        if len(parts) == 2:
            return parts
    return None


def _is_coordinate_only(value):
    parts = [x.strip() for x in str(value or "").split(",")]
    return len(parts) == 2 and _valid_coordinate_pair(parts[0], parts[1])


def validate_map_links(html, errors, split_edition=None):
    """Validate generated external map links without making network calls."""
    hrefs = re.findall(r'<a[^>]+class="[^"]*btn-map[^\"]*"[^>]+href="([^"]+)"', html)
    hrefs += re.findall(r'<a[^>]+class="[^"]*offline-destination[^\"]*"[^>]+href="([^"]+)"', html)
    hrefs += re.findall(r'<a[^>]+class="[^"]*modern-map-link[^\"]*"[^>]+href="([^"]+)"', html)
    if not hrefs:
        if split_edition is not None:
            platforms = set(split_edition.get("map_platforms") or [])
            required_templates = {
                "google": "https://www.google.com/maps/search/?api=1&query=",
                "apple": "https://maps.apple.com/?q=",
                "amap": "https://uri.amap.com/marker",
                "baidu": "https://api.map.baidu.com/marker",
            }
            missing = sorted(
                platform for platform in platforms
                if required_templates.get(platform) not in html
            )
            if missing:
                fail(errors, f"分栏渲染器缺少地图跳转模板: {missing}")
            return
        fail(errors, "HTML 未找到可用的外部地图跳转链接")
        return
    for raw_url in hrefs:
        raw_url = html_lib.unescape(raw_url)
        parsed = urllib.parse.urlsplit(raw_url)
        platform = MAP_HOSTS.get(parsed.netloc.lower())
        if parsed.scheme != "https" or not platform:
            fail(errors, f"地图链接平台或协议不合法: {raw_url[:180]}")
            continue
        query = urllib.parse.parse_qs(parsed.query)
        if platform == "google":
            target = (query.get("query") or [""])[0].strip()
            if parsed.path != "/maps/search/" or not target:
                fail(errors, f"Google 地图链接缺少搜索目标: {raw_url[:180]}")
            elif _is_coordinate_only(target):
                fail(errors, f"Google 地图链接只有坐标、缺少可识别地点名称: {raw_url[:180]}")
        elif platform == "apple":
            target = (query.get("q") or [""])[0].strip()
            if parsed.path != "/" or not target:
                fail(errors, f"Apple 地图链接缺少地点名称: {raw_url[:180]}")
            elif _is_coordinate_only(target):
                fail(errors, f"Apple 地图链接只有坐标、缺少可识别地点名称: {raw_url[:180]}")
        elif platform == "amap":
            if parsed.path == "/search":
                if not (query.get("keyword") or [""])[0].strip():
                    fail(errors, f"高德地图搜索链接缺少地点名称: {raw_url[:180]}")
            elif parsed.path == "/marker":
                if not (query.get("name") or [""])[0].strip():
                    fail(errors, f"高德地图标记链接缺少地点名称: {raw_url[:180]}")
            else:
                fail(errors, f"amap 地图链接路径不合法: {raw_url[:180]}")
        elif parsed.netloc.lower() == "map.baidu.com":
            if not parsed.path.startswith("/search/") or not urllib.parse.unquote(parsed.path[len("/search/"):]).strip("/"):
                fail(errors, f"百度地图搜索链接缺少地点名称: {raw_url[:180]}")
        elif parsed.path != "/marker" or not (query.get("title") or [""])[0].strip():
            fail(errors, f"baidu 地图标记链接缺少地点名称或路径不合法: {raw_url[:180]}")
        coordinate = _coordinate_from_query(parsed.query)
        if platform == "google" and not coordinate:
            raw_query = (query.get("query") or [""])[0]
            candidate = [x.strip() for x in raw_query.split(",")]
            if len(candidate) == 2:
                try:
                    float(candidate[0])
                    float(candidate[1])
                    coordinate = candidate
                except ValueError:
                    coordinate = None
        coordinate_order = "lng_lat" if platform == "amap" else "lat_lng"
        if coordinate and not _valid_coordinate_pair(coordinate[0], coordinate[1], order=coordinate_order):
            fail(errors, f"地图链接坐标超出合法范围: {raw_url[:180]}")


import os

def verify_remote_image(url):
    raise ValueError('Remote validation is disabled; use local asset and browser evidence')


def main():
    parser = argparse.ArgumentParser(description="Validate Travel-Scope delivery artifacts")
    parser.add_argument("--html", required=True)
    parser.add_argument("--delivery-xlsx")
    parser.add_argument("--research-xlsx")
    parser.add_argument("--scope-json")
    parser.add_argument("--route-plan-json", help="Optional route semantics/coverage plan")
    parser.add_argument("--expected-days", type=int)
    parser.add_argument("--verify-remote-images", action="store_true", help="Retired: remote verification is disabled")
    args = parser.parse_args()
    if args.verify_remote_images:
        parser.error('Remote verification is disabled; no requests were made')

    errors = []
    html_path = Path(args.html)
    if not html_path.exists():
        print(f"ERROR: HTML not found: {html_path}")
        return 2
    html = html_path.read_text(encoding="utf-8", errors="replace")
    split_payload = None
    split_edition = None
    split_match = re.search(
        r'<script id="travel-data" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    if split_match:
        try:
            split_payload = json.loads(split_match.group(1))
            if split_payload.get("contract", {}).get("renderer_id") == "travel-scope-split-v1":
                editions = split_payload.get("editions") or {}
                split_edition = editions.get("en" if re.search(r'<html[^>]+lang=["\']en["\']', html, re.I) else "cn")
                if split_edition is None and editions:
                    split_edition = next(iter(editions.values()))
            else:
                split_payload = None
        except (json.JSONDecodeError, TypeError):
            fail(errors, "分栏渲染器 travel-data JSON 无法解析")
            split_payload = None
    is_english = bool(re.search(r'<html[^>]+lang=["\']en["\']', html, re.I))
    is_overseas = bool(split_edition.get("is_overseas")) if split_edition else bool(re.search(r'var IS_OVERSEAS = true;', html))
    live_map_enabled = bool(re.search(r'var LIVE_MAP_ENABLED = true;', html))
    if split_edition is not None:
        if not str(split_edition.get("country") or split_edition.get("country_en") or "").strip():
            fail(errors, "分栏地图链接缺少国家/区域上下文")
        for module in ("hotels", "restaurants", "cafes", "attractions", "dive_sites"):
            for row in split_edition.get(module) or []:
                if not isinstance(row, list) or len(row) < 2 or not str(row[0]).strip() or not str(row[1]).strip():
                    fail(errors, f"{module} 存在无法构造地图身份的记录: {row}")
    validate_map_links(html, errors, split_edition)
    if not live_map_enabled:
        forbidden_runtime_calls = re.findall(
            r'https://(?:maps\.googleapis\.com|webapi\.amap\.com|places\.googleapis\.com)[^"\'<> ]*',
            html,
        )
        if forbidden_runtime_calls:
            fail(errors, "普通网页跳转模式仍包含供应商运行时 API URL，可能在打开 HTML 时产生调用")

    split_renderer = split_edition is not None
    modern_renderer = 'data-renderer="modern-v1"' in html or split_renderer
    bilingual_renderer = 'edition-switcher' in html and 'edition-en' in html
    if split_renderer:
        module_specs = split_payload["contract"].get("modules") or {}
        poi_modules = ("hotels", "restaurants", "cafes", "attractions", "dive_sites")
        cards = sum(len(split_edition.get(module) or []) for module in poi_modules)
        poi_cards = cards
        image_tags = []
        for module in poi_modules:
            rows = split_edition.get(module) or []
            image_index = (module_specs.get(module) or {}).get("image")
            if image_index is None:
                continue
            for row in rows:
                image_tags.extend(str(value) for value in row[image_index:image_index + 2] if value)
    else:
        card_blocks = html.split('<article class="modern-poi"')[1:] if modern_renderer else html.split('<div class="loc-card"')[1:]
        cards = len(card_blocks)
        poi_cards = sum('class="loc-thumb"' in block for block in card_blocks)
        image_tags = [html_lib.unescape(u) for u in re.findall(r'<img class="loc-thumb"\s+src="([^"].*?)"', html)]
    if not cards:
        fail(errors, "HTML 未生成任何卡片")
    require_complete_images = bool(split_edition and (split_edition.get("image_collection") or {}).get("require_complete"))
    if poi_cards and ((require_complete_images and len(image_tags) != poi_cards * 2) or (not split_renderer and len(image_tags) != poi_cards * 2)):
        fail(errors, f"图片数量不完整: poi_cards={poi_cards}, image_tags={len(image_tags)}, expected={poi_cards * 2}")
    if split_renderer and len(image_tags) > poi_cards * 2:
        fail(errors, f"图片引用数异常: poi_cards={poi_cards}, image_tags={len(image_tags)}")
    local_images = [u for u in image_tags if not u.startswith(("http://", "https://"))]
    missing_local = [u for u in local_images if not (html_path.parent / u).is_file()]
    if missing_local:
        fail(errors, f"本地图片资源不存在: {len(missing_local)} 张")
    synthetic = [u for u in image_tags if is_synthetic_image_url(u)]
    if synthetic:
        fail(errors, f"存在虚构图片URL: {len(synthetic)} 张；必须重新采集真实图片")
    if is_overseas and not split_renderer:
        invalid_google = [u for u in image_tags if is_invalid_google_media_url(u)]
        if invalid_google:
            fail(errors, f"海外图片不是已验证的 Google Places media 资源: {len(invalid_google)} 张")
    # Never charge for validation. Remote-only images require local evidence.
    remote_images = [u for u in image_tags if u.startswith(("http://", "https://"))]
    if remote_images and is_overseas:
        fail(errors, 'Remote-only images are not locally verified; no network requests were made')
    if not bilingual_renderer and len(image_tags) != len(set(image_tags)):
        fail(errors, "卡片图片存在跨 POI URL 复用，疑似模板图或映射错位")
    image_ids = [image_identity(u) for u in image_tags]
    if not bilingual_renderer and len(image_ids) != len(set(image_ids)):
        fail(errors, "卡片图片去除查询参数后存在真实资源复用，疑似模板图或跨类别映射错位")
    detail_blocks = re.findall(r'<div class="loc-detail">(.*?)</div>', html, re.S)
    # 国内评分可能因来源访问限制而明确标记为“待核验”，这不等于价格占位。
    # 卡片结构为“类型 | 价格 | 评分”，门禁只阻断价格字段的占位值。
    price_fields = [
        b.split("|")[1].strip()
        for b in detail_blocks
        if len(b.split("|")) >= 2
        and b.split("|")[0].strip() not in {"出发地", "目的地", "From", "To"}
    ]
    if any("待核验" in b or "待补充" in b for b in price_fields):
        fail(errors, "卡片价格字段仍包含占位值")
    if split_renderer:
        split_price_fields = []
        for module in ("hotels", "restaurants", "cafes", "attractions", "dive_sites"):
            split_price_fields.extend(str(row[4]).strip() for row in (split_edition.get(module) or []) if len(row) > 4)
        if any("待核验" in value or "待补充" in value for value in split_price_fields):
            fail(errors, "分栏卡片价格字段仍包含占位值")

    destination_names = ({str(row[0]) for row in (split_edition.get("destinations") or []) if row}
                         if split_renderer else
                         set(re.findall(r'<(?:div|section) class="dest-section"[^>]*data-dest="([^"]+)"', html)))
    if is_overseas and not split_renderer and "var GOOGLE_PLACE_IDS =" not in html:
        fail(errors, "海外 HTML 缺少 Google Place ID 映射")
    if is_english and not split_renderer:
        destination_headers = re.findall(r'<div class="dest-header"[^>]*>(.*?)<span class="dest-count">', html, re.S)
        for header in destination_headers:
            visible = re.sub(r'<[^>]+>', ' ', header)
            if not re.search(r'[A-Za-z]', visible):
                fail(errors, f"英文页面目的地标题缺少英文名称: {visible.strip()}")
    if args.scope_json:
        scope = json.loads(Path(args.scope_json).read_text(encoding="utf-8"))
        expected_destinations = {
            x.get("name") for x in scope.get("selected_destinations", [])
            if x.get("status") in {"正式纳入", "路线备选"}
        }
        missing = sorted(expected_destinations - destination_names)
        if missing:
            fail(errors, f"HTML遗漏已纳入/备选目的地: {missing}")

    route_match = re.search(r'var itineraryData = (\{.*?\});\s*\nvar allRouteNames = (\[.*?\]);', html, re.S)
    if split_renderer:
        itinerary = {}
        for row in split_edition.get("itinerary") or []:
            if len(row) < 5:
                fail(errors, f"分栏行程记录字段不足: {row}")
                continue
            route, day, _sequence, category, name = row[:5]
            itinerary.setdefault(str(route), {}).setdefault(str(day), []).append({
                "name": str(name),
                "category": str(category),
                "coordinates": str(row[5]) if len(row) > 5 else "",
            })
        route_names = list(itinerary)
    if not route_match and modern_renderer:
        if not split_renderer:
            fail(errors, "现代渲染器缺少行程数据契约")
    elif not route_match:
        fail(errors, "未找到 itineraryData 或 allRouteNames")
    if route_match or split_renderer:
        if route_match:
            itinerary = json.loads(route_match.group(1))
            route_names = json.loads(route_match.group(2))
        if is_english and not split_renderer:
            labels_match = re.search(r'var allRouteLabels = (\[.*?\]);', html, re.S)
            if not labels_match:
                fail(errors, "英文页面缺少 allRouteLabels")
            else:
                route_labels = json.loads(labels_match.group(1))
                for route, label in zip(route_names, route_labels):
                    if not re.search(r'[A-Za-z]', str(label)):
                        fail(errors, f"英文页面路线名称缺少英文名称: {route}")
        expected_days = args.expected_days
        if expected_days is None:
            expected_days = max((int(d.replace("Day ", "")) for r in itinerary.values() for d in r), default=0)
        for route in route_names:
            if route not in itinerary:
                fail(errors, f"路线 {route} 没有 itineraryData")
                continue
            actual_days = {int(d.replace("Day ", "")) for d in itinerary[route] if d.startswith("Day ")}
            missing_days = set(range(1, expected_days + 1)) - actual_days
            if missing_days:
                fail(errors, f"路线 {route} 缺少天数: {sorted(missing_days)}")
            for day, points in itinerary[route].items():
                if split_renderer:
                    for point in points:
                        coordinate = [x.strip() for x in point.get("coordinates", "").split(",")]
                        if len(coordinate) != 2 or not _valid_coordinate_pair(coordinate[0], coordinate[1]):
                            fail(errors, f"路线 {route} {day} 点位 {point.get('name', '')} 坐标无效")
                    continue
                daily_destination_only = (
                    len(points) == 1
                    and str(points[0].get("map_scope", "")).strip() == "daily_destination"
                )
                if not daily_destination_only:
                    fail(errors, f"路线 {route} {day} 地图必须只保留一个 daily_destination 大目的地锚点")
                for point in points:
                    if str(point.get("type", point.get("category", ""))).strip() == "交通":
                        continue
                    # The map route intentionally contains one major
                    # destination anchor per day. These anchors are not
                    # POI cards and therefore do not need card images.
                    if str(point.get("map_scope", "")).strip() == "daily_destination":
                        continue
                    img1 = str(point.get("img1") or "")
                    img2 = str(point.get("img2") or "")
                    if not img1.startswith(("http://", "https://")) or not img2.startswith(("http://", "https://")):
                        fail(errors, f"路线 {route} {day} 点位 {point.get('name', '')} 缺少双图")

        # A complete calendar is not enough: reject synthetic routes that
        # repeat the same two POIs for the entire trip or duplicate another route.
        route_signatures = {}
        min_unique = max(4, min(8, (expected_days + 1) // 2))
        for route in route_names:
            if route not in itinerary:
                continue
            day_values = list(itinerary[route].values())
            names = [str(p.get("name", "")).strip() for pts in day_values for p in pts if str(p.get("name", "")).strip()]
            unique_names = set(names)
            if len(unique_names) < min_unique:
                fail(errors, f"路线 {route} 点位过度重复: unique_points={len(unique_names)}, minimum={min_unique}")
            day_signatures = {tuple(sorted(str(p.get("name", "")).strip() for p in pts)) for pts in day_values}
            if len(day_signatures) < max(3, min(6, expected_days // 3)):
                fail(errors, f"路线 {route} 每日结构过度重复: unique_day_signatures={len(day_signatures)}")
            route_signatures[route] = unique_names
            for name in unique_names:
                day_count = sum(1 for pts in day_values if any(str(p.get("name", "")).strip() == name for p in pts))
                if day_count > max(3, expected_days // 2):
                    fail(errors, f"路线 {route} 点位 {name} 占用过多天数: {day_count}/{expected_days}")
        route_list = list(route_signatures)
        for i, left in enumerate(route_list):
            for right in route_list[i + 1:]:
                union = route_signatures[left] | route_signatures[right]
                overlap = len(route_signatures[left] & route_signatures[right]) / len(union) if union else 1.0
                if overlap >= 0.95:
                    fail(errors, f"路线 {left} 与 {right} 实际点位高度重复: overlap={overlap:.2f}")

        if args.route_plan_json:
            plan = json.loads(Path(args.route_plan_json).read_text(encoding="utf-8"))
            for route_idx, route_plan in enumerate(plan.get("routes", [])):
                route = route_plan.get("name")
                itin_entry = itinerary.get(route)
                if not itin_entry and is_english:
                    for k, v in itinerary.items():
                        if k == route or (route and route.replace("方案", "Option") == k):
                            itin_entry = v
                            route = k
                            break
                    if not itin_entry and len(itinerary) == len(plan.get("routes", [])):
                        k = list(itinerary.keys())[route_idx]
                        itin_entry = itinerary[k]
                        route = k
                if not itin_entry:
                    fail(errors, f"路线计划 {route} 未出现在 HTML itineraryData")
                    continue
                route_text = " ".join(str(p.get("name", "")) for pts in itin_entry.values() for p in pts)
                missing_required = [x for x in route_plan.get("required_poi_names", []) if x not in route_text]
                if missing_required:
                    fail(errors, f"路线 {route} 缺少路线计划要求的经典节点: {missing_required}")

    if args.delivery_xlsx or args.research_xlsx:
        try:
            import openpyxl
            if args.delivery_xlsx:
                wb = openpyxl.load_workbook(args.delivery_xlsx, read_only=True)
                sheet_aliases = {"Transport": "交通信息", "Transport Nodes": "交通节点", "Daily Itinerary": "每日行程"}
                missing_core = [name for name, chinese_name in sheet_aliases.items()
                                if name not in wb.sheetnames and chinese_name not in wb.sheetnames]
                if missing_core:
                    fail(errors, f"Excel 缺少核心交通/每日行程工作表: {missing_core}")
                has_diving = ('潜水活动' in wb.sheetnames or 'Diving' in wb.sheetnames)
                has_cafes = ('咖啡馆推荐' in wb.sheetnames or 'Cafés' in wb.sheetnames or 'Cafes' in wb.sheetnames)
                optional_modules = {
                    "Key Experiences", "核心体验", "Local Chains & Convenience", "当地连锁与便捷选择",
                    "Pre-trip Checklist", "行前准备", "Local Travel Essentials", "当地旅行要点",
                }
                has_local_apps = ('常用APP' in wb.sheetnames or 'Local Apps' in wb.sheetnames)
                expected_sheets = 11 + int(has_diving) + int(has_cafes) + int(has_local_apps) + sum(name in wb.sheetnames for name in optional_modules)
                if len(wb.sheetnames) != expected_sheets:
                    fail(errors, f"交付版工作表数量错误: {len(wb.sheetnames)}，预期: {expected_sheets}")
                if is_overseas:
                    for sheet_name in ("Accommodation", "Food & Restaurants", "Attractions & Activities", "Cafés"):
                        if sheet_name in wb.sheetnames:
                            headers = {str(cell.value).strip() for cell in next(wb[sheet_name].iter_rows(max_row=1)) if cell.value is not None}
                            for required in ("Google Image 1", "Google Image 2", "Google Place ID"):
                                if required not in headers:
                                    fail(errors, f"海外 Excel 工作表 {sheet_name} 缺少字段: {required}")
            if args.research_xlsx:
                wb = openpyxl.load_workbook(args.research_xlsx, read_only=True)
                has_diving = ('潜水活动' in wb.sheetnames or 'Diving' in wb.sheetnames)
                has_cafes = ('咖啡馆推荐' in wb.sheetnames or 'Cafés' in wb.sheetnames or 'Cafes' in wb.sheetnames)
                optional_modules = {
                    "Key Experiences", "核心体验", "Local Chains & Convenience", "当地连锁与便捷选择",
                    "Pre-trip Checklist", "行前准备", "Local Travel Essentials", "当地旅行要点",
                }
                has_local_apps = ('常用APP' in wb.sheetnames or 'Local Apps' in wb.sheetnames)
                expected_sheets = 14 + int(has_diving) + int(has_cafes) + int(has_local_apps) + sum(name in wb.sheetnames for name in optional_modules)
                if len(wb.sheetnames) != expected_sheets:
                    fail(errors, f"研究版工作表数量错误: {len(wb.sheetnames)}，预期: {expected_sheets}")
        except ImportError:
            fail(errors, "缺少 openpyxl，无法验证 Excel")

    if errors:
        print("FAIL")
        for e in errors:
            print(f"- {e}")
        return 1
    print(json.dumps({"status": "PASS", "destinations": len(destination_names), "cards": cards, "images": len(image_tags), "routes": len(route_names) if (route_match or split_renderer) else 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
