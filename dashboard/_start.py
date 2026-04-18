#!/usr/bin/env python3
"""
Dashboard启动器
支持本地和远程部署
"""
import os
import sys

# 添加项目根目录
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# 启动Dashboard
if __name__ == "__main__":
    from dashboard.app import app
    print("""
╔════════════════════════════════════════════════════╗
║       🚀 Mory Dashboard Pro v4.0                 ║
╠════════════════════════════════════════════════════╣
║  🌐 地址: http://localhost:5000                  ║
║  🔐 密码: mory2026                               ║
║  📱 局域网: http://<你的IP>:5000                 ║
╚════════════════════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=5000, debug=False)
