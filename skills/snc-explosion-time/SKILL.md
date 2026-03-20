---
name: snc-explosion-time
description: Predict transient explosion time with the local SN Clock models, save the structured prediction payload, and generate HTML or PNG visual artifacts directly from the SNC workspace. Use when Codex needs explosion-time estimation, SN Clock output, or a portable visualization of the prediction result without the SNC API server.
---

# SNC Explosion Time

Use this skill to run the local SN Clock predictor against a target that already exists in the workspace SN Clock assets.

## Quick Start

- Run `python skills/snc-explosion-time/scripts/predict_explosion_time.py --name "SN 2026fvx"`.
- Add `--redshift` or `--host-redshift` when you want to override the stored values.
- When running the mounted copy from `~/.codex/skills`, start inside the SNC workspace root or set `SNC_REPO_ROOT`; the script also needs a writable shell session that is allowed to launch Python.

## Workflow

1. Require the target to exist in `sn_clock/data/tns/parsed/tns_full_info.json`.
2. Load local forced photometry when it exists.
3. Call `get_sn_clock_predictor().predict(...)` to produce the structured prediction.
4. Call `get_texp_prediction_html(...)` to reuse the richer existing visualization path.
5. Save a fallback interval plot even when the richer plot is already available.

## Outputs

- `*_explosion_time.json`: prediction payload plus artifact paths.
- `*_sn_clock.html`: rendered SN Clock HTML panel.
- `*_texp_interval.png`: simple interval visualization that is always local to the skill output directory.
- `plots/sn_clock/*_sn_clock.png`: reused/generated rich SN Clock PNG when available.

## References

- Read [references/script-usage.md](references/script-usage.md) for workspace constraints and known-good targets.
