<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# AI 调试病历（去重重写）

> 模板：**问题 | 根因 | 解法 | 预防**。完整历史（截至 2026-07-06）已归档至 `docs/archive/AI_DEBUG_HISTORY_archive_20260707.md`。
> 本文件只保留反复出现、有结构风险的暗病；新增条目按模板追加，超 300 行先归档。

## 反复暗病清单

### 6.44 Telegram 字段类型与降级目标被想当然
- 问题 | 频道帖整数时间戳触发 `.timestamp()` 异常，回复目标消失时图片降文本仍引用坏目标且误报媒体成功。根因 | 未按真实 Telegram 类型和错误语义测试。解法 | 兼容 Unix 时间戳，窄识别 reply-not-found 后无引用直发并记录真实媒介。预防 | 固定生产原错、整数时间和正常引用反例。

### 6.43 资料广告变体被单词硬条件割裂
- 问题 | “正品水果17手机全系”配Bio招代理出货和群内寻手机店合作仍存活。根因 | 旧规则硬依赖“走私”，姓名、Bio、频道和发言证据未闭合。解法 | 增加窄范围水果机型号及规模分销组合，并桥接明确交易续句。预防 | 固定截图原文、拆字变体及水果种植、摄影、维修反例。

### 6.42 实际漏答被误当成可自行扩写的预设
- 问题 | 为修漏答擅自新增签到积分变体，混淆功能机器人与Mory问答边界。根因 | 未把生产预设当白名单真相。解法 | 配置原句优先，未配置变体仅记录delegated且不进AI/FAQ优化。预防 | 每次补答先核生产预设，新增问法必须有老板底稿。

### 6.41 数据迁移只有代码快照，没有数据库回滚点
- 问题 | 迁移前无数据库回滚点，shell 读取 dotenv 还可能解析失败或选错库。根因 | 只备份代码且迁移目标依赖环境继承。解法 | 精确绑定生产 `mory.db`，先做 0600 在线快照并校验完整性/外键。预防 | 备份、校验、迁移保持同一失败关闭链。

### 6.40 统一处置豁免后调用方仍旁路删除
- 问题 | 启动追溯已跳过管理员/白名单后仍逐条删历史消息，查询失败还被当完成。根因 | 账号处置与消息删除分支未共享终态。解法 | 保护/待重试结果立即短路，重试态保留追踪，成功日志绑定真实禁言结果。预防 | 所有处置调用方回归保护对象零副作用、查询失败可重试及正常账号闭环。

### 6.39 时敏模型断言与异常卫生门自身漏检
- 问题 | 模型过期后全量测试因硬编码旧首选失败，异常卫生扫描又漏掉 `pass # 注释`并误判命名异常。根因 | 测试直接依赖墙钟，扫描器只匹配纯 `pass` 且用子串识别 `Exception`。解法 | 冻结日期验过期选路，扩展注释 pass 规则并按单词边界识别宽异常。预防 | 门禁自身必须同时有逃逸正例和窄异常反例。

### 6.38 头像 CTA 与资料绑定频道证据断裂
- 问题 | “看我简介”头像账号绑定“聘群演有时间来”频道后发 `2Qoo+`，机器人仍回复且无处置记录。根因 | 频道规则缺群演招募变体，入群头像门未收到 personal_chat，消息门又只查姓名/Bio/频道。解法 | 频道三锚点只作候选，再与明确头像 CTA 联合进入统一处置。预防 | 固定真实短句、拆字变体、普通结算/排期/简历/政策频道及无 CTA 头像反例。

### 6.35 挂机收益正文与私密群 Bio 招揽双层漏判
- 问题 | “电脑养家、挂机印钞”正文配合“小白必做、勤快来、懒人勿扰”私密群 Bio 未处置。根因 | 收益规则缺少设备挂机组合，资料层只认旧“多一条路”话术。解法 | 增加组合语义与三锚点 Bio 规则，接入消息、进群和延迟复审。预防 | 固定原文、变体、反诈与正常电脑反例，并验证删除、限制和数据库标记全链。

### 6.34 低层兜底越权改写高层语义成系统性尬聊源
- 问题 | 敌意门禁把"自己去 @moryselect 看看"整条换成答非所问、去舞台化吃掉【积分商城】正文、FAQ 分类不看内容抢答、深夜警告吞业务提问。根因 | 后置过滤/兜底层用宽正则和分类捷径直接替换整条回复，违反高层证据优先。解法 | v5.39.0 全部改"只降级不换义"：删泛化敌意 pattern、业务词白名单+强线索优先、分类兜底限空 pattern、深夜仅修文案。预防 | 新增兜底必须带最小作用域测试，断言正常话术不被误杀；**门禁类改动禁止在分发主链提前 return**（v5.39 雷达门禁曾因 `return False` 掐断 P8-P10，自查发现已修）。

### 6.33 实锤广告也播自助卡且按用户去重仍会刷群
- 问题 | 多个不同 UID 连续发实锤广告时，每人一张自助卡挤满群聊。根因 | 播报未区分证据等级，去重又只覆盖用户和根事件。解法 | high 静默处置，仅 low/ambiguous 每群24小时一张共享卡。预防 | 固定实锤零播报、多UID疑似聚合、本人路由测试。

