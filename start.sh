#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
#  Mory · 一键部署+更新脚本  (Ubuntu VPS)
#
#  【数据安全承诺】
#    - update 命令在重启前会自动备份 config.json 和 mory.db
#    - 备份位置：backup/pre_update_时间戳/
#    - 万一更新出问题，可手动恢复
#    - 所有用户数据/积分/等级/记忆都存储在 mory.db 中，不会丢失
#
#  用法：
#    首次部署：bash start.sh install
#    启动机器人：bash start.sh start
#    查看日志：bash start.sh log
#    停止机器人：bash start.sh stop
#    热更新代码（无感继续）：bash start.sh update
#    查看状态：bash start.sh status
#    恢复备份：bash start.sh restore
# ═══════════════════════════════════════════════════════════════════════════

set -e
BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="mory_bot"
PYTHON=$(which python3 || which python)
PID_FILE="$BOT_DIR/.mory.pid"
LOG_FILE="$BOT_DIR/mory.log"

cd "$BOT_DIR"
APP_VERSION=$("$PYTHON" -c "import version; print(version.VERSION)" 2>/dev/null || echo "unknown")

case "$1" in

# ─── 首次安装 ───────────────────────────────────────────────────
install)
    echo "📦 安装系统依赖..."
    apt-get update -qq
    apt-get install -y python3 python3-pip python3-venv screen fonts-noto-cjk -qq

    echo "🐍 创建虚拟环境..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip -q
    if [ -f "$BOT_DIR/requirements.txt" ]; then
        pip install -r "$BOT_DIR/requirements.txt" -q
    else
        pip install pyTelegramBotAPI requests Pillow apscheduler flask paramiko -q
    fi

    echo "✅ 安装完成！"
    echo ""
    echo "下一步：直接运行  bash start.sh start"
    ;;

# ─── 启动 ────────────────────────────────────────────────────────
start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        echo "⚠️  机器人已在运行 (PID=$(cat $PID_FILE))"
        exit 0
    fi

    echo "🚀 启动 Mory $APP_VERSION..."
    
    # 如果有虚拟环境就用，否则用系统python
    if [ -f "$BOT_DIR/venv/bin/python" ]; then
        PY="$BOT_DIR/venv/bin/python"
    else
        PY="$PYTHON"
    fi

    # 用 nohup 后台运行，重定向日志
    nohup "$PY" "$BOT_DIR/main.py" >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    
    sleep 2
    if kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        echo "✅ 启动成功！PID=$(cat $PID_FILE)"
        echo "📋 查看日志：bash start.sh log"
    else
        echo "❌ 启动失败，请查看日志：bash start.sh log"
        rm -f "$PID_FILE"
        exit 1
    fi
    ;;

# ─── 停止 ────────────────────────────────────────────────────────
stop)
    # 【v4.5.32】强力清理：先SIGTERM，再SIGKILL，防止多进程残留
    # 【v4.5.33】修复：精确匹配完整路径+排除mory_media，不误杀其他Bot项目
    PIDS=""
    if [ -f "$PID_FILE" ]; then
        PIDS=$(cat "$PID_FILE")
    fi
    PIDS="$PIDS $(ps -ef | grep '/home/ubuntu/mory_assistant/main.py' | grep -v grep | grep -v mory_media | awk '{print $2}')"
    PIDS=$(echo "$PIDS" | tr ' ' '\n' | sort -u | grep -v '^$')
    
    if [ -n "$PIDS" ]; then
        for PID in $PIDS; do
            if kill -0 "$PID" 2>/dev/null; then
                kill "$PID" 2>/dev/null
                echo "   ⏳ 发送停止信号 PID=$PID"
            fi
        done
        
        # 等待最多5秒让进程正常退出
        for i in $(seq 1 5); do
            ALL_STOPPED=true
            for PID in $PIDS; do
                if kill -0 "$PID" 2>/dev/null; then
                    ALL_STOPPED=false
                    break
                fi
            done
            if $ALL_STOPPED; then
                break
            fi
            sleep 1
        done
        
        # 如果还有残留，强制SIGKILL
        for PID in $PIDS; do
            if kill -0 "$PID" 2>/dev/null; then
                kill -9 "$PID" 2>/dev/null
                echo "    强制杀死残留进程 PID=$PID"
            fi
        done
        sleep 0.5
        rm -f "$PID_FILE"
        echo "✅ 所有Bot进程已清理"
    else
        echo "⚠️  机器人未在运行"
    fi
    ;;

# ─── 重启 ────────────────────────────────────────────────────────
restart)
    bash "$0" stop
    sleep 1
    bash "$0" start
    ;;

