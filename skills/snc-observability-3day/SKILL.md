---
name: snc-observability-3day
description: Forecast the next 3 days of observability for a target across the SNC telescope set with the bundled portable observability runtime. Use when Codex needs the workspace-style forward observability comparison, not just a single-night altitude glance.
---

# SNC Observability 3day

Use this skill for the workspace-style observability question: which SNC sites can observe the target best over the next 3 days.

## Quick Start

Run:

```powershell
python skills/snc-observability-3day/scripts/forecast_observability_3day.py --name "SN 2026fvx" --output-dir C:\SNC\tmp_skill_test\obs3day
```

## Workflow

1. Resolve the target coordinates from public TNS or direct input.
2. Call `get_best_observability_analysis(...)`.
3. Summarize each site by total observable hours and best night.
4. Save a structured payload and a total-hours comparison plot.

## Outputs

- `*_observability_3day.json`: per-site 3-day observability summary
- `*_observability_3day.png`: bar chart of total observable hours by site
- This skill is cloud-ready: it can run from a plain GitHub install without a local `C:\SNC` checkout.