### 6.32 歧义联系方式被单规则永久封禁且 P1 覆盖根因
- 问题 | “私信开了”等日常表达被封，随后“签到”只显示黑名单拦截。根因 | 字符集合误当词组，裸联系方式权重过高，P1 用 REPLACE 覆盖首次原因。解法 | 歧义信号降权并要求独立强证据，处置事件保留根因，增加本人限频复检。预防 | 固定日常反例、完整分发、原因保真及恢复读回测试。

### 6.31 成人交易暗语与低频重复刷屏共同漏判
- 问题 | 广告号用“同城PC+担保交易”隔数小时刷屏，广告化姓名和Bio拉新深链也被字段隔离放行。根因 | 成人规则缺PC组合，资料层又禁止所有跨字段证据。解法 | 正文和姓名各加独立强规则，并仅允许“老师/同城/同程+免费上榜”叠加Bot邀请深链定罪。预防 | 固定进群、首次发言正例及普通姓名/链接反例。

### 6.30 入群 Bio 短时不可见且邀请引流组合漏判
- 问题 | 广告号入群时 Bio 两次为空，数小时后用“看我”把群友导向资料邀请链接仍未封。根因 | 延迟补审只有验证码放行单点，裸链接防误封后又缺少邀请链接与规避引流的同字段组合。解法 | 30 秒/5 分钟/30 分钟有界复审，并将群邀请链接+“多一条路试试”作为高置信资料证据。预防 | 固定空 Bio 后出现、截图正例、普通备用群和裸个人链接反例。

### 6.29 临时模型故障被永久拉黑且旧索引跨重启复活
- 问题 | 超时、限流等短暂失败会长期改变首选模型，旧数据库索引还会覆盖新池顺序。根因 | 故障分类混用永久黑名单，切换索引写入配置和数据库。解法 | 仅明确额度耗尽永久拉黑，其余走进程内熔断并自动回首选；模型索引只认当前配置。预防 | 回归超时回切、普通429不拉黑、明确额度拉黑与数据库旧索引隔离。

### 6.28 普通闲聊污染 FAQ 日报且群冷场问题落入泛聊
- 问题 | “你在干嘛”被列成 FAQ 漏命中，冷场回答又被擅自降调且追问无转化。根因 | 日报未区分闲聊，早路由缺审核底稿与分轮 CTA。解法 | 整句过滤闲聊；首轮锁定老板话锋，正向/继续追问单预览转化，拒绝不推、明确购买交统一订阅链。预防 | 回归底稿关键词、同用户上下文、单目标与拒绝/无关反例。

### 6.27 频道转发取消置顶但自动评论缺席
- 问题 | 频道发帖只取消置顶，无彩虹屁。根因 | 评论硬依赖先到的 channel_post pending，生产只收到群自动转发。解法 | 自有频道群转发直接生成同帖图片评论，后到频道事件幂等。预防 | 回归无频道事件、反序到达、单入口和图片卡。

### 6.26 新消息未取消旧延迟回复导致私聊串台
- 问题 | 新问照片后上一轮旧回复仍可能晚到。根因 | 私聊 Timer 无用户级代际状态。解法 | 新消息统一取消旧 Timer，预设照片按消息持久幂等。预防 | 回归取消竞态、重复 update、否定索图和文字后置图片。

### 6.25 预设问题落入模型后连续乱答
- 问题 | 高频业务短句漏入模型，预设回复又未进问题表，日报长期误报零命中。根因 | 预设缺私聊语境匹配且在 P10 记录前返回，表内无回答来源。解法 | 私聊短句/群聊强对象分层匹配，送达后原子记录 preset/FAQ/入口/AI/待优化来源。预防 | 每族固定生产原话与反例，日报和蒸馏按来源统计并排除已覆盖项。

### 6.24 已确认工具推荐被模型连续拒答
- 问题 | VPN/梯子咨询连续两轮被判成高风险而尬聊。根因 | 通用 LLM 没有已确认推荐事实和上下文早路由。解法 | AI 前确定性返回群置顶与免费体验链接，并保存短期上下文。预防 | 固定截图原话、短追问及机场/代理/拒绝反例。

### 6.23 英文姓名子串被短成人词误封
- 问题 | Smith 等正常姓名在入群放行后被永久禁言。根因 | 裸 `[Ss][Mm]` 无边界且单词直接计 4 分。解法 | 独立 SM 必须组合成人招揽语义。预防 | 短外文词必须覆盖姓名、普通单词、孤立缩写和真实广告正例。

### 6.22 健康绿灯与自动生产动作耦合
- 问题：旧 health 脚本以 HTTP 200 汇总“healthy”，旧回滚脚本据此自动停服务和换目录。
- 根因：liveness、发布身份、业务完成和修复授权没有分层，且缺少 evidence_gap/failed 退出码。
- 解法：统一只读巡检控制面与 0/2/3 回执；移除旧入口，生产动作仍需明确授权。
- 预防：Automation 只取证报告；health 不提供版本/业务证明，journal 不可读必须 evidence_gap。

### 6.20 自然语言反馈混入治理写操作
- 问题：普通用户私聊“我被禁言”可进入反馈分支并调用广告恢复，临时禁言用户可绕过管理员审核。
- 根因：反馈、通知和不可逆治理共用旁路；测试未覆盖非管理员自然语言的分发可达性。
- 解法：自然语言只提交管理员复核；仅 `/unban` 与审核回调保留写权限，回复明确状态未改变。
- 预防：复权入口必须有身份门禁、状态读回和负向可达性测试，用户自述不构成误封证据。

