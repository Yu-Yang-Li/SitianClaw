from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from sitianclaw_runtime.runtime import dataframe_records, ensure_output_dir, json_safe, safe_slug, write_json  # noqa: E402
from sitianclaw_runtime.transients import (  # noqa: E402
    broker_summary,
    fallback_target_row,
    fetch_tns_photometry_by_name,
    filter_tns_dataframe,
    plot_lightcurve,
    plot_tns_sky,
    query_alerce_by_coordinates,
    resolve_target,
)
from sitianclaw_runtime.tns import fetch_tns_data_from_web  # noqa: E402

LOGGER = logging.getLogger("snc_transient_query")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Query recent TNS candidates and public broker photometry.")
    parser.add_argument("--name", help="Transient name, for example 'SN 2026fvx'.")
    parser.add_argument("--ra", type=float, help="RA in degrees.")
    parser.add_argument("--dec", type=float, help="Dec in degrees.")
    parser.add_argument("--days-back", type=int, default=3, help="Recent TNS window in days.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of TNS rows.")
    parser.add_argument(
        "--skip-brokers",
        action="store_true",
        help="Do not query public broker photometry.",
    )
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    resolved = resolve_target(name=args.name, ra=args.ra, dec=args.dec)
    target_name = resolved["name"]
    output_dir = ensure_output_dir(REPO_ROOT, "snc-transient-query", target_name, args.output_dir)

    tns_df = fetch_tns_data_from_web(days_back=max(args.days_back, 1))
    filtered_tns = filter_tns_dataframe(tns_df, args.name, args.limit, days_back=max(args.days_back, 1))
    if filtered_tns.empty and resolved["tns_entry"]:
        filtered_tns = pd.DataFrame([resolved["tns_entry"]])

    alerce_df = pd.DataFrame()
    if not args.skip_brokers and resolved["ra"] is not None and resolved["dec"] is not None:
        try:
            alerce_df = query_alerce_by_coordinates(
                ra_deg=float(resolved["ra"]),
                dec_deg=float(resolved["dec"]),
                days_back=max(args.days_back, 30),
            )
        except Exception as exc:
            LOGGER.debug("ALeRCE broker query failed: %s", exc)

    tns_phot_df = pd.DataFrame()
    if args.name:
        try:
            tns_phot_df = fetch_tns_photometry_by_name(args.name)
        except Exception as exc:
            LOGGER.debug("TNS photometry fetch failed: %s", exc)

    artifacts: dict[str, Any] = {}
    sky_source = filtered_tns
    if sky_source.empty or sky_source[["ra_deg", "dec_deg"]].isna().all().all():
        sky_source = fallback_target_row(
            target_name=target_name,
            ra=resolved["ra"],
            dec=resolved["dec"],
            redshift=(resolved["tns_entry"] or {}).get("redshift"),
        )

    sky_plot = plot_tns_sky(
        sky_source,
        output_dir / f"{safe_slug(target_name)}_tns_sky.png",
        title=f"TNS Query Results: {target_name}",
    )
    if sky_plot is not None:
        artifacts["tns_sky_plot"] = str(sky_plot)

    broker_lightcurve_plot = plot_lightcurve(
        target_name=target_name,
        frames=[frame for frame in [alerce_df, tns_phot_df] if frame is not None and not frame.empty],
        output_path=output_dir / f"{safe_slug(target_name)}_lightcurve.png",
        title_prefix="Transient Light Curve",
    )
    if broker_lightcurve_plot is not None:
        artifacts["lightcurve_plot"] = str(broker_lightcurve_plot)

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
        "photometry": {
            "tns": broker_summary(tns_phot_df),
            "alerce": broker_summary(alerce_df),
        },
        "artifacts": artifacts,
    }
    json_path = write_json(output_dir / f"{safe_slug(target_name)}_transient_query.json", result)
    result["json_path"] = str(json_path)
    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
