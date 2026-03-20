from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import numpy as np
import pandas as pd
import requests
from astropy import units as u
from astropy.coordinates import SkyCoord
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_TNS_URL = (
    "https://www.wis-tns.org/search?reported_within_last_value=3&reported_within_last_units=days"
    "&classified_sne=0&num_page=500"
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}

TNS_COLUMNS = [
    "id",
    "tns_name",
    "type",
    "ra",
    "dec",
    "redshift",
    "internal_name",
    "discoverymag",
    "discoverydate",
    "discfilt",
    "source_group_name",
]

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        session = requests.Session()
        adapter = HTTPAdapter(
            max_retries=Retry(total=4, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _session = session
    return _session


def _convert_single_coordinate(ra_str: object, dec_str: object) -> tuple[float, float]:
    try:
        if ra_str in ["N/A", "", None] or dec_str in ["N/A", "", None]:
            return np.nan, np.nan
        if isinstance(ra_str, str) and ":" in ra_str and isinstance(dec_str, str):
            coord = SkyCoord(ra=ra_str, dec=dec_str, unit=(u.hourangle, u.deg))
            return float(coord.ra.deg), float(coord.dec.deg)
        return float(ra_str), float(dec_str)
    except Exception:
        return np.nan, np.nan


def _convert_tns_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    coordinates = [_convert_single_coordinate(ra, dec) for ra, dec in zip(df["ra"], df["dec"])]
    df["ra_deg"] = [item[0] for item in coordinates]
    df["dec_deg"] = [item[1] for item in coordinates]
    return df


def _build_tns_url(name: str | None = None) -> str:
    if name:
        parsed = urlparse("https://www.wis-tns.org/search?name_like=0")
        query = parse_qs(parsed.query)
        query["name"] = [name]
        return urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query, doseq=True), parsed.fragment)
        )
    return DEFAULT_TNS_URL


