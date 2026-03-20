from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from astropy import units as u  # noqa: E402
from astropy.coordinates import SkyCoord  # noqa: E402

from _snc_skill_support import (  # noqa: E402
    bootstrap_repo_root,
    ensure_output_dir,
    json_safe,
    resolve_target,
    safe_slug,
    write_json,
)

REPO_ROOT = bootstrap_repo_root(__file__)
from src.tns_project.core.alerce_scraper import get_host_redshift  # noqa: E402
from src.tns_project.core.redshift_consensus import merge_redshifts  # noqa: E402
from src.tns_project.utils.ned_query import query_ned_for_z_and_host  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _plot_redshift_summary(
    measurements: list[dict[str, Any]],
    consensus: dict[str, Any],
    output_path: Path,
    title: str,
) -> Path | None:
    if not measurements:
        return None

    fig, ax = plt.subplots(figsize=(8, 3.8))
    y_positions = list(range(len(measurements)))
    values = [float(item["z"]) for item in measurements]
    labels = [item["label"] for item in measurements]
    colors = ["#1f77b4" if item["source"] != consensus.get("z_source") else "#d62728" for item in measurements]
    ax.scatter(values, y_positions, s=140, c=colors, edgecolor="black", linewidth=0.4)
    for idx, value in enumerate(values):
        ax.text(value, idx + 0.12, f"{value:.5f}", fontsize=9)
    if consensus.get("z_final") is not None:
        ax.axvline(float(consensus["z_final"]), color="#444444", linestyle="--", linewidth=1.5)
    ax.set_yticks(y_positions, labels)
    ax.set_xlabel("Redshift")
    ax.set_title(title)
    ax.grid(alpha=0.25, axis="x")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def _compute_offset_arcsec(
    source_ra: float | None,
    source_dec: float | None,
    host_ra: float | None,
    host_dec: float | None,
) -> float | None:
    if None in (source_ra, source_dec, host_ra, host_dec):
        return None
    try:
        source_coord = SkyCoord(ra=float(source_ra) * u.deg, dec=float(source_dec) * u.deg)
        host_coord = SkyCoord(ra=float(host_ra) * u.deg, dec=float(host_dec) * u.deg)
        return float(source_coord.separation(host_coord).arcsec)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve host redshift and redshift consensus.")
    parser.add_argument("--name", help="Transient name, for example 'SN 2026fvx'.")
    parser.add_argument("--ra", type=float, help="RA in degrees.")
    parser.add_argument("--dec", type=float, help="Dec in degrees.")
    parser.add_argument("--tns-z", type=float, help="Override TNS redshift.")
    parser.add_argument("--broker-z", type=float, help="Broker-provided redshift override.")
    parser.add_argument("--broker-source", default="broker", help="Label for --broker-z.")
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    resolved = resolve_target(REPO_ROOT, name=args.name, ra=args.ra, dec=args.dec)
    target_name = resolved["name"]
    if resolved["ra"] is None or resolved["dec"] is None:
        raise SystemExit("Need RA/Dec directly or via a resolvable local target name.")

    output_dir = ensure_output_dir(REPO_ROOT, "snc-redshift-query", target_name, args.output_dir)
    tns_entry = resolved["tns_entry"] or {}

    tns_z = args.tns_z
    if tns_z is None:
        tns_z = tns_entry.get("redshift") or tns_entry.get("host_redshift")
    tns_z = float(tns_z) if tns_z not in (None, "") else None

    host_z, host_name, host_ra, host_dec, host_type, host_source = get_host_redshift(
        float(resolved["ra"]),
        float(resolved["dec"]),
        target_name,
    )
    ned_z, ned_host_name, ned_host_ra, ned_host_dec, ned_host_type = query_ned_for_z_and_host(
        float(resolved["ra"]),
        float(resolved["dec"]),
        target_name,
    )

    broker_z = args.broker_z
    broker_source = args.broker_source
    if broker_z is None and host_source == "ALeRCE" and host_z is not None:
        broker_z = float(host_z)

    consensus = merge_redshifts(
        ned_z=ned_z,
        broker_z=broker_z,
        broker_source=broker_source,
        tns_z=tns_z,
    )

    measurements: list[dict[str, Any]] = []
    if tns_z is not None and math.isfinite(tns_z):
        measurements.append({"source": "tns", "label": "TNS", "z": float(tns_z)})
    if ned_z is not None and math.isfinite(ned_z):
        measurements.append({"source": "ned", "label": "NED", "z": float(ned_z)})
    if broker_z is not None and math.isfinite(broker_z):
        measurements.append({"source": broker_source, "label": broker_source.upper(), "z": float(broker_z)})

    plot_path = _plot_redshift_summary(
        measurements,
        consensus,
        output_dir / f"{safe_slug(target_name)}_redshift_summary.png",
        title=f"Redshift Consensus: {target_name}",
    )

    final_host_ra = host_ra if host_ra is not None else ned_host_ra
    final_host_dec = host_dec if host_dec is not None else ned_host_dec
    final_host_name = host_name or ned_host_name
    final_host_type = host_type if host_type not in (None, "N/A") else ned_host_type
    offset_arcsec = _compute_offset_arcsec(
        resolved["ra"],
        resolved["dec"],
        final_host_ra,
        final_host_dec,
    )

    result = {
        "target": {
            "name": target_name,
            "ra": resolved["ra"],
            "dec": resolved["dec"],
            "resolved_from": resolved["resolved_from"],
        },
        "measurements": measurements,
        "consensus": json_safe(consensus),
        "host_query": {
            "z": host_z,
            "name": host_name,
            "ra": host_ra,
            "dec": host_dec,
            "type": host_type,
            "source": host_source,
        },
        "ned_query": {
            "z": ned_z,
            "name": ned_host_name,
            "ra": ned_host_ra,
            "dec": ned_host_dec,
            "type": ned_host_type,
        },
        "final_host": {
            "name": final_host_name,
            "ra": final_host_ra,
            "dec": final_host_dec,
            "type": final_host_type,
            "offset_arcsec": offset_arcsec,
        },
        "artifact": str(plot_path) if plot_path is not None else None,
    }

    json_path = write_json(output_dir / f"{safe_slug(target_name)}_redshift_query.json", result)
    result["json_path"] = str(json_path)
    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
