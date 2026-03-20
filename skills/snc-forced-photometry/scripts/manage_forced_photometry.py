from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from _snc_skill_support import (  # noqa: E402
    bootstrap_repo_root,
    dataframe_records,
    ensure_output_dir,
    find_requests_by_name,
    json_safe,
    load_request_cache,
    resolve_target,
    safe_slug,
    write_json,
)

REPO_ROOT = bootstrap_repo_root(__file__)
from src.tns_project.core.ztf_forced_photometry import ZTFForcedPhotometryClient  # noqa: E402
from src.tns_project.utils.plotting import AstronomicalPlotter  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _status_plot(rows: list[dict[str, Any]], output_path: Path, title: str) -> Path | None:
    if not rows:
        return None
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown").lower()
        counts[status] = counts.get(status, 0) + 1

    labels = list(counts.keys())
    values = [counts[label] for label in labels]
    palette = {
        "completed": "#2ca02c",
        "processing": "#1f77b4",
        "submitted": "#ff7f0e",
        "timeout": "#d62728",
        "failed": "#d62728",
        "unknown": "#7f7f7f",
    }
    colors = [palette.get(label, "#7f7f7f") for label in labels]

    fig, ax = plt.subplots(figsize=(7.5, 4))
    ax.bar(labels, values, color=colors)
    for idx, value in enumerate(values):
        ax.text(idx, value + 0.05, str(value), ha="center", va="bottom")
    ax.set_title(title)
    ax.set_ylabel("Request count")
    ax.grid(alpha=0.2, axis="y")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def _lightcurve_plot(source_name: str, photometry_df, output_path: Path) -> Path | None:
    if photometry_df is None or photometry_df.empty:
        return None
    plotter = AstronomicalPlotter(output_dir=str(output_path.parent))
    generated = plotter.plot_lightcurve(
        tns_name=source_name,
        ztf_data=photometry_df,
        save_path=str(output_path),
        time_window_days=180,
        use_days_ago=False,
    )
    return Path(generated) if generated else None


def _find_requests_by_id(request_id: str | None) -> list[dict[str, Any]]:
    if not request_id:
        return []
    return [row for row in load_request_cache(REPO_ROOT) if row.get("request_id") == request_id]


def _run_submit(args, client: ZTFForcedPhotometryClient, output_dir: Path) -> dict[str, Any]:
    resolved = resolve_target(REPO_ROOT, name=args.name, ra=args.ra, dec=args.dec)
    if resolved["ra"] is None or resolved["dec"] is None:
        raise SystemExit("Submission needs RA/Dec directly or via a cached target name.")

    if args.incremental:
        request_id = client.submit_incremental_forced_photometry(
            source_name=resolved["name"],
            ra=float(resolved["ra"]),
            dec=float(resolved["dec"]),
        )
    else:
        request_id = client.submit_normal_forced_photometry(
            ra=float(resolved["ra"]),
            dec=float(resolved["dec"]),
            jd_start=args.jd_start,
            jd_end=args.jd_end,
            source_name=resolved["name"],
            use_conservative_window=args.jd_start is None or args.jd_end is None,
        )

    matching_rows = _find_requests_by_id(request_id) if request_id else []
    plot_path = _status_plot(
        matching_rows if matching_rows else load_request_cache(REPO_ROOT),
        output_dir / f"{safe_slug(resolved['name'])}_request_status.png",
        title=f"ZTF Forced Photometry Status: {resolved['name']}",
    )
    return {
        "action": "submit",
        "target": {
            "name": resolved["name"],
            "ra": resolved["ra"],
            "dec": resolved["dec"],
        },
        "request_id": request_id,
        "requests": json_safe(matching_rows),
        "artifact": str(plot_path) if plot_path is not None else None,
    }


