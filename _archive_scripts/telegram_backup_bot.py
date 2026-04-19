#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mory小助理 - Telegram私聊备份功能
功能：通过私聊指令将数据库记录发送给用户
"""

import telebot
import sqlite3
import io
import sys
import os
import json
from datetime import datetime
import zipfile

# 注意：这个脚本需要在Mory主程序中集成，这里只是示例代码

class BackupBot:
    def __init__(self, token, admin_id, db_path="mory.db"):
        self.bot = telebot.TeleBot(token)
        self.admin_id = admin_id
        self.db_path = db_path
        
        # 注册命令处理器
        @self.bot.message_handler(commands=['backup'])
        def handle_backup(message):
            self.send_backup(message)
            
        @self.bot.message_handler(commands=['stats'])
        def handle_stats(message):
            self.send_stats(message)
            
        @self.bot.message_handler(commands=['export'])
        def handle_export(message):
            self.export_data(message)
    
    def check_permission(self, user_id):
        """检查用户权限"""
        return str(user_id) == str(self.admin_id)
    
    def get_database_info(self):
        """获取数据库信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            info = []
            info.append("=== 数据库信息 ===")
            info.append(f"备份时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            info.append(f"文件大小: {os.path.getsize(self.db_path)} 字节")
            
            # 获取所有表信息
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = cursor.fetchall()
            
            info.append(f"\n=== 表信息 ({len(tables)}个) ===")
            for table in tables:
                table_name = table[0]
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                info.append(f"{table_name}: {count} 条记录")
            
            conn.close()
            return "\n".join(info)
            
        except Exception as e:
            return f"获取数据库信息失败: {e}"
    
    def create_backup_file(self):
        """创建备份文件"""
        try:
            # 创建内存中的zip文件
            backup_io = io.BytesIO()
            
            with zipfile.ZipFile(backup_io, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 添加数据库文件
                zipf.write(self.db_path, "mory.db")
                
                # 添加数据库信息文本
                info = self.get_database_info()
                zipf.writestr("database_info.txt", info)
                
                # 添加备份时间戳
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                zipf.writestr("backup_time.txt", timestamp)
            
            backup_io.seek(0)
            return backup_io
            
        except Exception as e:
            print(f"创建备份文件失败: {e}")
            return None
    
    def send_backup(self, message):
        """发送备份文件"""
        if not self.check_permission(message.from_user.id):
            self.bot.reply_to(message, "❌ 权限不足，只有管理员可以使用此命令")
            return
        
        try:
            self.bot.reply_to(message, "🔄 正在创建数据库备份...")
            
            backup_io = self.create_backup_file()
            if not backup_io:
                self.bot.reply_to(message, "❌ 创建备份失败")
                return
            
            # 发送文件
            self.bot.send_document(
                chat_id=message.chat.id,
                document=backup_io,
                caption=f"📦 Mory小助理数据库备份\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n文件: mory.db.zip",
                visible_file_name=f"mory_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            )
            
            # 发送数据库信息
            info = self.get_database_info()
            if len(info) > 4000:
                # 如果信息太长，分开发送
                parts = [info[i:i+4000] for i in range(0, len(info), 4000)]
                for i, part in enumerate(parts):
                    caption = f"数据库信息 (第{i+1}/{len(parts)}部分):"
                    self.bot.send_message(message.chat.id, f"{caption}\n```\n{part}\n```", parse_mode="Markdown")
            else:
                self.bot.send_message(message.chat.id, f"```\n{info}\n```", parse_mode="Markdown")
                
        except Exception as e:
            self.bot.reply_to(message, f"❌ 发送备份失败: {e}")
    
    def send_stats(self, message):
        """发送统计信息"""
        if not self.check_permission(message.from_user.id):
            self.bot.reply_to(message, "❌ 权限不足")
            return
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            stats = []
            stats.append("📊 Mory小助理数据统计")
            stats.append(f"统计时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            stats.append("")
            
            # 获取关键表统计
            key_tables = ['users', 'reply_tracking', 'user_levels', 'blacklist']
            
            for table in key_tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    stats.append(f"{table}: {count} 条记录")
                except:
                    stats.append(f"{table}: 表不存在或查询失败")
            
            # 获取用户活跃度统计
            try:
                cursor.execute("SELECT COUNT(*) FROM users WHERE last_active > ?", 
                             (int(time.time()) - 7*24*3600,))
                active_7d = cursor.fetchone()[0]
                stats.append(f"\n最近7天活跃用户: {active_7d} 人")
            except:
                pass
            
            conn.close()
            
            stats_text = "\n".join(stats)
            self.bot.reply_to(message, f"```\n{stats_text}\n```", parse_mode="Markdown")
            
        except Exception as e:
            self.bot.reply_to(message, f"❌ 获取统计信息失败: {e}")
    
    def export_data(self, message):
        """导出特定数据为CSV"""
        if not self.check_permission(message.from_user.id):
            self.bot.reply_to(message, "❌ 权限不足")
            return
        
        try:
            # 解析命令参数
            args = message.text.split()
            if len(args) < 2:
                self.bot.reply_to(message, "用法: /export <table_name>\n例如: /export users")
                return
            
            table_name = args[1]
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 检查表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
            if not cursor.fetchone():
                self.bot.reply_to(message, f"❌ 表 '{table_name}' 不存在")
                conn.close()
                return
            
            # 获取表数据
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            
            conn.close()
            
            if not rows:
                self.bot.reply_to(message, f"表 '{table_name}' 为空")
                return
            
            # 创建CSV内容
            import csv
            csv_io = io.StringIO()
            writer = csv.writer(csv_io)
            writer.writerow(columns)
            writer.writerows(rows)
            
            csv_content = csv_io.getvalue().encode('utf-8')
            csv_io_bytes = io.BytesIO(csv_content)
            
            # 发送CSV文件
            self.bot.send_document(
                chat_id=message.chat.id,
                document=csv_io_bytes,
                caption=f"📋 {table_name} 表数据导出\n记录数: {len(rows)}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                visible_file_name=f"{table_name}_export_{datetime.now().strftime('%Y%m%d')}.csv"
            )
            
        except Exception as e:
            self.bot.reply_to(message, f"❌ 导出数据失败: {e}")
    
    def run(self):
        """启动bot"""
        print(f"🔧 Telegram备份Bot已启动，管理员ID: {self.admin_id}")
        print("可用命令:")
        print("  /backup - 下载完整数据库备份")
        print("  /stats  - 查看数据统计")
        print("  /export <table> - 导出指定表为CSV")
        self.bot.polling(none_stop=True)

# 使用示例
if __name__ == "__main__":
    # 需要从config.json读取配置
    import json
    
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        
        token = config.get("TELEGRAM_BOT_TOKEN")
        admin_id = config.get("ADMIN_ID")
        
        if not token or not admin_id:
            print("❌ 请在config.json中配置TELEGRAM_BOT_TOKEN和ADMIN_ID")
            sys.exit(1)
        
        backup_bot = BackupBot(token, admin_id)
        backup_bot.run()
        
    except FileNotFoundError:
        print("❌ config.json文件不存在")
    except json.JSONDecodeError:
        print("❌ config.json格式错误")