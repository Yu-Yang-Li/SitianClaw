from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

from .redshift import query_ned_for_z_and_host, valid_z

logger = logging.getLogger(__name__)

DEFAULT_REDSHIFT_RANGE = (0.0, 0.025)
DEFAULT_RELAXED_REDSHIFT_RANGE = (0.0, 0.05)
DEFAULT_RECENT_DAYS = 3
DEFAULT_RELAXED_RECENT_DAYS = 7
DEFAULT_MIN_GALACTIC_LATITUDE = 15.0
DEFAULT_BRIGHT_MAG_THRESHOLD = 18.0


def get_portable_screening_config() -> dict[str, Any]:
    return {
        "REDSHIFT_RANGE": DEFAULT_REDSHIFT_RANGE,
        "RECENT_DISCOVERY_DAYS": DEFAULT_RECENT_DAYS,
        "MIN_GALACTIC_LATITUDE": DEFAULT_MIN_GALACTIC_LATITUDE,
        "BRIGHT_MAG_THRESHOLD": DEFAULT_BRIGHT_MAG_THRESHOLD,
        "HOST_QUERY_MAX_WORKERS": 6,
        "HOST_QUERY_TIMEOUT_SECONDS": 8.0,
    }


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")


def ensure_required_columns(df: pd.DataFrame) -> pd.DataFrame:
    table = df.copy()
    required_columns = [
        "redshift",
        "host_redshift",
        "discoverydate",
        "ra",
        "dec",
        "ra_deg",
        "dec_deg",
        "discoverymag",
        "host_name",
        "host_type",
        "host_ra_deg",
        "host_dec_deg",
        "host_galactic_b",
    ]
    for column in required_columns:
        if column not in table.columns:
            table[column] = np.nan

    need_backfill = table["ra_deg"].isna() | table["dec_deg"].isna()
    if bool(need_backfill.any()):
        coords = []
        for _, row in table.loc[need_backfill, ["ra", "dec"]].iterrows():
            try:
                if pd.isna(row["ra"]) or pd.isna(row["dec"]):
                    coords.append((np.nan, np.nan))
                    continue
                if isinstance(row["ra"], str) or isinstance(row["dec"], str):
                    try:
                        coord = SkyCoord(ra=row["ra"], dec=row["dec"], unit=(u.hourangle, u.deg), frame="icrs")
                    except Exception:
                        coord = SkyCoord(ra=float(row["ra"]), dec=float(row["dec"]), unit=u.deg, frame="icrs")
                else:
                    coord = SkyCoord(ra=float(row["ra"]), dec=float(row["dec"]), unit=u.deg, frame="icrs")
                coords.append((float(coord.ra.deg), float(coord.dec.deg)))
            except Exception:
                coords.append((np.nan, np.nan))
        table.loc[need_backfill, "ra_deg"] = [item[0] for item in coords]
        table.loc[need_backfill, "dec_deg"] = [item[1] for item in coords]
    return table


def process_data_types(df: pd.DataFrame) -> pd.DataFrame:
    table = df.copy()
    table["discoverydate_dt"] = pd.to_datetime(table.get("discoverydate"), errors="coerce")

    if "firstmjd" in table.columns:
        firstmjd = pd.to_numeric(table["firstmjd"], errors="coerce")
        missing = table["discoverydate_dt"].isna() & firstmjd.notna()
        if bool(missing.any()):
            table.loc[missing, "discoverydate_dt"] = Time(firstmjd.loc[missing], format="mjd").to_datetime()

    if "discovery_mjd" in table.columns:
        discovery_mjd = pd.to_numeric(table["discovery_mjd"], errors="coerce")
        missing = table["discoverydate_dt"].isna() & discovery_mjd.notna()
        if bool(missing.any()):
            table.loc[missing, "discoverydate_dt"] = Time(discovery_mjd.loc[missing], format="mjd").to_datetime()

    table["discoverymag"] = pd.to_numeric(table.get("discoverymag"), errors="coerce")
    table["redshift"] = pd.to_numeric(table.get("redshift"), errors="coerce")
    if "host_redshift" in table.columns:
        table["host_redshift"] = pd.to_numeric(table["host_redshift"], errors="coerce")
    return table


def apply_discovery_date_filter(df: pd.DataFrame, recent_days: int) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    cutoff = datetime.utcnow() - timedelta(days=recent_days)
    table = df.copy()
    table["discoverydate_dt"] = pd.to_datetime(table.get("discoverydate_dt"), errors="coerce")
    return table.loc[table["discoverydate_dt"] >= cutoff].copy()


