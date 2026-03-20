from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:
    from astropy.coordinates import EarthLocation, SkyCoord
    from astropy.time import Time
    import astropy.units as u
    from astroplan import FixedTarget, Observer

    ASTROPLAN_AVAILABLE = True
except ImportError:
    ASTROPLAN_AVAILABLE = False

STANDARD_SITES = [
    {"name": "Xinglong", "lat": 40.3956, "lon": 117.5783, "height": 960.0},
    {"name": "TRT-SBO", "lat": -31.28198, "lon": 149.082341, "height": 1165.0},
    {"name": "Liverpool Telescope", "lat": 28.762222, "lon": -17.879167, "height": 2326.0},
    {"name": "C14", "lat": 51.613333, "lon": -0.241944, "height": 25.0},
]


class AstroplanObservabilityCalculator:
    def __init__(self, site_config: dict[str, Any]):
        if not ASTROPLAN_AVAILABLE:
            raise ImportError("astroplan is required for observability calculations.")
        self.site_config = site_config
        self.location = EarthLocation(
            lat=site_config["lat"] * u.deg,
            lon=site_config["lon"] * u.deg,
            height=site_config["height"] * u.m,
        )
        self.observer = Observer(location=self.location, name=site_config["name"])

    def calculate_3day_observability(self, ra: float, dec: float) -> dict[str, Any]:
        target = FixedTarget(coord=SkyCoord(ra=ra * u.deg, dec=dec * u.deg), name="Target")
        start_time = Time.now()
        nights = []
        total_observable_hours = 0.0
        for day_offset in range(3):
            day_start = start_time + day_offset * u.day
            day_end = day_start + 1 * u.day
            day_times = Time(np.linspace(day_start.jd, day_end.jd, 24, endpoint=False), format="jd", scale="utc")
            altaz = self.observer.altaz(day_times, target)
            altitudes = altaz.alt.to(u.deg).value
            observable_hours = float((altitudes >= 30.0).sum())
            nights.append(
                {
                    "date": day_start.to_datetime().strftime("%Y-%m-%d"),
                    "observable_hours": observable_hours,
                    "max_altitude": round(float(np.max(altitudes)), 1),
                    "constraints_applied": "altitude>=30deg",
                    "altitude_range": f"{np.min(altitudes):.1f}deg - {np.max(altitudes):.1f}deg",
                }
            )
            total_observable_hours += observable_hours
        return {
            "site_name": self.site_config["name"],
            "calculation_method": "astroplan simplified altitude-only method",
            "nights": nights,
            "total_observable_hours": round(total_observable_hours, 2),
        }


def get_best_observability_analysis(ra: float, dec: float, site_names: list[str] | None = None) -> list[dict[str, Any]]:
    if not ASTROPLAN_AVAILABLE:
        raise RuntimeError("astroplan is not installed in this environment.")

    def _compute(site_config: dict[str, Any]) -> dict[str, Any]:
        if site_names and site_config["name"] not in site_names:
            return {"site": site_config, "skipped": True}
        calculator = AstroplanObservabilityCalculator(site_config)
        return {"site": site_config, "astroplan_3day": calculator.calculate_3day_observability(ra, dec)}

    results = []
    with ThreadPoolExecutor(max_workers=min(len(STANDARD_SITES), 4)) as executor:
        futures = [executor.submit(_compute, site) for site in STANDARD_SITES]
        for future in as_completed(futures):
            result = future.result()
            if not result.get("skipped"):
                results.append(result)
    return results
