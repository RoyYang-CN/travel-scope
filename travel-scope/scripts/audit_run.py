#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only audit for a country run directory before delivery."""

import argparse
import base64
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cafe_contract import validate_cafes
from formal_data_gate import audit as audit_formal_data

KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
FALLBACK_COORD_PATTERN = re.compile(
    r"(?:get\([^\n]{0,120},\s*[\'\"][+-]?\d+(?:\.\d+)?,[+-]?\d+(?:\.\d+)?[\'\"]\)|fallback|\u9ed8\u8ba4\u5750\u6807|\u56de\u9000\u5750\u6807)",
    re.I,
)
FAKE_PHOTO_PATTERN = re.compile(r"photo_\d+")
BASE64_TOKEN_PATTERN = re.compile(r"atob\(\s*['\"]([A-Za-z0-9+/=_-]{24,})['\"]\s*\)", re.I)


def contains_obfuscated_key(text):
    for token in BASE64_TOKEN_PATTERN.findall(text):
        try:
            padded = token + "=" * ((4 - len(token) % 4) % 4)
            decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
        except Exception:
            continue
        if KEY_PATTERN.search(decoded):
            return True
    return False


def check_image(url):
    for attempt in range(3):
        try:
            headers = {"User-Agent": "Travel-Scope-audit/3.4.31", "Range": "bytes=0-1"}
            key = os.environ.get("TRAVEL_SCOPE_GOOGLE_PLACES_KEY") or os.environ.get("GOOGLE_MAPS_KEY") or ""
            if key and "places.googleapis.com" in url and "key=" not in url:
                headers["X-Goog-Api-Key"] = key
            request = Request(url, headers=headers)
            with urlopen(request, timeout=20) as response:
                status = int(getattr(response, "status", response.getcode()))
                content_type = (response.headers.get("content-type") or "").lower()
                return 200 <= status < 300 and content_type.startswith("image/")
        except Exception:
            if attempt < 2:
                continue
            return False
    return False


def fail(errors, message):
    errors.append(message)


def audit_payload(path, errors):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(errors, f"payload 无法读取: {exc}")
        return
    collection = payload.get("image_collection") or {}
    try:
        validate_cafes(payload)
    except ValueError as exc:
        fail(errors, str(exc))

    has_google_data = any((payload.get("google_images") or {}).values()) or any((payload.get("google_place_ids") or {}).values())
    is_open_media = collection.get("provider") in {"open_license_verified", "wikimedia_commons", "local_verified", "designed_no_photo_state"}

    if has_google_data and not is_open_media and collection.get("provider") != "Google Places API (New)":
        fail(errors, "Google payload 缺少统一 image_collection provider 元数据")

    if collection.get("provider") == "Google Places API (New)":
        if collection.get("failed"):
            fail(errors, f"Google 图片采集仍有 {len(collection['failed'])} 个失败点位")
        images = payload.get("google_images") or {}
        place_ids = payload.get("google_place_ids") or {}
        all_urls = []
        for name, urls in images.items():
            if not isinstance(urls, list) or len(urls) < 2:
                fail(errors, f"{name} 缺少两张图片")
                continue
            place_id = str(place_ids.get(name) or "")
            for url in urls[:2]:
                parsed = urlsplit(str(url))
                all_urls.append(str(url))
                if parsed.netloc != "places.googleapis.com" or not re.search(r"^/v1/places/[^/]+/photos/[^/]+/media$", parsed.path):
                    fail(errors, f"{name} 图片不是 Google Places media URL")
                    continue
                path_place_id = parsed.path.split("/", 4)[3]
                if place_id and path_place_id != place_id:
                    fail(errors, f"{name} 图片所属 Place ID 与 POI 不一致")
                if FAKE_PHOTO_PATTERN.search(parsed.path):
                    fail(errors, f"{name} 使用疑似伪造 photo 资源标识")
        if len(all_urls) != len(set(all_urls)):
            fail(errors, "Google 图片 URL 存在复用")
        with ThreadPoolExecutor(max_workers=8) as pool:
            reachable = list(pool.map(check_image, sorted(set(all_urls))))
        failed_remote = sum(not ok for ok in reachable)
        if failed_remote:
            fail(errors, f"Google 图片远程不可访问或非 image/*: {failed_remote}/{len(reachable)}")


def main():
    parser = argparse.ArgumentParser(description="Audit a Travel-Scope run directory without modifying it")
    parser.add_argument("run_dir")
    args = parser.parse_args()
    root = Path(args.run_dir).resolve()
    if not root.is_dir():
        print(f"ERROR: run directory not found: {root}")
        return 2
    errors = []
    for path in root.rglob("*"):
        if any(part in {"node_modules", ".git", "__pycache__"} for part in path.parts):
            continue
        if not path.is_file() or path.suffix.lower() not in {".py", ".json", ".html", ".md", ".txt", ".yml", ".yaml"}:
            continue
        if "outputs" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if KEY_PATTERN.search(text):
            fail(errors, f"{path.relative_to(root)} 包含 API Key 字面量")
        if path.suffix.lower() == ".py" and FALLBACK_COORD_PATTERN.search(text):
            fail(errors, f"{path.relative_to(root)} 疑似包含坐标静默回退逻辑")
        if contains_obfuscated_key(text):
            fail(errors, f"{path.relative_to(root)} 包含 Base64/atob 混淆 API Key")
        if "\ufffd" in text:
            fail(errors, f"{path.relative_to(root)} 包含 Unicode 替换字符，疑似编码损坏")
    payloads = [path for path in (root / "dataset.json", root / "data_payload.json") if path.exists()]
    if not payloads:
        fail(errors, "缺少 dataset.json/data_payload.json，未执行统一数据审计")
    for payload in payloads:
        before = len(errors)
        audit_payload(payload, errors)
        if len(errors) > before:
            errors[before:] = [f"{payload.name}: {message}" for message in errors[before:]]
    formal_paths = {name: root / filename for name, filename in {
        "data": "dataset.json", "manifest": "manifest.json", "scope": "scope.json",
        "corridors": "corridors.json", "assets": "asset-manifest.json",
    }.items()}
    if all(path.is_file() for path in formal_paths.values()):
        result = audit_formal_data(
            json.loads(formal_paths["data"].read_text(encoding="utf-8")),
            json.loads(formal_paths["manifest"].read_text(encoding="utf-8")),
            json.loads(formal_paths["scope"].read_text(encoding="utf-8")),
            json.loads(formal_paths["corridors"].read_text(encoding="utf-8")),
            json.loads(formal_paths["assets"].read_text(encoding="utf-8")),
        )
        errors.extend(f"formal_data_gate: {message}" for message in result["errors"])
    if errors:
        print("FAIL")
        for error in errors[:80]:
            print(f"- {error}")
        return 1
    print(json.dumps({"status": "PASS", "run_dir": str(root)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
