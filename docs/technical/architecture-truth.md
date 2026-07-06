# 架构真相：媒体 / 宣发 Bot 与 mory_assistant 的关系（2026-07-07 修订）

## 结论
- **mory_assistant**（本仓库，`/home/ubuntu/mory_assistant`）：双核心服务 `mory-assistant` + `mory-dashboard`，生产库 `mory.db`。
- **媒体 / 宣发 Bot**：是**独立项目**，位于 VPS `/opt/moryfansbot`（`bot.py` + `web_admin`），**不在本仓库**。它读取本仓库 `mory.db` 的 `promotions` 表做定时广播。
- 本仓库**不存在** `mory_media_assistant` 目录 / 服务。文档中出现的 `mory_media_assistant` 是**历史过期描述**（见 `docs/technical/vps-deploy-trap.md` 陷阱 7 修订）。

## 对决策的影响
1. 媒体相关需求：第一反应去 `/opt/moryfansbot` 看，不要在 mory_assistant 加 media 模式。
2. 跨项目耦合：因共享 `mory.db`，主项目长事务 / 锁表会饿死宣发 Bot；改 `mory.db` 写操作须评估锁影响。
3. 文档口径：`mory_media_assistant` 提法一律当过期处理。

## 治理动作（2026-07-07）
- 删除本仓库坏桩 `config/mory-media-assistant.service` / `config/mory-media-dashboard.service`，从 `deploy_vps.py` 的 `SERVICE_FILES` 移除，VPS 上 `systemctl disable` + `rm` + `daemon-reload`。
- 当前线上仅一套稳定部署：双核心服务。
- 本仓库残留的 media 模式 env 驱动代码（dashboard `DASHBOARD_MODE=media`、`auto_tasks` `_mode=="media"`、`core/shared_db.py` 跨 Bot 共享库）为休眠分支，仅手动设 env 时生效，删 unit 不影响运行。
