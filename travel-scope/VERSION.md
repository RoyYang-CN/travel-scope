# Travel-Scope v5.0.0

> **状态（业主 2026-11-05 版本身份迁移）：v5.0.0 LIMITED-SCOPE RELEASE — California zh-formal validated。**
> 一句话：**本版＝加州中文正式范围发布**，不是整体认证版。唯一机读范围合同是
> `references/release-scope.json`（`production_certified: false`、`validated_profile: zh-formal`、
> `excluded_destinations: [philippines]`、`excluded_profiles: [en-formal, en-audit]`）。
> - **加州中文正式 run 已签署通过**：业主 2026-11-04 独立复核后签署该档并判定加州链路已闭环。
>   读者成品 3,536,450 B／SHA-256
>   `55A83704B6A06FB6B8D0539EC0C7EDAC31FB2E2AB69540E49FBA27F56206DE1F`。
> - **英文面未认证（DEFERRED，不作本版门槛）**：MT-E apply／MT-F 全量双审／MT-G 重建／
>   31 处英文渲染槽位拆除移入下一迭代。本版唯一正式档位是 `zh-formal`；`en-audit` 只供审计与后续迭代，
>   **不得进入正式输出目录**。
> - **菲律宾未交付（AUDIT_HOLD／EXCLUDED）**：现场硬事实——该 run 的 manifest 声明读者件已生成、
>   `completed_stages` 仍写 `artifact_generation`，但 `outputs/` 里只有 `zero_call_ledger.json`；
>   来源快照路径缺失、媒体链 18 行仍全是绝对路径。菲律宾不得随 ZIP、Skill 安装或本文档
>   被表述成已验证样例。
> - 地图承诺按 §2 保持降级：**不保证每个地图链接打开唯一 Google 实体卡**，只保证状态如实、
>   已知错链不发布、具名搜索明确标为「搜索」。
> - **本版不声明整体 production-certified（production_certified=false）**；本文出现的
>   `production-certified` 与 `production certification` 都只用于否定句，不是认证声明。
> - 封装与安装：当前包名为 `travel-scope-v5.0.0-limited-release.zip`；Skill 安装仍是独立的用户操作，不由版本迁移自动执行。
>   这两件事**不改变**上面的范围——身份是 LIMITED-SCOPE，不是整体认证。
>
> 本目录按 `V4.2.2_ITERATION_CHECKLIST.md`（SHA-256
> `F9634F96671C9BEA55EB25C4424D5B2FCA980CDB3F506D1FE1A4E2AD7F480844`，只读未改）实施。
> 文中 `v4.2.0 / v4.2.1` 段落是从旧候选根继承来的历史开发记录与撤回对象，不代表本版能力。
> DOC-TRUTH-1 的撤回登记仍在下面那张表里，逐条有效。
>
> **v5.0.0 迁移边界**：这是新主版本的发布身份迁移，不是新的攻略内容生成。加州中文正式 HTML 继承业主已签署的 v4.2.2 字节（SHA-256 `55A83704B6A06FB6B8D0539EC0C7EDAC31FB2E2AB69540E49FBA27F56206DE1F`）；英文、其他目的地与 `production_certified=false` 状态不变。迁移来源封条、ZIP 和 HTML 摘要登记在 `references/release-scope.json::version_identity_migration`。
>
> （上一版头部原文保留不删，供对照：「> 状态（V1 版本再基线，2026-10-29）：**独立候选根，未发布、未安装、未获得 production > certification。** 本目录按 `V4.2.2_ITERATION_CHECKLIST.md`（诚实地图搜索版，SHA-256 > `F9634F96671C9BEA55EB25C4424D5B2FCA980CDB3F506D1FE1A4E2AD7F480844`）实施，是 v4.2.1 > `W3 核心架构 NO-GO-BLOCKED` 之后的新立项候选，**不继承 v4.2.1 的任何 GO／PASS 名义**；v4.2.1 > 的失实声明撤回登记（DOC-TRUTH-1）留在 v4.2.1 树与 `V4.2.1_ITERATION_CHECKLIST.md` 里，本版不复制、 > 不重述为已完成。以下条目在 V7 文档收口并经验证前一律视为**开发中记录**，不得当作验收结论；文中 > 出现 `v4.2.0 / v4.2.1` 的段落是从旧候选根继承来的历史开发记录与撤回对象，不代表本版能力。 > 本版地图产品承诺已按 §2 主动降低：不保证每个跳转打开唯一 Google 实体卡片，只保证状态如实、 > 已知错链不发布、具名搜索明确标为「搜索」。」。那一版写的是加州尚未签署时的状态；
> 现在加州中文正式 run 已由业主签署，而**整体 production certification 仍未取得**。）」

## DOC-TRUTH-1 失实声明撤回登记

| 原表述 | 实测依据 | 判定 |
| --- | --- | --- |
| Google Maps 国际查询 URL「100% 使用官方英文 POI 名与 `query_place_id=...`」 | 两棵冻结 run 合计 403 条 `map_targets`：非空 Place ID **0 条**；`identity_status` 403/403 `UNVERIFIED`；`google_resolution_status` 403/403 `NOT_OBSERVED`；`link_mode` 403/403 `NONE` | 不成立，撤回 |
| 「eradicating dead-end 'Google Maps cannot find' errors」等 Google 实体精确命中类表述 | 同上：没有任何一条 target 具备可核验的实体解析证据；渲染 DOM 与目标环境从未实测（W4–W8 STOPPED） | 不成立，撤回 |
| 「Eradication of EN Mode Chinese Leakage」/ 零中文残留 | v4.2.1 复审实测英文模式 CJK 残留 7.5%（清册 §3.2.5 判定不成立）；`required_location_role` 也仅 120/403 已定，283 条为 `None` | 过度声明，撤回为「已加门禁但仍存在残留」 |
| 「hero-only inline、其余为外链」 | 本版默认已改为全内联（单文件成品体积记录见清册 §5/§12），描述与实现相反 | 失实，撤回 |
| 本文原头部「v4.2.0 的失实声明撤回与完整变更记录在 §9 第 9 步统一补入」 | 该步骤从未执行；本节即为补入结果，头部状态已改为停止 | 已更正 |

其余绝对表述（`permanently`、`guaranteeing 100%`、`completely purges`、`Zero … permitted`、
`ensuring authentic …`）在本版未重新验收前一律按**历史声明**阅读，不作为当前能力证据。撤回依据的
数字由只读复算得出，可在 `.temp/v421_map_phase1/W3_closure/DOC_TRUTH_1/` 的哈希与命令输出中复核。



