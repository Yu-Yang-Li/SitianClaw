# Script Usage

- Entry point: `scripts/query_observability.py`
- Core modules:
  - `src/tns_project/utils/plotting.py`
  - `astropy.coordinates`, `astropy.time`
- Typical outputs:
  - `*_observability.json`
  - `*_altitude.png`
- Runtime behavior:
  - Reuse the existing SNC altitude-plot implementation for the PNG.
  - Independently sample altitude curves to compute hours above 20 and 30 degrees plus best local observing time.
  - Resolve coordinates from local request cache when the target name is known there.
- Telescope set in this skill:
  - TRT-CTO
  - LT
  - XL-216cm
  - TRT-SRO
- Good test target in this workspace:
  - `SN 2026fvx`
