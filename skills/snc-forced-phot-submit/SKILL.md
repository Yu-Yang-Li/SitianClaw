---
name: snc-forced-phot-submit
description: Submit a new ZTF forced-photometry request through the SNC workspace client, using the same request construction and cache bookkeeping as the live workflow. Use when Codex needs to start forced photometry for a target, either as an initial submission or an incremental continuation.
---

# SNC Forced Phot Submit

Use this skill for the submit step only. It maps directly to the request-submission stage in `src/tns_project/core/ztf_forced_photometry.py`.

## Quick Start

Run:

```powershell
python skills/snc-forced-phot-submit/scripts/submit_forced_phot.py --name "SN 2026fvx" --output-dir C:\SNC\tmp_skill_test\fp_submit
```

## Workflow

1. Resolve the target coordinates from direct input or the local SNC caches.
2. Submit either:
   - a normal request via `submit_normal_forced_photometry`
   - an incremental request via `submit_incremental_forced_photometry`
3. Save the returned request metadata and a quick status plot.

## Outputs

- `*_forced_phot_submit.json`: submission payload and request metadata
- `*_submit_status.png`: quick request-status visualization