## Zero-Chinese EN Mode, Place ID Overseas Maps, Daily City Headers, Robust Route Splitting & Anti-Squish Budget Breakdown

> 本章标题里的 `Zero-Chinese` 与 `Place ID Overseas Maps` 属上表已撤回表述，仅作当时立项口径存档。

Comprehensive internationalization, geographic navigation, daily itinerary space orientation, and visual reliability release:

- **Eradication of EN Mode Chinese Leakage (P0)** — **已撤回**：门禁与词典确已落地，但「彻底根除」不成立（实测英文模式 CJK 残留 7.5%）。Embeds standard bilingual category dictionary into SPA renderer and pipeline, translating categories (e.g. `Seaview Boutique Resort`, `Cliffside Pool Villa`, `Tropical Garden Boutique Hotel`). Automatically translates POI notes and daily corridor summaries, backed by strict zero-Chinese validation gates.
- **Pure USD Currency Calculation & Anti-Squish Typography (P0)**: Standardizes `budget_meta.rates.USD` calculation contract. Completely purges `(exchange rate unverified)` disclaimer text across all card types and daily breakdown items. Adds `white-space: nowrap; flex-shrink: 0;` to `.dc-no` to permanently stop `Day 1` squishing and vertical line wrapping.
- **Daily Itinerary Destination & Theme Headers (P0)**: Upgrades timeline accordion headers to explicitly render structured destination cities and day route themes: `Day X 第X天 · 【城市/驻留地】 | 当日核心主题 (X项) +` (and clean English equivalents in EN mode), completely eliminating user disorientation in unfamiliar countries.
- **Mandatory English & Place ID for Overseas Maps (P0)** — **已撤回**：「100% 使用 `query_place_id`」与「eradicating dead-end 报错」均不成立（403 条 target 非空 Place ID 0 条、`link_mode` 全为 `NONE`）。原描述保留为工程意图记录：Enforces that Google Maps query URLs for international destinations use officially registered English POI names and `query_place_id=...` parameters where such identifiers exist. Zero Chinese characters permitted in overseas map query strings.
- **Robust Route Line Separator Regex (P0)**: Expands node split regular expression to `/→|->|\s+-\s+|—/`, fully supporting hyphenated corridor names (`旧金山 - 蒙特雷与卡梅尔 - 大苏尔...`) without collapsing routes into a single isolated dot.
- **Permanent Topbar & Language Switch Visibility (P0)**: Fixes floating island topbar positioning so that `#lang-btn` and navigation tabs are fully visible and clickable at `scrollY = 0`, eliminating element clipping and Playwright timeouts.
- **Atmosphere Reference Disclaimers (P0)**: Activates `branch_cover_role_badges: true` by default and renders explicit non-venue atmosphere badges (`目的地氛围参考图` / `Destination atmosphere — not this venue`) on reference imagery.
- **Editorial Media Route Parity (P0)**: Enforces that all `editorial_media[i].route` strictly match valid `routes[i][0]` corridor names, preventing whole-batch editorial figure loss.

# 以下条目为历史版本存档（v4.1.9 及更早）

> 自本行起的内容记录的是**旧版本当时写下的声明**，未在 v4.2.1 重新验收，不代表 v4.2.1 当前能力，
> 也不构成任何验收证据。其中的绝对表述（`100%`、`permanently`、`guaranteeing`、`completely purges`、
> `eradicating`、`ensuring authentic Google Place business cards` 等）一律按历史声明阅读。
> 保留原文而不删除，是为了让后续审计能看到声明与实测之间的原样差距。

# Travel-Scope v4.1.9

## Map Card Entity Landing, Transport Node Parameter Restoration, Hotel Vintage Badges & Custom Budget Range

Major map accuracy, transit card navigation, hotel freshness transparency, and intake contract upgrade:

- **Map Card Entity Landing & Dropped Pin Prevention (P0)**: Deprecates synthetic `/maps/place/{Name}/@{coords}` URL pattern without Place ID/CID which caused Google Maps to drop an empty coordinate pin with no business card. Prioritizes verified `google_place_id` (`query_place_id=...`) and clean Universal Search API (`/maps/search/?api=1&query={Name},+{Dest},+{Country}`) without coordinate hijacking, ensuring authentic Google Place business cards render directly.
- **Transport Card Departure/Arrival Parameter Restoration (P0)**: Resolves regression in `spa-layout.js` `transfersBlock` where `mapLinks` was passed `x[2]` (duration string: "1.5小时") and `x[3]` (distance string: "53公里") instead of `x[12]` (`fromLoc`) and `x[13]` (`toLoc`), fully restoring departure/destination terminal names and navigation deep links for ferries, flights, and charters.
- **Hotel Vintage & Renovation Badges and Quick Filter (P1)**: Extracts `open_year` and `renovate_year` in `spa-layout.js` to render visual vintage status badges (`✨ {year}全新开业`, `🛠️ {year}全面焕新`) on hotel cards, and adds an interactive quick filter toolbar (`[全部住宿] [✨ 2020+次新/焕新]`) allowing users to easily isolate modern and recently upgraded accommodations.
- **Intake Q3 Budget Brackets & Custom Range Support (P1)**: Enriches questionnaire Q3 options with explicit CNY price brackets (`经济实用 (¥300以下/晚)`, `中档舒适 (¥300~600/晚)`, `品质轻奢 (¥600~1200/晚)`, `高端奢华 (¥1200以上/晚)`), and implements `parse_custom_budget_range()` to flexibly handle natural user inputs like `350~900`, `¥500-1000/晚`, or `每晚不超过800元`.
- **Visual QA SPA Artifact Detection Hardening (P1)**: Enhances `visual_qa.py` to identify `*-travel-guide.html` as the authoritative SPA artifact and record its checksum in `html_sha256["spa"]`, closing validation gap for reader delivery profiles.

# Travel-Scope v4.1.8

- Run initialization is driven by `delivery_profile` and required `artifact_slug`; its generation command and expected artifact list now match reader, review and full-audit output exactly.
- Formal artifact generation rejects missing or invalid slugs instead of inventing `travel-guide`.
- Every formal map target requires `entity_type`; POIs and transport nodes must be `named_entity`, whose Google URL cannot be a pure coordinate query.
- SPA currency conversion has no fixed-rate fallback. Missing rates retain CNY or local currency and show an unverified-rate label.
- Executable regressions cover all delivery profiles, browser-rendered DOM, final map hrefs and missing-rate behavior.

