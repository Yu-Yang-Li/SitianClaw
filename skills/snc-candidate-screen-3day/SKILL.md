---
name: snc-candidate-screen-3day
description: Apply the SNC-style strict shortlist logic to the recent 3-day candidate crawl, including discovery-date filtering, host enrichment, redshift cuts, and galactic-latitude cuts, using the bundled portable runtime. Use when Codex needs the same science shortlist that the SNC data cycle would keep, rather than a raw broker or TNS intake list.
---

# SNC Candidate Screen 3day

Use this skill when the user is really asking for the workflow shortlist. It reproduces the order used in `DataCycleHandler._apply_astronomical_processing()` instead of doing an ad hoc single-object lookup.

## Quick Start

Run:

```powershell
python skills/snc-candidate-screen-3day/scripts/screen_candidates_3day.py --output-dir C:\SNC\tmp_skill_test\screen3day
```

## Workflow

1. Fetch the raw 3-day candidate pool from public TNS plus ZTF plus LSST feeds.
2. Apply the workflow strict screening sequence:
   discovery-date filter, host enrichment, host-redshift cut, and galactic-latitude cut.
3. If strict mode returns zero rows, mirror the live workspace safety net and try the relaxed fallback unless `--disable-relaxed-fallback` is set.
4. Save both the raw pool and final shortlist so the delta is inspectable.
5. Generate a stage-count plot for quick review.

## Overrides

- `--recent-days`
- `--redshift-max`
- `--min-galactic-latitude`
- `--disable-relaxed-fallback`

Keep the defaults unless the user explicitly wants to inspect alternative thresholds.

## Outputs

- `candidate_screen_3day.json`: structured summary, stage counts, and shortlist preview
- `candidate_screen_3day_raw.csv`: raw merged pool before cuts
- `candidate_screen_3day.csv`: strict shortlist after cuts
- `candidate_screen_3day_stage_counts.png`: candidate counts after each stage

## Notes

- Default strict thresholds stay aligned to the SNC workflow: `3 days`, `z<=0.025`, and `|b|>15`.
- Relaxed fallback stays aligned to the workspace safety net: `7 days` and `z<=0.05`.
- This skill is cloud-ready: it can run from a plain GitHub install without a local `C:\SNC` checkout.
