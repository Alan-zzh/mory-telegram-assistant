<!-- 文档守则：本文件仅接受符合本文档路由表的内容；禁止追加对话流水账；规则版本随规则修订 bump，项目版本以 VERSION.md 为准。 -->

# Mory小助理 项目规则

> 规则版本 v5.38.26（2026-08-06）| 本文件是项目规则唯一入口，技术细节指向 `docs/technical/`，业务细节指向对应技术文档。

---

## A. 核心铁律

1. **先验证后动手**：改之前先 `ls` / `grep` / 读文件确认位置与现状，再动手。
2. **最小修改**：只改要改的地方，不顺手重构；保留现有风格、命名、结构、架构。
3. **证据式完工（含生产证据）**：完成的唯一标准是证据（修改文件+行号 / 命令与输出 / 测试结果）。禁止用 mock、硬编码、空壳函数冒充实现。**凡影响生产行为的改动，证据清单必须含生产验证（双服务 active + health 200 + VPS 版本 == `version.py`），未拿到生产证据不得宣称完成。**
4. **禁止走偏**：不新增任务外功能；不顺手升级依赖、更换框架、搞计划外大重构；任务外必要小改动须在台账列理由。
5. **熔断协议**：路径不存在 / 现状与描述不符 / 依赖无法安装 / 测试失败且原因不明 → 停止该任务，记 `[BLOCKED]` + 原因 + 所需信息，跳到下一个不受影响的任务；禁止硬写错误代码绕过。
6. **改后必验证**：改完跑最相关检查（`py_compile`、相关单测、dry-run）；无法验证须明说。**验证命令见 `docs/technical/runbook-ship-gate.md` 最小必查集。**
7. **诚实汇报**：做不到就说做不到 + 原因 + 需要什么；零阻塞、零取消反而可疑。
8. **新功能默认关闭**：用 `config.get('KEY', False)`，测试通过后手动开启。
9. **改配置三处同步**：`config.json.example` + 代码 `.get()` 默认值 + Dashboard 白名单，改后必跑 `python scripts/check_config_sync.py`（断言 example ↔ 白名单差集；代码默认值靠人工核对）。注释中文、变量英文；报错写入 `logs/`，不向用户甩 stack trace。

---

## B. 工作流程

### 接手顺序（一行）
`AGENTS.md` → `README.md` → `VERSION.md` → `CHANGELOG.md` 最近条目 → `AI_DEBUG_HISTORY.md` → `project_snapshot.md` → 按需查 `docs/technical/`。

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

**部署三选一（收工必填，未填视为未完工）**：
- `已部署`（附验证输出：双服务 + health + VPS 版本）
- `无需部署`（仅本地 / 无运行态影响，写明理由）
- `门禁阻断`（写明阻断项与所需信息）

### 验证门禁（部署前必过）
- **改动必查集**（按类型分组的具体命令见 `docs/technical/runbook-ship-gate.md`）：pytest 相关测试 + 全仓 unit、`verify_db_methods.py`（新增 Repo 方法必须同步 `_REPO_METHOD_MAP` / `_REPO_ATTR_MAP`）、`doc_consistency.py`、`check_config_sync.py`（配置改动时）。
- 涉及数据库：改 schema 必须同步 Alembic migration，部署后验证表结构。
- **部署前置门禁**：`git status --porcelain` 干净（脏工作树禁止部署）；`version.py` == `VERSION.md` 首行 == 本次期望版本（bump 与代码改动同 commit）；增量清单必须含 `version.py` 与本次非 `.py` 资源。一键检查：`python scripts/check_deploy_ready.py`。
- 单元测试命令：`python -m pytest tests/unit/ -q`；本地用 `.venv`（Python 3.12，与 CI 一致）。

---

## C. 本项目特有约定

### 技术选型
- 数据库 SQLite（原生连接 + WAL + busy_timeout=30s）；需更强数据库时经评估替换（迁移幂等 + 零丢失 + 回滚就绪）。
- LLM 走 `config.json` 的 `MODEL_POOLS` 三层池（`llm_light` / `llm_standard` / `llm_premium`），按 mode 路由（`model_router.py` 内置 10 个 task_type 映射），无需改代码即可扩展厂商。

