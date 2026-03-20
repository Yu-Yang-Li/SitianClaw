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
from astropy import units as u
from astropy.coordinates import SkyCoord

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from sitianclaw_runtime.redshift import get_host_redshift, merge_redshifts, query_ned_for_z_and_host  # noqa: E402
from sitianclaw_runtime.runtime import (  # noqa: E402
    ensure_output_dir,
    json_safe,
    normalize_name,
    safe_slug,
    write_json,
)
from sitianclaw_runtime.tns import fetch_tns_data_by_name  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _resolve_target(name: str | None, ra: float | None, dec: float | None) -> dict[str, Any]:
    if ra is not None and dec is not None:
        return {"name": name or "custom-target", "ra": ra, "dec": dec, "tns_entry": None, "resolved_from": ["direct_input"]}
    if not name:
        raise SystemExit("Need a target name or direct RA/Dec.")
    table = fetch_tns_data_by_name(name)
    if table.empty:
        raise SystemExit(f"Unable to resolve {name} from public TNS data.")
    normalized = normalize_name(name)
    for _, row in table.iterrows():
        if normalize_name(row.get("tns_name")) == normalized:
            return {
                "name": row.get("tns_name") or name,
                "ra": float(row.get("ra_deg")),
                "dec": float(row.get("dec_deg")),
                "tns_entry": row.to_dict(),
                "resolved_from": ["public_tns"],
            }
    row = table.iloc[0]
    return {
        "name": row.get("tns_name") or name,
        "ra": float(row.get("ra_deg")),
        "dec": float(row.get("dec_deg")),
        "tns_entry": row.to_dict(),
        "resolved_from": ["public_tns_fallback"],
    }


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
    parser = argparse.ArgumentParser(description="Resolve host redshift and redshift consensus from GitHub-only portable sources.")
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
    resolved = _resolve_target(args.name, args.ra, args.dec)
    target_name = resolved["name"]
    output_dir = ensure_output_dir(REPO_ROOT, "snc-redshift-query", target_name, args.output_dir)
    tns_entry = resolved["tns_entry"] or {}

    tns_z = args.tns_z
    if tns_z is None:
        raw_tns_z = tns_entry.get("redshift")
        try:
            tns_z = float(raw_tns_z) if raw_tns_z not in (None, "", "N/A") else None
        except Exception:
            tns_z = None

    host_z, host_name, host_ra, host_dec, host_type, host_source = get_host_redshift(
        float(resolved["ra"]), float(resolved["dec"]), target_name
    )
    ned_z, ned_host_name, ned_host_ra, ned_host_dec, ned_host_type = query_ned_for_z_and_host(
        float(resolved["ra"]), float(resolved["dec"]), target_name
    )

    broker_z = args.broker_z
    broker_source = args.broker_source
    consensus = merge_redshifts(ned_z=ned_z, broker_z=broker_z, broker_source=broker_source, tns_z=tns_z)

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
    offset_arcsec = _compute_offset_arcsec(resolved["ra"], resolved["dec"], final_host_ra, final_host_dec)

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
