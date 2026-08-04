<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理 项目状态快照（覆盖式）

> 本文件每次整段覆盖对应区块，禁止无限追加。最后更新：2026-08-05。

## 一句话
Telegram 群组助手机器人 Mory小助理：人设对话、广告检测、群管、积分商城、转化漏斗、传统文化栏目、运营 Dashboard。单机 VPS 部署（systemd 唯一）。

## 模块状态表（2026-08-05 更新）
| 模块 | 状态 | 入口文件 | 备注 |
|------|------|----------|------|
| 消息总分发 | 在用 | `core/message_dispatcher.py` | 9 个分发函数（8 定义 + 导入 `_dispatch_p10_ai`） |
| AI 回复 / 人设 | 在用 | `core/handlers/ai_reply_handler.py`、`core/ai_engine.py`、`core/persona_adapter.py` | ReplyContract v1 + 全类型语气合同：`casual/curiosity/flirt/challenge/emotional/convert` 六类均以温情托底，安全保留轻微绿茶感、俏皮和含蓄纯欲；群短私柔，正常追问不讽刺对呛；合同模式屏蔽旧毒舌/敷衍桶，FAQ/缓存/模型结果统一走动作旁白和敌意发送前门禁。普通聊天无 CTA，了解→预览，明确购买→自助；近期 CTA 去重；私聊零按钮、群聊单目标 |
| 模型路由 | 在用 | `core/model_router.py`、`core/ai_engine.py` | 单池模式（llm 主池）；配置无三层池时自动降级；局部 `MODE_ROUTING` 与默认映射合并；所有用户可见自然对话跳过 code/coder 专用模型；模型按到期日升序；`enable_thinking` 声明思考能力，实时场景跳过仅思考模型；到期/熔断/超时自动切换 + 黑名单 dirty 标记异步落盘 |
| 定时任务 | 在用 | `tasks/task_scheduler.py` 自动发现 45 个 BaseTask 子类、46 个静态调度项 | 健康检查按真实动态 key 和截止时间核对；重启从 `scheduler_metrics` 恢复累计与最近结果；SQLite/审计失败与任务正文异常上浮；多步骤任务独立执行后聚合失败；旧进程 running 与 task_log 原子回收；FAQ 空候选为 aborted；启动扫描在 scheduler/心跳之后的唯一 daemon 线程运行；`modules/auto_tasks.py` 为 legacy |
| 广告检测 | 在用 | `modules/ad_detector.py`、`modules/ad_patterns_encoded.py`、`modules/ai_advisor.py`、`modules/avatar_detector.py`、`core/handlers/*` | L0–L4 五层；入群四信号（显示名/username/Bio/头像 + Premium）任一高置信命中即统一处置，验证码解限后补审延迟 Bio/头像；头像只采纳明确暴露、广告文字/二维码或批量相似证据，弱视觉统计不定罪；消息层覆盖 QQ 数字群号、露出邀约 q裙色情招揽及彩票代称+货量+庄家交易三要素；外部 SPB 单探针熔断失败降级；追溯只删当前窗口内显式广告证据；v5.38.21 起 `enforce_ad_user` 统一处置链群内管理员/群主豁免（不禁言/不黑名单/不删消息/不清反应）；v5.38.22 加配置级 `ADMIN_IDS/ADMIN_ID` 白名单豁免前置（零网络）与 `get_chat_member` 失败三态降级（unknown 跳过不可逆惩罚 + 通知人工复核），启动追溯对跳过不再误报"禁言失败"，入群资料检测路径补 `_is_member_ad_exempt` 豁免前置；拼音检测增加中文字符过滤 |
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
| 定点播报 | 在用 | `tasks/maintenance/scheduled_broadcast_task.py`、`modules/scheduled_broadcast.py` | 4 个时段；早晚正文无按钮，午后/睡前如带入口只到预览；AI 失败回退可信底稿；v5.38.16 CTA 支持 afternoon/night 精确池 |
| 传统文化播报 | 在用 | `tasks/broadcast/mystic_broadcast_task.py`、`tasks/support/mystic_content.py` | 早 09:05 风水黄历(almanac)/午 13:05 塔罗(tarot)/晚 20:35 易经(iching)；v5.37.0 替换原新闻播报；v5.38.20 修复 MYSTIC.enabled 配置脏状态(07-30 起误关致停摆 5 天已恢复)；NewsTask 代码已删，NEWS_BROADCAST_CONFIG.enabled 残留已清理为 false |
| 关键话题回复 | 在用 | `modules/keyword_trigger.py` | 助理唤醒无 CTA；价格/内容/福利早路由只给预览；明确购买交给主成交链；私聊风水/塔罗/算卦请求在 LLM 前走本地日期稳定随机回复并记 0 Token |
| 自动沟通 | 默认克制 | `tasks/interaction/*.py`、`modules/group_mgr.py`、`modules/auto_tasks.py` | 欢迎群内一次预览、不主动私聊；传统文化栏目每卡至多一个配置化入口；非活跃/购物车/每周轻互动默认关闭，离群默认只记录 |

