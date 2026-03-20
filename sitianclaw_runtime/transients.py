from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astropy import units as u
from bs4 import BeautifulSoup

from .runtime import normalize_name
from .tns import (
    DEFAULT_HEADERS,
    _get_session,
    _object_slug,
    _parse_tns_object_page,
    fetch_tns_data_by_name,
    fetch_tns_data_from_web,
)

logger = logging.getLogger(__name__)


def resolve_target(name: str | None, ra: float | None, dec: float | None) -> dict[str, Any]:
    if ra is not None and dec is not None:
        return {
            "name": name or "custom-target",
            "ra": ra,
            "dec": dec,
            "tns_entry": None,
            "resolved_from": ["direct_input"],
        }
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


def filter_tns_dataframe(dataframe: pd.DataFrame | None, name: str | None, limit: int, days_back: int) -> pd.DataFrame:
    if dataframe is None or dataframe.empty:
        return pd.DataFrame()
    df = dataframe.copy()
    if "id" in df.columns:
        df["id"] = pd.to_numeric(df["id"], errors="coerce")
        df = df.sort_values("id", ascending=False, na_position="last")
    if "discoverydate" in df.columns and days_back > 0:
        discovery_dt = pd.to_datetime(df["discoverydate"], errors="coerce")
        cutoff = datetime.utcnow() - timedelta(days=days_back)
        df = df.loc[discovery_dt >= cutoff].copy()
    if name:
        target = normalize_name(name)
        mask = df["tns_name"].astype(str).map(normalize_name) == target
        filtered = df.loc[mask].copy()
        if not filtered.empty:
            return filtered.head(limit)
        fallback = _parse_tns_object_page(name)
        return fallback.head(limit) if not fallback.empty else pd.DataFrame()
    return df.head(limit).copy()


