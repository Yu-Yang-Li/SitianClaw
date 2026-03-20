from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from astropy import units as u
from astropy.coordinates import Angle, SkyCoord

logger = logging.getLogger(__name__)

_GAIA_LOCK = threading.Lock()
_GAIA_LAST_QUERY_TIME = 0.0
_GAIA_MIN_INTERVAL = 1.5


def _optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if hasattr(value, "mask") and bool(value.mask):
            return None
        result = float(value)
        if result != result:
            return None
        return result
    except Exception:
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if hasattr(value, "mask") and bool(value.mask):
            return None
    except Exception:
        pass
    if hasattr(value, "decode"):
        try:
            value = value.decode("utf-8")
        except Exception:
            pass
    text = str(value).strip()
    return text or None


def _row_value(row: Any, *candidates: str) -> Any:
    try:
        colnames = list(getattr(row, "colnames", []) or [])
    except Exception:
        colnames = []
    lowered = {str(name).lower(): name for name in colnames}
    for candidate in candidates:
        actual = lowered.get(candidate.lower())
        if actual is None:
            continue
        try:
            return row[actual]
        except Exception:
            continue
    return None


def _gaia_cache_dir() -> Path:
    cache_dir = Path(tempfile.gettempdir()) / "sitianclaw_cache" / "gaia_dr3"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _gaia_cache_key(ra_deg: float, dec_deg: float) -> str:
    return f"{ra_deg:.4f}_{dec_deg:.4f}"


def _gaia_cache_get(ra_deg: float, dec_deg: float) -> dict[str, Any] | None:
    path = _gaia_cache_dir() / f"{_gaia_cache_key(ra_deg, dec_deg)}.json"
    if not path.exists():
        return None
    try:
        age_days = (time.time() - path.stat().st_mtime) / 86400
        if age_days > 30:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload == {}:
            return {}
        return payload
    except Exception:
        return None


def _gaia_cache_put(ra_deg: float, dec_deg: float, payload: dict[str, Any] | None) -> None:
    path = _gaia_cache_dir() / f"{_gaia_cache_key(ra_deg, dec_deg)}.json"
    try:
        path.write_text(json.dumps(payload or {}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def query_vsx(ra_deg: float, dec_deg: float, radius_arcsec: float = 2.0) -> dict[str, Any] | None:
    try:
        from astroquery.vizier import Vizier

        vizier = Vizier(columns=["*"])
        result = vizier.query_region(
            SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg), frame="icrs"),
            radius=Angle(radius_arcsec / 3600.0, "deg"),
            catalog="B/vsx/vsx",
        )
        if result and len(result) > 0 and len(result[0]) > 0:
            row = result[0][0]
            return {
                "source": "VSX",
                "name": _optional_str(row["Name"]) if "Name" in row.colnames else None,
                "type": _optional_str(row["Type"]) if "Type" in row.colnames else None,
                "period": _optional_float(row["Period"]) if "Period" in row.colnames else None,
                "max_mag": _optional_float(row["max"]) if "max" in row.colnames else None,
                "min_mag": _optional_float(row["min"]) if "min" in row.colnames else None,
                "is_variable_star": True,
            }
    except Exception as exc:
        logger.debug("VSX query failed: %s", exc)
    return None


def query_simbad(ra_deg: float, dec_deg: float, radius_arcsec: float = 2.0) -> dict[str, Any] | None:
    try:
        from astroquery.simbad import Simbad

        simbad = Simbad()
        simbad.add_votable_fields("otype", "sp", "z_value", "rvz_radvel")
        simbad.TIMEOUT = 30
        result_table = simbad.query_region(
            SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg), frame="icrs"),
            radius=radius_arcsec * u.arcsec,
        )
        if result_table is not None and len(result_table) > 0:
            row = result_table[0]
            otype = _optional_str(_row_value(row, "OTYPE", "otype"))
            star_types = ["*", "Star", "V*", "PM*", "HV*", "WD", "pMS", "YSO", "RG", "SG", "HB*"]
            agn_types = ["AGN", "QSO", "Seyfert", "Blazar", "BLLac", "LINER"]
            return {
                "source": "SIMBAD",
                "main_id": _optional_str(_row_value(row, "MAIN_ID", "main_id")),
                "otype": otype,
                "sp_type": _optional_str(_row_value(row, "SP_TYPE", "sp_type")),
                "z_value": _optional_float(_row_value(row, "Z_VALUE", "z_value", "RVZ_REDSHIFT", "rvz_redshift")),
                "is_star": any(token in (otype or "") for token in star_types),
                "is_agn": any(token in (otype or "") for token in agn_types),
            }
    except Exception as exc:
        logger.debug("SIMBAD query failed: %s", exc)
    return None


