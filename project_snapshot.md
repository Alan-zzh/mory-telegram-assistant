<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理 项目状态快照（覆盖式）

> 本文件每次整段覆盖对应区块，禁止无限追加。最后更新：2026-07-28。

## 一句话
Telegram 群组助手机器人 Mory小助理：人设对话、广告检测、群管、积分商城、转化漏斗、传统文化栏目、运营 Dashboard。单机 VPS 部署（systemd 唯一）。

## 模块状态表
| 模块 | 状态 | 入口文件 | 备注 |
|------|------|----------|------|
| 消息总分发 | 在用 | `core/message_dispatcher.py` | 9 个分发函数（8 定义 + 导入 `_dispatch_p10_ai`） |
| AI 回复 / 人设 | 在用 | `core/handlers/ai_reply_handler.py`、`core/ai_engine.py`、`core/persona_adapter.py` | ReplyContract v1：公开 Mory 小助理身份，清醒/温柔/小傲娇与群/私差异；普通聊天无 CTA，价格/内容/权益→预览，明确购买/看过预览/明确定制→自助；“怎么订阅”等明确入口问法跳过旧 P7.5 旁路并结合近期预览直接承接；近期 CTA 去重；私聊零按钮、群聊单目标；禁止虚构事实、动作场景、假稀缺和社会证明 |
| 模型路由 | 在用 | `core/model_router.py`、`core/ai_engine.py` | 单池模式（llm 主池）；配置无三层池时自动降级；局部 `MODE_ROUTING` 与默认映射合并；所有用户可见自然对话跳过 code/coder 专用模型；模型按到期日升序；`enable_thinking` 声明思考能力，实时场景跳过仅思考模型；到期/熔断/超时自动切换 + 黑名单 dirty 标记异步落盘 |
| 定时任务 | 在用 | `tasks/task_scheduler.py` 自动发现 `tasks/` 下 45 个 BaseTask 子类、50 个调度项 | 09:05 今日黄历、13:05 三张塔罗、20:35 易经一卦取代新闻，旧定向塔罗不再注册；FAQ每日23:50汇总；短期业务原文每分钟清理；`modules/auto_tasks.py` 为 legacy |
| 广告检测 | 在用 | `modules/ad_detector.py`、`modules/ad_patterns_encoded.py`、`modules/ad_marketing_patterns.py`、`modules/ai_advisor.py`、`modules/avatar_detector.py`、`core/handlers/security_handlers.py`、`core/handlers/member_handlers.py` | L0–L4 五层；入群显示名/username、Bio、Premium emoji 状态和头像任一高置信命中即统一处置，验证码解限后补审延迟 Bio/头像；头像主体使用本地 NudeNet 明确暴露类别，营销文字用 OCR，证据不足不封；数据库追溯只删除当前窗口内有明确广告证据的消息；NFKC + 上下文受限模板覆盖六类数字/字母拆字 |
| 群管 / 积分 / 娱乐 | 在用 | `modules/*.py` | 135 个业务 `.py`（同步冲突副本不计入）；繁体“簽到”/QD提示使用无符号简体“签到”；签到开关与连续奖励兼容Dashboard新键和历史运行键 |
| 销售中心 | 默认关闭 | `modules/sales_center.py`、`core/db_repos/sales_repo.py` | 商品/订单/销售漏斗/佣金，`SALES_CENTER_CONFIG.enabled` 开关 |
| 安全中心 | 默认关闭 | `modules/security_center.py` | 统一风险评分/自动分级处置，`SECURITY_CENTER_CONFIG.enabled` 开关 |
| 多群托管 | 默认关闭 | `modules/managed_groups.py` | 代运营/套餐管理/功能矩阵，`MANAGED_GROUPS_CONFIG.enabled` 开关 |
| 内容排查增强 | 默认关闭 | `modules/content_audit.py` | 文本/链接/文件/违规日志，`CONTENT_AUDIT_CONFIG.enabled` 开关 |
| 新成员数据图 | 默认关闭 | `modules/new_member_analytics.py` | 入群漏斗/来源分析/留存曲线/质量评估，`NEW_MEMBER_ANALYTICS.enabled` 开关 |
| 网编会员 | 默认关闭 | `modules/membership.py` | 付费等级/订阅管理/权益体系，`MEMBERSHIP_CONFIG.enabled` 开关 |
| 孤儿清理 | 在用 | `orphan_api.py`、`burn_orphan_task.py` | 端到端串联 |
| 入群验证 | 在用 | `modules/verification.py` | button / puzzle / timeout / max_attempts |
| Dashboard | 在用 | `dashboard/app.py`、`dashboard/api/*.py` | 162 个路由，端口 6616；传统文化页配置三档时间、单 CTA 轮换和私聊零 Token 占卜开关，栏目身份固定不可串台 |
| 数据库 | 在用 | `core/database.py`、`core/db_repos/*.py` | 170 张表；`reply_style_samples` 由 Alembic 0002 管理；0003 增加独立的 30 分钟短期业务上下文与结构化转化状态，使进化遥测关闭原文后仍可跨重启承接、CTA 去重和持久拒绝 |
| 配置 / 部署 | 在用 | `core/settings.py`、`deploy_vps.py` + `config.json` | 密钥仅 `.env`；动态发布排除同步冲突副本并同步根目录六件套；依赖预检包含 NudeNet/ONNX/OpenCV，避免头像模型缺包却误报依赖已满足 |
| 转化漏斗 | 在用 | `social_repo.py` + `message_dispatcher` | `conversion_events` 各阶段 |
| 记忆 / 画像 | 在用 | `memory_summarizer.py`、`profile_learner.py` | `profile_learner` 的 `sticker` 维度未入库 |
| Rich Message | 在用 | `core/telebot_compat.py`、`core/broadcast_formatter.py` | 黄历、三张塔罗、易经使用分区 HTML/Rich 卡片；正文有元信息、主题块和组合解读，不重复显示免责声明；每天三档轮换单 CTA，卡片署名 `@MoryMateBot`；`EPHEMERAL_MESSAGE_ENABLED` 默认关闭 |
| 定点播报 | 在用 | `tasks/maintenance/scheduled_broadcast_task.py`、`modules/scheduled_broadcast.py` | 4 个时段；早晚正文无按钮，午后/睡前如带入口只到预览；AI 失败回退可信底稿 |
| 关键话题回复 | 在用 | `modules/keyword_trigger.py` | 助理唤醒无 CTA；价格/内容/福利早路由只给预览；明确购买交给主成交链；私聊明确风水/塔罗/算卦请求在 LLM 前走本地日期稳定随机回复并记 0 Token，普通讨论不抢答 |
| 自动沟通 | 默认克制 | `tasks/interaction/*.py`、`modules/group_mgr.py`、`modules/auto_tasks.py` | 欢迎群内一次预览、不主动私聊；传统文化栏目每卡至多一个配置化入口；非活跃/购物车/每周轻互动默认关闭，离群默认只记录；legacy 与 modular 路径一致 |

