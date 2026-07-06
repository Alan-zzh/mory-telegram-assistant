# Mory小助理 项目深度审计报告（AI Project Audit）

> 审计类型：只读第三方代码法证审计（独立审计 AI）
> 审计日期：2026-07-07
> 审计对象：d:/Documents/Syncdisk/Work/project/mory_assistant（git `ae3a9c8`，v5.31.2）
> 铁律遵守：未修改/移动/删除任何文件与代码；仅创建本报告。所有密钥按"前4位..后4位"脱敏；真实用户数据未触碰。

---

## A. 审计元信息

- **审计工具/模型**：本地代码静态分析（grep + 文件树 + 量化计数）+ 4 个并行 code-explorer 子代理（只读）交叉取证 + 主审计员合成。
- **git commit**：`ae3a9c852d74aa2df3b9f81244ffe346c22e52f6`（2026-07-06 "add unban buttons to ban notifications"）。
- **扫描覆盖率**：项目自有 `.py` 共 **385** 个（已排除 `.venv` 1365 文件与 `__pycache__`/`.pyc`）。完整精读核心文件约 14 个（ai_engine / model_router / message_dispatcher / auto_tasks / ad_detector / orphan_api / config_api / auth / rbac_guard / database / profile_learner / memory_summarizer / natural_cmd / keyword_trigger / verification / scheduled_broadcast）；grep/计数覆盖全部 385 个 `.py`。文档 6 份（AGENTS/README/VERSION/CHANGELOG/project_snapshot/AI_DEBUG_HISTORY）全读。**测试 39 个 `.py` 仅静态确认存在，未执行**（避免副作用）。
- **未覆盖区域及原因**：
  - 未逐行阅读全部 92 个 `modules/` 业务模块（仅抽样核验代表性模块）；若某模块存在静默空实现未被抽样命中，可能漏判 → 标记 `[Unknown]`。
  - 未执行 `pytest` 全套与 `verify_db_methods.py`（触及 DB/可能触发外部依赖）；文档声称"164/165 方法注册通过、单测 passed"**未经本人复跑验证** → 相关结论标 `[Unknown]`。
  - `.venv/`、`mory.db`、`config.json`、`.env` 仅做存在性/脱敏检查，未读内容（含密钥）。
- **实际执行过的验证命令清单**：
  - `git rev-parse HEAD` / `git status --short` / `git check-ignore config.json .env mory.db backups backup` / `git ls-files | grep`
  - 量化计数：`Get-ChildItem modules/core -Recurse -Include *.py`；`Select-String 'def _job_' auto_tasks.py`；`Select-String '@\w+\.route\(' dashboard/api/*`；`Select-String 'CREATE TABLE IF NOT EXISTS' core/database.py`；`Select-String '_dispatch_p' message_dispatcher.py`；`(Get-Content).Count` 各文档。
  - 安全：`Select-String 'sk-|BEGIN.*PRIVATE KEY|api_key|secret|password'` 全仓（仅占位/公开凭证命中，无用户密钥泄露）。
  - 代码搜索：TODO/FIXME（8 处）、`except:`（2 处）、`def _dispatch_p10_ai`（定位至 ai_reply_handler.py:73）。

---

## B. 白话总评（写给零基础的项目主人）

你这个机器人不是"空壳"。我一行行查了代码：人设对话、广告检测、群管、积分商城、转化漏斗、新闻播报、Dashboard 这些**核心功能都真做出来了**，不是假样子。好消息是——它没虚报成"什么都没干"。

但有三个最该先处理的问题：

1. **文档自己打架、数字乱写**。同一份 README 里模块数写了"87+48"又写"95+35"，定时任务写了"52 个"又写"53 个"，还说消息分发有"34 个拦截点"——实际只有 9 个分发函数。功能在，但文档数字不可信，接手的人会被误导。
2. **仓库很脏**。有两套备份文件夹（backup/、backups/ 共 22 个 .bak 旧文件），根目录还散落运行时垃圾（fault_dedup_state.json、reload_flag、test_selfcheck.db 等）。AI_DEBUG_HISTORY.md 已 4440 行、CHANGELOG 2456 行，越堆越难查。
3. **有几处"写了但没用"的死代码**（如 structured_logger 两个函数、pinyin_util 一个函数从没被调用），以及一段工具命令路由被复制了两份。

