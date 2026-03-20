# Script Usage

- Entry point: `scripts/query_transients.py`
- Core modules:
  - `src/tns_project/core/tns_fetcher.py`
  - `src/tns_project/core/ztf_broker_client.py`
  - `src/tns_project/utils/plotting.py`
- Typical outputs:
  - `*_transient_query.json`
  - `*_tns_sky.png`
  - `*_broker_lightcurve.png` when broker photometry is available
- Runtime behavior:
  - Fetch recent TNS rows from the live TNS search page.
  - Resolve missing coordinates from local `data/ztf_forced_cache/*requests*.json` or `sn_clock/data/tns/parsed/tns_full_info.json`.
  - Query ALeRCE and Lasair only when coordinates are available and `--skip-brokers` is not set.
- Good test targets in this workspace:
  - `SN 2026fvx`
  - direct coordinates from `data/ztf_forced_cache/pending_requests.json`
