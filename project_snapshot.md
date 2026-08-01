<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理 项目状态快照（覆盖式）

> 本文件每次整段覆盖对应区块，禁止无限追加。最后更新：2026-08-01。

## 一句话
Telegram 群组助手机器人 Mory小助理：人设对话、广告检测、群管、积分商城、转化漏斗、传统文化栏目、运营 Dashboard。单机 VPS 部署（systemd 唯一）。

## 模块状态表
| 模块 | 状态 | 入口文件 | 备注 |
|------|------|----------|------|
| 消息总分发 | 在用 | `core/message_dispatcher.py` | 9 个分发函数（8 定义 + 导入 `_dispatch_p10_ai`） |
| AI 回复 / 人设 | 在用 | `core/handlers/ai_reply_handler.py`、`core/ai_engine.py`、`core/persona_adapter.py` | ReplyContract v1 + 全类型语气合同：`casual/curiosity/flirt/challenge/emotional/convert` 六类均以温情托底，安全保留轻微绿茶感、俏皮和含蓄纯欲；群短私柔，正常追问不讽刺对呛；合同模式屏蔽旧毒舌/敷衍桶，FAQ/缓存/模型结果统一走动作旁白和敌意发送前门禁。普通聊天无 CTA，了解→预览，明确购买→自助；近期 CTA 去重；私聊零按钮、群聊单目标 |
| 模型路由 | 在用 | `core/model_router.py`、`core/ai_engine.py` | 单池模式（llm 主池）；配置无三层池时自动降级；局部 `MODE_ROUTING` 与默认映射合并；所有用户可见自然对话跳过 code/coder 专用模型；模型按到期日升序；`enable_thinking` 声明思考能力，实时场景跳过仅思考模型；到期/熔断/超时自动切换 + 黑名单 dirty 标记异步落盘 |
| 定时任务 | 在用 | `tasks/task_scheduler.py` 自动发现 `tasks/` 下 45 个 BaseTask 子类、50 个调度项 | 09:05 今日黄历、13:05 三张塔罗、20:35 易经一卦取代新闻，旧定向塔罗不再注册；FAQ每日23:50汇总；短期业务原文每分钟清理；启动时先持久化心跳并启动 scheduler，再由唯一 daemon 线程串行执行成员扫描和历史清理，避免耗时扫描触发 health 503 与 watchdog 误重启；`modules/auto_tasks.py` 为 legacy |
| 广告检测 | 在用 | `modules/ad_detector.py`、`modules/ad_patterns_encoded.py`、`modules/ad_marketing_patterns.py`、`modules/ai_advisor.py`、`modules/avatar_detector.py`、`core/handlers/security_handlers.py`、`core/handlers/member_handlers.py` | L0–L4 五层；入群显示名/username、Bio、Premium emoji 状态和头像任一高置信命中即统一处置，验证码解限后补审延迟 Bio/头像；头像只采纳明确暴露、广告文字/二维码或批量相似证据，弱视觉统计不定罪；消息层覆盖 QQ 数字群号、露出邀约 q裙色情招揽及彩票代称+货量+庄家交易三要素，拆字与正反语序受限，新闻教学、户外摄影和实物履约冲突语境放行；外部 SPB 单探针熔断失败降级，本地规则继续执行；数据库追溯只删除当前窗口内有明确广告证据的消息 |
| 群管 / 积分 / 娱乐 | 在用 | `modules/*.py` | 135 个业务 `.py`（同步冲突副本不计入）；繁体“簽到”/QD提示使用无符号简体“签到”；签到开关与连续奖励兼容Dashboard新键和历史运行键 |
| 销售中心 | 默认关闭 | `modules/sales_center.py`、`core/db_repos/sales_repo.py` | 商品/订单/销售漏斗/佣金，`SALES_CENTER_CONFIG.enabled` 开关 |
| 安全中心 | 默认关闭 | `modules/security_center.py` | 统一风险评分/自动分级处置，`SECURITY_CENTER_CONFIG.enabled` 开关 |
| 多群托管 | 默认关闭 | `modules/managed_groups.py` | 代运营/套餐管理/功能矩阵，`MANAGED_GROUPS_CONFIG.enabled` 开关 |
| 内容排查增强 | 默认关闭 | `modules/content_audit.py` | 文本/链接/文件/违规日志，`CONTENT_AUDIT_CONFIG.enabled` 开关 |
| 新成员数据图 | 默认关闭 | `modules/new_member_analytics.py` | 入群漏斗/来源分析/留存曲线/质量评估，`NEW_MEMBER_ANALYTICS.enabled` 开关 |
| 网编会员 | 默认关闭 | `modules/membership.py` | 付费等级/订阅管理/权益体系，`MEMBERSHIP_CONFIG.enabled` 开关 |
| 孤儿清理 | 在用 | `orphan_api.py`、`burn_orphan_task.py` | 端到端串联 |
| 入群验证 | 在用 | `modules/verification.py` | button / puzzle / timeout / max_attempts |
| Dashboard | 在用 | `dashboard/app.py`、`dashboard/api/*.py` | 163 个路由，端口 6616；传统文化页配置三档时间、单 CTA 轮换和私聊零 Token 占卜开关，栏目身份固定不可串台 |
| 数据库 | 在用 | `core/database.py`、`core/db_repos/*.py` | 173 张表；`reply_style_samples` 由 Alembic 0002 管理；0003 增加短期业务上下文与结构化转化状态；0004 增加任务执行历史，生产迁移表已验证存在 |
| 配置 / 部署 | 在用 | `core/settings.py`、`deploy_vps.py` + `config.json` | 密钥仅 `.env`；动态发布排除同步冲突副本和内部治理文档，部署前备份、失败保险恢复双服务；依赖预检包含 NudeNet/ONNX/OpenCV |
| 转化漏斗 | 在用 | `social_repo.py` + `message_dispatcher` | `conversion_events` 各阶段 |
| 记忆 / 画像 | 在用 | `memory_summarizer.py`、`profile_learner.py` | `profile_learner` 的 `sticker` 维度未入库 |
| Rich Message | 在用 | `core/telebot_compat.py`、`core/broadcast_formatter.py` | 黄历、三张塔罗、易经使用分区 HTML/Rich 卡片；正文有元信息、主题块和组合解读，不重复显示免责声明；每天三档轮换单 CTA，卡片署名 `@MoryMateBot`；`EPHEMERAL_MESSAGE_ENABLED` 默认关闭 |
| 定点播报 | 在用 | `tasks/maintenance/scheduled_broadcast_task.py`、`modules/scheduled_broadcast.py` | 4 个时段；早晚正文无按钮，午后/睡前如带入口只到预览；AI 失败回退可信底稿 |
| 关键话题回复 | 在用 | `modules/keyword_trigger.py` | 助理唤醒无 CTA；价格/内容/福利早路由只给预览；明确购买交给主成交链；私聊明确风水/塔罗/算卦请求在 LLM 前走本地日期稳定随机回复并记 0 Token，普通讨论不抢答 |
| 自动沟通 | 默认克制 | `tasks/interaction/*.py`、`modules/group_mgr.py`、`modules/auto_tasks.py` | 欢迎群内一次预览、不主动私聊；传统文化栏目每卡至多一个配置化入口；非活跃/购物车/每周轻互动默认关闭，离群默认只记录；legacy 与 modular 路径一致 |

