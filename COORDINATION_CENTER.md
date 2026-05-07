# Mory小助理 · 多窗口协同作战中心

> 生成时间：2026-05-01
> 版本：v4.5.16
> 本文件是整个项目的"总指挥部"，所有分窗口的AI都必须遵守这里制定的规则

---

## 一、项目全景图

**项目定位**：Telegram群管机器人 + 私域运营自动化平台
**当前版本**：v4.5.16
**技术栈**：Python3 + pyTelegramBotAPI + SQLite(WAL) + Flask
**部署**：VPS（systemd进程管理）
**数据库**：mory.db（13张表）
**核心配置**：config.json（人设/模型池/路由/价格）

### 核心资产清单
| 资产 | 位置 | 作用 |
|------|------|------|
| 项目快照 | project_snapshot.md | 每个AI新会话必读，了解当前状态 |
| 病历本 | AI_DEBUG_HISTORY.md | 记录所有修过的bug和失败方案，禁止重复踩坑 |
| 部署工具 | core/deploy_utils.py | 安全上传配置，保护密钥不被覆盖 |
| 规则文档 | .trae/rules/project_rules.md | 所有AI必须遵守的铁律 |

---

## 二、板块拆分方案（6大任务部门）

整个项目拆分为 **6个独立板块**，每个板块可以开一个独立对话窗口并行工作。

### 🏢 总指挥部（就是当前窗口）
- **文件位置**：本文件 + project_snapshot.md + AI_DEBUG_HISTORY.md
- **职能**：全局统筹、版本管理、最终审核、跨板块协调
- **广告词**："我是整个项目的CEO，所有板块的成果最终汇总到我这里，我确保整体不崩溃、不冲突"
- **负责AI**：你（老板）+ 当前对话窗口

---

### 📦 板块A：AI引擎与模型路由层
- **窗口广告词**："我管AI的大脑——6个模型池、三层智能路由、多模型轮换、全模态优先、熔断缓存，让Bot聪明又省钱"
- **涉及文件**：
  - `core/ai_engine.py` — 主AI引擎（多池多模型轮换）
  - `core/optimizer.py` — 优化引擎（语义缓存+熔断+令牌桶）
  - `universal_ai_router/` — 通用AI路由模块（独立项目）
  - `config.json` — MODEL_POOLS / MODE_ROUTING / MODEL_COSTS
- **核心能力**：
  - 6个模型池：llm / vision / omni / voice_tts / voice_asr / embedding
  - 三层路由：llm_light / llm_standard / llm_premium
  - 22个mode映射到不同层级
  - 自动拉黑/切换/恢复模型
  - 联网新闻7源并行抓取
- **可委托的Skills/智能体**：`ai-integration-engineer`、`backend-architect`
- **什么时候找它**：模型切换、API报错、路由调整、新增模型池、优化响应速度

---

### 🤖 板块B：Bot核心与消息分发层
- **窗口广告词**："我是Bot的心脏——消息从哪来、怎么分发、先处理什么后处理什么、回复怎么追踪，全部我说了算"
- **涉及文件**：
  - `main.py` — 主入口（消息分发+中间件+10级优先级）
  - `core/mory_bot.py` — Bot封装层（reply_and_track追踪）
  - `core/database.py` — 数据库层（13张表+线程安全）
  - `core/resource_manager.py` — 资源管理（图片/语音池+锁）
  - `core/logging_util.py` — 日志工具
  - `core/monitoring.py` — 系统监控
  - `core/token_statistics.py` — Token统计
- **核心能力**：
  - ReplySnifferMiddleware 全局嗅探器
  - P0~P10 消息分发优先级链
  - 阅后即焚追踪机制
  - 连续对话追踪（绿茶风反问/转化引导）
  - Function Calling（价格表/私聊引导）
  - 数据库线程安全锁
- **可委托的Skills/智能体**：`backend-architect`、`performance-expert`
- **什么时候找它**：消息不回复、分发顺序调整、数据库报错、新增消息处理器、线程安全问题

---

### 📋 板块C：功能模块层
- **窗口广告词**："我是Bot的十八般武艺——群管、定时任务、关键词触发、自然语言配置、内容处理，你要的功能全在这"
- **涉及文件**：
  - `modules/admin_cmds.py` — 管理员指令
  - `modules/auto_tasks.py` — 定时任务（12个任务+防重复机制）
  - `modules/content.py` — 内容处理（打码/塔罗/勋章/频道转发）
  - `modules/group_mgr.py` — 群管理（欢迎/敏感词/刷屏/黑名单）
  - `modules/keyword_trigger.py` — 关键词触发（静态/AI/动作三种模式）
  - `modules/natural_cmd.py` — 自然语言指令（塔罗/解梦/树洞/配置修改）
  - `modules/optimizer_admin.py` — 运营管理指令
