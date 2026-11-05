---
name: travel-scope
description: Build Travel-Scope guides with batch conversational Q0-Q8, nationwide route exploration, verified hotels, food, cafes and transport, no-key map links, and a responsive Chinese-first (zh-formal) single-file SPA whose English mode is audit-only, with optional review and audit exports. Use for Travel-Scope travel planning and guide generation.
---

# Travel-Scope

Version 5.0.0 — v5.0.0 LIMITED-SCOPE RELEASE — California zh-formal validated。**默认正式档位：zh-formal**——本版唯一正式档位是中文读者面，**英文 slug 命名的中文单文件 SPA**（文件名与产物 slug 用英文，正文是中文）。**en-audit 不是正式交付物，不得进入正式输出目录**；英文正式交付未认证（DEFERRED），MT-E／MT-F／MT-G 与 31 处英文渲染槽位拆除进入下一迭代。**未验证的目的地一律不得表述成已验证样例**（排除名单与现场硬事实登记在 `references/release-scope.json::excluded_destinations`）：**当前版本只以加州正式 run 完成端到端验证；其他目的地必须重新通过全部门禁**。**本版不声明整体 production-certified（production_certified=false）**。
运行合同：**零付费 Google API 调用、不使用 API Key**、零抓取、不合成 Place ID；**NAMED_SEARCH 允许，但必须标明落点未核验**；地图链接四态（PUBLISHER_ENTITY_LINK／NAMED_SEARCH／COORDINATE／NONE）与「不保证每个地图链接打开唯一 Google 实体卡」照旧生效。
**媒体来源逐字定位符、run 相对路径、离线重放与正式门要求**（登记在 `references/media-policy.json`：每行三段血缘＝修订身份⇄采集字节⇄派生链、来源逐字定位符、run 内 POSIX 相对路径、离线重放两次同字节、正式构建跑在零调用哨兵下）；正式门不放行就不产出交付物。本文其余章节描述该合同内部的工程约束与门禁用法。

（v5.0.0 版本身份迁移，2026-11-05：业主授权将已收口的 v4.2.2 有限范围合同升为新一代主版本。本迁移不扩大产品范围，不把英文或其他目的地改判为 PASS，不重建业主已签署的加州中文 HTML 字节。机器可读血缘见 `references/release-scope.json::version_identity_migration`。）
（上一版状态行原文保留不删：「Version 4.2.2 — 诚实地图搜索候选：**独立候选根，未发布、未安装、未获得 production certification**。本目录不是当前可安装、也不是可用于正式生成的产品合同。本版按 `V4.2.2_ITERATION_CHECKLIST.md` 执行地图诚实降级合同（PUBLISHER_ENTITY_LINK／NAMED_SEARCH／COORDINATE／NONE 四态 + 零 Google Billing／零 Key／零抓取／零合成 Place ID），v4.2.1 的 §17 离线 resolver 路线已按审计裁决停止且未恢复、其候选结果不得作为生产答案。本文其余章节描述的是该候选分支内部的工程约束与门禁用法，不代表任何发布资格；v4.2.1 的失实声明撤回登记见 v4.2.1 树 `VERSION.md` 的 DOC-TRUTH-1 段。」。）
Historical version notes and old prompts do not override it.

## Verify the product, not just the name

Resolve this SKILL.md's directory as ROOT. Before any build:

`python ROOT/scripts/verify_product.py`

It must match `product-origin.json`, `references/renderer-contract.json` and
`scripts/travel_renderer.py`. A mismatch blocks generation. Integrity is not proof
that research, translations or licensing are correct.

Never execute another travel skill's controller, questionnaire, canonical HTML,
renderer or validator. Never resolve a conflict by renaming the other package.
External projects are references only; do not inherit their requirements or PASS
reports. Maintain provenance and licenses when borrowing assets or techniques.

## Intake: one conversational Q0–Q8 batch

Immediately upon skill loading or invocation, if the user has not provided their complete destination and itinerary requirements, the agent MUST automatically send the complete Q0–Q8 questionnaire in chat to let the user choose.
Output all questions together in chat and follow `references/intake-policy.json`.
Fill already-known answers directly. Never replace an unanswered fixed-choice
question with an empty colon; show every option. Free-input questions keep a
format hint or example when unanswered. The required reader-facing choices are:

