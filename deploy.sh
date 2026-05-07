#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
#  Mory v21.44  ·  完整部署脚本  (Ubuntu/Debian VPS)
#
#  功能：
#    - 系统依赖检查与安装
#    - Python环境配置
#    - 项目依赖安装
#    - 配置文件检查
#    - 服务启动与自启设置
#    - 健康检查
#
#  用法：
#    bash deploy.sh [install|start|stop|status|health|autostart]
# ═══════════════════════════════════════════════════════════════════════════

set -e

# 项目根目录
BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="mory_bot"
PYTHON=$(which python3 || which python)
PID_FILE="$BOT_DIR/.mory.pid"
LOG_FILE="$BOT_DIR/mory.log"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

echo_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

echo_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

cd "$BOT_DIR"

case "$1" in

# ─── 完整安装 ───────────────────────────────────────────────────
install)
    echo_info "开始完整部署 Mory 小助理..."
    
    # 1. 系统更新与依赖安装
    echo_info "1. 系统更新与依赖安装..."
    apt-get update -qq
    apt-get install -y python3 python3-pip python3-venv screen fonts-noto-cjk curl wget git -qq
    
    # 2. 创建虚拟环境
    echo_info "2. 创建Python虚拟环境..."
    if [ -d "$BOT_DIR/venv" ]; then
        echo_warning "虚拟环境已存在，跳过创建"
    else
        python3 -m venv venv
        echo_success "虚拟环境创建成功"
    fi
    
    # 3. 激活虚拟环境并安装依赖
    echo_info "3. 安装项目依赖..."
    source venv/bin/activate
    pip install --upgrade pip -q
    
    if [ -f "$BOT_DIR/requirements.txt" ]; then
        pip install -r "$BOT_DIR/requirements.txt" -q
        echo_success "依赖安装完成（从requirements.txt）"
    else
        pip install pyTelegramBotAPI requests Pillow apscheduler paramiko flask -q
        echo_success "依赖安装完成（默认包）"
    fi
    
    # 4. 配置文件检查
    echo_info "4. 配置文件检查..."
    
    if [ ! -f "$BOT_DIR/config.json" ]; then
        echo_warning "config.json 不存在，使用默认配置"
        cp "$BOT_DIR/config.json.example" "$BOT_DIR/config.json" 2>/dev/null || {
            echo_error "config.json.example 不存在，创建最小默认配置"
            cat > "$BOT_DIR/config.json" << EOF
{
  "_CONFIG_VERSION": "4.5.0",
  "_CONFIG_UPDATED": "$(date '+%Y-%m-%d %H:%M')",
  "TOKEN": "",
  "API_KEY": "",
  "ADMIN_ID": 0,
  "GROUP_ID": 0,
  "BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
  "MODEL_POOLS": {
    "llm": [
      {
        "name": "qwen-plus",
        "expire": "2099-12-31"
      }
    ]
  },
  "REPLY_CHANCE": 10,
  "SYSTEM_PROMPT": "你是Mory，一个活泼可爱的小助理。"
}
EOF
        }
    fi
    
    if [ ! -f "$BOT_DIR/.env" ]; then
        echo_warning ".env 文件不存在，创建配置模板"
        cat > "$BOT_DIR/.env" << EOF
# Telegram Bot Token
TG_TOKEN=

# 通义千问 API Key
DASHSCOPE_KEY=

# Dashboard
DASHBOARD_SECRET=
DASHBOARD_PASSWORD=

# VPS
VPS_HOST=
VPS_PORT=22
VPS_USER=root
VPS_SSH_PASS=
VPS_PATH=/root/mory
EOF
        echo_warning "请编辑 .env 文件填写必要的配置"
    fi
    
    # 5. 创建必要目录
    echo_info "5. 创建必要目录..."
    mkdir -p backup logs
    
    # 6. 权限设置
    echo_info "6. 设置文件权限..."
    chmod +x start.sh deploy.sh
    
    echo_success "🎉 完整部署完成！"
    echo ""
    echo "下一步："
    echo "1. 编辑 .env 文件填写 Telegram Bot Token 和 API Key"
    echo "2. 运行: bash start.sh start 启动机器人"
    echo "3. 运行: bash deploy.sh autostart 设置开机自启"
    ;;