def enrich_host_information(df: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, int]]:
    table = df.copy()
    if table.empty:
        return table, {"attempted": 0, "resolved_redshift": 0, "resolved_host": 0}

    for column in ["host_name", "host_type"]:
        table[column] = table[column].astype("object")

    source_redshift = pd.to_numeric(table.get("redshift"), errors="coerce")
    bright_mag = pd.to_numeric(table.get("discoverymag"), errors="coerce") <= float(config["BRIGHT_MAG_THRESHOLD"])
    valid_coords = pd.to_numeric(table["ra_deg"], errors="coerce").notna() & pd.to_numeric(table["dec_deg"], errors="coerce").notna()
    should_query = valid_coords & (source_redshift.isna() | bright_mag.fillna(False))
    indices = table.index[should_query].tolist()

    summary = {"attempted": len(indices), "resolved_redshift": 0, "resolved_host": 0}
    if not indices:
        return table, summary

    def _query(index: int) -> tuple[int, float | None, str | None, float | None, float | None, str | None]:
        row = table.loc[index]
        return (
            index,
            *query_ned_for_z_and_host(
                ra_deg=float(row["ra_deg"]),
                dec_deg=float(row["dec_deg"]),
                tns_name_short=str(row.get("tns_name") or "Unknown"),
                timeout_seconds=float(config["HOST_QUERY_TIMEOUT_SECONDS"]),
            ),
        )

    max_workers = min(int(config["HOST_QUERY_MAX_WORKERS"]), len(indices))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_query, index) for index in indices]
        for future in as_completed(futures):
            index, z_ned, host_name, host_ra, host_dec, host_type = future.result()
            if valid_z(z_ned):
                table.at[index, "host_redshift"] = float(z_ned)
                summary["resolved_redshift"] += 1
            if host_name:
                table.at[index, "host_name"] = host_name
                summary["resolved_host"] += 1
            if host_type:
                table.at[index, "host_type"] = host_type
            if host_ra is not None and host_dec is not None:
                table.at[index, "host_ra_deg"] = host_ra
                table.at[index, "host_dec_deg"] = host_dec
                try:
                    host_coord = SkyCoord(ra=float(host_ra) * u.deg, dec=float(host_dec) * u.deg, frame="icrs")
                    table.at[index, "host_galactic_b"] = float(host_coord.galactic.b.deg)
                except Exception:
                    pass
    return table, summary


