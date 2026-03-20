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
from astropy.time import Time

logger = logging.getLogger(__name__)

DEFAULT_SUBMIT_URL = "https://ztfweb.ipac.caltech.edu/cgi-bin/requestForcedPhotometry.cgi"
DEFAULT_STATUS_URL = "https://ztfweb.ipac.caltech.edu/cgi-bin/getForcedPhotometryRequests.cgi"
ZTF_START_JD = 2458194.5


def portable_cache_dir(repo_root: Path, cache_dir: str | Path | None = None) -> Path:
    base = Path(cache_dir) if cache_dir is not None else repo_root / "data" / "ztf_forced_cache"
    base.mkdir(parents=True, exist_ok=True)
    return base


def credentials_status() -> dict[str, Any]:
    required = {
        "ZTF_EMAIL": bool(os.getenv("ZTF_EMAIL", "").strip()),
        "ZTF_PASSWORD": bool(os.getenv("ZTF_PASSWORD", "").strip()),
        "ZTF_FP_AUTH_USER": bool(os.getenv("ZTF_FP_AUTH_USER", "").strip()),
        "ZTF_FP_AUTH_PASS": bool(os.getenv("ZTF_FP_AUTH_PASS", "").strip()),
    }
    return {
        "required": required,
        "ready": all(required.values()),
    }


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


def _now_jd() -> float:
    now = Time.now()
    try:
        return float(now.jd)
    except (TypeError, ValueError):
        return float(now.jd.value)


def normalize_submission_window(
    jd_start: float | None = None,
    jd_end: float | None = None,
    use_conservative_window: bool = True,
    max_range_days: float = 60.0,
) -> dict[str, Any]:
    current_jd = _now_jd()
    used_default_window = bool(use_conservative_window or jd_start is None or jd_end is None)
    if used_default_window:
        jd_end = current_jd
        jd_start = max(jd_end - 2.0, ZTF_START_JD)
    else:
        jd_start = max(float(jd_start), ZTF_START_JD)
        jd_end = min(float(jd_end), current_jd)
        time_range = jd_end - jd_start
        if time_range <= 0:
            raise ValueError(f"Invalid time range after clipping: {time_range:.3f} days.")
        if time_range > max_range_days:
            jd_start = jd_end - max_range_days
    return {
        "jd_start": float(jd_start),
        "jd_end": float(jd_end),
        "used_default_window": used_default_window,
        "span_days": float(jd_end - jd_start),
    }


def latest_matching_jd_end(
    records: dict[str, dict[str, Any]],
    source_name: str,
    ra: float,
    dec: float,
) -> tuple[float | None, str | None]:
    target_name = str(source_name or "").strip().lower()
    latest_jd_end: float | None = None
    latest_request_id: str | None = None
    for record in records.values():
        if bool(record.get("dry_run")):
            continue
        if str(record.get("source_name") or "").strip().lower() != target_name:
            continue
        try:
            if abs(float(record.get("ra")) - float(ra)) >= 1e-3 or abs(float(record.get("dec")) - float(dec)) >= 1e-3:
                continue
            jd_end = float(record.get("jd_end") or 0.0)
        except Exception:
            continue
        if jd_end > 0 and (latest_jd_end is None or jd_end > latest_jd_end):
            latest_jd_end = jd_end
            latest_request_id = str(record.get("request_id") or "") or None
    return latest_jd_end, latest_request_id


def incremental_submission_window(
    records: dict[str, dict[str, Any]],
    source_name: str,
    ra: float,
    dec: float,
    overlap_days: float = 0.02,
    min_window_days: float = 0.01,
) -> dict[str, Any]:
    current_jd = _now_jd()
    last_end, parent_request_id = latest_matching_jd_end(records, source_name=source_name, ra=ra, dec=dec)
    if last_end is None or last_end <= 0:
        jd_start = max(current_jd - 2.0, ZTF_START_JD)
    else:
        jd_start = max(last_end - overlap_days, ZTF_START_JD)
    jd_end = current_jd
    span_days = float(jd_end - jd_start)
    if span_days < min_window_days:
        raise ValueError(f"Incremental window too small: {span_days:.5f} days.")
    return {
        "jd_start": float(jd_start),
        "jd_end": float(jd_end),
        "span_days": span_days,
        "parent_request_id": parent_request_id,
        "used_fallback_window": last_end is None or last_end <= 0,
    }


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


def _html_submission_acknowledged(html_text: str, ra: float | None = None, dec: float | None = None) -> bool:
    try:
        lowered = str(html_text or "").lower()
        plain = lowered.replace("\n", " ")
        patterns = [
            "your request has been submitted",
            "request has been submitted",
            "your job has been submitted",
            "successfully submitted",
            "has been submitted",
            "is now in the queue",
            "queued",
            "thank you",
        ]
        if any(pattern in plain for pattern in patterns):
            return True
        if ra is not None and dec is not None and "<table" in lowered and "<td>" in lowered:
            ra_formats = [f"{float(ra):.{digits}f}" for digits in [6, 5, 4, 3]]
            dec_formats = [f"{float(dec):.{digits}f}" for digits in [6, 5, 4, 3]]
            return any(ra_text in html_text for ra_text in ra_formats) and any(dec_text in html_text for dec_text in dec_formats)
    except Exception:
        return False
    return False


