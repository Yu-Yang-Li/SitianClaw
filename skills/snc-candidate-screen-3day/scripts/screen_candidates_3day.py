from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from _snc_skill_support import (
    bootstrap_repo_root,
    dataframe_records,
    ensure_output_dir,
    json_safe,
    write_json,
)

REPO_ROOT = bootstrap_repo_root(__file__)
from src.tns_project.config.astronomical_config import get_astronomical_config  # noqa: E402
from src.tns_project.core.astronomical_processor import (  # noqa: E402
    apply_astronomical_processing,
    _apply_discovery_date_filter,
    _apply_galactic_latitude_filter,
    _apply_redshift_filter,
    _ensure_required_columns,
    _process_data_types,
    _process_host_information,
)
from src.tns_project.core.tns_fetcher import fetch_combined_data  # noqa: E402


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


def _final_summary(dataframe: pd.DataFrame) -> dict[str, Any]:
    if dataframe.empty:
        return {
            "row_count": 0,
            "host_redshift_available": 0,
            "median_host_redshift": None,
            "median_abs_galactic_latitude": None,
        }

    host_redshift = pd.to_numeric(dataframe.get("host_redshift"), errors="coerce")
    host_galactic_b = pd.to_numeric(dataframe.get("host_galactic_b"), errors="coerce")
    return {
        "row_count": int(len(dataframe)),
        "host_redshift_available": int(host_redshift.notna().sum()),
        "median_host_redshift": float(host_redshift.dropna().median()) if host_redshift.notna().any() else None,
        "median_abs_galactic_latitude": float(host_galactic_b.abs().dropna().median())
        if host_galactic_b.notna().any()
        else None,
    }


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

    config = get_astronomical_config()
    if args.recent_days is not None:
        config["RECENT_DISCOVERY_DAYS"] = args.recent_days
    if args.redshift_max is not None:
        config["REDSHIFT_RANGE"] = (0.0, args.redshift_max)
    if args.min_galactic_latitude is not None:
        config["MIN_GALACTIC_LATITUDE"] = args.min_galactic_latitude

    working_df = _ensure_required_columns(raw_df.copy())
    working_df = _process_data_types(working_df)
    after_time = _apply_discovery_date_filter(working_df, config["RECENT_DISCOVERY_DAYS"], config)
    after_host = _process_host_information(after_time, config)
    if "host_redshift" in after_host.columns:
        host_z = pd.to_numeric(after_host["host_redshift"], errors="coerce")
        near_zero = host_z.le(1e-5)
        after_host.loc[near_zero.fillna(False), "host_redshift"] = np.nan
    after_redshift = _apply_redshift_filter(
        after_host,
        config["REDSHIFT_RANGE"],
        config["RECENT_DISCOVERY_DAYS"],
        config,
    )
    after_galactic = _apply_galactic_latitude_filter(after_redshift, config["MIN_GALACTIC_LATITUDE"])
    final_df = after_galactic.copy()
    filter_mode = "strict"
    relaxed_summary: dict[str, Any] | None = None

    if final_df.empty and not args.disable_relaxed_fallback:
        relaxed_config = get_astronomical_config()
        relaxed_config["REDSHIFT_RANGE"] = (0.0, 0.05)
        relaxed_config["RECENT_DISCOVERY_DAYS"] = 7
        relaxed_config["ENABLE_SECONDARY_HOST_MATCH"] = False
        relaxed_df = apply_astronomical_processing(
            df=raw_df.copy(),
            redshift_range=(0.0, 0.05),
            config=relaxed_config,
        )
        relaxed_summary = {
            "enabled": True,
            "recent_discovery_days": 7,
            "redshift_range": [0.0, 0.05],
            "row_count": int(len(relaxed_df)),
        }
        if not relaxed_df.empty:
            final_df = relaxed_df.copy()
            final_df["_filter_mode"] = "relaxed"
            filter_mode = "relaxed"

    raw_csv_path = output_dir / "candidate_screen_3day_raw.csv"
    final_csv_path = output_dir / "candidate_screen_3day.csv"
    raw_df.to_csv(raw_csv_path, index=False)
    final_df.to_csv(final_csv_path, index=False)

    stage_counts = {
        "raw": int(len(raw_df)),
        "date_cut": int(len(after_time)),
        "host_enriched": int(len(after_host)),
        "redshift_cut": int(len(after_redshift)),
        "strict_final": int(len(after_galactic)),
        "returned_final": int(len(final_df)),
    }
    stage_plot_path = _stage_plot(stage_counts, output_dir / "candidate_screen_3day_stage_counts.png")

    payload: dict[str, Any] = {
        "skill": "snc-candidate-screen-3day",
        "workspace_alignment": "Matches DataCycleHandler._apply_astronomical_processing() strict mode on the current SNC workspace.",
        "config": {
            "recent_discovery_days": config["RECENT_DISCOVERY_DAYS"],
            "redshift_range": list(config["REDSHIFT_RANGE"]),
            "min_galactic_latitude": config["MIN_GALACTIC_LATITUDE"],
        },
        "filter_mode": filter_mode,
        "relaxed_fallback": json_safe(relaxed_summary),
        "crawl_summary": json_safe(fetch_result.get("summary", {})),
        "stage_counts": stage_counts,
        "final_summary": _final_summary(final_df),
        "preview": dataframe_records(
            final_df,
            columns=[
                "tns_name",
                "type",
                "discoverydate",
                "host_name",
                "host_redshift",
                "host_galactic_b",
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
