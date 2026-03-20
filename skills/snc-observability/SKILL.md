---
name: snc-observability
description: Evaluate target observability for the SNC telescope set, compute hours above altitude thresholds, and generate altitude plots without starting the SNC web stack. Use when Codex needs observability windows, altitude-curve visualization, or telescope-by-telescope visibility summaries for a transient.
---

# SNC Observability

Use this skill to turn a transient name or coordinates into an observability summary and altitude plot.

## Quick Start

- Run `python skills/snc-observability/scripts/query_observability.py --name "SN 2026fvx"`.
- Run `python skills/snc-observability/scripts/query_observability.py --ra ... --dec ... --date 2026-03-20`.
- When running the mounted copy from `~/.codex/skills`, start inside the SNC workspace root or set `SNC_REPO_ROOT`; the script also needs a writable shell session that is allowed to launch Python.

## Workflow

1. Resolve coordinates from explicit inputs or local request-cache entries.
2. Reuse the existing SNC altitude-plot generator for the PNG artifact.
3. Compute per-telescope visibility statistics from the same date window.
4. Read the JSON artifact first, then inspect the altitude plot.

## Outputs

- `*_observability.json`: best time, max altitude, and hours above 20 and 30 degrees for each telescope.
- `*_altitude.png`: multi-telescope altitude plot for the requested date.

## References

- Read [references/script-usage.md](references/script-usage.md) for the telescope set and current workspace test target.