## 当前版本
v5.38.8（2026-07-28）

生产状态：生产为 v5.38.8（可信提交 `715f430`，备份 `/home/ubuntu/mory_assistant/backups/deploy_v5388_20260729_004405`）；18/18 文件哈希一致，双服务 active+enabled、NRestarts=0、health v5.38.8、当前进程高严重日志为空。本地专项 34 passed、整仓 585 passed / 7 skipped、DB 190/190、文档 7/7。生产正例名字/Bio/真实头像命中，正常神兽/景区/纯色头像放行；截图用户资料 `score=3`，NudeNet 命中三项明确暴露并输出 `score=2`，已真实 restricted，`blacklist` / `global_blacklist` / `mute_records` 均为 1。

## 最近 3 条大事
1. 2026-07-28 v5.38.8 接通入群四类资料信号、验证码解限补审和真正本地 NudeNet 头像主体识别。
2. 2026-07-28 v5.38.7 新增六类上下文受限广告变体模板，歧义词需第二锚点并收紧“上门”误封。
3. 2026-07-28 v5.38.6 修复“一日 9Oo+ / 4oO+”混写日收益广告漏判并收紧日常计量反误封边界。

## 客观指标（供 `scripts/doc_consistency.py` 断言，勿手改）
<!-- METRICS:BEGIN -->
modules_py=135
core_py=77
job_count=50
db_tables=170
dashboard_routes=162
dispatch_funcs=9
model_router_mappings=10
<!-- METRICS:END -->
