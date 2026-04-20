#!/bin/bash
# ============================================================
# Mory Docker 部署脚本
# 使用方法：
#   bash docker_deploy.sh start   # 启动
#   bash docker_deploy.sh stop    # 停止
#   bash docker_deploy.sh restart  # 重启
#   bash docker_deploy.sh logs    # 查看日志
#   bash docker_deploy.sh status  # 查看状态
#   bash docker_deploy.sh update  # 更新代码并重启
# ============================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检查Docker
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log_error "Docker Compose 未安装，请先安装 Docker Compose"
        exit 1
    fi
}

# 检查.env文件
check_env() {
    if [ ! -f .env ]; then
        log_warn ".env 文件不存在，创建模板..."
        cat > .env << 'EOF'
# Telegram Bot Token（从 @BotFather 获取）
TG_TOKEN=your_telegram_bot_token_here

# 阿里云通义千问API Key
DASHSCOPE_KEY=your_dashscope_api_key_here

# 管理员ID（你自己的Telegram用户ID）
ADMIN_ID=123456789
EOF
        log_warn "请编辑 .env 文件填入你的配置！"
        exit 1
    fi
}

# 启动
start() {
    log_info "启动 Mory 助手..."
    docker compose up -d --build
    log_info "启动成功！"
    status
}

# 停止
stop() {
    log_info "停止 Mory 助手..."
    docker compose down
    log_info "已停止"
}

# 重启
restart() {
    log_info "重启 Mory 助手..."
    docker compose restart
    log_info "重启成功！"
    status
}

# 查看日志
logs() {
    docker compose logs -f --tail=100
}

# 查看状态
status() {
    docker compose ps
}

# 更新代码并重启
update() {
    log_info "更新代码..."
    if command -v git &> /dev/null; then
        git pull origin main
    fi
    log_info "重新构建镜像..."
    docker compose up -d --build
    log_info "更新完成！"
}

# 构建镜像
build() {
    log_info "构建镜像..."
    docker compose build --no-cache
    log_info "构建完成！"
}

# 清理
clean() {
    log_warn "清理 Docker 资源..."
    docker compose down -v --rmi local
    log_info "清理完成"
}

# 帮助
help() {
    echo "Mory Docker 部署脚本"
    echo ""
    echo "使用方法: bash docker_deploy.sh <command>"
    echo ""
    echo "命令:"
    echo "  start   - 启动服务"
    echo "  stop    - 停止服务"
    echo "  restart - 重启服务"
    echo "  logs    - 查看日志"
    echo "  status  - 查看状态"
    echo "  update  - 更新代码并重启"
    echo "  build   - 构建镜像"
    echo "  clean   - 清理Docker资源"
    echo "  help    - 显示帮助"
}

# 主逻辑
case "${1:-help}" in
    start)    check_docker && check_env && start ;;
    stop)     check_docker && stop ;;
    restart)  check_docker && restart ;;
    logs)     docker compose logs -f --tail=50 ;;
    status)   docker compose ps ;;
    update)   check_docker && update ;;
    build)    check_docker && build ;;
    clean)    check_docker && clean ;;
    help)     help ;;
    *)        help ;;
esac
