"""Repeatable browser-level visual smoke checks for CN/EN Travel-Scope HTML."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

try:  # 包内导入优先；作为脚本直接运行时退回同名顶层模块。
    from . import map_gate_v422
except ImportError:  # pragma: no cover - 取决于运行方式
    import map_gate_v422

try:  # v4.2.2 V5-A：视觉 QA 报告同样要能追到产码与输入（V0-L17）
    from . import gate_producer
except ImportError:  # pragma: no cover
    import gate_producer

try:  # v4.2.2 V5-B：汇率状态由唯一登记处判定，本文件只把 DOM 里的值取回来
    from . import budget_contract
except ImportError:  # pragma: no cover
    import budget_contract

try:  # v4.2.2 V5-C：英文汉字残留只有一个口径
    from . import en_residue_measure
except ImportError:  # pragma: no cover
    import en_residue_measure

try:  # v4.2.2 V5-D：图片预算/围栏来自登记配置，交付字节的登记规则来自媒体门禁模块
    from . import local_media_gate
    from . import single_file_policy
except ImportError:  # pragma: no cover
    import local_media_gate
    import single_file_policy

try:  # v4.2.2 V6-B：读者载荷该剔哪些 provider 字段，只有链接合同登记处说了算
    from . import map_link_selector
except ImportError:  # pragma: no cover
    import map_link_selector

try:  # ZH-RELEASE-1（业主 2026-11-02 裁 Q1-A/Q2-A）：语言档位与来源投影的判据都不在本文件重写
    from . import spa_renderer
    from . import source_projection
    from . import reader_payload_scope
except ImportError:  # pragma: no cover
    import spa_renderer
    import source_projection
    import reader_payload_scope

PRODUCING_CODE = ("scripts/visual_qa.py", "scripts/gate_producer.py", "scripts/map_gate_v422.py",
                  "scripts/spa_renderer.py", "scripts/budget_contract.py",
                  "scripts/en_residue_measure.py", "scripts/local_media_gate.py",
                  "scripts/single_file_policy.py", "scripts/map_link_selector.py",
                  "scripts/source_projection.py", "scripts/reader_payload_scope.py")
PRODUCING_CONFIG = ("references/map-gate-v422.json", "references/map-link-selection.json",
                    "references/renderer-contract.json", "references/budget-policy.json",
                    "references/run-quality-policy.json",
                    "references/single-file-delivery-policy.json",
                    "references/data-model.json")


# v4.2.2 §8.1/§9：DOM 与 dataset 的对账由门禁模块做，本文件只负责把浏览器里的值取回来。
# 这里刻意不写主机名名单——QA 再维护一套 provider 正则就是第二套规则（§9 明令禁止）。
MAP_DOM_ROWS_JS = r'''() => [...document.querySelectorAll('.map-links a[data-link-mode]')]
  .map(a => ({targetId: a.dataset.targetId || '', provider: a.dataset.provider || '',
              linkMode: a.dataset.linkMode || '', href: a.getAttribute('href') || '',
              resolvedHref: a.href, text: (a.textContent || '').trim(),
              entityType: a.dataset.entityType || '',
              criticality: a.dataset.criticality || '',
              identityStatus: a.dataset.identityStatus || '',
              coordinateStatus: a.dataset.coordinateStatus || '',
              resolutionStatus: a.dataset.googleResolutionStatus || ''}))'''


# 排版护栏：找出"文字比容器宽，却被 ellipsis 截断，又没有滚动/换行出口"的元素。
# 英文通常比同义中文长 1.5-2 倍，所以这类缺陷在 §2.2.2 补齐英文来源后才显形。
# 已知可横向滚动的槽位（标签栏、路线选择、覆盖表）不算，读者能滑到就不算丢内容。
CLIPPED_TEXT_JS = r'''() => {
  const scrollers = new Set(['tabs', 'route-pick', 'coverage-table-wrap']);
  const rows = [];
  for (const el of document.querySelectorAll('#main *')) {
    if (!el.innerText || !el.innerText.trim()) continue;
    const cs = getComputedStyle(el);
    if (cs.overflowX === 'auto' || cs.overflowX === 'scroll') continue;
    if (el.parentElement && scrollers.has(el.parentElement.className.split(/\s+/)[0])) continue;
    const over = el.scrollWidth - el.clientWidth;
    if (over > 24 && cs.textOverflow === 'ellipsis') {
      rows.push({sig: el.tagName.toLowerCase() + '.' +
                (typeof el.className === 'string' ? el.className.trim().split(/\s+/)[0] : ''),
                 px: over, text: el.innerText.trim().slice(0, 34)});
    }
  }
  return rows.sort((a, b) => b.px - a.px).slice(0, 6);
}'''


def first(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"missing HTML: {pattern}")
    # A repaired run may retain older titled drafts. Prefer the canonical,
    # shortest delivery name instead of accidentally validating a stale copy.
    return min(matches, key=lambda path: (len(path.name), path.name))


def check_split_page(page, html_path: Path, label: str, viewport: dict[str, int], screenshot: Path, *, bilingual: bool) -> dict:
    """Check the V4.0.3 split renderer against its own UI contract."""
    console_errors: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    page.goto(html_path.resolve().as_uri(), wait_until="domcontentloaded")
    page.wait_for_timeout(250)
    result = {"label": label, "viewport": viewport, "console_errors": console_errors, "renderer": "travel-scope-split-v1"}
    initial_language = page.locator("html").get_attribute("lang") or "zh-CN"
    is_english = initial_language.lower().startswith("en")
    headline_text = page.locator("#headline").inner_text()
    status_text = page.locator("#status").inner_text()
    result["product_headline"] = headline_text
    headline_clean = headline_text.strip()
    headline_lines = [l.strip() for l in headline_clean.splitlines() if l.strip()]
    has_banned_headline = bool(re.search(r"(?<!\d)-Day\b", headline_clean)) or any(b in headline_clean for b in ("undefined", "null", "NaN"))
    has_duplicate_country = False
    if len(headline_lines) >= 2:
        lead_token = headline_lines[0]
        if lead_token and lead_token in headline_lines[1]:
            has_duplicate_country = True

    result["product_headline_factual"] = (
        ("route" in headline_clean.lower() if is_english else "路线" in headline_clean)
        and "慢慢探索" not in headline_clean
        and not has_banned_headline
        and not has_duplicate_country
    )
    result["reader_status_factual"] = (
        (("Updated" in status_text or "Recheck dynamic information" in status_text) if is_english else ("更新于" in status_text or "动态信息请临行复核" in status_text))
        and "研究稿" not in status_text
    )
    result["hero_carousel_slides"] = page.locator(".hero-slide").count()
    result["hero_carousel_dots"] = page.locator(".hero-dot").count()
    result["hero_carousel_interval"] = page.locator(".hero-dots").get_attribute("data-interval") if result["hero_carousel_dots"] else ""
    result["hero_pause_control_removed"] = page.locator("#motion-toggle").count() == 0
    tabs = page.locator("#tabs [role=tab]")
    result["navigation_links"] = tabs.count()
    result["navigation_interaction"] = False
    route_buttons = page.locator("[data-route]")
    result["route_options"] = route_buttons.count()
    result["unique_route_corridors"] = page.evaluate("() => { const editions = JSON.parse(document.querySelector('#travel-data').textContent).editions; const edition = editions.cn || editions.en || Object.values(editions)[0]; return new Set(edition.routes.map(row => row[2])).size; }")
    result["expected_section_media"] = page.evaluate("() => { const editions = JSON.parse(document.querySelector('#travel-data').textContent).editions; const edition = editions.cn || editions.en || Object.values(editions)[0]; return (edition.section_media || []).filter(item => item.image).length; }")
    section_sources: list[str] = []
    branch_cover_checks: list[dict] = []
    reader_detail_checks: list[bool] = []
    poi_media_counts: list[int] = []
    coordinate_pattern = re.compile(r"[-+]?\d{1,3}\.\d+\s*,\s*[-+]?\d{1,3}\.\d+")
    def capture_branch_state() -> None:
        text_content = page.locator("#panel-body").inner_text()
        reader_detail_checks.append("未采用聚合平台评分" not in text_content and not coordinate_pattern.search(text_content))
        poi_media_counts.append(page.locator(".branch-records .poi img,.branch-records .image-missing").count())
        branch_cover_checks.extend(page.locator(".destination-branch").evaluate_all("""branches => {
          const editions=JSON.parse(document.querySelector('#travel-data').textContent).editions;
          const edition=editions[document.documentElement.lang.startsWith('en')?'en':'cn']||editions.cn||editions.en;
          const media=[...(edition.section_media||[]),...(edition.editorial_media||[])];
          return branches.map(branch=>{const visual=branch.querySelector('.branch-visual'),image=visual?.querySelector('img'),destination=branch.dataset.destination||'';return {destination,mediaDestination:visual?.dataset.mediaDestination||'',hasImage:!!image,hasAvailableContext:media.some(item=>item.destination===destination&&item.image),badgeCount:visual?.querySelectorAll('small').length||0};});
        }"""))
    result["route_switch"] = False
    result["route_motion"] = False
    if route_buttons.count() > 1:
        before_route = page.locator(".route-feature h4").inner_text()
        before_hero_images = page.locator(".hero-slide img").evaluate_all("imgs => imgs.map(img => img.getAttribute('src'))")
        result["route_motion"] = page.evaluate("() => { document.querySelectorAll('[data-route]')[1].click(); return document.querySelector('#panel-body').classList.contains('route-leaving'); }")
        page.wait_for_timeout(480)
        after_route = page.locator(".route-feature h4").inner_text()
        result["route_switch"] = after_route != before_route and route_buttons.nth(1).get_attribute("aria-pressed") == "true"
        after_hero_images = page.locator(".hero-slide img").evaluate_all("imgs => imgs.map(img => img.getAttribute('src'))")
        result["route_hero_media_sync"] = before_hero_images != after_hero_images
    flow_check = page.evaluate(r"""() => {
      const editions=JSON.parse(document.querySelector('#travel-data').textContent).editions;
      const lang=document.documentElement.lang.startsWith('en')?'en':'cn';
      const edition=editions[lang]||editions.cn||editions.en;
      const active=document.querySelector('[data-route][aria-pressed=true]')?.dataset.route||edition.routes?.[0]?.[0]||'';
      const routeRow=(edition.routes||[]).find(r=>r[0]===active)||[];
      const rawCorridor=String(routeRow[2]||'');
      const expectedNodes=(Array.isArray(routeRow[8])&&routeRow[8].length?routeRow[8]:rawCorridor.split(/\s*(?:→|->|—|-|>)\s*/)).map(s=>String(s).trim()).filter(Boolean);
      const actualNodes=[...document.querySelectorAll('.route-flow span')].map(s=>{
        const clone=s.cloneNode(true);
        clone.querySelectorAll('i').forEach(i=>i.remove());
        return clone.textContent.trim();
      });
      return {expected:expectedNodes.length,actual:actualNodes.length,match:actualNodes.length>=2&&actualNodes.length===expectedNodes.length};
    }""")
    result["route_flow_nodes_match"] = flow_check.get("match", False)
    result["route_flow_expected_nodes"] = flow_check.get("expected", 0)
    result["route_flow_actual_nodes"] = flow_check.get("actual", 0)
    result["no_spot_spot_boilerplate"] = not bool(re.search(r"\bSpot\s+Spot\b", page.locator("body").inner_text(), re.I))
    result["visible_route_days"] = page.locator(".day").count()
    result["expected_route_days"] = page.evaluate(r"""() => {
      const data=JSON.parse(document.querySelector('#travel-data').textContent);
      const edition=data.editions[document.documentElement.lang.startsWith('en')?'en':'cn']||data.editions.cn||data.editions.en;
      const active=document.querySelector('[data-route][aria-pressed=true]')?.dataset.route||edition.routes?.[0]?.[0]||'';
      return Math.max(0,...(edition.itinerary||[]).filter(row=>row[0]===active).map(row=>Number(String(row[1]).replace(/\D/g,''))||0));
    }""")
    result["editorial_images"] = page.locator(".editorial-inline img").count()
    result["editorial_wall_removed"] = page.locator(".editorial-grid,.editorial-card").count() == 0
    page.evaluate("() => document.querySelectorAll('.editorial-inline img').forEach(img => { img.loading = 'eager'; })")
    page.wait_for_function("() => [...document.querySelectorAll('.editorial-inline img')].every(img => img.complete && img.naturalWidth > 0)")
    result["broken_editorial_images"] = page.locator(".editorial-inline img").evaluate_all(
        "els => els.filter(img => !img.complete || img.naturalWidth === 0).length"
    )
    page.screenshot(path=str(screenshot.with_name(screenshot.stem + "-overview" + screenshot.suffix)), full_page=False)
    if tabs.count() >= 2:
        # The docked navigation must stay usable while reading downward; a tab
        # change must not require an upward-scroll reveal gesture.
        page.evaluate("window.scrollTo(0, Math.min(900, document.documentElement.scrollHeight - window.innerHeight))")
        page.wait_for_timeout(620)
        result["floating_navigation_persistent"] = page.locator(".navigation.is-docked.is-visible").count() == 1
        before = page.locator("#panel-title").inner_text()
        tabs.nth(1).click()
        page.wait_for_timeout(260)
        after = page.locator("#panel-title").inner_text()
        result["navigation_interaction"] = bool(after and after != before and tabs.nth(1).get_attribute("aria-selected") == "true")
    result["stay_branches"] = page.locator('[data-module="hotels"] .destination-branch').count()
    result["stay_branch_visuals"] = page.locator('[data-module="hotels"] .branch-visual img').count()
    capture_branch_state()
    section_sources.extend(page.locator('[data-module="hotels"] .branch-visual img').evaluate_all("els => els.map(img => img.getAttribute('src'))"))
    if viewport["width"] >= 1000:
        page.screenshot(path=str(screenshot.with_name(screenshot.stem + "-stays" + screenshot.suffix)), full_page=False)
    page.evaluate("document.querySelector('[data-tab=food]').click()")
    page.wait_for_timeout(340)
    page.wait_for_function("() => !document.getElementById('content')?.getAttribute('aria-busy')")
    result["food_lead_first"] = page.locator("#panel-body .module").first.get_attribute("data-module") == "local_chains"
    result["food_lead_copy"] = page.locator("#panel-body .module .module-heading h3").first.inner_text() == (
        "Local chains and convenient options" if is_english else "当地连锁与便捷选择"
    )
    result["food_branches"] = page.locator('[data-module="restaurants"] .destination-branch, [data-module="cafes"] .destination-branch').count()
    capture_branch_state()
    section_sources.extend(page.locator('[data-module="restaurants"] .branch-visual img, [data-module="cafes"] .branch-visual img').evaluate_all("els => els.map(img => img.getAttribute('src'))"))
    if viewport["width"] >= 1000:
        page.screenshot(path=str(screenshot.with_name(screenshot.stem + "-food" + screenshot.suffix)), full_page=False)
    page.evaluate("document.querySelector('[data-tab=sights]').click()")
    page.wait_for_timeout(340)
    page.wait_for_function("() => !document.getElementById('content')?.getAttribute('aria-busy')")
    result["sights_lead_first"] = page.locator("#panel-body .module").first.get_attribute("data-module") == "worth_it"
    result["sights_lead_copy"] = page.locator("#panel-body .module .module-heading h3").first.inner_text() == (
        "Key experiences" if is_english else "核心体验"
    )
    result["sight_branches"] = page.locator('[data-module="attractions"] .destination-branch, [data-module="dive_sites"] .destination-branch').count()
    capture_branch_state()
    section_sources.extend(page.locator('[data-module="attractions"] .branch-visual img, [data-module="dive_sites"] .branch-visual img').evaluate_all("els => els.map(img => img.getAttribute('src'))"))
    result["section_branch_images"] = len(section_sources)
    result["unique_section_branch_images"] = len(set(section_sources))
    result["branch_cover_context_valid"] = all(not item["hasImage"] or item["mediaDestination"] == item["destination"] for item in branch_cover_checks)
    result["branch_cover_fallback_resolved"] = all(item["hasImage"] or not item["hasAvailableContext"] for item in branch_cover_checks)
    result["branch_cover_badges"] = sum(item["badgeCount"] for item in branch_cover_checks)
    result["poi_item_media"] = sum(poi_media_counts)
    result["reader_detail_hygiene"] = all(reader_detail_checks)
    if viewport["width"] >= 1000:
        page.screenshot(path=str(screenshot.with_name(screenshot.stem + "-sights" + screenshot.suffix)), full_page=False)
    page.evaluate("document.querySelector('[data-tab=transport]').click()")
    page.wait_for_timeout(340)
    page.wait_for_function("() => !document.getElementById('content')?.getAttribute('aria-busy')")
    result["transport_branches"] = page.locator('[data-module="transport"] .transport-branch').count()
    result["transport_map_links"] = page.locator('[data-module="transport"] .map-links a').count()
    result["transport_schedule_statuses"] = page.locator('[data-module="transport"] .schedule-status').count()
    result["map_contract"] = page.evaluate("""() => {
      const data=JSON.parse(document.querySelector('#travel-data').textContent);
      const edition=data.editions[document.documentElement.lang.startsWith('en')?'en':'cn']||data.editions.cn||data.editions.en;
      const links=[...document.querySelectorAll('.map-links')];
      const allowed=new Set(['www.google.com','google.com','maps.google.com','maps.app.goo.gl','maps.apple.com','uri.amap.com','map.baidu.com','api.map.baidu.com']);
      return {formal:!edition.demo_mode,total:links.length,searchCandidates:links.filter(node=>node.dataset.mapLevel==='search_candidate').length,
              missingLevel:links.filter(node=>!node.dataset.mapLevel).length,
              invalidUrls:links.flatMap(node=>[...node.querySelectorAll('a')]).filter(a=>{try{const u=new URL(a.href);return u.protocol!=='https:'||!allowed.has(u.hostname);}catch{return true;}}).length};
    }""")
    page.evaluate("document.querySelector('[data-tab=budget]').click()")
    page.wait_for_timeout(340)
    page.wait_for_function("() => !document.getElementById('content')?.getAttribute('aria-busy')")
    result["budget_is_independent_tab"] = page.locator("#panel-body .module").count() == 1 and page.locator('[data-module="budget"]').count() == 1
    result["budget_overview"] = page.locator('[data-module="budget"] .budget-overview').count() == 1
    result["budget_cards"] = page.locator('[data-module="budget"] .budget-cards>article').count()
    budget_text = page.locator('[data-module="budget"]').inner_text()
    result["budget_formula_hidden"] = not any(token in budget_text.upper() for token in ("=SUM", "=AVERAGE", "=IF("))
    result["budget_summary_nonzero"] = page.locator('[data-module="budget"] .budget-card-head strong').last.inner_text().strip() not in ("", "¥0")
    page.evaluate("document.querySelector('[data-tab=local_toolkit]').click()")
    page.wait_for_timeout(340)
    page.wait_for_function("() => !document.getElementById('content')?.getAttribute('aria-busy')")
    result["local_toolkit_is_independent_tab"] = page.locator("#panel-body .module").count() == 1 and page.locator('[data-module="local_apps"]').count() == 1
    result["local_toolkit_essential_cards"] = page.locator('.app-card[data-priority="essential"]').count()
    result["local_toolkit_drawer_groups"] = page.locator('.app-drawer').count()
    result["local_toolkit_no_retired"] = page.locator('.app-card[data-status="retired"]').count() == 0
    page.evaluate("document.querySelector('[data-tab=notes]').click()")
    page.wait_for_timeout(340)
    page.wait_for_function("() => !document.getElementById('content')?.getAttribute('aria-busy')")
    result["notes_lead_first"] = page.locator("#panel-body .module").first.get_attribute("data-module") == "local_knowledge"
    note_headings = page.locator("#panel-body .module .module-heading h3").all_inner_texts()
    expected_note_headings = (
        ["Local travel essentials", "Entry and local practicalities", "Pre-trip checklist"]
        if is_english
        else ["当地旅行要点", "入境与当地事务", "行前准备"]
    )
    result["notes_copy"] = all(name in note_headings for name in expected_note_headings)
    result["notes_has_no_budget"] = page.locator('[data-module="budget"]').count() == 0
    result["tip_branches"] = page.locator('[data-module="practical"] .tip-branches>details, [data-module="packing"] .tip-branches>details').count()
    result["source_groups"] = page.locator('[data-module="source_evidence"] .source-groups>details').count()
    result["source_groups_open_by_default"] = page.locator('[data-module="source_evidence"] .source-groups>details[open]').count()
    result["broken_local_images"] = page.locator(".poi img").evaluate_all(
        "els => els.filter(img => !/^https?:/i.test(img.getAttribute('src') || '') && img.complete && img.naturalWidth === 0).length"
    )
    result["modules"] = page.locator("#panel-body .module").count()
    language = page.locator("#language")
    result["language_switch"] = not bilingual
    if bilingual and language.count() == 1 and language.is_visible():
        before_language = page.locator("html").get_attribute("lang")
        language.click()
        page.wait_for_timeout(260)
        result["language_switch"] = page.locator("html").get_attribute("lang") != before_language
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(80)
    media = page.locator(".media-card")
    before_top = media.bounding_box()["y"] if media.count() else None
    page.evaluate("window.scrollTo(0, Math.min(900, document.documentElement.scrollHeight - window.innerHeight))")
    page.wait_for_timeout(80)
    after_box = media.bounding_box() if media.count() else None
    after_top = after_box["y"] if after_box else None
    result["hero_scrolls_with_page"] = before_top is not None and after_top is not None and after_top < before_top - 20
    page.wait_for_timeout(620)
    result["floating_navigation_persistent"] = page.locator(".navigation.is-docked.is-visible").count() == 1
    result["horizontal_overflow"] = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2")
    page.screenshot(path=str(screenshot), full_page=False)
    if console_errors:
        raise RuntimeError(f"{label} browser errors: {console_errors[:3]}")
    if result["navigation_links"] != 8 or not result["navigation_interaction"] or not result["language_switch"]:
        raise RuntimeError(f"{label} interaction check failed: {result}")
    is_demo = page.evaluate("() => { try { const d=JSON.parse(document.querySelector('#travel-data').textContent); return !!(d.editions.cn?.demo_mode || d.editions.en?.demo_mode); } catch(e){ return false; } }")
    if not is_demo:
        if result["route_options"] < 3 or result["unique_route_corridors"] < 3 or not result["route_switch"] or not result["route_motion"] or not result.get("route_hero_media_sync") or result["visible_route_days"] != result["expected_route_days"]:
            raise RuntimeError(f"{label} route switch check failed: {result}")
        if result["editorial_images"] < 2 or not result["editorial_wall_removed"] or result["broken_editorial_images"]:
            raise RuntimeError(f"{label} editorial media check failed: {result}")
        if not result["product_headline_factual"] or not result["reader_status_factual"]:
            raise RuntimeError(f"{label} reader-facing headline/status copy failed: {result}")
        if result["stay_branches"] < 2 or result["stay_branch_visuals"] < 2 or not result["food_lead_first"] or not result["food_lead_copy"] or result["food_branches"] < 2:
            raise RuntimeError(f"{label} stays/food information architecture failed: {result}")
        if not result["sights_lead_first"] or not result["sights_lead_copy"] or result["sight_branches"] < 2 or result["transport_branches"] < 2 or result["transport_map_links"] < 4 or result["transport_schedule_statuses"] != result["transport_branches"]:
            raise RuntimeError(f"{label} sights/transport information architecture failed: {result}")
    if not result.get("route_flow_nodes_match", True):
        raise RuntimeError(f"{label} route flow nodes mismatch: expected {result.get('route_flow_expected_nodes')}, got {result.get('route_flow_actual_nodes')}: {result}")
    if not result.get("no_spot_spot_boilerplate", True):
        raise RuntimeError(f"{label} contains repetitive placeholder text 'Spot Spot': {result}")
    if not is_demo:
        if not (1 <= result["hero_carousel_slides"] <= 3) or result["hero_carousel_dots"] != result["hero_carousel_slides"] or result["hero_carousel_interval"] != "5000" or not result["hero_pause_control_removed"]:
            raise RuntimeError(f"{label} hero carousel check failed: {result}")
    if not result["modules"] or result["horizontal_overflow"] or result["broken_local_images"]:
        raise RuntimeError(f"{label} layout/media check failed: {result}")
    if not result["hero_scrolls_with_page"]:
        raise RuntimeError(f"{label} hero remains fixed during page scroll: {result}")
    if not result["floating_navigation_persistent"]:
        raise RuntimeError(f"{label} docked navigation did not remain visible during downward scrolling: {result}")
    if not is_demo:
        if not result["branch_cover_context_valid"] or not result["branch_cover_fallback_resolved"] or result["branch_cover_badges"] or result["poi_item_media"] or not result["reader_detail_hygiene"]:
            raise RuntimeError(f"{label} branch cover/reader detail presentation failed: {result}")
    if result["map_contract"]["missingLevel"] or result["map_contract"]["invalidUrls"] or (result["map_contract"]["formal"] and result["map_contract"]["searchCandidates"]):
        raise RuntimeError(f"{label} map target contract failed: {result}")
    if not result["budget_is_independent_tab"] or not result["budget_overview"] or not result["budget_cards"] or not result["budget_formula_hidden"] or not result["budget_summary_nonzero"]:
        raise RuntimeError(f"{label} budget presentation failed: {result}")
    if not result.get("local_toolkit_is_independent_tab") or result.get("local_toolkit_essential_cards", 0) < 1 or not result.get("local_toolkit_no_retired", True):
        raise RuntimeError(f"{label} local toolkit presentation failed: {result}")
    if not result["notes_lead_first"] or not result["notes_copy"] or not result["notes_has_no_budget"] or result["tip_branches"] < 2 or not result["source_groups"] or result["source_groups_open_by_default"]:
        raise RuntimeError(f"{label} budget/source presentation failed: {result}")
    return result


SPA_VIEWPORTS = (
    (1920, 1080, "desktop-1920"),
    (1440, 900, "desktop"),
    (768, 1024, "tablet"),
    (430, 932, "mobile-430"),
    (390, 844, "mobile-390"),
    (360, 800, "mobile-360"),
)


def _record(results: list, label: str, call) -> None:
    """Turn a raising check into a recorded failure so one run lists every defect.

    Without this the report file is never written when a check raises, and the
    delivery gate can then read a stale PASS report from the previous run.
    """
    try:
        results.append(call())
    except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
        results.append({"label": label, "status": "FAIL",
                        "failures": [f"BROWSER_ABORT|{type(exc).__name__}: {exc}"]})


def check_page(page, html_path: Path, label: str, viewport: dict[str, int], screenshot: Path) -> dict:
    console_errors: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    page.goto(html_path.resolve().as_uri(), wait_until="domcontentloaded")
    page.wait_for_timeout(150)
    result = {"label": label, "viewport": viewport, "console_errors": console_errors}
    result["content_toc"] = page.locator("nav#guide-toc").count() == 1 and page.locator("nav#guide-toc a").count() >= 2
    result["toc_targets"] = page.locator("nav#guide-toc a").evaluate_all(
        "els => els.filter(a => { const id = (a.getAttribute('href') || '').slice(1); return id && !document.getElementById(id); }).length"
    )
    result["theme_toggle"] = page.locator("button.theme-toggle").count() == 1
    if result["theme_toggle"]:
        page.locator("button.theme-toggle").click()
        result["theme_switch"] = page.locator("body.theme-dark").count() == 1
        page.locator("button.theme-toggle").click()
    else:
        result["theme_switch"] = False
    nav_links = page.locator("nav#guide-toc [data-op-panel]")
    result["navigation_links"] = nav_links.count()
    result["navigation_interaction"] = False
    if nav_links.count():
        nav_links.first.click()
        page.wait_for_timeout(50)
        result["navigation_interaction"] = page.locator("#op-panel-title").count() == 1 and page.locator("#op-panel-body").count() == 1
    result["broken_local_images"] = page.locator("img.loc-thumb").evaluate_all(
        "els => els.filter(img => !/^https?:/i.test(img.getAttribute('src') || '') && (!img.complete || img.naturalWidth === 0)).length"
    )
    result["destination_headers"] = page.locator(".op-full-section").count()
    result["horizontal_overflow"] = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2")
    page.screenshot(path=str(screenshot), full_page=False)
    if console_errors:
        raise RuntimeError(f"{label} browser errors: {console_errors[:3]}")
    if not result["theme_toggle"] or not result["theme_switch"] or not result["navigation_interaction"]:
        raise RuntimeError(f"{label} interaction check failed: {result}")
    if not result["content_toc"] or result["toc_targets"]:
        raise RuntimeError(f"{label} content navigation check failed: {result}")
    # V4.2.0: 顶栏首屏常驻可达断言 (scrollY=0 时 opacity===1 且 top>=0)
    topbar_accessible = page.evaluate('''() => {
        const topbar = document.getElementById('topbar');
        const btn = document.getElementById('lang-btn');
        if (!topbar || !btn) return false;
        const s = window.getComputedStyle(topbar);
        const rect = btn.getBoundingClientRect();
        return s.opacity === '1' && rect.top >= 0;
    }''')
    if not topbar_accessible:
        raise RuntimeError(f"{label} scrollY=0 时 topbar 或 #lang-btn 未处于视口内常驻可见 (opacity!=1 或 top<0)")

    # V4.2.0: 路线拓扑节点数断言 (>= 2，杜绝连字符未拆分造成孤独圆点)
    rl_nodes = page.locator(".route-line .rl-node").count()
    if rl_nodes < 2:
        raise RuntimeError(f"{label} 路线节点数 < 2 (仅 {rl_nodes} 个节点，走廊连线未拆分)")

    # V4.2.0: 每日行程 Header 结构化信息断言 (天数、城市、主题)
    day_summaries = page.locator(".day summary").all_inner_texts()
    for s in day_summaries:
        if len(s.strip()) < 5:
            raise RuntimeError(f"{label} 日程标题栏内容过短或空洞: '{s}'")

    # V4.2.0: 双语切换状态与零汉字泄漏/美元计价断言
    lang_btn = page.locator("#lang-btn")
    if lang_btn.count():
        lang_btn.click()
        page.wait_for_timeout(350)
        en_body = page.locator("body").inner_text()
        
        # 英文模式绝对禁止未核验免责声明残留
        if "exchange rate unverified" in en_body:
            raise RuntimeError(f"{label} EN 模式存在 'exchange rate unverified' 未核验免责声明残留")
        
        # 英文模式每日花费面板绝对禁止出现 CNY
        day_cards_text = page.locator(".day-cards").inner_text() if page.locator(".day-cards").count() else ""
        if "CNY" in day_cards_text:
            raise RuntimeError(f"{label} EN 模式每日花费面板残留 CNY 货币符号")
            
        # 英文模式分类标签绝不含汉字
        for sub in page.locator(".poi-sub").all_inner_texts():
            if re.search(r"[一-龥]", sub):
                raise RuntimeError(f"{label} EN 模式 .poi-sub 存在中文汉字泄漏: '{sub}'")
                
        # 截图归档 EN 视图
        en_shot = screenshot.parent / f"{label}-en.png"
        page.screenshot(path=str(en_shot), full_page=False)
        
        # 切回中文
        lang_btn.click()
        page.wait_for_timeout(200)

    if result["horizontal_overflow"]:
        raise RuntimeError(f"{label} horizontal overflow at {viewport}")
    if result["broken_local_images"]:
        raise RuntimeError(f"{label} local images failed to load: {result['broken_local_images']}")
    return result


def check_bilingual_page(page, html_path: Path, label: str, viewport: dict[str, int], screenshot: Path) -> dict:
    """Check the single-file bilingual shell without confusing its two editions."""
    console_errors: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    page.goto(html_path.resolve().as_uri(), wait_until="domcontentloaded")
    page.wait_for_timeout(150)
    result = {"label": label, "viewport": viewport, "console_errors": console_errors}
    cn = page.locator(".edition-cn")
    en = page.locator(".edition-en")
    result["content_toc"] = cn.locator("nav#guide-toc").count() == 1 and cn.locator("nav#guide-toc a").count() >= 2
    result["toc_targets"] = cn.locator("nav#guide-toc a").evaluate_all(
        "els => els.filter(a => { const id = (a.getAttribute('href') || '').slice(1); return id && !document.getElementById(id); }).length"
    )
    result["theme_toggle"] = cn.locator("button.theme-toggle").count() == 1
    if result["theme_toggle"]:
        cn.locator("button.theme-toggle").click()
        result["theme_switch"] = page.locator("body.theme-dark").count() == 1
        cn.locator("button.theme-toggle").click()
    else:
        result["theme_switch"] = False
    nav_links = cn.locator("nav#guide-toc [data-op-panel]")
    result["navigation_links"] = nav_links.count()
    result["navigation_interaction"] = False
    if nav_links.count():
        nav_links.first.click()
        page.wait_for_timeout(50)
        result["navigation_interaction"] = cn.locator("#op-panel-title").count() == 1 and cn.locator("#op-panel-body").count() == 1
    result["broken_local_images"] = cn.locator("img.loc-thumb").evaluate_all(
        "els => els.filter(img => !/^https?:/i.test(img.getAttribute('src') || '') && (!img.complete || img.naturalWidth === 0)).length"
    )
    result["destination_headers"] = cn.locator(".op-full-section").count()
    switch_en = page.locator(".edition-cn:not([hidden]) .edition-switcher button[onclick=\"switchEdition('en')\"]")
    result["language_switch_button_count"] = switch_en.count()
    result["language_switch"] = False
    if switch_en.count():
        switch_en.click()
        page.wait_for_timeout(50)
        result["cn_hidden_after_switch"] = cn.is_hidden()
        result["en_visible_after_switch"] = en.is_visible()
        result["en_toc_count_after_switch"] = en.locator("nav#guide-toc-en").count()
        result["language_switch"] = cn.is_hidden() and en.is_visible() and en.locator("nav#guide-toc-en").count() == 1
        page.locator(".edition-en:not([hidden]) .edition-switcher button[onclick=\"switchEdition('cn')\"]").click()
    result["horizontal_overflow"] = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2")
    page.screenshot(path=str(screenshot), full_page=False)
    if console_errors:
        raise RuntimeError(f"{label} browser errors: {console_errors[:3]}")
    if not result["theme_toggle"] or not result["theme_switch"] or not result["navigation_interaction"] or not result["language_switch"]:
        raise RuntimeError(f"{label} interaction check failed: {result}")
    if not result["content_toc"] or result["toc_targets"]:
        raise RuntimeError(f"{label} content navigation check failed: {result}")
    if result["horizontal_overflow"]:
        raise RuntimeError(f"{label} horizontal overflow at {viewport}")
    if result["broken_local_images"]:
        raise RuntimeError(f"{label} local images failed to load: {result['broken_local_images']}")
    return result


# 逐元素「有没有汉字」复用 en_residue_measure 的同一字类（V0-L06，导入在文件顶部）：
# 本文件不得再写第二份 [\u4e00-\u9fff]。
CJK_RE = en_residue_measure.CJK_IDEOGRAPH_RE

# 英文态快照：可见正文 + 逐槽定位。字类由登记处注入（__CJK_CLASS__），不在这里重打一遍。
EN_STATE_JS = r'''() => ({
  body: document.body.innerText,
  cover: document.getElementById('cover-title')?.innerText || '',
  poiSub: [...document.querySelectorAll('.poi-sub')].map(e => e.innerText.trim()),
  dayCards: document.querySelector('.day-cards')?.innerText || '',
  title: document.title || '',
  pending: parseInt(document.documentElement.dataset.enUntranslated || '0', 10),
  pendingList: (() => {
    try { return JSON.parse(document.documentElement.dataset.enUntranslatedList || '[]'); }
    catch (e) { return []; }
  })(),
  daySummaries: [...document.querySelectorAll('.day summary')].map(e => e.innerText.trim()),
  census: (() => {
    const groups = {};
    const cjk = new RegExp("^[__CJK_CLASS__]$");
    const has = (s) => [...s].some(ch => cjk.test(ch));
    const skip = new Set(['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT', 'TEXTAREA']);
    for (const el of document.querySelectorAll('body *')) {
      if (skip.has(el.tagName)) continue;
      if (el.id === 'lang-btn') continue;   // the toggle label is meant to read 中文
      const own = [...el.childNodes].filter(n => n.nodeType === 3)
        .map(n => n.textContent).join('').trim();
      if (!own || !has(own)) continue;
      const cls = (typeof el.className === 'string' && el.className.trim())
        ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
      const sig = el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + cls;
      const g = groups[sig] || (groups[sig] = {count: 0, samples: []});
      g.count += 1;
      if (g.samples.length < 3) g.samples.push(own.slice(0, 36));
    }
    return groups;
  })(),
})'''

# §11.6.4 / §14: a placeholder venue name is exactly the shape the v4.2.0 patch
# script manufactured when it regex-deleted CJK characters out of a POI name.
MAP_PLACEHOLDER_SEGMENT_RE = re.compile(r"\b(?:[A-Z][A-Za-z .&'-]{0,40} )?Venue\b")
MAP_NUMERIC_SEGMENT_RE = re.compile(r"^\s*\d{2,4}\s*$")
STRICT_PLACE_ID_RE = re.compile(r"^ChIJ[0-9A-Za-z-]{20,27}$")
SYNTHETIC_PLACE_ID_RE = re.compile(r"^ChIJ_")
RELEASE_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT_LEVELS = ["search_candidate"]
try:
    _CONTRACT_LEVELS = json.loads(
        (RELEASE_ROOT / "references/renderer-contract.json").read_text(encoding="utf-8")
    )["presentation"]["map_target_levels"]
except (OSError, KeyError, ValueError, json.JSONDecodeError):
    pass
# The contract file is the authority (§11.6.4); a hard-coded copy here would drift again.
CONTRACT_MAP_LEVELS = tuple(_CONTRACT_LEVELS)
UNNAMED_LEVEL = "unnamed_coordinate" if "unnamed_coordinate" in _CONTRACT_LEVELS else "__none__"
# v4.2.2 V5-D（V0-L11）：图片预算以前是这里的三个裸数（1200 / 80KB / 4MB），改一处忘一处
# 就是 §10 说的「门槛被悄悄降低」。现在一律从 references/single-file-delivery-policy.json 读；
# 配置读不到就让门禁报错，而不是退回一套默认值。
try:
    SINGLE_FILE_POLICY = single_file_policy.load_policy()
except single_file_policy.SingleFilePolicyError as _policy_exc:
    # 配置读不到就退出得响亮：把预算退回到本地默认值，等于用另一套规则给产物放行。
    raise SystemExit(f"visual_qa 无法启动：单文件交付配置不可用（{_policy_exc}）")
_budgets = SINGLE_FILE_POLICY.get("budgets") or {}
MAX_DELIVERED_IMG_WIDTH = int(_budgets.get("max_delivered_image_width_px") or 0)
HERO_INLINE_BUDGET_BYTES = int(_budgets.get("hero_inline_budget_bytes") or 0)
# Budget for the bytes the reader must carry before the first card paints, and for the whole file.
# A single-file guide is opened on a phone over a cellular link, so the total is the number that
# decides whether "fully inline" is affordable at all; the per-image number only covers first paint.
TOTAL_INLINE_BUDGET_BYTES = int(_budgets.get("total_inline_budget_bytes") or 0)


def inline_budget_verdict(inline_items, *, hero_budget_bytes=None, total_budget_bytes=None) -> dict:
    """两条 DOM 内联预算的唯一点判定：首屏单图（hero）与全页内联合计。

    业主 2026-11-04 裁示把首屏预算从 81,920 抬到 90,112（下一个 8 KiB 档），并明令
    「不能通过修改质量、宽度或来源绕过」。所以这里刻意只看**读者浏览器真要解码的内联字节数**：
    不看 width、不看 jpeg_quality、不看来源与档位——一张图无论怎么产出来，只要它落在首屏且字节超门，
    就是同一条形。想靠「换个更小的宽度」过关的人必须先真的把字节做小，而不是把尺子挪开。
    边界是严格大于：正好等于预算算通过（登记值就是给得起的上限，不是「小于等于才算数」的另一个数）。
    """
    hero = int(HERO_INLINE_BUDGET_BYTES if hero_budget_bytes is None else hero_budget_bytes)
    total_cap = int(TOTAL_INLINE_BUDGET_BYTES if total_budget_bytes is None else total_budget_bytes)
    inline = [item for item in (inline_items or []) if item.get("inline")]
    first_screen = [item for item in inline if item.get("on_first_screen")]
    over = [item for item in first_screen if int(item.get("inline_bytes") or 0) > hero]
    total_bytes = sum(int(item.get("inline_bytes") or 0) for item in inline)
    return {"hero_budget_bytes": hero, "total_budget_bytes": total_cap,
            "inline_images": len(inline), "first_screen_count": len(first_screen),
            "first_screen_bytes": sum(int(i.get("inline_bytes") or 0) for i in first_screen),
            "inline_total_bytes": total_bytes,
            "over_budget": [{"name": i.get("name"), "inline_bytes": int(i.get("inline_bytes") or 0)}
                            for i in over],
            "hero_violation": bool(over), "total_violation": total_bytes > total_cap}


def split_over_wide_images(images, cap_px=None, floor_height_px=None):
    """按登记规则把超宽交付图分成「放行」与「仍算缺陷」两堆。

    IMG_TOO_WIDE 的宽度上限（max_delivered_image_width_px）和 min_delivered_geometry 的高度下限
    是同一条交付档的两面：1600×533 的全景源要保住 360px 高度，等比出档就是 1081×360——比槽位声明的
    1000px 宽。prepare_media 按登记的 clamp_rule 钳出这一档，媒体门按同一条款判定；视觉门若仍按裸
    宽度判缺陷，就是在惩罚一张「两侧都照登记办事」的图，并把读者看不到的照片说成是超宽问题。

    放行条件不引入新数字：只有「把宽度收回上限就会让等比高度跌破登记下限」的图才放行——也就是两条
    规则确实无法同时成立的那一类。做得到却没做的超宽（例如 2000×1500 压到 1000 仍有 750px 高）照旧算
    blocking。上限与下限都从 references/single-file-delivery-policy.json 取，本函数不留副本。
    """
    cap_px = int(MAX_DELIVERED_IMG_WIDTH if cap_px is None else cap_px)
    floor_height_px = int(floor_height_px if floor_height_px is not None
                          else single_file_policy.delivered_geometry_floor()[1])
    if cap_px <= 0 or floor_height_px <= 0:
        raise SystemExit("visual_qa 无法判定交付图宽度：登记的上限/几何下限不可用"
                         "（cap=%s floor_height=%s）" % (cap_px, floor_height_px))
    allowed, blocking = [], []
    for item in images:
        width, height = int(item.get("width") or 0), int(item.get("height") or 0)
        if width <= cap_px:
            continue
        scaled_height = height * cap_px / width
        (allowed if scaled_height < floor_height_px else blocking).append(item)
    return allowed, blocking


def _map_query_segments(url: str) -> list[str]:
    """Return the decoded comma-separated segments of a maps URL query string."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return []
    raw = urllib.parse.parse_qs(parsed.query).get("query") or []
    if not raw:
        return []
    return [segment.strip() for segment in urllib.parse.unquote(raw[0]).split(",")]


