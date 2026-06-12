# -*- coding: utf-8 -*-
"""
db_repos 共享常量

集中存放各 Repo 共同使用的常量，消除重复定义。
"""
from datetime import timezone, timedelta

# 【修复v21.47】统一使用北京时间，避免时区混乱导致每日重置错误
_CST = timezone(timedelta(hours=8))
