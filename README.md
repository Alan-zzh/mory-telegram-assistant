<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# Mory小助理

Telegram 群组助手机器人：人设对话、广告检测、群管、积分商城、转化漏斗、传统文化栏目、运营 Dashboard。单机 VPS（systemd）部署。

当前版本 **v5.38.52**：普通用户私聊 `/start` 使用随机欢迎卡；群聊精确 @ 小助理时，纯点名返回无销售按钮的随机图片卡，带问题则直接进入问题处理链。

## 快速开始

### 环境
- Python 3.12+；唯一依赖锁为 `requirements.lock`；虚拟环境 `.venv/`。
- 敏感凭据仅在 `.env`（`TG_TOKEN` / `DASHSCOPE_KEY` / `DASHBOARD_SECRET` / `DASHBOARD_PASSWORD` 等），绝不入库。

### 本地运行
```bash
pip install -r requirements.lock
cp .env.example .env   # 填入真实凭据
python main.py
```

### 部署（仅 VPS，systemd 唯一）
```bash
sudo systemctl restart mory-assistant     # 主进程
sudo systemctl restart mory-dashboard     # Dashboard，端口 6616
python deploy_vps.py                       # stop→上传→start→验证（safe_upload_config 保护密钥）
```
部署后验证：`systemctl status` 双 active + `curl localhost:6616/api/health`。
项目默认把生产部署纳入更新/修复闭环：本地门禁通过并提交可信 Git commit 后直接增量部署；仅限本地、无运行态影响或安全门禁阻断时跳过。完整约束以 `AGENTS.md` 为准。

## 本地启动故障排查

### 虚拟环境损坏
- 现象：`.venv/Scripts/python.exe` 缺失，或启动报 `ModuleNotFoundError` / 解释器路径异常。
- 处理：删除 `.venv` 后用 `python -m venv .venv` 重建，再 `.venv\Scripts\activate`，最后 `pip install -r requirements.lock`。

### 依赖安装失败
- 优先 `pip install -r requirements.lock`（锁定版本，与生产一致）。
- 锁文件安装失败时回退 `pip install -r requirements.txt`，并记录差异以便后续修复 lock。