### 6.21 部署移动文件继承普通用户权限
- 问题：systemd unit 和 root cron 脚本归 ubuntu 且可写，`.env`/config 还允许同机用户读取。
- 根因：部署用 `sudo mv` 保留上传文件所有者/模式，未对 root 执行面和凭据做权限断言。
- 解法：unit 用 `install root:root 0644`；凭据/DB 0600；root cron 改执行 root-owned watchdog 副本。
- 预防：发布门禁核验 owner/mode/cron 真实目标；主机级 sudoers 变更另走受控运维审批。

### 6.16 配置热重载只改内存，不重编排 APScheduler
- 问题：Dashboard 打开问候或传统文化栏目后配置已保存，运行中却没有新增 job，必须重启才执行。
- 根因：reload watcher 只原地更新 config dict，任务 `schedule()` 仅在启动时调用，配置可见被误当作运行态生效。
- 解法：TaskScheduler 跟踪自身 job 集并支持 replace/add/remove；配置更新失败时恢复旧配置与旧任务集。
- 预防：所有动态调度开关必须测试 disabled→enabled→disabled 的真实 scheduler job 集，不能只断言配置或 `schedule()` 返回值。

### 6.17 任务监控使用临时防重锁表，失败事实被日志噪声遮蔽
- 问题：Loop 用 `task_log` 统计成功率、journal 判断失败；重启和日志轮转后会漏掉真实 failed/aborted/running。
- 根因：`task_log` 是 claim/防重锁，不是执行历史；已有四态表未成为监控真相源，关键清单也漏了生产三档栏目。
- 解法：L4/L5 改读 `task_execution_history` 四态和 `scheduler_metrics`，查询失败 fail-close；30 分钟关键检查纳入 mystic 三任务。
- 预防：任务健康只能以持久化四态和业务回执为主，journal 只补充；生产启用的用户面 job 必须进入关键清单。

### 6.18 报表伪官方 API 与看门狗不可诊断失败
- 问题：日/周/月报宣称可用 Telegram 官方统计但分支恒为 None；watchdog 重启失败只留空 stdout，日志无限增长。
- 根因：未实现数据源的占位分支长期保留；子进程 stderr 被丢弃、外部 cron 日志不在轮转范围，关键 watchdog 还被通配规则误排除出 Git。
- 解法：报表明确使用 Bot 事件自统计和 Telegram 实时人数；watchdog 纳入版本控制，严格解析 JSON、保留 stderr、root 直调 systemctl 并自轮转。
- 预防：数据来源文案必须有可执行调用和回执测试；运维恢复链必须覆盖失败诊断、日志上限和非交互权限。

### 6.19 部署上传断线后半部署，异常仍返回退出码 0
- 问题：SFTP 上传 80/408 时连接被关闭，磁盘代码已部分更新、服务仍跑旧 PID，但部署器最终进程码为 0。
- 根因：单连接串行上传全仓且无重连；顶层异常只打印不传播，`main()` 没有把 `deploy_ok` 映射为进程退出码。
- 解法：每 40 文件分批上传，断线重连并重传当前批次；最终按双服务/health 验证结果返回 0/1。
- 预防：发布工具必须测试连接中断恢复与失败非零；任何“异常/待手工检查”都不得以成功码结束。

### 6.8 配置三处同步漏同步 .get() 默认值（v5.38.17 新增）
- 问题：config.json.example 写了 "AI_REQUEST_TIMEOUT": 30 / "AI_MAX_ATTEMPTS": 2，但代码里 `config.get("AI_REQUEST_TIMEOUT", 15)` / `config.get("AI_MAX_ATTEMPTS", 3)`，example 没配这两项时运行态默认值反而比 example 更激进（更短超时、更多重试），导致高频超时或吞吐下降。
- 根因：三处同步规则（example + 代码 .get() 默认值 + Dashboard UI）只改了 example 或 UI，代码中的 fallback 默认值没有跟随更新；`config.get(key, FALLBACK)` 的 FALLBACK 是"最终兜底值"，不是"建议初始值"。
- 解法：统一把代码中的 FALLBACK 值改成与 config.json.example 中声明的一致；优先顺序保持不变（真实 config.json 覆盖 example，example 覆盖代码 FALLBACK）。
- 预防：① 修改任一配置项的默认值时，必须同时查三处：config.json.example 声明值、代码中 `config.get("KEY", X)` 的 X 与 Dashboard 端点默认值；② 新增配置项必须跑"无 config.json.example 时的代码默认值行为"回归测试，不能只跑 example 存在的 happy path。

### 6.9 裸 except: pass 吞掉异常导致零可观测性（v5.38.17 新增）
- 问题：ai_engine.py wave_tilde_daily 更新、dashboard/audit.py 多处长 `except Exception: pass`，发生异常时没有任何日志、没有上下文，用户感知是"功能偶尔失效但查不到原因"，排障成本极高。
- 根因：开发者知道这段是非致命、失败了也不影响主流程继续跑，就顺手写了 pass，但"非致命"不等于"不需要观测"。
- 解法：非致命异常统一降级为 logger.debug 或 logger.warning 保留堆栈和上下文，绝对禁止纯 pass（只有在防御性兼容旧版本库 import 失败且完全有替代实现、不需要观察时例外）。
- 预防：① 全仓静态审查禁止裸 except: pass；允许的模式只有：`except ImportError: # 兼容旧版库` + 有真实替代实现 / `except Exception as e: logger.debug(f"...跳过（非致命）：{e}")`；② 新增 try/except 时必须说明"为什么失败可接受"并保留最基本的 debug 留痕。

