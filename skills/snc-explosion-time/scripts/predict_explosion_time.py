from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from sitianclaw_runtime.explosion_time import (  # noqa: E402
    get_public_prediction,
    make_prediction_payload,
    photometry_summary,
    plot_explosion_summary,
    plot_interval_only,
    render_prediction_html,
)
from sitianclaw_runtime.runtime import ensure_output_dir, json_safe, safe_slug, write_json, write_text  # noqa: E402
from sitianclaw_runtime.transients import resolve_target  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Predict explosion time with the portable GitHub-only SN Clock runtime.")
    parser.add_argument("--name", required=True, help="Transient name resolvable from public TNS.")
    parser.add_argument("--ra", type=float, help="Optional RA override in degrees.")
    parser.add_argument("--dec", type=float, help="Optional Dec override in degrees.")
    parser.add_argument("--redshift", type=float, help="Override redshift.")
    parser.add_argument("--host-redshift", type=float, help="Override host redshift.")
    parser.add_argument("--forced-phot-file", help="Optional local forced-photometry text file to improve the prediction.")
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    resolved = resolve_target(name=args.name, ra=args.ra, dec=args.dec)
    target_name = resolved["name"]
    output_dir = ensure_output_dir(REPO_ROOT, "snc-explosion-time", target_name, args.output_dir)
    tns_entry = resolved["tns_entry"] or {}

    prediction_result = get_public_prediction(
        target_name=target_name,
        ra=resolved["ra"],
        dec=resolved["dec"],
        tns_entry=tns_entry,
        redshift_override=args.redshift,
        host_redshift_override=args.host_redshift,
        forced_phot_file=args.forced_phot_file,
    )
    prediction = prediction_result["prediction"]
    discovery_mjd = prediction_result["feature_metadata"].get("discovery_mjd")

    summary_png = plot_explosion_summary(
        target_name=target_name,
        prediction=prediction,
        discovery_mjd=discovery_mjd,
        tns_photometry=prediction_result["tns_photometry"],
        forced_photometry=prediction_result["forced_photometry"],
        output_path=output_dir / f"{safe_slug(target_name)}_sn_clock_summary.png",
    )
    interval_png = plot_interval_only(
        prediction=prediction,
        output_path=output_dir / f"{safe_slug(target_name)}_texp_interval.png",
        title=f"SN Clock Prediction: {target_name}",
    )

    summary = photometry_summary(prediction_result["tns_photometry"], prediction_result["forced_photometry"])
    workflow_mode = "public_tns_plus_forced_phot" if prediction_result["forced_photometry"] is not None and not prediction_result["forced_photometry"].empty else "public_tns_only"
    html = render_prediction_html(
        target_name=target_name,
        prediction=prediction,
        discovery_mjd=discovery_mjd,
        summary_png_path=summary_png,
        photometry_summary=summary,
        workflow_mode=workflow_mode,
    )
    html_path = write_text(output_dir / f"{safe_slug(target_name)}_sn_clock.html", html)

    payload = make_prediction_payload(
        target_name=target_name,
        ra=resolved["ra"],
        dec=resolved["dec"],
        resolved_from=resolved["resolved_from"],
        prediction_result=prediction_result,
        artifacts={
            "html": str(html_path),
            "sn_clock_png": str(summary_png),
            "interval_png": str(interval_png),
        },
    )
    json_path = write_json(output_dir / f"{safe_slug(target_name)}_explosion_time.json", payload)
    payload["json_path"] = str(json_path)
    print(json.dumps(json_safe(payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