def _run_status(args, client: ZTFForcedPhotometryClient, output_dir: Path) -> dict[str, Any]:
    if args.refresh:
        try:
            client.check_pending_requests()
        except Exception as exc:
            logging.warning("Refreshing pending requests failed: %s", exc)

    rows = _find_requests_by_id(args.request_id)
    if not rows and args.name:
        rows = find_requests_by_name(REPO_ROOT, args.name)
    if not rows:
        rows = load_request_cache(REPO_ROOT)

    plot_name = args.name or args.request_id or "ztf_forced_requests"
    plot_path = _status_plot(
        rows,
        output_dir / f"{safe_slug(plot_name)}_status_summary.png",
        title=f"ZTF Forced Photometry Monitor: {plot_name}",
    )

    return {
        "action": "status",
        "request_id": args.request_id,
        "name": args.name,
        "refresh": args.refresh,
        "requests": json_safe(rows),
        "artifact": str(plot_path) if plot_path is not None else None,
    }


def _run_fetch(args, client: ZTFForcedPhotometryClient, output_dir: Path) -> dict[str, Any]:
    photometry_df, data_path = client.get_photometry_for_source({"tns_name": args.name})
    if photometry_df is None or photometry_df.empty:
        raise SystemExit(f"No forced photometry found for {args.name}.")

    plot_path = _lightcurve_plot(
        args.name,
        photometry_df,
        output_dir / f"{safe_slug(args.name)}_forced_lightcurve.png",
    )
    return {
        "action": "fetch",
        "name": args.name,
        "data_path": data_path,
        "photometry_summary": {
            "rows": int(len(photometry_df)),
            "mjd_min": float(photometry_df["mjd"].min()),
            "mjd_max": float(photometry_df["mjd"].max()),
            "detections": int(photometry_df["is_detection"].sum()) if "is_detection" in photometry_df.columns else None,
            "filters": sorted({str(item) for item in photometry_df["filter"].dropna().tolist()}) if "filter" in photometry_df.columns else [],
            "preview": dataframe_records(
                photometry_df,
                columns=["mjd", "filter", "mag", "magerr", "snr", "is_detection"],
                limit=25,
            ),
        },
        "artifact": str(plot_path) if plot_path is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit, monitor, or fetch ZTF forced photometry.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit_parser = subparsers.add_parser("submit", help="Submit a new forced-photometry request.")
    submit_parser.add_argument("--name", required=True, help="Source name.")
    submit_parser.add_argument("--ra", type=float, help="RA in degrees.")
    submit_parser.add_argument("--dec", type=float, help="Dec in degrees.")
    submit_parser.add_argument("--jd-start", type=float, help="Start JD.")
    submit_parser.add_argument("--jd-end", type=float, help="End JD.")
    submit_parser.add_argument("--incremental", action="store_true", help="Submit an incremental request.")
    submit_parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    submit_parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    status_parser = subparsers.add_parser("status", help="Inspect cached/pending requests.")
    status_parser.add_argument("--name", help="Filter by source name.")
    status_parser.add_argument("--request-id", help="Filter by request id.")
    status_parser.add_argument("--refresh", action="store_true", help="Refresh pending states before reading cache.")
    status_parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    status_parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    fetch_parser = subparsers.add_parser("fetch", help="Load downloaded forced photometry and plot it.")
    fetch_parser.add_argument("--name", required=True, help="Source name.")
    fetch_parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    fetch_parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    args = parser.parse_args()
    _setup_logging(getattr(args, "verbose", False))

    target_name = getattr(args, "name", None) or getattr(args, "request_id", None) or "ztf-forced-photometry"
    output_dir = ensure_output_dir(REPO_ROOT, "snc-forced-photometry", target_name, getattr(args, "output_dir", None))
    os.chdir(REPO_ROOT)
    client = ZTFForcedPhotometryClient(cache_dir=str(REPO_ROOT / "data" / "ztf_forced_cache"))

    if args.command == "submit":
        result = _run_submit(args, client, output_dir)
    elif args.command == "status":
        result = _run_status(args, client, output_dir)
    else:
        result = _run_fetch(args, client, output_dir)

    json_path = write_json(output_dir / f"{safe_slug(target_name)}_forced_photometry.json", result)
    result["json_path"] = str(json_path)
    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
