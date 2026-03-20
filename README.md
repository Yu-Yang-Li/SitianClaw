# SitianClaw

Portable astronomy skills for Codex/OpenClaw style agents.

`SitianClaw` packages the current SNC no-server workflows as installable skills so an agent can gain transient-analysis capabilities from a single GitHub install step.

The preferred entry points are now workflow-aligned skills that mirror the real SNC workspace pipeline, not only broad one-off utilities.

## Install

Install the whole bundle from a GitHub repo URL:

```text
install https://github.com/<org>/SitianClaw
```

If your client supports subpath installs, individual skills can also be installed from `skills/<skill-name>`.

## Preferred Workflow Skills

- `snc-candidate-crawl-3day`: fetch the raw 3-day TNS plus ZTF plus LSST candidate pool used by the workspace intake stage
- `snc-candidate-screen-3day`: apply the strict SNC shortlist science cuts to that 3-day pool
- `snc-forced-phot-submit`: submit a new ZTF forced-photometry request
- `snc-forced-phot-monitor`: monitor pending requests and refresh cache or mailbox state
- `snc-forced-phot-fetch`: load downloaded forced-photometry results and plot them
- `snc-observability-3day`: evaluate the next 3 days of observability across the SNC telescope set

## Additional Skills

- `snc-transient-query`: ad hoc single-target TNS and broker inspection
- `snc-redshift-query`: host-redshift consensus lookup for a single target
- `snc-forced-photometry`: legacy combined forced-photometry wrapper
- `snc-observability`: legacy generic observability wrapper
- `snc-explosion-time`: local SN Clock explosion-time prediction
- `snc-host-context`: host-environment crossmatch and contamination summary

## Runtime Requirements

- This repository ships skills, not the full SNC science codebase.
- The actual SNC workspace must still exist locally with `src/tns_project`, `sn_clock`, and the related data/cache directories.
- Run the installed skill from inside the SNC workspace, or set `SNC_REPO_ROOT` to the workspace root.
- The agent session must allow launching Python and writing output artifacts.

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