# Travel-Scope v4.1.7

## Contract Hardening, Named Entity Map Landing, Authoritative Single SPA & Streamlined Output Profiles

Major data contract, map landing authenticity, and delivery profile streamlining release:

- **Data Contract & Zero `[object Object]` (P0)**: Formalizes `route_budgets` object schema (`total_cny`, categorized breakdown, and summary); `spa_renderer.py` and `spa-layout.js` explicitly extract `total_cny` and fail-fast on corrupted structures; `money()` strictly validates numeric inputs and eliminates `[object Object]人均`.
- **Named Entity Map Card Landing (P0)**: Strictly distinguishes `named_entity` from `coordinate_landmark`; hotels, restaurants, cafes, sights, and transit hubs prioritize verified Google Place URLs, Place IDs, and English entity search queries with coordinates strictly as map view centers (`ll`), permanently stopping named businesses from landing on anonymous dropped pins.
- **Authoritative Single-Stage SPA Generation (P1)**: Decouples SPA generation from bilingual legacy loops, producing exactly one authoritative `{artifact_slug}-travel-guide.html` from canonical validated data.
- **Streamlined Delivery Profiles & ASCII Slugs (P1)**: Implements `--delivery-profile` (`reader` by default, `review`, `full_audit`); cleans user delivery to an ASCII kebab-case slug; eliminates redundant legacy Excel/Markdown duplication in reader mode while preserving 100% of underlying research data and evidence.
- **POI Card Decluttering (P1)**: Completely removes the redundant `.poi-details` / "规划详情" accordion from reader-facing SPA cards, keeping focus on core experience while preserving research fields in datasets and review workbooks.
- **Dynamic Rates & Safe Store Links (P1)**: De-hardcodes all static exchange rates in favor of dynamic `dataset.budget_meta`; hardens official App Store and Google Play details page URLs with `rel="noopener noreferrer"`.

# Travel-Scope v4.1.6

## Mobile Navigation Enhancement, Full Parity with Classic Split-v1, Universal De-Hardcoding & Hero-Only Inline Media

Major correctness, mobile ergonomics, and architectural de-hardcoding release:

- **Mobile Navigation Ergonomics (P1)**: Adds gradient fade masks to `.tabs` and `.route-pick`; implements `selectTab()` auto-centering via `scrollIntoView({inline:'center'})`; transforms `.route-line` route corridor nodes into a vertical timeline on narrow viewports ($\le 768px$), eliminating awkward mobile horizontal scrolling.
- **Hero-Only Inline Media Delivery (P1)**: `spa_renderer.py` now inlines only the route cover hero images as Base64 Data URIs (`hero-only inline`) by default, guaranteeing 100% immediate first-frame cover rendering during site deployment while keeping all auxiliary images as lightweight external links.
- **Universal Hardcoding Elimination (P1)**: Completely purges all destination-specific Indonesian/Bali hardcoded strings from universal SPA engine: removes `巴厘文化海岸深度线` from budget breakdown, eliminates hardcoded Bali ferry booking URLs (`sanur/nusa-penida`) and Grab `/id/` paths in transport links, and de-hardcodes static `2026年2月` from budget notes.
- **Parity with Classic Split-v1 Restored (P1)**:
  - **Overview Destinations & Coverage**: Restores `destinationsBlock()` displaying destination climate, timezones, currency, languages, and gateway ports/IATA codes, alongside `coverageBlock()` summarizing multi-category coverage depth.
  - **Transfers Deep Links & Schedules**: Prioritizes verified official timetables (`row[20]`) and direct booking portals (`row[21]`), restores outbound/return schedule times (`row[22]`/`row[23]`), buffer times (`row[9]`), and official dispatch counters (`row[10]`).
  - **POI Planning Details**: Restores collapsible `<details class="poi-details"><summary>规划详情</summary>` on hotel, food, sight, and dive cards for duration, booking advice, and verified ratings.
  - **Budget Daily Breakdown**: Restores full daily spend breakdown (`#budget-daily`) dynamically aligned with the primary route.
- **TBD Dates & Day Normalization (P1)**: Suppresses redundant repeated "未定日/TBD" date badges across timeline cards, presenting clean `DAY 1` ~ `DAY X` and preventing `DAY Day 1` string concatenation defects.
- **Map Navigation Hardening (P1)**: Coordinates-first pin fallback guarantees 100% accurate pinning without zero-hit white screens; strips Chinese characters from destination queries on international mapping engines.

# Travel-Scope v4.1.4

## SPA Money Parser Source Restore, Reader Evidence Anti-Fabrication, SPA Gate Coverage & Non-Destructive Delivery Gate

Independent-audit-driven correctness release closing systematic false-PASS and version-chain gaps:

- **SPA money() source restore (P0)**: Backports the validated range/PHP/free-aware `money()` parser into `assets/spa-layout.js` (replacing `Number(cnyVal) || 0`), so `550-1000`, `30比索`, `免费` render correctly from the generator, not just in one delivered HTML.
- **Reader-facing source_evidence anti-fabrication gate (P0)**: `formal_data_gate.py` now validates the reader-facing `source_evidence` list (not only `source_evidence_meta`) — blocking fabricated TripAdvisor URLs lacking `-g\d+-d\d+`, and orphan/ghost entities whose evidence exists but no longer maps to any hotels/restaurants/cafes/attractions/dive row.
- **SPA delivery & visual QA coverage (P0)**: `delivery_gate.py` adds `*重构版.html` to artifacts, API-key scan, cross-artifact checks, and a money() regression check; `visual_qa.py` adds a dedicated SPA smoke check (8-tab nav, no `¥0`, localized categories, no horizontal overflow) plus a 1920×1080 viewport (six viewports total) and a `spa` SHA256 fingerprint.
- **Non-destructive delivery gate (P0)**: Removes `formal_data_gate.json` / `MEDIA_AUDIT.json` / `delivery-visual-rerun.json` from the stale-purge list so re-running the gate no longer deletes evidence.
- **Map search-URL demotion (P1)**: `map_contract.py` rejects `verified_coordinate` / `verified_place_id` targets whose `google_url` is a bare `maps/search` link without `&ll` coordinates; SPA renderer appends `&ll=` to verified-coordinate fallback links.
- **Version-chain hygiene (P0/P1)**: `init_run.py` reads version from `product-origin.json`, uses real timestamps, correct artifacts list (no `单文件离线版.html`), and a correct generation command; `formal_data_gate.py` rejects generation commands referencing older `travel-scope-v*` versions and reconciles `exact_dates_confirmed` against the intake date specificity.
- **Local toolkit category localization (P1)**: `spa-layout.js` renders app-category badges from a localized label map instead of raw uppercase enum keys.
- **Carousel limit unification (P2)**: Removes the conflicting top-level `hero_carousel_max_items` (5) in favor of the single `max_route_images: 3`.