def _object_slug(name: str) -> str:
    slug = str(name or "").strip()
    slug = re.sub(r"^(SN|AT)\s+", "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"\s+", "", slug)
    return slug


def _first_data_row(table: BeautifulSoup) -> dict[str, str]:
    header_row = next((tr for tr in table.find_all("tr") if tr.find_all("th")), None)
    if header_row is None:
        return {}
    headers = [cell.get_text(" ", strip=True) for cell in header_row.find_all("th")]
    if not headers:
        return {}
    for tr in table.find_all("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) >= len(headers):
            values = [cell.get_text(" ", strip=True) for cell in cells[: len(headers)]]
            return {headers[idx]: values[idx] for idx in range(len(headers))}
    return {}


def _parse_tns_object_page(name: str) -> pd.DataFrame:
    slug = _object_slug(name)
    if not slug:
        return pd.DataFrame(columns=TNS_COLUMNS + ["ra_deg", "dec_deg", "data_source"])

    url = f"https://www.wis-tns.org/object/{slug}"
    session = _get_session()
    response = session.get(url, headers=DEFAULT_HEADERS, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")

    report_table = None
    class_table = None
    for table in soup.find_all("table"):
        classes = table.get("class") or []
        if "atreps-results-table" in classes and report_table is None:
            report_table = table
        if "class-results-table" in classes and class_table is None:
            table_text = table.get_text(" ", strip=True)
            if "Classification" in table_text and "Redshift" in table_text:
                class_table = table

    report_row = _first_data_row(report_table) if report_table is not None else {}
    class_row = _first_data_row(class_table) if class_table is not None else {}
    if not report_row and not class_row:
        return pd.DataFrame(columns=TNS_COLUMNS + ["ra_deg", "dec_deg", "data_source"])

    payload = {
        "id": np.nan,
        "tns_name": name,
        "type": class_row.get("Classification", report_row.get("AT Type", "")),
        "ra": report_row.get("RA", ""),
        "dec": report_row.get("DEC", ""),
        "redshift": class_row.get("Redshift", ""),
        "internal_name": report_row.get("Internal name", ""),
        "discoverymag": report_row.get("Discovery Mag.", ""),
        "discoverydate": report_row.get("Discovery date (UT)", ""),
        "discfilt": report_row.get("Filter", ""),
        "source_group_name": report_row.get("Reporting group", ""),
    }
    table = pd.DataFrame([payload])
    table = _convert_tns_coordinates(table)
    table["data_source"] = "TNS"
    if "discoverymag" in table.columns:
        extracted = table["discoverymag"].astype(str).str.extract(r"(\d+\.?\d*)")[0]
        table["discoverymag"] = pd.to_numeric(extracted, errors="coerce")
    return table


def fetch_tns_data_from_url(target_url: str) -> pd.DataFrame:
    session = _get_session()
    response = session.get(target_url, headers=DEFAULT_HEADERS, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")

    rows = []
    for tr in soup.find_all("tr"):
        class_list = tr.get("class")
        if isinstance(class_list, list) and any("public" in item for item in class_list):
            rows.append(tr)
        elif isinstance(class_list, str) and "public" in class_list:
            rows.append(tr)

    data = {column: [] for column in TNS_COLUMNS}
    for row in rows:
        cells = row.find_all("td")
        if len(cells) <= 23:
            continue
        tns_id = cells[0].get_text(strip=True)
        if not tns_id.isdigit():
            continue
        data["id"].append(tns_id)
        data["tns_name"].append(cells[1].get_text(strip=True))
        data["type"].append(cells[6].get_text(strip=True) if len(cells) > 6 else "")
        data["ra"].append(cells[4].get_text(strip=True) if len(cells) > 4 else "")
        data["dec"].append(cells[5].get_text(strip=True) if len(cells) > 5 else "")
        data["redshift"].append(cells[7].get_text(strip=True) if len(cells) > 7 else "")
        data["internal_name"].append(cells[14].get_text(strip=True) if len(cells) > 14 else "")
        data["discoverymag"].append(cells[21].get_text(strip=True) if len(cells) > 21 else "")
        data["discfilt"].append(cells[22].get_text(strip=True) if len(cells) > 22 else "")
        data["discoverydate"].append(cells[23].get_text(strip=True) if len(cells) > 23 else "")
        data["source_group_name"].append(cells[10].get_text(strip=True) if len(cells) > 10 else "")

    table = pd.DataFrame(data)
    if not table.empty:
        table["id"] = pd.to_numeric(table["id"], errors="coerce")
        table = table.sort_values("id", ascending=False).reset_index(drop=True)
        table = _convert_tns_coordinates(table)
        table["data_source"] = "TNS"
        if "discoverymag" in table.columns:
            extracted = table["discoverymag"].astype(str).str.extract(r"(\d+\.?\d*)")[0]
            table["discoverymag"] = pd.to_numeric(extracted, errors="coerce")
    return table


def fetch_tns_data_from_web() -> pd.DataFrame:
    return fetch_tns_data_from_url(_build_tns_url())


def fetch_tns_data_by_name(name: str) -> pd.DataFrame:
    try:
        table = fetch_tns_data_from_url(_build_tns_url(name=name))
        if not table.empty:
            return table
    except Exception as exc:
        logger.warning("TNS search lookup failed for %s: %s", name, exc)

    try:
        return _parse_tns_object_page(name)
    except Exception as exc:
        logger.warning("TNS object-page lookup failed for %s: %s", name, exc)
        return pd.DataFrame(columns=TNS_COLUMNS + ["ra_deg", "dec_deg", "data_source"])


def resolve_tns_target(name: str) -> dict[str, object] | None:
    try:
        table = fetch_tns_data_by_name(name)
    except Exception as exc:
        logger.warning("TNS name lookup failed for %s: %s", name, exc)
        return None
    if table.empty:
        return None
    normalized = re.sub(r"[\s_]+", "", name).lower()
    for _, row in table.iterrows():
        candidate_name = re.sub(r"[\s_]+", "", str(row.get("tns_name") or "")).lower()
        if candidate_name == normalized:
            return row.to_dict()
    return table.iloc[0].to_dict()
