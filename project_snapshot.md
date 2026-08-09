<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理 项目状态快照（覆盖式）

> 本文件每次整段覆盖对应区块，禁止无限追加。最后更新：2026-08-09。

## 一句话
Telegram 群组助手机器人 Mory小助理：人设对话、广告检测、群管、积分商城、转化漏斗、传统文化栏目、运营 Dashboard。单机 VPS 部署（systemd 唯一）。

## 模块状态表（2026-08-05 更新）
| 模块 | 状态 | 入口文件 | 备注 |
|------|------|----------|------|
| 消息总分发 | 在用 | `core/message_dispatcher.py` | 9 个分发函数（8 定义 + 导入 `_dispatch_p10_ai`） |
| AI 回复 / 人设 | 在用 | `core/handlers/ai_reply_handler.py`、`core/ai_engine.py`、`core/persona_adapter.py` | ReplyContract v1 + 全类型语气合同：`casual/curiosity/flirt/challenge/emotional/convert` 六类均以温情托底，安全保留轻微绿茶感、俏皮和含蓄纯欲；群短私柔，正常追问不讽刺对呛；合同模式屏蔽旧毒舌/敷衍桶，FAQ/缓存/模型结果统一走动作旁白和敌意发送前门禁。普通聊天无 CTA，了解→预览，明确购买→自助；近期 CTA 去重；私聊零按钮、群聊单目标 |
| 模型路由 | 在用 | `core/model_router.py`、`core/ai_engine.py` | 单池模式（llm 主池）；配置无三层池时自动降级；局部 `MODE_ROUTING` 与默认映射合并；所有用户可见自然对话跳过 code/coder 专用模型；模型按到期日升序；`enable_thinking` 声明思考能力，实时场景跳过仅思考模型；到期/熔断/超时自动切换 + 黑名单 dirty 标记异步落盘 |
| 定时任务 | 在用 | `tasks/task_scheduler.py` 自动发现 45 个 BaseTask 子类、46 个静态调度项 | 健康检查按真实动态 key 和截止时间核对；重启从 `scheduler_metrics` 恢复累计与最近结果；SQLite/审计失败与任务正文异常上浮；多步骤任务独立执行后聚合失败；旧进程 running 与 task_log 原子回收；FAQ 空候选为 aborted；启动扫描在 scheduler/心跳之后的唯一 daemon 线程运行；`modules/auto_tasks.py` 为 legacy |
| 广告检测 | 在用 | `modules/ad_detector.py`、`modules/ad_patterns_encoded.py`、`modules/ad_profile_signals.py`、`modules/ad_enforcement.py`、`core/handlers/*` | L0–L4 五层；资料层读取显示名/username/Bio/Premium/个人关联频道，关联频道以平台暗语、拉群动作、商业招揽、频道载体的三锚点识别拆字与扩写；头像只作明确文字/二维码或相似证据；短句命中资料强证据时在 AI 前统一禁言、黑名单与删除当前消息；群管及配置白名单前置豁免，网络查询 unknown 不处罚；历史追溯只删逐条显式证据 |
| 群管 / 积分 / 娱乐 | 在用 | `modules/*.py` | 135 个业务 `.py`；繁体“簽到”兼容无符号简体“签到”；签到开关与连续奖励兼容Dashboard新键和历史键 |
| 销售中心 | 默认关闭 | `modules/sales_center.py`、`core/db_repos/sales_repo.py` | 商品/订单/销售漏斗/佣金，`SALES_CENTER_CONFIG.enabled` 开关 |
| 安全中心 | 默认关闭 | `modules/security_center.py` | 统一风险评分/自动分级处置，`SECURITY_CENTER_CONFIG.enabled` |
| 多群托管 | 默认关闭 | `modules/managed_groups.py` | 代运营/套餐管理/功能矩阵，`MANAGED_GROUPS_CONFIG.enabled` |
| 内容排查增强 | 默认关闭 | `modules/content_audit.py` | 文本/链接/文件/违规日志，`CONTENT_AUDIT_CONFIG.enabled` |
| 新成员数据图 | 默认关闭 | `modules/new_member_analytics.py` | 入群漏斗/来源分析/留存曲线/质量评估，`NEW_MEMBER_ANALYTICS.enabled` |
| 网编会员 | 默认关闭 | `modules/membership.py` | 付费等级/订阅管理/权益体系，`MEMBERSHIP_CONFIG.enabled` |
| 孤儿清理 | 在用 | `dashboard/api/orphan_api.py`、`tasks/maintenance/burn_orphan_task.py` | 端到端串联 |
| 入群验证 | 在用 | `modules/verification.py` | button / puzzle / timeout / max_attempts |
| Dashboard | 在用 | `dashboard/app.py`、`dashboard/api/*.py` | 164 个路由，端口 6616；传统文化页配置三档时间、单 CTA 轮换和私聊零 Token 占卜开关，栏目身份固定不可串台 |
| 数据库 | 在用 | `core/database.py`、`core/db_repos/*.py` | 173 张表；`reply_style_samples`=Alembic 0002；0003=业务上下文+转化状态；0004=任务执行历史，生产迁移表已验证存在 |
| 配置 / 部署 | 在用 | `core/settings.py`、`deploy_vps.py` + `config.json` | 密钥仅 `.env`；动态发布排除同步冲突副本和内部治理文档，部署前备份、失败保险恢复双服务；v5.38.22 新增 `scripts/check_config_sync.py` 三处同步差集断言（example ↔ 代码默认 ↔ ALLOWED_CONFIG_FIELDS），白名单补 MYSTIC/GREETING/SCHEDULED/NEWS/PROACTIVE 等 10 个业务键；历史（v5.38.16-21）：MAX_UPLOAD_FILE_SIZE/SKIP_PATH_FRAGMENTS/EXCLUDE_NAMES/ALLOWED_CONFIG_FIELDS 补项见 CHANGELOG |
| 转化漏斗 | 在用 | `social_repo.py` + `message_dispatcher` | `conversion_events` 各阶段 |
| 记忆 / 画像 | 在用 | `memory_summarizer.py`、`profile_learner.py` | `profile_learner` 的 `sticker` 维度未入库 |
| Rich Message / 图片卡 | 在用 | `core/telebot_compat.py`、`core/broadcast_formatter.py`、`core/broadcast_image_card.py`、`core/broadcast_image_payload.py`、`core/broadcast_cta.py` | v5.38.16：黄历/塔罗/易经公共 helper 去重 170 行；CTA label↔image_label 强绑定 + 清理全部 24 条 mystic contact/preview/subscribe img_label 遗留“· 点击头像”后缀；新增 greeting/scheduled × afternoon/night 四套时段 CTA 池；font() LRU(128)；11 处 PIL Image.close()；单 block 异常隔离占位；失败自动回退 Rich/HTML；字体兜底 Windows→Linux→仓库；README 新增图片卡章节；20 smoke 单测。v5.38.22：CTA 收敛为统一单一真相源（删旧 CTA 池/get_random_cta/cta_pool 死参/mystic 第二套 CTA，发送层统一生成回填）、四路开关收敛 `is_broadcast_image_enabled`、视觉常量对齐（CTA 圆角 18/标签 8）、缓存存在性短路 + 原子写、`_stable_seed` 改 md5 确定性 |
| 泛问候/定点播报 | 生产关闭 | `tasks/broadcast/greeting_task.py`、`tasks/maintenance/scheduled_broadcast_task.py` | 早午晚泛问候与 4 档定点播报全部关闭，避免与内容栏目重叠；若未来人工开启，问候模型失败直接跳过，不用固定套话，图片卡只渲染同源正文 |
| 传统文化播报 | 在用 | `tasks/broadcast/mystic_broadcast_task.py`、`tasks/support/mystic_content.py` | 生产唯一主动栏目：09:05 黄历、13:05 塔罗、20:35 易经；三档语义各异、间隔至少 4 小时，图片卡保留；新闻执行链已删除 |
| 关键话题回复 | 在用 | `modules/keyword_trigger.py` | 助理唤醒无 CTA；价格/内容/福利早路由只给预览；明确购买交给主成交链；私聊风水/塔罗/算卦请求在 LLM 前走本地日期稳定随机回复并记 0 Token；自动回复卡片 conversion_target=none 禁止按钮，仅未声明键才随机入口；opt_out 跳过关键词销售路由 |
| 自动沟通 | 默认克制 | `tasks/interaction/*.py`、`modules/group_mgr.py`、`modules/auto_tasks.py` | 欢迎群内一次预览、不主动私聊；传统文化栏目每卡至多一个配置化入口；非活跃/购物车/每周轻互动默认关闭，离群默认只记录 |
| 关联频道联动 | 生产开启 | `modules/linked_channel_sync.py` | 仅 `CHANNEL_IDS` 自有频道可信：保留群内转发、取消置顶、点赞、每帖至多一条匹配评论/彩虹屁，并在文本/媒体广告、反频道与 AI 前终止；外部频道不豁免 |

## 当前版本
v5.38.36（2026-08-09）· 生产真相审计与运行闭环加固

生产状态：**v5.38.36 已部署并验收**。双服务 active、NRestarts=0、health 200，VPS 代码与配置版本均一致；无操作热重载后仍为 40 个任务且只注册三档传统文化用户栏目，L4/L5 真实四态监控均为 OK，看门狗真实健康探针退出 0、失败计数归零。

## 最近 3 条大事
1. 2026-08-09 v5.38.36：调度热重载、任务四态监控、报表真相源与看门狗完成加固。
2. 2026-08-09 v5.38.35：个人资料关联频道纳入广告检测，覆盖拆字、改写和长段扩写。
3. 2026-08-09 v5.38.34：自有频道可信联动与广告首条/媒体检测链已部署验收。

## 客观指标（供 `scripts/doc_consistency.py` 断言，勿手改）
<!-- METRICS:BEGIN -->
modules_py=137
core_py=81
job_count=33
db_tables=173
dashboard_routes=164
dispatch_funcs=9
model_router_mappings=10
<!-- METRICS:END -->
