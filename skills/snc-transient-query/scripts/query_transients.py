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

from _snc_skill_support import (  # noqa: E402
    bootstrap_repo_root,
    dataframe_records,
    ensure_output_dir,
    json_safe,
    normalize_name,
    resolve_target,
    safe_slug,
    write_json,
)

REPO_ROOT = bootstrap_repo_root(__file__)
from src.tns_project.core.tns_fetcher import fetch_tns_data_from_web  # noqa: E402
from src.tns_project.core.ztf_broker_client import ZTFBrokerClient  # noqa: E402
from src.tns_project.utils.plotting import AstronomicalPlotter  # noqa: E402

LOGGER = logging.getLogger("snc_transient_query")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _filter_tns_dataframe(dataframe: pd.DataFrame | None, name: str | None, limit: int) -> pd.DataFrame:
    if dataframe is None or dataframe.empty:
        return pd.DataFrame()

    df = dataframe.copy()
    if "id" in df.columns:
        df["id"] = pd.to_numeric(df["id"], errors="coerce")
        df = df.sort_values("id", ascending=False, na_position="last")

    if name:
        target = normalize_name(name)
        mask = df["tns_name"].astype(str).map(normalize_name) == target
        filtered = df[mask].copy()
        return filtered.head(limit) if not filtered.empty else pd.DataFrame()

    return df.head(limit).copy()


def _plot_tns_sky(dataframe: pd.DataFrame, output_path: Path, title: str) -> Path | None:
    if dataframe.empty or "ra_deg" not in dataframe.columns or "dec_deg" not in dataframe.columns:
        return None

    plot_df = dataframe.copy()
    plot_df["ra_deg"] = pd.to_numeric(plot_df["ra_deg"], errors="coerce")
    plot_df["dec_deg"] = pd.to_numeric(plot_df["dec_deg"], errors="coerce")
    plot_df["discoverymag"] = pd.to_numeric(plot_df.get("discoverymag"), errors="coerce")
    plot_df = plot_df.dropna(subset=["ra_deg", "dec_deg"])
    if plot_df.empty:
        return None

    fig, ax = plt.subplots(figsize=(9, 5.5))
    color_values = plot_df["discoverymag"] if plot_df["discoverymag"].notna().any() else "#1f77b4"
    scatter = ax.scatter(
        plot_df["ra_deg"],
        plot_df["dec_deg"],
        c=color_values,
        cmap="viridis_r" if plot_df["discoverymag"].notna().any() else None,
        s=60,
        edgecolor="black",
        linewidth=0.3,
    )
    ax.set_title(title)
    ax.set_xlabel("RA (deg)")
    ax.set_ylabel("Dec (deg)")
    ax.grid(alpha=0.25)
    if plot_df["discoverymag"].notna().any():
        colorbar = fig.colorbar(scatter, ax=ax)
        colorbar.set_label("Discovery mag")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def _fallback_target_row(target_name: str, ra: float | None, dec: float | None, redshift: Any) -> pd.DataFrame:
    if ra is None or dec is None:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "tns_name": target_name,
                "ra_deg": ra,
                "dec_deg": dec,
                "redshift": redshift,
            }
        ]
    )


def _plot_broker_lightcurve(
    target_name: str,
    broker_frames: list[pd.DataFrame],
    output_path: Path,
    days_back: int,
) -> Path | None:
    valid_frames = [frame for frame in broker_frames if frame is not None and not frame.empty]
    if not valid_frames:
        return None

    merged = pd.concat(valid_frames, ignore_index=True, sort=False)
    if "mjd" in merged.columns:
        merged = merged.sort_values("mjd")
    plotter = AstronomicalPlotter(output_dir=str(output_path.parent))
    generated = plotter.plot_lightcurve(
        tns_name=target_name,
        ztf_data=merged,
        save_path=str(output_path),
        time_window_days=max(days_back, 30),
        use_days_ago=False,
    )
    return Path(generated) if generated else None