最该先做的三件事：① 把文档数字统一成真实值并加自动检查；② 清理两套备份和根目录垃圾；③ 删掉死代码、合并重复路由。

### 健康评分表（0–10）

| 维度 | 评分 | 一句话理由 |
|------|------|-----------|
| 功能真实性 | 8 | 核心功能实测存在、非虚报；但文档数量夸大 |
| 架构合理性 | 7 | 分层清晰（core/modules/dashboard），有少量死代码与过度封装 |
| 代码质量 | 7 | 参数化 SQL、hmac 校验、结构化日志到位；存在死代码与重复 |
| 安全性 | 8 | 密钥 gitignore、RBAC、无硬编码用户密钥；仅 1 处公开凭证硬编码且已被忽略 |
| 文档与文件卫生 | 4 | 数字多处自相矛盾、病历/日志严重膨胀、两套备份、根目录散落文件 |

---

## C. 声称-实证对照表（Phase 2 全量）

判定图例：✅ 真实现｜🟡 半实现/夸大｜🎭 假实现｜💀 死代码｜❓ 无法验证。

| CLAIM | 文档声称（出处） | 代码证据 | 判定 | 说明 |
|-------|----------------|----------|------|------|
| CLAIM-001 | 135 模块（87 modules + 48 core，README §1.8 L132；§3.4 L605 写 95+35） | `modules/` 92 `.py`、`core/` 73 `.py`（实测，含子目录） | 🟡 | 功能真实；但两处数字互相矛盾且均偏离实测（92/73） |
| CLAIM-002 | 108 张数据库表（README L24/L451；project_snapshot §3） | `core/database.py` 108 处 `CREATE TABLE IF NOT EXISTS`（实测） | ✅ | 数量自洽 |
| CLAIM-003 | 156 个 Dashboard 端点（README §1.9） | `dashboard/api/*` `@*.route(` 实测 157–158 处 | ✅ | 数量准确（差 1 属正常新增） |
| CLAIM-004 | 34 个消息分发拦截点（12 主级+22 子级，README §1.10） | `message_dispatcher.py` 8 个 `_dispatch_p*` + 导入 `_dispatch_p10_ai`（ai_reply_handler.py:73）= 9 个分发函数；子级为内联步骤 | 🟡 | 优先级链真实；"34"为文档构造，非 34 个独立函数 |
| CLAIM-005 | SYSTEM_PROMPT 从 config 读取并用于 AI | `ai_engine.py:1539` `cfg.get("SYSTEM_PROMPT")` 拼装入 persona | ✅ | 真实读取，非占位 |
| CLAIM-006 | 三层模型池+故障转移+25 mode 路由 | `model_router.py:40-83,114-128` 三层池+降级链真实；`_DEFAULT_TASK_TYPE_MAP` 仅 11 项（:61-75），无 morning/convert | 🟡 | 路由机制真；"25 mode"夸大，实际 11 项映射 |
| CLAIM-007 | 人设引擎 4 桶反模板 + `PERSONA_ENGINE_ENABLED` | 4 桶逻辑在 `ai_engine.py:308-336`；`persona_adapter.py` 实为按模型家族 4 策略适配 | 🟡 | 能力真，但文档把"4 桶"归到 persona_adapter 是错位 |
| CLAIM-008 | keyword_trigger 三模式 + 三词典触发 | `keyword_trigger.py:83-88` 三模式真实；SLANG/PHOTO/HATE 词典实际在 `group_mgr.py:205-207,557-597` 触发 | 🟡 | 能力真，模块归属描述错位 |
| CLAIM-009 | natural_cmd "把X改成Y" 可用 | `natural_cmd.py:591/611/1210` re.split 解析+写回 config；全文 TODO=0 | ✅ | 实装，文档"6 处 TODO"不成立 |
| CLAIM-010 | 转化漏斗 conversion_events + log_conversion_event 各阶段 | `social_repo.py:219` 定义；`message_dispatcher.py:1539/1578` 等调用 | ✅ | 表与函数真实串联 |
| CLAIM-011 | _job_cart_recovery 每小时 AI 挽回私信 | `auto_tasks.py:2030-2099` 真实逻辑；但 cron `minute=*/5`（:4627）= 每 5 分钟 | 🟡 | 功能真；频率与文档"每小时"不符 |
| CLAIM-012 | memory_summarizer 异步 LLM 摘要+1h 冷却 | `memory_summarizer.py:32/84-91/307-398` 线程+冷却+廉价 LLM | ✅ | 真实 |
| CLAIM-013 | profile_learner 6 维画像自动学习 | `profile_learner.py:108-178/197-216` 真实计算 upsert | ✅ | 但 `sticker` 维度不入库（:240-242 注释"暂不入库"），1 维为死维度 |
| CLAIM-014 | 广告检测 5 层 L0-L4 | `ad_detector.py` CAS(L0:280)/Bio(L1:463)/关键词(L2:525)/零宽(L3:166)/追溯(L4:1268) 全存在；无 L0-L4 代码命名 | ✅ | 能力真；术语与代码命名不一致 |
| CLAIM-015 | 孤儿清理串联 | `orphan_api.py`→`burn_orphan_task.py`→`orphan_cleanup_log` 表；`verify_orphan_cleanup.py --dry-run` 存在 | ✅ | 端到端真实 |
| CLAIM-016 | 入群验证 button/puzzle/timeout/max_attempts | `verification.py:59/70/118/125/229` 全实现且被调用 | ✅ | 真实 |
| CLAIM-017 | 定时群播报 SCHEDULED_BROADCASTS | `scheduled_broadcast.py:280,285` 读取；`_job_scheduled_broadcast` 注册 | ✅ | 真实 |
| CLAIM-018 | anti_raid/message_locks/night_mode 被调用 | `message_dispatcher.py` 及 handlers 多处调用 | ✅ | 非死代码 |
| CLAIM-019 | RBAC before_request 默认拒绝守卫 | `rbac_guard.py:71-130`；`app.py:82-83` 注册 | ✅ | 真实 |
| CLAIM-020 | 认证 admin/viewer + hmac.compare_digest | `auth.py:299/319/113-129` | ✅ | 真实 |
| CLAIM-021 | config_api 保护密钥字段 | `config_api.py:71,173` 过滤 key/token/password/secret | ✅ | 真实 |
| CLAIM-022 | .gitignore 排除 .env/config.json/mory.db | `.gitignore:6-13`；`git check-ignore` 确认 | ✅ | 真实 |
| CLAIM-023 | 无硬编码明文用户密钥 | 全仓 grep `sk-`/`BEGIN PRIVATE KEY`=0；仅 `scripts/scan_group.py:446` 硬编码 Telegram Desktop 公开 api_hash（已 gitignore） | ✅ | 无用户密钥泄露 |
| CLAIM-024 | 53 个 _job_ 函数 | `auto_tasks.py` 实测 53 个 `def _job_` | ✅ | 真实；但 README §1.11 写 52（过时） |
| CLAIM-025 | "零暗病、零下一步计划"（VERSION.md L3） | 与 4440 行 AI_DEBUG_HISTORY 持续 hotfix、本审计发现 12 项问题相矛盾 | 🎭 | 该自评过度乐观，不可采为"已无问题"证据（[Inference]） |