def check_embedded_map_contract(dataset: dict, failures: list[str], result: dict) -> None:
    """Assert the map contract against the dataset actually shipped inside the HTML.

    Reading the embedded copy (not run/dataset.json) is deliberate: it catches the
    case where the artifact and the sealed input have diverged.
    """
    targets = dataset.get("map_targets") or {}
    if isinstance(targets, list):
        targets = {str(index): item for index, item in enumerate(targets)}
    if not isinstance(targets, dict) or not targets:
        if dataset:
            failures.append("MAP_CONTRACT_MISSING|内嵌 dataset 没有 map_targets，地图链接无法核验")
        result["map_targets"] = 0
        return

    placeholder: list[str] = []
    cjk_urls: list[str] = []
    arrow_urls: list[str] = []
    numeric_city: list[str] = []
    self_referential: int = 0
    unknown_level: list[str] = []
    search_candidate: int = 0
    level_name_mismatch: list[str] = []
    bad_place_ids: list[str] = []
    synthetic_place_ids: int = 0
    real_place_ids: int = 0
    unnamed_no_display: list[str] = []
    unnamed_no_reason: list[str] = []
    google_urls: dict[str, list[str]] = {}
    url_modes: dict[str, set] = {}
    is_demo = bool(dataset.get("demo_mode"))
    # V6-B：读者载荷里「本不该出现」的 provider 字段面。剔除规则由链接合同登记，
    # 这里按同一登记反查——渲染器漏剔、或被别的装配路径绕过去，都在这条上 FAIL，
    # 而不是等字节账变大才发现。denominator 用目标数，不用「字段种类×目标数」这种看起来大、
    # 实际说不清问题的数。
    projection = map_link_selector.reader_payload_projection()
    audit_only_providers = list(projection["audit_only_providers"])
    audit_only_url_fields = ["%s_url" % provider for provider in audit_only_providers]
    leaked_audit_fields: list[str] = []
    # V6-P：过程记录（血缘/欠账/隔离/判决日志/版本戳）按「渲染器读不读」投影。
    # 这里只能证明「读者载荷里没有」；marker 报的行数与审计面是否相符由 delivery_gate 拿
    # dataset 文件对账——那一面才有剔除前的原始行数，在这里对等于让被剔的一方自证。
    process_fields = list(projection["process_record_fields"])
    leaked_process_fields: list[str] = []

    for key, target in targets.items():
        if not isinstance(target, dict):
            continue
        name = str(target.get("canonical_name") or "")
        level = str(target.get("target_level") or "")
        google_url = str(target.get("google_url") or "")
        # V6-B：非渲染 provider 的 URL 字段本该被投影剔干净。名单来自登记，不写死 apple_url——
        # 留着不剔是泄漏，剔了却不让门禁查是第二次自证循环。
        audit_only_urls = [str(target.get(field) or "") for field in audit_only_url_fields]
        for provider in audit_only_providers:
            if provider in (target.get("map_link_by_provider") or {}):
                leaked_audit_fields.append("%s::map_link_by_provider.%s" % (key, provider))
            verdicts = target.get("classifier_verdicts") or {}
            if isinstance(verdicts, dict) and ("%s_url" % provider) in verdicts:
                leaked_audit_fields.append("%s::classifier_verdicts.%s_url" % (key, provider))
            if any(map_link_selector.quarantine_row_attributed(item, provider)
                   for item in (target.get("quarantine") or [])):
                leaked_audit_fields.append("%s::quarantine[%s]" % (key, provider))
        for field in audit_only_url_fields:
            if target.get(field):
                leaked_audit_fields.append("%s::%s" % (key, field))
        for field in process_fields:
            if field in target:
                leaked_process_fields.append("%s::%s" % (key, field))
        source_url = str(target.get("source_url") or "")
        place_id = str(target.get("google_place_id") or target.get("place_id") or "")

        if level == UNNAMED_LEVEL:
            # An empty canonical_name is the correct shape for the coordinate tier
            # (user-confirmed degradation), as long as the reader still sees the real
            # Chinese name and the reason is recorded.
            if not str(target.get("display_name_cn") or "").strip():
                unnamed_no_display.append(key)
            if not str(target.get("unnamed_reason") or "").strip():
                unnamed_no_reason.append(key)
        elif MAP_PLACEHOLDER_SEGMENT_RE.search(name) or not name.strip():
            placeholder.append(f"{key}={name!r}")
        for url in [google_url] + audit_only_urls:
            if not url:
                continue
            # v4.2.2 §4 禁止动作第 2 条（清册 line 102，业主 2026-10-29 登记）：
            # 有来源的本地正式名称允许原样进入搜索串，「URL 解码后含汉字」不再是地图错误。
            # 反删字的牙没放松：解码后每段本地文字必须能在该 target 自己的有来源名称字段里
            # 原样找到；找不到就是删字/截断造出来的残片，仍记 MAP_HREF_CJK。
            decoded_url = urllib.parse.unquote(url)
            sourced_names = " | ".join(filter(None, (
                str(target.get("display_name") or ""), str(target.get("canonical_name") or ""),
                str((target.get("names") or {}).get("cn") or ""),
                str((target.get("names") or {}).get("en") or ""), str(key))))
            unsourced = [chunk for chunk in CJK_RE.findall(decoded_url)
                         if chunk not in sourced_names]
            if unsourced:
                cjk_urls.append(f"{url} :: 无来源本地片段 {unsourced[:2]}")
            if "\u2192" in url:
                arrow_urls.append(url)
        segments = _map_query_segments(google_url)
        numeric_hits = [segment for segment in segments if MAP_NUMERIC_SEGMENT_RE.match(segment)]
        if numeric_hits:
            numeric_city.append(f"{key}: {segments}")
        if source_url and source_url == google_url:
            self_referential += 1
        if level not in CONTRACT_MAP_LEVELS:
            unknown_level.append(f"{key}={level!r}")
        elif level == "search_candidate":
            search_candidate += 1
        if level == "verified_coordinate" and (MAP_PLACEHOLDER_SEGMENT_RE.search(name) or not name.strip()):
            level_name_mismatch.append(f"{key}: level={level} name={name!r}")
        if place_id:
            if SYNTHETIC_PLACE_ID_RE.match(place_id):
                synthetic_place_ids += 1
            elif STRICT_PLACE_ID_RE.match(place_id):
                real_place_ids += 1
            else:
                bad_place_ids.append(f"{key}={place_id[:40]!r}")
        if google_url:
            google_urls.setdefault(google_url, []).append(str(key))
            url_modes.setdefault(google_url, set()).add(
                str((target.get("map_link_by_provider") or {}).get("google", {})
                    .get("link_mode") or target.get("link_mode") or ""))
    duplicate_urls = {url: keys for url, keys in google_urls.items() if len(keys) > 1}

    result["map_targets"] = len(targets)
    result["map_placeholder_targets"] = len(placeholder)
    result["map_real_place_ids"] = real_place_ids
    result["map_synthetic_place_ids"] = synthetic_place_ids
    result["map_duplicate_urls"] = len(duplicate_urls)
    result["map_search_candidates"] = search_candidate
    result["map_unnamed_targets"] = sum(1 for value in targets.values()
                                        if isinstance(value, dict) and value.get("target_level") == UNNAMED_LEVEL)
    result["map_unnamed_no_display"] = unnamed_no_display[:8]
    result["map_reader_payload_leaked_audit_fields"] = len(leaked_audit_fields)
    result["map_reader_payload_audit_only_providers"] = audit_only_providers

    if leaked_audit_fields:
        failures.append(
            f"MAP_READER_PAYLOAD_AUDIT_FIELD_LEAK|{len(leaked_audit_fields)} 处未渲染 provider 的审计"
            f"字段仍在读者载荷里（分母＝这页内嵌的 {len(targets)} 条 map_targets；登记见 "
            f"map-link-selection.json::reader_payload_projection）。读者拿不到那颗按钮，却要下载它的 "
            f"URL/分类判决/隔离记录，源码里还留着一条没人渲染的供应商链接。样例: "
            f"{leaked_audit_fields[:3]}")

    if leaked_process_fields:
        failures.append(
            f"MAP_READER_PAYLOAD_PROCESS_RECORD_LEAK|{len(leaked_process_fields)}/{len(targets)} 处"
            f"过程记录（血缘/欠账/隔离/判决日志/版本戳）仍在读者载荷里。判据是「渲染器读不读」，"
            f"不是「归属哪个 provider」——assets/spa-layout.js 与 split-layout.js 逐字段核过都不读"
            f"（登记见 map-link-selection.json::process_record_fields，业主 2026-10-30 Q1 裁决）。"
            f"样例: {leaked_process_fields[:3]}")
        result["map_process_record_leaks"] = len(leaked_process_fields)

    if placeholder:
        failures.append(
            f"MAP_TARGET_PLACEHOLDER|{len(placeholder)}/{len(targets)} 条 map_targets 的 canonical_name 是占位 venue 名，"
            f"读者点地图会落到'查无此地'。样例: {placeholder[:4]}"
        )
    if cjk_urls:
        failures.append(f"MAP_HREF_CJK|{len(cjk_urls)} 条地图 URL 含**无来源**的本地文字片段"
                        f"（v4.2.2：有来源的本地正式名称允许原样进串，删字/截断残片仍然违规）。"
                        f"样例: {cjk_urls[:2][:1]}")
    if arrow_urls:
        failures.append(f"MAP_HREF_ARROW|{len(arrow_urls)} 条地图 URL 未编码 '→'，会被 Google 当作查询词。样例: {arrow_urls[:1]}")
    if numeric_city:
        failures.append(f"MAP_HREF_NUMERIC_CITY|{len(numeric_city)} 条地图查询串把公里数当城市名。样例: {numeric_city[:3]}")
    if duplicate_urls:
        # v4.2.2 V6-T2（Checklist line 174 是权威：「未得到者逐项列出，但不以必须唯一实体卡片阻断」）：
        # NAMED_SEARCH 的搜索串本来就只表示"执行这次搜索"，不承诺落点唯一（line 77），所以两个邻近
        # POI 共用一条搜索串是诚实形态，不是缺陷——把它判 FAIL 会逼着实现方编造更窄的名字。
        # 仍然阻断的是：同一 href 被当作 PUBLISHER_ENTITY_LINK 发给两个不同目标（那是在宣布
        # "同一个已核验实体"，两行不可能同时为真）。共用数量无论是否阻断都进报告分母。
        entity_shared = {url: keys for url, keys in duplicate_urls.items()
                         if "PUBLISHER_ENTITY_LINK" in (url_modes.get(url) or set())}
        result["map_duplicate_named_search_hrefs"] = len(duplicate_urls) - len(entity_shared)
        if entity_shared:
            failures.append(
                f"MAP_HREF_DUPLICATE|{len(entity_shared)} 条实体直达 href 被多个不同 POI 共用"
                f"（PUBLISHER_ENTITY_LINK 宣布的是同一个已核验实体，两行不可能同时为真）: "
                f"{list(entity_shared.items())[:2]}")
    if self_referential:
        failures.append(f"MAP_SOURCE_SELFREFERENTIAL|{self_referential} 条 source_url 与 google_url 完全相同（自证循环，不构成外部证据）")
    if unknown_level:
        failures.append(f"MAP_LEVEL_UNKNOWN|{len(unknown_level)} 条 target_level 不在契约枚举内: {unknown_level[:3]}")
    # v4.2.2 V6-T 撤回（Checklist line 44/151/175 是权威）：合同要求「没有可信实体直达链接但
    # 名称可用时，提供『在 Google Maps 搜索此地点（落点未核验）』入口」，也要求所有 NAMED_SEARCH
    # 使用搜索文案。原来的这条 MAP_LEVEL_SEARCH_CANDIDATE 把「渲染了按钮」本身当成缺陷，与合同
    # 直接冲突——它会把唯一正确的诚实实现判成 FAIL（V6-D 端到端实测：CA 198 条 / PH 87 条被误判）。
    # 按钮文案与档位的真正牙齿在 scripts/map_gate_v422.py::GATE_DOM_COPY_DIFFERS /
    # GATE_DOM_LINK_MODE_DIFFERS：DOM 文案必须逐字等于该档位登记的文案，写错一个字就 FAIL。
    # 计数仍留在 result["map_search_candidates"]（上面已写），这里不再判失败；
    # 在视觉 QA 里再实现一遍同一规则，就是 §9 禁止的第二套规则。
    if level_name_mismatch:
        failures.append(
            f"MAP_LEVEL_NAME_MISMATCH|{len(level_name_mismatch)} 条标为 verified_coordinate 却带占位名"
            f"（契约阈值只问坐标档位、不问名字，故'合规但死路'）: {level_name_mismatch[:3]}"
        )
    if unnamed_no_display:
        errors_placeholder = (f"MAP_UNNAMED_NO_DISPLAY|{len(unnamed_no_display)} 条坐标档没有 display_name_cn，"
                              f"读者会看到空白卡片: {unnamed_no_display[:4]}")
        failures.append(errors_placeholder)
    if unnamed_no_reason:
        failures.append(f"MAP_UNNAMED_NO_REASON|{len(unnamed_no_reason)} 条 unnamed_coordinate 未记录降级原因"
                        f"（降级必须是显式决定，不能是默认值）: {unnamed_no_reason[:4]}")
    if bad_place_ids:
        failures.append(f"MAP_PLACE_ID_SHAPE|{len(bad_place_ids)} 条 google_place_id 不符合 ChIJ 真实形状: {bad_place_ids[:3]}")
    if synthetic_place_ids:
        failures.append(f"MAP_PLACE_ID_SYNTHETIC|{synthetic_place_ids} 条 google_place_id 是 ChIJ_ 人工 slug，不是供应商返回")


