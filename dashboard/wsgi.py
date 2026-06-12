# -*- coding: utf-8 -*-
"""
dashboard/wsgi.py  ·  Gunicorn 生产级入口

给 gunicorn 导入用的：
    python3 -m gunicorn -k gevent -w 2 -b 0.0.0.0:6616 dashboard.wsgi:app

这样就不用改 app.py 的代码结构。
"""
from dashboard.app import app

# 如果 create_app() 返回 None（密钥没配），让 gunicorn 启动失败
if app is None:
    raise RuntimeError("Dashboard 初始化失败：DASHBOARD_SECRET 未设置或太短")
