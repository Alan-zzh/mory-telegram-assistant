<!-- 文档守则：本文件仅接受符合本文档路由表的内容；禁止追加对话流水账；规则版本随规则修订 bump，项目版本以 VERSION.md 为准。 -->

# Mory小助理 项目规则

> 规则版本 v5.38.31（2026-08-13）| 本文件只保存长期决策与红线；技术步骤指向 `docs/technical/`，运行态结论必须重新取证。

---

## A. 核心铁律

1. **先取证后动手**：先确认真实入口、调用链、当前 diff、相关测试；涉及 VPS、运行配置、数据库或用户可见行为时，必须从对应真实表面取证，禁止用本地文件或文档推断生产。
2. **最小必要作用域**：优先做有界修复并保留无关改动；若证据证明局部补丁会延续重复真相源、系统性竞态或结构债，先冻结基线与不变量，再在当前授权内分阶段治理，不用“最小修改”回避必要重构。
3. **证据式完工**：完成回执至少包含改动、原因、真实 diff、验证命令与结果、用户可见结果、剩余风险、部署三选一。mock、配置可见、启动成功、健康接口或文档存在均不能替代真实效果。
4. **授权不外扩**：诊断默认只读；授权修改才写代码；生产重启、部署、不可逆治理、真实账号动作必须落在当前授权内。任务外必要改动须说明因果和作用域。
5. **失败熔断**：路径/现状不符、依赖缺失、测试失败或证据冲突时，先穷尽安全只读检查和可逆替代；仍无法继续则记录 `[BLOCKED]`、原始错误和所需条件，禁止硬编码、吞错或假成功。
6. **按风险验证**：文档、配置、代码、数据库和部署分别使用 `docs/technical/runbook-ship-gate.md` 的对应门禁；相关测试先行，高风险或待部署代码再跑全仓 unit，不为纯文档改动浪费全仓测试。
7. **诚实表达**：事实、推断、估算、未验证项分开写；没有真实 A/B 或业务回执时，不把“预计节省”“可能改善”写成已实现收益。
8. **新功能默认关闭**：用 `config.get('KEY', False)`，测试通过后手动开启。
9. **改配置三处同步**：`config.json.example` + 代码 `.get()` 默认值 + Dashboard 白名单，改后必跑 `python scripts/check_config_sync.py`（断言 example ↔ 白名单差集；代码默认值靠人工核对）。注释中文、变量英文；报错写入 `logs/`，不向用户甩 stack trace。

---

## B. 工作流程

### 任务分流与最小上下文
- 状态/健康：只读执行 `runbook-vps-recon.md`，输出事实与证据缺口，不顺手修复。
- 故障/截图：以真实失败文本为规格，追踪入口→决策→输出，加入正常反例；用户已授权修复时直接完成回归。
- 代码/配置变更：读取 `AGENTS.md`、目标文件、相关测试和一份最近同类病历；只有涉及入口、版本、发布或当前状态时才读 `README.md`、`VERSION.md`、`CHANGELOG.md`、`project_snapshot.md`，不再默认通读全部根文档。
- 删除/重构：先执行 `runbook-safe-change.md` 的引用清扫；生产发布再进入 `runbook-ship-gate.md`。
- 全量历史、最近 30 天会话或全部文档只在审计/复盘任务中加载；日常修复使用当前 diff + 最近同类证据，避免重复上下文。

