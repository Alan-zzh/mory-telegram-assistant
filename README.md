# Mory小助理 · Telegram群管机器人

## 项目简介

Mory小助理是一个功能强大的Telegram群管机器人，集成了AI对话、定时任务、内容管理、数据监控等多种功能。

### 核心功能

- **AI对话** - 基于通义千问等多模型的智能对话，三层智能路由（轻量/标准/旗舰）
- **定时任务** - 早安/午安/晚安问候、新闻播报（TTS语音）、塔罗搭讪、TrendRadar播报
- **广告拦截** - 三级检测：入群封禁+内容评分+延迟封禁，零Token消耗
- **阅后即焚** - 中间件拦截回复消息，自动追踪并清理
- **群管功能** - 敏感词检测、禁言管理、入群欢迎、刷屏检测、黑名单
- **优化引擎** - 语义缓存 + 熔断器 + 令牌桶限流 + Token统计
- **Dashboard** - Flask网页后台，群组数据/日志查看/配置管理/自然语言配置

## 快速开始

### VPS 部署（推荐）

```bash
# 一键部署（本地执行，自动上传+重启）
python deploy_vps.py
```

### Windows 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env

# 启动
python main.py
```

## 配置说明

### 环境变量（.env）

| 变量 | 用途 | 必填 |
|------|------|------|
| TG_TOKEN | Telegram Bot Token | 是 |
| DASHSCOPE_KEY | 通义千问 API Key | 是 |
| DASHBOARD_SECRET | Dashboard 密钥（至少16位） | 是 |
| DASHBOARD_PASSWORD | Dashboard 登录密码（至少6位） | 是 |
| VPS_HOST | VPS IP 地址 | 部署时需要 |
| VPS_SSH_PASS | VPS SSH 密码 | 部署时需要 |
| VPS_PORT | SSH 端口（默认22） | 否 |
| VPS_PATH | VPS 项目路径（默认/home/ubuntu/mory_assistant） | 否 |

### 主配置（config.json）

- 模型池配置（MODEL_POOLS）- 三层路由映射（MODE_ROUTING）
- AI 人设（SYSTEM_PROMPT）
- 管理员列表、功能开关等

## 项目结构

```
mory_assistant/
├── main.py                     # 主入口（消息分发+中间件注册）
├── version.py                  # 版本号统一管理
├── deploy_vps.py               # VPS一键部署脚本
├── sync_vps.py                 # VPS同步脚本
├── windows_helper.py           # Windows辅助工具
├── start_dashboard.py          # Dashboard启动入口
├── config.json                 # 运行时配置（不提交Git）
├── config.json.example         # 配置模板
├── .env                        # 环境变量（不提交Git）
├── .env.example                # 环境变量模板
├── .gitignore                  # Git忽略规则
├── requirements.txt            # Python依赖
├── Dockerfile                  # Docker镜像构建
├── docker-compose.yml          # Docker Compose编排
├── deploy.bat                  # Windows部署脚本
├── deploy.sh                   # Linux部署脚本
├── docker_deploy.sh            # Docker部署脚本
├── 一键部署.bat                 # Windows一键部署
├── start_dashboard.bat         # Windows启动Dashboard
├── start.sh                    # Linux启动脚本（VPS端，已由systemd替代）
├── mory.db                     # SQLite数据库（运行时生成）
├── mory.log                    # 运行日志（运行时生成）
├── core/                       # 核心模块
│   ├── __init__.py
│   ├── ai_engine.py            # AI引擎（三层路由+多模型轮换+TTS语音）
│   ├── trendradar_news.py      # TrendRadar新闻获取
│   ├── database.py             # SQLite数据层（14张表+线程安全）
│   ├── logging_util.py         # 日志工具（按大小轮转+错误分级）
│   ├── mory_bot.py             # Bot封装类（中间件+消息路由）
│   ├── optimizer.py            # 运营优化器（语义缓存+熔断+限流）
│   ├── resource_manager.py     # 资源管理（图片/语音池+线程锁）
│   ├── deploy_utils.py         # 安全部署工具库
│   ├── monitoring.py           # 系统监控
│   ├── token_statistics.py     # Token统计
│   ├── telegram_stats.py       # Telegram统计
│   ├── migrate.py              # 数据库迁移工具
│   └── vps_config.py           # VPS连接配置
├── modules/                    # 功能模块
│   ├── __init__.py
│   ├── admin_cmds.py           # 管理员指令
│   ├── ad_detector.py          # 广告检测引擎（三级检测+延迟封禁）
│   ├── ad_patterns_encoded.py  # 编码后的广告关键词
│   ├── auto_tasks.py           # 定时任务（原子抢占防重复）
│   ├── avatar_detector.py      # 色情头像检测
│   ├── content.py              # 内容处理（图片打码+频道转发+勋章）
│   ├── group_mgr.py            # 群管理（敏感词/禁言/黑名单）
│   ├── keyword_trigger.py      # 关键词触发
│   ├── natural_cmd.py          # 自然语言指令
│   └── optimizer_admin.py      # 运营管理指令
├── dashboard/                  # 网页后台
│   └── app.py                  # Flask控制台
├── universal_ai_router/        # 通用AI路由模块（Token统计依赖）
│   ├── main.py                 # 路由主入口
│   ├── setup.py                # 安装配置
│   ├── config/
│   │   └── router_config.json  # 路由配置
│   ├── core/                   # 路由核心（8个py文件）
│   └── data/
│       └── account_states.json # 账号状态数据
├── scripts/                    # 调试和诊断工具
│   ├── debug_db.py             # 数据库调试
│   ├── debug_vps.py            # VPS调试
│   ├── deep_check.py           # 深度检查
│   ├── find_bug.py             # Bug定位
│   ├── full_diagnosis.py       # 全量诊断
│   ├── get_keyword_module.py   # 关键词模块获取
│   ├── restore_after_reinstall.py  # 重装后恢复
│   ├── test_connection.py      # 连接测试
│   ├── test_vps_ai.py          # VPS AI测试
│   └── README.md               # 调试工具说明
├── data/                       # 数据目录
│   └── router_usage.db         # 路由使用统计数据库
├── project_snapshot.md         # 项目快照
├── AI_DEBUG_HISTORY.md         # 调试病历本
├── BOT_投喂与自然语言配置说明.md  # 投喂与自然语言配置说明
├── CHANGELOG.md                # 变更日志
└── VERSION.md                  # 版本号
```

## VPS 服务管理（systemd）

| 命令 | 说明 |
|------|------|
| `sudo systemctl start mory-assistant` | 启动 |
| `sudo systemctl stop mory-assistant` | 停止 |
| `sudo systemctl restart mory-assistant` | 重启 |
| `sudo systemctl status mory-assistant` | 查看状态 |
| `journalctl -u mory-assistant -n 100 --no-pager` | 查看日志 |

⚠️ 禁止使用 `start.sh` 或手动 `python main.py` 启动，会与 systemd 冲突导致 409 错误。

## 技术栈

- **后端**: Python 3.12+
- **Telegram API**: pyTelegramBotAPI
- **数据库**: SQLite (WAL模式，14张表)
- **Web后台**: Flask
- **定时任务**: APScheduler
- **进程管理**: systemd
- **AI模型**: 通义千问（三层路由+多模型轮换）

## 文档

| 文档 | 说明 |
|------|------|
| [project_snapshot.md](project_snapshot.md) | 项目快照（版本/架构/数据结构） |
| [AI_DEBUG_HISTORY.md](AI_DEBUG_HISTORY.md) | 调试病历本（Bug修复记录/失败方案避让） |
| [BOT_投喂与自然语言配置说明.md](BOT_投喂与自然语言配置说明.md) | Telegram/网页端投喂、自然语言改配置说明 |
| [scripts/README.md](scripts/README.md) | 调试工具说明 |

## 安全注意事项

- `.env` 和 `config.json` 包含敏感信息，已加入 `.gitignore`，不提交到版本控制
- 部署时使用 `safe_upload_config()` 安全上传，不会覆盖VPS密钥
- Dashboard 密码至少6位，Secret Key 至少16位
- 所有SQL使用参数化查询，禁止f-string拼接
- 密码校验使用 `hmac.compare_digest()`

## 版本升级

1. **本地修改代码**
2. **一键部署**：`python deploy_vps.py`（自动：stop → 上传 → start → 验证）
3. **手动重启**：`sudo systemctl restart mory-assistant`
4. **查看日志**：`journalctl -u mory-assistant -n 100 --no-pager`
