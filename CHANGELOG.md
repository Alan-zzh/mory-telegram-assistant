<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# 变更日志（一行一条）

> 格式：`日期 | 类型[新增/修复/清理/文档] | 一句话 | 涉及文件`
> 2026-07-05 及之前的历史长日志已整体归档至 `docs/archive/CHANGELOG_archive_20260707.md`。

| 日期 | 类型 | 一句话 | 涉及文件 |
|------|------|--------|----------|
| 2026-07-09 | 处置 | 封禁3个发送色情骚扰消息的账号（uid=7811860071/810654988/7630821037），已落 `blacklist`+`global_blacklist` 并清理历史消息 | `modules/ad_enforcement.py` |
| 2026-07-09 | 修复 | 消息层色情骚扰话术漏检，新增"水多多/看b吗/好大...好痛"等即时封禁规则 | `modules/ad_patterns_encoded.py`、`modules/ad_detector.py` |
| 2026-07-09 | 优化 | 专家团多角度审查落地低占用（稳定第一）：telebot num_threads 50→10、dashboard gunicorn -w 2→1、SQLite 加 cache_size=-4000/mmap=256MB、备份降为每6h+硬上限60、ad_detector 缓存加 2000 容量上限、_ensure_deps 默认只校验不自动安装、config_reload_watcher 5s→30s；并修复 dashboard 宕机（sudo systemctl enable --now 持久拉起，原 disabled+inactive） | `core/bot_initializer.py`、`core/database.py`、`modules/auto_tasks.py`、`modules/ad_detector.py`、`config/mory-dashboard.service` |
| 2026-07-08 | 修复 | 生产服务器 OOM/高 swap 恢复，限制异常 `dreamina-bridge` 容器内存并修复 `conversion_events` 重复加列错误 | `core/funnel_state_machine.py`、`core/growth_optimizer.py`、`version.py` |
| 2026-07-07 | 修复 | 生产 Dashboard worker timeout 隐患修复，Gunicorn 超时放宽并启用 worker 回收，巡检期望版本同步到 v5.31.3 | `config/mory-dashboard.service`、`version.py`、`scripts/puzan_loop_monitor.py`、`project_snapshot.md` |
| 2026-07-06 | 修复 | 解封入口三次加固，`/unban` 私聊解析到正确 ID | `main.py`、`core/message_dispatcher.py` |
| 2026-07-06 | 修复 | 修复解封指令私聊不生效，前移 P5.6 早路由 | `core/message_dispatcher.py` |
| 2026-07-06 | 修复 | 彻底修复"签到"误封，正常业务动作不进广告资料层 | `modules/ad_detector.py` |
| 2026-07-06 | 修复 | 广告资料层误封风险，白名单/管理员免检前移 | `modules/ad_detector.py`、`core/handlers/security_handlers.py` |
| 2026-07-06 | 修复 | 单人禁封管理员通知带"一键解封"按钮 | `modules/ad_detector.py` |
| 2026-07-05 | 修复 | AI 失败静默兜底，移除拟人化尴尬文案 | `core/ai_engine.py` |
| 2026-07-05 | 修复 | 剔除慢/坏模型，standard 首发 glm-5.1，预算收紧 30s/2 次 | `core/model_router.py`、`core/ai_engine.py` |
| 2026-07-04 | 修复 | 修复 `burn_orphan` 漏清 `channel_tracking` | `modules/orphan_cleanup*.py` |
| 2026-07-07 | 文档 | 深度审计+整改：统一文档数字、清理两套备份与根目录垃圾、重建六大根文档 | `AGENTS.md`、`README.md`、`project_snapshot.md`、`VERSION.md`、`CHANGELOG.md`、`AI_DEBUG_HISTORY.md` |
| 2026-07-07 | 新增 | 文档数字一致性自检脚本 `scripts/doc_consistency.py` | `scripts/doc_consistency.py`、`project_snapshot.md` |
| 2026-07-07 | 清理 | 两套备份（`backup/`、`backups/`）与根目录垃圾移入 `_quarantine_20260707/`，审计报告移入 `runtime/audit-reports/` | `_quarantine_20260707/`、`runtime/audit-reports/` |