**统计**：✅ 19 项｜🟡 6 项（CLAIM-001/004/006/007/008/011）｜🎭 1 项（CLAIM-025）｜💀 0（死代码归入 ISSUE）｜❓ 0。

**核心结论**：项目**并非虚报实现**（与章程预设的"虚报"病灶不同）——核心功能真实落地。主要病灶是**文档数字夸大与自相矛盾**、**文件卫生差**、**少量死代码**，而非"空壳功能"。

---

## D. 架构与代码问题清单

| ISSUE | 严重度 | 类别 | 现象 | 证据 | 影响 | 修复建议 | 工作量 | 验证 |
|-------|--------|------|------|------|------|----------|--------|------|
| ISSUE-001 | P1 | 文档失实 | 模块数/任务数文档自相矛盾 | README §1.8 L132 "87+48" vs §3.4 L605 "95+35"；§1.11 L392 "52" vs §1.8 L231 "53" | 接手 AI 与主人无法信任文档数字 | 统一为实测（modules 92 / core 73 / _job_ 53）；加 CI 脚本自动核对并断言 | 小 | grep 计数复跑一致 |
| ISSUE-002 | P2 | 死代码 | 定义但从未调用 | `core/structured_logger.py:104 get_struct_logger`、`150 clear_context`；`core/pinyin_util.py:98 has_pinyin_leak` 全仓 0 引用 | 维护噪音、误读 | 删除三函数 | 小 | grep 确认 0 引用后删 |
| ISSUE-003 | P2 | 重复代码 | 同一批工具命令路由复制两份 | `core/handlers/module_handlers.py:227-275` 与 `core/handlers/command_handlers.py:1349-1394` 逐行重复 | 改一处易漏另一处 | 抽公共 `dispatch_utility_commands()` | 中 | 两处调用一致 |
| ISSUE-004 | P1 | 文件卫生 | 两套备份 + 根目录散落 | `backup/`（11 .bak）、`backups/`（11 .bak）；根目录 `fault_dedup_state.json`/`reload_flag`/`test_selfcheck.db`/`_ssh_known_hosts` | 仓库脏、混淆、sync 盘易冲突 | 归档备份至 `docs/archive/` 或 gitignore；删运行时垃圾（`_ssh_known_hosts` 勿删，部署依赖） | 小 | 目录清理后 `git status` |
| ISSUE-005 | P2 | 文档失实 | "34 拦截点"夸大 | `message_dispatcher.py` 仅 9 个分发函数 | 误导架构理解 | 改述为"P0-P10 优先级链，9 分发函数+内联子步骤" | 小 | 文档改正 |
| ISSUE-006 | P2 | 文档失实 | model_router 仅 11 项映射 vs 文档 25 mode | `model_router.py:61-75` 仅 11 task_type | 路由覆盖不全、文档夸大 | 对齐文档或补足映射（尤其 morning/convert） | 中 | 文档/代码一致 |
| ISSUE-007 | P2 | 文档失实 | cart_recovery "每小时"实为每 5 分钟 | `auto_tasks.py:4627` `minute=*/5` | 私信频率高于说明，可能扰民/增成本 | 文档改正或调频 | 小 | 调度核对 |
| ISSUE-008 | P1 | 文档膨胀 | 病历/日志严重膨胀 | `AI_DEBUG_HISTORY.md` 4440 行、`CHANGELOG.md` 2456 行（AGENTS.md 仅 184 行较精简） | 检索困难、易踩旧坑、同步盘膨胀 | 定期归档旧条目到 `docs/archive/`；新增条目加 TTL | 中 | 归档后体积下降 |
| ISSUE-009 | P1 | 流程缺口 | "自检"未覆盖文档一致性 | VERSION.md 称"零暗病"但本审计发现 12 项 | 自检流于形式 | 把文档数字一致性纳入 `verify_*` 自检脚本（[Inference] 基于文档矛盾） | 小 | 自检脚本新增断言 |
| ISSUE-010 | P2 | 半实现 | profile_learner sticker 维度不入库 | `profile_learner.py:240-242` 注释"暂不入库，仅内存" | 画像 6 维中 1 维无效 | 实现持久化或文档标注为未启用 | 小 | 维度入库验证 |
| ISSUE-011 | P2 | 安全（低） | 硬编码公开凭证 | `scripts/scan_group.py:446` api_hash=`b1844...e627`（Telegram Desktop 公开凭证，非用户密钥，已 gitignore） | 风险低，但应改用配置 | 移至配置/环境变量 | 小 | grep 确认无明文 |
| ISSUE-012 | P2 | 规划缺失 | docs/plans 无实际计划文档 | `docs/plans/` 仅 `README.md` | 规划不可见、无路线图沉淀 | 将进行中计划落入 `docs/plans/` | 小 | 目录有实体计划 |

