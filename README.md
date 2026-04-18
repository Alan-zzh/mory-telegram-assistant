# 🤖 Mory小助理 · Telegram群管机器人

> **快速入口**：查看 docs/README.md 了解完整项目说明
> **技术调试**：查看 AI_DEBUG_HISTORY.md 了解技术细节

---

## 📁 文档结构

```
根目录（核心文档）
├── CHANGELOG.md          ← 更新日志（必读）
├── AI_DEBUG_HISTORY.md   ← 技术调试手册（必读）
└── docs/                 ← 归档文档
    ├── README.md         ← 项目说明
    ├── CHANGELOG.md      ← 完整更新历史
    └── ...
```

---

## 🚀 快速开始

### 部署到VPS
```bash
python vps_deploy.py
# 或
.\vps_one_click_update.bat update
```

### 检查Bot状态
```bash
ssh root@43.159.168.175
# 密码: 066Sh9$YhG#Let

ps aux | grep main.py | grep -v grep
tail -100 /root/mory/mory.log
```

### 重启Bot
```bash
cd /root/mory
pkill -9 -f 'main.py'
nohup python3 main.py > bot.log 2>&1 &
```

---

## ⚠️ 重要提醒

1. **修改database.py后要转LF行尾** - Windows默认CRLF会导致SQL错误
2. **Bot无法访问群历史消息** - 需手动删除历史消息
3. **reply_tracking表为空是正常的** - 只有Bot回复群消息才会创建记录

---

*更多信息请查看 docs/README.md*
