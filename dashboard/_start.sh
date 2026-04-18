#!/bin/bash
cd /root/mory/dashboard

# 使用虚拟环境中的python
VENV_PYTHON="/root/mory/dashboard/venv/bin/python"

# 如果venv不存在，创建它
if [ ! -d "venv" ]; then
    python3 -m venv venv
    source venv/bin/activate
    pip install flask paramiko -q
    deactivate
fi

# 停止旧进程
pkill -f "dashboard.*app.py" 2>/dev/null
sleep 1

# 启动
nohup /root/mory/dashboard/venv/bin/python app.py >> dashboard.log 2>&1 &
echo $! > dashboard.pid
echo "Dashboard started, PID: $(cat dashboard.pid)"
