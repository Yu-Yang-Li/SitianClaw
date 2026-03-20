from __future__ import annotations

import base64
import importlib.util
import io
import json
import logging
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

from .forced_phot import read_forced_photometry_file
from .redshift import get_host_redshift
from .runtime import json_safe
from .transients import fetch_tns_photometry_by_name

logger = logging.getLogger(__name__)

ASSET_DIR = Path(__file__).resolve().parent / "sn_clock_assets"
MODELS_DIR = ASSET_DIR / "models"

DEFAULT_LIMITING_MAG = {
    "g-ZTF": 20.8,
    "r-ZTF": 20.5,
    "i-ZTF": 20.0,
    "cyan-ATLAS": 19.7,
    "orange-ATLAS": 19.5,
    "Clear-": 18.0,
    "Unknown": 19.0,
}


@dataclass
class TexpPrediction:
    texp: float
    ci_lower: float
    ci_upper: float
    ci_width: float
    confidence: str
    n_features_used: int
    feature_importance: dict[str, float]
    warnings: list[str]


def _normalize_training_filter(value: Any) -> str:
    text = str(value or "").strip()
    lower = text.lower()
    mapping = {
        "ztf-g": "g-ZTF",
        "ztf-r": "r-ZTF",
        "ztf-i": "i-ZTF",
        "g-ztf": "g-ZTF",
        "r-ztf": "r-ZTF",
        "i-ztf": "i-ZTF",
        "g": "g-ZTF",
        "r": "r-ZTF",
        "i": "i-ZTF",
        "clear": "Clear-",
        "clear-": "Clear-",
        "c-atlas": "cyan-ATLAS",
        "cyan-atlas": "cyan-ATLAS",
        "o-atlas": "orange-ATLAS",
        "orange-atlas": "orange-ATLAS",
    }
    if lower in mapping:
        return mapping[lower]
    if "ztf" in lower and "g" in lower:
        return "g-ZTF"
    if "ztf" in lower and "r" in lower:
        return "r-ZTF"
    if "ztf" in lower and "i" in lower:
        return "i-ZTF"
    if "atlas" in lower and ("c" in lower or "cyan" in lower):
        return "cyan-ATLAS"
    if "atlas" in lower and ("o" in lower or "orange" in lower or "t" in lower):
        return "orange-ATLAS"
    return text or "Unknown"


def _default_limiting_mag(filter_name: str) -> float:
    return float(DEFAULT_LIMITING_MAG.get(filter_name, DEFAULT_LIMITING_MAG["Unknown"]))


def _parse_discovery_mjd(tns_entry: dict[str, Any]) -> float | None:
    raw_discovery = tns_entry.get("discoverydate")
    if raw_discovery in (None, "", "N/A"):
        return None
    try:
        timestamp = pd.Timestamp(raw_discovery)
        return float(timestamp.to_julian_date() - 2400000.5)
    except Exception:
        return None


