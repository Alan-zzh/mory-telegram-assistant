import sqlite3

# 检查数据库中是否有频道记录
db_path = r'c:\Users\Administrator\Desktop\mory_assistant\data\mory.db'

try:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 检查channel_tracking表
    print("=== channel_tracking表中的频道 ===")
    c.execute("SELECT DISTINCT chat_id FROM channel_tracking")
    rows = c.fetchall()
    for row in rows:
        chat_id = row[0]
        # 获取该频道的消息数量
        c.execute("SELECT COUNT(*) FROM channel_tracking WHERE chat_id=?", (chat_id,))
        count = c.fetchone()[0]
        # 获取最新消息
        c.execute("SELECT content_type, posted_at, current_views FROM channel_tracking WHERE chat_id=? ORDER BY posted_at DESC LIMIT 1", (chat_id,))
        latest = c.fetchone()
        print(f"  {chat_id}: {count}条消息, 最新: {latest}")
    
    # 检查是否有其他表存储频道信息
    print("\n=== 所有表名 ===")
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = c.fetchall()
    for t in tables:
        print(f"  {t[0]}")
    
    conn.close()
except Exception as e:
    print(f"数据库错误: {e}")
