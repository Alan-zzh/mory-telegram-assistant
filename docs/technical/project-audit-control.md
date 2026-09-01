# 项目内自动巡检控制面

## 边界

唯一执行入口是 `scripts/project_audit_control.py`。它只读本地 Git/文档/配置合同和 VPS 的 systemd、journal、文件、SQLite、cron 事实；不会修代码、部署、重启、改配置、写生产 DB、发 Telegram 或安装 Skill/Agent/Automation。

结构化回执使用 `mory.project-audit-receipt/v1`：`pass` 退出 0，证据不可得或 coverage 不足为 `evidence_gap` 退出 2，真实异常/漂移为 `failed` 退出 3。回执默认写到 `runtime/audit-reports/project-automation/`，同时维护各 profile 的 `latest-*.json`。

## 手动触发

```bash
python scripts/project_audit_control.py --profile production-truth
python scripts/project_audit_control.py --profile drift
python scripts/project_audit_control.py --profile monthly
python scripts/project_audit_control.py --profile all
```

- `production-truth`：开发机从 `.env` SSH 取证；部署在生产目录时自动走本机受限只读执行，不要求 VPS 再持有一份 SSH 密码。两种表面均复用 `puzan_loop_monitor` 和 `core.deploy_utils` 门禁，核验双服务、版本、health、日志、DB、调度、权限、watchdog 心跳与业务回执。
- `drift`：完整 Git 工作区运行 doc/config/Git/hash 门禁；不带 `.git` 和内部治理文档的生产发布包只核对部署版本子集、配置合同、指定文件 hash 与生产配置键名，并在 coverage 明示边界。
- `monthly`：完整工作区分析最近 Git 历史；生产发布包没有 `.git` 时分析随版本部署的 CHANGELOG 日期和主题。两者只输出 Skill/Agent/Automation/skip 候选、估算假设和验收标准，绝不安装或晋升能力。

## 定时定义（未启用）

仓库提供 systemd template 与三个 timer 样例，默认日巡生产真相、周巡漂移、月审重复工作。先本地验证计划：

```bash
python scripts/manage_project_audit_timers.py --action plan
python scripts/manage_project_audit_timers.py --action install
```

第二条未带 `--apply` 仍只输出 `planned_not_applied` 并退出 2。只有在目标 systemd 主机上明确授权后，root 才可执行：

```bash
python scripts/manage_project_audit_timers.py --action install --apply --audit-user ubuntu
python scripts/manage_project_audit_timers.py --action verify --audit-user ubuntu
python scripts/manage_project_audit_timers.py --action uninstall --apply --audit-user ubuntu
```

本仓库落地不代表 VPS timer 已安装。是否启用必须以目标主机 `systemctl list-timers 'mory-project-audit-*'`、unit 内容、最近运行退出码及 `latest-*.json` 回执为准。

安装器只接受拥有项目 `.env` 的审计用户，回执目录固定为该用户所有的 0700，unit `UMask=0077`；不会通过 systemd `EnvironmentFile` 把整份 `.env` 注入服务。生产部署清单只精确携带 audit example 与四个 systemd 模板，不上传真实 `.env`/`config.json`。

## 证据判读

- health 200 只判 liveness，版本必须读远端 `version.py` 或 hash。
- L1 的 `top/free/df/ss/uptime/loadavg` 必须同时满足命令成功和关键字段可解析；纯证据不可得为 `evidence_gap`，若同时发现真实资源或 OOM 告警仍为 `failed`。
- `conversion_events.ts` 使用秒级 Unix 时间，L4 转化窗口不得乘 1000；时间单位以生产写入点和真实样本为准。
- `task_execution_history` 只覆盖事务任务，`scheduler_metrics` 是持久历史；当前进程 registry 未被观察时必须在 coverage 中明说。
- journal 无法读取或启动时间缺失是 `evidence_gap`，不能用“无匹配输出”冒充无错误。
- 配置的业务回执只是 DB 中已完成任务的只读 receipt，不执行真实账号动作；受影响功能需要更强的真实业务探针时，Automation 只报告缺口，由人授权 Agent 执行。
- 生产配置键审计允许仍被运行代码使用的兼容键继续可见；命中 `core.config_compat.REMOVED_CONFIG_FIELDS` 的已确认废弃键必须判 `failed`，不能因必需键齐全就假绿。审计只输出键名，不读取或回显值。
