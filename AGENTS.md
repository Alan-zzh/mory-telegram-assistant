<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理 项目规则

> v5.38.1 | 本文件是项目规则唯一入口，技术细节指向 `docs/technical/`。

---

## A. 核心铁律

1. **先验证后动手**：改之前用 `ls` / `grep` / 读文件确认位置、模块数量、现状，再动手。
2. **最小修改**：只改要改的地方，不顺手重构；保留现有风格、命名、结构、架构。
3. **证据式完工**：完成的唯一标准是证据（修改文件+行号 / 命令与输出 / 测试结果）。禁止用 mock、硬编码返回、空壳函数冒充实现；确需占位必须在台账标"未完成/占位"。
4. **禁止走偏**：不新增任务外功能；不顺手升级依赖、更换框架、搞计划外大重构；任务外的必要小改动须在台账列理由。
5. **熔断协议**：路径不存在 / 现状与描述不符 / 依赖无法安装 / 测试失败且原因不明 → 停止该任务，记 `[BLOCKED]` + 原因 + 所需信息，跳到下一个不受影响的任务。禁止硬写错误代码绕过。
6. **改后必验证**：改完跑最相关的检查（如 `python -m py_compile`、相关单测、dry-run）；无法验证须明说。
7. **诚实汇报**：做不到就说做不到 + 原因 + 需要什么。零阻塞、零取消反而可疑，不要为"好看"隐瞒问题。
8. **新功能默认关闭**：用 `config.get('KEY', False)`，测试通过后手动开启。
9. **改配置三处同步**：`config.json.example` + 代码 `.get()` 默认值 + Dashboard 面板，三处一致。
10. **注释中文、变量英文**；报错写入 `logs/`，不向用户甩 stack trace。
11. **改完默认部署**：凡会影响生产行为的更新或修复，完成本地验证并提交可信 Git commit 后，默认直接增量部署 VPS，无需再次询问；部署前必须只读侦察并备份，禁止覆盖 `.env` / `config.json` / `mory.db`，失败立即回滚；部署后必须验证双服务、health、版本、当前进程日志和最小真实业务回执，未拿到生产证据不得宣称完成。仅当老板明确说“仅本地/不要部署”、改动不影响运行态，或安全门禁阻断时例外。

---

## B. 工作流程

### 接手顺序
1. `AGENTS.md`（本文件）→ 规则与协作方式
2. `README.md` → 简介与快速开始
3. `VERSION.md` → 当前版本
4. `CHANGELOG.md` 最近条目 → 避免重复造轮子
5. `AI_DEBUG_HISTORY.md` → 反复踩坑病历
6. `project_snapshot.md` → 当前真实状态
7. `docs/technical/` → 按需查技术细节

### 日常开发收工六件套（同一会话内完成，禁止"下次再补"）
根文档仅限六文档，须保持同步：AGENTS.md / VERSION.md / CHANGELOG.md / AI_DEBUG_HISTORY.md / project_snapshot.md / README.md。
1. `CHANGELOG.md` 追加：`日期 | 类型 | 一句话 | 涉及文件`。
2. `project_snapshot.md` 覆盖更新对应模块状态区块（METRICS 与代码一致）。
3. `AI_DEBUG_HISTORY.md` 有新教训则按（问题 | 根因 | 解法 | 预防）追加。
4. `VERSION.md` 版本/阶段有变则 bump；`AGENTS.md` 规则有变则同步；`README.md` 入口有变则同步。
5. 完成后跑 `python scripts/doc_consistency.py` 确认通过。

### 验证门禁
- 任何新代码改动，合并前至少两条证据（文件路径+diff 摘要 / 命令输出 / 测试结果，三者至少其二）。
- 涉及数据库：改 schema 必须同步 Alembic migration，部署后验证表结构。
- 新增 Repo 方法：必须同步 `core/database.py` 的 `_REPO_METHOD_MAP` / `_REPO_ATTR_MAP`；部署前跑 `python scripts/verify_db_methods.py`，输出"✅ DB 方法注册验证通过"才可上线。

---

## C. 本项目特有约定

### 技术选型
- 数据库默认 SQLite（WAL + busy_timeout + 单线程写入队列 + 连接代理）。业务增长需更强数据库时，经评估可替换（迁移脚本幂等 + 数据零丢失 + 回滚就绪）。
- LLM：已接入阿里千问百炼；可扩展 DeepSeek / OpenAI / Gemini。路由走 `config.json` 的 `MODEL_POOLS`，无需改代码。
- 模型路由三层池：`llm_light` / `llm_standard` / `llm_premium`，按 mode 路由；当前 `model_router.py` 内置 10 个 task_type 映射。