### 6.10 三处同步第三处（Dashboard 白名单 ALLOWED_CONFIG_FIELDS）漏加导致 UI 无法改配置（v5.38.18 新增）
- 问题：config.json.example 声明了 AI_REQUEST_TIMEOUT=30、AI_MAX_ATTEMPTS=2，代码里 `config.get("KEY", fallback)` 的 fallback 也已修到与 example 对齐，但 Dashboard 端 /config/update 的 ALLOWED_CONFIG_FIELDS 白名单里没有这两个键，用户在 UI 上提交修改会被拒绝，只能 ssh 上 VPS 改 config.json，不符合三处同步规则（example + 代码默认 + Dashboard UI 三处必须一致）。
- 根因：三处同步规则默认只检查前两处，忘了 ALLOWED_CONFIG_FIELDS 是第三道门——任何允许通过 HTTP 修改的配置字段都必须显式在白名单中。
- 解法：v5.38.18 在 dashboard/api/config_api.py ALLOWED_CONFIG_FIELDS 的"模型与路由"分组下显式加入 AI_REQUEST_TIMEOUT、AI_MAX_ATTEMPTS。
- 预防：① 新增或调整任何配置项的默认值/声明时，必须同时查三处：config.json.example → 代码 config.get() fallback → dashboard/api/config_api.py ALLOWED_CONFIG_FIELDS；② 配置三处同步的静态审查改为 diff 三者集合差（example.keys() ∩ ALLOWED_CONFIG_FIELDS 至少包含业务配置项，不能只靠人工记忆）。

### 6.11 错误详情（str(e)）直接返回前端导致 DB 路径/列名/凭据片段泄露（v5.38.18 新增）
- 问题：dashboard/api/metrics_api.py /api/metrics 端点的 except Exception as e 分支把 `f"指标生成失败: {str(e)}"` 直接 jsonify 返回给浏览器。若 e 来自 SQLite、file IO、Prometheus client 内部异常，可能把 DB 路径（/opt/moryassistant/mory.db）、列名、失败的 SQL、配置文件路径等敏感信息原样返回给 Dashboard 操作者；越权或 XSS 情况下，这些信息可用于构造注入攻击。
- 根因：写代码图省事，"后端报错了顺便写给前端看，省得查日志"，忘记 Dashboard 是用户可见 HTTP 响应，不是 CLI stderr。
- 解法：固定返回 "指标生成失败，请查看服务器日志获取详情"，完整异常详情保留在 logger.error（已存在且覆盖到位），前端只返回统一错误文案。
- 预防：① 所有 Flask/FastAPI 路由 except Exception 分支禁止把 str(e) / repr(e) / traceback.format_exc 直接 jsonify 或拼进返回字符串；② 允许返回给前端的只有固定语义文案 + 结构化错误代码（如 "ok": False, "code": "METRICS_GENERATE_FAILED"）；③ 运营需要看详情时走服务器日志或审计面板，不走 API 响应体。

### 6.12 系统状态/动态状态值明文落入 DEBUG 日志导致配置/凭据/长 list 泄露（v5.38.19 新增）
- 问题：core/bot_initializer.py `_load_dynamic_state` 把 `cfg[key]` 整体 `={cfg[key]}` 打印到 logger.debug；core/db_repos/config_repo.py `update_system_state` 把 `={value}` 整体打印。两处都是动态状态表/系统状态表的全量值，包含人设部署副本、黑名单长 list、偶尔塞进 system_states 的 API key、用户数据 list，当运行时 DEBUG 级别日志会被滚动归档（默认 logs/ 下保留 30 天），形成"配置值/临时凭据被无意落盘"，运维、审计脚本、外部同步工具或日志泄露都会变成持久化的敏感信息池。
- 根因：为了调试方便"打个 log 看值"，忘记日志是持久化到磁盘并保留多日的；同时默认思维是 "只有 INFO 以上才有人看"，但实际上 DEBUG 也会被轮转写盘、被 grep、被 Agent 或巡检工具扫描。
- 解法：两处统一脱敏为 `<类型(长度)>` 占位：None → `<None>`；str → `<str(len=123)>`；list/dict/tuple/set → `<list(len=456)>` 等；其他标量 → `<int>`/`<float>`/`<bool>`。禁止任何容器、字符串全值落入 DEBUG。只保留键名 + 类型/长度，便于排障又不泄露明文。
- 预防：① 任何 logger.debug / logger.info 写入配置表/动态状态表/用户内容相关对象时，统一先脱敏或只写类型/长度，禁止全明文；② 敏感状态表（system_states / dynamic_states 等）的 set/get 辅助类默认在 __repr__ 处脱敏，或禁止在日志中直接 `%s`/`f-string` 打印；③ 新增 CI 级 smoke：用正则断言 "动态状态加载/系统状态更新" 这两句日志行中不含 `={cfg[` 或 `={value}` 明文拼接模式（已随 v5.38.19 新 test_log_sanitization_and_trace_smoke.py 4 smoke 覆盖）。