### 能力复用与自动化边界
- 本项目优先复用 Puzan `mory-assistant-maintenance`、生产闭环和审查能力；不得因一次任务新建重复 Skill/Agent。
- 新 Skill/Agent/Automation 仅在同类工作至少重复 2 次、输入稳定、流程可重复、结果可机械验收时进入候选；先给日期/频次/收益估算和验收标准，获批后再实施。
- Automation 只适合只读巡检、漂移检测、部署后取证和周期复盘；不得自动部署、重启、修改生产配置、执行封禁/解封或操作真实账号。正常时静默，失败时必须附原始证据和最近一次成功时间。
- “已安装/已配置/已路由”不等于自动化已运行；生效必须有最近运行时间、退出码、产物或业务回执。
- 项目内巡检唯一入口为 `scripts/project_audit_control.py`：`pass=0`、`evidence_gap=2`、`failed=3`，health 只判 liveness；定时定义由 `scripts/manage_project_audit_timers.py` 管理，默认仅输出计划，未显式 `--apply` 不得修改 systemd。
- Puzan `mory-assistant-maintenance` 是唯一项目 Skill，`handoff/task-continuity` 是唯一续接入口，`record-keeping/records-autopilot` 是唯一记录治理链；历史 handoff、audit report 和 subagent result 只作历史证据，不是当前运行态或能力注册。

### 收工闭环（替代旧"六件套"，触发式执行，禁止"下次再补"）
按以下触发条件更新文档，**未达条件不写**（防止流水账膨胀）；达到条件的同会话内完成。

| 文档 | 必须更新的触发条件 | 粒度 |
|------|-------------------|------|
| `CHANGELOG.md` | 用户可感知改动：升版 / 事故修复 / 配置或部署变化 | 一行 ≤100 字，文件 ≤5 个+等；**验收证据写 commit message**，详细报告落 `runtime/audit-reports/` |
| `AI_DEBUG_HISTORY.md` | 反复暗病 ≥2 次 / 系统性结构风险 / 生产事故根因 | 单条 ≤200 字（问题\|根因\|解法\|预防）；一次性问题不写 |
| `project_snapshot.md` | METRICS 数字变化 / 模块状态变化 / 发布 | 覆盖式；"最近大事"恒 ≤3 条，每条 ≤50 字 |
| `VERSION.md` | 仅升版时（与 `version.py` 同步） | 版本号 + 日期一行 |
| `README.md` | 入口 / 命令 / 部署方式变化 / 版本发布 | 顶部版本号与 VERSION 一致 |
| `AGENTS.md` | 规则修订（须用户明确同意） | 头部规则版本 bump |

发生实质写入时复用同一 active handoff；交付前由当前宿主运行 Puzan records autopilot `--apply --strict` 后立即以同一 fingerprint 跑 `--verify-only --strict`。只读巡检本身不触发记录写入，也不依赖计划任务或常驻 records watcher。

### 统一完成回执
1. 完成/决策；2. 改动文件与真实 diff；3. 验证命令与原始结果摘要；4. 生产版本/哈希与运行态（如适用）；5. 用户可见业务探针；6. 剩余风险/证据缺口；7. 部署三选一。重复细节落 `runtime/audit-reports/`，根文档不写流水账。

**部署三选一（收工必填，未填视为未完工）**：
- `已部署`（附双服务/进程、health、VPS 版本或文件哈希、启动窗口日志、受影响业务探针；调度改动另附持久四态）
- `无需部署`（仅本地 / 无运行态影响，写明理由）
- `门禁阻断`（写明阻断项与所需信息）

### 验证门禁（部署前必过）
- **改动必查集**（具体命令见 `docs/technical/runbook-ship-gate.md`）：目标测试；待部署/高风险代码再跑全仓 unit；新增 Repo 方法跑 `verify_db_methods.py`；文档跑 `doc_consistency.py`；配置跑 `check_config_sync.py`。
- 涉及数据库：改 schema 必须同步 Alembic migration，部署后验证表结构。
- **部署前置门禁**：`git status --porcelain` 干净（脏工作树禁止部署）；`version.py` == `VERSION.md` 首行 == 本次期望版本（bump 与代码改动同 commit）；增量清单必须含 `version.py` 与本次非 `.py` 资源。一键检查：`python scripts/check_deploy_ready.py`。
- 单元测试命令：`python -m pytest tests/unit/ -q`；本地用 `.venv`（Python 3.12，与 CI 一致）。

