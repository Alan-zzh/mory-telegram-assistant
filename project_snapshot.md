<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理 项目状态快照（覆盖式）

> 本文件每次整段覆盖对应区块，禁止无限追加。最后更新：2026-07-24。

## 一句话
Telegram 群组助手机器人 Mory小助理：人设对话、广告检测、群管、积分商城、转化漏斗、新闻播报、运营 Dashboard。单机 VPS 部署（systemd 唯一）。

## 模块状态表
| 模块 | 状态 | 入口文件 | 备注 |
|------|------|----------|------|
| 消息总分发 | 在用 | `core/message_dispatcher.py` | 9 个分发函数（8 定义 + 导入 `_dispatch_p10_ai`） |
| AI 回复 / 人设 | 在用 | `core/handlers/ai_reply_handler.py`、`core/ai_engine.py`、`core/persona_adapter.py` | `SYSTEM_PROMPT` 从 config 读取；时段提示词支持默认集与局部配置合并 |
| 模型路由 | 在用 | `core/model_router.py`、`core/ai_engine.py` | 单池模式（llm 主池）；`use_tier_routing = bool(_tier_pools)` 配置无三层池时自动降级；7 个文本模型按到期日升序；`qwen3.5-ocr` 归视觉池；到期/熔断/超时自动切换 + 黑名单 dirty 标记异步落盘 |
| 定时任务 | 在用 | `tasks/task_scheduler.py` 自动发现 `tasks/` 下 53 个 BaseTask 子类 | `modules/auto_tasks.py` 为 legacy（`_start_with_apscheduler` 死代码，仅保留部分工具函数） |
| 广告检测 | 在用 | `modules/ad_detector.py`、`modules/ad_marketing_patterns.py`、`modules/ai_advisor.py`、`modules/avatar_detector.py`、`core/handlers/security_handlers.py` | L0–L4 五层 + 营销话术 4 维度 71 条 + AI 辅助决策 4 函数（默认关闭） |
| 群管 / 积分 / 娱乐 | 在用 | `modules/*.py` | 135 个业务 `.py` |
| 销售中心 | 默认关闭 | `modules/sales_center.py`、`core/db_repos/sales_repo.py` | 商品/订单/销售漏斗/佣金，`SALES_CENTER_CONFIG.enabled` 开关 |
| 安全中心 | 默认关闭 | `modules/security_center.py` | 统一风险评分/自动分级处置，`SECURITY_CENTER_CONFIG.enabled` 开关 |
| 多群托管 | 默认关闭 | `modules/managed_groups.py` | 代运营/套餐管理/功能矩阵，`MANAGED_GROUPS_CONFIG.enabled` 开关 |
| 内容排查增强 | 默认关闭 | `modules/content_audit.py` | 文本/链接/文件/违规日志，`CONTENT_AUDIT_CONFIG.enabled` 开关 |
| 新成员数据图 | 默认关闭 | `modules/new_member_analytics.py` | 入群漏斗/来源分析/留存曲线/质量评估，`NEW_MEMBER_ANALYTICS.enabled` 开关 |
| 网编会员 | 默认关闭 | `modules/membership.py` | 付费等级/订阅管理/权益体系，`MEMBERSHIP_CONFIG.enabled` 开关 |
| 孤儿清理 | 在用 | `orphan_api.py`、`burn_orphan_task.py` | 端到端串联 |
| 入群验证 | 在用 | `modules/verification.py` | button / puzzle / timeout / max_attempts |
| Dashboard | 在用 | `dashboard/app.py`、`dashboard/api/*.py` | 157 个路由，端口 6616；关键词页展示关键话题近 30 天无原文命中统计 |
| 数据库 | 在用 | `core/database.py`、`core/db_repos/*.py` | 167 张表 |
| 配置 | 在用 | `core/settings.py` + `config.json` | 密钥仅 `.env` |
| 转化漏斗 | 在用 | `social_repo.py` + `message_dispatcher` | `conversion_events` 各阶段 |
| 记忆 / 画像 | 在用 | `memory_summarizer.py`、`profile_learner.py` | `profile_learner` 的 `sticker` 维度未入库 |
| Rich Message | 在用 | `core/telebot_compat.py`、`core/broadcast_formatter.py` | 新闻来源仅内部诊断，不向用户展示；问候/新闻统一联系按钮；`EPHEMERAL_MESSAGE_ENABLED` 默认关闭 |
| 定点播报 | 在用 | `tasks/maintenance/scheduled_broadcast_task.py`、`modules/scheduled_broadcast.py` | 4 个时段：morning_nudge(10:00) / afternoon_tea(14:30) / evening_wind(19:00) / night_whisper(22:30)；AI 失败回退可信底稿 |
| 关键话题回复 | 在用 | `modules/keyword_trigger.py` | `SPECIAL_AUTO_REPLIES` 支持规则级提示词、AI 润色、安全兜底及匿名话题统计 |

## 当前版本
v5.35.6（2026-07-24）

## 最近 3 条大事
1. 2026-07-24 v5.35.6 生产播报与关键话题闭环：修复新闻内部来源说明泄漏、问候缺按钮、时段话术模板化、局部提示词覆盖默认模式、福利/定制无法按规则润色及统计、零吞吐瞬时积压触发 999 秒迁移假警报。四时段正文与联系入口分工，关键话题统计不保存用户原话。
2. 2026-07-21 v5.35.5 整仓闭环复验：恢复 4 个被 VPS→本地反向同步覆盖的正确模块实现，新增监控/Windows 门禁回归；生产恢复 root watchdog cron并最小发布，双服务、health、watchdog 跨周期与真实调度回执通过。
3. 2026-07-21 v5.35.4 第2轮深度审查修复 22 项：修复单行表数据丢失、高危行为、SQL 字段/类型错误、错误信息泄露与异常处理。

## 客观指标（供 `scripts/doc_consistency.py` 断言，勿手改）
<!-- METRICS:BEGIN -->
modules_py=135
core_py=75
job_count=50
db_tables=167
dashboard_routes=157
dispatch_funcs=9
model_router_mappings=10
<!-- METRICS:END -->