def check_embedded_image_supply(page, failures: list[str], result: dict, dataset: dict | None = None) -> None:
    """§12: per-device image supply and first-screen budget, measured in the browser."""
    images = page.evaluate("""() => [...document.querySelectorAll('img')].map(i => {
      const attr = i.getAttribute('src') || '';
      const isInline = /^data:/i.test(attr);
      const base = (i.currentSrc || i.src || attr);
      const rect = i.getBoundingClientRect();
      const name = isInline
        ? 'inline:' + ((attr.match(/^data:image\\/([+\\w.-]+)/) || [, 'unknown'])[1]) + ':' + Math.round(attr.length * 0.75 / 1024) + 'KB'
        : base.split('/').pop().split('?')[0];
      return {
        name: name,
        src: base.slice(0, 200),
        width: i.naturalWidth,
        height: i.naturalHeight,
        complete: i.complete,
        srcset: !!i.getAttribute('srcset'),
        sizes: !!i.getAttribute('sizes'),
        inline: isInline,
        on_first_screen: rect.top < window.innerHeight && rect.bottom > 0 && rect.width > 0,
        inline_bytes: isInline ? Math.round(attr.length * 0.75) : 0
      };
    })""")
    total = len(images)
    with_srcset = sum(1 for item in images if item["srcset"])
    # 超宽放行 / 仍算缺陷的分档只在 split_over_wide_images 里实现一次，判定用的是登记值本身。
    _, floor_height = single_file_policy.delivered_geometry_floor()
    clamped_wide, oversized = split_over_wide_images(images)
    broken = [item for item in images if item["complete"] and item["width"] == 0]
    inline_all = [item for item in images if item["inline"]]
    # "first screen" is what the reader's phone must decode before the first card paints, not every
    # picture in the file. v4.2.1 charged a 13-image / 1535KB bill to images three panels down.
    # 预算判定只在 inline_budget_verdict 里做一次；这里不再自己写 `> HERO_INLINE_BUDGET_BYTES`，
    # 否则边界测试测的是另一把尺子，真页面用的又是第二把。
    budget = inline_budget_verdict(inline_all)
    inline_bytes_total = budget["inline_total_bytes"]
    first_screen_count = budget["first_screen_count"]
    inline_over = budget["over_budget"]

    result["images_in_dom"] = total
    result["images_with_srcset"] = with_srcset
    result["images_oversized"] = [{"name": item["name"], "width": item["width"]} for item in oversized[:8]]
    result["images_wide_by_geometry_clamp"] = [
        {"name": item["name"], "width": item["width"], "height": item["height"]}
        for item in clamped_wide[:8]]
    result["images_inline_total_bytes"] = inline_bytes_total
    result["images_inline_first_screen"] = first_screen_count
    result["images_inline_first_screen_bytes"] = budget["first_screen_bytes"]
    result["images_inline_over_budget_bytes"] = sum(item["inline_bytes"] for item in inline_over)
    result["hero_inline_budget_bytes"] = budget["hero_budget_bytes"]
    result["total_inline_budget_bytes"] = budget["total_budget_bytes"]

    # Slot-aware: a cover that only declares one tier cannot be blamed for lacking srcset.
    declared = list((dataset or {}).get("editorial_media") or []) + \
        list((dataset or {}).get("section_media") or [])
    multi_slot = sum(1 for m in declared if isinstance(m, dict) and len(m.get("image_srcset") or []) > 1)
    if len((dataset or {}).get("hero_srcset") or []) > 1:
        multi_slot += 1
    result["images_multi_tier_declared"] = multi_slot
    result["images_multi_tier_with_srcset"] = with_srcset
    # An all-inline page cannot gain from srcset: every candidate is already inside the file, so a
    # two-tier slot means the reader carries two renditions of one picture and the browser still
    # downloads both. Demand srcset only when the bytes are actually fetched as files.
    is_inline_delivery = total > 0 and len(inline_all) == total
    result["media_delivery_inline"] = is_inline_delivery
    if is_inline_delivery:
        if multi_slot:
            failures.append(
                f"IMG_INLINE_MULTI_TIER|{multi_slot} 个槽位内联了多档 rendition：单文件里 srcset "
                f"省不下任何字节，反而把同一张图的两份字节都塞给读者")
    else:
        if total and with_srcset == 0 and not multi_slot:
            failures.append(f"IMG_SRCSET_ABSENT|{total} 张在屏图片 0 张带 srcset/sizes，"
                            f"且清单没有声明任何多档 rendition，手机版仍在下载桌面尺寸")
        # Not an equality check: only some dataset entries are on screen at once (the carousel shows
        # a few per route), so a lower count is normal. Zero is the failure that matters — it means
        # the tier list was built and then thrown away between the manifest and the img tag.
        if multi_slot and with_srcset == 0:
            failures.append(
                f"IMG_SRCSET_INCOMPLETE|{multi_slot} 个槽位声明了多档 rendition，页面里 0 个 img 带 "
                f"srcset/sizes，手机版仍只能取最大档"
            )
    if oversized:
        failures.append(
            f"IMG_TOO_WIDE|{len(oversized)}/{total} 张交付图宽度 > {MAX_DELIVERED_IMG_WIDTH}px，"
            f"且它们并非几何钳制的产物（压回 {MAX_DELIVERED_IMG_WIDTH}px 后高度仍在登记的 "
            f"{floor_height}px 下限之上，说明本可以出更小的档）: "
            f"{[item['name'] for item in oversized[:4]]}"
        )
    if inline_over:
        failures.append(
            f"IMG_INLINE_OVER_BUDGET|首屏 {len(inline_over)} 张内联图超过 {budget['hero_budget_bytes'] // 1024}KB "
            f"预算（合计 {sum(item['inline_bytes'] for item in inline_over) // 1024}KB），"
            f"手机端首屏必须先解码它: {[item['name'] for item in inline_over[:4]]}"
        )
    if budget["total_violation"]:
        failures.append(
            f"IMG_INLINE_TOTAL_OVER_BUDGET|页面内联图片合计 {inline_bytes_total // 1024 // 1024}MB "
            f"超过 {budget['total_budget_bytes'] // 1048576}MB 单文件预算，"
            f"读者要用蜂窝网络整页下载后才能开始阅读")
    if broken:
        failures.append(f"IMG_BROKEN|{len(broken)} 张已渲染图片解码失败: {[item['name'] for item in broken[:4]]}")


