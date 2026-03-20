# Script Usage

- Entry point: `scripts/query_redshift.py`
- Core modules:
  - `src/tns_project/core/alerce_scraper.py`
  - `src/tns_project/utils/ned_query.py`
  - `src/tns_project/core/redshift_consensus.py`
- Typical outputs:
  - `*_redshift_query.json`
  - `*_redshift_summary.png`
- Runtime behavior:
  - Use local TNS redshift first when it exists.
  - Query host redshift through the current multi-stage fallback: ALeRCE/NEDz first, then NED.
  - Merge TNS, NED, and optional broker redshifts with `merge_redshifts`.
- Good test target in this workspace:
  - `SN 2026fvx`
