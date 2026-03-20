---
name: snc-forced-photometry
description: Submit, monitor, and fetch ZTF forced-photometry jobs through the existing SNC client, then generate request-status or lightcurve artifacts. Use when Codex needs ZTF forced photometry submission, status tracking, cached result loading, or a quick visualization of forced-photometry output without running the SNC server.
---

# SNC Forced Photometry

Use this skill to work with the current ZTF forced-photometry client directly from the workspace.

## Quick Start

- Run `python skills/snc-forced-photometry/scripts/manage_forced_photometry.py fetch --name "AT 2026fkv"`.
- Run `python skills/snc-forced-photometry/scripts/manage_forced_photometry.py status --name "SN 2026fvx"`.
- Run `python skills/snc-forced-photometry/scripts/manage_forced_photometry.py submit --name "SN 2026fvx" --incremental`.
- When running the mounted copy from `~/.codex/skills`, start inside the SNC workspace root or set `SNC_REPO_ROOT`; the script also needs a writable shell session that is allowed to launch Python.

## Workflow

1. Use `fetch` when you already have a cached `ztf_forced_photometry.txt`.
2. Use `status` for queue monitoring and add `--refresh` only when you want to hit the live check path.
3. Use `submit` when you truly want to queue work; the wrapped client will reuse an existing pending request for duplicate coordinates.
4. Read the JSON artifact first, then inspect the generated status or lightcurve plot.

## Outputs

- `*_forced_photometry.json`: request summary or photometry summary.
- `*_status_summary.png`: request-state histogram.
- `*_forced_lightcurve.png`: plotted cached forced photometry when `fetch` succeeds.

## References

- Read [references/script-usage.md](references/script-usage.md) for subcommand behavior, env requirements, and safe test targets.