### Telegram Bot Token 未设置
- 复制 `.env.example` 为 `.env`，填写 `TG_TOKEN`（从 [@BotFather](https://t.me/BotFather) 获取）。
- 缺少 `TG_TOKEN` 时 preflight 启动检查会阻断启动并打印告警。

### Dashboard 无法访问
- 检查环境变量 `DASHBOARD_SECRET`（至少 16 位）与 `DASHBOARD_PASSWORD` 是否已设置。
- 默认端口 6616，本地验证：`curl localhost:6616/api/health`。

### 数据库初始化
- 首次运行自动建表（`mory.db`），无需手动迁移。
- 如需重置可删除 `mory.db`（⚠️ 会丢失全部数据，谨慎操作）；生产环境请改用 `migrations/` 下的 Alembic 迁移。

## 管理员命令清单

⚠️ 以下命令仅 `ADMIN_ID` / `ADMIN_IDS` 配置的管理员可用；普通用户触发会被忽略或拒绝。

### 用户入口（所有人可用）

| 命令 | 参数 | 用途 |
| --- | --- | --- |
| `/start` | — | 新用户引导：普通用户私聊返回随机姓名日期欢迎卡与双入口；管理员私聊返回群管理清单；群聊返回简短引导 |
| `/help` | — | 帮助命令：私聊返回用户命令清单，管理员额外附带管理员清单；群聊主动私聊完整帮助 |

### 广告 / 封禁

| 命令 | 参数 | 用途 |
| --- | --- | --- |
| `/scan_ads` | `[start_id] [end_id]` | 追溯扫描广告（可选范围，缺省取近 N 条） |
| `/scan_status` | — | 查询最近一次 `/scan_ads` 扫描进度与结果 |
| `/unban` · `解封` | `@user` 或 `<uid>` | 解除广告封禁 |
| `/fban` | `@user [reason]` | 联邦封禁（跨群生效） |
| `/unfban` | `@user` | 解除联邦封禁 |
| `/feds` | — | 查询联邦封禁列表 |

### 认证 / 标签

| 命令 | 参数 | 用途 |
| --- | --- | --- |
| `/certify` | `@user` 或 `<uid>` | 认证用户 |
| `/uncertify` | `@user` 或 `<uid>` | 取消认证 |
| `标签` | `@user <tag>` | 给用户打标签（自然语言） |
| `备注` | `@user <note>` | 给用户加备注（自然语言） |
| `查看标签` | `@user` | 查看用户标签（自然语言） |

### 群欢迎 / 规则

| 命令 | 参数 | 用途 |
| --- | --- | --- |
| `/setwelcome` | `<text>` | 设置欢迎语 |
| `/setgoodbye` | `<text>` | 设置离别语 |
| `/setrules` | `<text>` | 设置群规 |
| `/cleanwelcome` | — | 清除欢迎语 |
| `/getwelcome` | — | 查看当前欢迎语 |

### 设置面板 / 业务模块

| 命令 | 参数 | 用途 |
| --- | --- | --- |
| `/settings` | — | 打开设置面板（按钮交互） |
| `/sales` | — | 销售中心 |
| `/security` | — | 安全中心 |
| `/managed` | — | 多群托管 |
| `/content_audit` | — | 内容审核 |
| `/analytics` | — | 新成员分析 |
| `/membership` | — | 会员管理 |

### 优惠券

| 命令 | 参数 | 用途 |
| --- | --- | --- |
| `生成优惠券` | `<args>` | 生成优惠券（自然语言） |
| `领券` | `<code>` | 领取优惠券 |
| `核券` | `<code>` | 核销优惠券 |

> 普通用户命令见 `/help`；管理员在私聊触发 `/help` 会额外附带上述清单。

## 目录结构
- `core/`：消息分发、AI 引擎、模型路由、数据库、配置、handler（81 个业务 `.py`）。
- `modules/`：137 个业务模块（广告检测、群管、积分、转化、播报、定时任务、销售/安全/多群托管/会员等默认关闭能力）。
- `dashboard/`：运营后台（`app` + `api`，163 路由，含人工审核风格样本 API）。
- `tasks/`：后台定时任务（`task_scheduler.py` 自动发现 BaseTask 子类；`auto_tasks.py` 为 legacy）。
- `scripts/`：工具脚本（含 `doc_consistency.py` 自检与默认只报告的 `scan_group.py` 全量成员扫描）。
- `tests/`：单元测试。
- `docs/`：技术(`technical`)、计划(`plans`)、愿景(`vision`)、归档(`archive`)。
- `migrations/`：Alembic 数据库迁移。
- `runtime/audit-reports/`：审计报告与完工报告。
- `config/`：systemd 服务文件。

## 客观指标（2026-08-09 实测，`scripts/doc_consistency.py` 全过）
modules 业务 `.py` = 137，core 业务 `.py` = 81，`_job_` = 33，DB 表 = 173，Dashboard 路由 = 163，消息分发函数 = 9，model_router 映射 = 10。
一致性由 `scripts/doc_consistency.py` 断言（`project_snapshot.md` 的 `METRICS` 块为基准）。

## 播报图片卡（PIL 图片卡）
全播报类型统一走图片卡视觉输出，失败自动回退 Rich Message / HTML，不丢内容。

**生产启用类型**（3 类）：黄历（09:05）、塔罗（13:05）、易经（20:35）。泛问候与四档定点播报默认关闭，避免同一时段重复主动触达；新闻执行链已删除。

**统一视觉**：Mory 品牌配色（墨绿+金+朱砂）、右上角日期标签、`Mory / 沫沫的沫` 右下角红章、底部渐变 CTA 按钮视觉。

**关键开关**（三处同步：`config.json.example` + 代码 `.get()` + Dashboard 面板）：
- `BROADCAST_IMAGE_CARD_ENABLED`：总开关（默认 False，生产已开启）
- 分类型子开关（嵌套在各自 CONFIG 里，非独立顶层键）：
  - `MYSTIC_BROADCAST_CONFIG.image_card_enabled`：黄历/塔罗/易经共用一个开关
  - `GREETING_CONFIG.image_card_enabled`：问候播报（生产关闭）
  - `SCHEDULED_BROADCASTS[].image_card_enabled`：每个定点播报单独配（生产全关）
- `BROADCAST_THEME_ENABLED`：主题色开关
- `BUTTON_STYLE_ENABLED`：Inline Keyboard 彩色按钮样式
- `RICH_MESSAGE_STYLE`：回退链路样式

**回退链路**（三层，任一失败自动降级）：图片卡 → Rich Message → 纯 HTML/Markdown。

**字体兜底**（v5.38.15+）：Windows 走微软雅黑/宋体 → Linux 走 Noto CJK → 仓库自带 `assets/fonts/LXGWWenKai-Regular.ttf`，避免 VPS 汉字变方块。

**CTA 强绑定**（v5.38.16+）：图片按钮文案由真实 InlineKeyboard 文案经 `strip_visual_emoji()` 派生，杜绝两处硬编码不一致。

**性能**：`font()` LRU(128) 缓存；临时 `Image` 用完 `close()`；单区块异常隔离（一个区块报错不崩整张卡）。

## 六大文档索引
- `AGENTS.md`：项目规则唯一入口（铁律 / 流程 / 约定 / 文档路由表）。
- `README.md`：本文件。
- `VERSION.md`：当前版本号与升版规则。
- `CHANGELOG.md`：用户可感知变更（一行一条）。
- `project_snapshot.md`：当前真实状态快照（覆盖式）。
- `AI_DEBUG_HISTORY.md`：反复暗病病历（问题 | 根因 | 解法 | 预防）。

## 常见问题
- **文档数字以哪为准？** 以 `project_snapshot.md` 的 `METRICS` 块 + `scripts/doc_consistency.py` 校验为准；README 中的数字与其一致。
- **改了配置为何不生效？** 配置三处同步：`config.json.example` + 代码 `.get()` 默认值 + Dashboard 面板；改后需重启对应 systemd 服务。
- **新增数据库表 / Repo 方法？** 必须同步 Alembic migration 与 `core/database.py` 的 `_REPO_METHOD_MAP` / `_REPO_ATTR_MAP` 注册，否则启动失败；部署前跑 `python scripts/verify_db_methods.py`。
- **密钥泄露怎么办？** 立即在 `.env` 与对应平台更换，旧密钥视为失效；本项目密钥均已 gitignore，勿提交。
