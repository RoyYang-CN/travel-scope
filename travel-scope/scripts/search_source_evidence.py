#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Search-engine snippet evidence collector for domestic Travel-Scope runs.

This intentionally uses indexed search snippets rather than pretending that
Xiaohongshu, Dianping, or Ctrip has a public API. It records the query, result
URL, snippet, extracted rating/count, and confidence so the result remains
auditable and clearly non-live.
"""

import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}


SEARCH_ENDPOINTS = {
    "google": "https://www.google.com/search?q=",
    "baidu": "https://www.baidu.com/s?wd=",
    "bing": "https://www.bing.com/search?q=",
}


def _search(query, engine, cache, cache_lock):
    cache_key = f"{engine}\n{query}"
    with cache_lock:
        if cache_key in cache:
            return cache[cache_key]
    url = SEARCH_ENDPOINTS[engine] + quote(query)
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    selectors = {
        "google": "div.MjjYud",
        "baidu": "div.result",
        "bing": "li.b_algo",
    }
    for item in soup.select(selectors[engine])[:10]:
        link = item.select_one("h2 a")
        if engine == "baidu":
            link = item.select_one("h3 a") or item.select_one("a")
        if engine == "google" and not link:
            link = item.select_one("a")
        if not link:
            continue
        snippet = item.get_text(" ", strip=True)
        results.append({"engine": engine, "url": link.get("href", ""), "snippet": snippet})
    with cache_lock:
        cache[cache_key] = results
    return results


def _extract(text):
    ratings = re.findall(r"(?<!\d)([0-5](?:\.\d)?)\s*(?:分|/5|星)", text)
    counts = re.findall(r"([0-9][0-9,]*)\s*(?:条评价|条点评|条评论|个评价|条)", text)
    return (ratings[0] if ratings else ""), (counts[0].replace(",", "") if counts else "")


def collect(row, engines, cache, cache_lock, max_relevant):
    kind, destination, name = row["kind"], row["destination"], row["name"]
    if kind == "restaurant":
        queries = [("大众点评", f'大众点评 "{name}" {destination}')]
    else:
        queries = [
            ("携程", f'携程 "{name}" 评分 {destination}'),
            ("小红书", f'小红书 "{name}" {destination}'),
        ]
    evidence = []
    platform_markers = {
        "携程": ("携程", "ctrip", "trip.com"),
        "大众点评": ("大众点评", "dianping"),
        "小红书": ("小红书", "xiaohongshu"),
    }
    for platform, query in queries:
        for engine in engines:
            try:
                results = _search(query, engine, cache, cache_lock)
            except Exception as exc:
                evidence.append({"platform": platform, "engine": engine, "query": query, "status": "error", "error": str(exc)})
                continue
            for result in results:
                rating, count = _extract(result["snippet"])
                point_hit = name in result["snippet"] or (len(name) >= 4 and name[:4] in result["snippet"])
                marker_hit = any(marker.lower() in (result["snippet"] + " " + result["url"]).lower() for marker in platform_markers[platform])
                relevant = point_hit and marker_hit
                evidence.append({
                    "platform": platform,
                    "engine": engine,
                    "query": query,
                    "url": result["url"],
                    "snippet": result["snippet"],
                    "rating": rating,
                    "review_count": count,
                    "status": "snippet_found",
                    "point_relevant": point_hit,
                    "relevant": relevant,
                    "confidence": "medium" if rating or count else "low",
                })
            if sum(1 for x in evidence if x.get("relevant")) >= max_relevant:
                break
    return {"kind": kind, "destination": destination, "name": name, "evidence": evidence}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="JSON array of POI rows")
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--engines", default="google,baidu,bing", help="逗号分隔的搜索引擎顺序；Bing 可作为备用")
    parser.add_argument("--cache", default="", help="搜索结果缓存 JSON 路径")
    parser.add_argument("--max-relevant", type=int, default=4, help="每个点位达到有效相关结果数后停止继续搜索")
    args = parser.parse_args()
    engines = [x.strip() for x in args.engines.split(",") if x.strip()]
    invalid = sorted(set(engines) - set(SEARCH_ENDPOINTS))
    if invalid:
        parser.error(f"不支持的搜索引擎: {invalid}")
    cache = {}
    if args.cache:
        try:
            cache = json.loads(open(args.cache, encoding="utf-8").read())
        except FileNotFoundError:
            cache = {}
    cache_lock = threading.Lock()
    rows = json.loads(open(args.input, encoding="utf-8").read())
    output = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(collect, row, engines, cache, cache_lock, args.max_relevant) for row in rows]
        for index, future in enumerate(as_completed(futures), 1):
            output.append(future.result())
            if index % 25 == 0:
                print(f"searched {index}/{len(futures)}", flush=True)
            time.sleep(0.03)
    output.sort(key=lambda x: (x["kind"], x["destination"], x["name"]))
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)
    if args.cache:
        with open(args.cache, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=2)
    print(json.dumps({"status": "PASS", "records": len(output), "output": args.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