## 当前版本
v5.38.24（2026-08-05）· 遗留事项闭环（mypy 债务清零/sanitize 自愈生效/文档治理/垃圾清理）后增量部署 VPS

生产状态：**v5.38.24 已增量部署 VPS 并验收通过**（双服务 active、health 200、生产版本 v5.38.24、Bot 心跳任务正常运行）。本地验收：全仓 pytest 863 passed/7 skipped、flake8 8 文件清单 0 错、mypy 4 文件（含 ai_engine.py）通过、verify_db_methods 199/199、doc_consistency 通过。上一版 v5.38.23 已完成 VPS 增量部署并验收通过（双服务 active、health 200）。

## 最近 3 条大事
1. 2026-08-05 v5.38.24 遗留事项闭环 + 治理：ai_engine.py 10 项 mypy 类型债务清零并纳入 CI；sanitize 自愈参数失效彻底修复（降温度+约束注入下沉到 payload 构建点，回归测试断言载荷）；get_pool_info 补回归测试；文档治理（README 版本、9 篇 technical 头部声明、orphan-cleanup/write-queue-batch 过时内容、vision 数字、archive 索引、snapshot 路径）；垃圾清理（本地 _quarantine/backup 旧备份/logs 旧日志/runtime 杂物/pycache 186 个；VPS 部署残留与旧日志 41 项）；上下文泄漏评估结论记录（低风险）。
2. 2026-08-05 v5.38.23 Harness 审查六项修复：CI 门禁断链修复（失效文件引用移除、database.py/ai_engine.py 纳入 flake8、verify_db_methods/doc_consistency 接入 CI、--fail-under=25）；ai_engine 输出门禁状态残留三路径清理（含 get_pool_info 隐藏 NameError 修复）；.venv 重建 3.12.10；request_id 日志关联键贯穿失败链。
3. 2026-08-05 v5.38.22 四项整改收尾：CTA 三套真相源收敛为统一 `core/broadcast_cta.py` 单一真相源（删旧 CTA 池/死参/mystic 第二套 CTA，发送层统一生成回填）+ 四路图片卡开关收敛 + 视觉常量对齐 + 缓存短路/原子写/确定性种子；广告处置配置级白名单豁免前置 + `get_chat_member` 失败三态降级 + 启动追溯跳过计数修正 + 入群检测豁免拉齐；新增 `scripts/check_config_sync.py` 三处同步差集断言 + 白名单补 10 业务键；AI_DEBUG_HISTORY 归档 362→93 行、CHANGELOG 近期超长条目压缩。
4. 2026-08-05 v5.38.21 广告处置群管豁免（热修）：`enforce_ad_user` 统一处置链顶部新增 `_is_chat_admin_member`（`bot.get_chat_member` 查 status ∈ administrator/creator），群内管理/群主直接返回 `skipped_reason=admin_or_creator`，不做永久禁言、双黑名单、删消息、清反应；查询失败按非管理继续处置不放过可疑号。覆盖 message_dispatcher / member_handlers / security_handlers / ad_detector 启动追溯 / group_mgr / auto_tasks / startup_member_scan_task 全部调用链（此前仅入群检测处豁免）。生产实例：群管 1193526296 因资料命中 t.me/morychat 被误封禁言+黑名单+删消息。新增单测断言管理不删消息/不禁言/不写黑名单。
5. 2026-08-04 v5.38.20 Graph Mode 第四轮 4 维度补扫残余漏洞闭环（4 维度残余：PII 泄露/裸 except/三处同步 ALLOWED_CONFIG_FIELDS 差集/SQL 注入 0 命中），落地 5 P0+9 P1+2 P2 最小加固：① P0 faq_api 11 端点 f"失败：{e}" HTTP 明文响应全换固定文案 + logger.exception；health_api 6 处 score.detail / audit 缺失键样本明文外泄全治（integrity: {r}、f"检查失败: {e}"×4、missing[:5] 样本外泄）；② P1 裸 except 残余清场：weekly/monthly 2 处周报月报群人数回退裸 except 清掉 + health_api 7 处 except 无绑定无日志补 as e + logger.debug；③ P2 三处同步第三处 BROADCAST_IMAGE_CARD_ENABLED、BROADCAST_THEME_ENABLED 加入 ALLOWED_CONFIG_FIELDS 白名单（播报图片卡 v5.38.16 配置键三处同步闭环）；SQL 注入维度全仓 0 项命中（未发现 .execute() 中 f-string/格式化字符串非 ? 占位）。

## 客观指标（供 `scripts/doc_consistency.py` 断言，勿手改）
<!-- METRICS:BEGIN -->
modules_py=135
core_py=81
job_count=36
db_tables=173
dashboard_routes=164
dispatch_funcs=9
model_router_mappings=10
<!-- METRICS:END -->