# Travel-Scope v4.1.3

## Mobile Offline Resilience, iOS WebKit Positive Stacking Fix, Dynamic Themed SVG Fallback & Standalone Base64 Delivery

Mobile device rendering and offline single-file distribution release:

- **iOS Safari / WebKit Positive Stacking Context (P0-1)**: Eliminates negative `z-index` (-2, -1) on `.cover-bg` and `.cover:before` within `isolation: isolate`, establishing natural positive compositing (`cover-bg: 0` -> `overlay: 1` -> `content: 2`). Completely resolves cover background disappearance on iOS Safari and mobile WebKit.
- **Dynamic Themed SVG Placeholder & Error Fallback (P0-2)**: Introduces `makePlaceholderSvg()` and automatic `error` event handlers on all `<img>` elements and the cover background. When single `.html` files are shared to mobile devices without accompanying `assets/` folders or offline, missing images gracefully fall back to branded, destination-themed vector cards instead of broken image icons.
- **Tab Switch Lazy-Loading Awakening (P1-1)**: Enriches `selectTab()` to automatically unblock and awaken lazy-loaded images inside newly activated panels, preventing WebKit hidden-container opacity traps and intersection deadlocks.
- **Configuration-Driven Standalone Base64 Delivery (P1-2)**: Introduces `spa_media_delivery_mode` ("standalone" vs "linked") in `spa_renderer.py`. In standalone mode, automatically encodes local hero and editorial images into Base64 Data URIs, producing a truly self-contained single-file HTML deliverable for WeChat/AirDrop mobile distribution.
- **Four-Tier Version Synchronization (P1-3)**: Synchronizes release version 4.1.3 across `version-policy.json`, `provenance-policy.json`, `renderer-contract.json`, and `formal_data_gate.py`.

# Travel-Scope v4.1.2

## UI Refinement, WCAG AA Accessibility, WAI-ARIA Navigation, Token Consolidation & Print Roadbook

UI polish and accessibility enhancement release:

- **WCAG AA Color Contrast Compliance (P0-1)**: Deepens `--muted` to `#525E64`, `.chart .meta dt` to `#4E5B63`, and `--teal` / `--accent` to `#2A7080`, achieving $\ge 4.5:1$ contrast ratio across all light background surfaces.
- **OS Dark Mode Control Tearing Elimination (P0-2)**: Injects `<meta name="color-scheme" content="light">` and CSS `color-scheme: light` to prevent OS Dark Mode from rendering dark system scrollbars on light parchment pages.
- **WAI-ARIA Tab Specification & Keyboard Navigation (P1-1)**: Implements `aria-controls`, `aria-labelledby`, and `ArrowLeft` / `ArrowRight` / `Home` / `End` keyboard navigation across the 8-tab switcher.
- **Token Isolation Elimination (P1-2)**: Consolidates hardcoded component radii to `--radius-sm` (8px), `--radius-md` (12px), `--radius-lg` (16px), `--radius-xl` (22px), `--radius-pill` (999px), and unifies card micro-borders to `1px solid var(--line)`.
- **Mobile 44px Touch Targets & Scroll Snap (P1-3)**: Expands interactive button touch targets to Apple HIG minimum 44px on mobile viewports; adds `scroll-snap-type: x mandatory` to route picker.
- **Print Roadbook Optimization (P1-4)**: Enhances `@media print` with non-essential widget hiding, automatic `<details>` full expansion, and `break-inside: avoid` page-break protection.
- **10px Minimum Font Size Floor (P2-1)**: Enforces `font-size: max(10px, ...)` across all auxiliary tags and labels, preventing blur on low-DPI displays.
- **Async Image Decoding & Decorative Asset Semantics (P2-2)**: Applies `decoding="async"` to all images and `aria-hidden="true"` to cover background images.
- **Pure CSS Smooth Transitions & Motion Reduction Guarantee (P2-3)**: Implements lightweight CSS transitions with strict `@media (prefers-reduced-motion: reduce)` cancellation for visual QA stability.

# Travel-Scope v4.1.1

## SPA Payload Restoration, Transport Contract Parity, Gate Hardening & Multi-Platform Reconciliation

Patch release fixing SPA flagship edition rendering crash, transport column alignment, cross-category media deduplication, and production gate false-positives:

- **SPA Payload & Route Budgets Restoration (P0-1)**: Enriches renderer payload with `route_budgets` and `duration_days`; hardens `spa-layout.js` with optional chaining to prevent white-screen crashes.
- **Release Provenance & Version Alignment (P0-2)**: Resolves provenance-policy target version divergence across four authoritative release manifests.
- **Transport Contract & Geo-Coordinate Gate (P0-3)**: Standardizes 24-column transport matrix schema; mandates `parse_coords()` verification for departure/arrival coordinates, intercepting column drift into Excel.
- **SPA Contract Adapter Layer (P1-1)**: Normalizes route columns, daily budget indexing, and accommodation legend aliases in `spa_renderer.py` without mutating client state machine.
- **Dead Code Cleanup (P1-2)**: Eliminates legacy inline rendering dead code in `gen_travel_scope.py`.
- **Delivery Gate Self-Attrition Prevention (P1-3)**: Preserves explicitly passed audit and visual QA reports during stale file cleanups.
- **Ctrip Singular Route Pattern Support (P1-7)**: Extends G10 regex to recognize domestic `/hotel/{id}.html` canonical structures.
- **Global Media Deduplication Gate (P2-1, P2-5)**: Unifies editorial and section media byte checks into a single authoritative deduplication pool.

# Travel-Scope v4.1.0

## Production Gate Hardening, Multi-Platform Synthetic URL Ban, Schema Parity & Excel Numeric Exporter

