<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理 项目状态快照（覆盖式）

> 本文件每次整段覆盖对应区块，禁止无限追加。最后更新：2026-07-25。

## 一句话
Telegram 群组助手机器人 Mory小助理：人设对话、广告检测、群管、积分商城、转化漏斗、新闻播报、运营 Dashboard。单机 VPS 部署（systemd 唯一）。

## 模块状态表
| 模块 | 状态 | 入口文件 | 备注 |
|------|------|----------|------|
| 消息总分发 | 在用 | `core/message_dispatcher.py` | 9 个分发函数（8 定义 + 导入 `_dispatch_p10_ai`） |
| AI 回复 / 人设 | 在用 | `core/handlers/ai_reply_handler.py`、`core/ai_engine.py`、`core/persona_adapter.py` | 保留清冷/傲娇/温柔与群聊/私聊差异；同一用户/聊天最近30分钟3轮问答进入意图与模型并隔离缓存；普通聊天不按轮数硬推，低频推进只先到预览；价格/内容/权益→预览，明确购买/看过预览/明确定制→自助，拒绝和概念咨询无入口；近期 CTA 去重；私聊零按钮、群聊单目标；禁止虚构服务和动作旁白 |
| 模型路由 | 在用 | `core/model_router.py`、`core/ai_engine.py` | 单池模式（llm 主池）；配置无三层池时自动降级；局部 `MODE_ROUTING` 与默认映射合并；所有用户可见自然对话跳过 code/coder 专用模型；模型按到期日升序；`enable_thinking` 声明思考能力，实时场景跳过仅思考模型；到期/熔断/超时自动切换 + 黑名单 dirty 标记异步落盘 |
| 定时任务 | 在用 | `tasks/task_scheduler.py` 自动发现 `tasks/` 下 53 个 BaseTask 子类 | FAQ每日23:50汇总待优化问题与未命中样本；`modules/auto_tasks.py` 为 legacy（`_start_with_apscheduler` 死代码，仅保留部分工具函数） |
| 广告检测 | 在用 | `modules/ad_detector.py`、`modules/ad_marketing_patterns.py`、`modules/ai_advisor.py`、`modules/avatar_detector.py`、`core/handlers/security_handlers.py` | L0–L4 五层 + 营销话术 4 维度 71 条 + AI 辅助决策 4 函数（默认关闭） |
| 群管 / 积分 / 娱乐 | 在用 | `modules/*.py` | 135 个业务 `.py`（同步冲突副本不计入）；繁体“簽到”/QD提示使用无符号简体“签到”；签到开关与连续奖励兼容Dashboard新键和历史运行键 |
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
| 配置 / 部署 | 在用 | `core/settings.py`、`deploy_vps.py` + `config.json` | 密钥仅 `.env`；动态发布排除同步冲突副本并同步根目录六件套 |
| 转化漏斗 | 在用 | `social_repo.py` + `message_dispatcher` | `conversion_events` 各阶段 |
| 记忆 / 画像 | 在用 | `memory_summarizer.py`、`profile_learner.py` | `profile_learner` 的 `sticker` 维度未入库 |
| Rich Message | 在用 | `core/telebot_compat.py`、`core/broadcast_formatter.py` | 后台保留 10 条综合候选，用户只看 5 条精炼头条 + 1 句随机人设互动尾语；尾语不总结新闻，随机采用温情自白、邀聊、人格表达或定制沟通；卡片署名 `@MoryMateBot`，自助订阅按钮独立指向 `@MorychannelBot`；`EPHEMERAL_MESSAGE_ENABLED` 默认关闭 |
| 定点播报 | 在用 | `tasks/maintenance/scheduled_broadcast_task.py`、`modules/scheduled_broadcast.py` | 4 个时段：morning_nudge(10:00) / afternoon_tease(14:30) / evening_warm(19:00) / night_hook(22:30)；AI 失败回退可信底稿 |
| 关键话题回复 | 在用 | `modules/keyword_trigger.py` | 内置助理唤醒、签到积分福利、定制视频等人设化回答；福利/开通走自助售卖入口，定制确认走Mory联系入口；配置可同名覆盖或关闭 |

## 当前版本
v5.35.16（2026-07-25）

## 最近 3 条大事
1. 2026-07-25 v5.35.16 双项目人设与成交链统一：普通聊天不按轮数硬推；了解先预览、明确意向再自助；群承接不再额外轰炸私聊，入口单目标且不虚构服务。
2. 2026-07-25 v5.35.15 定制转化节奏收口：意图继续承接，但近期已给过下单入口时不重复 CTA；私聊零按钮，预览/下单/人工入口单轮互斥。
3. 2026-07-25 v5.35.14 AI 对话上下文与定制转化闭环：最近3轮真实问答进入意图、模型和缓存键；定制承接短句不再失忆。

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
