# -*- coding: utf-8 -*-
"""Rebuild the run's image supply from its declared sources (§5.4.1 + owner decision).

Why this exists: 20 section covers were baked into a fixed 1000x650 box (an 8.6:1 panorama became a
1.54:1 smear) and 14 editorial heroes carry manifest digests that never described their bytes. The
transform that produced them is not in the release, so nothing downstream could attest it.

Flow per asset:
  File title -> Commons imageinfo(iiurlwidth=slot target) -> download that exact rendition
             -> prepare_media (aspect-preserving, never upscaled) -> renditions + double hash chain

Bytes are written under a scratch run root; the delivered run is only replaced after the gates
agree, and the old files stay untouched for comparison.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_media

API = "https://commons.wikimedia.org/w/api.php"
UA = "Travel-Scope/5.0.0 (media rebuild from declared sources)"
# Slot -> the widest rendition the layout can actually use. Heroes go full-bleed; section covers
# live in <=500px CSS boxes, so a 1200px copy of them would be bytes nobody spends.
SLOT_WIDTH = {"hero": 1200, "destination_atmosphere": 800}


def get_json(params):
    url = API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}),
                                timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}),
                                timeout=180) as resp:
        return resp.read()


def imageinfo(titles, width):
    payload = get_json({"action": "query", "format": "json", "redirects": "1",
                        "prop": "imageinfo", "titles": "|".join(titles),
                        "iiprop": "url|size|mime|sha1|extmetadata", "iiurlwidth": str(width)})
    return {p["title"]: (p.get("imageinfo") or [{}])[0]
            for p in payload.get("query", {}).get("pages", {}).values() if p.get("title")}


def slot_of(item: dict) -> str:
    return prepare_media.slot_for(item)


def main(run_root: Path, out_root: Path, *, limit: int = 0,
           force_refetch: bool = False, install: bool = False) -> int:
    run_root = Path(run_root).resolve()
    out_root = Path(out_root).resolve()
    if install and limit:
        raise ValueError("MEDIA_INSTALL_PARTIAL|--install 会重写整份 asset-manifest，"
                         "不能与 --limit 混用（半装清单等于谎报交付字节）")
    manifest = json.loads((run_root / "asset-manifest.json").read_text(encoding="utf-8"))
    items = manifest if isinstance(manifest, list) else manifest.get("assets", [])
    if limit:
        items = items[:limit]

    plan = {}
    for item in items:
        slot = slot_of(item)
        plan.setdefault(slot, []).append(item)

    resolved = {}
    for slot, group in plan.items():
        width = SLOT_WIDTH[slot]
        titles = [str(i.get("source_file_title") or "").strip() for i in group]
        for start in range(0, len(titles), 6):
            batch = [t for t in titles[start:start + 6] if t]
            if not batch:
                continue
            resolved[(slot, width)] = resolved.get((slot, width), {})
            resolved[(slot, width)].update(imageinfo(batch, width))
            time.sleep(0.35)

    (out_root / "sources").mkdir(parents=True, exist_ok=True)
    rebuilt, errors = [], []
    for item in items:
        slot = slot_of(item)
        width = SLOT_WIDTH[slot]
        title = str(item.get("source_file_title") or "").strip()
        info = resolved.get((slot, width), {}).get(title) or {}
        local_rel = str(item.get("local_file") or "")
        if not title or not info:
            errors.append("MEDIA_SOURCE_UNRESOLVED|%s 无法按 %r 解析上游文件" % (local_rel, title))
            continue
        original_width = int(info.get("width") or 0)
        url = info.get("url") if original_width and width >= original_width else \
            (info.get("thumburl") or info.get("url"))
        if not url:
            errors.append("MEDIA_SOURCE_URL_MISSING|" + local_rel)
            continue
        try:
            cached = out_root / "sources" / Path(local_rel).name
            if cached.is_file() and cached.stat().st_size > 0 and not force_refetch:
                blob = cached.read_bytes()
            else:
                blob = fetch(url)
        except Exception as exc:                                    # noqa: BLE001
            errors.append("MEDIA_FETCH_FAILED|%s %s: %s" % (local_rel, type(exc).__name__,
                                                            str(exc)[:120]))
            continue
        source_path = out_root / "sources" / Path(local_rel).name
        source_path.write_bytes(blob)
        rebuilt.append({"item": item, "slot": slot, "target_width": width,
                        "source_path": source_path, "source_url": url,
                        "upstream_original_sha1": info.get("sha1", ""),
                        "upstream_original_width": original_width,
                        "upstream_original_url": info.get("url", "")})
        print("%-26s %-34s %6.0fKB  sha1=%s  src_w=%d" % (
            slot, Path(local_rel).name, len(blob) / 1024,
            (info.get("sha1") or "")[:10], original_width))
        time.sleep(0.4)

    # Aspect-preserving renditions + the double hash chain, per declared slot.
    summary = {"assets": len(rebuilt), "errors": errors, "entries": []}
    for record in rebuilt:
        entry = prepare_media.prepare_asset(
            record["source_path"], out_root / "renditions", slot=record["slot"])
        entry.update({"slot": record["slot"], "local_file": record["item"].get("local_file"),
                      "source_rendition_url": record["source_url"],
                      "upstream_original_sha1": record["upstream_original_sha1"],
                      "upstream_original_url": record["upstream_original_url"],
                      "declared_sha256": str(record["item"].get("sha256") or ""),
                      "license": record["item"].get("license"),
                      "author": record["item"].get("author"),
                      "poi_name": record["item"].get("poi_name"),
                      "destination": record["item"].get("destination"),
                      "display_role": record["item"].get("display_role")})
        entry["declared_matches_source"] = entry["declared_sha256"] == entry["source_sha256"]
        summary["entries"].append(entry)
    (out_root / "rebuild-report.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "entries"} |
                   {"entries": summary["entries"]}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    images = sum(r["bytes"] for e in summary["entries"] for r in e["renditions"])
    install_report = None
    if install:
        install_report = prepare_media.install_run_media(run_root, summary, out_dir=out_root)
        summary["install"] = install_report
        (out_root / "rebuild-report.json").write_text(
            json.dumps({k: v for k, v in summary.items() if k != "entries"} |
                       {"entries": summary["entries"]}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    print("\nrebuilt=%d errors=%d image_bytes=%.2fMB" % (
        len(rebuilt), len(errors), images / 1048576))
    if install_report:
        print("installed=%d/%d backup=%s status=%s" % (
            install_report["installed"], install_report["manifest_entries"],
            install_report["backup_dir"], install_report["status"]))
        for error in install_report["errors"][:10]:
            print("ERROR", error[:170])
    for error in errors[:10]:
        print("ERROR", error[:170])
    if install_report:
        return 0 if not errors and install_report["status"] == "PASS" else 2
    return 0 if not errors else 2


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="按声明来源重建图片供给（保比例 + 双跳摘要）")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--refetch", action="store_true",
                        help="忽略已下载的 sources/ 缓存，重新向上游取字节")
    parser.add_argument("--install", action="store_true",
                        help="把双跳链与档位文件写回 run 的 asset-manifest.json（原图先备份）")
    args = parser.parse_args()
    raise SystemExit(main(Path(args.run_root), Path(args.out_root), limit=args.limit,
                      force_refetch=args.refetch, install=args.install))
