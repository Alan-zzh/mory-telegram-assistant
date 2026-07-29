# Mory Telegram Assistant Docker镜像
FROM python:3.11-slim

# 安装系统依赖（telegram-bot-py需要的C库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    libssl-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制依赖文件（优先使用 lock 锁定版本）
COPY requirements.lock requirements.txt

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 创建必要的目录
RUN mkdir -p logs backups data

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD pgrep -f 'python.*main.py' > /dev/null || exit 1

# 启动脚本
CMD ["python3", "main.py"]