def _build_request_id(source_name: str, ra: float, dec: float, request_type: str) -> str:
    submit_timestamp = int(Time.now().unix)
    prefix = "ztf_normal"
    return f"{prefix}_{source_name}_{ra:.6f}_{dec:.6f}_{submit_timestamp}"


def submit_forced_photometry(
    records: dict[str, dict[str, Any]],
    cache_dir: Path,
    source_name: str,
    ra: float,
    dec: float,
    jd_start: float | None = None,
    jd_end: float | None = None,
    incremental: bool = False,
    dry_run: bool = False,
    overlap_days: float = 0.02,
    min_window_days: float = 0.01,
) -> dict[str, Any]:
    if incremental:
        window = incremental_submission_window(
            records,
            source_name=source_name,
            ra=ra,
            dec=dec,
            overlap_days=overlap_days,
            min_window_days=min_window_days,
        )
        request_type = "incremental"
        parent_request_id = window.get("parent_request_id")
    else:
        window = normalize_submission_window(jd_start=jd_start, jd_end=jd_end, use_conservative_window=jd_start is None or jd_end is None)
        request_type = "initial"
        parent_request_id = None

    for existing in records.values():
        try:
            same_coords = abs(float(existing.get("ra")) - float(ra)) < 1e-3 and abs(float(existing.get("dec")) - float(dec)) < 1e-3
        except Exception:
            same_coords = False
        if same_coords and str(existing.get("status") or "").lower() in {"submitted", "processing", "unknown"} and not bool(existing.get("dry_run")):
            return {
                "ok": True,
                "duplicate_pending": True,
                "request_id": existing.get("request_id"),
                "record": existing,
                "dry_run": dry_run,
                "request_type": request_type,
                "window": window,
            }

    request_id = _build_request_id(source_name=source_name, ra=ra, dec=dec, request_type=request_type)
    submit_time = datetime.now(timezone.utc).isoformat()
    request_record = {
        "request_id": request_id,
        "source_name": source_name,
        "ra": float(ra),
        "dec": float(dec),
        "jd_start": float(window["jd_start"]),
        "jd_end": float(window["jd_end"]),
        "status": "dry_run" if dry_run else "submitted",
        "submit_time": submit_time,
        "origin": "api",
        "data_points": 0,
        "request_type": request_type,
        "parent_request_id": parent_request_id,
        "dry_run": bool(dry_run),
    }
    form_data = {
        "ra": f"{float(ra):.6f}",
        "dec": f"{float(dec):.6f}",
        "jdstart": f"{float(window['jd_start']):.5f}",
        "jdend": f"{float(window['jd_end']):.5f}",
        "email": os.getenv("ZTF_EMAIL", "").strip(),
        "userpass": os.getenv("ZTF_PASSWORD", "").strip(),
    }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "request_id": request_id,
            "record": request_record,
            "request_type": request_type,
            "window": window,
            "form_preview": form_data,
        }

    creds = credentials_status()
    if not creds["ready"]:
        return {
            "ok": False,
            "dry_run": False,
            "reason": "Missing required ZTF environment variables.",
            "credentials": creds,
            "request_type": request_type,
            "window": window,
        }

    try:
        response = requests.post(
            DEFAULT_SUBMIT_URL,
            auth=(os.getenv("ZTF_FP_AUTH_USER", "").strip(), os.getenv("ZTF_FP_AUTH_PASS", "").strip()),
            data=form_data,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            timeout=(10, 20),
        )
    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "dry_run": False,
            "reason": "ZTF submission timed out.",
            "request_type": request_type,
            "window": window,
        }
    except requests.exceptions.RequestException as exc:
        return {
            "ok": False,
            "dry_run": False,
            "reason": f"ZTF submission network error: {exc}",
            "request_type": request_type,
            "window": window,
        }

    response_excerpt = response.text[:600]
    lowered = response.text.lower()
    if response.status_code != 200:
        return {
            "ok": False,
            "dry_run": False,
            "reason": f"HTTP {response.status_code}",
            "response_excerpt": response_excerpt,
            "request_type": request_type,
            "window": window,
        }
    if "error" in lowered or "invalid" in lowered:
        return {
            "ok": False,
            "dry_run": False,
            "reason": "Remote service rejected the submission.",
            "response_excerpt": response_excerpt,
            "request_type": request_type,
            "window": window,
        }

    acknowledged = _html_submission_acknowledged(response.text, ra=ra, dec=dec)
    request_record["status"] = "submitted" if acknowledged else "unknown"
    records[request_id] = request_record
    write_request_records(cache_dir, records)
    return {
        "ok": True,
        "dry_run": False,
        "request_id": request_id,
        "record": request_record,
        "request_type": request_type,
        "window": window,
        "response_excerpt": response_excerpt,
        "acknowledged": acknowledged,
    }


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
