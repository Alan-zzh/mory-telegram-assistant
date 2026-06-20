#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/group_backup.py  ·  群设置备份/恢复模块                         ║
║                                                                        ║
║  功能：导出/导入群组全部设置，管理员专用。                               ║
║                                                                        ║
║  handle_backup()   -> 导出群设置为JSON文件                               ║
║  handle_restore()  -> 从JSON文件恢复群设置                              ║
║                                                                        ║
║  备份范围：                                                             ║
║    welcome_configs / message_locks / night_mode_settings                ║
║    custom_commands / group_notes / disabled_commands                    ║
║    scheduled_messages                                                   ║
║                                                                        ║
║  被调用：main.py 管理员命令处理                                         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import json
import time
import tempfile
import os
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("group_backup")

# 备份涉及的表及其列定义
_BACKUP_TABLES = {
    "welcome_configs": {
        "columns": ["chat_id", "welcome_text", "goodbye_text", "rules_text",
                     "enable_welcome", "enable_goodbye", "enable_rules",
                     "clean_welcome", "media_file_id"],
        "pk": ["chat_id"],
    },
    "message_locks": {
        "columns": ["chat_id", "lock_type", "enabled", "ts"],
        "pk": ["chat_id", "lock_type"],
    },
    "night_mode_settings": {
        "columns": ["chat_id", "start_hour", "end_hour", "enabled"],
        "pk": ["chat_id"],
    },
    "custom_commands": {
        "columns": ["chat_id", "cmd_name", "response", "created_by", "ts"],
        "pk": ["chat_id", "cmd_name"],
    },
    "group_notes": {
        "columns": ["chat_id", "note_name", "content", "created_by", "ts"],
        "pk": ["chat_id", "note_name"],
    },
    "disabled_commands": {
        "columns": ["chat_id", "cmd_name", "ts"],
        "pk": ["chat_id", "cmd_name"],
    },
    "scheduled_messages": {
        "columns": ["chat_id", "send_time", "content", "created_by", "ts", "enabled"],
        "pk": [],  # 无唯一约束，用INSERT
    },
}


def handle_backup(bot, m, config, db):
    """导出群设置为JSON文件（管理员）"""
    chat_id = m.chat.id
    uid = m.from_user.id
    backup_data = {
        "version": 1,
        "chat_id": chat_id,
        "backup_time": int(time.time()),
        "tables": {},
    }

    try:
        for table_name, table_info in _BACKUP_TABLES.items():
            cols = table_info["columns"]
            col_str = ", ".join(cols)
            with _db_lock:
                rows = db.conn.execute(
                    f"SELECT {col_str} FROM {table_name} WHERE chat_id=?",
                    (chat_id,),
                ).fetchall()
            # 转为字典列表
            backup_data["tables"][table_name] = [
                dict(zip(cols, row)) for row in rows
            ]

        # 序列化为JSON
        json_str = json.dumps(backup_data, ensure_ascii=False, indent=2)

        # 写入临时文件并发送
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(json_str)
            tmp_path = tmp.name

        chat_title = getattr(m.chat, "title", str(chat_id)) or str(chat_id)
        filename = f"backup_{chat_id}_{int(time.time())}.json"
        with open(tmp_path, "rb") as f:
            bot.send_document(
                chat_id,
                f,
                visible_file_name=filename,
                caption=f"📦 群设置备份：{chat_title}\n共 {_sum_counts(backup_data)} 条记录",
            )
        try:
            os.unlink(tmp_path)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        logger.info(f"群设置备份: chat={chat_id} by={uid} records={_sum_counts(backup_data)}")

    except Exception as e:
        logger.error(f"群设置备份失败: {e}")
        bot.reply_to(m, f"❌ 备份失败：{e}")


def handle_restore(bot, m, config, db):
    """从JSON文件恢复群设置（管理员）"""
    chat_id = m.chat.id
    uid = m.from_user.id

    # 必须回复一个文件消息
    if not m.reply_to_message or not m.reply_to_message.document:
        bot.reply_to(m, "❌ 请回复一个JSON备份文件来恢复设置")
        return

    try:
        # 下载文件
        file_info = bot.get_file(m.reply_to_message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        # 解析JSON
        if isinstance(downloaded, bytes):
            json_str = downloaded.decode("utf-8")
        else:
            json_str = downloaded
        backup_data = json.loads(json_str)

        # 校验格式
        if "version" not in backup_data or "tables" not in backup_data:
            bot.reply_to(m, "❌ 无效的备份文件格式")
            return

        restored = {}
        for table_name, rows in backup_data["tables"].items():
            if table_name not in _BACKUP_TABLES:
                continue
            table_info = _BACKUP_TABLES[table_name]
            cols = table_info["columns"]
            pk = table_info["pk"]
            count = 0
            for row_dict in rows:
                # 强制chat_id为当前群
                row_dict["chat_id"] = chat_id
                values = [row_dict.get(c) for c in cols]
                col_str = ", ".join(cols)
                placeholders = ", ".join(["?"] * len(cols))
                if pk:
                    # 有唯一约束用 INSERT OR REPLACE
                    sql = f"INSERT OR REPLACE INTO {table_name} ({col_str}) VALUES ({placeholders})"
                else:
                    # 无唯一约束直接 INSERT
                    sql = f"INSERT INTO {table_name} ({col_str}) VALUES ({placeholders})"
                with _db_lock:
                    db.conn.execute(sql, values)
                    db.conn.commit()
                count += 1
            restored[table_name] = count

        # 汇报恢复结果
        total = sum(restored.values())
        lines = [f"✅ 群设置已恢复（共 {total} 条记录）"]
        for table_name, count in restored.items():
            if count > 0:
                lines.append(f"  • {table_name}: {count} 条")
        bot.reply_to(m, "\n".join(lines))
        logger.info(f"群设置恢复: chat={chat_id} by={uid} total={total}")

    except json.JSONDecodeError:
        bot.reply_to(m, "❌ 备份文件JSON解析失败，请检查文件格式")
    except Exception as e:
        logger.error(f"群设置恢复失败: {e}")
        bot.reply_to(m, f"❌ 恢复失败：{e}")


def _sum_counts(backup_data):
    """统计备份记录总数"""
    return sum(len(rows) for rows in backup_data.get("tables", {}).values())
