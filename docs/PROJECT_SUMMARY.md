# Mory小助理 - 项目目录结构总结

## 目录清理完成 ✅

### 清理日期
2026年4月16日 05:40

### 已执行操作
1. **一键更新VPS工具已创建**：
   - `vps_one_click_update.bat` - 支持三种模式
     - `update` - 快速更新（仅上传修改文件）
     - `full` - 完整部署（停止进程+全量上传）
     - `status` - 状态检查
   - `一键部署.bat` - 更新使用最新的`deploy_final.py`

2. **冗余文件已清理**：
   - 删除7个重复的部署脚本
   - 删除2个重复的批处理文件
   - 所有文件已备份到`backup_deploy/`目录

3. **WorkBuddy工作区已清理**：
   - 21个测试文件已备份到`test_backup/`
   - 工作区保持整洁

### 当前项目结构
```
C:/Users/Administrator/Desktop/mory小助理/
├── 📄 一键部署.bat               # 完整部署到VPS
├── 📄 vps_one_click_update.bat   # 一键更新工具（update/full/status）
├── 📄 backup_vps_data.bat        # 手动备份VPS数据
├── 📄 restore_from_backup.bat    # 从备份恢复VPS数据
├── 🐍 main.py                   # 主程序 v21.43
├── ⚙️ config.json               # 配置文件
├── 📋 start.sh                  # 启动脚本
├── 📖 CHANGELOG.md              # 更新日志
├── 📖 AI_DEBUG_HISTORY.md      # 调试病历本
├── 📖 TECH_BUGFIX_GUIDE.md     # Bug修复指南（根因+方案）
├── 📚 README.md                 # 说明文档
├── 📦 requirements.txt          # 依赖列表
├── 🚀 deploy_final.py           # 完整部署脚本（含自动备份）
├── ⚡ vps_deploy.py             # 快速更新脚本（含自动备份）
├── 📊 vps_status_check.py       # VPS状态检查
├── ⛔ kill_bot.py               # 进程终止工具
├── ✅ final_checklist.md        # 最终确认清单
├── 📋 backup_design.md          # 备份方案设计文档
├── 📋 BACKUP_COMPARISON.md      # 备份方案对比
├── 🐍 telegram_backup_bot.py    # Telegram私聊备份示例
├── 🐍 check_db.py               # 数据库检查工具
├── 💾 mory.db                   # 数据库文件
├── 📁 scripts/                  # 备份恢复脚本
│   ├── vps_backup.py            # 完整备份脚本
│   └── vps_restore.py           # 恢复脚本
├── 📁 backups/                  # 自动备份目录
│   ├── 20260416_xxxxxx/         # 时间戳备份目录
│   ├── latest/ -> 20260416_xxxxxx
│   └── backup_list.txt
├── 📁 backup_deploy/            # 冗余文件备份目录
├── 📁 core/                     # 核心模块
│   ├── 🧠 ai_engine.py
│   ├── 🗃️ database.py
│   └── __init__.py
└── 📁 modules/                  # 功能模块
    ├── 👑 admin_cmds.py
    ├── 🔄 auto_tasks.py
    ├── 📝 content.py
    ├── 👥 group_mgr.py
    └── __init__.py
```

### 部署与更新
1. **快速更新**：双击 `vps_one_click_update.bat` 输入 `update`
   - 仅上传修改文件
   - 自动备份VPS数据到本地
   - 热重启bot
2. **完整部署**：双击 `vps_one_click_update.bat` 输入 `full`
   - 停止进程+全量上传+重启
   - 自动备份VPS数据到本地
3. **状态检查**：双击 `vps_one_click_update.bat` 输入 `status`
   - 查看VPS运行状态
   - 检查版本信息
4. **传统部署**：双击 `一键部署.bat`

### 数据备份与恢复
1. **手动备份**：双击 `backup_vps_data.bat`
   - 完整备份VPS数据到本地
2. **手动恢复**：双击 `restore_from_backup.bat`
   - 从本地备份恢复到VPS
   - 恢复前自动创建备份
3. **自动备份**：每次更新时自动执行
   - 备份保存在 `backups/` 目录
   - 保留最近7天备份

### VPS信息
- **IP**：43.159.168.175（腾讯云硅谷）
- **用户**：root
- **路径**：/root/mory
- **部署方式**：SSH + paramiko

### 版本管理规则
- **版本号同步**：修改`main.py`版本号时，同步更新：
  1. `config.json`中的`_CONFIG_VERSION`
  2. `start.sh`中的版本注释
  3. `CHANGELOG.md`记录变更
- **文件同步规则**：每次更新必须同步5个核心文件
  1. main.py
  2. config.json
  3. start.sh
  4. README.md
  5. CHANGELOG.md

### 备份说明
所有被清理的文件都保存在：
- `backup_deploy/` - 项目冗余文件备份
- `test_backup/` - WorkBuddy工作区测试文件备份

## ✅ 完成状态
所有清理工作已完成，项目目录现在清晰整洁，一键更新工具可用。