from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import requests
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

from .redshift import query_ned_for_z_and_host
from .tns import fetch_tns_data_from_web

logger = logging.getLogger(__name__)


def _apply_discovery_date_filter(df: pd.DataFrame, recent_days: int) -> pd.DataFrame:
    if df.empty:
        return df
    table = df.copy()
    table["discoverydate_dt"] = pd.to_datetime(table.get("discoverydate"), errors="coerce")
    if "discovery_mjd" in table.columns:
        missing = table["discoverydate_dt"].isna() & pd.to_numeric(table["discovery_mjd"], errors="coerce").notna()
        if missing.any():
            mjd_values = pd.to_numeric(table.loc[missing, "discovery_mjd"], errors="coerce")
            table.loc[missing, "discoverydate_dt"] = Time(mjd_values, format="mjd").to_datetime()
    cutoff = datetime.utcnow() - timedelta(days=recent_days)
    return table.loc[table["discoverydate_dt"] >= cutoff].copy()


def _cross_match_dedup(df: pd.DataFrame, radius_arcsec: float = 10.0) -> pd.DataFrame:
    if len(df) <= 1 or "ra_deg" not in df.columns or "dec_deg" not in df.columns:
        return df
    ra = pd.to_numeric(df["ra_deg"], errors="coerce")
    dec = pd.to_numeric(df["dec_deg"], errors="coerce")
    valid = ra.notna() & dec.notna()
    if valid.sum() <= 1:
        return df
    coords = SkyCoord(ra=ra[valid].values * u.deg, dec=dec[valid].values * u.deg)
    valid_idx = df.index[valid].tolist()
    priority = df["_source_priority"].fillna(9).astype(int)
    drop_set: set[int] = set()
    for index in range(len(coords)):
        if valid_idx[index] in drop_set:
            continue
        matches = np.where(coords[index].separation(coords).arcsec < radius_arcsec)[0]
        matched_indices = [valid_idx[item] for item in matches if valid_idx[item] not in drop_set]
        if len(matched_indices) <= 1:
            continue
        best = min(matched_indices, key=lambda item: priority[item])
        for item in matched_indices:
            if item != best:
                drop_set.add(item)
    return df.drop(index=list(drop_set)).reset_index(drop=True) if drop_set else df


def _fetch_alerce_candidates(
    survey: str,
    hours_back: int,
    limit: int,
    min_probability: float,
    source_label: str,
) -> pd.DataFrame:
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours_back)
    params = [
        ("classifier", "stamp_classifier"),
        ("class", "SN"),
        ("ranking", 1),
        ("firstmjd", Time(start_time).mjd),
        ("firstmjd", Time(end_time).mjd),
        ("page", 1),
        ("page_size", limit),
        ("count", "false"),
        ("order_by", "probability"),
        ("order_mode", "DESC"),
    ]
    url = f"https://api.alerce.online/{survey}/v1/objects/"
    try:
        response = requests.get(url, params=params, timeout=120)
        response.raise_for_status()
        items = response.json().get("items", [])
    except Exception as exc:
        logger.debug("%s candidate query failed: %s", source_label, exc)
        return pd.DataFrame()

    if not items:
        return pd.DataFrame()

    table = pd.DataFrame(items)
    if "probability" in table.columns:
        table = table.loc[pd.to_numeric(table["probability"], errors="coerce") >= min_probability].copy()
    if table.empty:
        return table

    ra_col = "meanra" if "meanra" in table.columns else "ra"
    dec_col = "meandec" if "meandec" in table.columns else "dec"
    mjd_col = "firstmjd" if "firstmjd" in table.columns else "first_mjd"
    table["tns_name"] = table.get("oid", pd.Series([f"{source_label}_{idx}" for idx in range(len(table))]))
    table["type"] = "Unknown"
    table["ra_deg"] = pd.to_numeric(table.get(ra_col), errors="coerce")
    table["dec_deg"] = pd.to_numeric(table.get(dec_col), errors="coerce")
    table["discovery_mjd"] = pd.to_numeric(table.get(mjd_col), errors="coerce")
    table["discoverydate"] = table["discovery_mjd"].apply(
        lambda value: Time(value, format="mjd").to_datetime().isoformat() if pd.notna(value) else None
    )
    table["data_source"] = source_label
    table["broker"] = "ALeRCE"
    table["broker_survey"] = survey.upper()
    table["stamp_probability"] = pd.to_numeric(table.get("probability"), errors="coerce")
    return table.reset_index(drop=True)