- **核心能力**：
  - 定时任务：早安/午安/晚安、早中晚新闻、塔罗、每日报告
  - 防重复机制：_can_run + _mark_done + task_log数据库持久化
  - 关键词触发：3种回复模式（静态文本/AI生成/动作执行）
  - 自然语言配置：TG里直接说人话改配置
  - 群管：入群欢迎/敏感词/反刷屏/黑名单/流失打捞
- **可委托的Skills/智能体**：`backend-architect`、`build`
- **什么时候找它**：新增定时任务、修改群规则、调整关键词、优化问候文案、修复功能bug

---

### 📊 板块D：Dashboard网页后台
- **窗口广告词**："我是Bot的可视化指挥中心——数据看板、用户管理、群组统计、配置管理、运营报表，老板看数据都来找我"
- **涉及文件**：
  - `dashboard/app.py` — Flask网页后台（1400行完整前后端）
  - `start_dashboard.py` — 启动脚本
  - `start_dashboard.bat` — Windows启动壳
- **核心能力**：
  - 深色主题专业级UI（Tailwind CSS + Chart.js）
  - 登录认证（CSRF + 速率限制 + 频率限制）
  - 数据看板：用户趋势/时段分布/转化漏斗
  - 用户管理：搜索/排序/分页
  - 群组数据：入群/离群统计
  - 系统配置：查看/编辑 + 自然语言配置
  - 运营报表：CSV导出
  - 日志查看：搜索/筛选
  - VPS状态监控（SSH远程）
- **可委托的Skills/智能体**：`frontend-architect`、`ui-designer`、`ui-ux-pro-max`
- **什么时候找它**：页面样式调整、新增图表、API端点、前端交互优化、安全加固

---

### 🚀 板块E：部署与运维层
- **窗口广告词**："我是项目的后勤保障——一键部署、安全上传、VPS同步、版本管理、备份恢复、故障诊断，没有我项目上不了线"
- **涉及文件**：
  - `core/deploy_utils.py` — 安全部署工具库（核心！）
  - `core/vps_config.py` — VPS连接配置
  - `deploy_vps.py` — VPS一键部署脚本
  - `deploy.sh` / `deploy.bat` — 部署壳脚本
  - `一键部署.bat` — Windows部署入口
  - `sync_vps.py` — VPS同步工具
  - `scripts/` — 诊断工具集（debug_db/debug_vps/deep_check/find_bug/full_diagnosis等）
  - `Dockerfile` / `docker-compose.yml` — Docker部署
  - `start.sh` — VPS启停脚本
  - `requirements.txt` — 依赖清单
  - `.env.example` — 环境变量模板
  - `windows_helper.py` — Windows中文助手
- **核心能力**：
  - 安全合并配置（保护TOKEN/API_KEY等密钥）
  - 部署前自动拉回线上投喂内容
  - 部署前备份VPS配置
  - 先停旧进程再上传（防覆盖）
  - 部署后验证
  - 多诊断脚本快速定位问题
  - Docker一键部署
- **可委托的Skills/智能体**：`devops-architect`、`api-test-pro`
- **什么时候找它**：部署失败、VPS连接问题、版本同步、备份恢复、新增诊断脚本、Docker配置

---

### 🧪 板块F：测试与质量保障层
- **窗口广告词**："我是项目的质检员——代码审查、性能分析、安全审计、测试用例生成，我确保每个板块交付的东西都是靠谱的"
- **涉及文件**：
  - `scripts/` 下所有诊断脚本
  - 所有模块的测试用例（待完善）
  - `AI_ISSUE_TEMPLATE.md` — 问题报告模板
- **核心能力**：
  - 代码审查（zh-code-reviewer / code-reviewer）
  - 性能分析（perf-profiler）
  - 安全审计（security-audit）
  - 依赖审计（dep-auditor）
  - 测试用例生成（test-generator / unit-test-generator）
  - ESLint修复（eslint-fix）
  - 错误翻译（error-translator）
- **可委托的Skills/智能体**：`code-reviewer`、`zh-code-reviewer`、`security-audit`、`perf-profiler`、`test-generator`、`dep-auditor`
- **什么时候找它**：代码写完要审查、怀疑有性能问题、安全漏洞检查、需要写测试用例、依赖有漏洞

---

## 三、板块间的依赖关系与协作流

