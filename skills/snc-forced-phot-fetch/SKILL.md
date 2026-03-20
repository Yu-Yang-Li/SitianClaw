---
name: snc-forced-phot-fetch
description: Load already-downloaded ZTF forced-photometry files from a portable cache or explicit text file and generate a quick lightcurve artifact. Use when Codex needs the final result-inspection stage of the forced-photometry workflow rather than submitting or monitoring requests.
---

# SNC Forced Phot Fetch

Use this skill once a forced-photometry result file already exists in a portable cache or has been provided explicitly. It turns the text file into a structured summary and a quick lightcurve plot.

## Quick Start

Run:

```powershell
python skills/snc-forced-phot-fetch/scripts/fetch_forced_phot.py --file skills/snc-forced-phot-fetch/assets/sample_ztf_forced_photometry.txt --name "AT 2026fkv"
```

## Workflow

1. Read the downloaded `ztf_forced_photometry.txt` file from a portable cache or explicit file path.
2. Convert it to the normalized photometry table used by the workspace.
3. Save a structured payload and a lightcurve plot.

## Outputs

- `*_forced_phot_fetch.json`: structured photometry summary and preview rows
- `*_forced_lightcurve.png`: quick-look forced-photometry lightcurve

## Notes

- This skill is cloud-ready: it can run from a plain GitHub install without a local `C:\SNC` checkout.
- The bundled `assets/sample_ztf_forced_photometry.txt` file is only for smoke testing and interface validation.
