---
name: snc-forced-phot-fetch
description: Load already-downloaded ZTF forced-photometry files from the SNC workspace cache and generate a quick lightcurve artifact. Use when Codex needs the final result-inspection stage of the SNC forced-photometry workflow rather than submitting or monitoring requests.
---

# SNC Forced Phot Fetch

Use this skill once a forced-photometry result file already exists in the SNC cache. It turns the cached text file into a structured summary and a quick lightcurve plot.

## Quick Start

Run:

```powershell
python skills/snc-forced-phot-fetch/scripts/fetch_forced_phot.py --name "AT 2026fkv" --output-dir C:\SNC\tmp_skill_test\fp_fetch
```

## Workflow

1. Read the downloaded `ztf_forced_photometry.txt` file from the SNC cache.
2. Convert it to the normalized photometry table used by the workspace.
3. Save a structured payload and a lightcurve plot.

## Outputs

- `*_forced_phot_fetch.json`: structured photometry summary and preview rows
- `*_forced_lightcurve.png`: quick-look forced-photometry lightcurve
