from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from sitianclaw_runtime.runtime import ensure_output_dir, json_safe, safe_slug, write_json  # noqa: E402
from sitianclaw_runtime.transients import resolve_target  # noqa: E402

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

COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _build_time_grid(date_str: str, timezone_name: str) -> tuple[list[datetime], list[datetime]]:
    tz = ZoneInfo(timezone_name)
    local_midnight = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    utc_midnight = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
    start_time = utc_midnight - timedelta(hours=6)
    utc_points = [start_time + timedelta(minutes=10 * idx) for idx in range(12 * 6)]
    local_points = [point.replace(tzinfo=timezone.utc).astimezone(tz) for point in utc_points]
    return utc_points, local_points


def _sample_telescope(target_coord: SkyCoord, telescope: dict[str, Any], date_str: str) -> dict[str, Any]:
    utc_points, local_points = _build_time_grid(date_str, telescope["timezone"])
    location = EarthLocation(
        lat=float(telescope["lat"]) * u.deg,
        lon=float(telescope["lon"]) * u.deg,
        height=float(telescope["height"]) * u.m,
    )
    altaz = target_coord.transform_to(AltAz(obstime=Time(utc_points), location=location))
    altitudes = altaz.alt.deg

    max_idx = int(max(range(len(altitudes)), key=lambda idx: altitudes[idx]))
    best_utc = utc_points[max_idx].replace(tzinfo=timezone.utc)
    best_local = local_points[max_idx]
    step_hours = 10.0 / 60.0

    return {
        "name": telescope["name"],
        "timezone": telescope["timezone"],
        "max_altitude_deg": float(max(altitudes)),
        "hours_above_20deg": float(sum(alt > 20 for alt in altitudes) * step_hours),
        "hours_above_30deg": float(sum(alt > 30 for alt in altitudes) * step_hours),
        "best_time_utc": best_utc.isoformat(),
        "best_time_local": best_local.isoformat(),
        "observable": bool(max(altitudes) > 20),
        "local_time_grid": [point.isoformat() for point in local_points],
        "altitudes_deg": [float(value) for value in altitudes],
    }


def _plot_altitude_curves(
    target_name: str,
    date_str: str,
    telescope_rows: list[dict[str, Any]],
    output_path: Path,
) -> Path | None:
    if not telescope_rows:
        return None
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for idx, row in enumerate(telescope_rows):
        time_values = [datetime.fromisoformat(item) for item in row["local_time_grid"]]
        ax.plot(
            time_values,
            row["altitudes_deg"],
            label=row["name"],
            color=COLORS[idx % len(COLORS)],
            linewidth=1.8,
        )
    ax.axhline(20.0, color="#7f7f7f", linestyle="--", linewidth=1.0, alpha=0.8, label="20 deg threshold")
    ax.axhline(30.0, color="#bbbbbb", linestyle=":", linewidth=1.0, alpha=0.8, label="30 deg threshold")
    ax.set_title(f"SNC Observability: {target_name} on {date_str}")
    ax.set_xlabel("Local time at each telescope")
    ax.set_ylabel("Altitude (deg)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate single-night observability and generate altitude plots.")
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
    resolved = resolve_target(name=args.name, ra=args.ra, dec=args.dec)
    if resolved["ra"] is None or resolved["dec"] is None:
        raise SystemExit("Observability needs RA/Dec directly or via public TNS name resolution.")

    target_name = resolved["name"]
    output_dir = ensure_output_dir(REPO_ROOT, "snc-observability", target_name, args.output_dir)
    target_coord = SkyCoord(ra=float(resolved["ra"]) * u.deg, dec=float(resolved["dec"]) * u.deg)
    summaries = [_sample_telescope(target_coord, telescope, args.date) for telescope in TELESCOPES]
    summaries.sort(key=lambda item: item["max_altitude_deg"], reverse=True)

    plot_rows = list(reversed(summaries))
    altitude_plot = _plot_altitude_curves(
        target_name=target_name,
        date_str=args.date,
        telescope_rows=plot_rows,
        output_path=output_dir / f"{safe_slug(target_name)}_altitude.png",
    )

    result = {
        "skill": "snc-observability",
        "workspace_alignment": "GitHub-only portable single-night observability summary across the legacy SNC telescope set.",
        "target": {
            "name": target_name,
            "ra": resolved["ra"],
            "dec": resolved["dec"],
            "resolved_from": resolved["resolved_from"],
        },
        "date": args.date,
        "telescopes": [
            {
                key: value
                for key, value in row.items()
                if key not in {"local_time_grid", "altitudes_deg"}
            }
            for row in summaries
        ],
        "artifact": str(altitude_plot) if altitude_plot is not None else None,
    }

    json_path = write_json(output_dir / f"{safe_slug(target_name)}_observability.json", result)
    result["json_path"] = str(json_path)
    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
