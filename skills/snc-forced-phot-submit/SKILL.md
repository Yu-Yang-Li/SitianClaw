---
name: snc-forced-phot-submit
description: Submit a new ZTF forced-photometry request through the bundled portable runtime, using environment-based credentials and portable cache bookkeeping. Use when Codex needs to start forced photometry for a target, either as an initial submission or an incremental continuation.
---

# SNC Forced Phot Submit

Use this skill for the submit step only. It maps directly to the request-submission stage of the SNC workflow without requiring a local `C:\SNC` checkout.

## Quick Start

Run:

```powershell
python skills/snc-forced-phot-submit/scripts/submit_forced_phot.py --name "SN 2026fvx" --dry-run
```

## Workflow

1. Resolve the target coordinates from direct input or public TNS name resolution.
2. Submit either:
   - a normal request with a conservative default time window
   - an incremental request that starts from the latest cached `jd_end`
3. In live mode, require `ZTF_EMAIL`, `ZTF_PASSWORD`, `ZTF_FP_AUTH_USER`, and `ZTF_FP_AUTH_PASS`.
4. Save the returned request metadata and a quick status plot.

## Outputs

- `*_forced_phot_submit.json`: submission payload and request metadata
- `*_submit_status.png`: quick request-status visualization

## Notes

- This skill is cloud-ready: it can run from a plain GitHub install without a local `C:\SNC` checkout.
- Use `--dry-run` for smoke tests and interface validation when you do not want to create a live ZTF request.
