---
name: snc-host-context
description: Crossmatch host-environment catalogs, summarize contamination risk, and generate a compact host-context visualization directly from the SNC workspace. Use when Codex needs host environment context, catalog contamination checks, or a star/AGN exclusion hint for a transient.
---

# SNC Host Context

Use this skill to query the existing crossmatch bundle and turn the result into a concrete contamination summary.

## Quick Start

- Run `python skills/snc-host-context/scripts/query_host_context.py --name "SN 2026fvx"`.
- Run `python skills/snc-host-context/scripts/query_host_context.py --ra ... --dec ... --skip-photometry`.
- When running the mounted copy from `~/.codex/skills`, start inside the SNC workspace root or set `SNC_REPO_ROOT`; the script also needs a writable shell session that is allowed to launch Python.

## Workflow

1. Resolve the target coordinates.
2. Run `crossmatch_all` through the current VSP-based crossmatch module.
3. Read `summary.contamination_score` and `summary.warnings` first.
4. Use `should_exclude_as_definite_star` as the hard exclusion decision.
5. Save the JSON artifact and the compact context-score plot even when catalog matches are sparse.

## Outputs

- `*_host_context.json`: raw crossmatch payload plus exclusion recommendation.
- `*_host_context.png`: compact contamination score and warning summary figure.

## References

- Read [references/script-usage.md](references/script-usage.md) for module behavior and current workspace caveats.
