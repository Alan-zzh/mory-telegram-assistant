<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理 项目状态快照（覆盖式）

> 本文件每次整段覆盖对应区块，禁止无限追加。最后更新：2026-07-20。

## 一句话
Telegram 群组助手机器人 Mory小助理：人设对话、广告检测、群管、积分商城、转化漏斗、新闻播报、运营 Dashboard。单机 VPS 部署（systemd 唯一）。

## 模块状态表
| 模块 | 状态 | 入口文件 | 备注 |
|------|------|----------|------|
| 消息总分发 | 在用 | `core/message_dispatcher.py` | 9 个分发函数（8 定义 + 导入 `_dispatch_p10_ai`） |
| AI 回复 / 人设 | 在用 | `core/handlers/ai_reply_handler.py`、`core/ai_engine.py`、`core/persona_adapter.py` | `SYSTEM_PROMPT` 从 config 读取 |
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
| Dashboard | 在用 | `dashboard/app.py`、`dashboard/api/*.py` | 157 个路由，端口 6616 |
| 数据库 | 在用 | `core/database.py`、`core/db_repos/*.py` | 167 张表 |
| 配置 | 在用 | `core/settings.py` + `config.json` | 密钥仅 `.env` |
| 转化漏斗 | 在用 | `social_repo.py` + `message_dispatcher` | `conversion_events` 各阶段 |
| 记忆 / 画像 | 在用 | `memory_summarizer.py`、`profile_learner.py` | `profile_learner` 的 `sticker` 维度未入库 |
| Rich Message | 在用 | `core/telebot_compat.py`、`core/broadcast_formatter.py` | `send_rich_message_compat` + `build_alert_card_html`；`EPHEMERAL_MESSAGE_ENABLED` 默认关闭 |
| 定点播报 | 在用 | `tasks/maintenance/scheduled_broadcast.py` | 4 个时段：morning_nudge(10:00) / afternoon_tea(14:30) / evening_wind(19:00) / night_whisper(22:30) |

## 当前版本
v5.35.3（2026-07-20）

## 最近 3 条大事
1. 2026-07-20 v5.35.3 GOAL MODE 9 阶段全量审计修复 5 P0 + 4 P1 + 3 P2：多智能体并行静态审计 11 分区共 43 问题；P0 修复 stats_report 第 67/93 行 fetchone 两次 bug 残留 + valid_speak.py import 漏改 + log_cleanup_task 漏 import os + security_center eval()→ast.literal_eval + settings_api 漏 import logger；P1 修复 group_props unmute 漏 hasattr + group_migration except:pass；P2 修复 main/dashboard/app except:pass + start_dashboard 临时密码明文打印脱敏。验证 py_compile 全过 + doc_consistency 7/7 OK + verify_db_methods 179 方法 0 缺失 0 孤儿 + pytest 274/274 passed。部署 VPS 10 文件 SFTP + 双服务 active+enabled + /api/health 200。
2. 2026-07-19 v5.35.2 全项目验收二轮修复 15 项缺陷（5 P0 + 4 P1 + 4 P2 + 2 P3）：4 处 fetchone() 两次调用 bug（group_safety_center 1 处 + stats_report 8 处）+ datetime.timedelta 多层引用 + group_props 4 effect 补 hasattr 防御 + 3 处 except:pass 改 logger.warning + sales_repo update_* rowcount 检查 + bottom_button telegram→telebot.types + sales_repo.get_user_orders 加 chat_id 过滤 + 6 模块接入管理员命令入口（/sales /security /managed /content_audit /analytics /membership）+ Dashboard 44 新模块 CONFIG 键纳入白名单。验证 355 passed / 0 failed + 179 DB 方法 0 缺失 0 孤儿 + doc_consistency 7/7 OK。
3. 2026-07-19 v5.35.1 全项目验收首轮修复 5 P0 + 1 P1 + 1 P2 + 50 测试：anti_raid 4 类断链 import 修复 + 36 模块批量修复断链 import + 36 模块 DB 三连修（表名复数 7 模块 20 处 + 25 张缺失表补 CREATE TABLE + 23 处 NOT NULL→允许 NULL）+ sales_repo.create_order 加 uuid 后缀防重复 + version.py 同步 v5.35.0 + README 数字修正 + 50 个回归测试。

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
