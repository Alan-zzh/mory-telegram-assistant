<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# 变更日志（一行一条）

> 格式：`日期 | 类型[新增/修复/清理/文档/治理] | 一句话（≤100 字） | 涉及文件（≤5 个+等）`
> 2026-07-05 及之前的历史已归档至 `docs/archive/CHANGELOG_archive_20260707.md`；v5.38.15 及之前已归档至 `docs/archive/CHANGELOG_v5.38.15_and_before.md`。
> 触发式更新：仅用户可感知改动（升版/事故修复/配置或部署变化）写条目；验收证据写 commit message，详细报告落 `runtime/audit-reports/`。

| 日期 | 类型 | 一句话 | 涉及文件 |
|------|------|--------|----------|
| 2026-08-17 | 新增 | v5.38.62 群消息支持预填关键词延迟删除，重启可恢复，只删消息不处罚用户。 | `keyword_auto_delete`、分发器、数据库、Dashboard与测试等 |
| 2026-08-17 | 修复/配置 | v5.38.61 模型池完全切换为当前10个型号；临时故障自动回切，仅额度耗尽永久拉黑。 | 模型配置、AI引擎、部署与回归等 |
| 2026-08-15 | 修复/优化 | v5.38.60 冷场首答保留老板指定话锋，后续认同或追问转单一预览，拒绝不硬推。 | `keyword_trigger`、问答回归与版本记录 |
| 2026-08-15 | 修复/新增 | v5.38.59 冷场问法用审核底稿随机润色，FAQ日报过滤明确小闲聊并保留实际诉求。 | `keyword_trigger`、`faq_distill_task`、问答回归等 |
| 2026-08-15 | 修复 | v5.38.58 高频业务问答改为整句意图匹配，并隔离跨话题事实样本，防止漏答与串答。 | `keyword_trigger`、`ai_reply_handler`、问答回归等 |
| 2026-08-14 | 修复 | v5.38.57 “怎么和你约”等自然问法零Token命中社交解锁资料，不再落入AI陪聊拒绝。 | `keyword_trigger`、问答回归与版本记录 |
| 2026-08-14 | 修复/新增 | v5.38.56 频道转发直出内容相关彩虹屁、单入口按钮与审核营销图片卡，不再依赖频道事件。 | `linked_channel_sync`、配置、素材与测试等 |
| 2026-08-14 | 新增/修复 | v5.38.55 私聊索图直发审核照片，福利内容先文字后图片，并阻断旧回复串台（已部署验收）。 | `private_preset_media`、`keyword_trigger`、分发器与素材等 |
| 2026-08-14 | 修复/新增 | v5.38.54 新增零Token业务问答族与同会话追问，修复“怎么约Mory”连续乱答。 | `keyword_trigger`、`growth_optimizer`、问答文档与测试 |
| 2026-08-14 | 修复 | v5.38.53 群成员首次精确 @ 完整复用私聊 /start 的六卡、随机文案与双入口，且零模型调用。 | `message_dispatcher`、`start_welcome_card`、数据库与测试等 |
| 2026-08-14 | 新增 | v5.38.52 群聊精确 @ 小助理时随机回应；纯点名发图片卡，带问题直接处理且无默认销售按钮。 | `message_dispatcher`、`ai_reply_handler`、`mory_bot` 与测试 |
| 2026-08-14 | 优化 | v5.38.51 /start 欢迎卡改为全幅连贯画面、人物右置分层排版，并随机轮换两枚按钮文案。 | `start_welcome_card`、三款新底图与回归测试 |
| 2026-08-14 | 修复/新增 | v5.38.50 普通用户 /start 改为随机姓名日期欢迎卡，明确办事承接、真实转达回执及预览/订阅入口。 | `start_welcome_card`、入口/AI交接处理与测试等 |
| 2026-08-13 | 修复 | v5.38.49 VPN/梯子及衍生咨询只返回老板指定免费体验链接，不再夹带群置顶入口。 | `keyword_trigger`、回复回归与生产探针 |
| 2026-08-13 | 修复 | v5.38.48 普通用户私聊 /start 恢复自然 AI 首次对话，群管理入门仅向管理员展示。 | `start_help_handler`、入口测试与版本记录 |
| 2026-08-13 | 修复 | v5.38.47 VPN/梯子及衍生咨询不再风险拒答，返回群置顶与免费体验链接并承接短追问。 | `keyword_trigger`、`message_dispatcher` 与测试 |
| 2026-08-13 | 修复 | v5.38.46 修复 Smith 等英文姓名被裸 SM 成人词误封，组合成人招揽继续拦截。 | `ad_patterns_encoded`、`ad_detector` 与测试 |
| 2026-08-13 | 修复 | v5.38.45 裸链接与普通绑定频道不再单独授权广告处置，资料字段隔离判断。 | `ad_patterns_encoded`、`ad_profile_signals` 与测试 |
| 2026-08-13 | 修复/治理 | v5.38.44 恢复生产审计控制面，并阻断不包含当前 main 的全目录部署。 | `deploy_vps`、部署门禁、审计控制与测试 |
| 2026-08-13 | 修复 | v5.38.43 候选当次个人频道帖子不可读时跳过，unknown 不进入统一处置链。 | `scan_group`、扫描回归与文档 |
| 2026-08-13 | 修复 | v5.38.42 区分 Profile 取证、Bot API 增强不可用和传输异常，复核前重建 peer。 | `scan_group`、扫描回归与文档 |
| 2026-08-13 | 修复 | v5.38.41 存量扫描改为限速有界并发，并对资料和个人频道覆盖率失败闭合。 | `scan_group`、扫描回归与文档 |
| 2026-08-13 | 修复 | v5.38.40 存量扫描隔离资料与消息证据，普通 username 不再冒充高置信广告。 | `member_ad_scan`、扫描回归与文档 |
| 2026-08-13 | 修复 | v5.38.39 补齐个人频道帖子广告、1小时三次重复刷屏清理及Q裙成人招揽首条拦截。 | `ad_profile_signals`、`ad_detector`、`ad_enforcement` 等 |
| 2026-08-13 | 新增/治理 | v5.38.39 新增项目内只读巡检、漂移与月审控制面，统一回执/退出码及安全 timer 入口。 | `project_audit_control`、systemd 样例、规则与测试等 |
| 2026-08-13 | 治理 | v5.38.38 规则改为最小上下文与分层真相，部署/巡检直读远端版本并校验调度、DB及权限。 | `AGENTS`、发布/巡检工具、runbook与测试 |
| 2026-08-13 | 修复/治理 | v5.38.39 全量成员扫描复用实时广告规则，报告与处置分离，零覆盖不再假成功。 | `member_ad_scan`、`scan_group`、启动任务与测试等 |
| 2026-08-12 | 修复 | v5.38.38 精确过滤 gevent 退出噪声，真实启动错误不再被吞，并对生产 Dashboard 依赖锁读回。 | `deploy_utils`、`deploy_vps`、部署测试等 |
| 2026-08-12 | 修复/治理 | v5.38.37 封堵自助复权，纠正假绿灯与热重载竞态，清除新闻和空报表幽灵入口。 | `message_dispatcher`、`health_api`、调度/部署与测试等 |
| 2026-08-09 | 修复/治理 | v5.38.36 热重载同步调度、四态监控、报表真相源、看门狗及部署断线恢复/失败码加固。 | `task_scheduler`、`scheduler_monitor`、`deploy_vps`、报表与看门狗等 |
| 2026-08-09 | 修复 | v5.38.35 资料关联频道广告纳入多锚点检测，覆盖拆字与扩写，短句探路在 AI 前处置。 | `ad_profile_signals`、`security_handlers`、资料广告测试等 |
| 2026-08-09 | 修复 | v5.38.34 自有频道转发保留并取消置顶、点赞和评论；外部频道不豁免，广告首条阻断 AI。 | `linked_channel_sync`、`media_handlers`、`ad_patterns_encoded` 等 |
| 2026-08-09 | 修复 | v5.38.33 播报收敛为三档玄学栏目，图片单正文，实时模型去超时并拦截尬聊。 | `ai_engine`、`greeting_task`、`broadcast_image_payload`、配置与测试 |
| 2026-08-09 | 清理 | 停止自动新闻播报执行链：删除 common.py / auto_tasks.py 中新闻任务、格式化与发送链，保留 news 配置与 Dashboard 面板，同步清理测试。 | `tasks/support/common.py`、`modules/auto_tasks.py`、`tests/unit/test_broadcast*` 等 |
| 2026-08-09 | 修复 | v5.38.32 全仓暗病闭环：转发删鉴权、解封四项条件、延迟禁言证据门、schedule/enabled 统一、问候部分成功保日锁、none 无按钮、媒体广告预检等。 | `message_dispatcher`、`ad_enforcement`、`greeting_task`、`burn_orphan` 等 |
| 2026-08-09 | 修复 | verify_deployment 日志检查误报修复：grep -v 漏过滤 gevent 停机 Traceback 上下文行，改 awk 整块剔除噪声，杜绝健康部署被误判失败触发保险重启。 | `core/deploy_utils.py` |
| 2026-08-09 | 新增 | v5.38.31 特定词自动回复卡片化：Rich/HTML 双卡片+单入口随机按钮（默认关），润色只精修原文不重写。 | `core/auto_reply_card.py`（新增）、`modules/keyword_trigger.py`、`tests/unit/test_auto_reply_card.py`（新增）等 |
| 2026-08-09 | 新增 | v5.38.30 关联频道联动模块（默认关）：频道新帖自动点赞、群内转发自动取消置顶、每帖至多一条评论转化，命中即停止分发。 | `modules/linked_channel_sync.py`、`core/message_dispatcher.py`、`core/handlers/media_handlers.py` 等 |
| 2026-08-08 | 修复 | v5.38.30 广告规避漏判修复：跳过"简"字的"看我💬介"变体现在被正确识别为引流用户名并触发永久禁言+删消息处置。 | `modules/ad_patterns_encoded.py`、`tests/unit/test_ad_patterns_v5161.py` |
| 2026-08-07 | 新增/优化 | v5.38.29 人设预设全量录入：54 组风格样本落库（15 方向）、INPUT_HINTS 启用、社交解锁改 2 阶、敏感话题先引导 VIP、FAQ 每周自动提醒优化。 | \core/db_repos/reply_evolution_repo.py\、\config.json\、\AGENTS.md\、\docs/technical/persona-qna-edit.md\ 等 |
| 2026-08-06 | 优化 | v5.38.28 播报视觉修复+文案随机化：深色主题夜色底+深色区块+近白字；背景图去云纹；字号≥16px；塔罗牌名半截修复；傍晚改暮安；问候文案每次发送重新随机。 | \core/broadcast_image_card.py\、\core/broadcast_image_payload.py\、\tasks/support/mystic_content.py\ 等 |
| 2026-08-06 | 新增/优化 | v5.38.27 播报体验二轮：问候卡新增「一言」独白区块+深色主题可读性；图片卡去图上按钮改真实按钮随机组合；vote_kick 事务暗病修复。 | \core/broadcast_image_payload.py\、\core/broadcast_cta.py\、\modules/vote_kick.py\、\AGENTS.md\ 等 |
| 2026-08-06 | 新增/优化 | v5.38.26 播报体验升级+人设治理：图片卡主题化与问候卡改版（含 night 档）、CTA 每日轮换与玄学三入口、搭讪/FAQ 人设升级、风格样本分组投喂与蒸馏、死代码清理。 | \core/broadcast_image_card.py\、\tasks/broadcast/greeting_task.py\、\modules/admin_cmds.py\、\AGENTS.md\ 等 |
| 2026-08-05 | 修复/清理 | v5.38.24 遗留闭环：mypy 10 项清零入 CI；sanitize 自愈修复生效；get_pool_info 补测试；文档治理+垃圾清理。 | \core/ai_engine.py\、\	ests/unit/test_ai_engine_resilience.py\、\project_snapshot.md\ 等 |
| 2026-08-05 | 修复 | v5.38.23 Harness 六项修复：CI 门禁断链、状态残留三路径、.venv 重建 3.12、request_id 关联。 | \core/ai_engine.py\、\core/database.py\、\.github/workflows/ci.yml\、\AGENTS.md\ 等 |
| 2026-08-05 | 修复/清理 | v5.38.22 整改收尾：CTA 收敛单一真相源；广告白名单豁免+三态降级；check_config_sync 新增；文档归档。验收：pytest 850+。 | \core/broadcast_cta.py\、\modules/ad_enforcement.py\、\scripts/check_config_sync.py\（新增）等 |
| 2026-08-05 | 修复 | v5.38.21 广告处置群管豁免：enforce_ad_user 统一处置链顶部群内管理员/群主直接豁免（覆盖 8 条调用链），修复生产误封群管实例，新增豁免单测。 | `modules/ad_enforcement.py`、`tests/unit/test_ad_enforcement.py` 等 |
| 2026-08-04 | 修复 | v5.38.20 配置脏状态闭环：MYSTIC 恢复、NEWS/AUTO_NEWS 对齐下线，合并部署验证。 | \config.json\、\AI_DEBUG_HISTORY.md\ 等 |
| 2026-08-04 | 修复/安全加固 | v5.38.20 Graph 第四轮：faq/health 明文异常改固定文案+留痕、裸 except 清场、白名单补键。验收：pytest 861。 | \dashboard/api/faq_api.py\、\dashboard/api/health_api.py\ 等 |
| 2026-08-04 | 修复/安全加固/测试 | v5.38.19 Graph 第三轮：状态日志明文脱敏 + 回退裸 except 留痕 + 4 项静态 smoke。 | \core/bot_initializer.py\、\	ests/unit/test_log_sanitization_and_trace_smoke.py\ 等 |
| 2026-08-04 | 修复/安全加固/测试 | v5.38.18 Graph 第二轮 19 处加固：metrics str(e) 修复、裸 except 留痕、白名单补键。验收：pytest 861。 | \dashboard/api/metrics_api.py\、\core/ai_engine.py\ 等 |
| 2026-08-04 | 修复/清理/安全加固 | v5.38.17：AI 超时/重试默认值与 example 三处同步对齐；wave_tilde 裸 except 留痕；deploy 补路径黑名单+EXCLUDE_NAMES 双防线。 | `core/ai_engine.py`、`deploy_vps.py` 等 |
| 2026-08-04 | 新增/优化 | v5.38.16 播报图片卡 7 项优化+20 smoke：helper 去重、CTA 强绑定、四套时段池、font LRU、deploy 上限。 | \core/broadcast_image_payload.py\、\core/broadcast_cta.py\、\deploy_vps.py\ 等 |
| 2026-08-04 | 修复 | v5.38.15.1 PIL 图片卡 Linux 汉字豆腐块根治：字体池平台分支+仓库楷体兜底；deploy 补 assets 扫描；清理 12 个孤儿临时脚本。 | `core/broadcast_image_card.py`、`deploy_vps.py` 等 |