def _extract_table_rows(table: Any) -> list[dict[str, str]]:
    if table is None:
        return []
    header_row = next((tr for tr in table.find_all("tr") if tr.find_all("th")), None)
    if header_row is None:
        return []
    headers = [th.get_text(" ", strip=True) for th in header_row.find_all("th")]
    if not headers:
        return []
    rows: list[dict[str, str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < len(headers):
            continue
        values = [cell.get_text(" ", strip=True) for cell in cells[: len(headers)]]
        rows.append({headers[idx]: values[idx] for idx in range(len(headers))})
    return rows


def fetch_tns_photometry_by_name(name: str) -> pd.DataFrame:
    slug = _object_slug(name)
    if not slug:
        return pd.DataFrame()
    session = _get_session()
    response = session.get(f"https://www.wis-tns.org/object/{slug}", headers=DEFAULT_HEADERS, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    rows: list[dict[str, Any]] = []
    for table in soup.find_all("table", class_="photometry-results-table"):
        for row in _extract_table_rows(table):
            jd_value = pd.to_numeric(row.get("JD"), errors="coerce")
            mag_value = pd.to_numeric(row.get("Mag. / Flux"), errors="coerce")
            err_value = pd.to_numeric(row.get("Err"), errors="coerce")
            filter_name = row.get("Filter")
            remarks = row.get("Remarks")
            rows.append(
                {
                    "source": "TNS",
                    "jd": float(jd_value) if pd.notna(jd_value) else None,
                    "mjd": float(jd_value - 2400000.5) if pd.notna(jd_value) else None,
                    "mag": float(mag_value) if pd.notna(mag_value) else None,
                    "magerr": float(err_value) if pd.notna(err_value) else None,
                    "filter": filter_name,
                    "instrument": row.get("Tel / Inst"),
                    "obsdate": row.get("Obs-date"),
                    "remarks": remarks,
                    "is_detection": bool(pd.notna(mag_value) and (not remarks or "non detection" not in remarks.lower())),
                }
            )
    table = pd.DataFrame(rows)
    if not table.empty and "jd" in table.columns:
        table = table.sort_values("jd").reset_index(drop=True)
    return table


def query_alerce_by_coordinates(
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float = 5.0,
    days_back: int = 30,
) -> pd.DataFrame:
    session = requests.Session()
    session.headers.update({"User-Agent": "SitianClaw/1.0", "Accept": "application/json"})
    url = "https://api.alerce.online/ztf/v1/objects"
    params = {"ra": ra_deg, "dec": dec_deg, "radius": radius_arcsec, "page_size": 50, "format": "json"}
    try:
        response = session.get(url, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.debug("ALeRCE object search failed: %s", exc)
        return pd.DataFrame()

    if isinstance(payload, dict):
        objects = payload.get("results") or payload.get("items") or payload.get("data") or []
        if "oid" in payload:
            objects = [payload]
    elif isinstance(payload, list):
        objects = payload
    else:
        objects = []

    all_rows: list[pd.DataFrame] = []
    for obj in objects:
        oid = obj.get("oid") or obj.get("objectId")
        if not oid:
            continue
        try:
            lc_response = session.get(f"https://api.alerce.online/ztf/v1/objects/{oid}/lightcurve", timeout=30)
            lc_response.raise_for_status()
            lc_payload = lc_response.json()
        except Exception as exc:
            logger.debug("ALeRCE lightcurve fetch failed for %s: %s", oid, exc)
            continue
        detections = lc_payload.get("detections") or []
        if not detections:
            continue
        frame = pd.DataFrame(detections)
        if frame.empty:
            continue
        if "mjd" in frame.columns and days_back > 0:
            current_mjd = Time(datetime.utcnow()).mjd
            cutoff_mjd = current_mjd - days_back
            frame = frame.loc[pd.to_numeric(frame["mjd"], errors="coerce") >= cutoff_mjd].copy()
        if frame.empty:
            continue
        frame["source"] = "ALeRCE"
        frame["ztf_id"] = oid
        frame["ra"] = obj.get("meanra") or obj.get("ra", ra_deg)
        frame["dec"] = obj.get("meandec") or obj.get("dec", dec_deg)
        frame["mag"] = pd.to_numeric(frame.get("magpsf"), errors="coerce")
        frame["magerr"] = pd.to_numeric(frame.get("sigmapsf"), errors="coerce")
        frame["filter"] = frame.get("fid").map({1: "g-ZTF", 2: "r-ZTF", 3: "i-ZTF"}) if "fid" in frame.columns else None
        frame["is_detection"] = frame["mag"].notna()
        if "mjd" in frame.columns:
            frame["jd"] = pd.to_numeric(frame["mjd"], errors="coerce") + 2400000.5
        all_rows.append(frame)
    if not all_rows:
        return pd.DataFrame()
    merged = pd.concat(all_rows, ignore_index=True, sort=False)
    if "mjd" in merged.columns:
        merged = merged.sort_values("mjd").reset_index(drop=True)
    return merged


def broker_summary(dataframe: pd.DataFrame | None) -> dict[str, Any]:
    if dataframe is None or dataframe.empty:
        return {"rows": 0, "filters": [], "mjd_min": None, "mjd_max": None}
    summary: dict[str, Any] = {"rows": int(len(dataframe))}
    if "filter" in dataframe.columns:
        summary["filters"] = sorted({str(item) for item in dataframe["filter"].dropna().tolist()})
    if "mjd" in dataframe.columns:
        mjd = pd.to_numeric(dataframe["mjd"], errors="coerce").dropna()
        summary["mjd_min"] = float(mjd.min()) if not mjd.empty else None
        summary["mjd_max"] = float(mjd.max()) if not mjd.empty else None
    return summary


def plot_lightcurve(
    target_name: str,
    frames: list[pd.DataFrame],
    output_path: Any,
    title_prefix: str = "Transient Light Curve",
) -> Any:
    valid_frames = [frame.copy() for frame in frames if frame is not None and not frame.empty]
    if not valid_frames:
        return None
    merged = pd.concat(valid_frames, ignore_index=True, sort=False)
    if merged.empty:
        return None
    if "mjd" not in merged.columns:
        merged["mjd"] = pd.to_numeric(merged.get("jd"), errors="coerce") - 2400000.5
    merged["mjd"] = pd.to_numeric(merged["mjd"], errors="coerce")
    merged["mag"] = pd.to_numeric(merged.get("mag"), errors="coerce")
    merged["magerr"] = pd.to_numeric(merged.get("magerr"), errors="coerce")
    merged = merged.dropna(subset=["mjd", "mag"])
    if merged.empty:
        return None

    palette = {
        "g-ZTF": "#1f77b4",
        "r-ZTF": "#d62728",
        "i-ZTF": "#9467bd",
        "ZTF-g": "#1f77b4",
        "ZTF-r": "#d62728",
        "ZTF-i": "#9467bd",
        "Clear-": "#7f7f7f",
        "o": "#ff7f0e",
        "c": "#2ca02c",
    }
    fig, ax = plt.subplots(figsize=(9, 5))
    grouped = merged.groupby(merged["filter"].fillna("unknown").astype(str))
    for label, group in grouped:
        color = palette.get(label, None)
        ax.errorbar(
            group["mjd"],
            group["mag"],
            yerr=group["magerr"] if group["magerr"].notna().any() else None,
            fmt="o",
            ms=4.5,
            elinewidth=1.0,
            capsize=2,
            label=label,
            color=color,
            alpha=0.85,
        )
    ax.invert_yaxis()
    ax.set_xlabel("MJD")
    ax.set_ylabel("Magnitude")
    ax.set_title(f"{title_prefix}: {target_name}")
    ax.grid(alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def plot_tns_sky(dataframe: pd.DataFrame, output_path: Any, title: str) -> Any:
    if dataframe.empty or "ra_deg" not in dataframe.columns or "dec_deg" not in dataframe.columns:
        return None
    plot_df = dataframe.copy()
    plot_df["ra_deg"] = pd.to_numeric(plot_df["ra_deg"], errors="coerce")
    plot_df["dec_deg"] = pd.to_numeric(plot_df["dec_deg"], errors="coerce")
    plot_df["discoverymag"] = pd.to_numeric(plot_df.get("discoverymag"), errors="coerce")
    plot_df = plot_df.dropna(subset=["ra_deg", "dec_deg"])
    if plot_df.empty:
        return None

    fig, ax = plt.subplots(figsize=(9, 5.5))
    color_values = plot_df["discoverymag"] if plot_df["discoverymag"].notna().any() else "#1f77b4"
    scatter = ax.scatter(
        plot_df["ra_deg"],
        plot_df["dec_deg"],
        c=color_values,
        cmap="viridis_r" if plot_df["discoverymag"].notna().any() else None,
        s=60,
        edgecolor="black",
        linewidth=0.3,
    )
    ax.set_title(title)
    ax.set_xlabel("RA (deg)")
    ax.set_ylabel("Dec (deg)")
    ax.grid(alpha=0.25)
    if plot_df["discoverymag"].notna().any():
        colorbar = fig.colorbar(scatter, ax=ax)
        colorbar.set_label("Discovery mag")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path


def fallback_target_row(target_name: str, ra: float | None, dec: float | None, redshift: Any) -> pd.DataFrame:
    if ra is None or dec is None:
        return pd.DataFrame()
    return pd.DataFrame([{"tns_name": target_name, "ra_deg": ra, "dec_deg": dec, "redshift": redshift}])
