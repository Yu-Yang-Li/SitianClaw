---
name: snc-candidate-crawl-3day
description: Fetch the SitianClaw 3-day transient candidate pool from public TNS plus ZTF plus LSST broker feeds, then bind the recent pool to host-redshift resolution and produce a nearby-universe candidate view using the same `z<=0.025` threshold as the SNC workflow. Use when Codex needs recent intake candidates with nearby redshift context rather than a pure raw list.
---

# SNC Candidate Crawl 3day

Fetch the same style of intake pool that the SNC workflow uses, but do not stop at a raw list. This skill combines public TNS results with public ALeRCE ZTF and LSST object feeds, then resolves host redshift for the recent subset so the returned pool is already biased toward nearby-universe triage with the same nearby threshold the workflow uses.

## Quick Start

Run:

```powershell
python skills/snc-candidate-crawl-3day/scripts/crawl_candidates_3day.py --output-dir C:\SNC\tmp_skill_test\crawl3day
```

## Workflow

1. Bootstrap the bundled SitianClaw runtime from the installed repository root.
2. Pull recent candidates from public TNS, ZTF ALeRCE, and LSST ALeRCE endpoints.
3. Keep the workspace defaults unless the user explicitly asks otherwise:
   - `include_ztf=True`
   - `include_lsst=True`
   - `ztf_days_back=3`
   - `ztf_max_candidates=300`
   - `lsst_hours_back=72`
   - `lsst_max_candidates=200`
4. Resolve host redshift for the recent subset and build a nearby candidate pool with the workspace default `z <= 0.025` unless the user overrides it.
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
- This skill is cloud-ready: it can run from a plain GitHub install without a local `C:\SNC` checkout.