- Q0 destination/country or explicit custom area: free input with example.
- Q1 travel month/dates: free input with example; never invent dates from a month.
- Q2 number of days: free positive integer with example.
- Q3 spending/accommodation tier: 经济 / 中档 / 舒适 / 高端 / 混合.
- Q4 transport: 自驾 / 非自驾.
- Q5 arrival city, airport or port: free input with format hint.
- Q7 research depth: 精简 / 标准 / 深度 / 超级深度 (concise / standard / deep / ultra).
- Q8 itinerary pace: 紧凑 / 适中 / 宽松.

Use `python ROOT/scripts/intake_contract.py` to print the canonical questionnaire,
or pass `--known RUN/intake-known.json` to preserve known answers. Validate the
completed intake with `--known RUN/intake.json --validate` before preflight.

Default delivery profile is `reader`: one bilingual SPA named
`{artifact_slug}-travel-guide.html`. `review` explicitly adds one merged research
workbook, and `full_audit` explicitly adds the compatibility HTML, Excel and
Markdown artifacts. `artifact_slug` is required ASCII lowercase kebab-case and
must not be guessed from a non-ASCII destination name. Default route selection is an AI
recommendation after nationwide exploration. Ask about either only when the user
explicitly wants to override the default. International map links default to
Google and Apple; mainland-China links default to Amap and Baidu.

No HTML questionnaire, extra preferences or map-provider question, and no routine
one-question-at-a-time flow unless requested. Do not invent traveler counts or
change moderate pace to relaxed. Ask only for missing material constraints.

After confirmation, continue through research, exports and QA without routine
stops; give concise updates. Pause only for contradictory requirements, missing
material authority, unverifiable critical data or failed required gates. State
the evidence and smallest necessary user action.

## Planning and evidence

1. Start a fresh isolated run and preserve the original brief unchanged.
   Before discovery, add `manifest.destination_profile`: scope type, physical
   geography, available mobility modes, map region, candidate-pool count,
   coverage boundary, data availability and explicit uncertainties. This profile
   controls applicable research modules without hard-coding a country. If a small
   or constrained destination cannot reach the Q7 candidate-pool target, record a
   concrete `candidate_pool_exception`; never add duplicate micro-areas to reach a number.
2. Country requests require nationwide discovery and route exploration. Arrival/
   departure ports are not scope. Run `scripts/route_explorer.py`; save input and
   result. Custom areas stay scoped. Present the route comparison and exclusions;
   do not reconfirm AI route choice already authorized by the user.
3. Research real hotels, restaurants, cafes, sights, applicable diving, transport,
   budgets, packing and local practical information. Record source URLs, retrieval
   dates, uncertainty and branch identity. No unrelated shopping or language quotas.
   For every route-changing transport leg, actively look for published flights,
   trains, ferries, intercity buses, scheduled shuttles and connecting services.
   Prefer operator booking/timetable pages, then airports/ports/stations or transport
   authorities. Record the timetable effective period and retrieval date. Classify
   each leg as exact-date verified, published reference, on-demand, future
   unpublished or unverified. Never present a current or historical timetable as a
   future-date commitment. Taxis, charters and transfers without fixed departures
   must say on-demand instead of inventing a timetable.
   A search result or generic homepage is discovery evidence only. It never proves
   a POI or a timetable. Alongside reader-facing `source_evidence`, write
   `source_evidence_meta` following `references/evidence-policy.md`. Apply Q7
   through `references/run-quality-policy.json`. Concise, standard, deep and ultra
   change both research breadth and evidence depth: deep and ultra require independent
   direct entity sources and per-entity cross-source review, while enforcing Tier 1 /
   Tier 2 destination category floors (hotels, food, cafes, sights) and whole-run totals.
   They never relax source truth, route continuity,
   geographic identity or map-target correctness. Record completed research passes
   in `manifest.research_passes` and link each pass to files or source records in
   `manifest.research_pass_evidence`; labels without corresponding evidence do not pass.
   After the first dataset draft, run `scripts/build_truth_worklist.py` to create
   a complete pending entity/map/schedule checklist. It never self-verifies a row;
   resolve every item with direct evidence before copying reviewed `map_targets`
   and `source_evidence_meta` into the dataset.
