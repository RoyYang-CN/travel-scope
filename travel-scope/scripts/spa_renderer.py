"""Travel-Scope v5.0.0 Single-Page Application (SPA) Magazine Renderer.

Generates responsive, high-taste, interactive travel guides embedding 100% loss-free
structured datasets in <script id="dataset">, with smart scroll navbars, dual-currency
amounts **only when the run registered a sourced exchange rate** (v4.2.2 V5-B), full 12-day
itineraries, direct action triggers, and mobile offline resilience.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import html
import json
import mimetypes
import os
import re
import sys
from pathlib import Path

try:
    import budget_contract
    import single_file_policy
except ImportError:  # pragma: no cover - 作为包内模块导入时
    from scripts import budget_contract  # type: ignore
    from scripts import single_file_policy  # type: ignore

try:
    import map_link_selector
except ImportError:  # pragma: no cover - 作为包内模块导入时
    from scripts import map_link_selector  # type: ignore

ROOT = Path(__file__).resolve().parents[1]

MAP_SELECTION_PATH = ROOT / "references" / "map-link-selection.json"
_MAP_LINK_UI_CACHE: dict | None = None
_READER_LANGUAGE_CONTRACT_CACHE: dict | None = None
_READER_SCOPE_REPORT: dict | None = None


def _map_link_ui() -> dict:
    """读者页的地图文案与「谁该出按钮」只有一个来源：references/map-link-selection.json。

    §7 的按钮文案表是产品合同，不是 JS 字面量。渲染层拿不到 references/ 目录（成品是单文件），
    所以由这里把登记好的文案、提示和 rendered_providers 随 dataset 一起发给客户端；
    spa-layout.js 只许读 D.map_link_ui，自己再写一份文案即违反 §9「渲染层不得维护第二套规则」。
    """
    global _MAP_LINK_UI_CACHE
    if _MAP_LINK_UI_CACHE is None:
        cfg = json.loads(MAP_SELECTION_PATH.read_text(encoding="utf-8"))
        ui = cfg["ui"]
        rendered = list(ui.get("rendered_providers") or [])
        if not rendered:
            raise ValueError("map-link-selection.json 没有登记 ui.rendered_providers，"
                             "渲染层不允许自己猜该出哪颗按钮")
        _MAP_LINK_UI_CACHE = {
            "selection_version": cfg["selection_version"],
            "primary_provider": ui.get("primary_provider") or rendered[0],
            "rendered_providers": rendered,
            "button_copy": ui["button_copy"],
            "notices": ui["notices"],
            "authority": "references/map-link-selection.json",
        }
    return dict(_MAP_LINK_UI_CACHE)


def _budget_ui(adapted_data) -> dict:
    """V5-B：读者页的汇率状态、换算因子与提示文案只有一个来源。

    登记处是 `references/budget-policy.json`，dataset 侧只提供 `budget_meta`；两者由
    `budget_contract.reader_projection()` 合成。客户端 JS 只读 `D.budget_fx`——
    旧版在 spa-layout.js 里写死 `7.15`／`0.125` 兜底，等于让渲染层自己编一个汇率（V0-L05）。
    """
    return budget_contract.reader_projection(adapted_data.get("budget_meta") or {})


def _utf8_len(value) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _record_strip(marker, kind, provider, value) -> None:
    """记一笔「这类字段从这个 provider 身上剔了多少行、多少字节」。

    `value` 必须是它在 payload 里实际占的那一段（字典项连键一起给），这样 marker 的字节口径
    与 `reader_payload_projection.audit_only_field_kinds[*].measured` 的登记口径是同一把尺子；
    两处数字对不上，V6 的字节账就只能二选一，那正是 V0-L11 要避免的东西。
    """
    bucket = marker["stripped_fields"].setdefault(kind, {}).setdefault(
        provider, {"rows": 0, "utf8_bytes": 0})
    bucket["rows"] += 1
    bucket["utf8_bytes"] += _utf8_len(value)


def _project_reader_map_links(adapted_data, ui):
    """读者载荷只带 `rendered_providers` 那一子集；其余 provider 的归属字段留在审计面。

    §3.3 的 per-provider 容器是**审计面**：每条目标每个 provider 都要有独立结论，这一条不因
    读者页只有一颗按钮而改变。但单文件 HTML 是读者载荷，把读者永远不会点的 provider 决策整包
    塞进去，等于让读者为看不见的东西付字节（V3R 实测：两棵 run 的 apple 决策容器共 217,329B）。

    V6-B 把同一口径补全：V3R 只剔了决策容器，`apple_url` 这类 legacy 单值 URL、
    `classifier_verdicts.apple_url`、归属 Apple 的 quarantine 行仍然整批躺在读者下载的文件里
    （V6-B 实测 CA 再 228,518B）。剔哪些字段由 `map-link-selection.json::reader_payload_projection`
    登记，渲染器不自己列字段（V0-L12 的「同一规则只许一处实现」）。

    这里做的是**投影**，不是删除：只作用于 `_adapt_spa_dataset()` 产出的深拷贝，
    dataset 文件与 link_selection_report.jsonl 里的完整容器一条都不少；
    投影结果随 payload 登记，门禁和审计都能看到「谁被剔出读者载荷、剔了多少字节、完整记录在哪」。
    """
    rules = map_link_selector.reader_payload_projection()
    targets = adapted_data.get("map_targets")
    rendered = list(ui.get("rendered_providers") or [])
    audit_only = sorted(set(rules["entity_hosts"]) - set(rendered))
    # marker 自己也进读者载荷，所以它只带「能证明剔了什么」的最小面：种类清单留在登记处
    # （rules_ref 指过去），不在每个成品里抄一遍。V6-B 实测：把 field_kinds 整包塞进 marker
    # 让本来无可剔的 PH 成品净增 838B——投影省下字节却又自己吃回去，这条必须可见。
    projected = {"authority": rules["authority"],
                 "rules_ref": "references/map-link-selection.json::reader_payload_projection",
                 "rendered_providers": rendered,
                 "audit_only_providers": audit_only,
                 "stripped_providers": {},
                 "stripped_fields": {},
                 "stripped_process_records": {},
                 "process_record_rows_seen": {},
                 "targets_with_container": 0,
                 "audit_records": "完整 per-provider 决策与血缘见 dataset_v422_selected.json "
                                  "与 link_selection_report.jsonl（806 条 provider 决策）"}
    if not isinstance(targets, dict):
        projected["map_targets_absent"] = True
        return projected
    if not rendered:
        raise ValueError("rendered_providers 为空：投影层不许自己猜该保留哪颗按钮")
    for row in targets.values():
        if not isinstance(row, dict):
            continue
        container = row.get("map_link_by_provider")
        if isinstance(container, dict) and container:
            projected["targets_with_container"] += 1
            extra = [provider for provider in sorted(container) if provider not in rendered]
            if extra:
                row["map_link_by_provider"] = {provider: container[provider]
                                               for provider in container if provider in rendered}
                for provider in extra:
                    projected["stripped_providers"][provider] = \
                        projected["stripped_providers"].get(provider, 0) + 1
                    _record_strip(projected, "map_link_container_entry", provider,
                                  {provider: container[provider]})
        for provider in audit_only:
            url_field = "%s_url" % provider
            if url_field in row:
                _record_strip(projected, "provider_url_field", provider,
                              {url_field: row.pop(url_field)})
            verdicts = row.get("classifier_verdicts")
            if isinstance(verdicts, dict) and url_field in verdicts:
                _record_strip(projected, "classifier_verdict_entry", provider,
                              {url_field: verdicts.pop(url_field)})
            quarantine = row.get("quarantine")
            if isinstance(quarantine, list) and quarantine:
                kept, removed = [], []
                for item in quarantine:
                    (removed if map_link_selector.quarantine_row_attributed(item, provider)
                     else kept).append(item)
                if removed:
                    _record_strip(projected, "quarantine_provider_rows", provider, removed)
                    row["quarantine"] = kept
            isolated = row.get("isolated_link_url")
            hosts = rules["entity_hosts"].get(provider) or []
            if isinstance(isolated, str) and any(host in isolated for host in hosts):
                _record_strip(projected, "isolated_link_url_provider_host", provider,
                              {"isolated_link_url": row.pop("isolated_link_url")})
        # V6-P：provider-neutral 的过程记录（血缘、欠账清单、隔离记录、判决日志、版本戳）同样
        # 不进读者载荷。判据不是「归属哪个 provider」而是「渲染器读不读它」——逐字段核过
        # assets/spa-layout.js 与 assets/split-layout.js，名单里每一条两个渲染器都不碰。
        # 剔的是这份深拷贝（读者下载的那一份），dataset 文件与 link_selection_report.jsonl
        # 一条不减；marker 里记下「审计面有多少行、剔了多少字节」，门禁才能反查而不是空跑。
        for field in rules["process_record_fields"]:
            if field not in row:
                continue
            projected["process_record_rows_seen"][field] = \
                projected["process_record_rows_seen"].get(field, 0) + 1
            bucket = projected["stripped_process_records"].setdefault(
                field, {"rows": 0, "utf8_bytes": 0})
            bucket["rows"] += 1
            bucket["utf8_bytes"] += _utf8_len({field: row[field]})
            row.pop(field)
    projected["stripped_utf8_bytes"] = sum(
        bucket["utf8_bytes"]
        for providers in projected["stripped_fields"].values()
        for bucket in providers.values()) + sum(
        bucket["utf8_bytes"] for bucket in projected["stripped_process_records"].values())
    return projected


def registered_max_inline_kb() -> int:
    """内联上限只有一个登记来源；这里不再留一份『看起来一样』的默认值。"""
    return single_file_policy.registered_max_inline_kb()


ASSET_REF_PREFIX = "asset://sha256:"


def _embed_media_as_asset_ref(file_path: Path, blob_table: dict, max_kb: int | None = None) -> str | None:
    """Inline a file once and hand back a content-addressed reference.

    v4.2.0 wrote the full base64 blob at every use site, so a hero image that was also the
    route cover shipped twice in one 2MB file (369KB decoded, twice) -- and the mobile first
    paint had to decode both. The blob now lives once in D.asset_blobs, keyed by the digest of
    the very bytes the manifest is supposed to attest, so local_media_gate can reconcile them.
    """
    if not file_path.is_file():
        return None
    if max_kb is None:
        # 上限必须由调用方显式给出（render_spa_document 从登记配置解析后传下来）。
        # 在这里再放一个「和登记值刚好一样」的默认数，就是第二套规则：改了登记、忘了这里，
        # 产物会静默按旧上限构建，而账单看起来仍然合规。
        raise ValueError("内联上限必须显式传入（由 references/single-file-delivery-policy.json 登记）")
    max_kb = int(max_kb)
    if max_kb <= 0:
        raise ValueError(f"内联上限必须是正整数 KB，收到 {max_kb!r}")
    data = file_path.read_bytes()
    if len(data) > max_kb * 1024:
        return None
    mime, _ = mimetypes.guess_type(str(file_path))
    mime = mime or "image/jpeg"
    digest = hashlib.sha256(data).hexdigest()
    blob_table.setdefault(digest, f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}")
    return ASSET_REF_PREFIX + digest


def _json(value):
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _adapt_spa_dataset(dataset, media_delivery_mode="linked", assets_dir=None, max_inline_kb=None,
                       run_asset_dir=None):
    """P1-1 Adapter Layer: normalize v4.1.0 dataset structures for spa-layout.js client state machine."""
    if max_inline_kb is None:
        # 缺省不等于随便：上限从登记配置解析，本文件不留任何本地数字。
        max_inline_kb = single_file_policy.registered_max_inline_kb()
    max_inline_kb = int(max_inline_kb)
    if max_inline_kb <= 0:
        raise ValueError(f"内联上限必须是正整数 KB，收到 {max_inline_kb!r}")
    adapted = copy.deepcopy(dataset)
    # 1. Normalize routes to 7 elements [name, name_en, corridor, days, transit, budget, highlights]
    if "routes" in adapted and isinstance(adapted["routes"], list):
        new_routes = []
        for r in adapted["routes"]:
            if isinstance(r, list) and len(r) >= 8 and not re.search(r"\d+\s*(?:天|days?)", str(r[1]), re.I) and re.search(r"\d+\s*(?:天|days?)", str(r[1]), re.I) is None:
                # v4.1.0 Excel format: [name, days, corridor, highlights, audience, budget, transit, en_name]
                new_routes.append([
                    r[0],
                    r[7] if len(r) > 7 else r[0],
                    r[2] if len(r) > 2 else "",
                    r[1] if len(r) > 1 else "",
                    r[6] if len(r) > 6 else "",
                    r[5] if len(r) > 5 else 0,
                    r[3] if len(r) > 3 else "",
                ])
            else:
                new_routes.append(r)
    # 1.5. Normalize route_budgets (v4.1.8: schema with total_cny)
    if "route_budgets" in adapted and isinstance(adapted["route_budgets"], dict):
        new_budgets = {}
        for r_name, b_val in adapted["route_budgets"].items():
            if isinstance(b_val, dict):
                if "total_cny" not in b_val:
                    raise ValueError(f"route_budgets['{r_name}'] missing required 'total_cny': {b_val}")
                new_budgets[r_name] = b_val
            elif isinstance(b_val, (int, float)):
                new_budgets[r_name] = {"total_cny": float(b_val)}
            elif isinstance(b_val, str) and re.search(r"\d+", b_val):
                m = re.search(r"(\d+(?:\.\d+)?)", b_val)
                new_budgets[r_name] = {"total_cny": float(m.group(1)) if m else 0.0}
            else:
                raise ValueError(f"route_budgets['{r_name}'] has invalid unknown type: {type(b_val)} ({b_val})")
        adapted["route_budgets"] = new_budgets

    # 2. Normalize budget first column from "Day 1" to "1" for Number(b[0]) mapping
    if "budget" in adapted and isinstance(adapted["budget"], list):
        new_budget = []
        for b in adapted["budget"]:
            if isinstance(b, list) and b:
                row_copy = list(b)
                m = re.search(r"\d+", str(row_copy[0]))
                if m:
                    row_copy[0] = m.group(0)
                new_budget.append(row_copy)
            else:
                new_budget.append(b)
        adapted["budget"] = new_budget

    # 3. Normalize itinerary kind alias ('住宿' -> '酒店')
    if "itinerary" in adapted and isinstance(adapted["itinerary"], list):
        new_itin = []
        for item in adapted["itinerary"]:
            if isinstance(item, list) and len(item) > 3:
                row_copy = list(item)
                if row_copy[3] == "住宿":
                    row_copy[3] = "酒店"
                elif row_copy[3] == "美食":
                    row_copy[3] = "餐厅"
                new_itin.append(row_copy)
            else:
                new_itin.append(item)
        adapted["itinerary"] = new_itin

    # 4. Normalize hotel/restaurant description column shift (index 11 -> index 10)
    for cat in ("hotels", "restaurants", "cafes"):
        if cat in adapted and isinstance(adapted[cat], list):
            new_rows = []
            for row in adapted[cat]:
                if isinstance(row, list) and len(row) > 11 and not str(row[10] or "").strip() and str(row[11] or "").strip():
                    r_copy = list(row)
                    r_copy[10] = r_copy[11]
                    new_rows.append(r_copy)
                else:
                    new_rows.append(row)
            adapted[cat] = new_rows

    # 5. Media inline embedding (v4.1.6 Hero-Only Inline for Linked & Full Inline for Standalone)
    if assets_dir and Path(assets_dir).is_dir():
        assets_path = Path(assets_dir).resolve()
        blob_table: dict[str, str] = {}
        tier_index = adapted.get("media_renditions") or {}
        run_assets_root = Path(run_asset_dir) if run_asset_dir else None
        # V6-Q（业主 2026-10-30 裁决）：读者页不许内联「拿不出证据」的图——清单没登记就没有来源、
        # 授权与摘要可对账；交付档位低于登记几何下限就没有读者能看的像素。两种都改成**显式媒体缺口**：
        # 行留在 dataset 里、缺口记进 media_gaps（含原字节与缺什么证据），但字节不进读者载荷。
        # 悄悄把图删掉是第二次「gate 说 PASS 而成品是坏的」；照旧内联未登记字节则是 §12 禁止的伪证据。
        media_gaps: list[dict] = []
        geometry_floor = single_file_policy.delivered_geometry_floor()

        def _record_gap(path_str: str, kind: str, detail: str, file_bytes: int = 0) -> None:
            media_gaps.append({"kind": kind, "asset": path_str, "detail": detail,
                               "source_bytes": file_bytes,
                               "authority": "references/single-file-delivery-policy.json::"
                                            "delivered_rendition_ladder.min_delivered_geometry"})

        def _tier_below_floor(tier: dict) -> str:
            """档位几何是否低于登记下限——只看清单声明的那对尺寸，不在渲染期再解一次像素。

            清单是 prepare_media 写完交付字节后登记的，delivered/rendition 的 width×height 就是
            读者会拿到的那一帧；再读一遍文件只会多一个可能与清单不一致的口径（V0-L11 的老路）。
            """
            width, height = int(tier.get("width") or 0), int(tier.get("height") or 0)
            if not width or not height:
                return "清单档位没写宽高，无法确认不低于登记下限"
            if width < geometry_floor[0] or height < geometry_floor[1]:
                return "交付档 %dx%d 低于登记下限 %dx%d" % (
                    width, height, geometry_floor[0], geometry_floor[1])
            return ""

        def _resolve_image(path_str: str) -> Path | None:
            rel_sub = path_str[7:] if path_str.startswith("assets/") else path_str
            candidate = assets_path / rel_sub
            if not candidate.is_file():
                candidate = assets_path.parent / path_str
            return candidate if candidate.is_file() else None

        # Tier bytes live in the run's own asset tree. The output directory is a *copy* of the
        # delivered assets, and a replay build renders into a temp directory that has no run tree
        # beside it at all -- guessing from adjacency is what made every srcset vanish in step 14
        # and what made the step-15 replay fail. The caller names the run root; adjacency is only
        # the fallback for callers that do not have one.
        asset_roots: list[Path] = []
        for root in ([run_assets_root] if run_assets_root else []) + [
                assets_path, assets_path.parent / "assets",
                assets_path.parent.parent / "assets"]:
            resolved_root = root.resolve() if root.is_dir() else None
            if resolved_root is not None and resolved_root not in asset_roots:
                asset_roots.append(resolved_root)

        def _find_tier_file(tier: dict) -> Path | None:
            name = Path(str(tier.get("file") or "")).name
            declared = str(tier.get("path") or "").replace("\\", "/")
            for root in asset_roots:
                for rel in (f"renditions/{name}", name, declared):
                    if rel:
                        candidate = root / rel
                        if candidate.is_file():
                            return candidate
            return None

        def _tier_url(tier: dict) -> str:
            """Linked delivery keeps tiers as files; only inline delivery turns them into blobs."""
            name = Path(str(tier.get("file") or "")).name
            candidate = _find_tier_file(tier)
            if candidate is None:
                return ""
            try:
                return "../" + candidate.relative_to(assets_path).as_posix()
            except ValueError:
                return candidate.as_uri()

        def _attach_srcset(owner: dict, path_str: str, key: str = "image",
                           srcset_key: str = "image_srcset") -> bool:
            """Deliver one slot at the size its slot can use (§12, owner decision 2026-10-25).

            Inline delivery: the widest declared tier, and only that one. Every candidate of a
            srcset is already inside the file, so listing two tiers makes the reader carry both
            while the browser still cannot fetch the smaller one over the wire -- 16 heroes x their
            w800 copy was 1.2MB spent on a saving that does not exist in a single file.

            Linked delivery: publish the real tier list, where srcset genuinely picks a size.

            Either way a declared tier that cannot be delivered is a build error, not a silently
            single-sourced image.
            """
            inline = media_delivery_mode in ("standalone", "embedded", "inline")
            tiers = tier_index.get(path_str) or tier_index.get(Path(path_str).name) or []
            if not tiers:
                return False
            ordered = sorted(tiers, key=lambda t: -int(t.get("width") or 0))
            wanted = ordered[:1] if inline else ordered
            refs, unusable = [], []
            for tier in wanted:
                candidate = _find_tier_file(tier)
                if candidate is None:
                    unusable.append("%s (%s 档位文件不在盘上)" % (path_str, tier.get("label")))
                    continue
                below_floor = _tier_below_floor(tier)
                if below_floor:
                    # 交付像素低于登记下限 = 读者拿不到能看的图。剔出载荷并登记缺口，
                    # 而不是让它进页面后再被媒体门判死（那等于让读者为一个坏档付字节）。
                    _record_gap(path_str, "MEDIA_BELOW_GEOMETRY_FLOOR", below_floor,
                                int(tier.get("bytes") or 0))
                    continue
                if inline:
                    ref = _embed_media_as_asset_ref(candidate, blob_table, max_kb=max_inline_kb)
                    if not ref:
                        size_kb = candidate.stat().st_size // 1024
                        unusable.append("%s (%s 档 %dKB 超过内联上限 %dKB)"
                                        % (path_str, tier.get("label"), size_kb, max_inline_kb))
                        continue
                else:
                    ref = _tier_url(tier)
                if ref:
                    refs.append({"ref": ref, "width": tier["width"], "label": tier["label"]})
            if unusable:
                raise ValueError(
                    "IMG_TIER_UNDELIVERABLE|清单声明的 rendition 无法交付: " + "；".join(unusable))
            if refs:
                if not inline and len(refs) > 1:
                    owner[srcset_key] = refs
                owner[key] = refs[0]["ref"]          # widest tier is the fallback src
                return True
            return False

        def _deliver(owner: dict, path_str: str, key: str, srcset_key: str) -> None:
            """Ship one image slot: the declared rendition when the manifest has one, else the file.

            v4.2.1 inlined the source file *and* its renditions because the fallback ran
            unconditionally, so the reader carried the same picture twice under two digests -- and
            the second one had no manifest backing at all. Exactly one of the two paths may run.
            """
            if _attach_srcset(owner, path_str, key=key, srcset_key=srcset_key):
                return
            if any(gap.get("asset") == path_str for gap in media_gaps):
                return                      # 已登记缺口：不许再退回原文件字节把它塞进读者载荷
            if tier_index and not (tier_index.get(path_str) or tier_index.get(Path(path_str).name)):
                # 清单存在却没登记这一条 ⇒ 这段字节没有来源、授权、可对账摘要。v4.2.0/v4.2.1 的
                # 加州成品就是这么把 511KB 未登记图内联进读者页的（IMG_DELIVERED_UNATTESTED）。
                candidate = _resolve_image(path_str)
                _record_gap(path_str, "MEDIA_UNREGISTERED_IN_MANIFEST",
                            "asset-manifest 里没有这条登记：来源/授权/摘要无从对账"
                            + ("（在盘 %dKB 原图未被交付档处理）"
                               % (candidate.stat().st_size // 1024) if candidate else "（文件不在盘上）"),
                            candidate.stat().st_size if candidate else 0)
                return
            candidate = _resolve_image(path_str)
            if candidate is None:
                return
            ref = _embed_media_as_asset_ref(candidate, blob_table, max_kb=max_inline_kb)
            if ref:
                owner[key] = ref

        # Always inline hero_image for fast first-frame rendering
        hero = adapted.get("hero_image")
        if hero and isinstance(hero, str) and not hero.startswith(("data:", "asset://")):
            _deliver(adapted, hero, "hero_image", "hero_srcset")

        # Collect route cover hero image paths from routes
        route_hero_images = set()
        for r in adapted.get("routes") or []:
            r_name = r[0] if isinstance(r, list) and r else str(r)
            for item in adapted.get("editorial_media") or []:
                if isinstance(item, dict) and item.get("route") == r_name and item.get("image"):
                    route_hero_images.add(item["image"])
                    break

        # Embed editorial_media: if standalone/embedded/inline, embed all; otherwise hero-only
        if "editorial_media" in adapted and isinstance(adapted["editorial_media"], list):
            for item in adapted["editorial_media"]:
                if isinstance(item, dict) and item.get("image") and not item["image"].startswith(("data:", "asset://")):
                    img_ref = item["image"]
                    is_hero = img_ref in route_hero_images or img_ref == hero
                    if is_hero or media_delivery_mode in ("standalone", "embedded", "inline"):
                        _deliver(item, img_ref, "image", "image_srcset")

        # Embed section_media: ONLY if standalone/embedded/inline
        if media_delivery_mode in ("standalone", "embedded", "inline") and "section_media" in adapted and isinstance(adapted["section_media"], list):
            for item in adapted["section_media"]:
                if isinstance(item, dict) and item.get("image") and not item["image"].startswith(("data:", "asset://")):
                    _deliver(item, item["image"], "image", "image_srcset")

        if media_gaps:
            # 被剔出读者载荷的那一行整行不进 payload（半张图比没图更糟），但缺口记录留下原标题、
            # 原字节与理由；审计面的 dataset 文件一行都不少。读者看到的是少一张图，审计看到的是全貌。
            gapped = {str(gap.get("asset") or "") for gap in media_gaps}
            for gap in media_gaps:
                gap.setdefault("withheld_from_reader", True)
            for key in ("editorial_media", "section_media"):
                rows = adapted.get(key)
                if not isinstance(rows, list):
                    continue
                kept = []
                for index, item in enumerate(rows):
                    image_value = str(item.get("image") or "") if isinstance(item, dict) else ""
                    if image_value and image_value in gapped:
                        for gap in media_gaps:
                            if gap.get("asset") == image_value and "withheld_row" not in gap:
                                gap["withheld_row"] = {
                                    "list": key, "index": index,
                                    "title": str(item.get("title_cn") or item.get("title") or ""),
                                    "destination": str(item.get("destination") or ""),
                                    "caption_cn": str(item.get("caption_cn") or "")}
                        continue
                    kept.append(item)
                adapted[key] = kept
            if str(adapted.get("hero_image") or "") in gapped:
                adapted["hero_image"] = ""
            adapted["media_gaps"] = media_gaps

        if blob_table:
            adapted["asset_blobs"] = blob_table

    # The tier index tells the renderer which bytes exist; the reader does not need to carry it.
    adapted.pop("media_renditions", None)

    return adapted


def reader_language_contract() -> dict:
    """读者语言档位的唯一登记来源（ZH-RELEASE-1 · 业主裁 Q1-A）。

    档位是**构建期事实**，不是读者可选功能：正式交付只有 zh-formal 一档，英文通道的真渲染
    探针走 en-audit 且产物不得进 outputs/。这里拿不到登记块就直接失败——渲染层不许自己
    猜「默认应该是中文」。
    """
    global _READER_LANGUAGE_CONTRACT_CACHE
    if _READER_LANGUAGE_CONTRACT_CACHE is None:
        contract = json.loads((ROOT / "references" / "renderer-contract.json").read_text(encoding="utf-8"))
        block = contract.get("reader_language")
        if not isinstance(block, dict) or "profiles" not in block or not block.get("formal_profile"):
            raise ValueError("renderer-contract.json 缺少 reader_language 登记块 ⇒ 语言档位没有唯一来源")
        _READER_LANGUAGE_CONTRACT_CACHE = block
    return _READER_LANGUAGE_CONTRACT_CACHE


def reader_profile_spec(profile: str) -> dict:
    profiles = reader_language_contract()["profiles"]
    if profile not in profiles:
        raise ValueError(f"未登记的读者语言档位 {profile!r}；已登记的只有 {sorted(profiles)}")
    return dict(profiles[profile])


def formal_reader_profile() -> str:
    return str(reader_language_contract()["formal_profile"])


def source_ledger_chain() -> dict:
    """来源台账正式链的注册面（合同 reader_language.source_ledger_chain）。"""
    chain = reader_language_contract().get("source_ledger_chain")
    if not isinstance(chain, dict):
        raise ValueError("合同缺少 reader_language.source_ledger_chain：正式生成链的血缘义务没有登记，"
                         "渲染器无法判断『缺台账该阻断还是该留空面』，不得静默按其中一种走")
    return chain


def zero_call_build_window() -> dict:
    """正式构建那一段的零调用账本形状（合同顶层 `zero_call_build_window`，ZH-RELEASE-2 步6c）。

    为什么要有这一条：§11 V4 要求四项零调用**来自执行期拦截器**，而树里此前只有两种账本——
    门禁自己那一趟审计的窗口（formal_data_gate 报 `self_check_window`）与测试窗口
    （test_v422_map_execution 的 `guarded(scope)`）。**正式构建那一段从来没有执行期账**，
    所以「生成时零 Google 调用」一直是推论而不是测量。

    形状（文件名／档位／必须绑定的字段）只住在合同里，生成器只执行；块缺失或字段不全就抛，
    不许按默认名悄悄写一份指不到输入字节的账。
    """
    contract = json.loads((ROOT / "references" / "renderer-contract.json").read_text(encoding="utf-8"))
    block = contract.get("zero_call_build_window")
    if not isinstance(block, dict):
        raise ValueError("renderer-contract.json 缺少 zero_call_build_window 登记块 ⇒ "
                         "正式构建的零调用账本没有唯一形状，不得由生成器自己编一个")
    missing = [key for key in ("outputs_relpath", "scope_prefix", "evidence_tier", "binding_fields")
               if not block.get(key)]
    if missing:
        raise ValueError("zero_call_build_window 登记块缺字段 %s ⇒ 账本会写成一份对不上字节的空面"
                         % missing)
    return dict(block)


def formal_build_declared() -> bool:
    """「这一趟是不是正式构建」的唯一判据：环境变量名与命中值都读合同登记，不在代码里硬写。

    存在的意义是把 smoke 与正式分开：直调 render_spa_document() 时这个信号不在环境里，
    载荷也没有（也无法伪造）指向具体输入字节的自证 ⇒ 那种产物只有 smoke 身份。
    """
    formal = source_ledger_chain().get("formal_build") or {}
    env_name = str(formal.get("env") or "")
    if not env_name:
        raise ValueError("source_ledger_chain.formal_build.env 没有登记环境变量名 ⇒ 正式构建身份无从判定")
    return os.environ.get(env_name) == str(formal.get("value") or "1")


def apply_reader_profile(data: dict, profile: str) -> dict:
    """决定「读者实际拿到什么」的唯一一处：来源投影 ＋ 合同驱动的语言范围投影。

    来源面板走 scripts/source_projection.py（业主 2026-11-02 裁 A）：读者面是
    source_evidence_meta 的**校验投影**，任何不认识的形状直接抛 ProjectionError 让构建失败，
    绝不 continue 跳过——#113 的空白条目＋「0 verified」假统计就是这么来的。

    语言范围走 scripts/reader_payload_scope.py（业主 P0-1）：正式档不是 pop 顶层黑名单，
    而是顶层允许清单＋任意深度 EN 形状剥离并登记；未登记的顶层键直接阻断构建。
    """
    import source_projection as sp
    import reader_payload_scope as scope
    spec = reader_profile_spec(profile)
    meta = data.get("source_evidence_meta")
    face = meta if isinstance(meta, list) else None
    formal_build = formal_build_declared()
    if face:
        rows = sp.project(face)
        data["source_records"] = rows
        data["source_counts"] = sp.counts(rows)
        data["source_ledger_status"] = "projected"
    else:
        # 业主 2026-11-03 裁 finding_1：正式构建不许「缺台账→回退空列表→印一张空表」。
        # 非正式（demo 夹具、直调 smoke）仍然登记成看得见的 absent 面，由门禁判它不是交付证据。
        if formal_build:
            raise ValueError(
                "SOURCE_LEDGER_FACE_%s：正式构建（%s=1）走到渲染器时载荷里没有可用的 source_evidence_meta。"
                "这一面只能由生成器从正式输入 dataset 携带进来；直调 render_spa_document() 造的件按合同只算 "
                "smoke，不得充当正式交付证据。"
                % ("MISSING" if face is None else "EMPTY",
                   str((source_ledger_chain().get("formal_build") or {}).get("env"))))
        data["source_records"] = []
        data["source_counts"] = sp.counts([])
        data["source_ledger_status"] = "absent"
    if formal_build:
        # 自证核对：装配载荷时钉的那张面，与现在真正投影出去的那张面，必须是同一份字节。
        problems = sp.provenance_problems(data.get("source_ledger_meta"), face)
        if problems:
            raise ValueError(
                "SOURCE_LEDGER_PROVENANCE_BROKEN：正式构建的来源台账血缘自证与手上的机器面不合 %s"
                "（自证=%r，机器面=%s 行；口径 source_projection.provenance_problems）"
                % ([code for code, _ in problems], data.get("source_ledger_meta"),
                   len(face or [])))
    dropped = []
    for key in spec.get("excluded_payload_keys") or []:
        if key in data:
            data.pop(key, None)
            dropped.append(key)
    if "source_evidence_meta" in data:          # 审计机器面留在 run 输入里，不进读者载荷
        data.pop("source_evidence_meta", None)
        dropped.append("source_evidence_meta")
    data["reader_profile"] = profile
    data["reader_profile_dropped_keys"] = sorted(set(dropped))
    # 业主 P0-1：正式档不是「pop 黑名单」，而是顶层允许清单＋任意深度 EN 形状剥离并登记；
    # 未登记的顶层键直接阻断 ⇒ 换个字段名带候审英文这条路走不通。
    data, scope_report = scope.project_reader_payload(
        data, profile, formal_profile=formal_reader_profile())
    global _READER_SCOPE_REPORT
    _READER_SCOPE_REPORT = scope_report
    return data


def reader_scope_report() -> dict:
    """最近一次构建的范围投影报告（门禁与构建日志读这里，不另算一份）。"""
    return dict(_READER_SCOPE_REPORT or {})


def render_spa_document(output_path, dataset, media_delivery_mode=None, assets_dir=None,
                        max_inline_kb=None, run_asset_dir=None, reader_profile=None):
    css_path = ROOT / "assets/spa-layout.css"
    js_path = ROOT / "assets/spa-layout.js"
    
    css = css_path.read_text(encoding="utf-8")
    js = js_path.read_text(encoding="utf-8")

    # Fail-fast minimal assertions (P0-1)
    if "route_budgets" not in dataset or not isinstance(dataset.get("route_budgets"), dict):
        raise ValueError("SPA renderer requires 'route_budgets' dict in payload")
    if "duration_days" not in dataset or not isinstance(dataset.get("duration_days"), (int, float)):
        days = 0
        for r in dataset.get("routes") or []:
            if isinstance(r, list):
                for cell in r:
                    m = re.search(r"(\d+)\s*(?:天|days?)", str(cell), re.I)
                    if m:
                        days = max(days, int(m.group(1)))
        if not days and dataset.get("itinerary"):
            for item in dataset.get("itinerary") or []:
                if isinstance(item, list) and len(item) > 1:
                    m = re.search(r"(\d+)", str(item[1]))
                    if m:
                        days = max(days, int(m.group(1)))
        if days:
            dataset["duration_days"] = days
        else:
            raise ValueError("SPA renderer requires 'duration_days' int/float in payload")

    # Configuration-driven delivery mode. The default is *inline*: the reader receives one HTML
    # file, so a build that links to a sibling assets/ directory ships 23 broken images. A run that
    # genuinely wants linked assets must say so in the dataset, not inherit it silently.
    if media_delivery_mode is None:
        media_delivery_mode = dataset.get("spa_media_delivery_mode", "inline")
    if assets_dir is None:
        cand = Path(output_path).parent / "assets"
        if cand.is_dir():
            assets_dir = cand
        else:
            cand_root = ROOT / "assets"
            if cand_root.is_dir():
                assets_dir = cand_root
    if max_inline_kb is None:
        # V5-D（V0-L11）：400 这个数以前硬写在渲染器里，产物又不声称自己用了哪一档，
        # 于是 11.4MB 的成品和 3.9MB 的成品看着像同一次构建。现在上限只有一个登记来源，
        # 且本次用的档位要写进产物 meta，交给 self_contained_audit 核对。
        max_inline_kb = int(dataset.get("spa_media_max_inline_kb",
                                        single_file_policy.registered_max_inline_kb()))
    max_inline_kb = int(max_inline_kb)
    if max_inline_kb <= 0:
        raise ValueError(f"内联上限必须是正整数 KB，收到 {max_inline_kb!r}：0 档等于「不内联」，"
                         f"要那种交付请显式写 media_delivery_mode='linked'")

    adapted_data = _adapt_spa_dataset(
        dataset,
        media_delivery_mode=media_delivery_mode,
        assets_dir=assets_dir,
        max_inline_kb=max_inline_kb,
        run_asset_dir=run_asset_dir,
    )
    adapted_data["map_link_ui"] = _map_link_ui()
    # V5-B：读者页的汇率状态与文案也只有一个来源（references/budget-policy.json）。
    # JS 不许再自己判断币种、更不许留兜底常数——见 budget_contract 模块头的现场记录。
    adapted_data["budget_fx"] = _budget_ui(adapted_data)
    map_link_projection = _project_reader_map_links(adapted_data, adapted_data["map_link_ui"])
    adapted_data["map_link_render_projection"] = map_link_projection
    # ZH-RELEASE-1：语言档位是构建期事实（合同 reader_language）。正式档剔除英文显示面，
    # 并把来源面板换成 source_evidence_meta 的校验投影；未知档位直接 raise，不回落默认。
    profile = reader_profile or formal_reader_profile()
    adapted_data = apply_reader_profile(adapted_data, profile)
    profile_spec = reader_profile_spec(profile)
    # 每一份产物都自己声明档位：门禁读到的「该按哪套检查」来自产物本身，而不是构建参数。
    reader_meta = (f'<meta name="{reader_language_contract()["html_meta_name"]}" '
                   f'content="{html.escape(profile, quote=True)}">\n')
    lang_btn_html = ('  <button class="lang-btn" id="lang-btn" type="button"></button>\n'
                     if profile_spec.get("reader_toggle") else "")
    country = adapted_data.get("country") or adapted_data.get("country_en") or "Travel-Scope"
    title = html.escape(str(country))
    payload = _json(adapted_data)
    media_cap_meta = single_file_policy.media_cap_meta_html(int(max_inline_kb))
    
    document = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light">
<meta name="travel-scope-renderer" content="travel-scope-spa-v1">
{reader_meta}{media_cap_meta}
<title>Travel-Scope · {title}旅行攻略</title>
<style>{css}</style>
</head>
<body>

<!-- ================= TOP BAR ================= -->
<nav class="topbar" id="topbar" aria-label="sections">
  <a class="brand" href="#cover">Travel-Scope</a>
  <div class="tabs" id="tabs" role="tablist" aria-label="sections"></div>
{lang_btn_html}</nav>

<!-- ================= COVER ================= -->
<header class="cover" id="cover">
  <img class="cover-bg" id="cover-bg" alt="" aria-hidden="true" decoding="async">
  <div class="cover-inner">
    <p class="eyebrow">Travel-Scope / Island &amp; Ocean</p>
    <h1 id="cover-title"></h1>
    <p class="cover-sub" id="cover-sub"></p>
    <p class="cover-lead" id="cover-lead"></p>
    <div class="stats" id="cover-stats"></div>
  </div>
  <span class="scroll-hint" id="scroll-hint"></span>
  <div class="cover-foot">
    <div class="route-pick" id="route-pick" role="group" aria-label="route picker"></div>
  </div>
</header>

<main id="main"></main>

<footer class="page-footer">
  <div class="wrap" id="footer-inner"></div>
</footer>

<noscript><p style="padding:30px">This guide requires JavaScript; the Markdown / Excel editions are available in the same folder.</p></noscript>

<script id="dataset" type="application/json">{payload}</script>
<script>{js}</script>
</body>
</html>'''

    Path(output_path).write_text(document, encoding="utf-8")
    return output_path
