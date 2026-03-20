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
    find_requests_by_name,
    json_safe,
    load_request_cache,
    safe_slug,
    write_json,
)

REPO_ROOT = bootstrap_repo_root(__file__)
from src.tns_project.core.ztf_email_monitor import ZTFEmailMonitor  # noqa: E402
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
    parser = argparse.ArgumentParser(description="Refresh and inspect ZTF forced-photometry request status.")
    parser.add_argument("--name", help="Filter by source name.")
    parser.add_argument("--request-id", help="Filter by request id.")
    parser.add_argument("--refresh", action="store_true", help="Call check_pending_requests() before reading cache.")
    parser.add_argument("--scan-emails", action="store_true", help="Run an explicit mailbox scan before reading cache.")
    parser.add_argument("--days-back", type=int, default=3, help="Mailbox lookback window for explicit scans.")
    parser.add_argument("--max-emails", type=int, default=50, help="Mailbox scan cap for explicit scans.")
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    target_name = args.name or args.request_id or "ztf_forced_monitor"
    output_dir = ensure_output_dir(REPO_ROOT, "snc-forced-phot-monitor", target_name, args.output_dir)
    os.chdir(REPO_ROOT)

    email_scan_result = None
    if args.scan_emails:
        email_monitor = ZTFEmailMonitor(cache_dir=str(REPO_ROOT / "data" / "ztf_forced_cache"))
        email_scan_result = email_monitor.scan_emails_and_download_optimized(
            days_back=args.days_back,
            max_emails=args.max_emails,
        )

    status_updates = None
    if args.refresh:
        client = ZTFForcedPhotometryClient(cache_dir=str(REPO_ROOT / "data" / "ztf_forced_cache"))
        status_updates = client.check_pending_requests()

    rows = _find_requests_by_id(args.request_id)
    if not rows and args.name:
        rows = find_requests_by_name(REPO_ROOT, args.name)
    if not rows:
        rows = load_request_cache(REPO_ROOT)

    plot_path = _status_plot(
        rows,
        output_dir / f"{safe_slug(target_name)}_monitor_status.png",
        title=f"ZTF Forced Photometry Monitor: {target_name}",
    )

    payload = {
        "skill": "snc-forced-phot-monitor",
        "workspace_alignment": "Matches the monitoring stage of the SNC ZTF forced-photometry workflow.",
        "action": "monitor",
        "name": args.name,
        "request_id": args.request_id,
        "refresh": bool(args.refresh),
        "scan_emails": bool(args.scan_emails),
        "email_scan_result": json_safe(email_scan_result),
        "status_updates": json_safe(status_updates),
        "requests": json_safe(rows),
        "artifact": str(plot_path) if plot_path is not None else None,
    }
    json_path = write_json(output_dir / f"{safe_slug(target_name)}_forced_phot_monitor.json", payload)
    payload["json_path"] = str(json_path)
    print(json.dumps(json_safe(payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