def _load_step2_module() -> Any:
    module_name = "sitianclaw_sn_clock_step2"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    if str(ASSET_DIR) not in sys.path:
        sys.path.insert(0, str(ASSET_DIR))
    step2_path = ASSET_DIR / "step2_build_samples.py"
    spec = importlib.util.spec_from_file_location(module_name, step2_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load SN Clock feature pipeline from {step2_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


class PortableSNClockPredictor:
    def __init__(self) -> None:
        self.models: dict[str, Any] = {}
        self.feature_cols: list[str] = []
        self.cat_cols: list[str] = []
        self.quantile_names: list[str] = []
        self.model_files: dict[str, str] = {}
        self.ci_scale = 1.0
        self.sample_idx_scales: dict[str, float] = {}
        self.config: dict[str, Any] = {}
        self._step2_module: Any | None = None
        self._load_models()

    def _load_models(self) -> None:
        try:
            from catboost import CatBoostRegressor
        except ImportError as exc:
            raise RuntimeError("catboost is required for snc-explosion-time.") from exc

        config_path = MODELS_DIR / "best_model_config.json"
        if not config_path.exists():
            raise RuntimeError(f"SN Clock model config is missing: {config_path}")
        self.config = json.loads(config_path.read_text(encoding="utf-8"))
        self.feature_cols = list(self.config.get("feature_cols", []))
        self.cat_cols = list(self.config.get("cat_cols", []))
        self.quantile_names = list(self.config.get("quantile_names", ["q10", "q16", "q50", "q84", "q90"]))
        self.model_files = dict(self.config.get("model_files", {}))
        self.ci_scale = float(self.config.get("ci_scale", 1.0))
        self.sample_idx_scales = {
            str(key): float(value) for key, value in dict(self.config.get("sample_idx_scales", {})).items()
        }

        for quantile in self.quantile_names:
            model_file = MODELS_DIR / self.model_files.get(quantile, f"best_cb_{quantile}.cbm")
            if not model_file.exists():
                continue
            model = CatBoostRegressor()
            model.load_model(str(model_file))
            self.models[quantile] = model

    def is_available(self) -> bool:
        return "q50" in self.models and bool(self.feature_cols)

    def _step2(self) -> Any:
        if self._step2_module is None:
            self._step2_module = _load_step2_module()
        return self._step2_module

    def _get_sample_idx_group(self, sample_idx: Any) -> str | None:
        try:
            if sample_idx is None or pd.isna(sample_idx):
                return None
            idx = int(float(sample_idx))
        except (TypeError, ValueError):
            return None
        if idx <= 0:
            return None
        return str(idx) if idx <= 5 else "6+"

    def _get_ci_scale(self, sample_idx: Any) -> float:
        group = self._get_sample_idx_group(sample_idx)
        if not group:
            return float(self.ci_scale)
        return float(self.sample_idx_scales.get(group, self.ci_scale))

    def _predict_single_quantile(self, quantile_name: str, model_input: pd.DataFrame) -> float | None:
        model = self.models.get(quantile_name)
        if model is None:
            return None
        try:
            prediction = model.predict(model_input)
            if isinstance(prediction, (list, tuple, np.ndarray, pd.Series)):
                return float(prediction[0])
            return float(prediction)
        except Exception as exc:
            logger.warning("SN Clock quantile prediction failed for %s: %s", quantile_name, exc)
            return None

    def _select_ci_pair(self) -> tuple[str | None, str | None]:
        if "q16" in self.models and "q84" in self.models:
            return "q16", "q84"
        if "q10" in self.models and "q90" in self.models:
            return "q10", "q90"
        return None, None

    def _compute_source_sky(self, ra: float | None, dec: float | None) -> dict[str, Any]:
        if ra is None or dec is None:
            return {}
        try:
            coord = SkyCoord(ra=float(ra) * u.deg, dec=float(dec) * u.deg, frame="icrs")
            galactic_b = float(coord.galactic.b.deg)
            abs_b = abs(galactic_b)
            mw_ebv = 0.03 / math.sin(math.radians(abs_b)) if abs_b > 5 else 0.5
            return {
                "ra": float(ra),
                "dec": float(dec),
                "galactic_b": galactic_b,
                "mw_ebv": float(mw_ebv),
            }
        except Exception:
            return {}

    def _build_model_input(self, features: dict[str, Any]) -> pd.DataFrame:
        frame = pd.DataFrame([features])
        for column in self.feature_cols:
            if column not in frame.columns:
                frame[column] = np.nan if column not in self.cat_cols else "Unknown"
        frame = frame[self.feature_cols].copy()
        for column in self.cat_cols:
            frame[column] = frame[column].fillna("Unknown").astype(str)
        for column in frame.columns:
            if column not in self.cat_cols:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame

    def _finalize_prediction(
        self,
        features: dict[str, Any],
        pred_q50: float,
        pred_low: float | None,
        pred_high: float | None,
    ) -> TexpPrediction:
        if pred_low is None:
            pred_low = pred_q50 - 3.0
        if pred_high is None:
            pred_high = pred_q50 + 3.0

        ci_scale = self._get_ci_scale(features.get("sample_idx"))
        half_width = (pred_high - pred_low) / 2.0 * ci_scale
        ci_lower = pred_q50 - half_width
        ci_upper = pred_q50 + half_width

        pred_q50 = min(float(pred_q50), 0.0)
        ci_upper = min(float(ci_upper), 0.0)
        ci_lower = float(ci_lower)
        ci_width = float(ci_upper - ci_lower)

        if ci_width < 3.0:
            confidence = "HIGH"
        elif ci_width < 6.0:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        warnings: list[str] = []
        if int(features.get("n_det", 0) or 0) < 3:
            warnings.append("观测点数较少，预测不确定性较大")
        if int(features.get("has_host_match", 0) or 0) == 0:
            warnings.append("缺少宿主星系信息")
        if pd.isna(features.get("redshift")) or float(features.get("redshift") or 0.05) == 0.05:
            warnings.append("使用默认红移")

        feature_importance = {
            "host_offset_kpc": float(features.get("host_offset_kpc")) if pd.notna(features.get("host_offset_kpc")) else np.nan,
            "redshift": float(features.get("redshift")) if pd.notna(features.get("redshift")) else np.nan,
            "last_nondet_phase": float(features.get("last_nondet_phase")) if pd.notna(features.get("last_nondet_phase")) else np.nan,
            "rise_rate": float(features.get("rise_rate")) if pd.notna(features.get("rise_rate")) else np.nan,
            "n_det": float(features.get("n_det") or 0),
            "sample_idx": float(features.get("sample_idx") or 0),
        }

        used = 0
        for value in features.values():
            try:
                if value is not None and not pd.isna(value):
                    used += 1
            except Exception:
                if value is not None:
                    used += 1

        return TexpPrediction(
            texp=pred_q50,
            ci_lower=ci_lower,
            ci_upper=float(ci_upper),
            ci_width=ci_width,
            confidence=confidence,
            n_features_used=used,
            feature_importance=feature_importance,
            warnings=warnings,
        )

    def predict_from_features(self, features: dict[str, Any]) -> TexpPrediction | None:
        if not self.is_available():
            return None
        try:
            model_input = self._build_model_input(features)
            pred_q50 = self._predict_single_quantile("q50", model_input)
            if pred_q50 is None:
                return None
            low_q, high_q = self._select_ci_pair()
            pred_low = self._predict_single_quantile(low_q, model_input) if low_q else None
            pred_high = self._predict_single_quantile(high_q, model_input) if high_q else None
            return self._finalize_prediction(features, pred_q50, pred_low, pred_high)
        except Exception as exc:
            logger.error("SN Clock portable feature prediction failed: %s", exc)
            return None

    def build_features(
        self,
        target_name: str,
        tns_entry: dict[str, Any],
        ra: float | None,
        dec: float | None,
        tns_photometry: pd.DataFrame,
        forced_photometry: pd.DataFrame | None = None,
        redshift: float | None = None,
        host_redshift: float | None = None,
        host_name: str | None = None,
        host_type: str | None = None,
        host_ra: float | None = None,
        host_dec: float | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        discovery_mjd = _parse_discovery_mjd(tns_entry)
        if discovery_mjd is None:
            return None, {"reason": "missing_discovery_mjd"}

        observations = build_tns_observations(tns_photometry, discovery_mjd)
        observations.extend(build_forced_phot_observations(forced_photometry, discovery_mjd))
        if not observations:
            return None, {"reason": "no_observations", "discovery_mjd": discovery_mjd}

        latest_phase = max(float(item["phase"]) for item in observations if pd.notna(item.get("phase")))
        report_phase_cutoff = max(latest_phase, 0.0)
        report_mjd = discovery_mjd + report_phase_cutoff
        for item in observations:
            item["report_phase"] = report_phase_cutoff
            item["report_mjd"] = report_mjd

        effective_redshift = redshift
        if effective_redshift is None:
            raw_redshift = tns_entry.get("redshift")
            try:
                effective_redshift = float(raw_redshift) if raw_redshift not in (None, "", "N/A") else None
            except Exception:
                effective_redshift = None

        effective_host_redshift = host_redshift if host_redshift is not None else effective_redshift
        source_sky = self._compute_source_sky(ra, dec)
        step2 = self._step2()
        features = step2.extract_features(
            observations,
            {
                target_name: {
                    "host_redshift": effective_host_redshift,
                    "ned_host_name": host_name,
                    "host_type": host_type,
                }
            },
            {
                "sn_name": target_name,
                "redshift": effective_redshift,
                "discovery_mjd": discovery_mjd,
            },
            report_phase_cutoff,
            source_sky=source_sky,
        )

        if not features:
            return None, {
                "reason": "feature_extraction_failed",
                "discovery_mjd": discovery_mjd,
                "report_phase_cutoff": report_phase_cutoff,
            }

        offset_arcsec = compute_offset_arcsec(ra, dec, host_ra, host_dec)
        features["host_offset_arcsec"] = offset_arcsec if offset_arcsec is not None else np.nan
        features["host_offset_kpc"] = np.nan
        features["host_gr"] = np.nan
        features["log_host_mass"] = np.nan
        features["has_host_match"] = 1 if host_name or effective_host_redshift is not None or offset_arcsec is not None else 0
        features["gaia_parallax"] = 0
        features["gaia_pm"] = 0
        features["gaia_is_stellar"] = 0
        features["wise_w1w2"] = 0
        features["wise_is_agn"] = 0
        features["host_dlr"] = 0
        features["host_log_dlr"] = -2
        features["sample_idx"] = int(min(max(len({round(float(item['mjd']), 3) for item in observations}), 1), 6))

        for column in self.feature_cols:
            if column not in features:
                features[column] = np.nan if column not in self.cat_cols else "Unknown"

        metadata = {
            "discovery_mjd": discovery_mjd,
            "report_phase_cutoff": report_phase_cutoff,
            "observation_count": len(observations),
            "sample_idx": features.get("sample_idx"),
            "host_offset_arcsec": offset_arcsec,
            "effective_redshift": effective_redshift,
            "effective_host_redshift": effective_host_redshift,
        }
        return features, metadata


def compute_offset_arcsec(
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


def build_tns_observations(tns_photometry: pd.DataFrame | None, discovery_mjd: float) -> list[dict[str, Any]]:
    if tns_photometry is None or tns_photometry.empty:
        return []
    observations: list[dict[str, Any]] = []
    frame = tns_photometry.copy()
    frame["mjd"] = pd.to_numeric(frame.get("mjd"), errors="coerce")
    frame["mag"] = pd.to_numeric(frame.get("mag"), errors="coerce")
    frame["magerr"] = pd.to_numeric(frame.get("magerr"), errors="coerce")
    frame = frame.dropna(subset=["mjd"])
    for _, row in frame.sort_values("mjd").iterrows():
        filter_name = _normalize_training_filter(row.get("filter"))
        phase = float(row["mjd"] - discovery_mjd)
        is_detection = bool(row.get("is_detection")) and pd.notna(row.get("mag"))
        limiting_mag = None if is_detection else _default_limiting_mag(filter_name)
        observations.append(
            {
                "mjd": float(row["mjd"]),
                "phase": phase,
                "report_phase": 0.0,
                "report_mjd": discovery_mjd,
                "mag": float(row["mag"]) if is_detection else None,
                "limiting_mag": limiting_mag,
                "filter": filter_name,
                "survey": "TNS",
                "is_detection": is_detection,
                "source": "TNS",
            }
        )
    return observations


def build_forced_phot_observations(forced_photometry: pd.DataFrame | None, discovery_mjd: float) -> list[dict[str, Any]]:
    if forced_photometry is None or forced_photometry.empty:
        return []
    frame = forced_photometry.copy()
    frame["mjd"] = pd.to_numeric(frame.get("mjd"), errors="coerce")
    frame["mag"] = pd.to_numeric(frame.get("mag"), errors="coerce")
    frame = frame.dropna(subset=["mjd"]).sort_values("mjd").reset_index(drop=True)
    frame["filter"] = frame["filter"].apply(_normalize_training_filter)
    frame["phase"] = frame["mjd"] - discovery_mjd
    observations: list[dict[str, Any]] = []

    detections = frame[(frame.get("is_detection", False) == True) & frame["mag"].notna()].copy()
    for _, row in detections.iterrows():
        observations.append(
            {
                "mjd": float(row["mjd"]),
                "phase": float(row["phase"]),
                "report_phase": 0.0,
                "report_mjd": discovery_mjd,
                "mag": float(row["mag"]),
                "limiting_mag": None,
                "filter": str(row["filter"]),
                "survey": "ZTF",
                "is_detection": True,
                "source": "forced_photometry",
            }
        )

    nondetections = frame[(frame.get("is_detection", False) != True) & (frame["phase"] < 0)].copy()
    if nondetections.empty:
        return observations
    for filter_name, group in nondetections.groupby("filter"):
        last_row = group.sort_values("phase").iloc[-1]
        limiting_mag = float(last_row["mag"]) if pd.notna(last_row["mag"]) else _default_limiting_mag(str(filter_name))
        observations.append(
            {
                "mjd": float(last_row["mjd"]),
                "phase": float(last_row["phase"]),
                "report_phase": 0.0,
                "report_mjd": discovery_mjd,
                "mag": None,
                "limiting_mag": limiting_mag,
                "filter": str(filter_name),
                "survey": "ZTF",
                "is_detection": False,
                "source": "forced_photometry",
            }
        )
    return observations


def load_optional_forced_photometry(forced_phot_file: str | Path | None) -> tuple[pd.DataFrame | None, str | None]:
    if forced_phot_file is None:
        return None, None
    photometry, resolved_path = read_forced_photometry_file(forced_phot_file)
    if photometry is None or photometry.empty:
        return None, resolved_path or str(forced_phot_file)
    return photometry, resolved_path or str(forced_phot_file)


def get_public_prediction(
    target_name: str,
    ra: float | None,
    dec: float | None,
    tns_entry: dict[str, Any],
    redshift_override: float | None = None,
    host_redshift_override: float | None = None,
    forced_phot_file: str | Path | None = None,
) -> dict[str, Any]:
    predictor = PortableSNClockPredictor()
    if not predictor.is_available():
        raise RuntimeError("Portable SN Clock predictor is unavailable.")

    tns_photometry = fetch_tns_photometry_by_name(target_name)
    forced_photometry, forced_path = load_optional_forced_photometry(forced_phot_file)

    host_z, host_name, host_ra, host_dec, host_type, host_source = get_host_redshift(float(ra), float(dec), target_name)
    features, metadata = predictor.build_features(
        target_name=target_name,
        tns_entry=tns_entry,
        ra=ra,
        dec=dec,
        tns_photometry=tns_photometry,
        forced_photometry=forced_photometry,
        redshift=redshift_override,
        host_redshift=host_redshift_override if host_redshift_override is not None else host_z,
        host_name=host_name,
        host_type=host_type,
        host_ra=host_ra,
        host_dec=host_dec,
    )
    if features is None:
        raise RuntimeError(f"Portable feature extraction failed for {target_name}: {metadata}")

    prediction = predictor.predict_from_features(features)
    if prediction is None:
        raise RuntimeError(f"Portable SN Clock prediction failed for {target_name}.")

    return {
        "prediction": prediction,
        "features": features,
        "feature_metadata": metadata,
        "tns_photometry": tns_photometry,
        "forced_photometry": forced_photometry,
        "forced_path": forced_path,
        "host_query": {
            "z": host_z,
            "name": host_name,
            "ra": host_ra,
            "dec": host_dec,
            "type": host_type,
            "source": host_source,
        },
        "source_data": {
            "tns_name": target_name,
            "discovery_mjd": metadata.get("discovery_mjd"),
            "redshift": redshift_override if redshift_override is not None else tns_entry.get("redshift"),
            "host_redshift": host_redshift_override if host_redshift_override is not None else host_z,
            "ra": ra,
            "dec": dec,
        },
    }


def _photometry_plot_rows(
    tns_photometry: pd.DataFrame | None,
    forced_photometry: pd.DataFrame | None,
    discovery_mjd: float | None,
) -> list[dict[str, Any]]:
    if discovery_mjd is None:
        return []
    rows: list[dict[str, Any]] = []

    def _append(frame: pd.DataFrame | None, source: str) -> None:
        if frame is None or frame.empty:
            return
        local = frame.copy()
        local["mjd"] = pd.to_numeric(local.get("mjd"), errors="coerce")
        local["mag"] = pd.to_numeric(local.get("mag"), errors="coerce")
        local = local.dropna(subset=["mjd"])
        for _, row in local.iterrows():
            mag_value = float(row["mag"]) if pd.notna(row.get("mag")) else None
            rows.append(
                {
                    "phase": float(row["mjd"] - discovery_mjd),
                    "mag": mag_value,
                    "filter": _normalize_training_filter(row.get("filter")),
                    "source": source,
                    "is_detection": bool(row.get("is_detection")) and mag_value is not None,
                }
            )

    _append(tns_photometry, "TNS")
    _append(forced_photometry, "forced_photometry")
    return rows


def plot_explosion_summary(
    target_name: str,
    prediction: TexpPrediction,
    discovery_mjd: float | None,
    tns_photometry: pd.DataFrame | None,
    forced_photometry: pd.DataFrame | None,
    output_path: Path,
) -> Path:
    rows = _photometry_plot_rows(tns_photometry, forced_photometry, discovery_mjd)
    palette = {
        "g-ZTF": "#1f77b4",
        "r-ZTF": "#d62728",
        "i-ZTF": "#9467bd",
        "orange-ATLAS": "#ff7f0e",
        "cyan-ATLAS": "#2ca02c",
        "Clear-": "#7f7f7f",
    }
    fig, (ax_lc, ax_interval) = plt.subplots(
        2,
        1,
        figsize=(9, 7.2),
        gridspec_kw={"height_ratios": [3.2, 1.3]},
    )

    plotted = False
    for filter_name in sorted({str(item["filter"]) for item in rows}):
        subset = [item for item in rows if str(item["filter"]) == filter_name and item["mag"] is not None]
        if not subset:
            continue
        detections = [item for item in subset if item["is_detection"]]
        nondets = [item for item in subset if not item["is_detection"]]
        color = palette.get(filter_name, None)
        if detections:
            ax_lc.scatter(
                [item["phase"] for item in detections],
                [item["mag"] for item in detections],
                s=42,
                color=color,
                edgecolors="black",
                linewidths=0.3,
                label=filter_name,
                zorder=4,
            )
        if nondets:
            ax_lc.scatter(
                [item["phase"] for item in nondets],
                [item["mag"] for item in nondets],
                s=50,
                marker="v",
                facecolors="none",
                edgecolors=color or "#666666",
                linewidths=1.0,
                zorder=3,
            )
        plotted = True

    ax_lc.axvline(0.0, linestyle="--", linewidth=1.2, color="#555555")
    ax_lc.set_title(f"SN Clock Portable Summary: {target_name}")
    ax_lc.set_xlabel("Days Relative to Discovery")
    ax_lc.set_ylabel("Magnitude")
    ax_lc.grid(alpha=0.25)
    if plotted:
        ax_lc.invert_yaxis()
        ax_lc.legend(loc="best", fontsize=8)
    else:
        ax_lc.text(0.5, 0.5, "No photometry points available for plotting", ha="center", va="center", transform=ax_lc.transAxes)

    ax_interval.errorbar(
        [float(prediction.texp)],
        [0],
        xerr=[
            [float(prediction.texp) - float(prediction.ci_lower)],
            [float(prediction.ci_upper) - float(prediction.texp)],
        ],
        fmt="o",
        color="#d62728",
        ecolor="#1f77b4",
        elinewidth=2,
        capsize=5,
    )
    ax_interval.axvline(0.0, linestyle="--", linewidth=1.2, color="#555555")
    ax_interval.set_yticks([])
    ax_interval.set_xlabel("Days Relative to Discovery")
    ax_interval.set_title(f"Predicted Explosion Window ({prediction.confidence})")
    ax_interval.grid(alpha=0.25, axis="x")

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def plot_interval_only(prediction: TexpPrediction, output_path: Path, title: str) -> Path:
    fig, ax = plt.subplots(figsize=(8, 2.4))
    ax.errorbar(
        [float(prediction.texp)],
        [0],
        xerr=[
            [float(prediction.texp) - float(prediction.ci_lower)],
            [float(prediction.ci_upper) - float(prediction.texp)],
        ],
        fmt="o",
        color="#d62728",
        ecolor="#1f77b4",
        elinewidth=2,
        capsize=5,
    )
    ax.axvline(0.0, linestyle="--", color="#555555", linewidth=1.2)
    ax.set_yticks([])
    ax.set_xlabel("Days relative to discovery")
    ax.set_title(title)
    ax.grid(alpha=0.25, axis="x")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def render_prediction_html(
    target_name: str,
    prediction: TexpPrediction,
    discovery_mjd: float | None,
    summary_png_path: Path,
    photometry_summary: dict[str, Any],
    workflow_mode: str,
) -> str:
    summary_image = ""
    try:
        encoded = base64.b64encode(summary_png_path.read_bytes()).decode("utf-8")
        summary_image = (
            f'<img src="data:image/png;base64,{encoded}" '
            'style="width: 100%; border-radius: 10px; border: 1px solid rgba(255,255,255,0.08);" '
            f'alt="SN Clock summary for {target_name}">'
        )
    except Exception:
        pass

    days_since_discovery = None
    t0_days_ago = None
    if discovery_mjd is not None:
        try:
            current_mjd = float(Time.now().mjd)
            days_since_discovery = current_mjd - float(discovery_mjd)
            t0_days_ago = days_since_discovery - float(prediction.texp)
        except Exception:
            days_since_discovery = None
            t0_days_ago = None

    def _fmt(value: Any, digits: int = 2) -> str:
        try:
            return f"{float(value):.{digits}f}"
        except Exception:
            return "--"

    return f"""
    <div style="margin-top: 16px; padding: 20px;
                background: linear-gradient(135deg, #1a1d23 0%, #232830 100%);
                border-radius: 12px; border: 1px solid rgba(255,255,255,0.1);">
        <div style="display:flex; align-items:center; gap:10px; margin-bottom:14px;">
            <span style="font-size:20px;">💥</span>
            <span style="font-weight:600; font-size:16px; color:#fff;">Explosion Time Prediction (SN Clock)</span>
            <span style="margin-left:auto; padding:4px 10px; background:rgba(39,174,96,0.18);
                         border-radius:12px; color:#bdf5c7; font-size:12px;">
                GitHub-only portable
            </span>
        </div>
        <div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:12px; margin-bottom:14px;">
            <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:8px; text-align:center;">
                <div style="color:#9ca3af; font-size:11px; margin-bottom:4px;">Predicted texp</div>
                <div style="color:#34d399; font-size:18px; font-weight:600;">{_fmt(prediction.texp)}</div>
                <div style="color:#6b7280; font-size:10px;">days before discovery</div>
            </div>
            <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:8px; text-align:center;">
                <div style="color:#9ca3af; font-size:11px; margin-bottom:4px;">68% CI</div>
                <div style="color:#60a5fa; font-size:14px; font-weight:600;">[{_fmt(prediction.ci_lower)}, {_fmt(prediction.ci_upper)}]</div>
                <div style="color:#6b7280; font-size:10px;">SN Clock interval</div>
            </div>
            <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:8px; text-align:center;">
                <div style="color:#9ca3af; font-size:11px; margin-bottom:4px;">Predicted t0</div>
                <div style="color:#f59e0b; font-size:16px; font-weight:600;">{_fmt(t0_days_ago, 1)} d ago</div>
                <div style="color:#6b7280; font-size:10px;">relative to now</div>
            </div>
            <div style="background:rgba(255,255,255,0.05); padding:12px; border-radius:8px; text-align:center;">
                <div style="color:#9ca3af; font-size:11px; margin-bottom:4px;">Confidence</div>
                <div style="color:#e5e7eb; font-size:16px; font-weight:600;">{prediction.confidence}</div>
                <div style="color:#6b7280; font-size:10px;">{prediction.n_features_used} features</div>
            </div>
        </div>
        <div style="margin-bottom:12px; color:#94a3b8; font-size:12px; line-height:1.6;">
            Mode: <strong>{workflow_mode}</strong>. TNS rows: {photometry_summary.get("tns_rows", 0)}.
            Forced-phot rows: {photometry_summary.get("forced_rows", 0)}.
        </div>
        {summary_image}
    </div>
    """


def photometry_summary(
    tns_photometry: pd.DataFrame | None,
    forced_photometry: pd.DataFrame | None,
) -> dict[str, Any]:
    def _summary(frame: pd.DataFrame | None) -> tuple[int, list[str]]:
        if frame is None or frame.empty:
            return 0, []
        filters = sorted({_normalize_training_filter(item) for item in frame.get("filter", pd.Series(dtype=object)).dropna().tolist()})
        return int(len(frame)), filters

    tns_rows, tns_filters = _summary(tns_photometry)
    forced_rows, forced_filters = _summary(forced_photometry)
    return {
        "tns_rows": tns_rows,
        "tns_filters": tns_filters,
        "forced_rows": forced_rows,
        "forced_filters": forced_filters,
    }


def make_prediction_payload(
    target_name: str,
    ra: float | None,
    dec: float | None,
    resolved_from: list[str],
    prediction_result: dict[str, Any],
    artifacts: dict[str, Any],
) -> dict[str, Any]:
    prediction: TexpPrediction = prediction_result["prediction"]
    tns_photometry = prediction_result["tns_photometry"]
    forced_photometry = prediction_result["forced_photometry"]
    feature_metadata = prediction_result["feature_metadata"]
    summary = photometry_summary(tns_photometry, forced_photometry)
    workflow_mode = "public_tns_plus_forced_phot" if forced_photometry is not None and not forced_photometry.empty else "public_tns_only"
    return {
        "skill": "snc-explosion-time",
        "workspace_alignment": "GitHub-only portable SN Clock prediction using bundled CatBoost models plus public TNS photometry and optional forced-phot input.",
        "target": {
            "name": target_name,
            "ra": ra,
            "dec": dec,
            "resolved_from": resolved_from,
        },
        "workflow_mode": workflow_mode,
        "source_data": json_safe(prediction_result["source_data"]),
        "host_query": json_safe(prediction_result["host_query"]),
        "feature_metadata": json_safe(feature_metadata),
        "feature_preview": json_safe(
            {
                key: prediction_result["features"].get(key)
                for key in [
                    "redshift",
                    "first_det_phase",
                    "last_nondet_phase",
                    "rise_rate",
                    "n_det",
                    "n_nondet",
                    "sample_idx",
                    "galactic_b",
                ]
            }
        ),
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
        "photometry": summary,
        "forced_photometry": {
            "path": prediction_result["forced_path"],
            "rows": int(len(forced_photometry)) if forced_photometry is not None else 0,
        },
        "artifacts": json_safe(artifacts),
    }
