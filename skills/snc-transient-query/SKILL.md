---
name: snc-transient-query
description: Query TNS and broker transient sources, resolve a transient by name or coordinates, inspect recent TNS candidates, and generate sky or broker-lightcurve artifacts without starting the SNC FastAPI server. Use when Codex needs TNS lookup, broker source search, recent transient summaries, or quick visual inspection of a transient query result.
---

# SNC Transient Query

Use this skill to look up recent TNS transients or inspect a specific source through the existing SNC Python modules.

## Quick Start

- Run `python skills/snc-transient-query/scripts/query_transients.py --name "SN 2026fvx"`.
- Run `python skills/snc-transient-query/scripts/query_transients.py --ra 183.7422 --dec 63.7879`.
- Add `--skip-brokers` when you only need TNS.
- When running the mounted copy from `~/.codex/skills`, start inside the SNC workspace root or set `SNC_REPO_ROOT`; the script also needs a writable shell session that is allowed to launch Python.

## Workflow

1. Resolve the target from explicit coordinates first.
2. Fall back to local request-cache coordinates or `tns_full_info.json` when only a name is provided.
3. Fetch recent TNS rows through `tns_fetcher`.
4. Query ALeRCE and Lasair when coordinates are available.
5. Read the JSON artifact first, then inspect the generated sky plot or broker light curve if present.

## Outputs

- `*_transient_query.json`: machine-friendly summary of TNS and broker results.
- `*_tns_sky.png`: sky distribution of the matched TNS rows or a single resolved target.
- `*_broker_lightcurve.png`: generated only when broker photometry is available.

## References

- Read [references/script-usage.md](references/script-usage.md) for the current workspace entry points and test targets.
