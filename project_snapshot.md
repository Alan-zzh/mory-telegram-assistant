<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理 项目状态快照（覆盖式）

> 本文件每次整段覆盖对应区块，禁止无限追加。最后更新：2026-08-31。

## 一句话
Telegram 群组助手机器人 Mory小助理：人设对话、广告检测、群管、积分商城、转化漏斗、传统文化栏目、运营 Dashboard。单机 VPS 部署（systemd 唯一）。

## 模块状态表（2026-08-05 更新）
| 模块 | 状态 | 入口文件 | 备注 |
|------|------|----------|------|
| 消息总分发 | 在用 | `core/message_dispatcher.py` | 10 个分发函数（9 定义 + 导入 `_dispatch_p10_ai`） |
| AI 回复 / 人设 | 在用 | `core/handlers/ai_reply_handler.py`、`core/ai_engine.py`、`core/persona_adapter.py` | ReplyContract v1 + 全类型语气合同：`casual/curiosity/flirt/challenge/emotional/convert` 六类均以温情托底，安全保留轻微绿茶感、俏皮和含蓄纯欲；群短私柔，正常追问不讽刺对呛；普通聊天无 CTA，了解→预览，明确购买→自助；近期 CTA 去重；私聊零按钮、群聊单目标。风格参考仅限当前场景，含价格、权益、联系方式、保证性事实或 CTA 的样本不进入普通 AI 提示 |
| 模型路由 | 在用 | `core/model_router.py`、`core/ai_engine.py` | 当前唯一池为9个文本型号+`qwen3.5-ocr`；严格按到期日升序且同日保留配置顺序；思考型按声明调用。超时、限流和服务异常仅进程内熔断并自动回首选，只有明确额度耗尽永久拉黑；当前索引只认配置，不从数据库复活旧值 |
| 定时任务 | 在用 | `tasks/task_scheduler.py` 自动发现 45 个 BaseTask 子类（AST 实测，doc_consistency 断言）；`start_background` 引擎同文件 | 健康检查按真实动态 key 和截止时间核对；重启从 `scheduler_metrics` 恢复累计与最近结果；SQLite/审计失败与任务正文异常上浮；多步骤任务独立执行后聚合失败；旧进程 running 与 task_log 原子回收；FAQ 空候选为 aborted；启动扫描在 scheduler/心跳之后的唯一 daemon 线程运行；legacy `modules/auto_tasks.py` 已于 v5.38.69 拆除收敛 |
| 广告检测 | 在用 | `modules/ad_detector.py`、`modules/ad_patterns_encoded.py`、`modules/ad_profile_signals.py`、`modules/ad_enforcement.py`、`modules/member_ad_scan.py`、`core/handlers/*` | 歧义联系方式仅作弱信号；看简介头像仅与绑定频道的群演招募三锚点联合处置，普通招聘资讯放行；处置事件保留首次根因，高风险/未知状态拒绝自动恢复 |
| 群管 / 积分 / 娱乐 | 在用 | `modules/*.py` | 102 个业务 `.py`（含子目录，与 METRICS 一致）；繁体“簽到”兼容无符号简体“签到”；已删除无入口的空报表模块与开关 |
| 销售中心 | 默认关闭 | `modules/sales_center.py`、`core/db_repos/sales_repo.py` | 仅管理员商品管理（/sales 别名 handle_admin_cmd），无用户侧触发；不在 Bot 内收款，咨询承接统一走单目标漏斗 |
| 安全中心 | 默认关闭 | `modules/security_center.py` | 统一风险评分/自动分级处置，`SECURITY_CENTER_CONFIG.enabled` |
| 多群托管 | 默认关闭 | `modules/managed_groups.py` | 代运营/套餐管理/功能矩阵，`MANAGED_GROUPS_CONFIG.enabled` |
| 内容排查增强 | 默认关闭 | `modules/content_audit.py` | 文本/链接/文件/违规日志，`CONTENT_AUDIT_CONFIG.enabled` |
| 新成员数据图 | 默认关闭 | `modules/new_member_analytics.py` | 入群漏斗/来源分析/留存曲线/质量评估，`NEW_MEMBER_ANALYTICS.enabled` |
| 网编会员 | 默认关闭 | `modules/membership.py` | 付费等级/订阅管理/权益体系，`MEMBERSHIP_CONFIG.enabled` |
| 孤儿清理 | 在用 | `dashboard/api/orphan_api.py`、`tasks/maintenance/burn_orphan_task.py` | 端到端串联 |
| 关键词延迟删 | 生产开启 | `modules/keyword_auto_delete.py`、`tasks/maintenance/keyword_message_auto_delete_task.py` | 生产精确匹配 `/me@afoolGroupBot` 并延迟 300 秒删除；SQLite 队列支持重启恢复，只删消息不处罚用户 |
| 入群验证 | 在用 | `modules/verification.py` | button / puzzle / timeout / max_attempts |
| Dashboard | 在用 | `dashboard/app.py`、`dashboard/api/*.py` | 163 个路由，端口 6616；健康未知不打分，历史调度不冒充当前注册清单 |
| 数据库 | 在用 | `core/database.py`、`core/db_repos/*.py` | 181 张表；运行时 DDL 收归 `core/database.py`，Alembic 0009 升级旧库并把 `funnel_state` 改为 `(uid, bot_id)` 复合主键；业务模块不再按请求懒建表 |
| 配置 / 部署 | 在用 | `core/settings.py`、`deploy_vps.py` + `config.json` | 密钥仅 `.env`；安全合并保护线上凭据，不上传数据库；部署源必须包含当前 main；Alembic 清除继承的 `DATABASE_URL` 并精确绑定生产 `mory.db`，迁移前生成随机名 0600 在线快照并校验完整性/外键，任一步失败即阻断；运行态验证失败时要求受控人工回滚 |
| 转化漏斗 | 在用 | `core/db_repos/social_repo.py` + `message_dispatcher` | `conversion_events` 各阶段 |
| 记忆 / 画像 | 在用 | `core/memory_summarizer.py`、`core/profile_learner.py` | `profile_learner` 的 sticker 维度显式未启用（`STICKER_DIMENSION_ENABLED=False`，仅内存统计不持久化） |
| Rich Message / 图片卡 | 在用 | `core/telegram_send_utils.py`、`core/broadcast_image_card.py`、`core/start_welcome_card.py`、`modules/private_preset_media.py` | `/start` 与群首次精确 @ 共用六套欢迎卡；普通用户私聊索图使用审核静态照片，原味/本人/普通照片分流，福利内容先文字后随机图；群聊与管理员不触发私聊媒体 |
| 泛问候/定点播报 | 生产关闭 | `tasks/broadcast/greeting_task.py`、`tasks/maintenance/scheduled_broadcast_task.py` | 早午晚泛问候与 4 档定点播报全部关闭，避免与内容栏目重叠；若未来人工开启，问候模型失败直接跳过，不用固定套话，图片卡只渲染同源正文 |
| 传统文化播报 | 在用 | `tasks/broadcast/mystic_broadcast_task.py`、`tasks/support/mystic_content.py` | 生产唯一主动栏目：09:05 黄历、13:05 塔罗、20:35 易经；三档语义各异、间隔至少 4 小时，图片卡保留；新闻执行链已删除；v5.40.0 新增易经经典句/值神浅释/吉时参考/免责尾注/塔罗框架轮换/私聊敏感分流，全部默认关闭待逐项开启 |
| 关键话题回复 | 在用 | `modules/keyword_trigger.py` | 进群、包年、预览、已购定制、联系Mory等审核问答按完整意图命中；签到积分只认生产配置白名单，未配置变体记 delegated 后退出，不进入AI或Mory优化统计；预设送达后记录来源；none/preview/subscribe 单目标 |
| 自动沟通 | 默认克制 | `tasks/interaction/*.py`、`modules/group_mgr.py` | 欢迎群内一次预览、不主动私聊；传统文化栏目允许 1-2 个同目标不重复入口；新闻执行链和配置入口已删除（legacy `auto_tasks.py` 已于 v5.38.69 拆除） |
| 关联频道联动 | 生产开启 | `modules/linked_channel_sync.py` | 仅 `CHANNEL_IDS` 自有频道可信：群自动转发即取消置顶并按文案选择私聊/订阅单入口，可回复审核营销图卡；回复目标消失时无引用直发，日志按实际媒体/文本记账；外部频道不豁免 |

## 当前版本
v5.42.8（2026-08-31）· 待部署：SSH key-first 回退、sudo 失败关闭与巡检入口统一

生产状态：**Mory 当前仍为 v5.42.4，v5.42.8 发布门禁已打开：双服务 active、NRestarts=0、health 200、数据库完整。Steel 以 PID 1 环境和真实拒绝日志确认客户页上限 2；连续 60 分钟以上 `oom=0/oom_kill=0/swap=0`，客户页稳定为 2，第三页被拒绝；3000 仅本机/容器桥，9224 仅实测合法来源和本机/容器桥，规则已持久化。**

## 最近 3 条大事
1. 2026-08-31 v5.42.8：Steel 双客户页与访问边界通过生产稳定门禁。
2. 2026-08-31 v5.42.8：SSH key-first 回退与 sudo 失败关闭完成。
3. 2026-08-31 v5.42.7：SSH root 无 PTY、引用与输出脱敏修复完成。

## 客观指标（供 `scripts/doc_consistency.py` 断言，勿手改）
<!-- METRICS:BEGIN -->
modules_py=102
core_py=77
db_tables=181
dashboard_routes=163
dispatch_funcs=10
model_router_mappings=10
base_task_subclasses=45
<!-- METRICS:END -->
