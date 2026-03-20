---
name: snc-observability
description: Evaluate target observability for the SNC telescope set, compute hours above altitude thresholds, and generate altitude plots without starting the SNC web stack. Use when Codex needs observability windows, altitude-curve visualization, or telescope-by-telescope visibility summaries for a transient.
---

# SNC Observability

Use this skill to turn a transient name or coordinates into a portable single-night observability summary and altitude plot.

## Quick Start

- Run `python skills/snc-observability/scripts/query_observability.py --name "SN 2026fvx"`.
- Run `python skills/snc-observability/scripts/query_observability.py --ra ... --dec ... --date 2026-03-20`.
- This portable wrapper resolves names from public TNS and runs from a clean GitHub clone without the full SNC workspace.

## Workflow

1. Resolve coordinates from explicit inputs or public TNS name lookup.
2. Sample the target altitude over a full night for each telescope in the legacy SNC set.
3. Generate a portable multi-telescope altitude plot PNG from the sampled curves.
4. Read the JSON artifact first, then inspect the altitude plot.

## Outputs

- `*_observability.json`: best time, max altitude, and hours above 20 and 30 degrees for each telescope.
- `*_altitude.png`: multi-telescope altitude plot for the requested date.

## References

- Read [references/script-usage.md](references/script-usage.md) for the telescope set and current workspace test target.