def query_gaia_dr3(ra_deg: float, dec_deg: float, radius_arcsec: float = 1.0) -> dict[str, Any] | None:
    global _GAIA_LAST_QUERY_TIME

    cached = _gaia_cache_get(ra_deg, dec_deg)
    if cached is not None:
        return cached or None

    for attempt in range(3):
        try:
            from astroquery.gaia import Gaia

            with _GAIA_LOCK:
                elapsed = time.time() - _GAIA_LAST_QUERY_TIME
                if elapsed < _GAIA_MIN_INTERVAL:
                    time.sleep(_GAIA_MIN_INTERVAL - elapsed)
                query = f"""
                SELECT TOP 1
                    source_id, ra, dec, parallax, parallax_error,
                    pmra, pmra_error, pmdec, pmdec_error,
                    phot_g_mean_mag, bp_rp,
                    DISTANCE(
                        POINT('ICRS', ra, dec),
                        POINT('ICRS', {ra_deg}, {dec_deg})
                    ) AS separation
                FROM gaiadr3.gaia_source
                WHERE 1=CONTAINS(
                    POINT('ICRS', ra, dec),
                    CIRCLE('ICRS', {ra_deg}, {dec_deg}, {radius_arcsec / 3600.0})
                )
                ORDER BY separation ASC
                """
                Gaia.MAIN_GAIA_TABLE = "gaiadr3.gaia_source"
                result_table = Gaia.launch_job_async(query, dump_to_file=False).get_results()
                _GAIA_LAST_QUERY_TIME = time.time()

            if result_table is None or len(result_table) == 0:
                _gaia_cache_put(ra_deg, dec_deg, {})
                return None

            row = result_table[0]
            parallax = _optional_float(row["parallax"]) if "parallax" in result_table.colnames else None
            parallax_error = _optional_float(row["parallax_error"]) if "parallax_error" in result_table.colnames else None
            pmra = _optional_float(row["pmra"]) if "pmra" in result_table.colnames else None
            pmdec = _optional_float(row["pmdec"]) if "pmdec" in result_table.colnames else None
            total_pm = None
            if pmra is not None and pmdec is not None:
                total_pm = (pmra ** 2 + pmdec ** 2) ** 0.5
            is_stellar = False
            if parallax is not None and parallax_error and parallax_error > 0 and parallax / parallax_error > 5:
                is_stellar = True
            if total_pm is not None and total_pm > 10:
                is_stellar = True

            payload = {
                "source": "Gaia DR3",
                "source_id": _optional_str(row["source_id"]) if "source_id" in result_table.colnames else None,
                "parallax": parallax,
                "parallax_error": parallax_error,
                "pmra": pmra,
                "pmdec": pmdec,
                "total_pm": total_pm,
                "phot_g_mean_mag": _optional_float(row["phot_g_mean_mag"]) if "phot_g_mean_mag" in result_table.colnames else None,
                "bp_rp": _optional_float(row["bp_rp"]) if "bp_rp" in result_table.colnames else None,
                "is_stellar": is_stellar,
            }
            _gaia_cache_put(ra_deg, dec_deg, payload)
            return payload
        except Exception as exc:
            err = str(exc).lower()
            if attempt < 2 and any(token in err for token in ["ip", "rate", "429", "disabled"]):
                time.sleep(2 ** (attempt + 1))
                continue
            logger.debug("Gaia query failed: %s", exc)
            return None
    return None


def query_gaia_variability(ra_deg: float, dec_deg: float, radius_arcsec: float = 2.0) -> dict[str, Any] | None:
    try:
        from astroquery.vizier import Vizier

        result = Vizier(columns=["*"]).query_region(
            SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg), frame="icrs"),
            radius=Angle(radius_arcsec / 3600.0, "deg"),
            catalog="I/358/vclassre",
        )
        if result and len(result) > 0 and len(result[0]) > 0:
            row = result[0][0]
            return {
                "source": "Gaia DR3 Variability",
                "var_class": _optional_str(row["Class"]) if "Class" in row.colnames else None,
                "is_variable": True,
            }
    except Exception as exc:
        logger.debug("Gaia variability query failed: %s", exc)
    return None