### 6.13 定时任务群人数 API 失败回退 DB 裸 except 吞错导致完全不可观测（v5.38.19 新增）
- 问题：tasks/analytics/daily_report_task.py 每日报告生成时，对 `rm.bot.get_chat_member_count(gid)` 失败后直接回退 DB 值 `rm.db.get_group_total_members_latest(gid)`，except Exception 后面既不绑定异常名也不留任何日志。每日/每群发生了多少次、是超时、是 Bot 被踢、权限、网络瞬断、限流、参数 gid 类型错误等完全没有上下文。当 DB 兜底数据本身陈旧时，报告值偏差也无从溯源。
- 根因：写代码时把"回退"当成"一切正常"，遗漏了"即便回退也得把失败原因 + gid + 次数记录在案"的可观测性铁律；尤其每日报告是运营指标，偏差发生时最需要知道"今天这数字真实来自 DB 兜底"。
- 解法：改为 `except Exception as e: logger.debug(f"群人数API失败，回退DB（非致命）：gid={gid} err={e}")`，保留 gid（非 PII）+ 异常上下文（通常是超时/被踢/Rate limit 等），并作为 DEBUG 级落盘，不影响 ERROR 告警阈值但保留可排障线索。
- 预防：① 任何"try 主路径失败 → 回退次要路径"模式，必须在回退分支写 `logger.debug` 级日志包含主路径失败原因 + 关键上下文，禁止裸 except: + 直接赋值；② 新增 CI 级 smoke：对 get_chat_member_count 紧邻回退段出现"裸 except 不绑定 + 不写日志"反例（已随 v5.38.19 新 smoke 覆盖）。

