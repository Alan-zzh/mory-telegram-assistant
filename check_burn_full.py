#!/usr/bin/env python3
"""
阅后即焚诊断脚本 v1.0
检查以下问题：
1. reply_tracking表状态
2. 追踪记录是否正常
3. 探测任务是否执行
4. 日志中追踪相关记录
"""
import sqlite3
import os
import sys
from datetime import datetime, timedelta, timezone

# VPS路径
VPS_DB = "/root/mory_bot/mory.db"
VPS_LOG = "/root/mory_bot/logs/bot.log"

def cst_now():
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz)

def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def check_database():
    print_section("1. 数据库状态检查")
    
    if not os.path.exists(VPS_DB):
        print(f"❌ 数据库不存在: {VPS_DB}")
        return False
    
    conn = sqlite3.connect(VPS_DB)
    c = conn.cursor()
    
    # 表列表
    c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in c.fetchall()]
    print(f"📋 数据表: {tables}")
    
    # reply_tracking表详情
    print(f"\n📊 reply_tracking 表:")
    c.execute("SELECT COUNT(*) FROM reply_tracking")
    total = c.fetchone()[0]
    print(f"   总记录数: {total}")
    
    if total > 0:
        c.execute("SELECT * FROM reply_tracking LIMIT 10")
        cols = [d[0] for d in c.description]
        print(f"   列: {cols}")
        print("   最近10条记录:")
        for row in c.fetchall():
            print(f"   {row}")
        
        # 统计
        c.execute("SELECT COUNT(*) FROM reply_tracking WHERE replied=0")
        unreplied = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM reply_tracking WHERE replied=1")
        replied = c.fetchone()[0]
        c.execute("SELECT MIN(ts), MAX(ts) FROM reply_tracking")
        min_max = c.fetchone()
        
        print(f"   replied=0: {unreplied}")
        print(f"   replied=1: {replied}")
        if min_max[0]:
            cst = timezone(timedelta(hours=8))
            min_dt = datetime.fromtimestamp(min_max[0], tz=cst)
            max_dt = datetime.fromtimestamp(min_max[1], tz=cst)
            print(f"   时间范围: {min_dt} ~ {max_dt}")
    else:
        print("   ⚠️ 表为空！检查追踪逻辑是否正常工作")
    
    conn.close()
    return total > 0

def check_config():
    print_section("2. 配置检查")
    
    config_path = "/root/mory_bot/config.json"
    if not os.path.exists(config_path):
        print(f"❌ 配置文件不存在: {config_path}")
        return
    
    import json
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # 关键配置
    keys = ["GROUP_ID", "ADMIN_ID", "BOT_NAME", "_LAST_LEAK_WEEK"]
    for key in keys:
        val = config.get(key, "未设置")
        print(f"   {key}: {val}")

def check_logs():
    print_section("3. 日志检查（追踪相关）")
    
    if not os.path.exists(VPS_LOG):
        print(f"❌ 日志文件不存在: {VPS_LOG}")
        return
    
    # 搜索追踪相关日志
    keywords = [
        "阅后即焚追踪",
        "tracked_reply",
        "track_reply",
        "孤儿清理",
        "原消息探测",
        "get_unconfirmed",
        "refresh_tracked",
        "auto_mark_group",
        "竞态",
        "forward_message",
    ]
    
    print(f"📄 检查日志: {VPS_LOG}")
    print()
    
    # 读取最近1000行
    with open(VPS_LOG, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    recent = lines[-2000:] if len(lines) > 2000 else lines
    print(f"📝 最近{len(recent)}行日志中搜索追踪相关记录...")
    
    found_any = False
    for kw in keywords:
        matches = [l.strip() for l in recent if kw in l]
        if matches:
            found_any = True
            print(f"\n🔍 [{kw}] ({len(matches)}条):")
            for m in matches[-5:]:  # 每种最多显示5条
                print(f"   {m[:120]}")
    
    if not found_any:
        print("⚠️ 未找到任何追踪相关日志！可能原因：")
        print("   1. 日志级别不是DEBUG（很多日志是logger.debug）")
        print("   2. _tracked_reply从未被调用")
        print("   3. 群聊消息没有触发AI回复")

def check_process():
    print_section("4. 进程状态")
    
    import subprocess
    try:
        result = subprocess.run(['pgrep', '-f', 'main.py'], 
                              capture_output=True, text=True)
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            print(f"✅ Bot进程运行中: {pids}")
            for pid in pids:
                try:
                    res = subprocess.run(['ps', '-p', pid, '-o', 'etime,cmd'], 
                                       capture_output=True, text=True)
                    print(res.stdout)
                except:
                    pass
        else:
            print("❌ Bot进程未运行")
    except Exception as e:
        print(f"检查进程失败: {e}")

def check_bot_mode():
    print_section("5. Bot运行模式检查")
    
    main_path = "/root/mory_bot/main.py"
    if not os.path.exists(main_path):
        print(f"❌ main.py不存在: {main_path}")
        return
    
    with open(main_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # 检查关键标记
    checks = {
        "_tracked_reply": "_tracked_reply函数存在",
        "bot.reply_to = _tracked_reply": "monkey-patch已应用",
        "db.track_reply": "调用track_reply",
        "get_unconfirmed_messages": "原消息探测函数",
        "get_orphan_messages": "孤儿清理函数",
        "forward_message": "forward探测",
    }
    
    print("代码检查:")
    for pattern, desc in checks.items():
        if pattern in content:
            print(f"   ✅ {desc}")
        else:
            print(f"   ❌ {desc} - 未找到!")

def check_recent_messages():
    print_section("6. 最近Bot活动检查")
    
    # 检查备份文件看是否有追踪记录
    backup_dir = "/root/mory_bot/backup"
    if os.path.exists(backup_dir):
        backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.db')])
        if backups:
            print(f"📁 最新备份: {backups[-1]}")
            latest = os.path.join(backup_dir, backups[-1])
            
            try:
                conn = sqlite3.connect(latest)
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM reply_tracking")
                count = c.fetchone()[0]
                print(f"   备份中reply_tracking记录数: {count}")
                conn.close()
            except Exception as e:
                print(f"   检查备份失败: {e}")

def summary():
    print_section("诊断总结")
    print("""
🔍 可能的问题原因:

1. 【最可能】reply_tracking表为空，说明群聊消息从未触发追踪
   - 检查: 群里是否有人发消息？Bot是否回复了？
   - Bot回复时是否调用了 bot.reply_to()？

2. 日志级别问题
   - 大部分追踪日志是 logger.debug() 级别
   - 默认不输出，需要配置 logging level=DEBUG

3. 群聊ID问题
   - cid < 0 才是群聊
   - 私聊不追踪（这是正确的）

4. 孤儿清理逻辑
   - get_orphan_messages() 基于时间窗口(86400秒=24小时)
   - auto_mark_group_active() 会标记10分钟内的消息为"已回复"

✅ 正确的修复应该确保:
   - 群聊消息触发AI回复时，调用 bot.reply_to()
   - _tracked_reply被正确调用
   - 数据库中有追踪记录
   - 探测任务能检查到未确认的消息
""")

if __name__ == "__main__":
    print(f"🔍 阅后即焚诊断开始 - {cst_now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    has_data = check_database()
    check_config()
    check_logs()
    check_process()
    check_bot_mode()
    check_recent_messages()
    summary()
