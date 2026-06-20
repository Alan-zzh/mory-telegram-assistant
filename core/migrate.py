"""
版本平滑升级迁移工具

功能：
  1. 数据库schema迁移（新增表/列/索引，幂等执行）
  2. 配置兼容性检查（缺失字段补默认值、废弃字段清理）
  3. 数据完整性校验

用法：
  python -m core.migrate          # 执行全部迁移
  python -m core.migrate --check  # 仅检查，不执行
"""

import json
import os
import sys
import sqlite3
import logging
from core.config_compat import normalize_runtime_config, compact_runtime_config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("migrate")

DB_FILE = "mory.db"
CONFIG_FILE = "config.json"

MIGRATIONS = []

DEFAULT_CONFIG = {
    "REPLY_CHANCE": 10,
    "REPLY_DELAY_MIN": 1,
    "REPLY_DELAY_MAX": 3,
    "MAX_MSG_LENGTH": 2000,
    "PUZZLE_ENABLED": False,
    "SIGNUP_ENABLED": False,
    "AUTO_GREETING": False,
    "AUTO_GOODNIGHT": False,
    "AUTO_NEWS": False,
    "WELCOME_MSG": False,
    "ANTI_REVOKE": False,
    "BURN_AFTER": False,
    "RECOVER_ENABLED": False,
    "SPAM_LIMIT": {"messages_per_minute": 10, "ban_minutes": 5},
    "BANNED_WORDS": ["赌博", "贩毒", "诈骗"],
    "HATE_KEYWORDS": [],
    "AUTO_MUTE_NAMES": [],
    "BAN_DURATION_DEFAULT": 5,
    "MAX_REQUESTS_PER_USER": 100,
    "TEMPERATURE": 0.85,
    "MAX_TOKENS": 500,
    "TOP_P": 0.9,
    "FREQUENCY_PENALTY": 0.3,
    "PRESENCE_PENALTY": 0.2,
}


def migration(version: str, desc: str):
    def decorator(func):
        MIGRATIONS.append({"version": version, "desc": desc, "func": func})
        return func
    return decorator


