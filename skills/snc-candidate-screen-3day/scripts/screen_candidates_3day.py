from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from sitianclaw_runtime.candidates import fetch_combined_data  # noqa: E402
from sitianclaw_runtime.runtime import (  # noqa: E402
    dataframe_records,
    ensure_output_dir,
    json_safe,
    write_json,
)
from sitianclaw_runtime.screening import get_portable_screening_config, run_candidate_screen  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _stage_plot(stage_counts: dict[str, int], output_path: Path) -> Path:
    labels = list(stage_counts.keys())
    values = [stage_counts[label] for label in labels]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(labels, values, color=["#4c72b0", "#55a868", "#c44e52", "#8172b3", "#ccb974"])
    for idx, value in enumerate(values):
        ax.text(idx, value + max(values + [1]) * 0.02, str(value), ha="center", va="bottom")
    ax.set_title("SNC 3-Day Screening: Stage Counts")
    ax.set_ylabel("Candidates")
    ax.grid(alpha=0.2, axis="y")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply the SNC 3-day shortlist screening pipeline to the freshly crawled candidate pool."
    )
    parser.add_argument("--ztf-days-back", type=int, default=3, help="How many days of ZTF broker data to pull.")
    parser.add_argument("--ztf-max-candidates", type=int, default=300, help="Maximum ZTF broker candidates.")
    parser.add_argument("--lsst-hours-back", type=int, default=72, help="How many hours of LSST broker data to pull.")
    parser.add_argument("--lsst-max-candidates", type=int, default=200, help="Maximum LSST broker candidates.")
    parser.add_argument("--recent-days", type=int, help="Override RECENT_DISCOVERY_DAYS.")
    parser.add_argument("--redshift-max", type=float, help="Override the host-galaxy redshift ceiling.")
    parser.add_argument("--min-galactic-latitude", type=float, help="Override the absolute galactic latitude cut.")
    parser.add_argument("--disable-relaxed-fallback", action="store_true", help="Disable the workspace relaxed fallback when strict screening returns zero targets.")
    parser.add_argument("--output-dir", help="Directory for JSON, CSV, and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    output_dir = ensure_output_dir(REPO_ROOT, "snc-candidate-screen-3day", "latest", args.output_dir)

    fetch_result = fetch_combined_data(
        include_ztf=True,
        include_lsst=True,
        ztf_days_back=args.ztf_days_back,
        ztf_max_candidates=args.ztf_max_candidates,
        lsst_hours_back=args.lsst_hours_back,
        lsst_max_candidates=args.lsst_max_candidates,
    )
    raw_df = fetch_result.get("combined_data")
    if raw_df is None:
        raw_df = pd.DataFrame()

    config = get_portable_screening_config()
    if args.recent_days is not None:
        config["RECENT_DISCOVERY_DAYS"] = args.recent_days
    if args.redshift_max is not None:
        config["REDSHIFT_RANGE"] = (0.0, args.redshift_max)
    if args.min_galactic_latitude is not None:
        config["MIN_GALACTIC_LATITUDE"] = args.min_galactic_latitude

    screen_result = run_candidate_screen(raw_df=raw_df.copy(), config=config, disable_relaxed_fallback=args.disable_relaxed_fallback)
    after_time = screen_result["after_time"]
    after_host = screen_result["after_host"]
    after_redshift = screen_result["after_redshift"]
    after_galactic = screen_result["after_galactic"]
    final_df = screen_result["final_df"]
    filter_mode = screen_result["filter_mode"]
    relaxed_summary = screen_result["relaxed_fallback"]

    raw_csv_path = output_dir / "candidate_screen_3day_raw.csv"
    final_csv_path = output_dir / "candidate_screen_3day.csv"
    raw_df.to_csv(raw_csv_path, index=False)
    final_df.to_csv(final_csv_path, index=False)

    stage_counts = screen_result["stage_counts"]
    stage_plot_path = _stage_plot(stage_counts, output_dir / "candidate_screen_3day_stage_counts.png")

    payload: dict[str, Any] = {
        "skill": "snc-candidate-screen-3day",
        "workspace_alignment": "GitHub-only portable shortlist aligned to the SNC strict 3-day screening defaults and relaxed fallback.",
        "config": {
            "recent_discovery_days": config["RECENT_DISCOVERY_DAYS"],
            "redshift_range": list(config["REDSHIFT_RANGE"]),
            "min_galactic_latitude": config["MIN_GALACTIC_LATITUDE"],
        },
        "filter_mode": filter_mode,
        "relaxed_fallback": json_safe(relaxed_summary),
        "crawl_summary": json_safe(fetch_result.get("summary", {})),
        "host_query_summary": json_safe(screen_result["host_query_summary"]),
        "stage_counts": stage_counts,
        "final_summary": screen_result["final_summary"],
        "preview": dataframe_records(
            final_df,
            columns=[
                "tns_name",
                "type",
                "discoverydate",
                "host_name",
                "host_redshift",
                "effective_redshift",
                "source_galactic_b",
                "data_source",
            ],
            limit=30,
        ),
        "artifacts": {
            "raw_csv": str(raw_csv_path),
            "screened_csv": str(final_csv_path),
            "stage_plot": str(stage_plot_path),
        },
    }

    json_path = write_json(output_dir / "candidate_screen_3day.json", payload)
    payload["json_path"] = str(json_path)
    print(json.dumps(json_safe(payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
