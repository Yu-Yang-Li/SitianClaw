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

from sitianclaw_runtime.host_context import (  # noqa: E402
    crossmatch_all,
    should_exclude_as_definite_star,
)
from sitianclaw_runtime.runtime import ensure_output_dir, json_safe, safe_slug, write_json  # noqa: E402
from sitianclaw_runtime.transients import resolve_target  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _summary_plot(results: dict[str, Any], output_path: Path, title: str) -> Path:
    summary = results.get("summary") or {}
    score = float(summary.get("contamination_score") or 0)
    matched_sources = summary.get("matched_sources") or []
    warnings = summary.get("warnings") or []

    fig, (ax_bar, ax_text) = plt.subplots(
        ncols=2,
        figsize=(11, 4.5),
        gridspec_kw={"width_ratios": [1.2, 1.8]},
    )
    color = "#d62728" if score >= 3 else "#ff7f0e" if score >= 2 else "#2ca02c"
    ax_bar.barh(["Contamination"], [score], color=color)
    ax_bar.set_xlim(0, 6)
    ax_bar.set_xlabel("Score")
    ax_bar.set_title("Contamination Score")
    ax_bar.grid(alpha=0.2, axis="x")

    ax_text.axis("off")
    lines = [f"Matched catalogs: {', '.join(matched_sources) if matched_sources else 'None'}"]
    lines.extend(warnings[:6] if warnings else ["No contamination warnings from available catalogs."])
    ax_text.text(
        0.0,
        1.0,
        "\n".join(lines),
        va="top",
        ha="left",
        fontsize=10,
        wrap=True,
    )
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Crossmatch host environment and contamination context from portable public catalogs.")
    parser.add_argument("--name", help="Source name, for example 'SN 2026fvx'.")
    parser.add_argument("--ra", type=float, help="RA in degrees.")
    parser.add_argument("--dec", type=float, help="Dec in degrees.")
    parser.add_argument("--timeout", type=float, default=40.0, help="Crossmatch timeout in seconds.")
    parser.add_argument(
        "--skip-photometry",
        action="store_true",
        help="Skip Pan-STARRS/2MASS photometric queries.",
    )
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    resolved = resolve_target(name=args.name, ra=args.ra, dec=args.dec)
    if resolved["ra"] is None or resolved["dec"] is None:
        raise SystemExit("Need RA/Dec directly or via public TNS name resolution.")

    target_name = resolved["name"]
    output_dir = ensure_output_dir(REPO_ROOT, "snc-host-context", target_name, args.output_dir)

    results = crossmatch_all(
        ra_deg=float(resolved["ra"]),
        dec_deg=float(resolved["dec"]),
        tns_name=target_name,
        timeout=float(args.timeout),
        include_photometry=not args.skip_photometry,
    )
    exclude_star, exclude_reason = should_exclude_as_definite_star(results)
    plot_path = _summary_plot(
        results,
        output_dir / f"{safe_slug(target_name)}_host_context.png",
        title=f"Host Context: {target_name}",
    )

    result = {
        "target": {
            "name": target_name,
            "ra": resolved["ra"],
            "dec": resolved["dec"],
            "resolved_from": resolved["resolved_from"],
        },
        "crossmatch": json_safe(results),
        "recommendation": {
            "exclude_as_definite_star": exclude_star,
            "reason": exclude_reason,
        },
        "artifact": str(plot_path),
    }

    json_path = write_json(output_dir / f"{safe_slug(target_name)}_host_context.json", result)
    result["json_path"] = str(json_path)
    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
