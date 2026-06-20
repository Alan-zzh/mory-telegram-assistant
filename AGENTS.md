# Mory小助理 项目规则

> v5.27.0-RC1 | 本文件是项目规则唯一入口，技术细节指向 `docs/technical/`

---

## 1. 接手流程

新会话按此顺序阅读：
1. `AGENTS.md` → 规则与协作方式（本文件）
2. `README.md` → 项目简介与快速开始
3. `VERSION.md` → 当前版本号
4. `CHANGELOG.md` 最近 2 条 → 避免重复造轮子
5. `AI_DEBUG_HISTORY.md` → 踩坑病历
6. `project_snapshot.md` → 目录/模块/部署状态
7. `docs/technical/` → 按需查阅技术细节

---

## 2. 根目录六件套

| 文件 | 作用 | 更新时机 | 禁止内容 |
|------|------|----------|----------|
| `AGENTS.md` | 项目规则唯一入口 | 长期规则/协作方式/文档归档规范变化时 | 长篇技术细节、流水账、固定 AI 署名、过时计划、与其他文件重复的大段内容 |
| `README.md` | 项目简介、运行方式、部署 | 使用方式/启动方式/部署方式/用户可见功能变化时 | 排错流水账、历史版本长记录、未实现愿景、敏感凭据 |
| `AI_DEBUG_HISTORY.md` | 踩坑病历与反复问题记录 | 排查 bug/修复反复问题/发现高风险坑/解决环境部署依赖问题后 | 普通功能介绍、无关聊天、没有结论的猜测、凭据明文 |
| `CHANGELOG.md` | 用户可感知变更记录 | 完成用户可感知改动后 | 详细排错过程、长篇技术解释、未完成计划 |
| `VERSION.md` | 版本号与当前版本摘要锚点 | `CHANGELOG.md` 出现新版本级变更时同步 | 多版本长篇历史、技术细节、计划列表 |
| `project_snapshot.md` | 项目当前真实状态快照 | 目录结构/服务管理方式/依赖/配置/模块边界/部署状态变化时 | 过时历史流水账、愿景、详细 bug 复盘、未验证状态 |

---

## 3. 文档真相源

### 3.1 根目录六件套
见 §2。这是项目真相源的第一层。

### 3.2 `docs/` 统一目录

所有细分文档归档到英文目录 `docs/`，避免中文目录名造成编码/终端/同步盘识别问题：

| 目录 | 职责 |
|------|------|
| `docs/technical/` | 已实现功能、模块、关键修复、重要技术约束（每篇只讲一个主题） |
| `docs/plans/` | 计划、实施方案、任务拆解、重构方案、后续执行计划 |
| `docs/vision/` | 愿景、路线图、产品方向、长期规划 |
| `docs/reference/` | 外部资料、接口说明、调研记录、背景材料 |
| `docs/archive/` | 过时但仍需保留的旧文档 |

**禁止**新建 `AI/`、`ai-docs/`、`rules/`、`specs/`、`plans/`（根目录）、临时文档、交接文档等分散目录。已有散落文档在确认用途后迁入 `docs/` 对应目录。

### 3.3 愿景与现状分离
- 愿景、路线图、产品方向 → `docs/vision/`
- `README.md` 和 `project_snapshot.md` 只写当前真实状态，不把"未来想做"写成"已完成"
- 发现旧文档把"未来想做"写成"已经完成"，必须修正

---

## 4. 行为规范

1. **先验证后动手**：用 `ls`/`grep` 确认文件位置、模块数量后再修改
2. **最小修改**：只改要改的地方，不顺重构
3. **模块化拆分**：禁止单文件跑全部功能；按职责拆分模块，单文件过大时拆函数或拆子模块，不硬设行数上限
4. **改后必验证**：`python -m py_compile` + 部署验证
5. **新功能默认关闭**：`config.get('KEY', False)`，测试后手动开启
6. **改配置三处同步**：`config.json.example` + 代码 `.get()` + Dashboard 面板
7. **注释中文**，变量名英文，报错写 `logs/` 不甩 stack trace

---

## 5. 技术选型约束

### 数据库
- 当前默认 SQLite（WAL + busy_timeout + 单线程写入队列 + 连接代理全量化），适合单机 VPS
- 不排斥更优方案：若业务增长到需要 Postgres/MySQL/分布式存储，经评估后可替换
- 替换前提：迁移脚本幂等 + 数据零丢失 + 回滚方案就绪

### LLM 模型
- 已接入：阿里千问百炼（固定 API）
- 可扩展：DeepSeek / OpenAI GPT 系列 / Google Gemini 系列等
- 路由策略：三层模型池（llm_light 廉价池 / llm_standard 标准池 / llm_premium 高端池），按 mode 路由
- 新模型接入：走 `config.json` 的 `MODEL_POOLS` 配置项，无需改代码