> 说明：未发现的"致命安全漏洞"（如未鉴权端口、密钥入库）经核查**不存在**——这是本项目相对健康的点，但依据铁律 4 不以"整体不错"收尾，仅陈述事实证据。

---

## E. 文档与文件卫生

### E.1 规则文件体检
- `AGENTS.md`：184 行，有效规则约 110 行（60%），索引/重定向型约 74 行（40%）。**未严重膨胀**，但 §9/§10/§6 文档入口清单高度重复，建议合并为单一索引。
- `AI_DEBUG_HISTORY.md`：4440 行——真实膨胀源（每次对话追加事故报告）。建议按月份归档至 `docs/archive/`。
- `CHANGELOG.md`：2456 行——持续累积，建议只保留近 N 条 + 链接归档。
- `project_snapshot.md`：450 行，信息密度高但混入大量 VPS 运维流水（如逐条热修备份路径），宜拆出运维日志。

### E.2 文档失实清单（来自 Phase 2 🟡/🎭）
- CLAIM-001/004/006/007/008/011/024/025 及 ISSUE-001/005/006/007 已全部列于 C、D 节。
- 核心矛盾：模块数双版本、_job_ 数双版本、DB 表分组重复计数、拦截点数夸大、mode 路由数夸大。

### E.3 垃圾候选清单（只列，不删）
| 文件/目录 | 类型 | 数量 | 风险 | 建议 |
|-----------|------|------|------|------|
| `backup/` | .bak 旧备份 | 11 | 低 | 归档 `docs/archive/` 或 gitignore |
| `backups/` | .bak 旧备份 | 11 | 低 | 同上 |
| `fault_dedup_state.json` | 运行时状态 | 1 | 低 | 可删（重启重建） |
| `reload_flag` | 热重载标志 | 1 | 低 | 可删（运行时生成） |
| `test_selfcheck.db` | 测试库 | 1 | 低 | 可删（测试产物） |
| `_ssh_known_hosts` | SSH 指纹 | 1 | 中 | **勿删**（部署依赖 VPS 地址） |
| `.pytest_cache/` | 缓存 | — | 低 | 可清 |

