from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

DEFAULT_STATUS_URL = "https://ztfweb.ipac.caltech.edu/cgi-bin/getForcedPhotometryRequests.cgi"


def portable_cache_dir(repo_root: Path, cache_dir: str | Path | None = None) -> Path:
    base = Path(cache_dir) if cache_dir is not None else repo_root / "data" / "ztf_forced_cache"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Failed to load %s: %s", path, exc)
        return None


def _coerce_record(request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = dict(payload)
    record.setdefault("request_id", request_id)
    return record


def load_request_records(cache_dir: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for filename in ["all_ztf_requests.json", "completed_requests.json", "pending_requests.json"]:
        payload = _load_json(cache_dir / filename)
        if not isinstance(payload, dict):
            continue
        for request_id, record in payload.items():
            if not isinstance(record, dict):
                continue
            merged = records.get(request_id, {}).copy()
            merged.update(_coerce_record(request_id, record))
            records[request_id] = merged
    return records


def write_request_records(cache_dir: Path, records: dict[str, dict[str, Any]]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    ordered = dict(
        sorted(
            records.items(),
            key=lambda item: str(item[1].get("submit_time") or item[0]),
            reverse=True,
        )
    )
    (cache_dir / "all_ztf_requests.json").write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    pending_statuses = {"submitted", "processing", "unknown"}
    pending = {request_id: record for request_id, record in ordered.items() if str(record.get("status") or "").lower() in pending_statuses}
    completed = {request_id: record for request_id, record in ordered.items() if request_id not in pending}
    (cache_dir / "pending_requests.json").write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
    (cache_dir / "completed_requests.json").write_text(json.dumps(completed, ensure_ascii=False, indent=2), encoding="utf-8")


def find_requests_by_name(records: dict[str, dict[str, Any]], source_name: str) -> list[dict[str, Any]]:
    target = str(source_name or "").strip().lower()
    matched = [record for record in records.values() if str(record.get("source_name") or "").strip().lower() == target]
    matched.sort(key=lambda item: str(item.get("submit_time") or item.get("request_id") or ""), reverse=True)
    return matched


def find_requests_by_id(records: dict[str, dict[str, Any]], request_id: str | None) -> list[dict[str, Any]]:
    if not request_id:
        return []
    record = records.get(request_id)
    return [record] if record else []


def status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "unknown").lower()
        counts[status] = counts.get(status, 0) + 1
    return counts


def _parse_submit_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _status_snippet(page_text: str, record: dict[str, Any]) -> str | None:
    lower_text = page_text.lower()
    request_id = str(record.get("request_id") or "").lower()
    if request_id and request_id in lower_text:
        idx = lower_text.find(request_id)
        return lower_text[max(0, idx - 200) : idx + 800]
    ra = record.get("ra")
    dec = record.get("dec")
    try:
        ra_formats = [f"{float(ra):.{digits}f}" for digits in [6, 5, 4, 3, 2]]
        dec_formats = [f"{float(dec):.{digits}f}" for digits in [6, 5, 4, 3, 2]]
    except Exception:
        return None
    for ra_text in ra_formats:
        for dec_text in dec_formats:
            idx = lower_text.find(ra_text.lower())
            if idx >= 0 and dec_text.lower() in lower_text[max(0, idx - 120) : idx + 220]:
                return lower_text[max(0, idx - 200) : idx + 800]
    return None


def _infer_remote_status(page_text: str, record: dict[str, Any]) -> str | None:
    snippet = _status_snippet(page_text, record)
    if not snippet:
        return None
    if "completed" in snippet or "done" in snippet:
        return "completed"
    if "processing" in snippet or "running" in snippet:
        return "processing"
    if "failed" in snippet or "error" in snippet:
        return "failed"
    return "submitted"


def refresh_request_statuses(
    records: dict[str, dict[str, Any]],
    cache_dir: Path,
    request_id: str | None = None,
    source_name: str | None = None,
    mark_timeout_hours: float = 48.0,
) -> dict[str, Any]:
    selected = find_requests_by_id(records, request_id)
    if not selected and source_name:
        selected = find_requests_by_name(records, source_name)
    if not selected:
        selected = [
            record
            for record in records.values()
            if str(record.get("status") or "").lower() in {"submitted", "processing", "unknown"}
        ]

    email = os.getenv("ZTF_EMAIL", "").strip()
    password = os.getenv("ZTF_PASSWORD", "").strip()
    auth_user = os.getenv("ZTF_FP_AUTH_USER", "").strip()
    auth_pass = os.getenv("ZTF_FP_AUTH_PASS", "").strip()
    if not all([email, password, auth_user, auth_pass]):
        return {
            "supported": False,
            "reason": "Set ZTF_EMAIL, ZTF_PASSWORD, ZTF_FP_AUTH_USER, and ZTF_FP_AUTH_PASS to enable refresh.",
            "selected_count": len(selected),
            "updates": {},
        }

    try:
        response = requests.post(
            DEFAULT_STATUS_URL,
            data={"email": email, "userpass": password},
            auth=(auth_user, auth_pass),
            timeout=30,
        )
        response.raise_for_status()
        page_text = response.text
    except Exception as exc:
        return {
            "supported": True,
            "ok": False,
            "reason": f"Remote status query failed: {exc}",
            "selected_count": len(selected),
            "updates": {},
        }

    now = datetime.now(timezone.utc)
    updates: dict[str, dict[str, Any]] = {}
    for record in selected:
        request_key = str(record.get("request_id") or "")
        current_status = str(record.get("status") or "unknown").lower()
        new_status = _infer_remote_status(page_text, record)
        if new_status is None:
            submit_time = _parse_submit_time(record.get("submit_time"))
            if submit_time is not None and now - submit_time >= timedelta(hours=float(mark_timeout_hours)):
                new_status = "timeout"
        if new_status and new_status != current_status:
            record["status"] = new_status
            record["last_status_change"] = now.isoformat()
            if new_status in {"completed", "failed", "timeout"} and not record.get("complete_time"):
                record["complete_time"] = now.isoformat()
            updates[request_key] = {"from": current_status, "to": new_status}
            records[request_key] = record

    if updates:
        write_request_records(cache_dir, records)

    return {
        "supported": True,
        "ok": True,
        "selected_count": len(selected),
        "updates": updates,
    }


def _normalize_filter(raw_filter: Any) -> str:
    text = str(raw_filter or "").lower().replace("ztf_", "").replace("ztf-", "")
    mapping = {"g": "ZTF-g", "r": "ZTF-r", "i": "ZTF-i", "zg": "ZTF-g", "zr": "ZTF-r", "zi": "ZTF-i"}
    return mapping.get(text, f"ZTF-{text}" if text else "ZTF-r")


def read_forced_photometry_file(file_path: str | Path) -> tuple[pd.DataFrame | None, str]:
    path = Path(file_path)
    if not path.exists():
        return None, ""
    try:
        data = pd.read_csv(path, comment="#", sep=r"\s+", header=None, engine="python")
    except Exception as exc:
        logger.debug("Failed to read forced-photometry file %s: %s", path, exc)
        return None, ""

    columns_new = [
        "sindex",
        "field",
        "ccdid",
        "qid",
        "filter",
        "pid",
        "infobitssci",
        "sciinpseeing",
        "scibckgnd",
        "scisigpix",
        "zpmaginpsci",
        "zpmaginpsciunc",
        "zpmaginpscirms",
        "clrcoeff",
        "clrcoeffunc",
        "ncalmatches",
        "exptime",
        "adpctdif1",
        "adpctdif2",
        "diffmaglim",
        "zpdiff",
        "programid",
        "jd",
        "rfid",
        "diffimgstatus",
        "forcediffimflux",
        "forcediffimfluxunc",
        "forcediffimsnr",
        "forcediffimchisq",
        "forcediffimfluxap",
        "forcediffimfluxuncap",
        "forcediffimsnrap",
        "aperturecorr",
        "dnearestrefsrc",
        "nearestrefmag",
        "nearestrefmagunc",
        "nearestrefchi",
        "nearestrefsharp",
        "refjdstart",
        "refjdend",
        "procstatus",
    ]
    columns_old = [
        "sindex",
        "field",
        "ccdid",
        "qid",
        "filter",
        "pid",
        "infobitssci",
        "sciinpseeing",
        "scibckgnd",
        "scisigpix",
        "zpmaginpsci",
        "zpmaginpsciunc",
        "zpmaginpscirms",
        "clrcoeff",
        "clrcoeffunc",
        "ncalmatches",
        "exptime",
        "adpctdif1",
        "adpctdif2",
        "diffmaglim",
        "zpdiff",
        "programid",
        "jd",
        "rfid",
        "forcediffimflux",
        "forcediffimfluxunc",
        "forcediffimsnr",
        "forcediffimchisq",
        "forcediffimfluxap",
        "forcediffimfluxuncap",
        "forcediffimsnrap",
        "aperturecorr",
        "dnearestrefsrc",
        "nearestrefmag",
        "nearestrefmagunc",
        "nearestrefchi",
        "nearestrefsharp",
        "refjdstart",
        "refjdend",
        "procstatus",
    ]
    if len(data.columns) == len(columns_new):
        data.columns = columns_new
    elif len(data.columns) == len(columns_old):
        data.columns = columns_old
    else:
        logger.debug("Unexpected forced-photometry column count: %s", len(data.columns))
        return None, ""

    numeric_columns = [
        "jd",
        "forcediffimflux",
        "forcediffimfluxunc",
        "forcediffimsnr",
        "zpdiff",
        "diffmaglim",
    ]
    for column in numeric_columns:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")

    photometry = pd.DataFrame()
    photometry["mjd"] = data["jd"] - 2400000.5
    photometry["jd"] = data["jd"]
    photometry["filter"] = data["filter"].apply(_normalize_filter)
    photometry["filtercode"] = photometry["filter"]

    valid_flux = pd.to_numeric(data["forcediffimflux"], errors="coerce") > 0
    photometry.loc[valid_flux, "mag"] = data.loc[valid_flux, "zpdiff"] - 2.5 * np.log10(data.loc[valid_flux, "forcediffimflux"])
    photometry.loc[valid_flux, "magerr"] = (
        2.5 / np.log(10) * data.loc[valid_flux, "forcediffimfluxunc"] / data.loc[valid_flux, "forcediffimflux"]
    )
    photometry.loc[~valid_flux, "mag"] = data.loc[~valid_flux, "diffmaglim"]
    photometry.loc[~valid_flux, "magerr"] = 99.0
    photometry["snr"] = data["forcediffimsnr"]
    photometry["is_detection"] = photometry["snr"] > 3.0
    photometry["data_source"] = "forced_photometry"
    photometry["is_forced_photometry"] = True
    photometry = photometry[photometry["mjd"].notna()].copy()
    photometry = photometry.sort_values("mjd").reset_index(drop=True)
    return photometry, str(path)


def resolve_forced_photometry_path(
    cache_dir: Path,
    source_name: str | None = None,
    explicit_file: str | Path | None = None,
    records: dict[str, dict[str, Any]] | None = None,
) -> Path | None:
    if explicit_file is not None:
        path = Path(explicit_file)
        return path if path.exists() else None

    if not source_name:
        return None
    normalized_dir = str(source_name).replace(" ", "_")
    direct_path = cache_dir / normalized_dir / "ztf_forced_photometry.txt"
    if direct_path.exists():
        return direct_path

    available = records or load_request_records(cache_dir)
    for record in find_requests_by_name(available, source_name):
        data_file = record.get("data_file")
        if not data_file:
            continue
        candidate = cache_dir / str(data_file)
        if candidate.exists():
            return candidate
    return None