IMAGE_REGISTRATION_JS = """() => [...document.querySelectorAll('img')].map(i => {
  const attr = i.getAttribute('src') || '';
  const kind = /^data:/i.test(attr) ? 'inline'
             : /^asset:\\/\\/sha256:/i.test(attr) ? 'ref'
             : attr ? 'file' : 'empty';
  return {digest: i.dataset.assetDigest || '',
          srcKind: kind,
          attrHead: attr.slice(0, 48),
          alt: (i.alt || '').slice(0, 40),
          fallback: i.dataset.fallbackFired === '1',
          painted: !!i.complete && i.naturalWidth > 0,
          slot: (() => { const host = i.closest('[class]'); return host ? '.' + String(host.className).trim().split(/\\s+/)[0] : ''; })()};
})"""


NO_PHOTO_STATE_DOM_JS = """() => [...document.querySelectorAll('[data-media-state]')].map(e => {
  const img = e.querySelector('img');
  return {state: e.getAttribute('data-media-state') || '',
          // textContent 而不是 innerText：槽位可能坐在收起的 <details> 里，innerText 会把隐藏
          // 文案读成空串，那样「页面上写着暂无已核验图片」这条判据就会假红。
          text: (e.textContent || '').trim(),
          imgCount: e.querySelectorAll('img').length,
          assetRef: /asset:\\/\\/|data:image/.test(e.innerHTML),
          fallback: !!e.querySelector('img[data-fallback-fired], img[data-asset-digest="fallback"]'),
          destination: (() => { const host = e.closest('[data-destination]');
                                return host ? (host.getAttribute('data-destination') || '') : ''; })()};
})"""