```
                    ┌──────────────┐
                    │   总指挥部    │
                    │  (本窗口)    │
                    └──────┬───────┘
                           │ 统筹/审核/发布
            ┌──────────────┼──────────────┐
            │              │              │
     ┌──────▼──────┐ ┌─────▼──────┐ ┌────▼──────┐
     │ A:AI引擎层  │ │ B:Bot核心层 │ │ D:Dashboard│
     └──────┬──────┘ └─────┬──────┘ └────┬──────┘
            │              │              │
            └──────┬───────┘              │
                   │                      │
            ┌──────▼──────┐               │
            │ C:功能模块层 │◄──────────────┘
            └──────┬──────┘
                   │
            ┌──────▼──────┐
            │ E:部署运维层 │
            └──────┬──────┘
                   │
            ┌──────▼──────┐
            │ F:质量保障层 │
            └─────────────┘
```

### 协作规则

1. **A→B**：AI引擎提供 `ai.ask()` 接口，Bot核心层调用它。AI引擎改了接口要通知B层。
2. **A→C**：AI引擎的mode决定功能模块用哪个人格。功能模块新增mode要更新AI引擎的prompt模板。
3. **B→C**：Bot核心层的消息分发链决定功能模块的调用顺序。功能模块不能跳过分发链直接拦截消息。
4. **D→B/C**：Dashboard的配置修改最终写入config.json，需要Bot重启后生效。自然语言配置直接调用C层的解析器。
5. **C→E**：功能模块改了代码，必须通过E层的部署工具上传VPS。
6. **F→所有**：质量保障层可以审查任何板块的代码，发现问题直接报告给总指挥部。

### 跨板块开发流程

```
老板提需求 → 总指挥部分析 → 分发给对应板块 → 板块开发 → 质量保障审查 → 总指挥部审核 → 部署运维上线
```

---

## 四、各窗口协同工作指南（小白专用）

### 你是零基础小白，这样用就行：

#### 场景1：Bot的早安问候文案不够好
→ 找 **板块C（功能模块层）** 开一个窗口，说：
"帮我优化auto_tasks.py里的早安问候文案，要更自然、更像真人"

#### 场景2：AI回复太慢或者经常报错
→ 找 **板块A（AI引擎层）** 开一个窗口，说：
"AI引擎经常超时，帮我排查模型池和路由配置，看看怎么优化"

#### 场景3：Dashboard页面想加个新图表
→ 找 **板块D（Dashboard网页后台）** 开一个窗口，说：
"帮我给Dashboard加一个用户活跃度热力图"

#### 场景4：部署到VPS出了问题
→ 找 **板块E（部署与运维层）** 开一个窗口，说：
"部署VPS失败了，帮我诊断并修复"

#### 场景5：写完代码怕有bug
→ 找 **板块F（质量保障层）** 开一个窗口，说：
"帮我审查一下刚改的代码，看看有没有问题"

#### 场景6：Bot收不到消息或者回复错乱
→ 找 **板块B（Bot核心与消息分发层）** 开一个窗口，说：
"Bot收不到群里的消息了，帮我排查分发链"

---

## 五、快照与病历保护机制

### 每次板块完成工作后，必须执行以下操作：

1. **更新项目快照**（project_snapshot.md）
   - 版本号 +1
   - 记录本次修改涉及的文件
   - 记录数据库表是否有变化
   - 记录配置字段是否有变化
   - 记录架构约束是否有变化

2. **更新病历本**（AI_DEBUG_HISTORY.md）
   - 如果有修bug，记录：问题/原因/修复方案/涉及文件
   - 如果有新增失败方案，记录到"失败方案避让表"
   - 如果有新增永久纪律，记录到"新增永久纪律"

3. **通知总指挥部**
   - 板块完成后，把修改摘要发给总指挥部
   - 总指挥部审核后更新 CHANGELOG.md 和 VERSION.md

### 关键文档清单（绝不能丢）
| 文件 | 内容 | 重要性 |
|------|------|--------|
| project_snapshot.md | 项目当前状态的完整快照 | 🔴 致命 |
| AI_DEBUG_HISTORY.md | 所有修过的bug和失败方案 | 🔴 致命 |
| .trae/rules/project_rules.md | 所有AI必须遵守的规则 | 🔴 致命 |
| core/deploy_utils.py | 安全部署工具库 | 🟡 重要 |
| config.json.example | 配置模板（不含密钥） | 🟡 重要 |
| .env.example | 环境变量模板 | 🟡 重要 |

---

## 六、可用Skills和智能体清单

