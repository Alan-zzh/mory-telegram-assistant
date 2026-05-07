# -*- coding: utf-8 -*-
import sqlite3
import sys

def check_database():
    try:
        conn = sqlite3.connect('mory.db')
        cursor = conn.cursor()
        
        # 查看所有表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        
        print("=== 数据库表结构 ===")
        for table in tables:
            table_name = table[0]
            print(f"\n表名: {table_name}")
            
            # 查看表结构
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            print("  列结构:")
            for col in columns:
                print(f"    {col[1]} ({col[2]})")
            
            # 查看数据量
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            print(f"  数据行数: {count}")
            
            # 如果是重要表，显示部分示例数据
            if count > 0 and count <= 10:
                cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
                rows = cursor.fetchall()
                print("  示例数据 (前3行):")
                for row in rows:
                    print(f"    {row}")
        
        # 查看数据库大小
        cursor.execute("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
        db_size = cursor.fetchone()[0]
        print(f"\n=== 数据库信息 ===")
        print(f"数据库文件大小: {db_size} 字节 ({db_size/1024:.2f} KB)")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"检查数据库时出错: {e}")
        return False

if __name__ == "__main__":
    check_database()