def check_rendered_image_registration(page, dataset: dict, manifest: dict | None,
                                      failures: list[str], result: dict, *,
                                      manifest_required: bool) -> None:
    """V5-D（V0-L12）：读者页真正画出来的每张图，都必须能回指到登记过的字节。

    v4.2.1 记的是「页面渲染但清单未登记的图 2 张」——那时候只能靠事后翻 HTML 文本发现。
    现在渲染层给每张 <img> 打上 data-asset-digest（asset:// 引用或 blob 反查得到），
    本函数把它与 asset-manifest 的登记摘要对表：登记规则仍归 local_media_gate，
    这里不重算摘要链，只问「画出来的这张有没有身份」。
    """
    rows = page.evaluate(IMAGE_REGISTRATION_JS)
    if manifest is None:
        result["image_registration"] = {
            "enforced": False, "reason": "MANIFEST_ABSENT",
            "dom_images": len(rows),
            "dom_inline": sum(1 for r in rows if r["srcKind"] == "inline"),
            "dom_file_refs": sum(1 for r in rows if r["srcKind"] == "file"),
            "dom_fallbacks": sum(1 for r in rows if r["fallback"]),
        }
        if manifest_required:
            failures.append(
                "IMG_MANIFEST_ABSENT|读者页要逐张对账图片身份，但这次运行没有可用的 "
                "asset-manifest.json：没检查不等于通过（§10）")
        return
    claims = local_media_gate.manifest_claim_map(manifest)
    painted_digests = {r["digest"] for r in rows if r["digest"] not in ("", "none", "fallback")}
    unregistered = [r for r in rows if re.fullmatch(r"[0-9a-f]{64}", r["digest"] or "")
                    and r["digest"] not in claims]
    file_refs = [r for r in rows if r["srcKind"] in ("file", "empty")]
    blobs_without_blob = [r for r in rows if r["srcKind"] == "inline" and r["digest"] in ("", "none")]
    placeholders = [r for r in rows if r["fallback"] or r["digest"] == "fallback"]
    slots = [item for item in list(dataset.get("section_media") or [])
             + list(dataset.get("editorial_media") or []) if isinstance(item, dict)]
    # R3B（业主 2026-11-03）：正式无图槽位不是「空槽位」。以前 image 为空就一起进
    # IMG_DATASET_SLOT_EMPTY（advisory，读者偶然少一张图），现在它换了一种要逐槽位核对的
    # 状态：数据层声明无图 ⇒ DOM 必须带登记属性、必须显示登记文案、必须没有图。
    no_photo_rows = [item for item in slots if local_media_gate.is_no_photo_row(item)]
    empty_slots = [str(item.get("destination") or item.get("title") or "") for item in slots
                   if not str(item.get("image") or "").strip()
                   and not local_media_gate.is_no_photo_row(item)]
    no_photo_contract = local_media_gate.no_photo_policy()["dom"]
    no_photo_dom = page.evaluate(NO_PHOTO_STATE_DOM_JS)
    no_photo_marks = [row for row in no_photo_dom
                      if row.get("state") == no_photo_contract["attribute_value"]]
    label_cn = str((no_photo_contract.get("visible_label") or {}).get("cn") or "")
    missing_marks = len(no_photo_rows) - len(no_photo_marks)
    unlabelled = [row for row in no_photo_marks if label_cn not in str(row.get("text") or "")]
    with_image = [row for row in no_photo_marks
                  if row.get("imgCount") or row.get("assetRef") or row.get("fallback")]
    no_photo_findings: list[str] = []      # findings 表在下面才建；这里先攒，建好再并进去
    result["designed_no_photo_state"] = {
        "declared_slots": [["%s" % (row.get("destination") or ""), str(row.get("primary_module") or "")]
                           for row in no_photo_rows],
        "dom_marked": len(no_photo_marks),
        "dom_marked_without_label": len(unlabelled),
        "dom_marked_with_image": len(with_image),
        "attribute": no_photo_contract["attribute"],
        "label_required": label_cn,
        "section_slot_total": len(dataset.get("section_media") or []),
        "photographic_slots": sum(1 for row in (dataset.get("section_media") or [])
                                  if isinstance(row, dict) and str(row.get("image") or "").strip()),
    }
    if missing_marks > 0:
        no_photo_findings.append(
            f"IMG_RENDERED_NO_PHOTO_SLOT_UNMARKED|dataset 声明 {len(no_photo_rows)} 个正式无图槽位，"
            f"读者页只有 {len(no_photo_marks)} 个带 {no_photo_contract['attribute']}="
            f"{no_photo_contract['attribute_value']}：无图状态没落到 DOM，读者看到的是偶然少图")
    elif len(no_photo_marks) > len(no_photo_rows):
        no_photo_findings.append(
            f"IMG_RENDERED_NO_PHOTO_STATE_MISMATCH|DOM 里 {len(no_photo_marks)} 处声明无图，"
            f"dataset 只登记 {len(no_photo_rows)} 个无图槽位⇒ 页面上多出来的「无图」没有数据层依据")
    if with_image:
        no_photo_findings.append(
            f"IMG_RENDERED_NO_PHOTO_HAS_IMAGE|{len(with_image)} 个声明无图的槽位里仍画出了图片字节"
            f"（img 或 asset:// ／内联字节）：无图状态不能同时是一张图，也不能用别的地点或生成的图填")
    if unlabelled:
        no_photo_findings.append(
            f"IMG_RENDERED_NO_PHOTO_LABEL_MISSING|{len(unlabelled)} 个无图槽位没有显示登记文案"
            f"「{label_cn}」⇒ 缺图必须说清楚，不能表现成图片加载失败")
    manifest_files = sorted({str(e.get("local_file") or "") for e in manifest.get("assets") or []
                             if str(e.get("local_file") or "").strip()})
    # 「登记了却没画」的判定不能用文件名去撞内联字节：全内联交付里根本没有文件名出现在 DOM。
    # 一条登记算作已画，当且仅当它的某个登记摘要出现在这页画出的 digest 里，
    # 或它的文件就是某个 file-ref 的 src。
    painted_files = {str(claims.get(digest) or "").split("#", 1)[0] for digest in painted_digests}
    src_files = {r["attrHead"].rsplit("/", 1)[-1] for r in file_refs}
    never_painted = sorted(name for name in manifest_files
                           if name not in painted_files
                           and name.rsplit("/", 1)[-1] not in src_files)

    inline_real = [r for r in rows if r["srcKind"] == "inline"
                   and r["digest"] != "fallback" and not r["fallback"]]
    result["image_registration"] = {
        "enforced": True,
        "dom_images": len(rows),
        # 兜底 SVG 的 src 也是 data:，不能算进「文件内图片字节」——它是生成的假封面，不是那张图。
        "dom_inline": len(inline_real),
        "dom_refs": sum(1 for r in rows if r["srcKind"] == "ref"),
        "dom_file_refs": len(file_refs),
        "dom_fallbacks": len(placeholders),
        "painted_digests": len(painted_digests),
        "painted_rows": sum(1 for r in rows if re.fullmatch(r"[0-9a-f]{64}", r["digest"] or "")),
        "manifest_entries": len(manifest.get("assets") or []),
        "manifest_claims": len(claims),
        "unregistered": [{"digest": r["digest"][:12], "alt": r["alt"], "slot": r["slot"]}
                         for r in unregistered[:8]],
        "unregistered_count": len(unregistered),
        "file_ref_samples": [r["attrHead"] for r in file_refs[:8]],
        "inline_without_blob": [{"alt": r["alt"], "head": r["attrHead"]} for r in blobs_without_blob[:6]],
        "empty_dataset_slots": empty_slots[:8],
        "manifest_rows_not_painted": never_painted[:8],
    }
    findings: list[str] = list(no_photo_findings)   # R3B：无图状态的 DOM 判据先并入，别让它攒在局部变量里蒸发
    if unregistered:
        findings.append(
            f"IMG_RENDERED_UNREGISTERED|读者页画出 {len(unregistered)}/{len(rows)} 张图，其字节身份"
            f"（data-asset-digest）不在 asset-manifest 的登记摘要里：等于向读者投放未登记来源的图。"
            f"样例: {[r['digest'][:12] for r in unregistered[:4]]}")
    if file_refs:
        findings.append(
            f"IMG_RENDERED_EXTERNAL_REF|读者页有 {len(file_refs)}/{len(rows)} 张图的 src 指向文件而非文件内字节，"
            f"单独发送这一个 HTML 时读者看不到图（自包含失效）: {[r['attrHead'] for r in file_refs[:3]]}")
    if blobs_without_blob:
        findings.append(
            f"IMG_RENDERED_NO_FILE_BLOB|{len(blobs_without_blob)} 张内联图在 D.asset_blobs 里没有对应条目，"
            f"字节是渲染期临时贴上去的，摘要链无法对账: {[r['head'][:24] for r in blobs_without_blob[:3]]}")
    if placeholders:
        findings.append(
            f"IMG_RENDERED_FALLBACK_PLACEHOLDER|{len(placeholders)} 张图加载失败后落到 JS 生成的占位 SVG，"
            f"读者看到的是画出来的假封面而不是缺图提示: {[r['alt'] for r in placeholders[:3]]}")
    if never_painted:
        findings.append(
            f"IMG_MANIFEST_NOT_RENDERED|asset-manifest 登记了 {len(never_painted)}/{len(manifest_files)} 个文件，"
            f"读者页这一页一张都没画：要么是死登记（清单说交付了、读者拿不到），要么槽位被裁掉，需说明: "
            f"{[name.rsplit('/', 1)[-1] for name in never_painted[:4]]}")
    if empty_slots:
        findings.append(
            f"IMG_DATASET_SLOT_EMPTY|dataset 里 {len(empty_slots)}/{len(slots)} 个图文槽位的 image 是空的，"
            f"读者在该位置只会看到文字: {empty_slots[:4]}")
    blocking, advisory = single_file_policy.split_findings(findings, SINGLE_FILE_POLICY)
    failures.extend(blocking)
    # advisory 也要留痕：它进报告但不进 failures，否则『不挡交付』会被 status=FAIL 变成挡交付。
    result["image_registration"]["advisory_findings"] = advisory


def check_map_dom_dataset_consistency(page, dataset: dict, failures: list[str],
                                      result: dict) -> None:
    """v4.2.2 §8.1「dataset/DOM/href/link mode 不一致 = 0」的执行期那一条。

    浏览器只负责把读者真正看到的 href / data-* / 可见文案取回来，比对全部交给
    `map_gate_v422.dom_findings`——本文件不持有 provider 主机名单或路径正则（§9 禁止第二套规则）。
    只对声明了本版血缘的 dataset 行使强制力：v4.2.1 的历史产物没有 selection_version，
    用本版规则判它们只会制造噪声（同 V4-A 的适用性开关）。
    """
    targets = dataset.get("map_targets") or {}
    if not isinstance(targets, dict) or not targets:
        result["map_dom_dataset_consistency"] = {"enforced": False, "reason": "NO_MAP_TARGETS"}
        return
    selection = json.loads((RELEASE_ROOT / "references" / "map-link-selection.json")
                           .read_text(encoding="utf-8"))
    gate = map_gate_v422.load_gate()
    # 血缘缺失/版本错在正式 run 里是阻断项，不再只是「不适用」（业主 V6-R §2）。
    provenance = map_gate_v422.provenance_findings(dataset, selection, gate)
    applicability = map_gate_v422.applicability(dataset, selection)
    if not applicability["enforced"]:
        result["map_dom_dataset_consistency"] = {"enforced": False,
                                                 "reason": applicability["reason"],
                                                 "formal_run": map_gate_v422.is_formal_run(gate),
                                                 "provenance_findings": provenance[:4]}
        failures.extend(provenance)
        return
    rows = page.evaluate(MAP_DOM_ROWS_JS)
    country = str(dataset.get("country") or "")
    alias_by_id, _alias_findings = map_gate_v422.resolve_aliases(targets, gate, selection, country)
    findings = map_gate_v422.dom_findings(targets, rows, gate, selection, country)
    result["map_dom_dataset_consistency"] = {"enforced": True, "dom_rows": len(rows),
                                             "dataset_rows": len(targets),
                                             "registered_aliases": len(alias_by_id),
                                             "expected_buttons": len(
                                                 map_gate_v422.expected_dom_links(
                                                     targets, selection, alias_by_id)),
                                             "findings": findings[:8],
                                             "findings_total": len(findings)}
    failures.extend(findings)


# v4.2.2 V5-B：汇率状态在 DOM 上的可观测形状（textContent 不受面板显隐影响）。
BUDGET_FX_JS = r'''() => {
  const strip = document.querySelector('[data-rate-state]');
  const note = document.querySelector('.rate-note');
  const panel = document.getElementById('panel-budget');
  const nodes = panel ? [...panel.querySelectorAll('.bs-num b, .dc-split b, .budget-strip b')] : [];
  return {state: strip ? (strip.dataset.rateState || '') : '',
          note: note ? note.textContent.trim() : '',
          money: nodes.map(n => n.textContent.trim()).filter(Boolean)};
}'''