---

## 6. 记录规范（更新路由）

| 事件 | 更新文件 |
|------|----------|
| 项目长期规则变化 | `AGENTS.md` |
| 使用方式/部署方式/项目说明变化 | `README.md` |
| bug / 踩坑 / 修复 / 根因 / 最终修复 | `AI_DEBUG_HISTORY.md` |
| 用户可感知变更（新增/删除/行为变化/重要修复/配置部署变化） | `CHANGELOG.md` |
| 版本变化 | `VERSION.md`（与 `CHANGELOG.md` 同步） |
| 目录/依赖/服务/模块/阶段状态变化 | `project_snapshot.md` |
| 功能实现/模块说明/关键修复细节 | `docs/technical/` |
| 计划/方案/任务拆解/重构方案 | `docs/plans/` |
| 愿景/路线图/产品方向 | `docs/vision/` |
| 过时但需保留的旧资料 | `docs/archive/` |
| 规则变化 | `AGENTS.md` |

---

## 7. 重点禁忌

### 部署安全
- 禁止 `sftp.put('config.json')` 覆盖 VPS（用 `safe_upload_config()`）
- 禁止 `sftp.put('mory.db')` 上传数据库
- 禁止 root SSH 部署（统一 `ubuntu`）
- 禁止 `start.sh`/`nohup`/`pm2`（systemd 唯一）
- 禁止 `.env`/密钥提交 Git
- 部署后必须验证：`systemctl status` 双 active + `curl localhost:6616/api/health`

### 广告治理
- 不踢人：永久禁言 + 删除消息 + `global_blacklist` + 历史清理
- 统一入口：`modules/ad_enforcement.py:enforce_ad_user()`

### 数据库
- 改 schema 必须同步 migration，部署后验证表结构
- 新增 SQL 操作必须 `CREATE TABLE IF NOT EXISTS`
- 代码未部署 = 修改未生效

### 凭据
- 唯一存 `.env`，代码用 `os.environ["KEY"]`
- 文档只写 KEY_NAME，不写明文

### 文档纪律
- 细分文档归档 `docs/` 英文子目录
- 技术细节不塞 AGENTS.md，指向 `docs/technical/`
- 引用代码前先 grep 确认行号
- 不在文档中固定 AI 软件署名（如 `[Trae]`/`[CodeBuddy]`）；如需追踪执行者，只能在 `CHANGELOG.md`/`AI_DEBUG_HISTORY.md` 条目中按当前 AI 环境自适应标注，识别不到时省略

### 去陈旧与去失真
- 文件说存在但真实目录不存在 → 修正
- `README`/`snapshot`/规则文件互相矛盾 → 以实测为准统一
- 旧计划没有状态导致误判 → 补状态或迁 `docs/archive/`
- 已实现功能没有技术文档 → 补 `docs/technical/`
- 反复踩坑只在聊天说过 → 写入 `AI_DEBUG_HISTORY.md`
- 同一内容多文件重复且版本不一致 → 合并或归档
- 长篇废话/空泛口号/过度流程化 → 精简

---

## 8. 失败升级

| 失败次数 | 动作 |
|:-------:|------|
| 1 | 检查环境，自动重试 |
| 2 | 换参数/路径/版本 |
| 3 | 换方案 |
| 3次都失败 | 回滚，告知用户需人工介入 |

---

## 9. 技术文档索引

详细技术说明见 `docs/technical/` 目录（共 21 篇文档，按主题命名）。常用入口：

- `capability-matrix.md` - 能力矩阵
- `ad-detection.md` - 广告检测 5 层
- `config-reload.md` - 配置热重载
- `orphan-cleanup.md` - 孤儿清理
- `vps-deploy-trap.md` - VPS 部署陷阱
- `broadcast-rich-format.md` - 播报富文本
- `persona-engine.md` - 人设引擎
- `scene-triggers.md` - 场景触发
- `load-test-threshold-tuning.md` - 压测阈值调优

完整列表见 `docs/technical/` 目录。计划文档见 `docs/plans/`，愿景文档见 `docs/vision/`。

---

## 10. 快速索引

- 项目介绍/启动/部署 → `README.md`
- 变更日志 → `CHANGELOG.md`
- 版本号 → `VERSION.md`
- 踩坑记录 → `AI_DEBUG_HISTORY.md`
- 代码库表/模块 → `project_snapshot.md`
- 技术细节 → `docs/technical/`
- 计划 → `docs/plans/`
- 愿景 → `docs/vision/`
