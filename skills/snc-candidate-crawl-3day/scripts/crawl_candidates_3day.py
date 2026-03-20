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
    _apply_discovery_date_filter,
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


def _source_counts(dataframe: pd.DataFrame) -> dict[str, int]:
    if dataframe.empty:
        return {}
    if "data_source" in dataframe.columns:
        source_series = dataframe["data_source"].fillna("unknown").astype(str)
    elif "source_group_name" in dataframe.columns:
        source_series = dataframe["source_group_name"].fillna("unknown").astype(str)
    else:
        source_series = pd.Series(["unknown"] * len(dataframe))
    counts = source_series.value_counts(dropna=False).to_dict()
    return {str(key): int(value) for key, value in counts.items()}


def _coord_series(dataframe: pd.DataFrame, candidates: list[str]) -> pd.Series:
    for column in candidates:
        if column in dataframe.columns:
            values = pd.to_numeric(dataframe[column], errors="coerce")
            if values.notna().any():
                return values
    return pd.Series([float("nan")] * len(dataframe), index=dataframe.index, dtype="float64")


def _plot_source_mix(source_counts: dict[str, int], output_path: Path) -> Path | None:
    if not source_counts:
        return None
    labels = list(source_counts.keys())
    values = [source_counts[label] for label in labels]
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.bar(labels, values, color=["#1f77b4", "#ff7f0e", "#2ca02c", "#7f7f7f"][: len(labels)])
    for idx, value in enumerate(values):
        ax.text(idx, value + 0.2, str(value), ha="center", va="bottom")
    ax.set_title("SNC 3-Day Candidate Crawl: Source Mix")
    ax.set_ylabel("Candidates")
    ax.grid(alpha=0.2, axis="y")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def _plot_sky_distribution(dataframe: pd.DataFrame, output_path: Path) -> Path | None:
    if dataframe.empty:
        return None

    ra_series = _coord_series(dataframe, ["ra_deg", "ra"])
    dec_series = _coord_series(dataframe, ["dec_deg", "dec"])
    mask = ra_series.notna() & dec_series.notna()
    if not mask.any():
        return None

    plot_df = dataframe.loc[mask].copy()
    plot_df["plot_ra"] = ra_series.loc[mask]
    plot_df["plot_dec"] = dec_series.loc[mask]

    fig, ax = plt.subplots(figsize=(8, 5))
    if "data_source" in plot_df.columns:
        grouped = plot_df.groupby(plot_df["data_source"].fillna("unknown").astype(str))
        palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#7f7f7f"]
        for idx, (label, group) in enumerate(grouped):
            ax.scatter(
                group["plot_ra"],
                group["plot_dec"],
                s=24,
                alpha=0.8,
                label=label,
                color=palette[idx % len(palette)],
            )
        ax.legend(loc="best", fontsize=8)
    else:
        ax.scatter(plot_df["plot_ra"], plot_df["plot_dec"], s=24, alpha=0.8, color="#1f77b4")

    ax.set_title("SNC 3-Day Candidate Crawl: Sky Distribution")
    ax.set_xlabel("RA (deg)")
    ax.set_ylabel("Dec (deg)")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def _resolve_nearby_redshift(dataframe: pd.DataFrame) -> pd.Series:
    host_z = pd.to_numeric(dataframe.get("host_redshift"), errors="coerce")
    source_z = pd.to_numeric(dataframe.get("redshift"), errors="coerce")
    resolved = host_z.where(host_z.notna(), source_z)
    resolved = resolved.where(resolved > 1e-5, np.nan)
    return resolved