Major release eliminating synthetic international platform URLs, out-of-bounds coordinate drift, schedule hallucinations, and export column index mismatches:

- **Anti-Synthetic International Platform Gate (G10)**: Enforces strict canonical structure validation for TripAdvisor (`g\d+-d\d+`), Booking, and PADI, preventing programmatic or LLM-generated fake URLs.
- **Physical Bounding & Distance Fence (G1)**: Audits POI coordinates against destination geographic centroids ($\le$ 60km, with explicit airport/port whitelisting) to prevent cross-region entity confusion.
- **Schedule Truthfulness & Bidirectional Anti-Symmetry Gate (G2)**: Intercepts reverse transit flights, prohibits artificially symmetric bidirectional schedules, and flags repetitive equal-interval departure grids.
- **Cross-Artifact Reconciliation Gate (G4)**: Enforces automated machine reconciliation across HTML, XLSX, and Markdown deliverables for fares, budgets, and POI counts before release.
- **Excel & Markdown Route Alignment (R1, PHL-3)**: Resolves route matrix column offset where duration, features, audience, and transit were misaligned; guarantees schema-renderer parity for destination overviews.
- **Numeric Excel Cell Exporter & Clean International Schema (R3, R4)**: Excludes empty domestic-only columns from international runs and casts price, score, and count cells to native numbers for spreadsheet calculations.
- **Local Currency & FX Three-Field Contract (G8)**: Mandates `fare_local_currency`, `fare_local_value`, and `exchange_rate_cny` across transport and ticket datasets.

# Travel-Scope v4.0.16

## Google Maps Place Entity Card Direct Navigation & Multi-Tier Landing Fallback

This release resolves the Google Maps coordinate-only regression by establishing a four-tier entity landing pipeline:

- **Verified Google Place URL Direct Landing**: Pre-indexes `D.map_targets` (379/379 points in Indonesia) to directly open official `/maps/place/{Name}/@{coords},17z` URLs, immediately surfacing hotel/restaurant/attraction photos, reviews, stars, and business cards instead of bare lat/long numbers.
- **Place ID Deep Link Fallback**: When place URLs are unavailable but `google_place_id` is verified, constructs official `query_place_id` search deep links.
- **Entity & Geographic Context Composite Search**: Prevents bare coordinate queries; combines `[en_name || local_name, destination, country]` to ensure Google Maps searches for the named business rather than generic geocoding.
- **Apple Maps Native Dual-Parameter Query**: Passes both `q={name}` and `ll={coords}` so Apple Maps displays the business name pin at the exact GPS coordinate.

# Travel-Scope v4.0.15

## SPA Architecture Merging, Magazine Editorial Layout, Smart Scroll Navbar, Real-Time Dual-Currency & Precision Maps

This release merges the high-taste SPA architecture into the official Travel-Scope delivery pipeline and resolves nine critical UI/UX details:

- **SPA Architecture & Magazine-Grade Editorial Layout**: Embeds 100% loss-free structured dataset within `<script id="dataset" type="application/json">`, enabling instant bilingual toggling, dynamic route recalculation, and smooth panel transitions.
- **Smart Scroll Navbar (0.2s Fast Slide-Down)**: Hides at the cover top, sliding down in 0.2s upon scrolling past the 120px threshold.
- **Segmented Sub-Navigation (Sub-Tabs)**: Introduces in-panel secondary sub-navigation for direct jumps across daily itineraries, destination branches, and utility categories.
- **Full 12-Day Itinerary Restoration**: Resolves day indexing to properly group and display all 12 days and 238 itinerary items.
- **Real-Time Dual-Currency Engine (CNY/USD)**: Dynamically calculates and formats currency in CNY (¥) or USD ($) upon language toggle (1 USD ≈ 7.20 CNY).
- **Actionable 3-Tier Transport Booking**: Surfaces direct booking links for Grab, Gojek, Traveloka, 12Go, airlines, and fast boats.
- **Surfaced App Store / Google Play Shortcuts**: Direct store pills on card surfaces, reserving prominent "Official Portal" buttons for web-only services.
- **Precision Coordinates for Google & Apple Maps**: Directly pins latitude and longitude, eliminating invalid parameters and regional search drift.
- **Cascade Translation Engine**: Seamlessly leverages `D.en_text_replacements` to eliminate CJK residue in English mode. — **条数声明已撤回（DOC-MTD2-COUNT-1，业主 2026-11-01 授权一次窄幅修正）**：本行原括号里的固定「2,129 items」失实，本轮不复换成另一个永久数字。legacy replacement 的条数随 run 与 build 投影变化；2026-11-01 在 CA/PH 两份冻结样本上实测为 run 输入面 835 条（CA 16／PH 819）、读者载荷面 1,017 条（CA 111／PH 906）。这两个数是**冻结样本的测量值**，不是产品合同常数，也不构成「这张表应当有多少条」的判据。逐条账见 `.temp/v422_honest_map/MT1_translation/artifacts/MTD2_LEGACY_MIGRATION.json`（双面清册）与 `references/prose-translation-contract.json::ownership.legacy_en_text_replacements`。

# Travel-Scope v4.0.14

## Dual Currency Conversion, 3-Tier Transport Links, Store Pill Buttons & Hero Carousel 5-Photo Limit

# Travel-Scope v4.0.13

## Release Provenance Sandbox, Anti-Contamination Gate, Bilingual Headline Naturalness & Themed Capsules

This release establishes strict isolation and UX refinements identified during the multi-destination review:

- **Release Provenance & Anti-Contamination Sandbox (`provenance_contract.py`)**: Mandates absolute root anchoring for all run manifests and evidence trees. Banned cross-version paths (`v4.0.10`, `v4.0.11`) and external path references trigger immediate hard gate failure. Disallows conflicting dual delivery reports (`evidence/delivery_gate.json` vs `outputs/delivery-gate.json`), standardizing on a single authoritative output gate report.
- **Bilingual Headline Naturalness Engine**: Resolves array index mismatch where route name was misparsed as duration. Generates clean, fluent headlines without duplicated country tokens or bare `-Day` fragments (`{country} · {days}天{theme} · {route_name}` / `{country} · {days}-Day {theme} · {route_name_en}`).
- **Themed Capsules & Lightweight Contextual Shortcuts**: Eliminates intrusive full-width pale shortcut banners. Replaces single-app occurrences with inline section title badges (`外卖 · Foodpanda ↗`), and 2-3 apps with module-themed compact capsules matching the module's color palette, plus "View All (N)" links for larger sets.
- **Progressive Disclosure for Local Toolkit**: Redesigns toolkit cards into a clean summary tier (Name, Status Badge, 1-line use case, Primary CTA button) with expandable `<details>` for regional boundaries, limitations, payment notes, and secondary links.
- **Multi-Viewport Mobile QA**: Enforces responsive validation across 4 key mobile/tablet viewports (360px, 390px, 430px, 768px) with active-tab auto-centering and horizontal scroll fade hints.