# ─── 热更新（上传新代码后安全重启）──────────────────────────────
update)
    echo "🔄 热更新代码..."
    
    # ╔══════════════════════════════════════════════════╗
    # ║  【数据安全保护】更新前自动备份                   ║
    # ║  备份 config.json + mory.db 到 backup/ 目录      ║
    # ╚══════════════════════════════════════════════════╝
    BACKUP_DIR="backup/pre_update_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    if [ -f "$BOT_DIR/config.json" ]; then
        cp "$BOT_DIR/config.json" "$BACKUP_DIR/config.json"
        echo "   ✅ config.json 已备份"
    fi
    
    if [ -f "$BOT_DIR/mory.db" ]; then
        cp "$BOT_DIR/mory.db" "$BACKUP_DIR/mory.db"
        echo "   ✅ mory.db 已备份"
    fi
    
    echo "   📁 备份位置：$BACKUP_DIR/"
    echo ""
    echo "   1. 停止旧进程..."
    bash "$0" stop
    sleep 1
    
    echo "   2. 检查数据库完整性..."
    if [ -f "$BOT_DIR/mory.db" ]; then
        if [ -f "$BOT_DIR/venv/bin/python" ]; then
            PY="$BOT_DIR/venv/bin/python"
        else
            PY="$PYTHON"
        fi
        # 快速完整性检查（sqlite3内置PRAGMA）
        CHECK=$($PY -c "
import sqlite3
conn = sqlite3.connect('$BOT_DIR/mory.db')
try:
    conn.execute('PRAGMA integrity_check')
    result = conn.execute('SELECT count(*) FROM sqlite_master').fetchone()[0]
    print(f'OK tables={result}')
except Exception as e:
    print(f'ERROR {e}')
finally:
    conn.close()
" 2>&1)
        if echo "$CHECK" | grep -q "^OK"; then
            echo "   ✅ 数据库完整性检查通过"
        else
            echo "   ⚠️ 数据库检查异常：$CHECK"
            echo "   → 已有备份在 $BACKUP_DIR/，可手动恢复"
        fi
    fi
    
    echo "   3. 启动新进程..."
    bash "$0" start
    echo ""
    echo "═══════════════════════════════════════════════════"
    echo "✅ 热更新完成！"
    echo "   - 数据库：完整继承"
    echo "   - 配置文件：完整继承"
    echo "   - 用户记忆/积分/等级：完整继承"
    echo "   - 更新前备份：$BACKUP_DIR/"
    echo "   - 出问题恢复：bash start.sh restore"
    echo "═══════════════════════════════════════════════════"
    ;;

# ─── 恢复最近一次备份 ─────────────────────────────────────────
restore)
    # 找最近的pre_update备份
    LATEST=$(ls -dt "$BOT_DIR/backup/pre_update_"* 2>/dev/null | head -1)
    if [ -z "$LATEST" ]; then
        echo "⚠️ 没有找到更新备份。backup/ 目录下只有定时备份。"
        echo "   如需恢复定时备份，手动执行："
        echo "   cp backup/mory_backup_XXXXXX.db mory.db"
        exit 1
    fi
    echo "📂 找到最近备份：$LATEST/"
    echo ""
    
    # 先停止
    bash "$0" stop 2>/dev/null || true
    sleep 1
    
    # 恢复
    if [ -f "$LATEST/config.json" ]; then
        cp "$LATEST/config.json" "$BOT_DIR/config.json"
        echo "   ✅ config.json 已恢复"
    fi
    if [ -f "$LATEST/mory.db" ]; then
        cp "$LATEST/mory.db" "$BOT_DIR/mory.db"
        echo "   ✅ mory.db 已恢复"
    fi
    
    echo ""
    bash "$0" start
    echo "✅ 已恢复并重新启动！"
    ;;

# ─── 查看状态 ────────────────────────────────────────────────────
status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        echo "🟢 机器人运行中  PID=$(cat $PID_FILE)"
        echo "📊 内存使用：$(ps -p $(cat $PID_FILE) -o rss= | awk '{print $1/1024 "MB"}')"
        echo "📁 数据库大小：$(du -h mory.db 2>/dev/null | cut -f1)"
        echo "📦 备份数量：$(ls backup/mory_backup_*.db 2>/dev/null | wc -l) 份"
        echo "📝 更新备份：$(ls -dt backup/pre_update_* 2>/dev/null | head -1 | xargs basename 2>/dev/null || echo '无')"
    else
        echo "🔴 机器人未运行"
    fi
    ;;

# ─── 实时日志 ────────────────────────────────────────────────────
log)
    echo "📋 实时日志 (Ctrl+C 退出)..."
    tail -f "$LOG_FILE"
    ;;

# ─── 查看最近100行日志 ──────────────────────────────────────────
log100)
    tail -100 "$LOG_FILE"
    ;;

# ─── 设置开机自启（systemd）─────────────────────────────────────
autostart)
    cat > /etc/systemd/system/mory_bot.service << EOF
[Unit]
Description=Mory Telegram Bot v4.5.8
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$BOT_DIR
ExecStart=$BOT_DIR/venv/bin/python $BOT_DIR/main.py
Restart=always
RestartSec=10
StandardOutput=append:$LOG_FILE
StandardError=append:$LOG_FILE

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable mory_bot
    systemctl start mory_bot
    echo "✅ 已设置开机自启并立即启动"
    echo "💡 查看状态：systemctl status mory_bot"
    ;;

# ─── 默认提示 ────────────────────────────────────────────────────
*)
    echo "═══════════════════════════════════════════"
    echo "  🤖 Mory v4.5.8 管理脚本"
    echo "═══════════════════════════════════════════"
    echo "  bash start.sh install    首次安装依赖"
    echo "  bash start.sh start      启动机器人"
    echo "  bash start.sh stop       停止机器人"
    echo "  bash start.sh restart    重启机器人"
    echo "  bash start.sh update     热更新代码（自动备份）"
    echo "  bash start.sh restore    恢复最近备份"
    echo "  bash start.sh status     查看状态+数据"
    echo "  bash start.sh log        实时日志"
    echo "  bash start.sh autostart  设置开机自启"
    echo "═══════════════════════════════════════════"
    ;;
esac
