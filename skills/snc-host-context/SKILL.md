---
name: snc-host-context
description: Crossmatch public host-environment catalogs, summarize contamination risk, and generate a compact host-context visualization with the bundled portable runtime. Use when Codex needs host environment context, catalog contamination checks, or a star/AGN exclusion hint for a transient.
---

# SNC Host Context

Use this skill to query public crossmatch catalogs through the bundled GitHub-only runtime and turn the result into a concrete contamination summary.

## Quick Start

- Run `python skills/snc-host-context/scripts/query_host_context.py --name "SN 2026fvx"`.
- Run `python skills/snc-host-context/scripts/query_host_context.py --ra ... --dec ... --skip-photometry`.

## Workflow

1. Resolve the target coordinates.
2. Run `crossmatch_all` through the bundled public-catalog crossmatch runtime.
3. Read `summary.contamination_score` and `summary.warnings` first.
4. Use `should_exclude_as_definite_star` as the hard exclusion decision.
5. Save the JSON artifact and the compact context-score plot even when catalog matches are sparse.

## Outputs

- `*_host_context.json`: raw crossmatch payload plus exclusion recommendation.
- `*_host_context.png`: compact contamination score and warning summary figure.

## References

- Read [references/script-usage.md](references/script-usage.md) for module behavior and current workspace caveats.
- This skill is cloud-ready: it can run from a plain GitHub install without a local `C:\SNC` checkout.
