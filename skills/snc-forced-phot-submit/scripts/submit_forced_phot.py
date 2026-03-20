from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from _snc_skill_support import (
    bootstrap_repo_root,
    ensure_output_dir,
    json_safe,
    load_request_cache,
    resolve_target,
    safe_slug,
    write_json,
)

REPO_ROOT = bootstrap_repo_root(__file__)
from src.tns_project.core.ztf_forced_photometry import ZTFForcedPhotometryClient  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _find_requests_by_id(request_id: str | None) -> list[dict[str, Any]]:
    if not request_id:
        return []
    return [row for row in load_request_cache(REPO_ROOT) if row.get("request_id") == request_id]


def _status_plot(rows: list[dict[str, Any]], output_path: Path, title: str) -> Path | None:
    if not rows:
        return None
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown").lower()
        counts[status] = counts.get(status, 0) + 1

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
    parser = argparse.ArgumentParser(description="Submit a ZTF forced-photometry request using the SNC workspace client.")
    parser.add_argument("--name", required=True, help="Source name.")
    parser.add_argument("--ra", type=float, help="RA in degrees.")
    parser.add_argument("--dec", type=float, help="Dec in degrees.")
    parser.add_argument("--jd-start", type=float, help="Start JD.")
    parser.add_argument("--jd-end", type=float, help="End JD.")
    parser.add_argument("--incremental", action="store_true", help="Submit an incremental request.")
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    output_dir = ensure_output_dir(REPO_ROOT, "snc-forced-phot-submit", args.name, args.output_dir)
    os.chdir(REPO_ROOT)

    resolved = resolve_target(REPO_ROOT, name=args.name, ra=args.ra, dec=args.dec)
    if resolved["ra"] is None or resolved["dec"] is None:
        raise SystemExit("Submission needs RA/Dec directly or via a cached workspace target name.")

    client = ZTFForcedPhotometryClient(cache_dir=str(REPO_ROOT / "data" / "ztf_forced_cache"))
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

    request_rows = _find_requests_by_id(request_id)
    plot_path = _status_plot(
        request_rows if request_rows else load_request_cache(REPO_ROOT),
        output_dir / f"{safe_slug(resolved['name'])}_submit_status.png",
        title=f"ZTF Forced Photometry Submit: {resolved['name']}",
    )

    payload = {
        "skill": "snc-forced-phot-submit",
        "workspace_alignment": "Matches the submit stage of the SNC ZTF forced-photometry workflow.",
        "action": "submit",
        "target": {
            "name": resolved["name"],
            "ra": resolved["ra"],
            "dec": resolved["dec"],
            "resolved_from": resolved["resolved_from"],
        },
        "incremental": bool(args.incremental),
        "jd_start": args.jd_start,
        "jd_end": args.jd_end,
        "request_id": request_id,
        "requests": json_safe(request_rows),
        "artifact": str(plot_path) if plot_path is not None else None,
    }
    json_path = write_json(output_dir / f"{safe_slug(resolved['name'])}_forced_phot_submit.json", payload)
    payload["json_path"] = str(json_path)
    print(json.dumps(json_safe(payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
