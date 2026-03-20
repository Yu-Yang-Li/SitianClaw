from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from _snc_skill_support import (
    bootstrap_repo_root,
    dataframe_records,
    ensure_output_dir,
    json_safe,
    safe_slug,
    write_json,
)

REPO_ROOT = bootstrap_repo_root(__file__)
from src.tns_project.core.ztf_forced_photometry import ZTFForcedPhotometryClient  # noqa: E402
from src.tns_project.utils.plotting import AstronomicalPlotter  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _lightcurve_plot(source_name: str, photometry_df, output_path: Path) -> Path | None:
    if photometry_df is None or photometry_df.empty:
        return None
    plotter = AstronomicalPlotter(output_dir=str(output_path.parent))
    generated = plotter.plot_lightcurve(
        tns_name=source_name,
        ztf_data=photometry_df,
        save_path=str(output_path),
        time_window_days=180,
        use_days_ago=False,
    )
    return Path(generated) if generated else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Load downloaded ZTF forced photometry from the SNC workspace cache.")
    parser.add_argument("--name", required=True, help="Source name.")
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    output_dir = ensure_output_dir(REPO_ROOT, "snc-forced-phot-fetch", args.name, args.output_dir)
    os.chdir(REPO_ROOT)

    client = ZTFForcedPhotometryClient(cache_dir=str(REPO_ROOT / "data" / "ztf_forced_cache"))
    photometry_df, data_path = client.get_photometry_for_source({"tns_name": args.name})
    if photometry_df is None or photometry_df.empty:
        raise SystemExit(f"No downloaded forced photometry found for {args.name}.")

    plot_path = _lightcurve_plot(
        args.name,
        photometry_df,
        output_dir / f"{safe_slug(args.name)}_forced_lightcurve.png",
    )

    payload = {
        "skill": "snc-forced-phot-fetch",
        "workspace_alignment": "Matches the fetch stage of the SNC ZTF forced-photometry workflow.",
        "action": "fetch",
        "name": args.name,
        "data_path": data_path,
        "photometry_summary": {
            "rows": int(len(photometry_df)),
            "mjd_min": float(photometry_df["mjd"].min()),
            "mjd_max": float(photometry_df["mjd"].max()),
            "detections": int(photometry_df["is_detection"].sum()) if "is_detection" in photometry_df.columns else None,
            "filters": sorted({str(item) for item in photometry_df["filter"].dropna().tolist()}) if "filter" in photometry_df.columns else [],
            "preview": dataframe_records(
                photometry_df,
                columns=["mjd", "filter", "mag", "magerr", "snr", "is_detection"],
                limit=25,
            ),
        },
        "artifact": str(plot_path) if plot_path is not None else None,
    }
    json_path = write_json(output_dir / f"{safe_slug(args.name)}_forced_phot_fetch.json", payload)
    payload["json_path"] = str(json_path)
    print(json.dumps(json_safe(payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
