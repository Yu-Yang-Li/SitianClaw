# Script Usage

- Entry point: `scripts/query_host_context.py`
- Core modules:
  - `src/tns_project/core/crossmatch_vsp.py`
- Typical outputs:
  - `*_host_context.json`
  - `*_host_context.png`
- Runtime behavior:
  - Query the catalog crossmatch bundle in parallel through `crossmatch_all`.
  - Summarize contamination risk through `summary.contamination_score`.
  - Run `should_exclude_as_definite_star` to turn catalog results into a concrete recommendation.
- Notes:
  - External catalog lookups may return partial or empty results depending on network state and installed extras.
  - Even when matches are empty, the skill should still produce a summary JSON and context score plot.
- Good test target in this workspace:
  - `SN 2026fvx`
