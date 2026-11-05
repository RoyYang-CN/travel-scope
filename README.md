# Travel-Scope v5.0.0

Evidence-aware travel research, validation, and single-file reader generation.

## Release status

This repository currently publishes the **v5.0.0 LIMITED-SCOPE RELEASE**:

- validated profile: `zh-formal`
- validated destination: California
- English formal delivery: deferred
- Philippines delivery: `AUDIT_HOLD` and excluded from this release
- `production_certified=false`

These boundaries are machine-readable in
[`travel-scope/references/release-scope.json`](travel-scope/references/release-scope.json).
Do not interpret this release as universal destination or bilingual certification.

## Key properties

- No Google Places API key or Google billing dependency.
- Named-search map links are allowed without claiming exact Google entity matching.
- Configuration-driven data, renderer, media, provenance, and delivery gates.
- Deterministic Skill ZIP with a self-verifying `product-origin.json` seal.
- Responsive single-file reader output.

## Verify the source tree

```powershell
cd travel-scope
python -B scripts/verify_product.py
python -B scripts/test_v500_release_package.py
```

The complete internal regression suite contains browser and frozen-run evidence that is
not all distributed in the public repository. The commands above are the self-contained
public verification surface; release-scope auditing is performed against the signed
release-run evidence before publication.

## Initialize a run

```powershell
python travel-scope/scripts/init_run.py `
  --country california `
  --run-id travel_scope_run_california_001 `
  --artifact-slug california `
  --delivery-profile reader `
  --runs-dir .temp/runs
```

See [`travel-scope/SKILL.md`](travel-scope/SKILL.md) for the workflow contract and
[`travel-scope/VERSION.md`](travel-scope/VERSION.md) for release history and withdrawn
claims.

## Release downloads

The GitHub `v5.0.0` release contains:

- `travel-scope-v5.0.0-limited-release.zip` — installable Skill package
- `travel-scope-v5.0.0-california-zh-formal.html` — signed California Chinese reader

## License and bundled media

Source code is licensed under the [Apache License 2.0](LICENSE). Bundled third-party
media and its independent license are documented in
[`travel-scope/THIRD_PARTY_NOTICES.md`](travel-scope/THIRD_PARTY_NOTICES.md).

Never commit provider keys, raw private travel records, authentication material, or
generated URLs containing credentials.
