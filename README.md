# SitianClaw

Portable astronomy skills for Codex/OpenClaw style agents.

`SitianClaw` packages the current SNC no-server workflows as installable skills so an agent can gain transient-analysis capabilities from a single GitHub install step.

## Install

Install the whole bundle from a GitHub repo URL:

```text
install https://github.com/<org>/SitianClaw
```

If your client supports subpath installs, individual skills can also be installed from `skills/<skill-name>`.

## Included Skills

- `snc-transient-query`: query TNS and broker sources with JSON and sky/lightcurve artifacts
- `snc-redshift-query`: resolve host redshift and consensus with a comparison plot
- `snc-forced-photometry`: submit, monitor, and fetch ZTF forced photometry
- `snc-observability`: compute telescope visibility windows and altitude plots
- `snc-explosion-time`: run local SN Clock explosion-time prediction
- `snc-host-context`: crossmatch host environment catalogs and summarize contamination risk

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
    ├── snc-redshift-query/
    ├── snc-forced-photometry/
    ├── snc-observability/
    ├── snc-explosion-time/
    └── snc-host-context/
```

Each skill is self-contained so the bundle can be installed as a whole or split into individual skill paths later.
