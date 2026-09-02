#!/usr/bin/env python3
"""Collect POI-level Google Places photos into a payload without hardcoding a key."""
import argparse
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests


def places_search(headers, body):
    last_error = None
    for _ in range(3):
        try:
            response = requests.post("https://places.googleapis.com/v1/places:searchText", headers=headers, json=body, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
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


def collect_one(poi, key):
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
    last_response = None
    for query in queries:
        body = {"textQuery": query, "languageCode": "en", "maxResultCount": 5}
        if location:
            body["locationBias"] = {"circle": {"center": {"latitude": location[0], "longitude": location[1]}, "radius": 50000}}
        response = places_search(headers, body)
        last_response = response
        response.raise_for_status()
        for place in response.json().get("places", []):
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
    provider_location = (best or {}).get("location", {})
    provider_coords = ""
    if provider_location.get("latitude") is not None and provider_location.get("longitude") is not None:
        provider_coords = f"{provider_location['latitude']},{provider_location['longitude']}"
    return name, {"place_id": (best or {}).get("id", ""), "images": urls, "coords": provider_coords}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    key = os.environ.get("TRAVEL_SCOPE_GOOGLE_PLACES_KEY", "").strip()
    if not key:
        raise SystemExit("缺少 TRAVEL_SCOPE_GOOGLE_PLACES_KEY；不会使用硬编码 Key")
    with open(args.input, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    pois = []
    seen = set()
    for data_key, coord_index in (("hotels", 7), ("restaurants", 7), ("attractions", 6), ("dive_sites", 6)):
        for row in payload.get(data_key, []) or []:
            if not isinstance(row, list) or len(row) <= coord_index or len(row) < 3:
                continue
            name = str(row[1]).strip()
            if name and name not in seen:
                seen.add(name)
                pois.append({"name": name, "name_en": str(row[2] or "").strip(), "coords": row[coord_index], "context": str(row[0] or "").strip()})
    images, place_ids, provider_coords, failures = {}, {}, {}, []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(collect_one, poi, key): poi for poi in pois}
        for future in as_completed(futures):
            poi = futures[future]
            try:
                name, result = future.result()
                if len(result["images"]) < 2:
                    failures.append({"name": name, "reason": "Google Places returned fewer than two photos"})
                    continue
                images[name] = result["images"]
                place_ids[name] = result["place_id"]
                if result.get("coords"):
                    provider_coords[name] = result["coords"]
            except Exception as exc:
                failures.append({"name": poi["name"], "reason": type(exc).__name__})
    payload["google_images"] = images
    payload["google_place_ids"] = place_ids
    updated_coords = 0
    for data_key, coord_index in (("hotels", 7), ("restaurants", 7), ("attractions", 6), ("dive_sites", 6)):
        for row in payload.get(data_key, []) or []:
            if isinstance(row, list) and len(row) > coord_index and row[1] in provider_coords:
                if str(row[coord_index]).strip() != provider_coords[row[1]]:
                    row[coord_index] = provider_coords[row[1]]
                    updated_coords += 1
    payload["google_place_locations"] = provider_coords
    payload["image_collection"] = {"provider": "Google Places API (New)", "poi_count": len(pois), "matched": len(images), "failed": failures, "coordinates_updated": updated_coords}
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"poi_count": len(pois), "matched": len(images), "failed": len(failures), "output": args.output}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