### 已安装的Skills（按需调用）
| Skill名称 | 用途 | 推荐板块 |
|-----------|------|----------|
| build | 业务需求落地，防退化开发 | B、C |
| code-reviewer | 代码审查 | F |
| zh-code-reviewer | 中文代码审查 | F |
| zh-docgen | 中文文档生成 | 所有 |
| zh-readme | README生成 | E |
| security-audit | 安全审计 | F、E |
| test-generator | 测试用例生成 | F |
| unit-test-generator | 单元测试生成 | F |
| perf-profiler | 性能分析 | F、A |
| dep-auditor | 依赖安全审计 | F |
| error-translator | 错误消息翻译 | 所有 |
| eslint-fix | ESLint修复 | F |
| refactor-advisor | 重构建议 | A、B、C |
| requirements-analyst | 需求拆分 | 总指挥部 |
| plan | MVP蓝图规划 | 总指挥部 |
| init | 项目初始化 | 总指挥部 |
| pack | 打包交付 | E |
| git-commit | Git提交规范 | E |
| git-workflow | Git工作流 | E |
| changelog-gen | Changelog生成 | E |
| brainstorming | 需求梳理 | 总指挥部 |
| data-visual-pro | 数据可视化 | D |
| chart-visualization | 图表生成 | D |
| ui-ux-pro-max | UI/UX设计 | D |
| frontend-design | 前端设计 | D |

### 可用的智能体（通过Task工具调用）
| 智能体 | 用途 | 推荐场景 |
|--------|------|----------|
| backend-architect | 后端架构设计 | A、B、C |
| frontend-architect | 前端开发 | D |
| devops-architect | DevOps/部署 | E |
| ai-integration-engineer | AI集成 | A |
| performance-expert | 性能优化 | F、A |
| api-test-pro | API测试 | F |
| ui-designer | UI设计 | D |

---

## 七、各板块的独立开发规则

### 通用规则（所有板块必须遵守）

1. **动手前先读快照和病历**：每次开发前必须读 `project_snapshot.md` 和 `AI_DEBUG_HISTORY.md`
2. **最小修改原则**：只改必须改的行，不顺手调整格式或无关逻辑
3. **风格一致**：严格匹配现有代码风格
4. **不碰密钥**：config.json中的TOKEN/API_KEY等字段，只能通过deploy_utils.py修改
5. **提交前审查**：代码写完必须让质量保障层审查
6. **完成必更新**：跑通后立即更新快照和病历

### 各板块特殊规则

**板块A（AI引擎）**：
- 修改MODEL_POOLS/MODE_ROUTING必须同步更新config.json
- 新增模型必须通过API实测可用性
- 不要随便改模型名，有日期后缀是正常的

**板块B（Bot核心）**：
- 不要改消息分发优先级链（P0~P10），除非老板明确要求
- 数据库操作必须加锁，禁止裸SQL
- 新增中间件必须考虑线程安全

**板块C（功能模块）**：
- 新增定时任务必须加防重复机制（_can_run + _mark_done）
- 新增admin指令必须检查管理员权限
- 关键词触发规则优先走配置，不要硬编码

**板块D（Dashboard）**：
- API端点必须加login_required装饰器
- POST请求必须加CSRF校验
- 密码等敏感字段不能在日志中输出

**板块E（部署运维）**：
- 上传config.json只能用safe_upload_config()
- 部署顺序：备份→停旧→上传→启新→验证
- 不要删除带日期后缀的模型名

**板块F（质量保障）**：
- 审查时必须参考病历本中的失败方案避让表
- 性能测试要考虑VPS实际配置
- 安全审计重点关注密钥泄露和SQL注入

---

## 八、版本管理与发布流程

### 版本号规则
- 当前版本：v4.5.16
- 格式：主版本.次版本.修订号
- 修订号 +1：每次板块完成并审核后

### 发布流程
1. 板块完成开发
2. 质量保障层审查通过
3. 总指挥部审核通过
4. 更新 project_snapshot.md（版本号+1）
5. 更新 AI_DEBUG_HISTORY.md（记录变更）
6. 更新 VERSION.md 和 CHANGELOG.md
7. 通过板块E部署到VPS
8. 验证VPS运行正常

---

## 九、老板操作手册（零基础版）

### 日常维护
1. 有什么新想法或问题，先来找**总指挥部**（这个窗口）
2. 我会帮你分析需求，然后告诉你去找哪个板块
3. 板块完成后，我会帮你审核和上线

### 紧急故障
1. Bot不回复消息 → 找板块B
2. AI报错或返回空 → 找板块A
3. 部署失败 → 找板块E
4. 页面打不开 → 找板块D

### 重要提醒
- ❌ 不要直接修改VPS上的config.json
- ❌ 不要把密钥发到任何地方
- ❌ 不要同时开多个窗口改同一个文件
- ✅ 每次开发前告诉我是做什么的
- ✅ 改完后告诉我帮你审核上线

---

*本文件由总指挥部维护，每次项目重大变更后自动更新*
*最后更新：2026-05-01*