def query_wise(ra_deg: float, dec_deg: float, radius_arcsec: float = 2.0) -> dict[str, Any] | None:
    try:
        from astroquery.ipac.irsa import Irsa

        result = Irsa.query_region(
            SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg), frame="icrs"),
            catalog="allwise_p3as_psd",
            radius=radius_arcsec * u.arcsec,
        )
        if result is not None and len(result) > 0:
            row = result[0]
            w1_mag = _optional_float(row["w1mpro"]) if "w1mpro" in result.colnames else None
            w2_mag = _optional_float(row["w2mpro"]) if "w2mpro" in result.colnames else None
            color = None
            if w1_mag is not None and w2_mag is not None:
                color = w1_mag - w2_mag
            return {
                "source": "AllWISE",
                "w1_mag": w1_mag,
                "w2_mag": w2_mag,
                "w1_w2_color": color,
                "is_agn_candidate": color is not None and color > 0.8,
                "agn_criterion": "W1-W2 > 0.8 (Stern+2012)",
            }
    except Exception as exc:
        logger.debug("AllWISE query failed: %s", exc)
    return None


def query_milliquas(ra_deg: float, dec_deg: float, radius_arcsec: float = 1.0) -> dict[str, Any] | None:
    try:
        from astroquery.vizier import Vizier

        vizier = Vizier(timeout=30)
        vizier.ROW_LIMIT = 1
        result = vizier.query_region(
            SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg), frame="icrs"),
            radius=radius_arcsec * u.arcsec,
            catalog="VII/290",
        )
        if result and len(result) > 0 and len(result[0]) > 0:
            row = result[0][0]
            return {
                "source": "Milliquas",
                "name": _optional_str(row["Name"]) if "Name" in row.colnames else None,
                "type": _optional_str(row["Type"]) if "Type" in row.colnames else None,
                "redshift": _optional_float(row["z"]) if "z" in row.colnames else None,
                "is_qso_agn": True,
            }
    except Exception as exc:
        logger.debug("Milliquas query failed: %s", exc)
    return None


def query_asassn_variable(ra_deg: float, dec_deg: float, radius_arcsec: float = 2.0) -> dict[str, Any] | None:
    try:
        from astroquery.vizier import Vizier

        result = Vizier(columns=["*"]).query_region(
            SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg), frame="icrs"),
            radius=Angle(radius_arcsec / 3600.0, "deg"),
            catalog="II/366",
        )
        if result and len(result) > 0 and len(result[0]) > 0:
            row = result[0][0]
            return {
                "source": "ASAS-SN Variable",
                "type": _optional_str(row["Type"]) if "Type" in row.colnames else None,
                "vmag": _optional_float(row["Vmag"]) if "Vmag" in row.colnames else None,
                "amplitude": _optional_float(row["Amp"]) if "Amp" in row.colnames else None,
                "period": _optional_float(row["Per"]) if "Per" in row.colnames else None,
                "is_variable_star": True,
            }
    except Exception as exc:
        logger.debug("ASAS-SN query failed: %s", exc)
    return None


def query_panstarrs(ra_deg: float, dec_deg: float, radius_arcsec: float = 2.0) -> dict[str, Any] | None:
    try:
        from astroquery.mast import Catalogs

        result = Catalogs.query_region(
            SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg), frame="icrs"),
            radius=radius_arcsec * u.arcsec,
            catalog="Panstarrs",
            data_release="dr2",
        )
        if result is not None and len(result) > 0:
            row = result[0]
            return {
                "source": "Pan-STARRS DR2",
                "objID": _optional_str(row["objID"]) if "objID" in result.colnames else None,
                "g_mag": _optional_float(row["gMeanPSFMag"]) if "gMeanPSFMag" in result.colnames else None,
                "r_mag": _optional_float(row["rMeanPSFMag"]) if "rMeanPSFMag" in result.colnames else None,
                "i_mag": _optional_float(row["iMeanPSFMag"]) if "iMeanPSFMag" in result.colnames else None,
                "z_mag": _optional_float(row["zMeanPSFMag"]) if "zMeanPSFMag" in result.colnames else None,
                "y_mag": _optional_float(row["yMeanPSFMag"]) if "yMeanPSFMag" in result.colnames else None,
            }
    except Exception as exc:
        logger.debug("Pan-STARRS query failed: %s", exc)
    return None