4. Store generator-compatible arrays in run-local JSON, shared by HTML, Excel and
   Markdown. Never inject run data into the installed generator's DATA constants.
   Existing schemas: `fixtures/demo.json`, `scripts/data_model.py`, Excel headers
   in `scripts/gen_travel_scope.py`. Demo is an example schema, not a data source.
   Persist the confirmed Q0-Q8 values unchanged in both preflight and run manifest.
   Run `scripts/formal_data_gate.py` before generation. For a country-level run it
   requires at least three distinct route corridors, complete daily plans, 100%
   documented corridor continuity, pace-compliant transfer days, canonical scope,
   complete entity-level visible-POI source coverage, map-target coverage,
   itinerary-to-POI coordinate binding and budget/date truthfulness.
5. Use `assets/` plus `asset-manifest.json`: source page, permission/license,
   place/category, local file and actual verification. Inspect contact sheets.
   Never generate CDN IDs, bind a waterfall to an island, pass generic images as
   exact branch photos or set verification flags in bulk. Collection always starts
   as `pending_visual_review`; only a separate contact-sheet review record may
   promote it to verified. A hero is illustrative,
   not POI evidence. Missing evidence stays missing.

   Image selection has four explicit levels: verified exact-place photo; same
   destination and same-category reference; same-region and same-category reference;
   designed no-photo state. Reference images must be labelled as atmosphere or
   category reference in the page and manifest, never as the named hotel's,
   restaurant's, attraction's or dive site's own photo. Do not substitute another
   identifiable business. Prefer a designed state when geographic/category identity
   or reuse permission is uncertain, but do not fill an entire guide with designed
   states: Q7 policy caps their ratio and requires verified atmosphere/category
   photographs for the remaining branch covers.

   Treat editorial storytelling media and section media as separate collections
   at collection and evidence time. At rendering time, a destination branch with
   no dedicated cover may reuse an already verified same-destination atmosphere
   or local-feature image as destination context. This exception is branch-level
   only: it must not imply that the image depicts a named hotel, restaurant, cafe,
   attraction or dive operator, and its source role remains machine-readable even
   though the cover has no visible role badge. Follow `references/media-policy.json`. Source order
   is user-supplied media with permission, official media with explicit reuse
   terms, Wikimedia Commons, then Openverse or stock libraries as discovery pools
   whose original rights must still be checked. Search-engine thumbnails, ordinary
   business websites and social posts are not reusable evidence. Generated imagery
   is limited to decorative textures, abstract maps and designed no-photo states;
   it must not impersonate a real place or business.

   Standard and deep guides should target one dedicated section image for each
   destination and section category (accommodation, food, sights). The run-local
   `image_collection.section_media_required` flag makes this a hard coverage gate.
   Each section slot must declare destination, modules, module category, selection
   level, display role, focal point, author, license, original source page,
   retrieval date, immutable source identity/page ID, source asset URL, SHA256 and
   a separate evidence file under `evidence/`. Duplicate asset records and
   unreviewed assets block formal generation. Reusing one verified asset as a
   same-destination branch-context fallback does not create a second asset record
   and is allowed only by the renderer rule above.
   When one category reference covers sibling modules such as restaurants/cafes
   or attractions/dive sites, declare one `primary_module`; sibling branches may
   reuse it only as same-destination context when no better verified local image exists.
   Transport primarily uses route and timetable graphics; add photos only when a
   verified port, vessel or local scene materially improves understanding.

No paid APIs by default, including remote-image QA. Never embed keyed Places
photo links. SQLite is not a prerequisite for ordinary local exports. Overseas
links use Google/Apple; mainland links use Amap/Baidu. Do not pass WGS84 as GCJ02/
BD09; use name search when conversion is unknown. Routes show major destinations
by day, not chains of restaurants, hotels and sights.

Live map links are verified targets, not unqualified search links. Every map target
must declare `entity_type` as `named_entity` or `coordinate_landmark`; hotels,
restaurants, cafes, attractions, dive operators and transport nodes are
`named_entity`. A named entity may use an exact entity URL, a compliant Place ID,
or a name + destination + country query, but never a pure-coordinate reader link. Build
`map_targets` according to `references/map-link-policy.md`. Prefer a verified exact
platform URL, then a compliant real Place ID, then a verified named query tied to
independently verified coordinates. Pure-coordinate links are reserved for genuinely
unnamed `coordinate_landmark` records. A name search is `search_candidate` until
its landing is independently verified and cannot pass formal delivery by label alone.
Never scrape Google Maps pages to manufacture IDs. Transport targets are individual
terminals, airports, ports or stations rather than route labels. Browser QA must
record the entity/address or pin actually reached; missing, multiple-result or
ambiguous targets block delivery.

