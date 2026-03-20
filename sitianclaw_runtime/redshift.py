from __future__ import annotations

import io
import logging
import math
from typing import Any

import numpy as np
import pandas as pd
import requests
import urllib3
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.io.votable import parse_single_table

logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

Z_QUALITY = {
    "tns": (95, 1),
    "ned": (55, 3),
    "broker": (40, 3),
    "unknown": (10, 5),
}


def valid_z(z: float | None) -> bool:
    if z is None:
        return False
    try:
        value = float(z)
        return math.isfinite(value) and 0.0005 < value < 5.0
    except (TypeError, ValueError):
        return False


def merge_redshifts(
    ned_z: float | None = None,
    broker_z: float | None = None,
    broker_source: str = "broker",
    tns_z: float | None = None,
) -> dict[str, Any]:
    measurements = []
    if valid_z(tns_z):
        measurements.append((float(tns_z), "tns"))
    if valid_z(ned_z):
        measurements.append((float(ned_z), "ned"))
    if valid_z(broker_z):
        measurements.append((float(broker_z), broker_source or "broker"))

    if not measurements:
        return {"z_final": None, "z_source": "", "z_quality_tier": 99, "z_n_sources": 0, "z_flag": "no_z"}

    measurements.sort(key=lambda item: -Z_QUALITY.get(item[1], Z_QUALITY["unknown"])[0])
    best_z, best_source = measurements[0]
    spread = max(item[0] for item in measurements) - min(item[0] for item in measurements)
    if len(measurements) == 1:
        flag = "single_source"
    elif spread < 0.01:
        flag = "consensus"
    elif spread < 0.05:
        flag = "minor_spread"
    else:
        flag = "outlier_detected"
    return {
        "z_final": best_z,
        "z_source": best_source,
        "z_quality_tier": Z_QUALITY.get(best_source, Z_QUALITY["unknown"])[1],
        "z_n_sources": len(measurements),
        "z_flag": flag,
    }


def _decode(value: object) -> object:
    return value.decode() if isinstance(value, bytes) else value


def _choose_ned_row(table) -> tuple[object, object, object, object, object]:
    available_cols = table.array.dtype.names or []
    name_col = "main_col2" if "main_col2" in available_cols else None
    ra_col = "main_col3" if "main_col3" in available_cols else None
    dec_col = "main_col4" if "main_col4" in available_cols else None
    type_col = "main_col5" if "main_col5" in available_cols else None
    z_col = "main_col7" if "main_col7" in available_cols else None
    if not all([name_col, ra_col, dec_col, type_col, z_col]):
        return "N/A", "N/A", "N/A", "N/A", "N/A"

    names = table.array[name_col][:30]
    ras = table.array[ra_col][:30]
    decs = table.array[dec_col][:30]
    types = table.array[type_col][:30]
    redshifts = table.array[z_col][:30]
    photometric_types = {"VisS", "IrS", "UvS", "UvES", "RadioS", "XrayS"}

    def is_valid_z(item: object) -> bool:
        if item in [None, "", "N/A"]:
            return False
        try:
            return valid_z(float(item))
        except Exception:
            return False

    def build_row(index: int) -> tuple[object, object, object, object, object]:
        z_value = redshifts[index]
        return _decode(names[index]), _decode(ras[index]), _decode(decs[index]), z_value, _decode(types[index])

    for idx, z_value in enumerate(redshifts):
        name = str(_decode(names[idx]) or "")
        if ("NGC" in name or "IC" in name) and is_valid_z(z_value):
            return build_row(idx)
    for idx, z_value in enumerate(redshifts):
        if str(_decode(types[idx]) or "").strip() == "G" and is_valid_z(z_value):
            return build_row(idx)
    for idx, z_value in enumerate(redshifts):
        obj_type = str(_decode(types[idx]) or "").strip()
        if obj_type not in {"*", "**"} and obj_type not in photometric_types and is_valid_z(z_value):
            return build_row(idx)
    for idx, z_value in enumerate(redshifts):
        obj_type = str(_decode(types[idx]) or "").strip()
        if obj_type in {"*", "**"} or not is_valid_z(z_value):
            continue
        try:
            if obj_type in photometric_types and float(z_value) < 0.05:
                continue
        except Exception:
            pass
        return build_row(idx)
    for idx, obj_type in enumerate(types):
        if str(_decode(obj_type) or "").strip() not in {"*", "**"}:
            return build_row(idx)
    return "N/A", "N/A", "N/A", "N/A", "N/A"


def query_ned_for_z_and_host(
    ra_deg: float,
    dec_deg: float,
    tns_name_short: str = "Unknown",
    radius_arcmin: float = 2.0,
    timeout_seconds: float = 8.0,
) -> tuple[float | None, str | None, float | None, float | None, str | None]:
    url = (
        "https://ned.ipac.caltech.edu/cgi-bin/objsearch?search_type=Near+Position+Search"
        f"&in_csys=Equatorial&in_equinox=J2000.0&lon={ra_deg}d&lat={dec_deg}d"
        f"&radius={radius_arcmin}&out_csys=Equatorial&out_equinox=J2000.0&of=xml_main"
    )
    try:
        response = requests.get(url, timeout=timeout_seconds, verify=False)
        response.raise_for_status()
        table = parse_single_table(io.BytesIO(response.content))
        if table is None or len(table.array) == 0:
            return None, None, None, None, None
        host_name, host_ra, host_dec, host_z, host_type = _choose_ned_row(table)
        final_z = None
        try:
            final_z = float(host_z) if valid_z(float(host_z)) else None
        except Exception:
            final_z = None
        if isinstance(host_ra, str) and isinstance(host_dec, str):
            try:
                coord = SkyCoord(ra=host_ra, dec=host_dec, unit=(u.hourangle, u.deg))
                host_ra = float(coord.ra.deg)
                host_dec = float(coord.dec.deg)
            except Exception:
                host_ra = None
                host_dec = None
        else:
            try:
                host_ra = float(host_ra)
                host_dec = float(host_dec)
            except Exception:
                host_ra = None
                host_dec = None
        return final_z, str(host_name) if host_name not in [None, "N/A"] else None, host_ra, host_dec, str(host_type) if host_type not in [None, "N/A"] else None
    except Exception as exc:
        logger.debug("NED lookup failed for %s: %s", tns_name_short, exc)
        return None, None, None, None, None


def get_host_redshift(
    ra: float,
    dec: float,
    tns_name: str | None = None,
) -> tuple[float | None, str | None, float | None, float | None, str | None, str]:
    z_ned, host_name, host_ra, host_dec, host_type = query_ned_for_z_and_host(ra, dec, tns_name or "")
    return z_ned, host_name, host_ra, host_dec, host_type, "NED" if z_ned is not None else "unresolved"