### 6.14 Flask API 响应体把异常/内部状态明文串进 HTTP 响应（v5.38.20 新增）
- 问题：dashboard/api/faq_api.py 共 11 处 except Exception as e 块把 f"失败：{e}" 直接塞进 jsonify 返回；dashboard/api/health_api.py 中 scores.detail 和 audit 缺失键字段把 f"检查失败: {e}"、f"integrity: {r}"、f"缺失 5 键: {missing[:5]}" 等内部错误/检查结果/配置键名样本直接写进 HTTP body。这些字段即便 @login_required 也会被 Dashboard 前端渲染、写入浏览器历史、抓包工具捕获；尤其健康检查部分未登录也能拿到。真实 e 信息包含 sqlite3.Error 的 DB 文件路径/表名/列名/约束冲突、OSError/IOError 路径、Permission denied 账号等敏感信息；integrity 失败细节会暴露 SQLite PRAGMA integrity_check 对业务表、索引的具体报错；missing[:5] 泄露配置 schema 键名结构便于攻击者有定向枚举。
- 根因：开发时为了"前端看一眼就知道啥错"，把服务端日志该写的东西推到了响应体，没有区分"对用户可见的错误文案"与"写服务器日志的错误详情"两条链路；@login_required 被当成"安全边界"，忘记登录用户也是攻击者模型之一；audit 中 missing[:5] 本意"排障方便"但把 sample 写进了响应体，而不是写在日志里。
- 解法：① 统一除 400 系列用户输入校验（"xx 不能为空"/"该配置项不允许修改"）外，所有 500/503/兜底响应的错误文案一律固定为"动作失败，请查看服务器日志获取详情"/"配置检查失败（详情见服务器日志）"等常量，禁止在 HTTP 响应的任何字段（含嵌套 JSON 的 detail/error/note/message 字段）拼接 str(e)、repr(e)、traceback、exception args、f-string 或格式化带异常对象；② 每处 except 块在固定返回之前写日志：异常上下文用 logger.exception（自动带堆栈，适合 except 最末），降级分支用 logger.debug / logger.warning（只写上下文），排障所需样本（如 missing[:5]）统一写日志，不写进响应体；③ faq_api 11 端点全部前置 logger.exception + 固定 msg；health_api 5 处 score.detail 泄露 + audit 缺失键样本 + 7 处 except 无日志全部按此改造。
- 预防：① 写任何 jsonify({"ok": False, ...}) 返回之前，自检 msg/detail/error 字段是否出现 e/r/missing 等动态对象；② 作为团队规则：except 块第一句先 logger.exception / logger.warning，第二句再 jsonify 固定错误，形成肌肉记忆；③ 在 CI 加静态断言：grep 禁止 jsonify(.*f"{e}" / jsonify(.*str(e) 模式出现。

### 6.15 裸 except Graph Mode 连续三轮残余未净的"回退暗病"反复出现（v5.38.20 新增）
- 问题：v5.38.17 修 wave_tilde_daily 裸 except；v5.38.18 修 ai_engine 9 处 + dashboard 7 处 + daily_report 回退；v5.38.19 修 daily_report 回退补全后，v5.38.20 再扫仍发现 weekly_report_task/monthly_report_task 2 处群人数 API 回退仍裸 except，health_api 7 处仍裸 except 不绑定。Graph Mode 按维度扫描但每轮没对"try 主路径 API + except 回退赋值"这种复合模式做全局反例匹配，导致"回退就裸 except"的坏模式反复在不同文件、不同任务中出现。
- 根因：旧坏模式"回退=成功"、"有回退不需要留痕"在不同业务模块中独立复现；每轮扫描只查模块局部/最近改动文件，缺少"复合语法模式反例"（A=try 调外部 API, B=except 不绑定异常名, C=except 体内只赋值回退数据 + 不写日志 = 命中）的全仓组合规则；周报/月报和日报是三个不同文件但复制粘贴了相同裸 except 段，修复日报时没按文件名 pattern 扫月报/周报兄弟文件。
- 解法：① 按文件名 pattern 成组扫描：daily_report_task.py 修后自动对 weekly_report_task.py / monthly_report_task.py 同样语义位置做二次扫；② 把"外部 API + 回退赋值 + except 不绑定 + 不写日志"提升为项目级语法反例，每次 Graph Mode 都用复合 Grep 扫（关键词组合：get_chat_member_count / getChat / requests.get / bot. + except Exception: + 下一行 = db. 回退）；③ weekly/monthly 2 处、health_api 7 处全部 as e + logger.debug 绑定上下文+动作标签，动作标签包括 aborts/jobs/audit/task_success_rate/root/task_checker/config_missing_keys 等可溯源到具体端点的短标签。
- 预防：① 新增 Graph Mode 每轮的必扫复合清单：不裸 except × 3（except Exception: 不绑定 / except: pass / except Exception 绑定了但不写日志）；② 代码评审时，看到 try 调外部 API（bot/requests/子进程/SSH/SFTP）必须检查 except 块是否：绑定异常名 + 写至少 debug 级日志 + 回退数据说明是回退值；③ 形成命名约定：每次回退 logger.debug 里带 `（非致命）/（回退）/（降级）`，方便巡检工具按关键词抽失败率。


## 结构性风险（推断，附依据）
- 历史误封集中在“检测链与入口/清理链不一致”类问题。新增检测或播报必须显式接入 dispatcher 与 burn_orphan，并加回归测试。
- v5.33.0—v5.35.3 的 Dashboard、SQLite、Rich Message 和模块审计病历已压缩归档到 `docs/archive/ai-debug-history-v5.33-v5.35.3.md`。


### 53. 配置脏状态与产品方向/代码逻辑脱节致播报停摆 5 天
- 问题：风水/塔罗/易经播报 07-30 起静默停摆 5 天未被发现；`MYSTIC_BROADCAST_CONFIG.enabled=false` 但 `MysticBroadcastTask.schedule()` 无条件注册（journal 可见任务注册），`execute_mystic_broadcast_task` 检查 `is_mystic_enabled` 返回 false 后 debug 级跳过（默认不显示），造成"注册了但没执行"的隐蔽假死；同时 `NEWS_BROADCAST_CONFIG.enabled=true` + `AUTO_NEWS=true` 但 `NewsTask` 代码 v5.37.0 已删（`news_morning` job_id 在代码中 0 引用），配置残留与产品方向相反。
- 根因：① 任务注册与执行分离 — `schedule()` 不检查 enabled，`execute()` 检查 enabled，导致 journal 显示注册成功但实际跳过，只看注册日志会被误导；② 下线功能只删代码不改配置 — v5.37.0 删 NewsTask 类但没清理 NEWS_BROADCAST_CONFIG.enabled 和 AUTO_NEWS 残留 true；③ 缺少"配置 vs 代码 vs 实际执行"三方一致性校验，task_log 是唯一真值但日常只看 scheduler_metrics 累计 success_count（含历史值）会误判还在跑。
- 解法：① 本地 config.json 三字段对齐产品方向：`MYSTIC.enabled false→true`、`NEWS.enabled true→false`、`AUTO_NEWS true→false`；② `safe_upload_config` 安全合并到 VPS（非 PROTECTED_FIELDS 本地覆盖 VPS）+ 重启双服务；③ 验证以 task_log 近期记录 + journal 注册日志 + scheduler_metrics last_run 三方交叉，不能只看单一来源。
- 预防：① 下线功能时必须同步清理 config 残留（enabled/AUTO_* 遗留开关），不能只删代码；② 任务 schedule() 与 execute() 的 enabled 检查应统一 — 要么都检查要么都不检查，避免"注册成功但执行跳过"的隐蔽假死；③ 日常巡检必须查 task_log 近 3 天记录（真值），不能只看 scheduler_metrics 累计 success_count（含历史）或 journal 注册日志（只证明注册不证明执行）；④ 任何"配置 vs 代码 vs 实际执行"三方对比必须以 task_log 为准。


### 54. CTA 三套真相源并存导致"图片按钮/正文/演示样张"互相不一致（v5.38.22 新增）
- 问题：同一播报体系里同时存在三套 CTA 文案：core/broadcast_image_card.py 的旧 CTA 池（含"· 点击头像"歧义文案，仅 demo 使用）、tasks/support/mystic_content.py 的第二套 CTA 系统（_CTA_URLS/_CTA_LABEL_POOLS/_CTA_CLOSING_POOLS/_build_cta 写入 payload["cta"]，正文 closing 与图片按钮各走各的池）、以及 v5.38.16 建立的统一 core/broadcast_cta.py。表现是"表面做完、实际不一致"：演示样张与生产按钮文案不一致、正文 closing 与按钮来自不同池、历史 24 条 img_label 后缀 bug 反复复发。
- 根因：能力演进时新增了统一组件，但旧实现只被"绕过"没有被删除，消费方（formatter 读 payload["cta"]、demo 调 get_random_cta、门禁按 _CTA_URLS 硬校验）仍挂在旧真相源上；没有任何静态断言阻止旧池残存。
- 解法：v5.38.22 删除旧 CTA 池与 get_random_cta、删除 mystic_content 第二套 CTA（_build_cta 及三池）、build_mystic_broadcast 不再写 payload["cta"]，由发送层统一 get_broadcast_cta 生成后回填；demo 改为统一池派生 image_label；门禁放宽为 target 合法 + label 非空；新增静态断言（grep 旧池名零残留）+ test_all_cta_pool_entries_pass_consistency_check 全池一致单测。
- 预防：① 引入新真相源时必须同时删除或显式废弃旧真相源，禁止"新老并存绕过式演进"；② 统一能力（CTA/图片卡/开关）必须加静态残留断言（grep 旧符号零命中）；③ 任何"文案池"改动必须跑全池一致性单测 + demo 样张核对，不能只看主路径 happy path。

### 55. get_chat_member 查询失败仍执行不可逆惩罚，群管误封风险残留（v5.38.22 新增）
- 问题：v5.38.21 群管豁免依赖 bot.get_chat_member 网络查询，查询失败分支返回 False 继续执行永久禁言+双黑名单+删消息等不可逆惩罚；若网络瞬时故障/限流，群管会被误封（生产实例：群管 1193526296 曾因资料命中被误封）。且 enforce_ad_user 只查网络身份，未先查零成本的配置级 ADMIN_IDS/ADMIN_ID 白名单。
- 根因：豁免判断全部押在单次网络调用上，没有"配置级先行 + 网络失败降级"的两层设计；失败语义被设计成"按非管理继续处置（不放过可疑号）"，把"无法判定"等同于"确认非管理"。
- 解法：v5.38.22 两层加固：① enforce_ad_user 顶部先查 _admin_ids(config) 配置白名单（零网络），命中即豁免；② _is_chat_admin_member 改三态返回（admin/not_admin/unknown），unknown（网络异常）走降级链：保留证据持久化 + 通知管理员人工复核，跳过四个不可逆惩罚，返回 skipped_reason=admin_query_failed；③ 启动追溯对 admin_or_creator/admin_query_failed 不再计为"禁言失败"，报告单独统计"跳过管理员/查询失败"。
- 预防：① 任何"判定用户身份后执行不可逆动作"的链路，必须"本地配置先于网络查询、网络失败只能降级不能默认有罪"；② 三态语义（是/否/无法判定）是豁免类逻辑的标准形态，禁止用布尔 False 同时表达"非管理"和"查询失败"；③ 豁免/跳过必须回传结构化 skipped_reason 供上游统计，避免把"跳过"误报为"失败"。

### 56. sanitize 降温度自愈重试参数被循环内重建覆盖，实际退化为原样重试（v5.38.23 新增）
- 问题：ai_engine.ask() 触发穿帮后"降温度重试一次"的机制（v5.23.0 P0-2）实际不生效：monkeypatch 断言第二次请求 payload.temperature 应为首次一半时，实测仍为原值；注入的约束 system 消息同样丢失。
- 根因：payload（含 temperature/messages）在 while 循环体顶部每轮重建（约 2614-2622 行），穿帮分支（约 2695-2704 行）对 payload 的修改在 continue 后进入下一轮被重建覆盖；标记 _sanitize_retry_done 只控制"是否再试一次"，重试参数从未真正改变。
- 解法：v5.38.23 先修复状态残留（全败兜底与 402/403 池耗尽早退路径清理 _sanitize_retry_done）；v5.38.24 彻底修复参数失效——把"降温度 + 约束注入"从穿帮触发点移至 while 循环内 payload 构建完成后应用（读取 _sanitize_retry_done 标记），触发点只置位标记并 continue；回归测试断言重试请求实际降温度（base*0.5）且 messages 含约束警告，两次 ask 序列均验证。
- 预防：任何"修改请求参数后 continue 重试"的逻辑，必须先确认参数构建点与修改点在同一作用域层级；写测试断言重试请求的实际载荷（payload 内容），不能只断言"发生了重试"。

### 57. 自有频道媒体转发绕过主分发器后被广告链删除（v5.38.34 新增）
- 问题 | 自有频道视频转发被删，Telegram 系统号还被误封；正文广告首轮进入 AI。根因 | 联动生产关闭、媒体 handler 早于 P0.1 且广告调用签名错误。解法 | CHANNEL_IDS 精确可信门、媒体复用联动/统一广告链、补正文规则。预防 | 自有/外部频道正反例与文本/媒体入口同测。

### 57. .venv 是 Python 3.14 空壳导致依赖装不上、pytest 缺失（v5.38.23 新增）
- 问题：本地 .venv 存在但完全为空（无 pip、无任何包），uv sync 静默跳过（pyproject.toml 无 [project] 段，uv 默认 requires-python>=3.14 且无依赖定义）；uv pip install 在 gevent==24.11.1 编译时失败（PyInt_AsLong 等 C API 在 3.14 被移除），pytest 始终不可用。
- 根因：.venv 由 Python 3.14 创建（版本过新，gevent 等依赖尚无 3.14 wheel），且项目依赖真相源是 requirements.txt（50 行）而非 pyproject.toml（仅 [tool.interrogate]）。
- 解法：删除空壳 .venv，用 Python 3.12.10 重建（python -m venv .venv），再 uv pip install --python .venv/Scripts/python.exe -r requirements.txt；AGENTS.md 验证门禁补充测试命令与环境要求。
- 预防：本地环境统一 Python 3.12（与 CI 一致）；venv 重建后用 .venv/Scripts/python.exe -m pytest tests/unit/ -q 冒烟验证；不要在 pyproject.toml 缺 [project] 时依赖 uv sync。

### 58. 线程日志上下文泄漏风险评估结论（v5.38.24 记录）
- 问题：message_dispatcher 消息入口 set_logging_context 后各分支手动 clear_logging_context（36 处），独立审查提示异常路径可能残留上下文污染下一条消息日志。
- 根因：thread-local 上下文只在消息线程内有效；telebot 默认每条更新独立线程（线程退出即销毁 thread-local），项目仅有的 ThreadPoolExecutor（append_pool，max_workers=2）不处理消息分发。
- 解法：评估结论为低风险不重构——telebot 每消息独立线程模型下残留上下文随线程销毁，无线程池复用污染路径；消息分发函数已有 36 处显式清理覆盖正常路径。如需未来改为线程池分发，需同步引入 try/finally 清理。
- 预防：若引入线程池处理消息，必须先加异常安全清理（try/finally clear_logging_context）再上线；新增异步/池化路径时审查 thread-local 生命周期。

### 59. 文档人工同步膨胀失真 + 部署无机械出口（v5.38.25 治理）
- 问题：CHANGELOG 93.6KB 流水账（单条 400-700 字验收报告）、README/AGENTS 版本落后（v5.38.23/v5.38.14 ≠ 实际）、snapshot 大事 5 条超限；v5.38.23 部署后 VPS 版本未 bump 才被发现。
- 根因：收工六件套无触发条件（每次全量同步→流水账）；六文档版本纯人工同步、脚本零覆盖；完成判据只列本地证据，部署无机械出口。
- 解法：AGENTS 重写为触发式更新矩阵（未达条件不写）+ 部署三选一（已部署/无需部署/门禁阻断，未填视为未完工）；doc_consistency 扩展机械断言（版本五源一致/六文档行数/CHANGELOG 条目 ≤100 字/snapshot 大事 ≤3 条/README 指标一致）；新增 scripts/check_deploy_ready.py 一键检查；CHANGELOG v5.38.15 及之前整体归档。
- 预防：文档更新按触发矩阵执行；升版五源同改（脚本拦截）；规则不锚历史版本号；收工必填部署三选一。

### 60. verify_deployment 日志检查漏过滤 gevent 停机噪声块，健康部署被误判失败（2026-08-09 修复）
- 问题：全量部署成功（health=200、双服务 active），verify_deployment 却报日志错误→保险无谓 restart。
- 根因：gunicorn/gevent 停机噪声是多行块，原过滤只剔末行，Traceback 上下文仍命中 error。
- 解法：`deploy_utils` 校验改 awk 整块剔除后再 grep。
- 预防：日志校验按块过滤；改校验后必须 VPS 实测命令本身。

### 61. 转发即删除无鉴权 + 解封不全 + 累计分无直证可永禁（v5.38.32）
- 问题：任意私聊用户转发群消息可触发 bot 删原消息；自助解封/ungban 只清 blacklist 留 global/mute/tracking→P1 再封；延迟/启动追溯仅靠累计分（含 profile emoji）永久禁言。
- 根因：特权动作缺管理员门禁；恢复路径未统一 restore_ad_user；行为/资料分被当广告证据。
- 解法：转发删强制 ADMIN_IDS；解封全走 restore_ad_user；延迟/启动追溯要求≥1 条直证；enforce 补 AD_WHITELIST。
- 预防：不可逆动作=配置白名单先于网络+失败降级；解封唯一入口 restore；累计分 alone 不得 ban。

### 62. schedule 与 enabled 分离 + 问候部分成功释放日锁双发（v5.38.32）
- 问题：mystic/greeting 等 schedule 无条件注册、execute 才查 enabled（假死）；多群问候部分成功抛错释放日锁可同日双发。
- 根因：注册与执行门禁分裂；事务异常分支一律 release claim。
- 解法：schedule 按 enabled 返回 []；部分成功 return 保留日锁；claim 孤立 task_log 启动回收。
- 预防：schedule/execute 门禁统一；部分成功不得当全失败释放日锁。

### 63. 三套主动触达叠加 + 随机拼图 + 思考模型超时导致重复套话
- 问题|根因|解法|预防：10 档播报时段重叠，问候图拼无关随机句，实时问候误跑思考模型超时后发固定兜底；收敛为三档传统文化栏目，图片单正文，移除固定兜底和过期模型，实时模型显式禁思考，并加节奏/输出回归门禁。

### 64. 广告搬进个人关联频道，群内短句绕过只读 Bio 的资料检测
- 问题|根因|解法|预防：广告号把引流放在 getChat.personal_chat，群内只发重复短句；旧链只读 Bio。资料检测统一采集关联频道标题/用户名/简介，以三类独立语义锚点覆盖拆字与扩写，并固定正常频道反例；新增 Telegram 资料字段须做真实对象字段审计。

### 65. 部署日志过滤过宽 + 运行解释器依赖来源漂移
- 问题|根因|解法|预防：任意析构异常后的真实启动失败可能被整块过滤，systemd 解释器还同时可见系统包与 user-site；过滤器改为只识别 logging/gevent 确证退出栈，其他异常保留，重启前按 requirements.lock 精确读回 Gunicorn/gevent，漂移或安装失败即阻断。

### 66. SSH helper sudo PTY 可能回显密码
- 问题|根因|解法|预防：root 分支分配 PTY 后向 stdin 写密码，终端可能回显到输出；改为无 PTY 的 sudo -S，输出与异常统一脱敏，并用 mock 与真实 UID 探针固定密码只走 stdin。
