from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from _snc_skill_support import (
    bootstrap_repo_root,
    ensure_output_dir,
    json_safe,
    resolve_target,
    safe_slug,
    write_json,
)

REPO_ROOT = bootstrap_repo_root(__file__)
from src.tns_project.utils.astroplan_observability import get_best_observability_analysis  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _site_summary(entry: dict[str, Any]) -> dict[str, Any]:
    site_name = (
        entry.get("site", {}).get("name")
        or entry.get("astroplan_3day", {}).get("site_name")
        or entry.get("three_day_precise", {}).get("site_name")
        or "unknown"
    )
    three_day = entry.get("astroplan_3day") or entry.get("three_day_precise") or {}
    nights = three_day.get("nights", [])
    total_hours = three_day.get("total_observable_hours")
    if total_hours is None:
        total_hours = three_day.get("total_good_hours", 0.0)
    best_night = None
    if nights:
        best_night = max(
            nights,
            key=lambda row: float(row.get("observable_hours", row.get("good_hours", 0.0)) or 0.0),
        )
    return {
        "site_name": site_name,
        "method": three_day.get("calculation_method"),
        "total_observable_hours": float(total_hours or 0.0),
        "best_night": json_safe(best_night),
        "nights": json_safe(nights),
    }


def _hours_plot(site_rows: list[dict[str, Any]], output_path: Path) -> Path | None:
    if not site_rows:
        return None
    labels = [row["site_name"] for row in site_rows]
    values = [float(row["total_observable_hours"]) for row in site_rows]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(labels, values, color=["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"][: len(labels)])
    for idx, value in enumerate(values):
        ax.text(idx, value + 0.05, f"{value:.1f}", ha="center", va="bottom")
    ax.set_title("SNC 3-Day Observability Forecast")
    ax.set_ylabel("Observable hours over next 3 days")
    ax.grid(alpha=0.2, axis="y")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Forecast the next 3 days of SNC observability for a target.")
    parser.add_argument("--name", help="Source name.")
    parser.add_argument("--ra", type=float, help="RA in degrees.")
    parser.add_argument("--dec", type=float, help="Dec in degrees.")
    parser.add_argument("--site", action="append", help="Limit to a specific site name. Repeat for multiple sites.")
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    resolved = resolve_target(REPO_ROOT, name=args.name, ra=args.ra, dec=args.dec)
    if resolved["ra"] is None or resolved["dec"] is None:
        raise SystemExit("Observability needs RA/Dec directly or via a cached workspace target name.")

    output_dir = ensure_output_dir(REPO_ROOT, "snc-observability-3day", resolved["name"], args.output_dir)
    results = get_best_observability_analysis(float(resolved["ra"]), float(resolved["dec"]), site_names=args.site)
    summaries = [_site_summary(entry) for entry in results if isinstance(entry, dict) and "error" not in entry]
    summaries.sort(key=lambda row: row["total_observable_hours"], reverse=True)
    best_site = summaries[0] if summaries else None

    plot_path = _hours_plot(
        summaries,
        output_dir / f"{safe_slug(resolved['name'])}_observability_3day.png",
    )

    payload = {
        "skill": "snc-observability-3day",
        "workspace_alignment": "Matches the SNC forward-looking 3-day observability analysis across workspace telescope sites.",
        "target": {
            "name": resolved["name"],
            "ra": resolved["ra"],
            "dec": resolved["dec"],
            "resolved_from": resolved["resolved_from"],
        },
        "site_filter": args.site,
        "best_site": json_safe(best_site),
        "sites": json_safe(summaries),
        "artifact": str(plot_path) if plot_path is not None else None,
    }
    json_path = write_json(output_dir / f"{safe_slug(resolved['name'])}_observability_3day.json", payload)
    payload["json_path"] = str(json_path)
    print(json.dumps(json_safe(payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
