# 🤖 Mory小助理 · Telegram群管机器人

## 📁 项目结构

```
mory小助理/
├── main.py              # 机器人主入口
├── config.json           # 配置文件（Token、管理员ID等）
├── requirements.txt      # Python依赖
├── start.sh              # VPS启动脚本
├── 一键部署.bat          # Windows一键部署
├── core/                 # 核心模块
│   ├── ai_engine.py      # AI对话引擎
│   ├── database.py       # 数据库操作
│   ├── mory_bot.py       # 机器人封装
│   └── ...
├── modules/              # 功能模块
│   ├── auto_tasks.py     # 定时任务（阅后即焚等）
│   ├── content.py        # 内容处理
│   └── ...
└── dashboard/            # 网页后台
    └── app.py            # Flask控制台
```

## 🚀 快速开始

### VPS部署
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置
cp config.example.json config.json
# 编辑 config.json 填入你的 BOT_TOKEN 和 ADMIN_ID

# 3. 启动
bash start.sh start
```

### 查看日志
```bash
bash start.sh log
```

### VPS管理
```bash
bash start.sh status   # 查看状态
bash start.sh restart  # 重启
bash start.sh stop     # 停止
```

## ⚙️ 配置说明

编辑 `config.json`：
```json
{
  "BOT_TOKEN": "你的TelegramBotToken",
  "ADMIN_ID": 你的用户ID,
  ...
}
```

## 📝 文档

- `CHANGELOG.md` - 更新日志
- `AI_DEBUG_HISTORY.md` - 技术调试手册

## 🔧 技术栈

- Python 3
- pyTelegramBotAPI
- SQLite (WAL模式)
- Flask (Dashboard)
