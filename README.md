# Mory小助理 · Telegram群管机器人

## 项目简介

Mory小助理是一个功能强大的Telegram群管机器人，集成了AI对话、定时任务、内容管理、数据监控等多种功能。

### 核心功能

- **AI对话** - 基于通义千问等多模型的智能对话，三层智能路由（轻量/标准/旗舰）
- **定时任务** - 早安/午安/晚安问候、新闻播报（TTS语音）、塔罗搭讪、醋意挽回、购物车挽回
- **阅后即焚** - 中间件拦截回复消息，自动追踪并清理
- **群管功能** - 敏感词检测、禁言管理、入群欢迎、刷屏检测、黑名单
- **优化引擎** - 语义缓存 + 熔断器 + 令牌桶限流 + Token统计
- **Dashboard** - Flask网页后台，群组数据/日志查看/配置管理/自然语言配置

## 快速开始

### 方法一：Linux VPS 部署（推荐）

```bash
# 1. 安装依赖
bash deploy.sh install

# 2. 配置环境变量
# 编辑 .env 文件，填写 TG_TOKEN、API_KEY、DASHBOARD_PASSWORD 等

# 3. 启动
bash start.sh start

# 4. 设置开机自启
bash deploy.sh autostart
```

### 方法二：Windows 本地部署

```bash
# 1. 安装依赖
deploy.bat install

# 2. 配置环境变量
# 编辑 .env 文件

# 3. 启动
python main.py
```

### 方法三：Docker 部署

```bash
# 1. 准备配置文件
cp .env.example .env

# 2. 启动容器
docker-compose up -d
```

### 方法四：VPS 一键部署

```bash
python deploy_vps.py
```

## 配置说明

### 环境变量（.env）

| 变量 | 用途 | 必填 |
|------|------|------|
| TG_TOKEN | Telegram Bot Token | 是 |
| API_KEY | 通义千问 API Key | 是 |
| DASHBOARD_SECRET | Dashboard 密钥（至少16位） | 是 |
| DASHBOARD_PASSWORD | Dashboard 登录密码（至少6位） | 是 |
| VPS_HOST | VPS IP 地址 | 部署时需要 |
| VPS_SSH_PASS | VPS SSH 密码 | 部署时需要 |
| VPS_PORT | SSH 端口（默认22） | 否 |
| VPS_PATH | VPS 项目路径（默认/root/mory） | 否 |

### 主配置（config.json）

- 模型池配置（MODEL_POOLS）
- 三层路由映射（MODE_ROUTING）
- AI 人设（SYSTEM_PROMPT）
- 管理员列表、功能开关等

## 项目结构

```
mory_assistant/
├── main.py                 # 主入口（消息分发+中间件注册）
├── config.json             # 运行时配置
├── .env                    # 环境变量（不提交Git）
├── .env.example            # 环境变量模板
├── requirements.txt        # Python 依赖
├── version.py              # 版本号统一管理
├── core/                   # 核心模块
│   ├── ai_engine.py        # AI引擎（三层路由+多模型轮换+TTS语音）
│   ├── trendradar_news.py  # TrendRadar新闻获取
│   ├── database.py         # SQLite数据层（13张表+线程安全）
│   ├── logging_util.py     # 日志工具（按大小轮转+错误分级）
│   ├── mory_bot.py         # Bot封装类（中间件+消息路由）
│   ├── optimizer.py        # 运营优化器（语义缓存+熔断+限流）
│   ├── resource_manager.py # 资源管理（图片/语音池+线程锁）
│   ├── monitoring.py       # 系统监控
│   ├── token_statistics.py # Token统计
│   └── vps_config.py       # VPS连接配置
├── modules/                # 功能模块
│   ├── admin_cmds.py       # 管理员指令
│   ├── auto_tasks.py       # 定时任务
│   ├── content.py          # 内容处理（图片打码+频道转发+勋章）
│   ├── group_mgr.py        # 群管理（敏感词/禁言/黑名单）
│   ├── keyword_trigger.py  # 关键词触发
│   ├── natural_cmd.py      # 自然语言指令
│   └── optimizer_admin.py  # 运营管理指令
├── dashboard/              # 网页后台
│   └── app.py              # Flask控制台
├── universal_ai_router/    # 通用AI路由模块
├── scripts/                # 调试和诊断工具
│   └── README.md           # 工具说明
├── backups/                # 自动备份
├── logs/                   # 日志文件
├── project_snapshot.md     # 项目快照
├── AI_DEBUG_HISTORY.md     # 调试病历本
└── 部署相关文件             # start.sh / deploy.sh / Dockerfile 等
```

## 常用命令

### Linux 服务器管理

| 命令 | 说明 |
|------|------|
| `bash start.sh start` | 启动 |
| `bash start.sh stop` | 停止 |
| `bash start.sh restart` | 重启 |
| `bash start.sh status` | 查看状态 |
| `bash start.sh log` | 查看日志 |
| `bash start.sh update` | 热更新 |
| `bash start.sh restore` | 恢复备份 |

### Docker 管理

| 命令 | 说明 |
|------|------|
| `docker-compose up -d` | 启动 |
| `docker-compose down` | 停止 |
| `docker-compose logs -f` | 查看日志 |
| `docker-compose restart` | 重启 |

## 技术栈

- **后端**: Python 3.8+
- **Telegram API**: pyTelegramBotAPI
- **数据库**: SQLite (WAL模式，13张表)
- **Web后台**: Flask
- **定时任务**: APScheduler
- **容器化**: Docker
- **AI模型**: 通义千问（多模型轮换）

## 文档

| 文档 | 说明 |
|------|------|
| [project_snapshot.md](project_snapshot.md) | 项目快照（版本/架构/数据结构） |
| [AI_DEBUG_HISTORY.md](AI_DEBUG_HISTORY.md) | 调试病历本（Bug修复记录/失败方案避让） |
| [BOT_投喂与自然语言配置说明.md](BOT_投喂与自然语言配置说明.md) | Telegram/网页端投喂、自然语言改配置、特定词自动回复说明 |
| [scripts/README.md](scripts/README.md) | 调试工具说明 |

## 安全注意事项

- `.env` 和 `config.json` 包含敏感信息，已加入 `.gitignore`，不提交到版本控制
- 部署时使用 `safe_upload_config()` 安全上传，不会覆盖VPS密钥
- Dashboard 密码至少6位，Secret Key 至少16位
- 所有SQL使用参数化查询，禁止f-string拼接
- 密码校验使用 `hmac.compare_digest()`

## 版本升级

1. **备份数据**：`bash start.sh backup`
2. **更新代码**：`python deploy_vps.py` 或 git pull
3. **更新依赖**：`bash deploy.sh install`
4. **重启服务**：`bash start.sh restart`

---

Mory小助理 - 让你的Telegram群组更智能、更活跃！