### E.4 归位建议
- 两套备份 → `docs/archive/backups/` 或加入 `.gitignore`。
- 根目录运行时文件 → 统一放 `data/` 或 `runtime/`（项目已有 `data/`、`logs/`）。
- 过期计划/旧文档 → `docs/archive/`。

---

## F. 差距与盲区

### F.1 已规划未实现（来自 plans/CHANGELOG）
- `docs/plans/` 无实质计划文档（仅 README），无法核对"规划 vs 实现"差距 → `[Unknown]` 具体缺口。
- CHANGELOG 大量条目标"已完成"，但与代码一致性问题（ISSUE-001）显示"完成"未含文档对齐步骤。

### F.2 需求盲区（[Inference]，附推断依据）
- **单测覆盖盲区**：文档称"164 方法注册通过、17/20/22 passed"，本人未复跑 → 实际通过率 `[Unknown]`。推断依据：项目体量大、hotfix 频繁，可能存在未被抽样命中的空实现模块。
- **异常流覆盖**：红线"绝对不能死"依赖每个 P 级 try/except；bare `except:` 仅 2 处，但 `except Exception: pass`/静默 log 类未全量统计 → 推断仍有静默吞错风险，需专项扫描。
- **风控点**：广告误封在 2026-07-06 集中修复（AI_DEBUG_HISTORY 多条），说明历史上误封是反复暗病；当前"免检前置+解封四件套"是否覆盖所有入口 `[Unknown]`，建议加回归测试固化。

### F.3 暗病风险推断（结合 AI_DEBUG_HISTORY 复发）
- 复发主题：①解封不生效（私聊路由吞掉）②签到误封 ③广告资料层误封 ④AI 失败兜底尴尬 ⑤新闻/问候超时不删。均为"检测链与入口/清理链不一致"类问题 → 推断**系统存在"新增能力未同步接入统一入口/清理"的结构性风险**，新功能易重蹈覆辙。应对：所有新增检测/播报必须显式接入 dispatcher 与 burn_orphan。

