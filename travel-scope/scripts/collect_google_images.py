#!/usr/bin/env python3
"""Collect POI-level Google Places photos into a payload without hardcoding a key."""
import argparse
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, urlsplit

import requests

try:
    from api_cache import ApiCache, default_cache_path
    from image_assets import asset_name, inspect_image, materialize
except ImportError:  # pragma: no cover - supports direct module loading
    from scripts.api_cache import ApiCache, default_cache_path
    from scripts.image_assets import asset_name, inspect_image, materialize


def places_search(headers, body, cache, request_key, daily_limit, monthly_limit):
    cached = cache.get("google_places", "searchText", request_key)
    if cached is not None:
        return cached
    call_id = cache.start_call("google_places", "searchText", request_key, daily_limit, monthly_limit)
    if not call_id:
        raise RuntimeError(f"Google Places daily quota safety limit reached: {daily_limit}")
    last_error = None
    for _ in range(1):
        try:
            response = requests.post("https://places.googleapis.com/v1/places:searchText", headers=headers, json=body, timeout=30)
            response.raise_for_status()
            data = response.json()
            cache.put("google_places", "searchText", request_key, data)
            cache.finish_call(call_id, "success")
            return data
        except requests.RequestException as exc:
            last_error = exc
            cache.finish_call(call_id, "error", str(exc))
    raise last_error