def apply_redshift_filter(
    df: pd.DataFrame,
    redshift_range: tuple[float, float],
    bright_mag_threshold: float,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    min_z, max_z = redshift_range
    table = df.copy()

    source_redshift = pd.to_numeric(table.get("redshift"), errors="coerce")
    host_redshift = pd.to_numeric(table.get("host_redshift"), errors="coerce")
    effective_redshift = host_redshift.where(host_redshift.notna(), source_redshift)

    bright_mag = pd.to_numeric(table.get("discoverymag"), errors="coerce") <= bright_mag_threshold
    has_valid_redshift = effective_redshift.notna() & (effective_redshift >= min_z) & (effective_redshift <= max_z)
    known_high_z = effective_redshift.notna() & (effective_redshift > max_z)
    missing_redshift = effective_redshift.isna() & ~known_high_z
    valid_mask = (has_valid_redshift | (missing_redshift & bright_mag.fillna(False))) & ~known_high_z

    table["effective_redshift"] = effective_redshift
    table["redshift_filter_reason"] = np.where(
        has_valid_redshift,
        "redshift_in_range",
        np.where(missing_redshift & bright_mag.fillna(False), "bright_no_redshift", "filtered"),
    )
    return table.loc[valid_mask].copy()


def apply_galactic_latitude_filter(df: pd.DataFrame, min_galactic_latitude: float) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    table = df.copy()
    galactic_b_values = []
    for _, row in table.iterrows():
        try:
            coord = SkyCoord(
                ra=_to_float(row["ra_deg"]) * u.deg,
                dec=_to_float(row["dec_deg"]) * u.deg,
                frame="icrs",
            )
            galactic_b_values.append(float(coord.galactic.b.deg))
        except Exception:
            galactic_b_values.append(np.nan)
    table["source_galactic_b"] = galactic_b_values
    valid_mask = pd.to_numeric(table["source_galactic_b"], errors="coerce").abs() > float(min_galactic_latitude)
    return table.loc[valid_mask.fillna(False)].copy()


def final_summary(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {
            "row_count": 0,
            "host_redshift_available": 0,
            "median_host_redshift": None,
            "median_abs_galactic_latitude": None,
        }
    host_redshift = pd.to_numeric(df.get("host_redshift"), errors="coerce")
    source_galactic_b = pd.to_numeric(df.get("source_galactic_b"), errors="coerce")
    return {
        "row_count": int(len(df)),
        "host_redshift_available": int(host_redshift.notna().sum()),
        "median_host_redshift": float(host_redshift.dropna().median()) if host_redshift.notna().any() else None,
        "median_abs_galactic_latitude": float(source_galactic_b.abs().dropna().median())
        if source_galactic_b.notna().any()
        else None,
    }


def run_candidate_screen(
    raw_df: pd.DataFrame,
    config: dict[str, Any],
    disable_relaxed_fallback: bool = False,
) -> dict[str, Any]:
    working_df = ensure_required_columns(raw_df)
    working_df = process_data_types(working_df)
    after_time = apply_discovery_date_filter(working_df, int(config["RECENT_DISCOVERY_DAYS"]))

    if disable_relaxed_fallback:
        after_host, host_query_summary = enrich_host_information(after_time, config)
        relaxed_after_host = None
        relaxed_host_summary = None
    else:
        relaxed_after_time = apply_discovery_date_filter(working_df, DEFAULT_RELAXED_RECENT_DAYS)
        relaxed_after_host, relaxed_host_summary = enrich_host_information(relaxed_after_time, config)
        after_host = relaxed_after_host.loc[after_time.index].copy()
        host_query_summary = {
            "attempted": int(relaxed_host_summary["attempted"]),
            "resolved_redshift": int(relaxed_host_summary["resolved_redshift"]),
            "resolved_host": int(relaxed_host_summary["resolved_host"]),
            "scope_days": DEFAULT_RELAXED_RECENT_DAYS,
        }

    after_redshift = apply_redshift_filter(
        after_host,
        redshift_range=tuple(config["REDSHIFT_RANGE"]),
        bright_mag_threshold=float(config["BRIGHT_MAG_THRESHOLD"]),
    )
    after_galactic = apply_galactic_latitude_filter(after_redshift, float(config["MIN_GALACTIC_LATITUDE"]))

    filter_mode = "strict"
    relaxed_summary: dict[str, Any] | None = None
    final_df = after_galactic.copy()

    if final_df.empty and not disable_relaxed_fallback:
        relaxed_config = dict(config)
        relaxed_config["RECENT_DISCOVERY_DAYS"] = DEFAULT_RELAXED_RECENT_DAYS
        relaxed_config["REDSHIFT_RANGE"] = DEFAULT_RELAXED_REDSHIFT_RANGE
        if relaxed_after_host is None or relaxed_host_summary is None:
            relaxed_working_df = process_data_types(ensure_required_columns(raw_df))
            relaxed_after_time = apply_discovery_date_filter(relaxed_working_df, DEFAULT_RELAXED_RECENT_DAYS)
            relaxed_after_host, relaxed_host_summary = enrich_host_information(relaxed_after_time, relaxed_config)
        relaxed_after_redshift = apply_redshift_filter(
            relaxed_after_host,
            redshift_range=DEFAULT_RELAXED_REDSHIFT_RANGE,
            bright_mag_threshold=float(relaxed_config["BRIGHT_MAG_THRESHOLD"]),
        )
        relaxed_after_galactic = apply_galactic_latitude_filter(
            relaxed_after_redshift,
            float(relaxed_config["MIN_GALACTIC_LATITUDE"]),
        )
        relaxed_summary = {
            "enabled": True,
            "recent_discovery_days": DEFAULT_RELAXED_RECENT_DAYS,
            "redshift_range": list(DEFAULT_RELAXED_REDSHIFT_RANGE),
            "row_count": int(len(relaxed_after_galactic)),
            "host_query_attempted": int(relaxed_host_summary["attempted"]),
            "host_query_resolved_redshift": int(relaxed_host_summary["resolved_redshift"]),
        }
        if not relaxed_after_galactic.empty:
            final_df = relaxed_after_galactic.copy()
            final_df["_filter_mode"] = "relaxed"
            filter_mode = "relaxed"

    stage_counts = {
        "raw": int(len(raw_df)),
        "date_cut": int(len(after_time)),
        "host_enriched": int(len(after_host)),
        "redshift_cut": int(len(after_redshift)),
        "strict_final": int(len(after_galactic)),
        "returned_final": int(len(final_df)),
    }
    return {
        "working_df": working_df,
        "after_time": after_time,
        "after_host": after_host,
        "after_redshift": after_redshift,
        "after_galactic": after_galactic,
        "final_df": final_df,
        "filter_mode": filter_mode,
        "relaxed_fallback": relaxed_summary,
        "host_query_summary": host_query_summary,
        "stage_counts": stage_counts,
        "final_summary": final_summary(final_df),
    }
