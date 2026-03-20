# SitianClaw

Portable astronomy skills for Codex/OpenClaw style agents.

`SitianClaw` packages the current SNC no-server workflows as installable skills so an agent can gain transient-analysis capabilities from a single GitHub install step.

The preferred entry points are now workflow-aligned skills that mirror the real SNC workflow, not only broad one-off utilities.

## Install

Install the whole bundle from a GitHub repo URL:

```text
install https://github.com/<org>/SitianClaw
```

If your client supports subpath installs, individual skills can also be installed from `skills/<skill-name>`.

## Preferred Workflow Skills

- `snc-candidate-crawl-3day`: fetch the 3-day TNS plus ZTF plus LSST intake pool and bind it to nearby host-redshift context using the workspace `z<=0.025` default
- `snc-candidate-screen-3day`: apply the strict SNC shortlist science cuts to that 3-day pool
- `snc-forced-phot-submit`: submit a new ZTF forced-photometry request
- `snc-forced-phot-monitor`: monitor pending requests and refresh cache or mailbox state
- `snc-forced-phot-fetch`: load downloaded forced-photometry results and plot them
- `snc-observability-3day`: evaluate the next 3 days of observability across the SNC telescope set

## Cloud-Ready Today

These skills are already GitHub-only portable and do not require a local `C:\SNC` checkout:

- `snc-transient-query`
- `snc-candidate-crawl-3day`
- `snc-candidate-screen-3day`
- `snc-redshift-query`
- `snc-forced-phot-submit`
- `snc-forced-phot-monitor`
- `snc-forced-phot-fetch`
- `snc-forced-photometry`
- `snc-observability`
- `snc-observability-3day`
- `snc-host-context`
- `snc-explosion-time`

They rely only on public upstream services plus standard Python packages listed in `requirements-cloud.txt`.

## Additional Skills

- `snc-transient-query`: ad hoc single-target TNS and broker inspection
- `snc-redshift-query`: host-redshift consensus lookup for a single target
- `snc-forced-photometry`: legacy combined forced-photometry wrapper
- `snc-observability`: legacy generic observability wrapper
- `snc-explosion-time`: portable SN Clock explosion-time prediction with bundled models
- `snc-host-context`: host-environment crossmatch and contamination summary

## Runtime Requirements

- All bundled skills now run from the GitHub repository itself; install `requirements-cloud.txt` if your agent runtime does not auto-resolve imports.
- Live forced-phot submission or refresh still needs real ZTF credentials, but the code path no longer depends on a local SNC checkout.
- The agent session must allow launching Python and writing output artifacts.

## GitHub-Only Smoke Test

After cloning the repository and installing `requirements-cloud.txt`, you can verify the cloud-ready subset without any local SNC workspace:

```text
python scripts/cloud_smoke_test.py --name "SN 2026fvx"
```

The script clears `SNC_REPO_ROOT` and `PYTHONPATH`, then runs:

- `snc-transient-query`
- `snc-redshift-query`
- `snc-forced-phot-submit`
- `snc-forced-phot-monitor`
- `snc-forced-phot-fetch`
- `snc-observability-3day`
- `snc-candidate-crawl-3day`
- `snc-explosion-time`

To include the portable shortlist workflow as well:

```text
python scripts/cloud_smoke_test.py --name "SN 2026fvx" --include-screen
```

To also include the portable host-context check against public catalogs:

```text
python scripts/cloud_smoke_test.py --name "SN 2026fvx" --include-screen --include-host-context
```

To also include the portable forced-phot monitor and fetch skills using bundled sample assets:

```text
python scripts/cloud_smoke_test.py --name "SN 2026fvx" --include-screen --include-host-context --include-forced-phot
```

The smoke test runs `snc-forced-phot-submit` in `--dry-run` mode, so it validates the portable submission path without creating a live ZTF request.

To also include the portable SN Clock explosion-time path:

```text
python scripts/cloud_smoke_test.py --name "SN 2026fvx" --include-screen --include-host-context --include-forced-phot --include-explosion-time
```

To also verify the portable legacy wrappers:

```text
python scripts/cloud_smoke_test.py --name "SN 2026fvx" --include-screen --include-host-context --include-forced-phot --include-explosion-time --include-legacy
```

## Layout

```text
SitianClaw/
├── README.md
├── README.zh-CN.md
└── skills/
    ├── snc-transient-query/
    ├── snc-candidate-crawl-3day/
    ├── snc-candidate-screen-3day/
    ├── snc-redshift-query/
    ├── snc-forced-phot-submit/
    ├── snc-forced-phot-monitor/
    ├── snc-forced-phot-fetch/
    ├── snc-forced-photometry/
    ├── snc-observability/
    ├── snc-observability-3day/
    ├── snc-explosion-time/
    └── snc-host-context/
```

Each skill is self-contained so the bundle can be installed as a whole or split into individual skill paths later.