### AI 对话与成交合同（红线，详见 `docs/technical/persona-engine.md`）
- 统一人设合同：`casual/curiosity/flirt/challenge/emotional/convert` 六类意图都以温情为底色（轻微绿茶感、俏皮、含蓄纯欲只按场景调权重）；各项目只用自己真实入口与业务能力。
- 对话轮数只影响熟悉度与语气；禁止按第 3/5/6 轮机械插销售/私聊/收网；普通问候与新闻播报的低频主动推进只能先去预览。
- 每轮 CTA 目标互斥：普通聊天/拒绝/取消/概念咨询无入口；价格/内容/权益/了解阶段只给 `@moryselect`；明确购买/套餐/看过预览/明确定制才给 `@MorychannelBot`；近 6 条助手历史已给过入口不重复 CTA，用户明确再索要才重发。
- 私聊正文可点击入口且不挂销售按钮；群聊每轮至多一个与正文一致入口。禁止双入口/多按钮/轰炸私聊，禁止编造表单、服务、价格、福利、交付或人工回访。
- 玄学（黄历/塔罗/易经）与定点群播报允许三入口（`@moryselect` 预览 / `@Moryfansbot` 私聊 / `@MorychannelBot` 自助下单）按北京日期确定性轮转，每张卡仍保持单一入口，禁止同卡多按钮。
- 回复者身份统一为公开的 `Mory 小助理`；不冒充真人、不写动作/场景/内心旁白、不用虚假稀缺与社会证明；正常怀疑/追问/短消息不讽刺、不挖苦、不赶客。
- 风格进化只允许人工审核的 `approved + enabled + safe` 样本进 Prompt，按场景分组（普通聊天/问候/搭讪承接/FAQ/播报）每组 ≤3 条、总数 ≤12 条；停止营销后持久化抑制普通聊天/主动推进/购物车提醒，仅再次明确询价或购买解除；30 分钟短期业务上下文独立保存按 TTL 清理。
- 风格样本投喂：管理员可投喂（群命令 `/投喂`、`/投喂文件`、Agent 问答收集），候选样本一律 `pending` 状态，经审核 `approved + enabled` 后才进 Prompt；自动蒸馏（`REPLY_EVOLUTION_DISTILL_ENABLED`）默认关闭。
- 通用"怎么买/看完了"等表达仅当当前出现本业务对象或近期存在预览/定制上下文才进成交；禁止靠枚举日常商品黑名单猜测。

### 数据库铁律
- 新增 SQL 操作必须 `CREATE TABLE IF NOT EXISTS`。
- **Repo 方法注册铁律**：新增任何 `core/db_repos/*.py` 的 public 方法，必须同步 `core/database.py` 的 `_REPO_METHOD_MAP` 和 `_REPO_ATTR_MAP`，否则启动直接失败；部署前跑 `python scripts/verify_db_methods.py`，输出"✅ DB 方法注册验证通过"才可上线。
- 代码未部署 = 修改未生效。

### 部署安全
- 禁止 `sftp.put('config.json')` 覆盖 VPS（用 `safe_upload_config()`）；禁止上传 `mory.db`；禁止 root SSH（统一 `ubuntu`）；systemd 唯一（禁 start.sh/nohup/pm2）；禁止 `.env`/密钥提交 Git。
- 部署后必须验证：`systemctl status` 双 active + `curl localhost:6616/api/health`（200）。

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
- 规则与文档不锚定历史版本号（如"vX 引入的机制"直接写机制名），避免版本漂移失真。

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
| 过程流水 | 不落盘；确有需要进 `docs/logs/` |
| **其余一切** | **禁止写入根目录** |

### 膨胀熔断（触发式 + 归档，防止流水账）
- 文档更新按 B 节触发条件执行，未达条件不写；单条超长（CHANGELOG >100 字 / AI_DEBUG >200 字）先压缩再写入。
- 根文档超行数上限（AGENTS ≤300 / snapshot ≤150 / VERSION ≤30 / CHANGELOG ≤400 / AI_DEBUG ≤300 / README ≤250）→ 整段归档到 `docs/archive/`（完整保留）后再写新内容。
- 新建文件默认进对应 `docs/` 子目录；根目录仅限六文档 + 程序运行必需的入口/配置 + `EXECUTION_LOG.md` / `EXECUTION_REPORT.md`。

### 文档数字防失真（机械断言）
- 根文档中的数量（模块数、表数、路由数、任务数等）以 `project_snapshot.md` 的 `METRICS` 块为唯一基准；新增/删除模块、表、路由、任务后必须同步 `METRICS` 并跑 `python scripts/doc_consistency.py`（含版本五源一致 / 行数上限 / CHANGELOG 条目长度断言），通过才可合入。
