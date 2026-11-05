# Travel-Scope Skill Engine

Current baseline: **v5.0.0**.

Use `SKILL.md` as the product workflow authority and run
`python scripts/verify_product.py` before a build. Live inputs belong in a fresh
run-local JSON dataset supplied with `--data`; do not edit installed source
constants.

The active HTML renderer is `scripts/travel_renderer.py`. External reference
products are not runtime or packaging dependencies.