def distance_km(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def coords(value):
    try:
        lat, lon = (float(x.strip()) for x in str(value).split(",", 1))
        return lat, lon
    except (ValueError, TypeError):
        return None


def collect_one(poi, key, cache, daily_limit, monthly_limit, assets_dir):
    name, name_en, location = poi["name"], poi.get("name_en", ""), coords(poi.get("coords", ""))
    context = str(poi.get("context", "")).strip()
    queries = []
    for query in (f"{name_en} {context}" if name_en and context else "", f"{name} {context}" if context else "", name_en, name):
        query = " ".join(str(query).split())
        if query and query not in queries:
            queries.append(query)
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": key,
               "X-Goog-FieldMask": "places.id,places.displayName,places.photos,places.location"}
    best = None
    for query in queries:
        body = {"textQuery": query, "languageCode": "en", "maxResultCount": 5}
        if location:
            body["locationBias"] = {"circle": {"center": {"latitude": location[0], "longitude": location[1]}, "radius": 50000}}
        request_key = json.dumps(body, ensure_ascii=False, sort_keys=True)
        data = places_search(headers, body, cache, request_key, daily_limit, monthly_limit)
        for place in data.get("places", []):
            ploc = place.get("location", {})
            pcoords = (ploc.get("latitude"), ploc.get("longitude"))
            if location and None not in pcoords and distance_km(location, pcoords) > 50:
                continue
            if len(place.get("photos", [])) >= 2:
                best = place
                break
        if best:
            break
    photos = (best or {}).get("photos", [])
    urls = [f"https://places.googleapis.com/v1/{photo['name']}/media?maxWidthPx=800&key={quote(key)}" for photo in photos[:2] if photo.get("name")]
    local_urls = []
    for remote_url in urls:
        filename = asset_name(remote_url)
        target = os.path.join(assets_dir, filename)
        if not (os.path.isfile(target) and os.path.getsize(target) > 0):
            photo_key = urlsplit(remote_url).path
            call_id = cache.start_call("google_places", "photoMedia", photo_key, daily_limit, monthly_limit)
            if not call_id:
                raise RuntimeError(f"Google Places photo daily quota safety limit reached: {daily_limit}")
            try:
                relative = materialize(remote_url, assets_dir)
                cache.finish_call(call_id, "success")
            except Exception as exc:
                cache.finish_call(call_id, "error", str(exc))
                raise
        else:
            relative = f"assets/{filename}"
        mime_type, content_hash, byte_size = inspect_image(target)
        cache.register_asset(relative, asset_name(remote_url), "google_places", name,
                             str(poi.get("category", "")), urlsplit(remote_url).path,
                             "verified", mime_type, byte_size, content_hash)
        local_urls.append(relative)
    provider_location = (best or {}).get("location", {})
    provider_coords = ""
    if provider_location.get("latitude") is not None and provider_location.get("longitude") is not None:
        provider_coords = f"{provider_location['latitude']},{provider_location['longitude']}"
    return f"{context}|{name}", {"name": name, "context": context, "place_id": (best or {}).get("id", ""), "images": local_urls, "coords": provider_coords}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--cache-db", default="", help="SQLite cache/usage ledger path")
    parser.add_argument("--daily-limit", type=int, default=int(os.environ.get("TRAVEL_SCOPE_GOOGLE_PLACES_DAILY_LIMIT", "33")))
    parser.add_argument("--monthly-limit", type=int, default=int(os.environ.get("TRAVEL_SCOPE_GOOGLE_PLACES_MONTHLY_LIMIT", "1000")))
    parser.add_argument("--warn-ratio", type=float, default=0.8, help="Warn when the estimated or current paid-call usage reaches this fraction of a limit")
    parser.add_argument("--assets-dir", default="", help="Local image asset directory")
    args = parser.parse_args()
    key = os.environ.get("TRAVEL_SCOPE_GOOGLE_PLACES_KEY", "").strip()
    if not key:
        raise SystemExit("缺少 TRAVEL_SCOPE_GOOGLE_PLACES_KEY；不会使用硬编码 Key")
    with open(args.input, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    cache = ApiCache(args.cache_db or default_cache_path(args.output))
    assets_dir = os.path.abspath(args.assets_dir or os.path.join(os.path.dirname(args.output), "assets"))
    pois = []
    seen = set()
    for data_key, coord_index in (("hotels", 7), ("restaurants", 7), ("cafes", 7), ("attractions", 6), ("dive_sites", 6)):
        for row in payload.get(data_key, []) or []:
            if not isinstance(row, list) or len(row) <= coord_index or len(row) < 3:
                continue
            name = str(row[1]).strip()
            identity = f"{str(row[0] or '').strip()}|{name}"
            if name and identity not in seen:
                seen.add(identity)
                pois.append({"name": name, "name_en": str(row[2] or "").strip(), "coords": row[coord_index], "context": str(row[0] or "").strip(), "category": data_key})
    # One search is the normal path; fallback queries are intentionally not
    # budgeted as free retries. If the first search misses, the per-call gate
    # still stops before the configured limit is crossed.
    estimated_searches = len(pois)
    estimated_photos = len(pois) * 2
    estimates = {"searchText": estimated_searches, "photoMedia": estimated_photos}
    run_id = os.path.abspath(args.output)
    for operation, estimate in estimates.items():
        cache.record_estimate(run_id, "google_places", operation, estimate)
    for operation, estimate in estimates.items():
        for label, limit in (("daily", args.daily_limit), ("monthly", args.monthly_limit)):
            if limit > 0 and estimate >= limit:
                raise SystemExit(f"预估 {operation} 付费调用量 {estimate} 已达到{label}安全上限 {limit}，请先复用缓存、缩小范围或提高已审核配额")
            if limit > 0 and estimate >= limit * args.warn_ratio:
                print(json.dumps({"warning": "estimated paid-call usage is close to safety limit", "operation": operation, "estimated_calls": estimate, "limit_type": label, "limit": limit}, ensure_ascii=False), file=sys.stderr)
    images, place_ids, provider_coords, failures = {}, {}, {}, []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(collect_one, poi, key, cache, args.daily_limit, args.monthly_limit, assets_dir): poi for poi in pois}
        for future in as_completed(futures):
            poi = futures[future]
            try:
                identity, result = future.result()
                if len(result["images"]) < 2:
                    failures.append({"name": identity, "reason": "Google Places returned fewer than two photos"})
                    continue
                images[identity] = result["images"]
                place_ids[identity] = result["place_id"]
                if result.get("coords"):
                    provider_coords[identity] = result["coords"]
            except Exception as exc:
                failures.append({"name": poi["name"], "reason": type(exc).__name__})
    payload["google_images"] = images
    payload["google_place_ids"] = place_ids
    updated_coords = 0
    for data_key, coord_index in (("hotels", 7), ("restaurants", 7), ("cafes", 7), ("attractions", 6), ("dive_sites", 6)):
        for row in payload.get(data_key, []) or []:
            identity = f"{str(row[0] or '').strip()}|{str(row[1] or '').strip()}" if isinstance(row, list) and len(row) > 1 else ""
            if isinstance(row, list) and len(row) > coord_index and identity in provider_coords:
                if str(row[coord_index]).strip() != provider_coords[identity]:
                    row[coord_index] = provider_coords[identity]
                    updated_coords += 1
    payload["google_place_locations"] = provider_coords
    payload["image_collection"] = {"provider": "Google Places API (New)", "poi_count": len(pois), "matched": len(images), "failed": failures, "coordinates_updated": updated_coords}
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    cache.close()
    print(json.dumps({"poi_count": len(pois), "matched": len(images), "failed": len(failures), "output": args.output}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
