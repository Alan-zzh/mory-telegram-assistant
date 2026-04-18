import sqlite3, os

db_path = os.path.join(r"C:\Users\Administrator\Desktop", "mory小助理", "mory.db")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 获取所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cursor.fetchall()]

for t in tables:
    print(f"\n=== {t} ===")
    cursor.execute(f"PRAGMA table_info({t})")
    cols = cursor.fetchall()
    for c in cols:
        print(f"  {c[1]} ({c[2]})")
    cursor.execute(f"SELECT COUNT(*) FROM {t}")
    cnt = cursor.fetchone()[0]
    print(f"  [总行数: {cnt}]")
    # 显示前2行样本数据
    cursor.execute(f"SELECT * FROM {t} LIMIT 2")
    rows = cursor.fetchall()
    col_names = [d[0] for d in cols]
    for row in rows:
        print(f"  样本: {dict(zip(col_names, row))}")

conn.close()