# Travel-Scope v4.0.12

## Local Toolkit (在地工具), 8-Tab Navigation, App Contract Verification & Multi-Artifact Parity

This release introduces the dedicated Local Toolkit architecture, integrating verified destination mobility, utility, communication, and official services into a unified, configuration-driven experience:

- **Dedicated Local Toolkit Navigation (8 Tabs)**: Introduces the `local_toolkit` top-level tab positioned between `budget` and `notes` (`Overview → Stays → Food → Sights → Transport → Budget → Local Toolkit → Tips`). Includes "Pre-trip Essentials" spotlight cards and category-grouped drawers (mobility, dining, transit, communication, safety).
- **Configuration-Driven Policy & App Contract (`app_contract.py`)**: All 14 application categories, 5 operational lifecycle states (`verified_active`, `conditional`, `regional`, `pending`, `retired`), store domain regexes, and freshness windows (`mobility_app`: 30d, `utility_app`: 90d, `official_service`: 180d) are governed by `references/local-apps-policy.json`. Hard blocks unverified search result URLs, third-party APK mirrors, and retired applications.
- **Cross-Artifact Parity & Zero CJK Leakage**: HTML interactive cards, Excel workbooks (`常用APP` / `Local Apps`), and Markdown reports (`## 在地工具` / `## Local Toolkit`) synchronize with strict zero-discrepancy parity. English versions enforce strict translation parity with zero CJK residue.
- **Contextual Shortcut Integration**: Seamlessly embeds validated ride-hailing/transit shortcuts into Transport, food delivery/discovery into Food, accommodation checkers into Stays, and safety/SIM advisories into Tips without data duplication.
- **Thailand Validation Reference**: End-to-end field verification against Thailand travel ecosystem (`fixtures/thailand_local_apps.json`), including Grab, LINE MAN, Wongnai, 12Go, Bolt (conditional status), and Tourist Police 1155.

# Travel-Scope v4.0.11

## End-to-End English Artifact Scan, Route Claims Contract, Resolved Map Landing Verification & Transparent Anti-Scraping Pending

This release closes systematic delivery vulnerabilities and data truth regressions identified during the multi-route Philippines field audit:

- **End-to-End English Artifact Quality Scan**: `delivery_gate.py` extends strict automated text audits to final outputs (`*en.html`, `*en.md`, `*en.xlsx`). Replaces porous dataset-only checks with full-text scanning, instantly flagging synthetic word outbreaks (e.g. 3,482 `area` placeholders, `12 days 11 area`), broken grammar patterns, and CJK text leakage (>0.1%).
- **Route Claims Contract (`route_claims`)**: Enforces configuration-driven title-corridor-media alignment. Title destination claims must be a strict subset of `corridor_sequence` (e.g. rejecting "Visayas & Palawan" titles lacking Palawan stops), and binds route media strictly to destinations in that corridor without off-corridor leakage.
- **Resolved Map Landing & Anti-Template Address Gate**: `map_contract.py` demotes plain `/maps/search/?query=...` URLs to `search_candidate`, mandating genuine entity landing URLs (`/place/...`, Place ID, CID). Detects and blocks templated fake addresses (e.g. `Premises, ... Coast Rd`).
- **Transparent Anti-Scraping Status (`pending`)**: Sources blocked by anti-scraping (403, Cloudflare, Captcha) must be marked `pending` rather than masquerading as `verified`. Requires explicit HTTP status, page title, and canonical path checks (e.g. PADI `/dive-site/`).
- **Operating Schedule Staleness & Historical Marking**: Transit timetables exceeding operating season limits (>180 days or older year publications like 2023) are barred from `exact_date_verified` or current seasonal labels, mandating explicit `historical_reference` tags.
- **Test Suite Decoupling**: Refactors Guangxi regression tests into standard `unittest.TestCase` format, resolving pytest missing `data_dir` fixture errors.

# Travel-Scope v4.0.10

## Coordinate Query Interception, Route Flow Connector Repair, Hero Carousel 3-Image Fallback & Theme Configuration

This release closes systematic false-positive PASS vulnerabilities and UX regressions identified during the Philippines island field audit:

- **Coordinate Query Interception (`verified_platform_url`)**: `map_contract.py` strictly blocks platform URLs that resolve merely to raw coordinate queries (`?q=lat,lng` or `ll=`), terminating coordinate masquerading as named entity pages. Named POIs must link to bona fide place pages or Place IDs.
- **Route Flow Connector Repair**: `split-layout.js` expands delimiter regex (`/\s*(?:→|->|—|-|>)\s*/`) and prioritizes structured arrays (`corridor_sequence`), fixing the regression where hyphenated corridors collapsed into a single node "1" with vanished connectors.
- **Hero Carousel 3-Image Fallback Guarantee**: `selectedHeroItems()` cascades from route-specific media to corridor matches and destination candidates, guaranteeing a full 3-slide carousel (`hero_carousel_slides: 3`).
- **Translation Quality Hard Gate**: `formal_data_gate.py` and `visual_qa.py` strictly ban synthetic placeholder repetitions (`Spot Spot`, `days ... Spot`) and block delivery if untranslated vocabulary files (`untranslated.json`) are detected.
- **Stale Report Hash Invalidation**: `delivery_gate.py` cascades SHA256 fingerprints across `media_audit` and `visual_qa_report`, instantly failing expired reports upon dataset changes.
- **Configurable Island Theme Palette**: `theme-config.json` and `split-layout.css` introduce midnight navy (`#0B2239`), deep ocean blue (`#183C55`), mist blue (`#3F83A3`), pearl sand gold (`#C8B28E`), warm ivory (`#F4F0E8`), and card background (`#FCFBF8`), removing hardcoded drab dark green.

# Travel-Scope v4.0.9

## Anti-Arithmetic Progression IDs, Self-Drive Semantics, Self-Cloning Map Interception & Provenance Integrity

