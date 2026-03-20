---
name: snc-candidate-crawl-3day
description: Fetch the SNC workspace raw 3-day transient candidate pool by calling the same TNS plus ZTF plus LSST broker crawl used by the live data cycle. Use when Codex needs the broad incoming candidate list before science cuts, especially for requests about recent 3-day transient crawling, broker/TNS intake, or raw candidate exports aligned with DataCycleHandler._fetch_tns_data().
---

# SNC Candidate Crawl 3day

Fetch the same raw candidate pool that the SNC workspace uses before shortlist screening. This skill mirrors `DataCycleHandler._fetch_tns_data()` and is the right entry point for "crawl the last 3 days" style requests.

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
4. Save both structured output and a quick-look visualization.

## Outputs

- `candidate_crawl_3day.json`: structured summary and preview rows
- `candidate_crawl_3day.csv`: raw merged candidate table
- `candidate_crawl_3day_source_mix.png`: per-source contribution counts
- `candidate_crawl_3day_sky.png`: RA/Dec scatter of the raw pool

## Notes

- Prefer this skill over `snc-transient-query` when the user is asking about the workspace intake queue rather than a single named object.
- If the user wants the science shortlist, run `snc-candidate-screen-3day` after this skill rather than hand-filtering the raw crawl.