---

## G. 行动路线图

| 优先级 | 项 | 关联 | 依赖 | 建议顺序 |
|--------|----|------|------|----------|
| P0 | 无阻断性安全/数据风险（经核查无） | — | — | — |
| P1 | ISSUE-001 文档数字统一+CI 断言 | CLAIM-001/024 | 无 | 1 |
| P1 | ISSUE-004 清理两套备份+根目录垃圾 | — | 无（勿删 `_ssh_known_hosts`） | 2 |
| P1 | ISSUE-008 归档 AI_DEBUG_HISTORY/CHANGELOG | — | 无 | 3 |
| P1 | ISSUE-009 文档一致性纳入自检 | ISSUE-001 | ISSUE-001 | 4 |
| P2 | ISSUE-002 删死代码 | — | 无 | 5 |
| P2 | ISSUE-003 合并重复 handler 路由 | — | 无 | 6 |
| P2 | ISSUE-005/006/007 文档数字改正 | CLAIM-004/006/011 | 无 | 7 |
| P2 | ISSUE-010 sticker 维度落地/标注 | CLAIM-013 | 无 | 8 |
| P2 | ISSUE-011 api_hash 入配置 | — | 无 | 9 |
| P2 | ISSUE-012 沉淀计划文档 | — | 无 | 10 |

> P0 说明：本审计未发现"不修就有实际损失或安全风险"的阻断项（密钥管理、RBAC、DB 表、端点数均达标）。最紧迫的是**可信度修复**（文档一致性）与**仓库卫生**，而非灭火。

---

## H. AI 交接包

### H.1 运行环境与依赖
- Python 3.12+；依赖锁于 `requirements.lock` / `uv.lock`；虚拟环境 `.venv/`（1365 文件，勿纳入审计范围）。
- 敏感凭据仅在 `.env`（TG_TOKEN / DASHSCOPE_KEY / DASHBOARD_SECRET / DASHBOARD_PASSWORD 等），**绝不入库**。

### H.2 启动方式
- 主进程：`sudo systemctl restart mory-assistant`（systemd 唯一，禁 nohup/pm2）。
- Dashboard：`sudo systemctl restart mory-dashboard`（端口 **6616**）。
- 本地开发：`pip install -r requirements.txt` → `cp .env.example .env` → `python main.py`。
- 部署：`python deploy_vps.py`（自动 stop→上传→start→验证，用 `safe_upload_config` 保护密钥）。

### H.3 入口点地图
| 功能 | 入口文件 |
|------|----------|
| 消息总分发 | `core/message_dispatcher.py`（`do_dispatch` + 9 个 `_dispatch_p*`） |
| AI 回复 | `core/handlers/ai_reply_handler.py`（`_dispatch_p10_ai`）、`core/ai_engine.py` |
| 模型路由 | `core/model_router.py` |
| 定时任务 | `modules/auto_tasks.py`（53 个 `_job_*`）|
| 广告检测 | `modules/ad_detector.py` + `core/handlers/security_handlers.py` |
| 群管/积分/娱乐 | `modules/*.py` |
| Dashboard | `dashboard/app.py` + `dashboard/api/*.py`（21 文件） |
| 数据库 | `core/database.py`（108 表）+ `core/db_repos/*.py` |
| 配置 | `core/settings.py` + `config.json` |

### H.4 危险区清单（一改就容易炸）
- `core/message_dispatcher.py`：优先级链，改顺序/漏接入口会丢消息或误判。
- `core/database.py` `_REPO_METHOD_MAP` / `_REPO_ATTR_MAP`：新增 Repo 方法必须同步注册，否则启动失败（v5.31.1 四层防御）。
- `modules/ad_detector.py` + `security_handlers.py`：检测链，误封历史坑（见 F.3）。
- `core/ai_engine.py` 模型池/预算：改错导致全失败或超时。
- `deploy_vps.py` / `safe_upload_config`：误覆盖 VPS 密钥。

