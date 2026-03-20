---
name: snc-redshift-query
description: Resolve host-galaxy redshift, compare TNS/NED/broker redshift candidates, and generate a consensus redshift plot without using the SNC API server. Use when Codex needs host redshift lookup, NED-backed redshift resolution, or a quick consensus decision for a transient.
---

# SNC Redshift Query

Use this skill to resolve host redshift through the current SNC fallback path and summarize the result as both JSON and a small comparison plot.

## Quick Start

- Run `python skills/snc-redshift-query/scripts/query_redshift.py --name "SN 2026fvx"`.
- Run `python skills/snc-redshift-query/scripts/query_redshift.py --ra ... --dec ... --tns-z ...`.
- Add `--broker-z` and `--broker-source sherlock` when you already have a broker redshift candidate.
- When running the mounted copy from `~/.codex/skills`, start inside the SNC workspace root or set `SNC_REPO_ROOT`; the script also needs a writable shell session that is allowed to launch Python.

## Workflow

1. Resolve the target coordinates.
2. Treat local TNS redshift as the manual-report candidate when available.
3. Query host information through the existing `get_host_redshift` and direct NED helper.
4. Merge all available candidates with `merge_redshifts`.
5. Read the JSON artifact first, then inspect the redshift comparison plot.

## Outputs

- `*_redshift_query.json`: host info, raw redshift candidates, and the consensus decision.
- `*_redshift_summary.png`: compact visualization of the candidate redshift values and the chosen consensus.

## References

- Read [references/script-usage.md](references/script-usage.md) for the module mapping and known-good test target.