@migration("4.6.0", "新增reply_feedback表")
def m_reply_feedback(conn, check_only=False):
    try:
        conn.execute("SELECT id FROM reply_feedback LIMIT 0")
        return "已存在，跳过"
    except sqlite3.OperationalError:
        if check_only:
            return "需要创建"
        conn.execute("""CREATE TABLE IF NOT EXISTS reply_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_msg_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            feedback TEXT NOT NULL,
            ts INTEGER NOT NULL,
            UNIQUE(bot_msg_id, chat_id, user_id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reply_feedback_ts ON reply_feedback(ts)")
        conn.commit()
        return "已创建"


@migration("4.6.0", "新增keyword_triggers表")
def m_keyword_triggers(conn, check_only=False):
    try:
        conn.execute("SELECT id FROM keyword_triggers LIMIT 0")
        return "已存在，跳过"
    except sqlite3.OperationalError:
        if check_only:
            return "需要创建"
        conn.execute("""CREATE TABLE IF NOT EXISTS keyword_triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            reply_text TEXT NOT NULL,
            reply_type TEXT DEFAULT 'static',
            action_type TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            created_at INTEGER,
            updated_at INTEGER
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_keyword_trigger_enabled ON keyword_triggers(enabled)")
        conn.commit()
        return "已创建"


@migration("4.6.0", "新增task_log表+唯一索引")
def m_task_log(conn, check_only=False):
    try:
        conn.execute("SELECT id FROM task_log LIMIT 0")
    except sqlite3.OperationalError:
        if check_only:
            return "需要创建"
        conn.execute("""CREATE TABLE IF NOT EXISTS task_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_key TEXT NOT NULL,
            exec_date TEXT NOT NULL,
            exec_ts REAL NOT NULL
        )""")
        conn.commit()
        return "已创建"
    try:
        conn.execute("SELECT 1 FROM sqlite_master WHERE name='idx_task_log_unique'")
        has_unique = conn.fetchone() is not None
    except Exception:
        has_unique = False
    if not has_unique:
        if check_only:
            return "需要添加唯一索引"
        try:
            conn.execute("DELETE FROM task_log WHERE id NOT IN (SELECT MIN(id) FROM task_log GROUP BY task_key, exec_date)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_task_log_unique ON task_log(task_key, exec_date)")
            conn.commit()
        except Exception as e:
            return f"索引添加跳过: {e}"
        return "唯一索引已添加"
    return "唯一索引已存在，跳过"


@migration("4.6.0", "补充users表缺失列")
def m_users_columns(conn, check_only=False):
    c = conn.cursor()
    c.execute("PRAGMA table_info(users)")
    existing = {r[1] for r in c.fetchall()}
    added = []
    new_cols = [
        ("private_messages", "INTEGER DEFAULT 0"),
        ("keywords", "TEXT DEFAULT ''"),
        ("conversion_status", "TEXT DEFAULT 'unknown'"),
    ]
    for col_name, col_type in new_cols:
        if col_name not in existing:
            if check_only:
                added.append(f"{col_name}(需要添加)")
            else:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
                added.append(f"{col_name}(已添加)")
    if added:
        conn.commit()
    return "、".join(added) if added else "无需迁移"


@migration("4.6.0", "补充reply_tracking缺失列")
def m_reply_tracking_columns(conn, check_only=False):
    c = conn.cursor()
    c.execute("PRAGMA table_info(reply_tracking)")
    existing = {r[1] for r in c.fetchall()}
    added = []
    new_cols = [
        ("chat_id", "INTEGER"),
        ("replied", "INTEGER DEFAULT 0"),
    ]
    for col_name, col_type in new_cols:
        if col_name not in existing:
            if check_only:
                added.append(f"{col_name}(需要添加)")
            else:
                conn.execute(f"ALTER TABLE reply_tracking ADD COLUMN {col_name} {col_type}")
                added.append(f"{col_name}(已添加)")
    if added:
        conn.commit()
    return "、".join(added) if added else "无需迁移"


def check_config_compat(config: dict, check_only=False) -> list:
    results = []
    for key, default in DEFAULT_CONFIG.items():
        if key not in config:
            if check_only:
                results.append(f"缺失 {key}，默认值: {repr(default)[:50]}")
            else:
                config[key] = default
                results.append(f"已补齐 {key}")
    return results


def run_migrations(check_only=False):
    if not os.path.exists(DB_FILE):
        logger.info(f"数据库文件 {DB_FILE} 不存在，跳过数据库迁移")
    else:
        conn = sqlite3.connect(DB_FILE)
        conn.execute("PRAGMA journal_mode=WAL")
        # 【TRAE SOLO CN v5.18.3审计修复】迁移连接加 busy_timeout，防止与 Bot 进程互锁
        conn.execute("PRAGMA busy_timeout=30000")
        logger.info(f"{'[检查模式]' if check_only else '[执行模式]'} 数据库迁移开始")
        for m in MIGRATIONS:
            try:
                result = m["func"](conn, check_only=check_only)
                status = "✅" if not check_only else "🔍"
                logger.info(f"  {status} [{m['version']}] {m['desc']}: {result}")
            except Exception as e:
                logger.error(f"  ❌ [{m['version']}] {m['desc']}: {e}")
        conn.close()

    if not os.path.exists(CONFIG_FILE):
        logger.info(f"配置文件 {CONFIG_FILE} 不存在，跳过配置兼容性检查")
    else:
        logger.info(f"{'[检查模式]' if check_only else '[执行模式]'} 配置兼容性检查")
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = normalize_runtime_config(json.load(f))
        results = check_config_compat(config, check_only=check_only)
        if results:
            for r in results:
                logger.info(f"  {'🔍' if check_only else '✅'} {r}")
            if not check_only:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(compact_runtime_config(config), f, ensure_ascii=False, indent=2)
                logger.info("  配置文件已保存")
        else:
            logger.info("  配置完整，无需补齐")


if __name__ == "__main__":
    check = "--check" in sys.argv
    run_migrations(check_only=check)
