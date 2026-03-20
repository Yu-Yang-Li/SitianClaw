---
name: snc-forced-photometry
description: Submit, monitor, and fetch ZTF forced-photometry jobs through the existing SNC client, then generate request-status or lightcurve artifacts. Use when Codex needs ZTF forced photometry submission, status tracking, cached result loading, or a quick visualization of forced-photometry output without running the SNC server.
---

# SNC Forced Photometry

Use this skill to work with the portable GitHub-only ZTF forced-photometry workflow from a single combined entry point.

## Quick Start

- Run `python skills/snc-forced-photometry/scripts/manage_forced_photometry.py fetch --name "AT 2026fkv" --file skills/snc-forced-phot-fetch/assets/sample_ztf_forced_photometry.txt`.
- Run `python skills/snc-forced-photometry/scripts/manage_forced_photometry.py status --name "SN 2026fvx" --cache-dir skills/snc-forced-phot-monitor/assets/sample_cache`.
- Run `python skills/snc-forced-photometry/scripts/manage_forced_photometry.py submit --name "SN 2026fvx" --dry-run`.
- This portable wrapper runs from a clean GitHub clone and writes artifacts locally without needing the full SNC workspace.

## Workflow

1. Use `fetch` when you already have a downloaded `ztf_forced_photometry.txt`, or point at the bundled sample asset for smoke tests.
2. Use `status` for queue monitoring and add `--refresh` only when you want to hit the live check path.
3. Use `submit` with `--dry-run` for cloud validation, or provide real ZTF credentials for a live submit.
4. Read the JSON artifact first, then inspect the generated status or lightcurve plot.

## Outputs

- `*_forced_photometry.json`: request summary or photometry summary.
- `*_status_summary.png`: request-state histogram.
- `*_forced_lightcurve.png`: plotted cached forced photometry when `fetch` succeeds.

## References

- Read [references/script-usage.md](references/script-usage.md) for subcommand behavior, portable env requirements, and safe test targets.
