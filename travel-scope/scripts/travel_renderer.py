"""Travel-Scope's approved split composition; one DOM and one bilingual state.

The legacy row arrays remain the Excel/Markdown source. No network operations,
invented media markers, fixed POI count floors, or silent record truncation.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def _json(value):
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _safe_asset(value):
    value = str(value or "")
    parsed = urlsplit(value)
    if parsed.scheme and parsed.scheme not in {"https", "http"}:
        raise ValueError("Unsupported media scheme")
    if parsed.netloc and not parsed.scheme:
        raise ValueError("Protocol-relative media is not supported")
    if ".." in Path(value).parts or "\\" in value:
        raise ValueError("Media must use portable relative paths or HTTPS")
    if "places.googleapis.com" in parsed.netloc or ("googleapis.com" in parsed.netloc and "/photo" in parsed.path):
        raise ValueError("Paid Places photo URLs cannot be embedded")
    return value


def render_travel_scope_html(output_path, context):
    render_document(output_path, {context.get("language", "cn"): context})


def combine_bilingual_html(cn_path, en_path, output_path):
    editions = {}
    for path in (cn_path, en_path):
        document = Path(path).read_text(encoding="utf-8")
        payload = re.search(r'<script id="travel-data" type="application/json">(.*?)</script>', document, re.S)
        if not payload:
            raise ValueError(f"Not a Travel-Scope split-renderer output: {path}")
        editions.update(json.loads(payload.group(1))["editions"])
    if set(editions) != {"cn", "en"}:
        raise ValueError("Both language editions are required")
    render_document(output_path, editions)


def render_document(output_path, editions):
    contract = json.loads((ROOT / "references/renderer-contract.json").read_text(encoding="utf-8"))
    first = editions.get("cn") or editions["en"]
    for context in editions.values():
        _safe_asset(context.get("hero_image"))
        _safe_asset(context.get("hero_video"))
        for item in list(context.get("editorial_media", [])) + list(context.get("section_media", [])):
            if isinstance(item, dict):
                _safe_asset(item.get("image"))
        for key, module in contract["modules"].items():
            if "image" in module:
                for row in context.get(key, []):
                    if len(row) > module["image"]:
                        _safe_asset(row[module["image"]])
    css = (ROOT / "assets/split-layout.css").read_text(encoding="utf-8")
    script = (ROOT / "assets/split-layout.js").read_text(encoding="utf-8")
    is_en_only = set(editions.keys()) == {"en"}
    html_lang = "en" if is_en_only else "zh-CN"
    title_country = (first.get("country_en") or first.get("country")) if is_en_only else (first.get("country") or "Travel-Scope")
    title = html.escape(str(title_country or "Travel-Scope"))
    payload = _json({"contract": contract, "editions": editions})
    document = f'''<!doctype html>
<html lang="{html_lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="travel-scope-renderer" content="{contract['renderer_id']}"><title>Travel-Scope · {title}</title><style>{css}</style></head>
<body><main class="shell">
<aside class="media-card" aria-label="Theme illustration"><div id="hero-media"></div><div class="media-caption" id="media-caption"></div></aside>
<section class="left-column"><nav class="navigation" aria-label="Travel-Scope"><a class="brand" href="#">Travel-Scope</a><div id="tabs" role="tablist"></div><button id="language" class="language-button" type="button"></button></nav>
<header class="intro"><p class="eyebrow" id="eyebrow"></p><h1 id="headline"></h1><p class="summary" id="summary"></p></header></section>
<section class="content" id="content" role="tabpanel" tabindex="0"><div class="panel-heading"><h2 id="panel-title"></h2><span id="panel-count"></span></div><div id="panel-body"></div></section>
<footer><span id="status"></span><span id="media-status" role="status"></span></footer></main>
<noscript>This interactive guide requires JavaScript. Use the accompanying Excel or Markdown edition.</noscript>
<script id="travel-data" type="application/json">{payload}</script><script>{script}</script></body></html>'''
    Path(output_path).write_text(document, encoding="utf-8")