## Approved renderer

Version 4.1.9 generates the flagship Single-Page Application (SPA) magazine layout
once from the validated bilingual canonical dataset (`scripts/spa_renderer.py`,
outputting `{artifact_slug}-travel-guide.html`). The compatibility split renderer
runs only for `full_audit` or explicit `--include-legacy-renderer`. Currency
conversion uses verified `budget_meta` rates; missing rates remain in the source
currency and are labelled unverified. One DOM/state supports both languages.
No external product template, DOM, stylesheet, script or product identity may be
used as the output foundation.

`references/theme-config.json` selects the theme. The cover uses up to three
route-relevant verified editorial stills, changes every five seconds with a slow
crossfade, and has no pause control. Reduced-motion mode stays on one still.
The configured theme image is the fallback when editorial stills are unavailable. No fake weather or markers
on stock photos. Do not claim offline readiness when required assets are remote.

`references/renderer-contract.json` maps modules to tabs. Budget is a separate
top-level tab. Notes starts with Local travel essentials, followed by topic
branches for Entry and local practicalities and the Pre-trip checklist; research sources remain grouped at
the end. Hotels, food, sights and transport use destination/route branches rather
than visually unbalanced fixed columns. Named POI rows are text-first and do not
show item photos or missing-photo boxes. Coordinates remain available to map-link
generation but raw coordinate strings and non-informative aggregate-rating status
are hidden from reader-facing planning details. Destination cover role badges are
also hidden. Preserve all records;
no silent slicing of POIs or days. Missing English translation is an issue, not
permission to call mixed-language output fully translated.

## Build and honest status

Read each script's --help before first use.

`python ROOT/scripts/gen_travel_scope.py --mode live --data RUN/dataset.json --output-dir RUN/outputs --language both --expected-days N --delivery-profile reader --artifact-slug DESTINATION-SLUG`

Formal generation also requires the existing SOP manifest gate
(`TRAVEL_SCOPE_FORMAL_RUN` and `TRAVEL_SCOPE_RUN_MANIFEST`). Set these only after
the recorded stages really ran; do not write completed flags to bypass failure.
The legacy `validate_output.py` targets retired DOM shapes and is not a valid
PASS authority for this renderer. Until a full live regression is complete,
keep the recovered release labelled recovery/research, not production-certified.

Live delivery is valid only after `delivery_gate.py` receives and passes the
unified dataset, run manifest, scope, route corridors, asset manifest, media audit
and browser visual-QA report. Required stages include media collection/contact-
sheet review, artifact generation and visual QA; stage labels without their
evidence files do not count as completion.

For local media, manifest assets require `local_file`, `poi_name`, `category`
(HOTELS/RESTAURANTS/CAFES/ATTRACTIONS/DIVE_SITES/EDITORIAL_MEDIA/SECTION_MEDIA), `source_page`, `license`,
`verification_status`, `sha256`, exact source identity fields and a distinct
run-relative `verification_evidence` file under `evidence/`. Delivery reruns the
media validator and compares dataset/manifest hashes; an old or hand-written PASS
report is not authoritative.

UI regression only: `python ROOT/scripts/test_product_recovery.py`.

Demo is never an automatic fallback. Do not use --no-strict-qa for final delivery,
or invent stops, translations or images to meet gates. Exports remain research
drafts until formal checks are completed. A file, package check or unit test is
not a completed guide.

Verify scope/exclusions, distinct route corridors, sources, day coverage, schedule
status/effective dates, actual image loading and image-role labels, language and tab
switching, record counts, map targets, the independent budget tab, Notes ordering,
and desktop/mobile layout. Compare Excel and Markdown to the same data, including
transport schedule fields. Retain input hash, product fingerprint, command, reports
and actual browser screenshots. Do not call renderer-only QA a live end-to-end
regression. Report missing required evidence explicitly.

## Maintenance

Approved release files are pinned by product-origin.json. Only reviewed release
changes may reseal it; verification never reseals automatically. Keep recoverable
backups outside the discoverable skills directory. Retired renderers and historic
instructions are not authorized fallbacks.

Every approved Skill modification increments the product version. Patch numbers
run from 0 through 99; after `4.0.99`, continue with `4.1.0` (and after
`4.99.99`, continue with `5.0.0`). Documentation, renderer contract, product
origin, installed Skill, source mirror and release package must carry the same version.
Treat `references/version-policy.json` as the machine-readable version authority.
