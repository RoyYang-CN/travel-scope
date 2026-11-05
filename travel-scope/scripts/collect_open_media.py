#!/usr/bin/env python3
"""Collect explicitly selected open-license media into a run-local bundle.

The input names exact Wikimedia Commons files. Search and editorial selection
remain separate human-reviewed steps; this collector never accepts a search hit
as a verified destination or category match by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "references/media-policy.json").read_text(encoding="utf-8"))
USER_AGENT = "Travel-Scope/4.0.3 (run-local open media collector)"


def clean_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()


def meta_value(info: dict, key: str) -> str:
    return clean_html((info.get("extmetadata", {}).get(key) or {}).get("value", ""))


def request_json(url: str) -> dict:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=45)
    response.raise_for_status()
    return response.json()


def download(url: str, target: Path, refresh: bool, retries: int = 4) -> None:
    if target.is_file() and not refresh:
        return
    for attempt in range(retries):
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=90)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
            if not content_type.startswith("image/"):
                raise ValueError(f"Not an image response for {target.name}: {content_type}")
            data = response.content
            break
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 429 or attempt + 1 >= retries:
                raise
            retry_after = exc.response.headers.get("Retry-After")
            time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def font(size: int, bold: bool = False):
    path = Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc")
    return ImageFont.truetype(str(path), size=size) if path.is_file() else ImageFont.load_default()


def contact_sheet(items: list[dict], run_root: Path, target: Path) -> None:
    width, cell_w, cell_h = 1600, 400, 300
    rows = (len(items) + 3) // 4
    sheet = Image.new("RGB", (width, rows * cell_h), "#ece9e1")
    draw = ImageDraw.Draw(sheet)
    for index, item in enumerate(items):
        x, y = (index % 4) * cell_w, (index // 4) * cell_h
        path = run_root / item["image"]
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((cell_w - 18, 218), Image.Resampling.LANCZOS)
            px, py = x + (cell_w - image.width) // 2, y + 8 + (210 - image.height) // 2
            sheet.paste(image, (px, py))
        draw.text((x + 12, y + 226), f"{index + 1:02d}  {item['destination']}", font=font(18, True), fill="#102f3a")
        draw.text((x + 12, y + 252), f"{item['module_category']} · {item['selection_level']}", font=font(13), fill="#42616a")
        draw.text((x + 12, y + 273), item["license"], font=font(12), fill="#6a716f")
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, format="JPEG", quality=90, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect exact Wikimedia Commons files declared in a run-local JSON config")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    run_root = Path(args.run_root).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assets = config.get("assets", [])
    contact_review = config.get("contact_sheet_review", {})
    if not assets:
        raise ValueError("Media config requires a non-empty assets list")
    if any(item.get("provider") != "wikimedia_commons" for item in assets):
        raise ValueError("This collector currently accepts only explicitly selected Wikimedia Commons files")

    titles = [str(item.get("file_title") or "") for item in assets]
    if any(not title.startswith("File:") for title in titles) or len(set(titles)) != len(titles):
        raise ValueError("Every asset needs a unique exact Wikimedia Commons File: title")
    # Wikimedia's shared repository metadata is also exposed by Wikimedia
    # client wikis. A run may select one to avoid a throttled Commons API edge;
    # rights and source links still come from Commons metadata/page URLs.
    endpoint = str(config.get("metadata_api") or POLICY["providers"]["wikimedia_commons"]["api"])
    # Keep request URLs bounded. Large deep-guide media sets can exceed proxy or
    # server URL limits when every exact File: title is sent in one GET.
    pages = {}
    batch_size = max(1, min(10, int(config.get("metadata_batch_size", 10))))
    for start in range(0, len(titles), batch_size):
        params = {
            "action": "query", "format": "json", "redirects": "1", "prop": "imageinfo",
            "titles": "|".join(titles[start:start + batch_size]), "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": str(config.get("download_width", 1280)),
        }
        payload = request_json(endpoint + "?" + urllib.parse.urlencode(params))
        pages.update({page.get("title"): page for page in payload.get("query", {}).get("pages", {}).values()})

    output_items, manifest_items = [], []
    prefixes = tuple(POLICY["providers"]["wikimedia_commons"]["allowed_license_prefixes"])
    for requested in assets:
        page = pages.get(requested["file_title"])
        if not page or not page.get("imageinfo"):
            raise ValueError(f"Commons file not found: {requested['file_title']}")
        info = page["imageinfo"][0]
        license_name = meta_value(info, "LicenseShortName")
        if not license_name.startswith(prefixes):
            raise ValueError(f"License is outside configured open-license set: {requested['file_title']} -> {license_name}")
        relative = Path("assets/section") / requested["filename"]
        target = (run_root / relative).resolve()
        if not target.is_relative_to(run_root / "assets"):
            raise ValueError(f"Unsafe asset target: {relative}")
        download(info.get("thumburl") or info["url"], target, args.refresh)
        time.sleep(max(0, int(config.get("request_interval_ms", 900))) / 1000)
        with Image.open(target) as image:
            image.verify()
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        source_page = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(requested["file_title"].replace(" ", "_"), safe=":(),;_-')")
        item = {
            "slot_id": requested["slot_id"], "destination": requested["destination"],
            "modules": requested["modules"], "module_category": requested["module_category"],
            "primary_module": requested.get("primary_module", requested["modules"][0]),
            "selection_level": requested["selection_level"], "asset_role": requested["asset_role"],
            "title": requested["title"], "title_en": requested["title_en"],
            "caption": requested["caption"], "caption_en": requested["caption_en"],
            "image": relative.as_posix(), "focal_point": requested.get("focal_point", "50% 50%"),
            "source_provider": "wikimedia_commons", "source_page": source_page,
            "author": meta_value(info, "Artist") or meta_value(info, "Credit") or "Unknown",
            "license": license_name, "license_url": meta_value(info, "LicenseUrl"),
            "retrieved_at": config["retrieved_at"],
            # Collection proves source identity and rights, not semantic visual fit.
            # A separate reviewer must promote this to verified after inspecting
            # the generated contact sheet.
            "verification_status": "pending_visual_review",
            "verification_evidence": contact_review.get("evidence", requested.get("verification_evidence", "")),
            "source_file_title": requested["file_title"],
            "source_page_id": page.get("pageid"), "source_asset_url": info.get("url"),
            "source_verification_status": "verified", "source_verification_method": "wikimedia_api_exact_file",
            "sha256": digest, "width": info.get("width"), "height": info.get("height"), "mime": info.get("mime"),
        }
        output_items.append(item)
        manifest_items.append({
            "local_file": item["image"], "poi_name": item["slot_id"], "category": "SECTION_MEDIA",
            "destination": item["destination"], "modules": item["modules"], "module_category": item["module_category"],
            "primary_module": item["primary_module"],
            "selection_level": item["selection_level"], "asset_role": item["asset_role"],
            "source_provider": "wikimedia_commons", "source_page": source_page, "license": license_name, "license_url": item["license_url"],
            "author": item["author"], "verification_status": item["verification_status"],
            "verification_evidence": item["verification_evidence"], "retrieved_at": item["retrieved_at"],
            "source_file_title": item["source_file_title"], "source_page_id": item["source_page_id"],
            "source_asset_url": item["source_asset_url"], "source_verification_status": item["source_verification_status"],
            "source_verification_method": item["source_verification_method"], "sha256": digest,
            "width": item["width"], "height": item["height"], "mime": item["mime"],
        })

    (run_root / "section-media.json").write_text(json.dumps({"schema_version": 1, "items": output_items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_root / "section-media-manifest.json").write_text(json.dumps({"schema_version": 1, "assets": manifest_items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    contact_sheet(output_items, run_root, run_root / "evidence/section-media-contact-sheet.jpg")
    print(json.dumps({"status": "COLLECTED", "items": len(output_items), "contact_sheet": "evidence/section-media-contact-sheet.jpg"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