# ─── 健康检查 ───────────────────────────────────────────────────
health)
    echo_info "执行健康检查..."
    
    # 1. 检查进程状态
    if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        echo_success "✅ 机器人进程运行正常"
        echo "   PID: $(cat $PID_FILE)"
        echo "   内存使用: $(ps -p $(cat $PID_FILE) -o rss= | awk '{print $1/1024 "MB"}')"
    else
        echo_error "❌ 机器人进程未运行"
    fi
    
    # 2. 检查配置文件
    if [ -f "$BOT_DIR/config.json" ]; then
        echo_success "✅ 配置文件存在"
        VERSION=$(grep "_CONFIG_VERSION" "$BOT_DIR/config.json" | cut -d '"' -f 4)
        echo "   配置版本: $VERSION"
    else
        echo_error "❌ 配置文件不存在"
    fi
    
    # 3. 检查依赖
    echo_info "检查Python依赖..."
    if [ -d "$BOT_DIR/venv" ]; then
        source "$BOT_DIR/venv/bin/activate"
        MISSING=0
        for pkg in "pyTelegramBotAPI" "requests" "Pillow" "apscheduler" "paramiko" "flask"; do
            if ! pip list | grep -q "^$pkg\s"; then
                echo_error "   ❌ $pkg 未安装"
                MISSING=1
            else
                echo_success "   ✅ $pkg 已安装"
            fi
        done
        if [ $MISSING -eq 0 ]; then
            echo_success "✅ 所有依赖安装完成"
        fi
    else
        echo_error "❌ 虚拟环境不存在"
    fi
    
    # 4. 检查数据库
    if [ -f "$BOT_DIR/mory.db" ]; then
        echo_success "✅ 数据库文件存在"
        echo "   大小: $(du -h "$BOT_DIR/mory.db" 2>/dev/null | cut -f1)"
    else
        echo_warning "⚠️  数据库文件不存在，首次启动会自动创建"
    fi
    
    # 5. 检查环境变量
    if [ -f "$BOT_DIR/.env" ]; then
        echo_success "✅ 环境变量文件存在"
        # 检查关键配置
        TG_TOKEN_SET=$(grep "TG_TOKEN" "$BOT_DIR/.env" | grep -v "^#" | grep -q "=".*"" && echo 1 || echo 0)
        API_KEY_SET=$(grep "DASHSCOPE_KEY" "$BOT_DIR/.env" | grep -v "^#" | grep -q "=".*"" && echo 1 || echo 0)
        
        if [ $TG_TOKEN_SET -eq 1 ]; then
            echo_success "   ✅ Telegram Token 已配置"
        else
            echo_error "   ❌ Telegram Token 未配置"
        fi
        
        if [ $API_KEY_SET -eq 1 ]; then
            echo_success "   ✅ API Key 已配置"
        else
            echo_error "   ❌ API Key 未配置"
        fi
    else
        echo_error "❌ 环境变量文件不存在"
    fi
    ;;

# ─── 开机自启 ───────────────────────────────────────────────────
autostart)
    echo_info "设置开机自启..."
    
    # 创建 systemd 服务文件
    cat > /etc/systemd/system/mory_bot.service << EOF
[Unit]
Description=Mory Telegram Bot v21.44
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
    
    # 重新加载服务
    systemctl daemon-reload
    systemctl enable mory_bot
    systemctl start mory_bot
    
    echo_success "✅ 开机自启设置完成"
    echo "   服务名称: mory_bot"
    echo "   查看状态: systemctl status mory_bot"
    echo "   停止服务: systemctl stop mory_bot"
    echo "   启动服务: systemctl start mory_bot"
    ;;

# ─── 启动 ───────────────────────────────────────────────────────
start)
    bash "$BOT_DIR/start.sh" start
    ;;

# ─── 停止 ───────────────────────────────────────────────────────
stop)
    bash "$BOT_DIR/start.sh" stop
    ;;

# ─── 查看状态 ───────────────────────────────────────────────────
status)
    bash "$BOT_DIR/start.sh" status
    ;;

# ─── 默认提示 ───────────────────────────────────────────────────
*)
    echo "═══════════════════════════════════════════"
    echo "  🤖 Mory v21.44 部署脚本"
    echo "═══════════════════════════════════════════"
    echo "  bash deploy.sh install    完整安装部署"
    echo "  bash deploy.sh start      启动机器人"
    echo "  bash deploy.sh stop       停止机器人"
    echo "  bash deploy.sh status     查看状态"
    echo "  bash deploy.sh health     健康检查"
    echo "  bash deploy.sh autostart  设置开机自启"
    echo "═══════════════════════════════════════════"
    ;;

esac