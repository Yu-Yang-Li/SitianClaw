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
- `snc-observability-3day`
- `snc-host-context`

They rely only on public upstream services plus standard Python packages listed in `requirements-cloud.txt`.

## Still Local-Dependent

These skills still depend on the full SNC workspace, local caches, credentials, or local models and are not yet pure cloud skills:

- `snc-forced-phot-submit`
- `snc-forced-phot-monitor`
- `snc-forced-phot-fetch`
- `snc-forced-photometry`
- `snc-observability`
- `snc-explosion-time`

## Additional Skills

- `snc-transient-query`: ad hoc single-target TNS and broker inspection
- `snc-redshift-query`: host-redshift consensus lookup for a single target
- `snc-forced-photometry`: legacy combined forced-photometry wrapper
- `snc-observability`: legacy generic observability wrapper
- `snc-explosion-time`: local SN Clock explosion-time prediction
- `snc-host-context`: host-environment crossmatch and contamination summary

## Runtime Requirements

- For the cloud-ready subset, only standard Python packages are needed; install `requirements-cloud.txt` if your agent runtime does not auto-resolve imports.
- The local-dependent subset still requires the full SNC science workspace, local caches, credentials, or local models.
- The agent session must allow launching Python and writing output artifacts.

## GitHub-Only Smoke Test

After cloning the repository and installing `requirements-cloud.txt`, you can verify the cloud-ready subset without any local SNC workspace:

```text
python scripts/cloud_smoke_test.py --name "SN 2026fvx"
```

The script clears `SNC_REPO_ROOT` and `PYTHONPATH`, then runs:

- `snc-transient-query`
- `snc-redshift-query`
- `snc-observability-3day`
- `snc-candidate-crawl-3day`

To include the portable shortlist workflow as well:

```text
python scripts/cloud_smoke_test.py --name "SN 2026fvx" --include-screen
```

To also include the portable host-context check against public catalogs:

```text
python scripts/cloud_smoke_test.py --name "SN 2026fvx" --include-screen --include-host-context
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
