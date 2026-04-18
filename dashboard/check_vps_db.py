import sqlite3, json, time

conn = sqlite3.connect("/root/mory/mory.db")
conn.row_factory = sqlite3.Row
cu = conn.cursor()
cu.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cu.fetchall()]
result = {}
now = int(time.time())

for t in tables:
    cu.execute(f"PRAGMA table_info({t})")
    cols = [{"name":r[1],"type":r[2]} for r in cu.fetchall()]
    cu.execute(f"SELECT COUNT(*) FROM {t}")
    cnt = cu.fetchone()[0]
    result[t] = {"cols": cols, "count": cnt}
    
    if t == "users":
        cu.execute("SELECT COUNT(*) FROM users WHERE last_active > ?", (now - 86400,))
        result[t]["active_today"] = cu.fetchone()[0]
        cu.execute("SELECT COUNT(*) FROM users WHERE last_active > ?", (now - 86400*7,))
        result[t]["active_week"] = cu.fetchone()[0]
        cu.execute("SELECT COUNT(*) FROM users WHERE private_messages > 0")
        result[t]["privated"] = cu.fetchone()[0]
        cu.execute("SELECT SUM(group_messages) FROM users")
        s = cu.fetchone()[0]
        result[t]["total_group_msgs"] = s or 0
        cu.execute("SELECT SUM(private_messages) FROM users")
        s = cu.fetchone()[0]
        result[t]["total_private_msgs"] = s or 0
        # 今日新增
        cu.execute("SELECT COUNT(*) FROM users WHERE first_seen > ?", (now - 86400,))
        result[t]["new_today"] = cu.fetchone()[0]
        # TOP10 群发言
        cu.execute("SELECT uid, name, group_messages FROM users ORDER BY group_messages DESC LIMIT 5")
        result[t]["top_group"] = [dict(r) for r in cu.fetchall()]
        # TOP10 私聊
        cu.execute("SELECT uid, name, private_messages FROM users ORDER BY private_messages DESC LIMIT 5")
        result[t]["top_private"] = [dict(r) for r in cu.fetchall()]
        # 转化漏斗
        cu.execute("SELECT COUNT(*) FROM users WHERE conversion_status = 'touched'")
        result[t]["funnel_touched"] = cu.fetchone()[0]
        cu.execute("SELECT COUNT(*) FROM users WHERE conversion_status = 'interested'")
        result[t]["funnel_interested"] = cu.fetchone()[0]
        cu.execute("SELECT COUNT(*) FROM users WHERE conversion_status = 'consulted'")
        result[t]["funnel_consulted"] = cu.fetchone()[0]
        cu.execute("SELECT COUNT(*) FROM users WHERE conversion_status = 'paid'")
        result[t]["funnel_paid"] = cu.fetchone()[0]
        # 等级分布
        cu.execute("""SELECT 
            CASE 
                WHEN level >= 30 THEN '30+'
                WHEN level >= 20 THEN '20-29'
                WHEN level >= 10 THEN '10-19'
                WHEN level >= 5 THEN '5-9'
                ELSE '0-4'
            END as lvl, COUNT(*) as cnt 
            FROM user_levels GROUP BY lvl ORDER BY lvl""")
        result[t]["level_dist"] = [dict(r) for r in cu.fetchall()]
        
    elif t == "user_levels":
        cu.execute("SELECT COUNT(*) FROM user_levels WHERE level >= 10")
        result[t]["level10plus"] = cu.fetchone()[0]
        cu.execute("SELECT AVG(points) FROM user_levels")
        result[t]["avg_points"] = round(cu.fetchone()[0] or 0, 1)
        
    elif t == "reply_tracking":
        cu.execute("SELECT COUNT(*) FROM reply_tracking WHERE replied = 1")
        result[t]["replied"] = cu.fetchone()[0]
        cu.execute("SELECT COUNT(*) FROM reply_tracking WHERE ts > ?", (now - 86400,))
        result[t]["today"] = cu.fetchone()[0]
        cu.execute("SELECT COUNT(*) FROM reply_tracking WHERE ts > ?", (now - 86400*7,))
        result[t]["week"] = cu.fetchone()[0]

print(json.dumps(result, ensure_ascii=False, default=str))
conn.close()
