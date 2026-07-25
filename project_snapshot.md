<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理 项目状态快照（覆盖式）

> 本文件每次整段覆盖对应区块，禁止无限追加。最后更新：2026-07-25。

## 一句话
Telegram 群组助手机器人 Mory小助理：人设对话、广告检测、群管、积分商城、转化漏斗、新闻播报、运营 Dashboard。单机 VPS 部署（systemd 唯一）。

## 模块状态表
| 模块 | 状态 | 入口文件 | 备注 |
|------|------|----------|------|
| 消息总分发 | 在用 | `core/message_dispatcher.py` | 9 个分发函数（8 定义 + 导入 `_dispatch_p10_ai`） |
| AI 回复 / 人设 | 在用 | `core/handlers/ai_reply_handler.py`、`core/ai_engine.py`、`core/persona_adapter.py` | 保留清冷/傲娇/温柔与群聊/私聊差异；定时问候继承主助理身份/性格但不加载销售和效率指导；明显问题主动承接；FAQ未命中且AI无可靠答案时给联系Mory/自助下单双按钮并标记待优化；最终合同禁止动作旁白和虚构生活画面 |
| 模型路由 | 在用 | `core/model_router.py`、`core/ai_engine.py` | 单池模式（llm 主池）；配置无三层池时自动降级；局部 `MODE_ROUTING` 与默认映射合并；问候跳过 code/coder 专用模型；模型按到期日升序；`enable_thinking` 声明思考能力，实时场景跳过仅思考模型；到期/熔断/超时自动切换 + 黑名单 dirty 标记异步落盘 |
| 定时任务 | 在用 | `tasks/task_scheduler.py` 自动发现 `tasks/` 下 53 个 BaseTask 子类 | FAQ每日23:50汇总待优化问题与未命中样本；`modules/auto_tasks.py` 为 legacy（`_start_with_apscheduler` 死代码，仅保留部分工具函数） |
| 广告检测 | 在用 | `modules/ad_detector.py`、`modules/ad_marketing_patterns.py`、`modules/ai_advisor.py`、`modules/avatar_detector.py`、`core/handlers/security_handlers.py` | L0–L4 五层 + 营销话术 4 维度 71 条 + AI 辅助决策 4 函数（默认关闭） |
| 群管 / 积分 / 娱乐 | 在用 | `modules/*.py` | 135 个业务 `.py`；繁体“簽到”/QD提示使用无符号简体“签到”；签到开关与连续奖励兼容Dashboard新键和历史运行键 |
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
| Rich Message | 在用 | `core/telebot_compat.py`、`core/broadcast_formatter.py` | 后台保留 10 条综合候选，用户只看 5 条精炼头条 + 1 句随机人设互动尾语；尾语不总结新闻，随机采用温情自白、邀聊、人格表达或定制沟通；卡片署名 `@MoryMateBot`，自助订阅按钮独立指向 `@MorychannelBot`；`EPHEMERAL_MESSAGE_ENABLED` 默认关闭 |
| 定点播报 | 在用 | `tasks/maintenance/scheduled_broadcast_task.py`、`modules/scheduled_broadcast.py` | 4 个时段：morning_nudge(10:00) / afternoon_tease(14:30) / evening_warm(19:00) / night_hook(22:30)；AI 失败回退可信底稿 |
| 关键话题回复 | 在用 | `modules/keyword_trigger.py` | 内置助理唤醒、签到积分福利、定制视频等人设化回答；福利/开通走自助售卖入口，定制确认走Mory联系入口；配置可同名覆盖或关闭 |

## 当前版本
v5.35.13（2026-07-25）

## 最近 3 条大事
1. 2026-07-25 v5.35.13 新闻尾语改为随机人设互动并已部署生产：前5条只讲新闻，第6行禁止总结新闻，随机用温情自白、邀聊、人格表达或定制沟通立住小助理人设；双服务 active+enabled、health v5.35.13，管理员 Rich Message 验收消息 ID 2948。
2. 2026-07-25 v5.35.12 新闻与问候纠偏：卡片署名改为 `@MoryMateBot`；问候继承主助理人设、拒绝效率/技术文案并跳过 code/coder 模型。
3. 2026-07-25 v5.35.11 群聊问题自动承接：助理唤醒、签到积分福利和定制视频按人设自动回复；繁体签到/QD提示正确格式；FAQ真实命中修复，答不上来给双按钮并进入每日问题汇总。

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
