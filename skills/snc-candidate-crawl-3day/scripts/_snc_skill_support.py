from __future__ import annotations

import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd


def repo_root_from_script(script_file: str | Path) -> Path:
    return resolve_repo_root(script_file)


def _is_snc_repo_root(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "src" / "tns_project").is_dir()
        and (path / "sn_clock").is_dir()
    )


def _candidate_root_chain(start: str | Path | None) -> list[Path]:
    if start is None:
        return []
    try:
        path = Path(start).expanduser().resolve()
    except OSError:
        path = Path(start).expanduser()

    base = path if path.is_dir() else path.parent
    return [base, *base.parents]


def resolve_repo_root(script_file: str | Path, env_var: str = "SNC_REPO_ROOT") -> Path:
    seen: set[Path] = set()
    search_starts = [
        os.environ.get(env_var),
        Path.cwd(),
        script_file,
    ]
    for start in search_starts:
        for candidate in _candidate_root_chain(start):
            if candidate in seen:
                continue
            seen.add(candidate)
            if _is_snc_repo_root(candidate):
                return candidate

    raise RuntimeError(
        f"Unable to locate the SNC workspace root. "
        f"Run this skill from inside the SNC repo or set {env_var} to that root."
    )


def bootstrap_repo_root(script_file: str | Path, env_var: str = "SNC_REPO_ROOT") -> Path:
    repo_root = resolve_repo_root(script_file, env_var=env_var)
    for path in (repo_root, repo_root / "src"):
        text = str(path)
        if text not in sys.path:
            sys.path.append(text)
    return repo_root


def normalize_name(value: Any) -> str:
    return re.sub(r"[\s_]+", "", str(value or "")).lower()


def safe_slug(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "artifact").strip())
    text = re.sub(r"_+", "_", text).strip("._")
    return text or "artifact"


def ensure_output_dir(
    repo_root: Path,
    skill_name: str,
    target_name: str | None = None,
    output_dir: str | Path | None = None,
) -> Path:
    if output_dir is not None:
        base = Path(output_dir)
    else:
        base = repo_root / "plots" / "skills" / safe_slug(skill_name)
        if target_name:
            base = base / safe_slug(target_name)
    base.mkdir(parents=True, exist_ok=True)
    return base


@lru_cache(maxsize=1)
def load_tns_full_info(repo_root_str: str) -> dict[str, Any]:
    path = Path(repo_root_str) / "sn_clock" / "data" / "tns" / "parsed" / "tns_full_info.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def find_tns_entry(repo_root: Path, name: str | None) -> tuple[str | None, dict[str, Any] | None]:
    if not name:
        return None, None
    data = load_tns_full_info(str(repo_root))
    if name in data:
        return name, data[name]

    target = normalize_name(name)
    for key, value in data.items():
        if normalize_name(key) == target:
            return key, value
    return None, None


def load_request_cache(repo_root: Path) -> list[dict[str, Any]]:
    cache_dir = repo_root / "data" / "ztf_forced_cache"
    request_rows: list[dict[str, Any]] = []
    for file_name in ("pending_requests.json", "completed_requests.json"):
        path = cache_dir / file_name
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        for request_id, item in payload.items():
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.setdefault("request_id", request_id)
            request_rows.append(row)
    request_rows.sort(
        key=lambda row: str(row.get("complete_time") or row.get("submit_time") or ""),
        reverse=True,
    )
    return request_rows


def find_requests_by_name(repo_root: Path, name: str | None) -> list[dict[str, Any]]:
    if not name:
        return []
    target = normalize_name(name)
    matches = []
    for row in load_request_cache(repo_root):
        row_name = row.get("source_name") or row.get("tns_name")
        if normalize_name(row_name) == target:
            matches.append(row)
    return matches


def resolve_target(
    repo_root: Path,
    name: str | None = None,
    ra: float | None = None,
    dec: float | None = None,
) -> dict[str, Any]:
    resolved_name = name or "custom-target"
    resolved_ra = float(ra) if ra is not None else None
    resolved_dec = float(dec) if dec is not None else None
    resolved_from: list[str] = []

    tns_key, tns_entry = find_tns_entry(repo_root, name)
    request_matches = find_requests_by_name(repo_root, name)

    if (resolved_ra is None or resolved_dec is None) and request_matches:
        row = request_matches[0]
        row_ra = row.get("ra")
        row_dec = row.get("dec")
        try:
            if resolved_ra is None and row_ra is not None:
                resolved_ra = float(row_ra)
            if resolved_dec is None and row_dec is not None:
                resolved_dec = float(row_dec)
            if resolved_ra is not None and resolved_dec is not None:
                resolved_from.append("ztf_request_cache")
        except (TypeError, ValueError):
            pass

    if (resolved_ra is None or resolved_dec is None) and tns_entry:
        entry_ra = tns_entry.get("ra")
        entry_dec = tns_entry.get("dec")
        try:
            if resolved_ra is None and entry_ra is not None:
                resolved_ra = float(entry_ra)
            if resolved_dec is None and entry_dec is not None:
                resolved_dec = float(entry_dec)
            if resolved_ra is not None and resolved_dec is not None:
                resolved_from.append("tns_full_info")
        except (TypeError, ValueError):
            pass

    return {
        "name": resolved_name,
        "ra": resolved_ra,
        "dec": resolved_dec,
        "tns_key": tns_key,
        "tns_entry": tns_entry,
        "request_matches": request_matches,
        "resolved_from": resolved_from,
    }


def dataframe_records(
    dataframe: pd.DataFrame | None,
    columns: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if dataframe is None or dataframe.empty:
        return []
    df = dataframe.copy()
    if columns:
        selected = [column for column in columns if column in df.columns]
        if selected:
            df = df[selected]
    if limit is not None:
        df = df.head(limit)
    return [json_safe(row) for row in df.to_dict(orient="records")]


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(json_safe(payload), handle, ensure_ascii=False, indent=2)
    return path


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
