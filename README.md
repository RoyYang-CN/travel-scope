# Travel-Scope

Evidence-aware travel research and itinerary generation for domestic and international travel.

Travel-Scope combines destination discovery, route-corridor exploration, multi-source evidence, structured POI data, and output QA. It generates HTML, Markdown, and Excel from one validated data model, with Chinese and English output.

## Who is Travel-Scope for?

- **Open-source and Python developers** — reuse the generator, data model, QA gates, and provider adapters in your own travel tools.
- **AI Agent users** — provide a standard travel brief and let the workflow discover destinations, search places, compare route corridors, and produce editable deliverables.
- **International visitors to China** — use English explanations while retaining Chinese names and pinyin for maps, taxis, tickets, and asking for directions.
- **Travel planners** — start from the Indonesia, Philippines, or China examples and adapt the route, budget, transport, and POI choices.

## Try it without API keys

```powershell
python travel-scope/scripts/gen_travel_scope.py `
  --mode demo `
  --fixture travel-scope/fixtures/demo.json `
  --output-dir .temp/demo `
  --language both
```

The generated files include CN/EN HTML, Markdown, and Excel examples under `examples/demo/`. They use synthetic offline data and are not travel recommendations.

## Live mode

Live mode uses provider credentials supplied at runtime. Do not commit API keys, raw provider responses, image caches, or generated URLs containing keys.

```powershell
python travel-scope/scripts/gen_travel_scope.py `
  --mode live `
  --output-dir <output> `
  --map-platform all `
  --language both
```

See [travel-scope/SKILL.md](travel-scope/SKILL.md) for the SOP and QA gates. See [travel-scope/README.md](travel-scope/README.md) for skill-specific usage.

## Product and workflow previews

- [中文产品介绍](travel-scope-intro.html) / [English product introduction](travel-scope-intro-en.html)
- [中文工作流说明](travel-scope-workflow.html) / [English workflow](travel-scope-workflow-en.html)

The previews include bilingual card, accommodation, food, attraction and route-interface screenshots. Public screenshots do not contain provider API keys.

### HTML output preview

<details open>
<summary>English interface screenshots</summary>

English card view and product output:

| Collapsed overview / cards | Route map | Accommodation | Food | Attractions |
|---|---|---|---|---|
| ![Travel-Scope English overview](assets/screenshot-indonesia-en-overview.png) | ![Travel-Scope English route](assets/screenshot-indonesia-en-route-full.png) | ![Travel-Scope English accommodation](assets/screenshot-indonesia-en-accommodation.png) | ![Travel-Scope English food](assets/screenshot-indonesia-en-food.png) | ![Travel-Scope English attractions](assets/screenshot-indonesia-en-attractions.png) |

The English route screenshot was rendered with a temporary local key and contains no API key. The public HTML still requires the user's own configuration for a live Google Maps view; no provider key is embedded in this repository.

</details>

<details open>
<summary>中文界面截图</summary>

Chinese card view and product output:

| 折叠总览 / 卡片 | 路线地图 | 住宿 | 美食 | 景点 |
|---|---|---|---|---|
| ![Travel-Scope 中文总览](assets/screenshot-indonesia-cn-overview.png) | ![Travel-Scope 中文路线](assets/screenshot-indonesia-cn-route-full.png) | ![Travel-Scope 中文住宿](assets/screenshot-indonesia-cn-accommodation.png) | ![Travel-Scope 中文美食](assets/screenshot-indonesia-cn-food.png) | ![Travel-Scope 中文景点](assets/screenshot-indonesia-cn-attractions.png) |

补充： [目的地折叠总览](assets/screenshot-indonesia-cn-destinations-collapsed.png)

</details>

## Current release

`v3.1.0` — real image source validation, remote image reachability QA, independent transport nodes, and image reuse QA.

The EN delivery gate now checks dynamic destination and route labels as well as the fixed interface text. English output uses `English Name (中文名)` for places and blocks incomplete route/destination translations before release.

HTML transport cards show only map-ready nodes, such as a bus station or port. Excel keeps both the node sheet and the detailed point-to-point transport sheet, so one destination can correctly contain multiple transport locations.

## Status

This repository is currently a private release candidate while API, data-source, licensing, and output safety checks are completed.

## Security and licensing

- Security reports: see [SECURITY.md](SECURITY.md). Sensitive reports should be emailed privately to `hnzzlulu@gmail.com`, not posted in Issues.
- Licensed under [Apache-2.0](LICENSE). Commercial use, modification, and redistribution are permitted subject to the license terms.
