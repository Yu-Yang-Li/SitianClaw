---
name: snc-explosion-time
description: Predict transient explosion time with bundled SN Clock CatBoost models, public TNS photometry, and optional forced-photometry input, then save structured outputs plus HTML or PNG visual artifacts. Use when Codex needs GitHub-only explosion-time estimation, SN Clock output, or a portable visualization without the SNC workspace.
---

# SNC Explosion Time

Use this skill to run the portable SN Clock predictor against a target resolvable from public TNS data.

## Quick Start

- Run `python skills/snc-explosion-time/scripts/predict_explosion_time.py --name "SN 2026fvx"`.
- Add `--forced-phot-file path/to/ztf_forced_photometry.txt` when a portable forced-phot file is available.
- Add `--redshift` or `--host-redshift` when you want to override the stored values.
- Install `requirements-cloud.txt` if the runtime does not auto-install Python packages. `catboost` and `scipy` are required.

## Workflow

1. Resolve the target from public TNS and fetch public TNS photometry.
2. Load an optional local forced-phot file when provided.
3. Build training-aligned SN Clock features through the bundled lightweight feature pipeline.
4. Run the bundled CatBoost quantile models to produce the structured prediction.
5. Save a portable HTML summary, a combined lightcurve/interval PNG, and a fallback interval PNG.

## Outputs

- `*_explosion_time.json`: prediction payload plus artifact paths.
- `*_sn_clock.html`: rendered portable SN Clock HTML panel.
- `*_sn_clock_summary.png`: combined lightcurve and interval summary.
- `*_texp_interval.png`: simple interval visualization that is always local to the skill output directory.

## References

- Read [references/script-usage.md](references/script-usage.md) for target examples and usage notes.