def query_2mass(ra_deg: float, dec_deg: float, radius_arcsec: float = 3.0) -> dict[str, Any] | None:
    try:
        from astroquery.vizier import Vizier

        result = Vizier(columns=["*"]).query_region(
            SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg), frame="icrs"),
            radius=Angle(radius_arcsec / 3600.0, "deg"),
            catalog="II/246/out",
        )
        if result and len(result) > 0 and len(result[0]) > 0:
            row = result[0][0]
            return {
                "source": "2MASS",
                "designation": _optional_str(row["_2MASS"]) if "_2MASS" in row.colnames else None,
                "j_mag": _optional_float(row["Jmag"]) if "Jmag" in row.colnames else None,
                "h_mag": _optional_float(row["Hmag"]) if "Hmag" in row.colnames else None,
                "k_mag": _optional_float(row["Kmag"]) if "Kmag" in row.colnames else None,
            }
    except Exception as exc:
        logger.debug("2MASS query failed: %s", exc)
    return None


def query_sdss_cv(ra_deg: float, dec_deg: float, radius_arcsec: float = 2.0) -> dict[str, Any] | None:
    try:
        from astroquery.vizier import Vizier

        result = Vizier(columns=["*"]).query_region(
            SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg), frame="icrs"),
            radius=Angle(radius_arcsec / 3600.0, "deg"),
            catalog="J/MNRAS/524/4867/tablea1",
        )
        if result and len(result) > 0 and len(result[0]) > 0:
            row = result[0][0]
            period = _optional_float(row["Per"]) if "Per" in row.colnames else None
            return {
                "source": "SDSS CV",
                "name": _optional_str(row["Name"]) if "Name" in row.colnames else None,
                "type": _optional_str(row["VType"]) if "VType" in row.colnames else None,
                "orbital_period_hr": period * 24.0 if period is not None else None,
                "is_cv": True,
            }
    except Exception as exc:
        logger.debug("SDSS CV query failed: %s", exc)
    return None


def _generate_summary(results: dict[str, Any], tns_name: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "tns_name": tns_name,
        "n_matches": 0,
        "is_stellar": False,
        "is_agn": False,
        "is_variable": False,
        "is_cv": False,
        "is_qso": False,
        "warnings": [],
        "matched_sources": [],
    }
    for key, result in results.items():
        if result is None or key == "summary":
            continue
        summary["n_matches"] += 1
        summary["matched_sources"].append(result.get("source", key))
        if result.get("is_stellar"):
            summary["is_stellar"] = True
            summary["warnings"].append("Gaia indicates a stellar source through significant parallax or proper motion.")
        if result.get("is_star"):
            summary["is_stellar"] = True
            summary["warnings"].append(f"SIMBAD classifies the source as stellar: {result.get('otype')}.")
        if result.get("is_agn"):
            summary["is_agn"] = True
            summary["warnings"].append(f"SIMBAD classifies the source as AGN-like: {result.get('otype')}.")
        if result.get("is_agn_candidate"):
            summary["is_agn"] = True
            color = result.get("w1_w2_color")
            summary["warnings"].append(f"WISE color W1-W2={color:.2f} is consistent with an AGN candidate.")
        if result.get("is_qso_agn"):
            summary["is_qso"] = True
            summary["is_agn"] = True
            summary["warnings"].append(f"Milliquas reports a known QSO/AGN match: {result.get('name')}.")
        if result.get("is_variable") or result.get("is_variable_star"):
            summary["is_variable"] = True
            summary["warnings"].append(f"Known variable-star signature: {result.get('type') or result.get('var_class')}.")
        if result.get("is_cv"):
            summary["is_cv"] = True
            summary["warnings"].append(f"Known cataclysmic-variable signature: {result.get('type')}.")

    contamination_score = 0
    if summary["is_stellar"]:
        contamination_score += 3
    if summary["is_agn"] or summary["is_qso"]:
        contamination_score += 3
    if summary["is_cv"]:
        contamination_score += 2
    if summary["is_variable"]:
        contamination_score += 1
    summary["contamination_score"] = contamination_score
    summary["is_likely_contaminant"] = contamination_score >= 3
    return summary