def check_budget_rate_state(page, dataset: dict, failures: list[str], result: dict,
                            phase: str) -> None:
    """v4.2.2 V5-B（V0-L05）：读者看到的金额币种必须与登记状态一致，由 DOM 实测。

    旧版在这里没有检查——因为旧版 JS 写死了 `return 7.15`，任何 run 都会显示 `$` 金额，
    「有没有登记汇率」这个问题在页面上根本不可见。现在状态挂在 `[data-rate-state]` 上，
    本函数把它和 `budget_contract.reader_projection()` 的复算结果对账：
    状态不符、未登记却出现 `$` 金额、未登记却不说明原因，三种都是 failure。
    """
    projection = budget_contract.reader_projection(dataset.get("budget_meta") or {})
    dom = page.evaluate(BUDGET_FX_JS)
    entry = {"phase": phase, "registered_status": projection["rate_status"],
             "dom_state": dom.get("state"), "declined_codes": projection["declined_codes"],
             "usd_amounts": 0}
    if dom.get("state") == "STATUS_MISSING" and dataset.get("budget_fx") is None:
        # 读者载荷里根本没有投影：JS 只能猜，而猜出来的金额看起来和登记过的一模一样。
        failures.append("FX_READER_PROJECTION_MISSING|读者载荷没有 budget_fx 投影（渲染层没有下发登记状态）")
        result["budget_fx_%s" % phase] = entry
        return
    if dom.get("state") != projection["rate_status"]:
        failures.append("FX_RATE_STATE_DOM_DIFFERS|页面标 %r，登记复算是 %r（渲染层与登记处各写了一套）"
                        % (dom.get("state"), projection["rate_status"]))
    amounts = [text for text in (dom.get("money") or []) if isinstance(text, str)]
    usd = [text for text in amounts if text.strip().startswith("$")]
    entry["usd_amounts"] = len(usd)
    entry["cny_amounts"] = len([text for text in amounts if text.strip().startswith("¥")])
    if projection["rate_status"] != "VERIFIED":
        notice = (projection["notice_unregistered"]["en"] if phase == "en"
                  else projection["notice_unregistered"]["cn"])
        if dom.get("state") != "STATUS_MISSING" and notice not in (dom.get("note") or ""):
            failures.append("FX_UNREGISTERED_NOTICE_MISSING|未登记汇率却没有向读者说明：%r"
                            % (dom.get("note") or "")[:80])
        if usd:
            failures.append("FX_FABRICATED_CONVERSION|汇率未登记却仍显示换算金额（§10/V0-L05）：%s"
                            % ", ".join(usd[:4]))
    elif phase == "en" and not usd and amounts:
        # 只在英文态要求「登记了就应当换算」：中文态本来就按人民币显示，没有 $ 不是缺陷。
        failures.append("FX_VERIFIED_BUT_NOT_CONVERTED|已登记带来源的汇率，英文态却没有任何换算金额：%s"
                        % ", ".join(amounts[:4]))
    result["budget_fx_%s" % phase] = entry


def registered_reader_face() -> str:
    """运行 dataset 的读者来源面键名：唯一登记处 references/data-model.json。

    按字节读（同 scripts/source_projection.py::registry）：负样本测试会全局 patch
    Path.read_text，判定表若在那种环境里重新读盘就会假报「配置缺失」。
    """
    model = json.loads((Path(__file__).resolve().parents[1] / "references" / "data-model.json")
                       .read_bytes().decode("utf-8"))
    face = str(model.get("source_evidence_reader_face") or "").strip()
    if not face:
        raise ValueError("references/data-model.json::source_evidence_reader_face 未登记"
                         "⇒ 读者来源面没有唯一来源，门禁不许自己猜一个键")
    return face


def _stat_int(value) -> "int | None":
    """把面板上印出来的统计数字取回来：浏览器用 toLocaleString，千位分隔符不是数字的一部分。"""
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return int(digits) if digits else None


def check_reader_language_profile(page, dataset: dict, failures: list[str], result: dict) -> dict:
    """档位是构建期登记事实（合同 reader_language），页面必须自己说清楚是哪一档。

    三条独立判据，各自一个错误码：没声明（meta 缺失或载荷没有 reader_profile）、
    声明与载荷不一致、声明了未登记的档位。缺任何一项都等于「这页不知道该被哪套门检查」，
    而双语 HTML 换个标签就发布（ZH-RELEASE-1 明令禁止的形状）正是从这一步漏出去的。
    """
    contract = spa_renderer.reader_language_contract()
    meta_name = str(contract.get("html_meta_name") or "")
    profiles = contract.get("profiles") or {}
    formal = str(contract.get("formal_profile") or "")
    declared = page.evaluate(
        "(name) => document.head.querySelector(`meta[name='${name}']`)?.content || ''",
        meta_name) if meta_name else ""
    payload = str(dataset.get("reader_profile") or "")
    state = {"meta_declared": declared, "payload_declared": payload,
             "formal_profile": formal, "is_formal": False,
             "registered_profiles": sorted(profiles)}
    result["reader_profile"] = state
    if not declared or not payload:
        failures.append(
            "SPA_READER_PROFILE_UNDECLARED|页面 meta[%s]=%r、读者载荷 reader_profile=%r："
            "每一份构建产物都必须自己声明语言档位（合同 reader_language.profiles_declare_self），"
            "没声明的页面无法判定它该按正式档还是候审档检查"
            % (meta_name, declared, payload))
        return state
    if declared != payload:
        failures.append(
            "SPA_READER_PROFILE_MISMATCH|页面 meta 声明 %r，读者载荷 reader_profile 是 %r："
            "同一个页面的两个自我声明各执一词，门禁不按任何一套放行" % (declared, payload))
        return state
    if declared not in profiles:
        failures.append(
            "SPA_READER_PROFILE_UNREGISTERED|声明的档位 %r 不在注册表 renderer-contract.json"
            "::reader_language.profiles（已登记：%s）；未登记的档位等于没有合同"
            % (declared, sorted(profiles)))
        return state
    state["is_formal"] = declared == formal
    state["spec"] = profiles[declared]
    state["reader_toggle"] = bool((profiles[declared] or {}).get("reader_toggle"))
    result["reader_profile_state"] = declared
    return state


def check_zh_formal_page(page, dataset: dict, failures: list[str], result: dict) -> dict:
    """正式档（注册的 formal_profile）的功能层面证据：不是把双语页面换个标签。

    判据全部来自 renderer-contract.json::reader_language.profiles[formal].gate_obligations，
    本文件不新增词汇：切换入口必须是**元素不存在**（DOM 零命中，CSS 隐藏不算删除），
    excluded_payload_keys 必须在读者载荷里零命中。
    """
    spec = spa_renderer.reader_profile_spec(spa_renderer.formal_reader_profile())
    toggle = page.locator("#lang-btn").count()
    excluded = [str(key) for key in (spec.get("excluded_payload_keys") or [])]
    hits = sorted(key for key in excluded if key in dataset)
    entry = {"lang_btn_count": toggle, "excluded_payload_keys": excluded,
             "excluded_key_hits": hits,
             "english_mode_walk": False}
    result["zh_formal"] = entry
    # 载荷范围的反向核对用唯一实现（scripts/reader_payload_scope.py）：
    # 声明 zh_only 却仍带嵌套英文 / 带未登记顶层键，都算「换个标签就发布」。
    scope_check = reader_payload_scope.assert_scope_declared(dataset, spa_renderer.formal_reader_profile())
    entry["payload_scope"] = scope_check
    if not scope_check["ok"]:
        failures.append(
            "SPA_ZH_FORMAL_PAYLOAD_SCOPE_WRONG|正式档载荷的语言范围自证不合：%s；判据来自 "
            "renderer-contract.json::reader_language.profiles[zh-formal].payload_scope"
            "（declared_scope_value=%r），实现只有一份（scripts/reader_payload_scope.py）"
            % ("; ".join(scope_check["problems"]),
               reader_payload_scope.SCOPE_VALUE))
    if toggle:
        failures.append(
            "SPA_ZH_FORMAL_TOGGLE_PRESENT|正式档 DOM 里仍有 %d 个 #lang-btn：语言档位是构建期登记"
            "事实、不是读者可选功能，切换入口必须删掉元素（合同禁止以 CSS 隐藏代替删除），"
            "留着入口就等于把候审英文发出去" % toggle)
    if hits:
        failures.append(
            "SPA_ZH_FORMAL_EXCLUDED_PAYLOAD_KEY_PRESENT|正式档读者载荷仍带 %d 个候审英文显示面键"
            "：%s；这些键是 renderer-contract.json::reader_language.profiles[zh-formal]"
            ".excluded_payload_keys 登记要剔除的，功能层面没剔除就是换标签发布"
            % (len(hits), hits))
    return entry


SOURCE_PANEL_JS = r'''() => {
  const root = document.querySelector('[data-module="source_evidence"]');
  if (!root) return {present: false};
  const rows = [...root.querySelectorAll('.se-row')];
  const num = (el) => (el ? (el.textContent || '').trim() : null);
  const stats = {};
  for (const el of root.querySelectorAll('[data-se-count]')) {
    stats[el.getAttribute('data-se-count')] = num(el);
  }
  const groups = [...root.querySelectorAll('.source-groups > details')].map((det) => ({
    label: num(det.querySelector('summary b')),
    summary_text: num(det.querySelector('summary small')),
    rows: det.querySelectorAll('.se-row').length,
    indices: [...det.querySelectorAll('.se-row')].map((r) => r.getAttribute('data-se-index')),
    uids: [...det.querySelectorAll('.se-row')].map((r) => r.getAttribute('data-se-uid')),
  }));
  return {present: true,
          ledger_status: root.getAttribute('data-se-ledger-status'),
          declared_rows: root.getAttribute('data-se-rows'),
          dom_rows: rows.length, stats, groups,
          indices: rows.map((r) => r.getAttribute('data-se-index')),
          uids: rows.map((r) => r.getAttribute('data-se-uid'))};
}'''


def check_source_panel(page, dataset: dict, failures: list[str], result: dict, *,
                       profile_state: dict, run_dataset: dict | None = None) -> dict:
    """来源面板三段对账：dataset → 投影 → DOM，口径只有 scripts/source_projection.py 一份。

    这一项存在的原因是 #113：面板曾经读十列位置面、又叠了 items.slice(0,15)＋「… N more」
    的死胡同，CA 174 条、PH 365 条来源记录在读者页面上根本不存在，统计还印成「0 verified」。
    「没渲染」与「没有这条记录」必须是两件事，所以这里量的是**数量恒等**与**逐行身份**，
    不是「有没有内容」。
    """
    formal = bool(profile_state.get("is_formal"))
    payload_rows = dataset.get("source_records")
    if not isinstance(payload_rows, list):
        payload_rows = []
    ledger_status = str(dataset.get("source_ledger_status") or "absent")
    dom = page.evaluate(SOURCE_PANEL_JS)
    measured = source_projection.counts(payload_rows)
    verified = measured["by_status"].get("verified", 0)
    face_key = None
    dataset_rows: "int | None" = None
    face_error = ""
    try:
        face_key = registered_reader_face()
    except ValueError as exc:
        face_error = str(exc)
    if isinstance(run_dataset, dict) and face_key is not None:
        face_rows = run_dataset.get(face_key)
        dataset_rows = len(face_rows) if isinstance(face_rows, list) else None
    else:
        face_rows = None
    # ZH-RELEASE-2 步1（业主 2026-11-03 裁 finding_1）：产物自己声明「这张台账是从哪份输入字节
    # 装配来的」。这里只做实测：自证存在但与现面不合就报码；自证**整块缺失**留给交付门判定
    # （缺输入字节的直调产物本来就只有 smoke 身份，不该由浏览器门替合同加规则）。
    declared_provenance = dataset.get("source_ledger_meta")
    provenance_problems: list[dict] = []
    provenance_check = "dataset_face_unavailable"
    if isinstance(face_rows, list):
        provenance_check = "ran"
        provenance_problems = [{"code": code, "detail": detail[:180]} for code, detail in
                               source_projection.provenance_problems(declared_provenance, face_rows)]
    if declared_provenance is not None and provenance_problems:
        failures.append(
            "SPA_SOURCE_PROVENANCE_WRONG|产物声明的来源台账血缘与运行 dataset 的机器面对不上：%s"
            "（自证=%r，dataset 机器面=%d 行；口径 source_projection.provenance_problems，"
            "正式链 input dataset→canonical_dataset→source_projection→source_records→DOM 在这一环断了）"
            % (";".join(item["code"] for item in provenance_problems),
               declared_provenance, len(face_rows)))
    reconciliation = source_projection.reconcile(
        dataset_rows=(dataset_rows if dataset_rows is not None else len(payload_rows)),
        projected_rows=len(payload_rows),
        dom_rows=int(dom.get("dom_rows") or 0) if dom.get("present") else 0)
    entry = {"present": bool(dom.get("present")), "ledger_status": ledger_status,
             "payload_rows": len(payload_rows), "dom_rows": dom.get("dom_rows"),
             "dataset_face": face_key, "dataset_rows": dataset_rows,
             "dataset_leg_measured": dataset_rows is not None,
             "ledger_provenance": {"declared": declared_provenance,
                                   "problems": provenance_problems,
                                   "check": provenance_check,
                                   "declared_present": declared_provenance is not None},
             "reconcile": reconciliation,
             "payload_verified": verified,
             "dom_stats": dom.get("stats"), "dom_groups": dom.get("groups"),
             "declared_rows_attr": dom.get("declared_rows"),
             "formal_path": formal}
    result["source_panel"] = entry
    if face_error:
        failures.append("SPA_SOURCE_READER_FACE_UNREGISTERED|%s" % face_error)
    if not dom.get("present"):
        failures.append(
            "SPA_SOURCE_PANEL_MISSING|读者页没有 [data-module=\"source_evidence\"] 面板根节点："
            "来源台账在读者层面不存在，无法对账（缺面板不等于没有来源问题）")
        return entry
    if ledger_status != "projected":
        if formal:
            failures.append(
                "SPA_SOURCE_LEDGER_ABSENT|正式档读者的来源台账缺失（source_ledger_status=%r）："
                "中文正式件必须带着可审计的来源面出货，缺失就是阻断，不许印一张空表当作没有这回事"
                % ledger_status)
    else:
        if dataset_rows is None:
            # 合同只给正式档登记了「三段数量逐项相等」这条义务（gate_obligations），
            # 候审档不在出货路径上：这里把它写成看得见的事实，而不是替合同再加一条规则。
            entry["dataset_leg_unmeasurable"] = True
            if formal:
                failures.append(
                    "SPA_SOURCE_DATASET_ROWS_UNMEASURABLE|拿不到运行 dataset 的 %r 行数，"
                    "dataset→投影→DOM 只剩两段可对账：数量恒等无法判定，不得当作通过（正式档阻断）"
                    % face_key)
        if not reconciliation["ok"]:
            failures.append(
                "SPA_SOURCE_ROW_COUNT_DRIFT|%s：dataset=%s 投影(payload source_records)=%s "
                "DOM(.se-row)=%s 三段数量必须逐项相等，不相等就是静默丢记录（#113 的形状）"
                % (";".join(reconciliation["problems"]),
                   reconciliation["numbers"]["dataset"], reconciliation["numbers"]["projected"],
                   reconciliation["numbers"]["dom"]))
        declared = _stat_int(dom.get("declared_rows"))
        if declared is not None and declared != dom.get("dom_rows"):
            failures.append(
                "SPA_SOURCE_DECLARED_ROWS_LIES|面板根节点自报 data-se-rows=%d，实际渲染 .se-row=%d："
                "面板自己声称的行数与真实行数不一致，读者看到的统计没有依据"
                % (declared, dom.get("dom_rows")))
        for stat_key, want in (("total", len(payload_rows)), ("verified", verified),
                               ("providers", len(measured["by_provider"]))):
            got = _stat_int((dom.get("stats") or {}).get(stat_key))
            if got is None:
                failures.append(
                    "SPA_SOURCE_STAT_MISSING|面板没有印 [data-se-count=\"%s\"]，"
                    "读者页的来源统计无法核对（旧实现把它写死成 0 正是 #113 的假统计）" % stat_key)
            elif got != want:
                failures.append(
                    "SPA_SOURCE_STAT_WRONG|[data-se-count=\"%s\"] 页面印 %d，从读者载荷逐行复算是 %d"
                    "（口径 scripts/source_projection.py::counts）；差 %d 条"
                    % (stat_key, got, want, abs(got - want)))
        labels = source_projection.registry()["labels"]
        buckets = {}
        for status, size in measured["by_status"].items():
            buckets[str(labels.get(status, status))] = size
        dom_groups = dom.get("groups") or []
        for group in dom_groups:
            summary = _stat_int(group.get("summary_text"))
            if summary != group.get("rows"):
                failures.append(
                    "SPA_SOURCE_GROUP_SUMMARY_WRONG|分组「%s」标题写着 %r，展开后实际渲染 %d 行："
                    "分组计数与内容不一致，读者按标题的数字判断覆盖范围"
                    % (group.get("label"), group.get("summary_text"), group.get("rows")))
        got_groups = {}
        for group in dom_groups:
            got_groups[str(group.get("label"))] = got_groups.get(str(group.get("label")), 0) + int(
                group.get("rows") or 0)
        if got_groups != buckets:
            failures.append(
                "SPA_SOURCE_GROUP_BUCKET_WRONG|页面分组行数 %s 与载荷按 verification_status 分桶 %s "
                "不相等：有整组记录没有出口（旧实现的「… N more」就是这么把 174/365 条吃掉的）"
                % (got_groups, buckets))
        want_indices = [str(r.get("row_index")) for r in payload_rows]
        want_uids = [str(r.get("row_uid")) for r in payload_rows]
        dom_indices = [str(v) for v in (dom.get("indices") or [])]
        dom_uids = [str(v) for v in (dom.get("uids") or [])]
        if sorted(dom_indices) != sorted(want_indices) or sorted(dom_uids) != sorted(want_uids):
            missing = sorted(set(want_indices) - set(dom_indices))
            failures.append(
                "SPA_SOURCE_ROW_IDENTITY_WRONG|页面上 .se-row 的 data-se-index/data-se-uid 集合与投影"
                "逐行身份不一致（截断、重复、丢失都在这一条里）：投影 %d 行、DOM %d 行、"
                "投影里有而页面没有的行号 %s；即使总数相等，身份集合不同就是有的记录在页面上不存在"
                % (len(payload_rows), len(dom_indices), missing[:12]))
        # 面板按 verification_status 分组，所以组内顺序才是可判定的序列（跨组比较会把分组当成乱序）。
        expected_seq: dict[str, list[tuple[str, str]]] = {}
        for row in payload_rows:
            status = str(row.get("verification_status"))
            expected_seq.setdefault(str(labels.get(status, status)), []).append(
                (str(row.get("row_index")), str(row.get("row_uid"))))
        for group in dom_groups:
            label = str(group.get("label"))
            got = [(str(i), str(u)) for i, u in zip(group.get("indices") or [],
                                                    group.get("uids") or [])]
            if label in expected_seq and got != expected_seq[label]:
                failures.append(
                    "SPA_SOURCE_GROUP_SEQUENCE_WRONG|分组「%s」的逐行身份序列与投影不符："
                    "页面 %d 行 / 投影 %d 行，被截断（slice(0,N)）或换序的记录不会出现在别的检查组里"
                    % (label, len(got), len(expected_seq[label])))
    return entry


