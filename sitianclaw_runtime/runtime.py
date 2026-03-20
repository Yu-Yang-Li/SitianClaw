from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd


def repo_root_from_script(script_file: str | Path) -> Path:
    path = Path(script_file).resolve()
    for candidate in [path.parent, *path.parents]:
        if (candidate / "skills").is_dir() and (candidate / "README.md").exists():
            return candidate
    raise RuntimeError("Unable to locate the SitianClaw repo root from the script path.")


def bootstrap_repo_root(script_file: str | Path) -> Path:
    repo_root = repo_root_from_script(script_file)
    text = str(repo_root)
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
        base = repo_root / "data" / "artifacts" / safe_slug(skill_name)
        if target_name:
            base = base / safe_slug(target_name)
    base.mkdir(parents=True, exist_ok=True)
    return base


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
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
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
