# v5.38.44 审计控制平面生产恢复

## 结论

- 生产已恢复到 `v5.38.44`；`project_audit_control.py --profile all --no-write` 在服务重启前后均返回 `pass / exit_code=0`。
- 三个 systemd 审计模板服务均真实执行并返回 `Result=success / ExecMainStatus=0`；三条 timer 保持 `enabled + active`。
- 本次未重新扫描成员、未修改广告处置持久态、未修改数据库 schema 或生产凭据。

## 根因与修复

- 根因：v5.38.43 从不包含主线审计修复的分叉工作树执行全目录上传，生产遗留新版 `project_audit_control.py`，但 `core/deploy_utils.py` 被旧版覆盖，形成 ImportError。
- 预防：`deploy_vps.py` 与 `scripts/check_deploy_ready.py` 共同要求部署 HEAD 包含当前本地 `main`，旧分叉全目录部署失败关闭。
- 实跑又发现本地只读 SSH 兼容器未接受监控器的 `get_pty` 参数；已兼容接收并忽略该参数，业务指标与调度层不再降级为 evidence gap。

## 本地门禁

- 提交：`8337353`（旧分叉部署阻断）、`97ea903`（本地监控接口兼容）。
- 目标测试：39 passed；最终审计控制目标测试：17 passed。
- 全仓单测：1074 passed。
- Ruff、配置同步、199 个 DB 委托、文档一致性、records autopilot 均通过。

## 部署与回滚

- 部署前独立代码快照：`backups/audit_recovery_pre_v53844_nXCCO2H4.tar.gz`，大小 15479910 bytes，mode 600，SHA256 `8cf1bd6f98d942435bfdd74cae25e0471a5caa8ffa633187a37cab5d97680ed6`。
- 全量部署外层在 6 分钟超时后遗留两个本机孤儿进程；现场确认文件已上传但 systemd 尚未 restart、远端无依赖安装/重启进程后，精确终止两个孤儿 PID，没有重跑全量部署。
- 随后只补传 `scripts/project_audit_control.py` 与 `scripts/check_deploy_ready.py`，在审计 all profile 通过后单次 restart 双核心服务。

## 生产真相

| 文件 | SHA256 |
|---|---|
| `version.py` | `4048d49a8e37b758a66ae64aa8e9861e31059660ab08d1a98eea92c1367a3cc3` |
| `core/deploy_utils.py` | `a4d8ca3f7116538183c837d2dc35d389b3cd9f4d271347337cfc3c31a39239c6` |
| `scripts/project_audit_control.py` | `615e770bbe4bb34755ff7e0d938ac2f71afa7804c325c4af4ab7e5815480e4af` |
| `scripts/manage_project_audit_timers.py` | `db9c98cc1bc3753248a68337123c27480375a125c293f8739fdc85ce9cf6f643` |
| `scripts/check_deploy_ready.py` | `680220121942a5f83ed5f74c35544a2de640475b3fb3bc33cb92032b3c773119` |

- 双核心服务：active/running，NRestarts=0，ActiveEnterTimestamp=`2026-08-13 10:11:21 CST`；health=200。
- 启动窗口：Bot 错误 0；Dashboard 原始退出噪声经 canonical 过滤后真实错误 0。
- `all --no-write`：production-truth、drift、monthly 三项全部 pass，无 evidence gap、无 failed。

## Timer 实跑与持久态

| Profile | 实跑时间 | Result/Status | 持久回执 |
|---|---|---|---|
| production-truth | 10:11:56–10:11:57 CST | success / 0 | pass 17、gap 0、failed 0、mode 600 |
| drift | 10:11:57–10:11:58 CST | success / 0 | pass 7、gap 0、failed 0、mode 600 |
| monthly | 10:11:58 CST | success / 0 | pass 1、gap 0、failed 0、mode 600 |

- production-truth timer：enabled/active，下次 `2026-08-14 03:26:02 CST`。
- drift timer：enabled/active，下次 `2026-08-17 04:11:33 CST`。
- monthly timer：enabled/active，下次 `2026-09-01 00:23:50 CST`。

## 证据边界

- health 只作为 liveness；完成证据由版本/哈希、重启后 all profile、模板服务真实退出码和 mode 600 持久回执共同组成。
- 成员扫描与 74 人处置未被本次修复重跑；其既有读回结论保持不变。