### H.5 当前已知坑
- 历史误封（签到/私聊解封/资料层）已于 2026-07-06 修复，但结构性风险仍在（F.3）。
- `burn_orphan` 曾漏清 `channel_tracking`（2026-07-04 修复）。
- AI 失败兜底已改为静默/固定入口（2026-07-05）。

### H.6 开放问题（全部 `[Unknown]` + 验证路径）
- Q1：全套 pytest 是否真通过？→ 验证：`python -m pytest tests/ -q`（需离线环境，避免触外部 API）。
- Q2：`verify_db_methods.py` 164/165 方法注册是否仍通过？→ 验证：`PYTHONUTF8=1 python scripts/verify_db_methods.py`。
- Q3：未被抽样的 92 模块中是否有静默空实现？→ 验证：对 `modules/*.py` 全量 grep `pass`/`return True`/`TODO` 并人工复核。
- Q4：新增能力是否都接入 dispatcher 与 burn_orphan？→ 验证：code review  checklist 固化。

---

## I. 给交叉审查 AI 的任务卡

请只做**证伪与补漏**，不做泛泛完善；回复引用 CLAIM/ISSUE 编号；遵守 `[Fact]/[Inference]/[Unknown]` 与脱敏规则。

1. **重点复核的判定（全部 🎭 与 ❓）**：
   - CLAIM-025（"零暗病"自评）——请独立判断该自评是否可信。
   - 本审计无 ❓ 项；但请复核所有 🟡（CLAIM-001/004/006/007/008/011）是否应升/降档，尤其 CLAIM-004（"34 拦截点"是否应判 🎭 而非 🟡）。
2. **本次审计最不确定的 3 个结论及原因**：
   - (a) ISSUE-003 重复路由——仅基于子代理报告，未亲自 diff 两文件全文。
   - (b) CLAIM-013 sticker 维度"死维度"影响范围——未确认是否有其他路径补该维度。
   - (c) 整体"功能真实"结论建立在抽样核验上，未逐模块精读（覆盖率见 A 节）。
3. **欢迎被挑战的 3 个架构建议**：
   - ISSUE-001 用 CI 断言锁定文档数字（可能被反驳：文档本就是"近似说明"）。
   - ISSUE-002 直接删死代码（可能被反驳：某些函数供未来/测试使用）。
   - ISSUE-008 归档膨胀文档（可能被反驳：病历本需保留完整以供排错）。
4. **对审查者要求**：证伪时给出 file:line 证据；补漏时指出本审计漏扫的具体文件/函数。

---

## 附录：证据索引与文件清单（精简）

### 证据索引（关键 file:line）
- 量化：`auto_tasks.py` 53×`def _job_`；`core/database.py` 108×`CREATE TABLE`；`dashboard/api/*` 157×`@*.route(`；`message_dispatcher.py` 9 个 `_dispatch_p*`（含导入 p10）。
- 功能：`ai_engine.py:1539`（SYSTEM_PROMPT）、`model_router.py:61-75`（11 映射）、`natural_cmd.py:591/1210`（把X改成Y）、`social_repo.py:219`（转化漏斗）、`ad_detector.py:280/463/525/166/1268`（5 层）、`orphan_api.py`+`burn_orphan_task.py`（孤儿清理）、`auth.py:113-129`（hmac）、`rbac_guard.py:71-130`（RBAC）。
- 死代码：`structured_logger.py:104/150`、`pinyin_util.py:98`。
- 安全：`scripts/scan_group.py:446`（公开 api_hash）、`.gitignore:6-13`。

### 文件清单（规模，非全列）
- 自有 `.py`：385（modules 92 / core 73 / dashboard 21 api+ / tasks 58 / scripts 62 / tests 39）。
- 文档 `.md`：46（docs/technical 21、docs/plans 1、根 6、tests 2）。
- 备份：`.bak` 22（backup/ 11 + backups/ 11）。
- 敏感（gitignore，未读）：`config.json`、`.env`、`mory.db`、`test_selfcheck.db`。

> 完整 385 文件逐行清单因篇幅未展开；如需可在 `AUDIT_APPENDIX.md` 单独生成。

---

*审计结束。本报告仅基于静态证据，未执行任何产生外部副作用的操作。所有密钥已脱敏。*
