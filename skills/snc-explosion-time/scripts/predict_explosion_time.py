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

from _snc_skill_support import (  # noqa: E402
    bootstrap_repo_root,
    ensure_output_dir,
    find_tns_entry,
    json_safe,
    resolve_target,
    safe_slug,
    write_json,
    write_text,
)

REPO_ROOT = bootstrap_repo_root(__file__)
from src.tns_project.core.sn_clock_predictor import get_sn_clock_predictor  # noqa: E402
from src.tns_project.core.texp_predictor import get_texp_prediction_html  # noqa: E402
from src.tns_project.core.ztf_forced_photometry import ZTFForcedPhotometryClient  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _fallback_interval_plot(prediction: Any, output_path: Path, title: str) -> Path:
    fig, ax = plt.subplots(figsize=(8, 2.4))
    ax.errorbar(
        [float(prediction.texp)],
        [0],
        xerr=[[float(prediction.texp) - float(prediction.ci_lower)], [float(prediction.ci_upper) - float(prediction.texp)]],
        fmt="o",
        color="#d62728",
        ecolor="#1f77b4",
        elinewidth=2,
        capsize=5,
    )
    ax.axvline(0.0, linestyle="--", color="#555555", linewidth=1.2)
    ax.set_yticks([])
    ax.set_xlabel("Days relative to discovery (negative means pre-discovery explosion)")
    ax.set_title(title)
    ax.grid(alpha=0.25, axis="x")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Predict explosion time with SN Clock.")
    parser.add_argument("--name", required=True, help="Transient name present in local SN Clock assets.")
    parser.add_argument("--ra", type=float, help="Optional RA override in degrees.")
    parser.add_argument("--dec", type=float, help="Optional Dec override in degrees.")
    parser.add_argument("--redshift", type=float, help="Override redshift.")
    parser.add_argument("--host-redshift", type=float, help="Override host redshift.")
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    resolved = resolve_target(REPO_ROOT, name=args.name, ra=args.ra, dec=args.dec)
    tns_key, tns_entry = find_tns_entry(REPO_ROOT, args.name)
    if not tns_entry:
        raise SystemExit(f"{args.name} is not available in sn_clock/data/tns/parsed/tns_full_info.json")

    target_name = tns_key or args.name
    output_dir = ensure_output_dir(REPO_ROOT, "snc-explosion-time", target_name, args.output_dir)

    redshift = args.redshift if args.redshift is not None else tns_entry.get("redshift")
    host_redshift = args.host_redshift if args.host_redshift is not None else tns_entry.get("host_redshift") or redshift

    source_data = {
        "tns_name": target_name,
        "discovery_mjd": tns_entry.get("discovery_mjd"),
        "redshift": redshift,
        "host_redshift": host_redshift,
        "ra": resolved["ra"],
        "dec": resolved["dec"],
    }

    forced_df, forced_path = ZTFForcedPhotometryClient().get_photometry_for_source({"tns_name": target_name})
    predictor = get_sn_clock_predictor()
    prediction = predictor.predict(
        source_data=source_data,
        ztf_data=forced_df,
        host_info={
            "host_redshift": host_redshift,
            "ra": resolved["ra"],
            "dec": resolved["dec"],
        },
    )
    if prediction is None:
        raise SystemExit(f"SN Clock prediction failed for {target_name}.")

    html = get_texp_prediction_html(
        tns_name=target_name,
        ztf_phot=forced_df,
        discovery_mjd=source_data["discovery_mjd"],
        redshift=redshift,
        host_info={
            "host_redshift": host_redshift,
            "ra": resolved["ra"],
            "dec": resolved["dec"],
        },
    )
    html_path = write_text(output_dir / f"{safe_slug(target_name)}_sn_clock.html", html or "")

    generated_png = REPO_ROOT / "plots" / "sn_clock" / f"{safe_slug(target_name)}_sn_clock.png"
    fallback_png = _fallback_interval_plot(
        prediction,
        output_dir / f"{safe_slug(target_name)}_texp_interval.png",
        title=f"SN Clock Prediction: {target_name}",
    )

    result = {
        "target": {
            "name": target_name,
            "resolved_from": resolved["resolved_from"],
            "ra": resolved["ra"],
            "dec": resolved["dec"],
        },
        "source_data": source_data,
        "prediction": {
            "texp": float(prediction.texp),
            "ci_lower": float(prediction.ci_lower),
            "ci_upper": float(prediction.ci_upper),
            "ci_width": float(prediction.ci_width),
            "confidence": prediction.confidence,
            "n_features_used": int(prediction.n_features_used),
            "feature_importance": json_safe(prediction.feature_importance),
            "warnings": prediction.warnings,
        },
        "forced_photometry": {
            "path": forced_path,
            "rows": int(len(forced_df)) if forced_df is not None else 0,
        },
        "artifacts": {
            "html": str(html_path),
            "sn_clock_png": str(generated_png) if generated_png.exists() else None,
            "interval_png": str(fallback_png),
        },
    }

    json_path = write_json(output_dir / f"{safe_slug(target_name)}_explosion_time.json", result)
    result["json_path"] = str(json_path)
    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