def check_spa_page(page, html_path: Path, label: str, viewport: dict[str, int], screenshot: Path, *,
                   export_en_text: Path | None = None, asset_manifest: dict | None = None,
                   require_manifest: bool = False, run_dataset: dict | None = None) -> dict:

    """Check the SPA (重构版) renderer.

    v4.2.1 §1: the SPA is the only renderer shipped under the reader/review
    delivery profiles, so every reader-visible assertion must execute here.
    Failures are collected instead of raised so one run exposes the whole defect
    list rather than stopping at the first tripwire.
    """
    console_errors: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    failures: list[str] = []
    page.goto(html_path.resolve().as_uri(), wait_until="domcontentloaded")
    page.wait_for_timeout(500)
    result = {"label": label, "viewport": viewport, "console_errors": console_errors, "renderer": "travel-scope-spa-v1", "failures": failures}

    raw_dataset = page.evaluate("() => document.getElementById('dataset')?.textContent || ''")
    dataset: dict = {}
    if raw_dataset.strip():
        try:
            dataset = json.loads(raw_dataset)
        except json.JSONDecodeError as exc:
            failures.append(f"DS_PARSE|内嵌 dataset JSON 无法解析: {exc}")
    else:
        failures.append("DS_PARSE|产物缺少内嵌 <script id=dataset type=application/json> 数据块")

    # ZH-RELEASE-1：先确定「这页该按哪套门检查」，再跑任何与语言档位相关的断言。
    profile_state = check_reader_language_profile(page, dataset, failures, result)
    formal_reader = bool(profile_state.get("is_formal"))
    result["profile_branch"] = ("zh-formal" if formal_reader else
                                "en-audit" if profile_state.get("meta_declared") else "undeclared")

    body_text = page.locator("body").inner_text()
    result["nav_links"] = page.locator("nav [role=tab]").count()
    if result["nav_links"] != 8:
        failures.append(f"SPA_NAV|SPA 导航标签数 != 8: {result['nav_links']}")
    if "\u00a50" in body_text:
        failures.append("SPA_MONEY_ZERO|money() 仍渲染出 \u00a50（区间/比索/免费解析回归）")
    raw_keys = re.findall(
        r"\b(RIDE_HAILING|MAPS_NAVIGATION|FOOD_DISCOVERY|FOOD_DELIVERY|INTERCITY_BOOKING|URBAN_TRANSIT|TRANSLATION|COMMUNICATION|OFFICIAL_TOURISM|SAFETY_EMERGENCY|ACTIVITIES_BOOKING|ACCOMMODATION_BOOKING|WEATHER_ENVIRONMENT|CURRENCY_PAYMENT)\b",
        body_text,
    )
    result["app_cat_localized"] = len(raw_keys) == 0
    result["raw_category_keys"] = raw_keys[:5]
    if raw_keys:
        failures.append(f"SPA_APP_CATEGORY|在地工具 category 未本地化，暴露原始枚举键: {raw_keys[:5]}")
    result["horizontal_overflow"] = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2")
    if result["horizontal_overflow"]:
        failures.append(f"SPA_OVERFLOW|横向溢出 at {viewport}")
    result["route_options"] = page.locator(".route-card, [data-route]").count()
    result["title"] = page.locator("#cover-title").inner_text() if page.locator("#cover-title").count() else ""

    # v4.2.0 wrote these three assertions for the SPA DOM but placed them inside
    # check_page(), which the shipped renderer never reaches. Relocated here.
    topbar_state = page.evaluate('''() => {
      const topbar = document.getElementById('topbar');
      const btn = document.getElementById('lang-btn');
      window.scrollTo(0, 0);
      if (!topbar || !btn) return {present: false};
      const style = window.getComputedStyle(topbar);
      const rect = btn.getBoundingClientRect();
      return {present: true, opacity: style.opacity, top: rect.top,
              visible: rect.width > 0 && rect.height > 0};
    }''')
    result["topbar_state"] = topbar_state
    if formal_reader:
        # 按档位分支（ZH-RELEASE-1 · 业主裁 Q1-A），不是删断言：正式档 DOM 里本来就不该有
        # #lang-btn（合同 excluded），所以上面那段「缺按钮＝读者无法切换语言」的判词在正式档
        # 是错的。正式档仍然要求 #topbar 常驻可见，切换入口的存在性由
        # SPA_ZH_FORMAL_TOGGLE_PRESENT 反着管（出现才是失败）。
        topbar_only = page.evaluate('''() => {
          const topbar = document.getElementById('topbar');
          window.scrollTo(0, 0);
          if (!topbar) return {present: false};
          const style = window.getComputedStyle(topbar);
          const rect = topbar.getBoundingClientRect();
          return {present: true, opacity: style.opacity, top: rect.top,
                  visible: rect.width > 0 && rect.height > 0};
        }''')
        result["topbar_state_formal"] = topbar_only
        if not topbar_only.get("present"):
            failures.append("SPA_TOPBAR_MISSING|正式档缺少 #topbar：读者没有任何板块导航（#lang-btn 在正式档必须不存在，见 SPA_ZH_FORMAL_TOGGLE_PRESENT）")
        elif topbar_only.get("opacity") != "1" or not topbar_only.get("visible") or (topbar_only.get("top") or 0) < 0:
            failures.append(f"SPA_TOPBAR_ACCESSIBLE|scrollY=0 时正式档 #topbar 未常驻可见: {topbar_only}")
        check_zh_formal_page(page, dataset, failures, result)
    elif not topbar_state.get("present"):
        failures.append("SPA_TOPBAR_MISSING|缺少 #topbar 或 #lang-btn，读者无法切换语言")
    elif topbar_state.get("opacity") != "1" or not topbar_state.get("visible") or (topbar_state.get("top") or 0) < 0:
        failures.append(f"SPA_TOPBAR_ACCESSIBLE|scrollY=0 时 topbar/#lang-btn 未常驻可见: {topbar_state}")

    rl_nodes = page.locator(".route-line .rl-node").count()
    result["route_line_nodes"] = rl_nodes
    if rl_nodes < 2:
        failures.append(f"SPA_ROUTE_NODES|路线节点数 < 2 (仅 {rl_nodes})，走廊连字符未拆分，读者只看到孤立圆点")

    # 排版护栏：手机版把文字裁掉，读者收到的是半句话。英文比同义中文长，所以这类缺陷只在
    # §2.2.2 补齐后第一次显形（日主题槽位被 220px nowrap+ellipsis 砍掉 60%）。
    clipped = page.evaluate(CLIPPED_TEXT_JS)
    result["clipped_text"] = clipped
    if clipped:
        examples = "; ".join("%s +%dpx '%s'" % (c["sig"], c["px"], c["text"]) for c in clipped[:3])
        failures.append(
            "SPA_TEXT_CLIPPED|" + str(len(clipped)) +
            " 处文字被容器裁掉且未提供滚动/换行，读者看到的是省略号后面的空白: " + examples
        )

    day_summaries = [s.strip() for s in page.locator(".day summary").all_inner_texts()]
    thin_days = [s for s in day_summaries if len(s) < 5]
    result["day_headers"] = len(day_summaries)
    result["thin_day_headers"] = thin_days[:5]
    if day_summaries and thin_days:
        failures.append(f"SPA_DAY_HEADER|每日行程标题空洞: {thin_days[:5]}")

    check_embedded_map_contract(dataset, failures, result)
    check_map_dom_dataset_consistency(page, dataset, failures, result)
    check_budget_rate_state(page, dataset, failures, result, "cn")
    check_embedded_image_supply(page, failures, result, dataset)
    check_rendered_image_registration(page, dataset, asset_manifest, failures, result,
                                      manifest_required=require_manifest)
    check_source_panel(page, dataset, failures, result, profile_state=profile_state,
                       run_dataset=run_dataset)

    if formal_reader:
        # 正式档不跑英文态遍历：合同 profiles["zh-formal"] 的 reader_toggle=false，
        # 页面上没有切换入口，硬点一次 #lang-btn 只会得到「找不到元素」，
        # 而旧实现把这一步当成必产物 spa-en-text.txt 的来源（delivery_gate 的英文文本门读它）。
        # 候审英文的证据只能在 en-audit 档真渲染真点击（业主裁 Q1-A），不记在正式件头上。
        result["english_mode_walk"] = {"ran": False, "reason": "profile=zh-formal：正式交付无英文切换入口"}
        lang_btn = page.locator("#lang-btn")
        result["lang_btn_count"] = lang_btn.count()
        result["lang_before"] = page.locator("html").get_attribute("lang") or ""
        result["lang_after"] = result["lang_before"]
        result["en_text_export"] = None
    elif not profile_state.get("reader_toggle"):
        # 档位没声明或没登记（或声明了但不带 reader_toggle）：不能替它决定该跑哪一套语言检查。
        # 这里既不放行英文遍历，也不报「英文模式无法验证」——那一页已经被
        # SPA_READER_PROFILE_UNDECLARED / SPA_READER_PROFILE_UNREGISTERED 判死了。
        result["english_mode_walk"] = {
            "ran": False,
            "reason": "档位 %r 未注册 reader_toggle（见 SPA_READER_PROFILE_* 判定）"
                      % profile_state.get("meta_declared")}
        result["lang_btn_count"] = page.locator("#lang-btn").count()
    else:
        lang_btn = page.locator("#lang-btn")
        if lang_btn.count() == 0:
            failures.append("SPA_EN_TOGGLE|未找到 #lang-btn，英文模式无法验证")
        else:
            before_lang = page.locator("html").get_attribute("lang") or ""
            before_btn = (lang_btn.inner_text() or "").strip()
            cn_cjk_chars = len(en_residue_measure.CJK_IDEOGRAPH_RE.findall(body_text))
            lang_btn.evaluate("el => el.click()")
            page.wait_for_timeout(400)
            after_lang = page.locator("html").get_attribute("lang") or ""
            after_btn = (lang_btn.inner_text() or "").strip()
            en_state = page.evaluate(EN_STATE_JS.replace("__CJK_CLASS__",
                                                         en_residue_measure.CJK_CLASS_JS))
            en_body = en_state.get("body", "")
            measurement = en_residue_measure.measure(en_body)
            cjk_chars = measurement["raw_cjk"]
            total_chars = max(1, len(en_body))
            en_active = after_btn != before_btn and cjk_chars < cn_cjk_chars
            result["lang_before"] = before_lang
            result["lang_after"] = after_lang
            result["lang_btn_before"] = before_btn
            result["lang_btn_after"] = after_btn
            result["en_active"] = en_active
            result["cn_cjk_chars"] = cn_cjk_chars
            # V5-C（V0-L06）：口径唯一。en_cjk_chars 保留为「原始汉字数」（向后兼容旧报告字段），
            # 判定用的残留是 en_cjk_leaked；两个比值都写出来，谁在看哪个数字不必猜。
            result["en_residue"] = {key: measurement[key] for key in
                                    ("chars", "raw_cjk", "intentional_cjk", "intentional_tokens",
                                     "leaked_cjk", "ratio", "ratio_unadjusted",
                                     "fullwidth_punctuation", "leaked_samples")}
            result["en_residue_scope"] = measurement["scope"]
            result["en_cjk_chars"] = cjk_chars
            result["en_cjk_leaked"] = measurement["leaked_cjk"]
            result["en_cjk_ratio"] = round(measurement["ratio"], 5)
            result["en_cjk_ratio_unadjusted"] = round(measurement["ratio_unadjusted"], 5)
            result["en_visible_chars"] = total_chars
            if not en_active:
                failures.append(
                    f"SPA_EN_TOGGLE|点击 #lang-btn 后未进入英文态: 按钮文字 '{before_btn}'->'{after_btn}'，"
                    f"可见汉字数 {cn_cjk_chars}->{cjk_chars}"
                )
            if before_lang == after_lang:
                failures.append(
                    f"SPA_HTML_LANG_STALE|切换语言后 <html lang> 仍为 '{after_lang}'：读屏软件与搜索引擎会把英文内容"
                    f"当作中文页面处理（spa-layout.js 的语言 handler 只改 state.lang，未写 documentElement.lang）"
                )
            if export_en_text is not None:
                export_en_text.write_text(en_body, encoding="utf-8")
                result["en_text_export"] = str(export_en_text)

            if not en_active:
                failures.append("SPA_EN_NOT_EVALUATED|未进入英文态，EN 槽位断言未判定（不得当作通过）")
            else:
                check_budget_rate_state(page, dataset, failures, result, "en")
                leaked = [s for s in en_state.get("poiSub", []) if CJK_RE.search(s)]
                result["en_poi_sub_leaks"] = leaked[:8]
                if leaked:
                    failures.append(f"SPA_EN_POI_SUB|EN 模式分类标签汉字泄漏 {len(leaked)} 处: {leaked[:5]}")
                if CJK_RE.search(en_state.get("cover", "")):
                    failures.append(f"SPA_EN_COVER|EN 模式主标题残留汉字: '{en_state.get('cover')}'")
                if "CNY" in en_state.get("dayCards", ""):
                    failures.append("SPA_EN_CURRENCY|EN 模式每日花费面板残留 CNY 货币符号")
                leaks = en_state.get("census") or {}
                ranked = sorted(leaks.items(), key=lambda kv: -kv[1].get("count", 0))
                total_leaky = sum(v.get("count", 0) for v in leaks.values())
                result["en_leak_slots"] = len(ranked)
                result["en_leak_elements"] = total_leaky
                result["en_leak_top"] = [f"{k} x{v.get('count')} {v.get('samples', [])[:1]}"
                                         for k, v in ranked[:8]]
                pending = en_state.get("pending") or 0
                pending_list = en_state.get("pendingList") or []
                result["en_translation_pending"] = pending
                result["en_translation_pending_list"] = pending_list
                if pending:
                    truncated = "" if pending <= len(pending_list) else f"（清单截断，仅列前 {len(pending_list)} 条）"
                    failures.append(
                        f"SPA_EN_UNTRANSLATED_TEXT|EN 态有 {pending} 处文字没有英文来源，页面上显示 "
                        f"'(translation pending)' 明示缺口{truncated}；定位方式："
                        f"translate_prose.py --locate-gaps <本报告> 逐条给判定：dataset_cell（登记表覆盖，"
                        f"--apply 能写）/ dataset_cell_unregistered（数据里有那一格、列未登记，带地址）/ "
                        f"render_composite（渲染层拼接）/ renderer_literal（实测在 assets/spa-layout.js 里）/ "
                        f"unattributed（两侧都量不到＝定位口径缺陷，不许冒充任一侧）/ "
                        f"proper_name（专名：走 display-name-channel 的 tier1 名对或 tier2 机器翻译显示名，"
                        f"不进翻译表、不升级身份）/ money_scaffold（格式化器槽：由 money() 登记金额语法与 "
                        f"enMetrics() 度量兜底出，塞进 prose_en 就是让散文表冒充金额规则）。"
                        f"词表与语义登记：references/data-model.json::english_gap_verdicts。"
                        f" 清单: {json.dumps(pending_list[:40], ensure_ascii=False)}"
                    )
                if total_leaky:
                    failures.append(
                        f"SPA_EN_LEAK_CENSUS|EN 态仍有 {total_leaky} 个元素直出汉字，分布在 {len(ranked)} 类槽位；"
                        f"最大来源: {result['en_leak_top'][:4]}"
                    )
                if cjk_chars / total_chars > 0.01:
                    failures.append(
                        f"SPA_EN_CJK_RATIO|EN 态整页可见汉字占比 {cjk_chars / total_chars:.2%} > 1% "
                        f"({cjk_chars}/{total_chars})，清册 §2.2.3 阈值"
                    )
                if CJK_RE.search(en_state.get("title", "")):
                    failures.append(
                        f"SPA_EN_TITLE|EN 态 document.title 残留汉字: '{en_state.get('title')}'（浏览器标签页读者可见）"
                    )
                day_leaks = [s for s in en_state.get("daySummaries") or [] if CJK_RE.search(s)]
                result["en_day_header_leaks"] = day_leaks[:5]
                if day_leaks:
                    failures.append(
                        f"SPA_EN_DAY_HEADER|EN 态每日标题汉字泄漏 {len(day_leaks)}/{len(en_state.get('daySummaries') or [])} 天: "
                        f"{day_leaks[:3]}"
                    )
                # v4.2.2 V5-B 删掉了这里原本的 SPA_EN_DISCLAIMER 检查（"EN 模式残留
                # 'exchange rate unverified' 未核验免责声明"）。那条规则把「向读者承认没有汇率」
                # 当成缺陷，正是 JS 里塞 `return 7.15` 的理由——它没有被解决，只是被消音了。
                # 现在的唯一规则是 check_budget_rate_state：未登记就必须说明原因，且不得出现换算金额。
                placeholder_hits = sorted({m.group(0) for m in MAP_PLACEHOLDER_SEGMENT_RE.finditer(en_body)})
                result["en_placeholder_names"] = placeholder_hits
                if placeholder_hits:
                    failures.append(f"SPA_EN_PLACEHOLDER|EN 模式可见占位 venue 名 {placeholder_hits[:6]}（读者会看到假地名）")

            # 复位到中文态，别把英文态留给后面的截图与视口检查（en-audit 档才有这一步）。
            lang_btn.evaluate("el => el.click()")
            page.wait_for_timeout(200)

    page.screenshot(path=str(screenshot), full_page=False)
    if console_errors:
        failures.append(f"SPA_CONSOLE|浏览器错误: {console_errors[:3]}")
    result["status"] = "PASS" if not failures else "FAIL"
    return result


