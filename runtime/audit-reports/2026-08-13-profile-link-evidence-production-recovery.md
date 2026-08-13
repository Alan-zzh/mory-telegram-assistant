# v5.38.45 资料链接广告证据门禁与误封恢复

## 结论

- 生产已升级到 `v5.38.45`：Bio 裸链接和普通绑定个人频道不再单独授权删除、禁言或黑名单，姓名/username/Bio 分字段匹配。
- 明确“广告引流 + 链接”、色情身份 + 资源/实战/服务 + 链接，以及个人频道多锚点广告组合仍按统一治理链处置。
- 2026-08-13 09:20–09:40 存量扫描中，64 个处置记录的唯一原因为裸 `t.me` 链接；按新规则逐人重新取证后，63 人恢复，1 人因当前资料仍有明确广告组合而保留。

## 本地门禁

- 提交：`34b44b1`。
- 广告相关定向回归：362 passed；入群与资料补充回归：72 passed。
- 全仓单测：1080 passed。
- 配置同步、199 个 DB 委托、文档一致性、Ruff、compileall 与 records autopilot 均通过。

## 生产发布

- 全量部署文件上传完成后外层命令超时，生产仍运行旧进程；精确终止一个本机 `deploy_vps.py` 孤儿，远端无依赖安装或 restart 进程，未重跑全量部署。
- 三个关键文件编译、导入和 SHA-256 与本地一致后，仅执行一次双服务 restart。
- 双服务于 2026-08-13 18:41:17 CST 启动，均 `active/running`、`NRestarts=0`，health 200。

| 文件 | SHA-256 |
|---|---|
| `version.py` | `e28e2e91fe79a64055dc4fcdb38071f3cd76cec2d18d7e5d2cea7cf8e1b25a51` |
| `modules/ad_patterns_encoded.py` | `a81bb4750463b6a90ba0c88b5dcad9dc1f9b6e0b677dbbf0321e9b3b2a9fd69f` |
| `modules/ad_profile_signals.py` | `9cd0a6d9e98836ee67b658d0da4859e6dfb49d42f7f73f458ac18ed2092c41bc` |

## 生产业务探针

- 裸个人链接：`is_ad=False / score=0`。
- 普通摄影个人频道：`is_ad=False / score=0`。
- 明确广告引流链接：`is_ad=True / score=3`。
- 色情资源招揽链接：`is_ad=True / score=3`。

## 历史误封恢复

- 恢复前 SQLite 在线备份：`backups/profile_link_recovery_pre_v53845_20260813T184426.db`，mode 600，SHA-256 `4a6f137cb04a527204f37916f990bc7b0705ff686ddfe10cb386ca2363456a16`。
- 原始目标 64；逐人新规则重取证后恢复 63、保留强广告 1、失败 0。
- Telegram 权限独立聚合读回：恢复 63、保留 1、查询失败 0。
- 原始目标集合的持久态聚合读回：`blacklist=1`、`global_blacklist=1`、`mute_records=1`、`ad_suspicious_users=0`；三表保留的同一对象为新规则仍命中的强广告账号。
- 已删除的历史消息无法恢复；本次未向用户发送通知，未重新扫描全群。

## 边界

- `project_audit_control.py --profile all --no-write` 中 production-truth 当前因服务器 `load1=5.03` 返回资源告警；drift、monthly 及 production-truth 其余 16 项通过。该告警不是本次广告规则或服务启动故障，未修改资源阈值掩盖它。
- 启动窗口原始 journal 的异常关键词仅为已知 Dashboard/gevent 旧进程退出噪声；新 Bot 和 Dashboard 进程保持运行。
- 生产无部署、扫描或恢复临时进程残留。
