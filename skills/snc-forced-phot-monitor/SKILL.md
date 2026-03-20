---
name: snc-forced-phot-monitor
description: Refresh portable ZTF forced-photometry request status, inspect request-cache ledgers, and summarize the current monitor state without the SNC workspace. Use when Codex needs the monitor stage of the forced-photometry workflow rather than a new submission or a final lightcurve fetch.
---

# SNC Forced Phot Monitor

Use this skill for the monitor step only. It tracks the same request-cache ledgers that the SNC workflow writes while jobs are pending and results arrive.

## Quick Start

Run:

```powershell
python skills/snc-forced-phot-monitor/scripts/monitor_forced_phot.py --name "SN 2026fvx" --cache-dir skills/snc-forced-phot-monitor/assets/sample_cache
```

## Workflow

1. Read the portable request-cache ledger from `all_ztf_requests.json` or the split pending/completed files.
2. Optionally refresh selected requests from the remote ZTF status page when `ZTF_EMAIL`, `ZTF_PASSWORD`, `ZTF_FP_AUTH_USER`, and `ZTF_FP_AUTH_PASS` are set.
3. Treat explicit IMAP mailbox scanning as unsupported in the GitHub-only path.
4. Save a structured snapshot and a status-count plot.

## Outputs

- `*_forced_phot_monitor.json`: request snapshot, refresh deltas, and optional email-scan result
- `*_monitor_status.png`: status-count plot for the selected request set

## Notes

- This skill is cloud-ready: it can run from a plain GitHub install without a local `C:\SNC` checkout.
- The bundled `assets/sample_cache` directory is only for smoke testing and interface validation.
