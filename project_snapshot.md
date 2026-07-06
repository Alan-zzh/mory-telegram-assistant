<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理 项目状态快照（覆盖式）

> 本文件每次整段覆盖对应区块，禁止无限追加。最后更新：2026-07-07。

## 一句话
Telegram 群组助手机器人 Mory小助理：人设对话、广告检测、群管、积分商城、转化漏斗、新闻播报、运营 Dashboard。单机 VPS 部署（systemd 唯一）。

## 模块状态表
| 模块 | 状态 | 入口文件 | 备注 |
|------|------|----------|------|
| 消息总分发 | 在用 | `core/message_dispatcher.py` | 9 个分发函数（8 定义 + 导入 `_dispatch_p10_ai`） |
| AI 回复 / 人设 | 在用 | `core/ai_reply_handler.py`、`core/ai_engine.py`、`core/persona_adapter.py` | `SYSTEM_PROMPT` 从 config 读取 |
| 模型路由 | 在用 | `core/model_router.py` | 三层池 + 降级链；10 个 task_type 映射 |
| 定时任务 | 在用 | `modules/auto_tasks.py` | 53 个 `_job_` 函数 |
| 广告检测 | 在用 | `modules/ad_detector.py`、`core/handlers/security_handlers.py` | L0–L4 五层 |
| 群管 / 积分 / 娱乐 | 在用 | `modules/*.py` | 92 个业务 `.py` |
| 孤儿清理 | 在用 | `orphan_api.py`、`burn_orphan_task.py` | 端到端串联 |
| 入群验证 | 在用 | `modules/verification.py` | button / puzzle / timeout / max_attempts |
| Dashboard | 在用 | `dashboard/app.py`、`dashboard/api/*.py` | 157 个路由，端口 6616 |
| 数据库 | 在用 | `core/database.py`、`core/db_repos/*.py` | 108 张表 |
| 配置 | 在用 | `core/settings.py` + `config.json` | 密钥仅 `.env` |
| 转化漏斗 | 在用 | `social_repo.py` + `message_dispatcher` | `conversion_events` 各阶段 |
| 记忆 / 画像 | 在用 | `memory_summarizer.py`、`profile_learner.py` | `profile_learner` 的 `sticker` 维度未入库 |

## 当前版本
v5.31.2（2026-07-06）

## 最近 3 条大事
1. 2026-07-07 文档治理：统一文档数字、清理两套备份与根目录垃圾、新增文档一致性自检脚本、重建六大根文档。
2. 2026-07-06 多次 Hotfix：解封入口加固、签到/资料层误封修复、AI 失败兜底静默、模型池根因修复。
3. 2026-07-04 修复 `burn_orphan` 漏清 `channel_tracking`。

## 客观指标（供 `scripts/doc_consistency.py` 断言，勿手改）
<!-- METRICS:BEGIN -->
modules_py=91
core_py=73
job_count=53
db_tables=108
dashboard_routes=157
dispatch_funcs=9
model_router_mappings=10
<!-- METRICS:END -->