def fetch_combined_data(
    include_ztf: bool = True,
    include_lsst: bool = True,
    ztf_days_back: int = 3,
    ztf_max_candidates: int = 300,
    lsst_hours_back: int = 72,
    lsst_max_candidates: int = 200,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "tns_data": pd.DataFrame(),
        "ztf_data": pd.DataFrame(),
        "lsst_data": pd.DataFrame(),
        "combined_data": pd.DataFrame(),
        "summary": {"tns_count": 0, "ztf_count": 0, "lsst_count": 0, "total_count": 0},
    }
    tns_df = fetch_tns_data_from_web()
    result["tns_data"] = tns_df
    result["summary"]["tns_count"] = len(tns_df)

    if include_ztf:
        ztf_df = _fetch_alerce_candidates(
            survey="ztf",
            hours_back=ztf_days_back * 24,
            limit=ztf_max_candidates,
            min_probability=0.5,
            source_label="ZTF_ALeRCE_Cloud",
        )
        result["ztf_data"] = ztf_df
        result["summary"]["ztf_count"] = len(ztf_df)

    if include_lsst:
        lsst_df = _fetch_alerce_candidates(
            survey="lsst",
            hours_back=lsst_hours_back,
            limit=lsst_max_candidates,
            min_probability=0.3,
            source_label="LSST/alerce/cloud",
        )
        result["lsst_data"] = lsst_df
        result["summary"]["lsst_count"] = len(lsst_df)

    frames = []
    if not result["tns_data"].empty:
        tns_copy = result["tns_data"].copy()
        tns_copy["_source_priority"] = 1
        frames.append(tns_copy)
    if not result["ztf_data"].empty:
        ztf_copy = result["ztf_data"].copy()
        ztf_copy["_source_priority"] = 2
        frames.append(ztf_copy)
    if not result["lsst_data"].empty:
        lsst_copy = result["lsst_data"].copy()
        lsst_copy["_source_priority"] = 3
        frames.append(lsst_copy)

    if frames:
        combined = pd.concat(frames, ignore_index=True, sort=False)
        combined = _cross_match_dedup(combined, radius_arcsec=10.0)
        result["combined_data"] = combined
        result["summary"]["total_count"] = len(combined)

    return result


def build_recent_nearby_pool(
    include_ztf: bool = True,
    include_lsst: bool = True,
    ztf_days_back: int = 3,
    ztf_max_candidates: int = 300,
    lsst_hours_back: int = 72,
    lsst_max_candidates: int = 200,
    recent_days: int = 3,
    nearby_redshift_max: float = 0.025,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    result = fetch_combined_data(
        include_ztf=include_ztf,
        include_lsst=include_lsst,
        ztf_days_back=ztf_days_back,
        ztf_max_candidates=ztf_max_candidates,
        lsst_hours_back=lsst_hours_back,
        lsst_max_candidates=lsst_max_candidates,
    )
    combined = result["combined_data"].copy()
    recent_df = _apply_discovery_date_filter(combined, recent_days)
    if recent_df.empty:
        recent_df["host_redshift"] = pd.Series(dtype="float64")
        recent_df["host_name"] = pd.Series(dtype="object")
        recent_df["nearby_redshift"] = pd.Series(dtype="float64")
        recent_df["redshift_resolution_source"] = pd.Series(dtype="object")
        return result, recent_df, recent_df

    source_redshift = pd.to_numeric(recent_df.get("redshift"), errors="coerce")
    recent_df["host_redshift"] = np.nan
    recent_df["host_name"] = None

    data_source = recent_df.get("data_source", pd.Series(["unknown"] * len(recent_df), index=recent_df.index))
    discoverymag = pd.to_numeric(recent_df.get("discoverymag"), errors="coerce")
    missing_source_z = source_redshift.isna()
    should_query_host = missing_source_z & (
        data_source.astype(str).eq("TNS")
        | (discoverymag.notna() & (discoverymag <= 18.5))
    )
    if bool(should_query_host.any()):
        indices = recent_df.index[should_query_host].tolist()
        result["summary"]["host_query_count"] = len(indices)
        result["summary"]["host_query_scope"] = "missing_z_tns_or_bright"

        def _resolve_host(index: int) -> tuple[int, float | None, str | None]:
            row = recent_df.loc[index]
            z_ned, host_name, _, _, _ = query_ned_for_z_and_host(
                float(row["ra_deg"]),
                float(row["dec_deg"]),
                str(row.get("tns_name") or "Unknown"),
            )
            return index, z_ned, host_name

        max_workers = min(6, len(indices))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_resolve_host, index) for index in indices]
            for future in as_completed(futures):
                index, z_ned, host_name = future.result()
                recent_df.at[index, "host_redshift"] = z_ned
                recent_df.at[index, "host_name"] = host_name
    else:
        result["summary"]["host_query_count"] = 0
        result["summary"]["host_query_scope"] = "missing_z_tns_or_bright"

    host_redshift = pd.to_numeric(recent_df["host_redshift"], errors="coerce")
    recent_df["nearby_redshift"] = host_redshift.where(host_redshift.notna(), source_redshift)
    recent_df["redshift_resolution_source"] = np.where(host_redshift.notna(), "NED", np.where(source_redshift.notna(), "TNS", "unresolved"))
    nearby_df = recent_df.loc[
        recent_df["nearby_redshift"].notna() & (recent_df["nearby_redshift"] <= nearby_redshift_max)
    ].copy()
    nearby_df = nearby_df.sort_values("nearby_redshift", ascending=True)
    return result, recent_df, nearby_df