## 当前版本
v5.38.12（2026-08-01）

生产状态：v5.38.12 已上线；三条生产漏判原文已统一处置为 Telegram 永久限制、本地/全局黑名单和永久禁言记录，消息快照均为广告且已删除。生产 7 条广告/7 条正常反例与 32 线程外部故障熔断探针通过。服务器日志另发现 3979 人同步启动扫描曾令数据库心跳超过 120 秒并触发 watchdog 误重启；scheduler 优先、即时持久心跳和后台维护修复已部署，131 秒内 14/14 次 health 200、Bot PID 不变，19:40/19:42 两轮独立 watchdog 均健康且失败计数为 0，当前进程 error 日志为空。

## 最近 3 条大事
1. 2026-08-01 v5.38.12 覆盖新澳门六叔公、新澳六彩盒和露出邀约 q裙群号等局部三要素变体，为外部 SPB 增加线程安全单探针熔断，并将启动扫描移到 scheduler/心跳之后的后台线程。
2. 2026-07-30 v5.38.11 覆盖 QQ 群数字联系方式与 q裙/扣郡关系招揽变体，歧义谐音要求第二广告锚点。
3. 2026-07-30 v5.38.10 六类群自动回复统一温情、轻微绿茶感、俏皮和含蓄纯欲合同，屏蔽旧敌意桶并统一发送前门禁。

## 客观指标（供 `scripts/doc_consistency.py` 断言，勿手改）
<!-- METRICS:BEGIN -->
modules_py=135
core_py=78
job_count=36
db_tables=173
dashboard_routes=163
dispatch_funcs=9
model_router_mappings=10
<!-- METRICS:END -->
