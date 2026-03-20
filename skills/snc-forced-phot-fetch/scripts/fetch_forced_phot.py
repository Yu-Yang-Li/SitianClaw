from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from sitianclaw_runtime.forced_phot import portable_cache_dir, read_forced_photometry_file, resolve_forced_photometry_path  # noqa: E402
from sitianclaw_runtime.runtime import dataframe_records, ensure_output_dir, json_safe, safe_slug, write_json  # noqa: E402
from sitianclaw_runtime.transients import plot_lightcurve  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _lightcurve_plot(source_name: str, photometry_df, output_path: Path) -> Path | None:
    if photometry_df is None or photometry_df.empty:
        return None
    generated = plot_lightcurve(
        target_name=source_name,
        frames=[photometry_df],
        output_path=output_path,
        title_prefix="Forced Photometry",
    )
    return Path(generated) if generated else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Load downloaded ZTF forced photometry from a portable cache or explicit file.")
    parser.add_argument("--name", help="Source name.")
    parser.add_argument("--file", help="Explicit forced-photometry text file path.")
    parser.add_argument("--cache-dir", help="Portable cache directory. Defaults to <repo>/data/ztf_forced_cache.")
    parser.add_argument("--output-dir", help="Directory for JSON and plots.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    _setup_logging(args.verbose)
    target_name = args.name or (Path(args.file).stem if args.file else "forced-phot")
    output_dir = ensure_output_dir(REPO_ROOT, "snc-forced-phot-fetch", target_name, args.output_dir)
    cache_dir = portable_cache_dir(REPO_ROOT, args.cache_dir)
    data_path = resolve_forced_photometry_path(cache_dir, source_name=args.name, explicit_file=args.file)
    if data_path is None:
        raise SystemExit("Need --file or a source name with a matching portable cache entry.")
    photometry_df, loaded_path = read_forced_photometry_file(data_path)
    if photometry_df is None or photometry_df.empty:
        raise SystemExit(f"No usable forced photometry found at {data_path}.")

    plot_path = _lightcurve_plot(
        target_name,
        photometry_df,
        output_dir / f"{safe_slug(target_name)}_forced_lightcurve.png",
    )

    payload = {
        "skill": "snc-forced-phot-fetch",
        "workspace_alignment": "Matches the fetch stage of the SNC ZTF forced-photometry workflow with a portable cache or explicit file.",
        "action": "fetch",
        "name": args.name,
        "file": args.file,
        "cache_dir": str(cache_dir),
        "data_path": loaded_path,
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
    json_path = write_json(output_dir / f"{safe_slug(target_name)}_forced_phot_fetch.json", payload)
    payload["json_path"] = str(json_path)
    print(json.dumps(json_safe(payload), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