This release closes systematic false-positive PASS vulnerabilities identified during multi-region field audits (Guangxi, Malaysia, Hulunbuir):

- **Anti-Arithmetic Progression URL Synthesis**: `formal_data_gate.py` detects arithmetic/stepping ID generation (e.g. constant +173 or +281 offsets) and blocks bulk synthetic URLs.
- **Self-Drive Transportation Semantic Enforcement**: Strictly disallows fixed timetables (`08:00`, `10:00`) or public transit statuses (`published_reference`) under self-drive / rental modes, mandating `on_demand`.
- **Anti-Self-Cloning Map Verification**: `map_contract.py` bans QA records that simply echo input names and coordinates without external platform landing metadata (`place_id`, `uid`, `amap_id`, `landing_url`).
- **Unified Product Provenance**: Synchronizes and seals authoritative release tree, ensuring exact byte-for-byte SHA256 integrity across local build, release zip, and installed skill.

# Travel-Scope v4.0.8

## Anti-Sequential Numbering, Map Physical Landing Verification, Domain-Role Alignment & Mobile Viewport Polish

This release closes systematic false-positive PASS vulnerabilities identified during the Malaysia nationwide field audit:

- **Anti-Sequential Numbering & Synthetics**: `formal_data_gate.py` bans continuous auto-incrementing numbered paths (e.g. `my-kuala-lumpur-0001`, `-[0-9]{3,6}(\.html)?$`), terminating counter-pattern evasions.
- **Domain-Category Role Alignment**: Stems mismatched source borrowing (e.g. transit operators like MyRapid acting as hotel or restaurant citations).
- **Physical Map Landing Verification**: `map_contract.py` mandates explicit third-party physical landing resolution (`resolved_name`, `resolved_address`) and bounds coordinate drift to $\le 0.001^\circ$ (~100m).
- **Delivery Gate Stale-Artifact Purge**: Cleans up lingering run artifacts, review notes and preflight reports, preventing cross-stage WARN leakage.
- **Mobile First-Screen Viewport Polish**: Fixes responsive media card heights and padding on mobile viewports (375px/390px/430px), eliminating blank space.

# Travel-Scope v4.0.7

## Cross-Regional False-Positive Hardening, Physical Entity Verification & Bilingual Preservation

This release eliminates systematic false-positive PASS vulnerabilities identified during multi-destination field audits (e.g. Hulunbuir & Guangxi):

- **Anti-Unencoded/Patterned Chinese URLs**: `formal_data_gate.py` and `run-quality-policy.json` strictly ban direct Chinese path fabrication (`re.search(r"[\u4e00-\u9fff]", parsed.path)`) and enforce platform-specific canonical ID patterns (Ctrip hotel/sight numeric IDs, Dianping shop alphanumeric IDs).
- **Physical Map QA Point-by-Point Audit Records**: `map_contract.py` mandates that referenced `qa_evidence` JSON files must contain explicit, verifiable point records matching target keys or canonical names, disallowing empty or placeholder QA files.
- **Accommodation Base Transfer Check**: Blocks silent overnight relocation without corresponding inter-destination transit corridor entries (`enforce_base_deduction_transit_check`).
- **Semantic Purpose & Excluded Destination Filtering**: `local_media_gate.py` prevents cross-purpose asset assignment (e.g. railway stations/bridges acting as hotels) and enforces `destination_exclusion` to block out-of-scope nearby cities.
- **Bilingual Non-Destructive Preservation**: `gen_travel_scope.py` completely overhauls text translation in Excel exports, preventing destructive substring replacements of long descriptive sentences and single-character terms.

# Travel-Scope v4.0.6

## Geographic Semantic Truth & Cross-Country Media Contamination Interception

This release closes critical reality vulnerabilities where agents borrowed foreign media assets (e.g. Thai temples in Chinese grassland guides) to satisfy local asset quotas while bypassing gates:

- **Geographic Semantic Media Gate**: `local_media_gate.py` and `media-policy.json` strictly enforce `geographic_consistency`. Media titles, page sources, asset URLs and captions are evaluated against cross-country contamination markers (e.g., foreign country names, prominent out-of-scope landmarks), immediately blocking cross-border media hijacking.
- **Strict Entity-Origin Mapping**: Disallows reusing foreign cached media packages across distinct geographical jurisdictions.
- **Synchronized Product Verification**: Updates release fingerprint, package tests and mirrors.

# Travel-Scope v4.0.5


## Anti-Synthetic Evidence, Map QA Physical Proof, Route Budget Integrity & Domestic Map Precision

This release closes critical reality vulnerabilities identified in v4.0.4 where programmatic synthetic entity URLs, missing map QA files, and shared unverified route budgets produced false PASS results:

- **Anti-Synthetic Evidence URLs**: `formal_data_gate.py` strictly bans patterned/synthetic URLs (e.g. `/entity/\d+(\.html)?`) programmatically assembled without actual verification.
- **Physical QA Evidence Enforcement**: `map_contract.py` mandates that all `qa_evidence` file references must resolve to real, existing files on the local filesystem containing verified audit records, eliminating ghost verification paths.
- **Route Budget Card Linkage & Independence**: Candidate routes with divergent stated budgets must provide distinct, balanced `route_budgets` breakdowns matching their respective route cards, preventing multi-thousand CNY calculation discrepancies.
- **Multi-Destination Scope Depth Threshold**: Corrects research depth threshold enforcement so that destinations $\ge 3$ mandate the 180 POI depth threshold across both `country` and `custom_area` / regional scopes.
- **Domestic Map Precision & Bilingual Localization**: Verified mainland China coordinates generate deterministic Amap and Baidu high-precision Marker URLs instead of fuzzy keyword search queries. Frontend map action buttons now support clean English labels (`Amap Location ↗` / `Baidu Maps Location ↗`), and mainland Excel exports strictly disallow Google Maps links.

# Travel-Scope v4.0.4

## Unified Gate Convergence, Map Contract Alignment, Route Continuity, Multi-Budget & Bilingual Parity

This release resolves the critical reality loopholes identified in v4.0.3 where false gate PASS results, map query degradations, schedule fabrications, and translation corruptions previously occurred:

