# SitianClaw

面向 Codex / OpenClaw / 龙虾类代理的一键安装天文技能仓库。

`SitianClaw` 把当前 SNC 里“不起服务、直接本地执行”的核心能力整理成可托管到 GitHub 的 skills 仓库，便于通过一条 `install` 指令完成集成。

## 安装方式

整仓安装：

```text
install https://github.com/<org>/SitianClaw
```

如果客户端支持子路径安装，也可以只安装某个单独 skill，例如 `skills/snc-redshift-query`。

## 已包含技能

- `snc-transient-query`：瞬变源查询，输出 JSON、天区图、broker 光变图
- `snc-redshift-query`：红移与宿主查询，输出共识红移和对比图
- `snc-forced-photometry`：强制测光提交、监控、结果读取与可视化
- `snc-observability`：多台站可观测性统计与高度角图
- `snc-explosion-time`：基于本地 SN Clock 的爆发时间预测
- `snc-host-context`：宿主环境交叉匹配与污染风险摘要

## 运行前提

- 本仓库只提供 skills，不包含完整 SNC 科学代码与数据。
- 本地仍需存在真实的 SNC 工作区，至少应包含 `src/tns_project`、`sn_clock`、`data` 等目录。
- 调用 skill 时，建议在 SNC 工作区根目录下运行；如果不在该目录下，请设置 `SNC_REPO_ROOT` 指向工作区根目录。
- 调用环境需要允许启动 Python，并允许写入 JSON / PNG / HTML 等产物。

## 仓库结构

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

当前设计目标是“每个 skill 自包含”，这样既能整仓安装，也便于后续拆成单独 skill 路径分发。