def _broker_summary(dataframe: pd.DataFrame | None) -> dict[str, Any]:
    if dataframe is None or dataframe.empty:
        return {"rows": 0, "filters": [], "mjd_min": None, "mjd_max": None}

    summary: dict[str, Any] = {"rows": int(len(dataframe))}
    if "filter" in dataframe.columns:
        summary["filters"] = sorted({str(item) for item in dataframe["filter"].dropna().tolist()})
    if "mjd" in dataframe.columns:
        mjd = pd.to_numeric(dataframe["mjd"], errors="coerce").dropna()
        summary["mjd_min"] = float(mjd.min()) if not mjd.empty else None
        summary["mjd_max"] = float(mjd.max()) if not mjd.empty else None
    return json_safe(summary)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query recent TNS candidates and optional ZTF broker photometry.",
    )
    parser.add_argument("--name", help="Transient name, for example 'SN 2026fvx'.")
    parser.add_argument("--ra", type=float, help="RA in degrees.")
    parser.add_argument("--dec", type=float, help="Dec in degrees.")
    parser.add_argument("--days-back", type=int, default=3, help="Recent TNS window in days.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of TNS rows.")
    parser.add_argument(
        "--skip-brokers",
        action="store_true",
        help="Do not query ALeRCE/Lasair broker photometry.",
    )
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    resolved = resolve_target(REPO_ROOT, name=args.name, ra=args.ra, dec=args.dec)
    target_name = resolved["name"]
    output_dir = ensure_output_dir(REPO_ROOT, "snc-transient-query", target_name, args.output_dir)

    tns_df = fetch_tns_data_from_web()
    filtered_tns = _filter_tns_dataframe(tns_df, args.name, args.limit)

    if filtered_tns.empty and resolved["tns_entry"]:
        filtered_tns = pd.DataFrame(
            [
                {
                    "tns_name": resolved["tns_key"] or target_name,
                    "ra_deg": resolved["tns_entry"].get("ra"),
                    "dec_deg": resolved["tns_entry"].get("dec"),
                    "redshift": resolved["tns_entry"].get("redshift"),
                    "discoverydate": resolved["tns_entry"].get("discovery_date"),
                    "source_group_name": resolved["tns_entry"].get("source_group_name"),
                }
            ]
        )

    broker = ZTFBrokerClient()
    alerce_df: pd.DataFrame | None = None
    lasair_df: pd.DataFrame | None = None
    if not args.skip_brokers and resolved["ra"] is not None and resolved["dec"] is not None:
        try:
            alerce_df = broker.search_alerce_by_coordinates(
                ra_deg=resolved["ra"],
                dec_deg=resolved["dec"],
                days_back=max(args.days_back, 30),
            )
        except Exception as exc:
            LOGGER.warning("ALeRCE broker query failed: %s", exc)
        try:
            lasair_df = broker.search_lasair_by_coordinates(
                ra_deg=resolved["ra"],
                dec_deg=resolved["dec"],
                days_back=max(args.days_back, 30),
            )
        except Exception as exc:
            LOGGER.warning("Lasair broker query failed: %s", exc)

    artifacts: dict[str, Any] = {}
    sky_source = filtered_tns
    if sky_source.empty or sky_source[["ra_deg", "dec_deg"]].isna().all().all():
        sky_source = _fallback_target_row(
            target_name=target_name,
            ra=resolved["ra"],
            dec=resolved["dec"],
            redshift=(resolved["tns_entry"] or {}).get("redshift"),
        )

    sky_plot = _plot_tns_sky(
        sky_source,
        output_dir / f"{safe_slug(target_name)}_tns_sky.png",
        title=f"TNS Query Results: {target_name}",
    )
    if sky_plot is not None:
        artifacts["tns_sky_plot"] = str(sky_plot)

    lightcurve_plot = _plot_broker_lightcurve(
        target_name=target_name,
        broker_frames=[frame for frame in [alerce_df, lasair_df] if frame is not None],
        output_path=output_dir / f"{safe_slug(target_name)}_broker_lightcurve.png",
        days_back=args.days_back,
    )
    if lightcurve_plot is not None:
        artifacts["broker_lightcurve"] = str(lightcurve_plot)

    result = {
        "query": {
            "name": args.name,
            "ra": args.ra,
            "dec": args.dec,
            "days_back": args.days_back,
            "limit": args.limit,
            "skip_brokers": args.skip_brokers,
        },
        "resolved_target": {
            "name": target_name,
            "ra": resolved["ra"],
            "dec": resolved["dec"],
            "resolved_from": resolved["resolved_from"],
        },
        "tns_matches": {
            "count": int(len(filtered_tns)),
            "rows": dataframe_records(
                filtered_tns,
                columns=[
                    "tns_name",
                    "type",
                    "ra",
                    "dec",
                    "ra_deg",
                    "dec_deg",
                    "redshift",
                    "discoverymag",
                    "discoverydate",
                    "source_group_name",
                ],
                limit=args.limit,
            ),
        },
        "brokers": {
            "alerce": _broker_summary(alerce_df),
            "lasair": _broker_summary(lasair_df),
        },
        "artifacts": artifacts,
    }

    json_path = write_json(output_dir / f"{safe_slug(target_name)}_transient_query.json", result)
    result["json_path"] = str(json_path)
    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
