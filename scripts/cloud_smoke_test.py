from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _run(command: list[str], workdir: Path) -> dict[str, object]:
    env = os.environ.copy()
    env.pop("SNC_REPO_ROOT", None)
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        command,
        cwd=str(workdir),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the GitHub-only cloud smoke tests for SitianClaw.")
    parser.add_argument("--name", default="SN 2026fvx", help="Target name for single-target smoke tests.")
    parser.add_argument(
        "--include-screen",
        action="store_true",
        help="Also run the portable snc-candidate-screen-3day workflow smoke test.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for smoke-test artifacts. Defaults to <repo>/data/cloud_smoke_test.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = Path(args.output_dir) if args.output_dir else repo_root / "data" / "cloud_smoke_test"
    output_dir.mkdir(parents=True, exist_ok=True)

    commands = {
        "transient_query": [
            sys.executable,
            str(repo_root / "skills" / "snc-transient-query" / "scripts" / "query_transients.py"),
            "--name",
            args.name,
            "--output-dir",
            str(output_dir / "transient_query"),
        ],
        "redshift": [
            sys.executable,
            str(repo_root / "skills" / "snc-redshift-query" / "scripts" / "query_redshift.py"),
            "--name",
            args.name,
            "--output-dir",
            str(output_dir / "redshift"),
        ],
        "observability": [
            sys.executable,
            str(repo_root / "skills" / "snc-observability-3day" / "scripts" / "forecast_observability_3day.py"),
            "--name",
            args.name,
            "--output-dir",
            str(output_dir / "observability"),
        ],
        "candidate_crawl": [
            sys.executable,
            str(repo_root / "skills" / "snc-candidate-crawl-3day" / "scripts" / "crawl_candidates_3day.py"),
            "--output-dir",
            str(output_dir / "candidate_crawl"),
        ],
    }
    if args.include_screen:
        commands["candidate_screen"] = [
            sys.executable,
            str(repo_root / "skills" / "snc-candidate-screen-3day" / "scripts" / "screen_candidates_3day.py"),
            "--output-dir",
            str(output_dir / "candidate_screen"),
        ]

    results = {name: _run(command, repo_root) for name, command in commands.items()}
    summary = {
        "repo_root": str(repo_root),
        "output_dir": str(output_dir),
        "python": sys.executable,
        "success": all(item["returncode"] == 0 for item in results.values()),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