STANDALONE_VIEWPORT = {"width": 390, "height": 844}


def check_standalone_images(page, html_path: Path, screenshot: Path) -> dict:
    """Open a lonely copy of the deliverable in an empty directory.

    The guide is sent to the reader as one HTML file, so every picture it shows must live
    inside that file. v4.2.0 validated the artifact next to its assets/ folder and reported
    PASS while the file the reader actually received had 2 working pictures out of 25 -- the
    missing ones were silently swapped for decorative SVG placeholders by the img error
    handler, which is a mask, not a fallback.
    """
    page.goto(html_path.resolve().as_uri(), wait_until="load")
    page.wait_for_timeout(700)
    for frac in (0.25, 0.5, 0.75, 1.0):
        page.evaluate("f => window.scrollTo(0, document.body.scrollHeight * f)", frac)
        page.wait_for_timeout(250)
    data = page.evaluate("""() => {
      const imgs = [...document.querySelectorAll('img')];
      const counts = {};
      const bump = k => { counts[k] = (counts[k] || 0) + 1; };
      for (const i of imgs) {
        const raw = i.getAttribute('src') || '';
        if (i.dataset.fallbackFired === '1') { bump('placeholder_masked'); continue; }
        if (raw.startsWith('data:')) { bump('inline'); continue; }
        if (/^https?:/i.test(raw)) { bump('remote'); continue; }
        bump('external_file');
      }
      return {total: imgs.length, counts,
              loaded: imgs.filter(i => i.naturalWidth > 0).length};
    }""")
    page.screenshot(path=str(screenshot), full_page=False)
    counts = data.get("counts") or {}
    failures: list[str] = []
    masked = counts.get("placeholder_masked", 0)
    external = counts.get("external_file", 0)
    total = data.get("total", 0)
    if masked or external:
        failures.append(
            f"SPA_IMAGES_NOT_SELF_CONTAINED|单独发送的成品里有 {masked + external}/{total} 张图片不在文件内："
            f"外链 {external} 张、被占位图掩盖 {masked} 张；读者收到的是这个文件，不是 assets/ 目录"
        )
    if counts.get("remote", 0):
        failures.append(
            f"SPA_IMAGES_REMOTE|成品依赖 {counts['remote']} 张远程图片，离线或换网即失效"
        )
    return {"label": "spa-standalone", "renderer": "travel-scope-spa-v1", "viewport": STANDALONE_VIEWPORT,
            "images_total": total, "image_kinds": counts, "images_loaded": data.get("loaded"),
            "screenshot": str(screenshot), "status": "FAIL" if failures else "PASS", "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Travel-Scope browser visual smoke checks")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--report", default="")
    parser.add_argument("--asset-manifest", default="",
                        help="run 的 asset-manifest.json；给了就把读者页每张图对账到登记字节（V0-L12）")
    parser.add_argument("--require-asset-manifest", action="store_true",
                        help="交付档使用：没有清单就是阻断，而不是跳过对账")
    parser.add_argument("--dataset", default="",
                        help="run 的 dataset.json；来源面板要做 dataset→投影→DOM 三段对账"
                             "必须有它。不传则按 outputs/../dataset.json 自动找（V0-L07：读不到"
                             "就如实报未判定，不许当成通过）")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    dataset_path = Path(args.dataset) if args.dataset else None
    if dataset_path is None:
        for candidate in (output / "dataset.json", output.parent / "dataset.json"):
            if candidate.is_file():
                dataset_path = candidate
                break
    run_dataset: dict | None = None
    dataset_note = {"path": str(dataset_path).replace("\\", "/") if dataset_path else "",
                    "loaded": False, "error": ""}
    if dataset_path is not None and dataset_path.is_file():
        try:
            run_dataset = json.loads(dataset_path.read_bytes().decode("utf-8"))
            dataset_note["loaded"] = True
        except (OSError, json.JSONDecodeError) as exc:
            dataset_note["error"] = str(exc)[:200]
    manifest_path = Path(args.asset_manifest) if args.asset_manifest else None
    if manifest_path is None:
        for candidate in (output / "asset-manifest.json", output.parent / "asset-manifest.json"):
            if candidate.is_file():
                manifest_path = candidate
                break
    asset_manifest: dict | None = None
    manifest_note = {"path": str(manifest_path).replace("\\", "/") if manifest_path else "",
                     "loaded": False, "error": ""}
    if manifest_path is not None and manifest_path.is_file():
        try:
            asset_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_note["loaded"] = True
        except (OSError, json.JSONDecodeError) as exc:
            manifest_note["error"] = str(exc)[:200]
    report_path = Path(args.report) if args.report else output / "visual-qa.json"
    screenshots = output / "visual-qa"
    screenshots.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            spa_files = list(output.glob("*-travel-guide.html")) + list(output.glob("*重构版.html"))
            for pattern, label in (("*地图标记.html", "cn"), ("*地图标记-en.html", "en"), ("*双语.html", "bilingual")):
                matches = sorted(output.glob(pattern))
                if not matches:
                    if label == "cn" and not spa_files:
                        raise FileNotFoundError(f"missing mandatory HTML: {pattern}")
                    results.append({"label": f"{label}-all", "status": "SKIP", "reason": f"missing optional HTML: {pattern}"})
                    continue
                html = min(matches, key=lambda path: (len(path.name), path.name))
                split_renderer = 'content="travel-scope-split-v1"' in html.read_text(encoding="utf-8", errors="replace")
                for width, height, suffix in (
                    (1920, 1080, "desktop-1920"),
                    (1440, 900, "desktop"),
                    (768, 1024, "tablet"),
                    (430, 932, "mobile-430"),
                    (390, 844, "mobile-390"),
                    (360, 800, "mobile-360"),
                ):
                    viewport = {"width": width, "height": height}
                    page = browser.new_page(viewport=viewport, reduced_motion="no-preference")
                    try:
                        if split_renderer:
                            _record(results, f"{label}-{suffix}", lambda: check_split_page(page, html, f"{label}-{suffix}", viewport, screenshots / f"{label}-{suffix}.png", bilingual=label == "bilingual"))
                        elif label == "bilingual":
                            _record(results, f"{label}-{suffix}", lambda: check_bilingual_page(page, html, f"{label}-{suffix}", viewport, screenshots / f"{label}-{suffix}.png"))
                        else:
                            _record(results, f"{label}-{suffix}", lambda: check_page(page, html, f"{label}-{suffix}", viewport, screenshots / f"{label}-{suffix}.png"))
                    finally:
                        page.close()
            spa_matches = sorted(output.glob("*-travel-guide.html")) + sorted(output.glob("*重构版.html"))
            if spa_matches:
                # The SPA artifact is the deliverable under reader/review profiles,
                # so a missing SPA file is a hard failure, never a SKIP.
                spa_html = min(spa_matches, key=lambda path: (len(path.name), path.name))
                for width, height, suffix in SPA_VIEWPORTS:
                    viewport = {"width": width, "height": height}
                    page = browser.new_page(viewport=viewport, reduced_motion="no-preference")
                    try:
                        _record(results, f"spa-{suffix}", lambda: check_spa_page(
                            page, spa_html, f"spa-{suffix}", viewport,
                            screenshots / f"spa-{suffix}.png",
                            export_en_text=(screenshots / "spa-en-text.txt" if suffix == "desktop" else None),
                            asset_manifest=asset_manifest,
                            require_manifest=args.require_asset_manifest,
                            run_dataset=run_dataset,
                        ))
                    finally:
                        page.close()
                with tempfile.TemporaryDirectory() as lonely_dir:
                    # The deliverable is the file itself: load it with no siblings present.
                    lonely = Path(lonely_dir) / spa_html.name
                    shutil.copy2(spa_html, lonely)
                    page = browser.new_page(viewport=STANDALONE_VIEWPORT, reduced_motion="no-preference")
                    try:
                        _record(results, "spa-standalone", lambda: check_standalone_images(
                            page, lonely, screenshots / "spa-standalone.png"))
                    finally:
                        page.close()
            else:
                results.append({"label": "spa-all", "status": "FAIL", "renderer": "travel-scope-spa-v1",
                                "failures": ["SPA_ARTIFACT_MISSING|reader/review 档位的必产物 *-travel-guide.html 不存在，英文态与地图契约无从验证"]})
        finally:
            browser.close()
    html_files = {}
    for pattern, label in (("*地图标记.html", "cn"), ("*地图标记-en.html", "en"), ("*双语.html", "bilingual"), ("*-travel-guide.html", "spa"), ("*重构版.html", "spa")):
        matches = sorted(output.glob(pattern))
        if matches and label not in html_files:
            html_files[label] = min(matches, key=lambda path: (len(path.name), path.name))
    failure_index: dict[str, dict] = {}
    for item in results:
        for failure in item.get("failures") or []:
            code = failure.split("|", 1)[0]
            entry = failure_index.setdefault(code, {"count": 0, "detail": failure.split("|", 1)[1][:220], "labels": []})
            entry["count"] += 1
            entry["labels"].append(item.get("label", "?"))
    spa_ran = any(item.get("renderer") == "travel-scope-spa-v1" and "failures" in item for item in results)
    status = "PASS" if spa_ran and not failure_index else "FAIL"
    # ZH-RELEASE-1：交付出去的是哪一档、按哪一档检的，写在报告头上，让 delivery_gate 不必猜。
    spa_checks = [item for item in results
                  if item.get("renderer") == "travel-scope-spa-v1" and "failures" in item]
    declared = sorted({str((item.get("reader_profile") or {}).get("meta_declared") or "")
                       for item in spa_checks})
    report = {
        "status": status,
        "html_sha256": {label: hashlib.sha256(path.read_bytes()).hexdigest() for label, path in html_files.items()},
        "asset_manifest": manifest_note,
        "run_dataset": dataset_note,
        "reader_profiles": {
            "registered_formal": spa_renderer.formal_reader_profile(),
            "meta_name": spa_renderer.reader_language_contract().get("html_meta_name"),
            "declared_by_check": declared,
            "spa_check_count": len(spa_checks),
        },
        "failure_codes": failure_index,
        "checks": results,
    }
    # V5-A：被检的是哪几份 HTML、由哪版代码检的，都要写进报告本身。
    producer_inputs = {"html[%s]" % label: path for label, path in sorted(html_files.items())}
    if asset_manifest is not None and manifest_path is not None:
        producer_inputs["asset_manifest"] = manifest_path
    if dataset_note["loaded"]:
        producer_inputs["run_dataset"] = dataset_path
    report = gate_producer.write_stamped_report(
        report_path, report, gate_role="visual_qa", producing_code=list(PRODUCING_CODE),
        producing_config=list(PRODUCING_CONFIG),
        inputs=producer_inputs)["report"]
    print(json.dumps({"status": status, "failure_codes": failure_index, "html_sha256": report["html_sha256"]}, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
