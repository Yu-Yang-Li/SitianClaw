from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from astropy import units as u  # noqa: E402
from astropy.coordinates import AltAz, EarthLocation, SkyCoord  # noqa: E402
from astropy.time import Time  # noqa: E402

from _snc_skill_support import (  # noqa: E402
    bootstrap_repo_root,
    ensure_output_dir,
    json_safe,
    resolve_target,
    safe_slug,
    write_json,
)

REPO_ROOT = bootstrap_repo_root(__file__)
from src.tns_project.utils.plotting import AstronomicalPlotter  # noqa: E402

TELESCOPES = [
    {
        "name": "TRT-CTO (Chile)",
        "lat": -30.16527,
        "lon": -70.80646,
        "height": 2207.0,
        "timezone": "America/Santiago",
    },
    {
        "name": "LT (La Palma)",
        "lat": 28.762222,
        "lon": -17.879167,
        "height": 2326.0,
        "timezone": "Atlantic/Canary",
    },
    {
        "name": "XL-216cm (Xinglong)",
        "lat": 40.3956,
        "lon": 117.5783,
        "height": 960.0,
        "timezone": "Asia/Shanghai",
    },
    {
        "name": "TRT-SRO (USA-CA)",
        "lat": 33.356111,
        "lon": -116.863333,
        "height": 1682.0,
        "timezone": "America/Los_Angeles",
    },
]


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _sample_telescope(target_coord: SkyCoord, telescope: dict[str, Any], date_str: str) -> dict[str, Any]:
    tz = ZoneInfo(telescope["timezone"])
    local_midnight = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    utc_midnight = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
    start_time = utc_midnight - timedelta(hours=6)
    time_points = [start_time + timedelta(minutes=10 * idx) for idx in range(12 * 6)]

    location = EarthLocation(
        lat=float(telescope["lat"]) * u.deg,
        lon=float(telescope["lon"]) * u.deg,
        height=float(telescope["height"]) * u.m,
    )
    altaz = target_coord.transform_to(AltAz(obstime=Time(time_points), location=location))
    altitudes = altaz.alt.deg

    max_idx = int(max(range(len(altitudes)), key=lambda idx: altitudes[idx]))
    best_utc = time_points[max_idx].replace(tzinfo=timezone.utc)
    best_local = best_utc.astimezone(tz)
    step_hours = 10.0 / 60.0

    return {
        "name": telescope["name"],
        "max_altitude_deg": float(max(altitudes)),
        "hours_above_20deg": float(sum(alt > 20 for alt in altitudes) * step_hours),
        "hours_above_30deg": float(sum(alt > 30 for alt in altitudes) * step_hours),
        "best_time_utc": best_utc.isoformat(),
        "best_time_local": best_local.isoformat(),
        "observable": bool(max(altitudes) > 20),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate observability and generate altitude plots.")
    parser.add_argument("--name", help="Source name, for example 'SN 2026fvx'.")
    parser.add_argument("--ra", type=float, help="RA in degrees.")
    parser.add_argument("--dec", type=float, help="Dec in degrees.")
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Observation date in YYYY-MM-DD format.",
    )
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    resolved = resolve_target(REPO_ROOT, name=args.name, ra=args.ra, dec=args.dec)
    if resolved["ra"] is None or resolved["dec"] is None:
        raise SystemExit("Need RA/Dec directly or via a cached target name.")

    target_name = resolved["name"]
    output_dir = ensure_output_dir(REPO_ROOT, "snc-observability", target_name, args.output_dir)
    plotter = AstronomicalPlotter(output_dir=str(output_dir))
    altitude_plot = plotter.plot_telescope_altitude(
        ra=float(resolved["ra"]),
        dec=float(resolved["dec"]),
        target_name=target_name,
        date=args.date,
        save_path=str(output_dir / f"{safe_slug(target_name)}_altitude.png"),
    )

    target_coord = SkyCoord(ra=float(resolved["ra"]) * u.deg, dec=float(resolved["dec"]) * u.deg)
    summaries = [_sample_telescope(target_coord, telescope, args.date) for telescope in TELESCOPES]
    summaries.sort(key=lambda item: item["max_altitude_deg"], reverse=True)

    result = {
        "target": {
            "name": target_name,
            "ra": resolved["ra"],
            "dec": resolved["dec"],
            "resolved_from": resolved["resolved_from"],
        },
        "date": args.date,
        "telescopes": summaries,
        "artifact": altitude_plot,
    }

    json_path = write_json(output_dir / f"{safe_slug(target_name)}_observability.json", result)
    result["json_path"] = str(json_path)
    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
