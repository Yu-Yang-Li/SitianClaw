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

from sitianclaw_runtime.forced_phot import credentials_status, load_request_records, portable_cache_dir, status_counts, submit_forced_photometry  # noqa: E402
from sitianclaw_runtime.runtime import ensure_output_dir, json_safe, safe_slug, write_json  # noqa: E402
from sitianclaw_runtime.transients import resolve_target  # noqa: E402


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
    fig, ax = plt.subplots(figsize=(7.5, 4))
    ax.bar(labels, values, color=["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"][: len(labels)])
    for idx, value in enumerate(values):
        ax.text(idx, value + 0.05, str(value), ha="center", va="bottom")
    ax.set_title(title)
    ax.set_ylabel("Request count")
    ax.grid(alpha=0.2, axis="y")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit a ZTF forced-photometry request through the portable GitHub-only runtime.")
    parser.add_argument("--name", required=True, help="Source name.")
    parser.add_argument("--ra", type=float, help="RA in degrees.")
    parser.add_argument("--dec", type=float, help="Dec in degrees.")
    parser.add_argument("--jd-start", type=float, help="Start JD.")
    parser.add_argument("--jd-end", type=float, help="End JD.")
    parser.add_argument("--incremental", action="store_true", help="Submit an incremental request.")
    parser.add_argument("--dry-run", action="store_true", help="Preview the request without sending it to the ZTF service.")
    parser.add_argument("--cache-dir", help="Portable cache directory. Defaults to <repo>/data/ztf_forced_cache.")
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    output_dir = ensure_output_dir(REPO_ROOT, "snc-forced-phot-submit", args.name, args.output_dir)
    cache_dir = portable_cache_dir(REPO_ROOT, args.cache_dir)

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
        output_dir / f"{safe_slug(resolved['name'])}_submit_status.png",
        title=f"ZTF Forced Photometry Submit: {resolved['name']}",
    )

    payload = {
        "skill": "snc-forced-phot-submit",
        "workspace_alignment": "Matches the submit stage of the SNC ZTF forced-photometry workflow with a portable cache and environment-based credentials.",
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
        "jd_start": args.jd_start,
        "jd_end": args.jd_end,
        "request_id": request_id,
        "submission": json_safe(submission),
        "requests": json_safe(request_rows),
        "artifact": str(plot_path) if plot_path is not None else None,
    }
    json_path = write_json(output_dir / f"{safe_slug(resolved['name'])}_forced_phot_submit.json", payload)
    payload["json_path"] = str(json_path)
    print(json.dumps(json_safe(payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