- **Delivery Gate Atomic Convergence**: `delivery_gate.py` now purges stale report artifacts before execution, atomically synchronizes `outputs/formal_data_gate.json`, eliminates redundant unverified dummy reports (`MEDIA_AUDIT.json`), and mandates 100% cryptographic SHA-256 fingerprint consistency across `input_sha256`, `product_fingerprint`, media audit, and visual QA reports.
- **Unified Map Navigation Contract**: Completely eliminates pure coordinate query degradation (`query=lat,lng`). Level 3 navigation links consistently retain full geographic entity identity (`query={name}, {city}, {country}`) across Google Maps and Apple Maps, harmonizing truth tests and UI actions.
- **Route Continuity, Airport Anchors & Accommodation Locking**: Guarantees zero topological teleportation across days (e.g. Amphawa-Bangkok transit leg restored), anchors Day 1 arrival and Day 10 departure to international airport hubs, and locks continuous stays in the same city to a single recommended property to prevent unnecessary daily packing and moving.
- **Independent Route Budgets & Currency Truth**: Each candidate route features an independent, fully balanced 10-day budget with explicit currency metadata (`currency: "THB"`, `exchange_rate_cny: 0.205`), eliminating mixed currency confusion and zero-tolerance sum mismatches.
- **Current Reference Schedules**: Future transit without published timetables is explicitly designated as `current_reference_schedule` with baseline reference periods and mandatory pre-trip recheck notices.
- **Excel Named Field Mapping & Translation Integrity**: Restores exact 24-column transport field mapping, removes destructive global regex replacements that produced boilerplate ("Verified Service") text, and enforces structured bilingual entity rendering.

# Travel-Scope v4.0.3

## Authenticity Gates, Place ID Truth, Route Rhythm, Budget Linkage & Unified State

This release closes critical reality loopholes where synthetic images, fake Place IDs, unreleased future schedules, and budget imbalances previously bypassed gates:

- **Media Authenticity & Color Perception**: Added algorithmic color entropy ($H \ge 4.5$) and dominant color ratio ($\le 0.40$) gating in `local_media_gate.py`. Synthetic wireframes, flat canvases, and boilerplate audit templates are strictly intercepted with zero false passes.
- **Honest Missing Fallback**: Missing media must use `designed_no_photo_state` instead of generating synthetic images or fake source links.
- **Map & Place ID Truth**: Strictly prohibits generating synthetic Place IDs (`ChIJ_th_*`, etc.) or claiming provider IDs when `provider_api_used: false`. All map targets must resolve to physical coordinates and concrete stations/terminals.
- **Itinerary Rhythm & Anti-Duplication**: Enforces consecutive city-change limits (max 2 consecutive days under moderate pace) and bans duplicate POIs within the same route.
- **Budget Mathematical Linkage**: Strict arithmetic validation ($\sum \text{daily items} \equiv \text{subtotals} \equiv \text{grand total}$ with zero tolerance).
- **Transport & Dynamic Facts**: Future unreleased timetables cannot claim `exact_date_verified`; must be flagged as current reference with pre-trip recheck notice. On-demand transit cannot exhibit fictitious departure times.
- **Natural Copywriting**: Replaces mechanical title prefixes with natural Chinese and English headlines.
- **Automatic Intake Interaction**: Immediately prompts for structured Q0–Q8 intake upon initial invocation.

# Travel-Scope v4.0.2

## Entity-truth, map-target and media-evidence repair

This patch retains the v4.0.1 intake contract and repairs systemic failures found
in an independent Thailand international run.

- Live POIs require structured direct-entity evidence; search pages and generic homepages no longer count.
- Research depth now changes independent-source and per-entity cross-review requirements, not only record counts.
- Live map buttons require structured, verified map targets; pseudo Place IDs and ambiguous search candidates fail.
- Itinerary coordinates must bind to the actual POI or a verified transport endpoint.
- Timetable claims require a specific schedule source, validity and checked date.
- Wikimedia collection records exact API page identity, original asset URL and SHA256, and cannot self-approve visual fit.
- Delivery reruns media validation and fingerprints the dataset and asset manifest instead of trusting a stale PASS report.
- `audit_run.py` audits `dataset.json` as well as legacy `data_payload.json`.
- Overseas Live research and ordinary map links remain no-key; missing supplier keys never silently selects Demo.

The following v4.0.1 capabilities remain part of this release:

- Conversational Q0-Q8 intake; default bilingual delivery and AI route recommendation do not consume questionnaire slots.
- Nationwide discovery and route comparison for country requests.
- Verified hotels, restaurants, cafes, sights, transport and practical content.
- One run-local dataset shared by bilingual HTML, Excel and Markdown.
- Seven-section HTML navigation with independent Budget and Notes led by Local travel essentials.
- Reader-facing product copy is factual and Travel-Scope-owned: Key experiences, Local chains and convenient options, Entry and local practicalities, and Pre-trip checklist replace inherited lifestyle labels across HTML, Excel and Markdown.
- Transport schedule acquisition covers flights, trains, ferries, buses, shuttles and connections with explicit validity/status fields.
- Exact-place, category-reference and destination-atmosphere roles remain explicit in evidence; reader-facing branch covers omit role badges.
- Overview editorial media and accommodation/food/sights section media remain separate evidence collections; the renderer may reuse an already verified same-destination atmosphere or local-feature asset as destination-branch context when no dedicated cover exists.
- Open-license collection is configuration-driven, locally materialized and gated by source rights, focal point, contact-sheet review, category coverage and duplicate-byte checks.
- Travel-Scope-owned white split renderer with one bilingual DOM and state.
- Route-aware three-still cover carousel uses a five-second interval without a pause button; named POI rows are text-first and hide raw coordinates and non-informative aggregate-rating notices.
- Ordinary map web links without keyed runtime map scripts.
- Verified map targets use exact platform URLs, compliant Place IDs or independently
  checked coordinates; transport links require concrete stations, airports or ports.
- Q7 is executable: concise, standard, deep and ultra have distinct POI category floors (Tier 1 vs Tier 2), whole-run POI minimums, media and auditable research-pass requirements in external policy configuration.
- A per-run destination profile captures geography, mobility, map region, data
  availability and uncertainties so country differences do not become hard-coded defaults.
- No automatic Demo fallback, paid-image lookup or remote-image QA.
- Product identity and critical release files are pinned by `product-origin.json`.
- External products may inform design principles only; their DOM, CSS, scripts,
  content requirements, product names and validation reports are prohibited.

Real-destination regression evidence remains outside the installed Skill in each
isolated run directory. A new destination must always pass its own discovery,
research, media, map, export, interaction and handoff gates before delivery.
