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

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from sitianclaw_runtime.forced_phot import (  # noqa: E402
    credentials_status,
    find_requests_by_id,
    find_requests_by_name,
    load_request_records,
    portable_cache_dir,
    read_forced_photometry_file,
    refresh_request_statuses,
    resolve_forced_photometry_path,
    status_counts,
    submit_forced_photometry,
)
from sitianclaw_runtime.runtime import dataframe_records, ensure_output_dir, json_safe, safe_slug, write_json  # noqa: E402
from sitianclaw_runtime.transients import plot_lightcurve, resolve_target  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _status_plot(rows: list[dict[str, Any]], output_path: Path, title: str) -> Path | None:
    if not rows:
        return None
    counts = status_counts(rows)
    labels = list(counts.keys())
    values = [counts[label] for label in labels]
    palette = {
        "completed": "#2ca02c",
        "processing": "#1f77b4",
        "submitted": "#ff7f0e",
        "timeout": "#d62728",
        "failed": "#d62728",
        "unknown": "#7f7f7f",
        "dry_run": "#9467bd",
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
    generated = plot_lightcurve(
        target_name=source_name,
        frames=[photometry_df],
        output_path=output_path,
        title_prefix="Forced Photometry",
    )
    return Path(generated) if generated else None


def _run_submit(args, output_dir: Path, cache_dir: Path) -> dict[str, Any]:
    resolved = resolve_target(name=args.name, ra=args.ra, dec=args.dec)
    if resolved["ra"] is None or resolved["dec"] is None:
        raise SystemExit("Submission needs RA/Dec directly or via public TNS name resolution.")

    records = load_request_records(cache_dir)
    submission = submit_forced_photometry(
        records,
        cache_dir=cache_dir,
        source_name=resolved["name"],
        ra=float(resolved["ra"]),
        dec=float(resolved["dec"]),
        jd_start=args.jd_start,
        jd_end=args.jd_end,
        incremental=bool(args.incremental),
        dry_run=bool(args.dry_run),
    )
    if not submission.get("ok"):
        raise SystemExit(submission.get("reason") or "Forced-photometry submission failed.")

    records_after = load_request_records(cache_dir)
    request_id = str(submission.get("request_id") or "")
    request_rows = [records_after[request_id]] if request_id in records_after else []
    if not request_rows and submission.get("record"):
        request_rows = [submission["record"]]
    plot_path = _status_plot(
        request_rows if request_rows else list(records_after.values()),
        output_dir / f"{safe_slug(resolved['name'])}_request_status.png",
        title=f"ZTF Forced Photometry Status: {resolved['name']}",
    )
    return {
        "action": "submit",
        "target": {
            "name": resolved["name"],
            "ra": resolved["ra"],
            "dec": resolved["dec"],
            "resolved_from": resolved["resolved_from"],
        },
        "cache_dir": str(cache_dir),
        "credentials": credentials_status(),
        "dry_run": bool(args.dry_run),
        "incremental": bool(args.incremental),
        "request_id": request_id,
        "submission": json_safe(submission),
        "requests": json_safe(request_rows),
        "artifact": str(plot_path) if plot_path is not None else None,
    }


def _run_status(args, output_dir: Path, cache_dir: Path) -> dict[str, Any]:
    records = load_request_records(cache_dir)
    email_scan_result: dict[str, Any] | None = None
    if args.scan_emails:
        email_scan_result = {
            "supported": False,
            "reason": "GitHub-only portable monitor does not bundle IMAP mailbox scanning.",
            "days_back": args.days_back,
            "max_emails": args.max_emails,
        }

    status_updates: dict[str, Any] | None = None
    if args.refresh:
        status_updates = refresh_request_statuses(
            records,
            cache_dir=cache_dir,
            request_id=args.request_id,
            source_name=args.name,
        )
        records = load_request_records(cache_dir)

    rows = find_requests_by_id(records, args.request_id)
    if not rows and args.name:
        rows = find_requests_by_name(records, args.name)
    if not rows:
        rows = sorted(records.values(), key=lambda item: str(item.get("submit_time") or item.get("request_id") or ""), reverse=True)

    plot_name = args.name or args.request_id or "ztf_forced_requests"
    plot_path = _status_plot(
        rows,
        output_dir / f"{safe_slug(plot_name)}_status_summary.png",
        title=f"ZTF Forced Photometry Monitor: {plot_name}",
    )
    return {
        "action": "status",
        "name": args.name,
        "request_id": args.request_id,
        "cache_dir": str(cache_dir),
        "refresh": bool(args.refresh),
        "scan_emails": bool(args.scan_emails),
        "email_scan_result": json_safe(email_scan_result),
        "status_updates": json_safe(status_updates),
        "requests": json_safe(rows),
        "artifact": str(plot_path) if plot_path is not None else None,
    }


def _run_fetch(args, output_dir: Path, cache_dir: Path) -> dict[str, Any]:
    data_path = resolve_forced_photometry_path(cache_dir, source_name=args.name, explicit_file=args.file)
    if data_path is None:
        raise SystemExit("Need --file or a source name with a matching portable cache entry.")
    photometry_df, loaded_path = read_forced_photometry_file(data_path)
    if photometry_df is None or photometry_df.empty:
        raise SystemExit(f"No usable forced photometry found at {data_path}.")

    plot_path = _lightcurve_plot(
        args.name or Path(loaded_path).stem,
        photometry_df,
        output_dir / f"{safe_slug(args.name or Path(loaded_path).stem)}_forced_lightcurve.png",
    )
    return {
        "action": "fetch",
        "name": args.name,
        "file": args.file,
        "cache_dir": str(cache_dir),
        "data_path": loaded_path,
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
    parser = argparse.ArgumentParser(description="Submit, monitor, or fetch ZTF forced photometry through the portable GitHub-only runtime.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit_parser = subparsers.add_parser("submit", help="Submit a new forced-photometry request.")
    submit_parser.add_argument("--name", required=True, help="Source name.")
    submit_parser.add_argument("--ra", type=float, help="RA in degrees.")
    submit_parser.add_argument("--dec", type=float, help="Dec in degrees.")
    submit_parser.add_argument("--jd-start", type=float, help="Start JD.")
    submit_parser.add_argument("--jd-end", type=float, help="End JD.")
    submit_parser.add_argument("--incremental", action="store_true", help="Submit an incremental request.")
    submit_parser.add_argument("--dry-run", action="store_true", help="Preview the request without sending it to the ZTF service.")
    submit_parser.add_argument("--cache-dir", help="Portable cache directory. Defaults to <repo>/data/ztf_forced_cache.")
    submit_parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    submit_parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    status_parser = subparsers.add_parser("status", help="Inspect cached or pending requests.")
    status_parser.add_argument("--name", help="Filter by source name.")
    status_parser.add_argument("--request-id", help="Filter by request id.")
    status_parser.add_argument("--refresh", action="store_true", help="Refresh pending states before reading cache.")
    status_parser.add_argument("--scan-emails", action="store_true", help="Reserved for the workspace IMAP path; unsupported in GitHub-only mode.")
    status_parser.add_argument("--days-back", type=int, default=3, help="Mailbox lookback window for explicit scans.")
    status_parser.add_argument("--max-emails", type=int, default=50, help="Mailbox scan cap for explicit scans.")
    status_parser.add_argument("--cache-dir", help="Portable cache directory. Defaults to <repo>/data/ztf_forced_cache.")
    status_parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    status_parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    fetch_parser = subparsers.add_parser("fetch", help="Load downloaded forced photometry and plot it.")
    fetch_parser.add_argument("--name", help="Source name.")
    fetch_parser.add_argument("--file", help="Explicit forced-photometry text file path.")
    fetch_parser.add_argument("--cache-dir", help="Portable cache directory. Defaults to <repo>/data/ztf_forced_cache.")
    fetch_parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    fetch_parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    args = parser.parse_args()
    _setup_logging(getattr(args, "verbose", False))
    target_name = getattr(args, "name", None) or getattr(args, "request_id", None) or "ztf-forced-photometry"
    output_dir = ensure_output_dir(REPO_ROOT, "snc-forced-photometry", target_name, getattr(args, "output_dir", None))
    cache_dir = portable_cache_dir(REPO_ROOT, getattr(args, "cache_dir", None))

    if args.command == "submit":
        result = _run_submit(args, output_dir, cache_dir)
    elif args.command == "status":
        result = _run_status(args, output_dir, cache_dir)
    else:
        result = _run_fetch(args, output_dir, cache_dir)

    json_path = write_json(output_dir / f"{safe_slug(target_name)}_forced_photometry.json", result)
    result["json_path"] = str(json_path)
    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
