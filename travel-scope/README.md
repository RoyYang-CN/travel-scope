# Travel-Scope

Current baseline: **v3.0.2**. See [VERSION.md](VERSION.md) for the POI identity, coordinate, image, and regression acceptance criteria.

Travel-Scope is an evidence-aware travel research and itinerary generation skill. It produces HTML, Markdown, and Excel outputs from one structured travel dataset, with Chinese and English output modes.

## Offline demo

The demo does not need API keys or network access to provider APIs:

```powershell
python scripts/gen_travel_scope.py --mode demo --fixture fixtures/demo.json --output-dir .temp/demo --language both
```

The fixture is synthetic and must not be used for real travel decisions.

## Live mode

Live mode uses the normal Travel-Scope workflow and requires provider credentials to be injected at runtime. Never commit API keys, raw provider responses, image caches, or generated URLs containing keys.

```powershell
python scripts/gen_travel_scope.py --mode live --output-dir <output> --map-platform all --language both
```

See [SKILL.md](SKILL.md) for the SOP, QA gates, data-source boundaries, and domestic/international routing rules.