---

## C. 本项目特有约定

### 技术选型
- 数据库 SQLite（原生连接 + WAL + busy_timeout=30s）；需更强数据库时经评估替换（迁移幂等 + 零丢失 + 回滚就绪）。
- LLM 以生产 `config.json` 的 `MODEL_POOLS` 和 `core/model_router.py` 当前实现为准；任务类型和模型数量属于可变运行配置，规则不写死数量。

### AI 对话与成交合同（红线，完整合同见 `docs/technical/persona-engine.md`）
- 身份始终是公开的 `Mory 小助理`，不冒充真人，不写动作/场景/内心旁白，不编造价格、福利、交付、人工回访、虚假稀缺或社会证明。
- CTA 状态互斥：普通聊天/拒绝/取消/概念咨询为 `none`；了解内容与权益先 `preview`（`@moryselect`）；明确购买/套餐/看过预览/定制才 `subscribe`（`@MorychannelBot`）。近 6 条已给入口不重复，用户明确再索要才重发。
- 私聊正文可点击但不挂销售按钮；群聊每轮至多一个与正文一致的目标。禁止双入口、无关购物后继续推进或按固定轮数机械销售。
- 敏感话题只使用管理员确认的合规承接，不评判、不教唆；风格进化仅允许人工审核后的 `approved + enabled + safe` 样本，自动蒸馏默认关闭。

### 数据库铁律
- 新增表定义必须 `CREATE TABLE IF NOT EXISTS`；schema 变化同步 Alembic migration、幂等升级与回滚验证，普通 CRUD 不得夹带隐式建表。
- **Repo 方法注册铁律**：新增任何 `core/db_repos/*.py` 的 public 方法，必须同步 `core/database.py` 的 `_REPO_METHOD_MAP` 和 `_REPO_ATTR_MAP`，否则启动直接失败；部署前跑 `python scripts/verify_db_methods.py`，输出"✅ DB 方法注册验证通过"才可上线。
- 代码未部署 = 修改未生效。

### 部署安全
- 禁止 `sftp.put('config.json')` 覆盖 VPS（用 `safe_upload_config()`）；禁止上传 `mory.db`；禁止 root SSH（统一 `ubuntu`）；systemd 唯一（禁 start.sh/nohup/pm2）；禁止 `.env`/密钥提交 Git。
- systemd unit 必须 `root:root 0644`；`.env`/数据库/敏感配置按最小权限；root cron 只能执行 root-owned、普通用户不可写的脚本。部署器必须使用不可预测且权限受控的临时文件，禁止固定 world-writable `/tmp` 路径产生提权窗口。

### 生产真相与防假绿
- 运行态优先级：真实用户/业务探针 > 当前进程与远端文件/配置/数据库 > 持久执行历史 > journal > 本地代码 > 文档。低层证据不能覆盖高层失败。
- `/api/health` 只证明 HTTP/liveness，不证明版本、调度完整性或业务成功；版本必须直接读 VPS `version.py` 或受影响文件哈希，并与本地预期比对。
- `scheduler_metrics` 是持久历史，不是当前 APScheduler 注册表；`task_execution_history` 仅覆盖进入事务审计的任务。调度结论必须明确 coverage，并结合当前进程日志/注册集、四态历史和受影响业务回执。
- 生产 `config.json` 是运行配置真相；本地 `config.json` 仅开发基线，不能据此声称生产开关、模型池或任务已生效，也不得覆盖生产配置。对比只报告键/值漂移，不读取或输出凭据。
- 当前生产状态会漂移，`project_snapshot.md` 只记录已验证快照；每次部署、故障或健康判断都必须重新执行只读探针。