def _plot_nearby_redshift_histogram(dataframe: pd.DataFrame, output_path: Path) -> Path | None:
    if dataframe.empty or "nearby_redshift" not in dataframe.columns:
        return None
    z = pd.to_numeric(dataframe["nearby_redshift"], errors="coerce").dropna()
    if z.empty:
        return None
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.hist(z, bins=min(12, max(4, len(z))), color="#55a868", edgecolor="white")
    ax.set_title("SNC 3-Day Nearby Candidate Pool: Redshift Distribution")
    ax.set_xlabel("Resolved redshift")
    ax.set_ylabel("Candidates")
    ax.grid(alpha=0.2, axis="y")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch the SNC raw 3-day candidate pool from TNS, ZTF, and LSST brokers."
    )
    parser.add_argument("--ztf-days-back", type=int, default=3, help="How many days of ZTF broker data to pull.")
    parser.add_argument("--ztf-max-candidates", type=int, default=300, help="Maximum ZTF broker candidates.")
    parser.add_argument("--lsst-hours-back", type=int, default=72, help="How many hours of LSST broker data to pull.")
    parser.add_argument("--lsst-max-candidates", type=int, default=200, help="Maximum LSST broker candidates.")
    parser.add_argument("--skip-ztf", action="store_true", help="Skip the ZTF broker component.")
    parser.add_argument("--skip-lsst", action="store_true", help="Skip the LSST broker component.")
    parser.add_argument("--recent-days", type=int, default=3, help="Recent-window filter before host-redshift enrichment.")
    parser.add_argument("--nearby-redshift-max", type=float, default=0.05, help="Nearby-universe redshift ceiling for the candidate pool.")
    parser.add_argument("--output-dir", help="Directory for JSON, CSV, and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    output_dir = ensure_output_dir(REPO_ROOT, "snc-candidate-crawl-3day", "latest", args.output_dir)

    result = fetch_combined_data(
        include_ztf=not args.skip_ztf,
        include_lsst=not args.skip_lsst,
        ztf_days_back=args.ztf_days_back,
        ztf_max_candidates=args.ztf_max_candidates,
        lsst_hours_back=args.lsst_hours_back,
        lsst_max_candidates=args.lsst_max_candidates,
    )

    combined_data = result.get("combined_data")
    if combined_data is None:
        combined_data = pd.DataFrame()
    config = get_astronomical_config()
    config["RECENT_DISCOVERY_DAYS"] = args.recent_days

    recent_df = _ensure_required_columns(combined_data.copy())
    recent_df = _process_data_types(recent_df)
    recent_df = _apply_discovery_date_filter(recent_df, args.recent_days, config)
    nearby_input = _process_host_information(recent_df.copy(), config) if not recent_df.empty else recent_df.copy()
    nearby_input["nearby_redshift"] = _resolve_nearby_redshift(nearby_input)
    nearby_pool = nearby_input.loc[
        nearby_input["nearby_redshift"].notna() & (nearby_input["nearby_redshift"] <= args.nearby_redshift_max)
    ].copy()
    nearby_pool = nearby_pool.sort_values("nearby_redshift", ascending=True, na_position="last")

    csv_path = output_dir / "candidate_crawl_3day.csv"
    nearby_csv_path = output_dir / "candidate_crawl_3day_nearby.csv"
    combined_data.to_csv(csv_path, index=False)
    nearby_pool.to_csv(nearby_csv_path, index=False)

    source_counts = _source_counts(combined_data)
    mix_plot_path = _plot_source_mix(source_counts, output_dir / "candidate_crawl_3day_source_mix.png")
    sky_plot_path = _plot_sky_distribution(combined_data, output_dir / "candidate_crawl_3day_sky.png")
    nearby_redshift_plot = _plot_nearby_redshift_histogram(
        nearby_pool,
        output_dir / "candidate_crawl_3day_nearby_redshift.png",
    )

    payload: dict[str, Any] = {
        "skill": "snc-candidate-crawl-3day",
        "workspace_alignment": "Matches DataCycleHandler._fetch_tns_data(), then binds the recent candidate pool to host-redshift resolution for nearby-universe triage.",
        "parameters": {
            "include_ztf": not args.skip_ztf,
            "include_lsst": not args.skip_lsst,
            "ztf_days_back": args.ztf_days_back,
            "ztf_max_candidates": args.ztf_max_candidates,
            "lsst_hours_back": args.lsst_hours_back,
            "lsst_max_candidates": args.lsst_max_candidates,
            "recent_days": args.recent_days,
            "nearby_redshift_max": args.nearby_redshift_max,
        },
        "summary": json_safe(result.get("summary", {})),
        "row_count": int(len(combined_data)),
        "recent_row_count": int(len(recent_df)),
        "nearby_row_count": int(len(nearby_pool)),
        "columns": list(combined_data.columns),
        "source_counts": source_counts,
        "nearby_preview": dataframe_records(
            nearby_pool,
            columns=[
                "tns_name",
                "type",
                "discoverydate",
                "host_name",
                "host_redshift",
                "redshift",
                "nearby_redshift",
                "data_source",
            ],
            limit=30,
        ),
        "preview": dataframe_records(
            combined_data,
            columns=[
                "tns_name",
                "type",
                "discoverydate",
                "discoverymag",
                "data_source",
                "ra_deg",
                "dec_deg",
            ],
            limit=30,
        ),
        "artifacts": {
            "csv": str(csv_path),
            "nearby_csv": str(nearby_csv_path),
            "source_mix_plot": str(mix_plot_path) if mix_plot_path is not None else None,
            "sky_plot": str(sky_plot_path) if sky_plot_path is not None else None,
            "nearby_redshift_plot": str(nearby_redshift_plot) if nearby_redshift_plot is not None else None,
        },
    }

    json_path = write_json(output_dir / "candidate_crawl_3day.json", payload)
    payload["json_path"] = str(json_path)
    print(json.dumps(json_safe(payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
