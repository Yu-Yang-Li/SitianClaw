---
name: snc-forced-phot-monitor
description: Refresh cached ZTF forced-photometry request status, inspect the pending and completed request caches, and optionally trigger mailbox scans for downloaded results. Use when Codex needs the monitor stage of the SNC forced-photometry workflow rather than a new submission or a final lightcurve fetch.
---

# SNC Forced Phot Monitor

Use this skill for the monitor step only. It tracks the same request caches that the SNC workspace updates while jobs are pending and results arrive.

## Quick Start

Run:

```powershell
python skills/snc-forced-phot-monitor/scripts/monitor_forced_phot.py --name "SN 2026fvx" --refresh --output-dir C:\SNC\tmp_skill_test\fp_monitor
```

## Workflow

1. Optionally trigger an explicit mailbox scan.
2. Optionally refresh pending requests with `check_pending_requests()`.
3. Read the local pending and completed request caches.
4. Save a structured snapshot and a status-count plot.

## Outputs

- `*_forced_phot_monitor.json`: request snapshot, refresh deltas, and optional email-scan result
- `*_monitor_status.png`: status-count plot for the selected request set