### 运维 Runbook（变更 / 部署 / 排查前必读）
- 上线前状态核实：`docs/technical/runbook-vps-recon.md`（只读探针，禁止本地推断）。
- 改动后验证 + 收工闭环 + 部署门禁：`docs/technical/runbook-ship-gate.md`。
- 删除 / 重构前引用清扫：`docs/technical/runbook-safe-change.md`。
- 架构真相（媒体 Bot 在 `/opt/moryfansbot`，非本仓库）：`docs/technical/architecture-truth.md`。

### 广告治理（红线，详见 `docs/technical/ad-detection.md`）
- 不踢人：永久禁言 + 删除消息 + `global_blacklist` + 历史清理；统一入口 `modules/ad_enforcement.py:enforce_ad_user()`。
- 回复、人设、预览、转化和文案优化不得直接或间接授权删除消息/禁言/写黑名单；治理动作必须经过独立的逐条证据门禁，行为追踪本身不是广告证据。
- 确认误封时统一恢复 Telegram 发言权限，并清理 `blacklist`、`global_blacklist`、`mute_records`、`ad_suspicious_users`；恢复后重新查询四项持久态；已删消息无法恢复须明说，不得假报。

### 凭据
- 唯一存 `.env`，代码用 `os.environ["KEY"]`；文档只写 KEY_NAME 不写明文；报告对外只显示前 4 位与后 4 位。

### 去陈旧与去失真
- 文件说存在但真实目录不存在 → 修正；README / snapshot / 规则互相矛盾 → 以实测为准统一；已实现功能无技术文档 → 补 `docs/technical/`。
- 规则不写易漂移数量、行号、模型/任务清单或“当前已健康”；这些数据进入 `project_snapshot.md` 的可机械区块或审计报告。历史版本只出现在 CHANGELOG/归档，不进入长期机制说明。
- 发现重复规则时保留一个规范所有者，其余改为链接；被代码、日志或生产证据证伪的陈述同会话删除或修正，禁止保留“以后再清”。

---

## D. 文档路由表（永久规则）

| 内容 | 落点 |
|------|------|
| 长期规则 | `AGENTS.md`（改规则须用户明确同意） |
| 版本 | `VERSION.md` |
| 用户可感知改动 | `CHANGELOG.md`（一行 ≤100 字） |
| 排错教训 / 反复暗病 | `AI_DEBUG_HISTORY.md`（问题\|根因\|解法\|预防） |
| 当前状态 | `project_snapshot.md`（覆盖式） |
| 计划 / 方案 | `docs/plans/` |
| 技术说明 | `docs/technical/` |
| 调研 / 背景 | `docs/research/` |
| 愿景 / 路线图 | `docs/vision/` |
| 审计与完工报告 | `runtime/audit-reports/` |
| 过程流水 | 默认不落盘；确有审计价值才进 `docs/logs/` |
| **其余一切** | **禁止写入根目录** |

### 膨胀熔断（触发式 + 归档，防止流水账）
- 文档更新按 B 节触发条件执行，未达条件不写；单条超长（CHANGELOG >100 字 / AI_DEBUG >200 字）先压缩再写入。
- 根文档超行数上限（AGENTS ≤300 / snapshot ≤150 / VERSION ≤30 / CHANGELOG ≤400 / AI_DEBUG ≤300 / README ≤250）→ 整段归档到 `docs/archive/`（完整保留）后再写新内容。
- 新建文件默认进对应 `docs/` 子目录；根目录仅限六份治理文档和程序运行必需入口/配置。既有 `EXECUTION_LOG.md` / `EXECUTION_REPORT.md` 视为冻结历史，不再追加。

### 文档数字防失真（机械断言）
- 根文档中的数量（模块数、表数、路由数、任务数等）以 `project_snapshot.md` 的 `METRICS` 块为唯一基准；新增/删除模块、表、路由、任务后必须同步 `METRICS` 并跑 `python scripts/doc_consistency.py`（含版本五源一致 / 行数上限 / CHANGELOG 条目长度断言），通过才可合入。
