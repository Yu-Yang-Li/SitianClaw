# Script Usage

- Entry point: `scripts/predict_explosion_time.py`
- Core modules:
  - `src/tns_project/core/sn_clock_predictor.py`
  - `src/tns_project/core/texp_predictor.py`
  - `src/tns_project/core/ztf_forced_photometry.py`
- Typical outputs:
  - `*_explosion_time.json`
  - `*_sn_clock.html`
  - `*_texp_interval.png`
  - reused/generated `plots/sn_clock/*_sn_clock.png`
- Runtime behavior:
  - Require the target to exist in `sn_clock/data/tns/parsed/tns_full_info.json`.
  - Load local forced photometry when present and pass it into SN Clock.
  - Save both the rich HTML visualization and a fallback interval plot.
- Good test target in this workspace:
  - `SN 2026fvx`