def crossmatch_all(
    ra_deg: float,
    dec_deg: float,
    tns_name: str = "Unknown",
    timeout: float = 60.0,
    include_photometry: bool = True,
) -> dict[str, Any]:
    tasks: dict[str, tuple[Any, tuple[Any, ...]]] = {
        "vsx": (query_vsx, (ra_deg, dec_deg, 2.0)),
        "simbad": (query_simbad, (ra_deg, dec_deg, 2.0)),
        "gaia": (query_gaia_dr3, (ra_deg, dec_deg, 1.0)),
        "gaia_var": (query_gaia_variability, (ra_deg, dec_deg, 2.0)),
        "wise": (query_wise, (ra_deg, dec_deg, 2.0)),
        "milliquas": (query_milliquas, (ra_deg, dec_deg, 1.0)),
        "asassn": (query_asassn_variable, (ra_deg, dec_deg, 2.0)),
        "sdss_cv": (query_sdss_cv, (ra_deg, dec_deg, 2.0)),
    }
    if include_photometry:
        tasks["panstarrs"] = (query_panstarrs, (ra_deg, dec_deg, 2.0))
        tasks["twomass"] = (query_2mass, (ra_deg, dec_deg, 3.0))

    results: dict[str, Any] = {}
    started = time.time()
    for name, (func, func_args) in tasks.items():
        elapsed = time.time() - started
        if elapsed >= timeout:
            logger.debug("Crossmatch timeout reached before %s; leaving remaining tasks empty.", name)
            break
        try:
            results[name] = func(*func_args)
        except Exception as exc:
            logger.debug("Crossmatch task %s failed: %s", name, exc)
            results[name] = None
    for name in tasks:
        results.setdefault(name, None)
    results["summary"] = _generate_summary(results, tns_name)
    logger.info("Host-context crossmatch finished for %s in %.1fs", tns_name, time.time() - started)
    return results


def should_exclude_as_definite_star(results: dict[str, Any]) -> tuple[bool, str]:
    exclude_reasons: list[str] = []

    gaia_result = results.get("gaia") or {}
    parallax = gaia_result.get("parallax")
    parallax_error = gaia_result.get("parallax_error")
    if parallax is not None and parallax_error is not None and parallax_error > 0:
        if parallax / parallax_error > 5 and parallax > 1.0:
            exclude_reasons.append(f"Gaia parallax is significant ({parallax:.2f}±{parallax_error:.2f} mas, likely <1 kpc).")
    total_pm = gaia_result.get("total_pm")
    if total_pm is not None and total_pm > 20:
        exclude_reasons.append(f"Gaia proper motion is high ({total_pm:.1f} mas/yr).")

    simbad_result = results.get("simbad") or {}
    otype = simbad_result.get("otype") or ""
    definite_star_types = [
        "Star",
        "*",
        "V*",
        "PM*",
        "WD",
        "pWD",
        "HV*",
        "RG",
        "SG",
        "HB*",
        "YSO",
        "pMS",
        "TTS",
        "LP*",
        "Mi*",
        "Mira",
        "RR*",
        "Cep",
        "Ce*",
        "EB*",
        "Al*",
        "bC*",
        "RS*",
        "BY*",
        "WR*",
    ]
    if any(token in otype for token in definite_star_types):
        exclude_reasons.append(f"SIMBAD classifies the source as stellar ({otype}).")

    vsx_result = results.get("vsx") or {}
    if vsx_result.get("is_variable_star"):
        var_type = vsx_result.get("type") or ""
        if not any(token in var_type for token in ["SN", "Nova", "N", "NL", "NR"]):
            exclude_reasons.append(f"VSX lists the source as a known variable star ({var_type}).")

    sdss_cv = results.get("sdss_cv") or {}
    if sdss_cv.get("is_cv"):
        exclude_reasons.append(f"SDSS classifies the source as a cataclysmic variable ({sdss_cv.get('type')}).")

    if len(exclude_reasons) >= 2:
        return True, "; ".join(exclude_reasons)
    if len(exclude_reasons) == 1 and ("parallax" in exclude_reasons[0] or "proper motion" in exclude_reasons[0]):
        return True, exclude_reasons[0]
    return False, ""
