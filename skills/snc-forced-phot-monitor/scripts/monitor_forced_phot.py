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
    find_requests_by_id,
    find_requests_by_name,
    load_request_records,
    portable_cache_dir,
    refresh_request_statuses,
    status_counts,
)
from sitianclaw_runtime.runtime import ensure_output_dir, json_safe, safe_slug, write_json  # noqa: E402


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
    parser = argparse.ArgumentParser(description="Refresh and inspect portable ZTF forced-photometry request caches.")
    parser.add_argument("--name", help="Filter by source name.")
    parser.add_argument("--request-id", help="Filter by request id.")
    parser.add_argument("--refresh", action="store_true", help="Query the remote ZTF status page when credentials are set.")
    parser.add_argument("--scan-emails", action="store_true", help="Reserved for the workspace IMAP path; unsupported in GitHub-only mode.")
    parser.add_argument("--days-back", type=int, default=3, help="Mailbox lookback window for explicit scans.")
    parser.add_argument("--max-emails", type=int, default=50, help="Mailbox scan cap for explicit scans.")
    parser.add_argument("--cache-dir", help="Portable cache directory. Defaults to <repo>/data/ztf_forced_cache.")
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    target_name = args.name or args.request_id or "ztf_forced_monitor"
    output_dir = ensure_output_dir(REPO_ROOT, "snc-forced-phot-monitor", target_name, args.output_dir)
    cache_dir = portable_cache_dir(REPO_ROOT, args.cache_dir)
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

    plot_path = _status_plot(
        rows,
        output_dir / f"{safe_slug(target_name)}_monitor_status.png",
        title=f"ZTF Forced Photometry Monitor: {target_name}",
    )

    payload = {
        "skill": "snc-forced-phot-monitor",
        "workspace_alignment": "Matches the monitoring stage of the SNC ZTF forced-photometry workflow with a portable cache and optional remote status refresh.",
        "action": "monitor",
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
    json_path = write_json(output_dir / f"{safe_slug(target_name)}_forced_phot_monitor.json", payload)
    payload["json_path"] = str(json_path)
    print(json.dumps(json_safe(payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
