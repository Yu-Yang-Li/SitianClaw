---
name: snc-candidate-crawl-3day
description: Fetch the SNC workspace 3-day transient candidate pool by calling the same TNS plus ZTF plus LSST broker crawl used by the live data cycle, then bind the recent pool to host-redshift resolution and produce a nearby-universe candidate view. Use when Codex needs recent intake candidates with nearby redshift context rather than a pure raw list.
---

# SNC Candidate Crawl 3day

Fetch the same intake pool that the SNC workspace uses, but do not stop at a raw list. This skill mirrors `DataCycleHandler._fetch_tns_data()`, then resolves host redshift for the recent subset so the returned pool is already biased toward nearby-universe triage.

## Quick Start

Run:

```powershell
python skills/snc-candidate-crawl-3day/scripts/crawl_candidates_3day.py --output-dir C:\SNC\tmp_skill_test\crawl3day
```

## Workflow

1. Bootstrap the local SNC repo from the current working directory or `SNC_REPO_ROOT`.
2. Call `src/tns_project/core/tns_fetcher.py::fetch_combined_data(...)`.
3. Keep the workspace defaults unless the user explicitly asks otherwise:
   - `include_ztf=True`
   - `include_lsst=True`
   - `ztf_days_back=3`
   - `ztf_max_candidates=300`
   - `lsst_hours_back=72`
   - `lsst_max_candidates=200`
4. Resolve host redshift for the recent subset and build a nearby candidate pool with `z <= 0.05` by default.
5. Save both structured output and quick-look visualizations.

## Outputs

- `candidate_crawl_3day.json`: structured summary, recent-pool counts, and nearby preview rows
- `candidate_crawl_3day.csv`: raw merged candidate table
- `candidate_crawl_3day_nearby.csv`: recent nearby-universe candidate pool with resolved redshift
- `candidate_crawl_3day_source_mix.png`: per-source contribution counts
- `candidate_crawl_3day_sky.png`: RA/Dec scatter of the raw pool
- `candidate_crawl_3day_nearby_redshift.png`: redshift distribution of the nearby pool

## Notes

- Prefer this skill over `snc-transient-query` when the user is asking about the workspace intake queue rather than a single named object.
- If the user wants the science shortlist, run `snc-candidate-screen-3day` after this skill rather than hand-filtering the raw crawl.
