# SitianClaw

面向 Codex / OpenClaw / 龙虾类代理的一键安装天文技能仓库。

`SitianClaw` 把当前 SNC 里“不起服务、直接本地执行”的核心能力整理成可托管到 GitHub 的 skills 仓库，便于通过一条 `install` 指令完成集成。

现在优先推荐的是“和工作区真实流程对齐”的 workflow skills，而不只是按宽泛能力划分的大 skill。

## 安装方式

整仓安装：

```text
install https://github.com/<org>/SitianClaw
```

如果客户端支持子路径安装，也可以只安装某个单独 skill，例如 `skills/snc-redshift-query`。

## 优先使用的工作流技能

- `snc-candidate-crawl-3day`：抓取工作区当前使用的 3 天 TNS + ZTF + LSST 候选池，并按工作区默认 `z<=0.025` 自动绑定近邻红移上下文
- `snc-candidate-screen-3day`：对 3 天候选池执行 SNC 严格 shortlist 筛选
- `snc-forced-phot-submit`：提交新的 ZTF 强制测光请求
- `snc-forced-phot-monitor`：监控待处理请求并刷新缓存/邮箱状态
- `snc-forced-phot-fetch`：读取已下载的强制测光结果并画图
- `snc-observability-3day`：评估未来 3 天在 SNC 台站集合上的可观测性

## 其他补充技能

- `snc-transient-query`：单目标的 TNS / broker 临时查询
- `snc-redshift-query`：单目标宿主红移共识查询
- `snc-forced-photometry`：旧版一体化强制测光封装
- `snc-observability`：旧版通用可观测性封装
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

当前设计目标是“每个 skill 自包含”，这样既能整仓安装，也便于后续拆成单独 skill 路径分发。