### AI 对话与成交合同
- MoryFansBot 与本项目统一清冷、傲娇、温柔的人设底色及正常聊天合同，但各项目只使用自己的真实入口和业务能力。
- 对话轮数只影响熟悉度和语气，禁止按第 3/5/6 轮机械插入销售、私聊或收网话术；低频主动推进也只能先去预览。
- 每轮 CTA 目标互斥：普通聊天、拒绝、取消、定制概念咨询为无入口；价格、内容、权益和了解阶段只给 `@moryselect`；明确购买、套餐选择、确认看过预览或明确提出定制需求才给 `@MorychannelBot`。
- 最近 6 条助手历史已经给过自助入口时，后续确认和细节补充继续承接但不重复 CTA；用户明确再次索要下单入口时才重发。
- 私聊使用正文可点击入口且不挂销售按钮；群聊每轮至多一个与正文一致的入口。禁止额外轰炸私聊、双入口、多销售按钮，以及编造定制表单、服务能力、价格、福利、交付或人工回访。
- 回复者身份统一为公开的 `Mory 小助理`；清醒/温柔/小傲娇只靠措辞、节奏和长短表达，不冒充真人，不写动作、场景或内心旁白，不使用虚假稀缺和社会证明。
- 风格进化只允许管理员人工审核的 `approved + enabled + safe` 样本进入 Prompt，最多 3 条；默认不保存用户/助手原文，禁止 AI 自动改写或直接发布基础 Prompt。
- 用户明确停止营销后，持久化抑制普通聊天、主动推进和购物车提醒；只有再次明确询价或购买才解除。进化遥测默认不存原文，但 30 分钟短期业务上下文须独立保存并按 TTL 清理，以保证跨重启承接和 CTA 去重
- 通用“怎么买/看完了”等表达只有当前出现本业务对象或近期存在预览/定制上下文时才进入成交；禁止靠枚举日常商品黑名单猜测

### 数据库铁律
- 新增 SQL 操作必须 `CREATE TABLE IF NOT EXISTS`。
- **Repo 方法注册铁律**：新增任何 `core/db_repos/*.py` 的 public 方法，必须同步在 `core/database.py` 的 `_REPO_METHOD_MAP` 和 `_REPO_ATTR_MAP` 添加映射。漏注册会导致启动直接失败（v5.31.1 四层防御）。
- 代码未部署 = 修改未生效。

### 部署安全
- 禁止 `sftp.put('config.json')` 覆盖 VPS（用 `safe_upload_config()`）。
- 禁止 `sftp.put('mory.db')` 上传数据库。
- 禁止 root SSH 部署（统一 `ubuntu`）；禁止 `start.sh` / `nohup` / `pm2`（systemd 唯一）。
- 禁止 `.env` / 密钥提交 Git。
- 部署后必须验证：`systemctl status` 双 active + `curl localhost:6616/api/health`。

### 运维 Runbook（变更 / 部署 / 排查前必读）
- 上线前状态核实：`docs/technical/runbook-vps-recon.md`（只读探针，禁止本地推断）。
- 改动后验证 + 收工六件套：`docs/technical/runbook-ship-gate.md`。
- 删除 / 重构前引用清扫：`docs/technical/runbook-safe-change.md`。
- 架构真相（媒体 Bot 在 `/opt/moryfansbot`，非本仓库）：`docs/technical/architecture-truth.md`。

### 广告治理
- 不踢人：永久禁言 + 删除消息 + `global_blacklist` + 历史清理。
- 统一入口：`modules/ad_enforcement.py:enforce_ad_user()`。

### 凭据
- 唯一存 `.env`，代码用 `os.environ["KEY"]`。
- 文档只写 KEY_NAME，不写明文；报告对外只显示前 4 位与后 4 位。

### 文档纪律
- 细分文档归档 `docs/` 英文子目录（technical / plans / vision / reference / archive）。
- 技术细节不塞进 AGENTS.md，指向 `docs/technical/`。
- 引用代码前先 grep 确认行号；不在文档固定 AI 软件署名。

### 去陈旧与去失真
- 文件说存在但真实目录不存在 → 修正。
- README / snapshot / 规则互相矛盾 → 以实测为准统一。
- 已实现功能无技术文档 → 补 `docs/technical/`。

---

## D. 文档路由表（永久规则）

| 内容 | 落点 |
|------|------|
| 长期规则 | `AGENTS.md`（改规则须用户明确同意） |
| 版本 | `VERSION.md` |
| 用户可感知改动 | `CHANGELOG.md` |
| 排错教训 / 反复暗病 | `AI_DEBUG_HISTORY.md`（问题\|根因\|解法\|预防） |
| 当前状态 | `project_snapshot.md`（覆盖式） |
| 计划 / 方案 | `docs/plans/` |
| 技术说明 | `docs/technical/` |
| 调研 / 背景 | `docs/research/` |
| 愿景 / 路线图 | `docs/vision/` |
| 审计与完工报告 | `runtime/audit-reports/` |
| 过程流水 | `docs/logs/` 或不落盘 |
| **其余一切** | **禁止写入根目录** |

### 膨胀熔断
- 任一根文档超行数上限（AGENTS ≤300 / snapshot ≤150 / VERSION ≤30 / CHANGELOG ≤400 / AI_DEBUG_HISTORY ≤300）→ 先归档压缩到 `docs/archive/`，再写入新内容。
- 新建文件默认进对应 `docs/` 子目录；能进根目录者仅限六文档 + 程序运行必需的入口/配置 + `EXECUTION_LOG.md` / `EXECUTION_REPORT.md` + `_quarantine_` 目录。

### 文档数字防失真
- 根文档中的数量（模块数、表数、路由数、任务数等）以 `project_snapshot.md` 的 `METRICS` 块为唯一基准。
- 新增/删除模块、表、路由、任务后，必须同步更新 `METRICS` 块并运行 `python scripts/doc_consistency.py` 确认通过，否则不得合入。
