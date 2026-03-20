---
name: snc-transient-query
description: Query public TNS and broker transient sources, resolve a transient by name or coordinates, inspect recent TNS candidates, and generate sky or lightcurve artifacts with the bundled portable runtime. Use when Codex needs TNS lookup, broker source search, recent transient summaries, or quick visual inspection of a transient query result.
---

# SNC Transient Query

Use this skill to look up recent TNS transients or inspect a specific source through the bundled GitHub-only runtime.

## Quick Start

- Run `python skills/snc-transient-query/scripts/query_transients.py --name "SN 2026fvx"`.
- Run `python skills/snc-transient-query/scripts/query_transients.py --ra 183.7422 --dec 63.7879`.
- Add `--skip-brokers` when you only need TNS.

## Workflow

1. Resolve the target from explicit coordinates first.
2. Fall back to public TNS name resolution when only a name is provided.
3. Fetch recent public TNS rows.
4. Query public ALeRCE broker photometry when coordinates are available and also parse TNS photometry when present.
5. Read the JSON artifact first, then inspect the generated sky plot or light curve if present.

## Outputs

- `*_transient_query.json`: machine-friendly summary of TNS and broker results.
- `*_tns_sky.png`: sky distribution of the matched TNS rows or a single resolved target.
- `*_lightcurve.png`: generated when public broker or TNS photometry is available.

## References

- Read [references/script-usage.md](references/script-usage.md) for the current workspace entry points and test targets.
- This skill is cloud-ready: it can run from a plain GitHub install without a local `C:\SNC` checkout.
