"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/database.py  ·  SQLite线程安全数据层                              ║
║                                                                        ║
║  功能：                                                                ║
║    统一管理所有持久化数据。所有模块通过 main.py 创建的 db 单例访问。     ║
║                                                                        ║
║  数据表清单：                                                          ║
║    users             → 用户画像（uid/名称/首次/最后活跃/消息数/关键词）  ║
║    wake_up           → 叫醒服务（uid/时间）                             ║
║    puzzle_scores     → 碎片寻宝积分（uid/分数）                         ║
║    puzzle_daily      → 碎片寻宝每日记录（uid/日期，防同日重复）          ║
║    cart_recovery     → 购物车挽回（uid/触发时间戳）                     ║
║    reply_tracking    → 阅后即焚追踪（机器人消息ID/群ID/用户消息ID/状态） ║
║    user_levels       → 等级积分（uid/等级/积分/加入时间）               ║
║    mute_records      → 禁言记录（uid/群ID/解禁时间/原因）               ║
║    blacklist         → 黑名单（uid/原因/日期）                          ║
║    conversion_funnel → 转化漏斗（uid/接触/感兴趣/咨询/已付）            ║
║    spam_track        → 反刷检测（uid/消息数/窗口起始时间）              ║
║                                                                        ║
║  线程安全：全局互斥锁 _db_lock，所有写操作都在锁内完成。                ║
║  被调用：main.py, modules/*.py → db.xxx()                              ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import sqlite3
import time
import logging
from threading import Lock
from datetime import datetime, timedelta, timezone

# 【修复v21.47】统一使用北京时间，避免时区混乱导致每日重置错误
_CST = timezone(timedelta(hours=8))
from core.logging_util import get_logger

logger = get_logger("database")

# 全局互斥锁，确保并发写入安全
_db_lock = Lock()


class DB:
    """
    统一数据管理器（线程安全）。
    所有模块通过单例 `db` 访问。
    """

    def __init__(self, db_file: str):
        self.db_file = db_file
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        # 【修复】：开启 WAL 模式，提升多线程下 SQLite 并发性能，杜绝 Locked 报错
        self.conn.execute("PRAGMA journal_mode=WAL;")
        # 【v4.3.2修复F-07】WAL自动checkpoint，防止WAL文件无限增长
        self.conn.execute("PRAGMA wal_autocheckpoint=1000;")
        self._init_tables()

    # 【v4.3.2修复F-05】添加close()方法，确保SQLite连接正确关闭
    def close(self):
        """关闭数据库连接，释放资源"""
        try:
            if self.conn:
                self.conn.close()
                logger.info("✅ 数据库连接已关闭")
        except Exception as e:
            logger.warning(f"数据库关闭异常：{e}")

    def __del__(self):
        """析构时自动关闭连接"""
        self.close()

    # ─────────────────────────────── 初始化 ──────────────────────────────
    def _init_tables(self):
        with _db_lock:
            c = self.conn.cursor()

            # 用户画像
            c.execute("""CREATE TABLE IF NOT EXISTS users (
                uid INTEGER PRIMARY KEY,
                name TEXT,
                first_seen INTEGER,
                last_active INTEGER,
                group_messages INTEGER DEFAULT 0,
                private_messages INTEGER DEFAULT 0,
                keywords TEXT DEFAULT '',
                conversion_status TEXT DEFAULT 'unknown'
            )""")

            # 叫醒服务
            c.execute("""CREATE TABLE IF NOT EXISTS wake_up (
                uid INTEGER PRIMARY KEY,
                wake_time TEXT
            )""")

            # 碎片寻宝积分
            c.execute("""CREATE TABLE IF NOT EXISTS puzzle_scores (
                uid INTEGER PRIMARY KEY,
                score INTEGER DEFAULT 0
            )""")

            # 碎片寻宝每日记录（防止同一天重复计分）
            c.execute("""CREATE TABLE IF NOT EXISTS puzzle_daily (
                uid INTEGER,
                date TEXT,
                ts INTEGER DEFAULT 0,
                PRIMARY KEY (uid, date)
            )""")

            # 购物车挽回
            c.execute("""CREATE TABLE IF NOT EXISTS cart_recovery (
                uid INTEGER PRIMARY KEY,
                ts INTEGER
            )""")

            # 阅后即焚追踪（【修复v21.33】复合主键，Telegram message_id跨群会重复）
            c.execute("""CREATE TABLE IF NOT EXISTS reply_tracking (
                bot_msg_id INTEGER,
                chat_id INTEGER,
                user_msg_id INTEGER,
                ts INTEGER,
                replied INTEGER DEFAULT 0,
                PRIMARY KEY (bot_msg_id, chat_id)
            )""")

            # 用户等级/积分
            c.execute("""CREATE TABLE IF NOT EXISTS user_levels (
                uid INTEGER PRIMARY KEY,
                level INTEGER DEFAULT 1,
                points INTEGER DEFAULT 0,
                join_date INTEGER,
                last_active INTEGER
            )""")

            # 禁言记录
            c.execute("""CREATE TABLE IF NOT EXISTS mute_records (
                uid INTEGER PRIMARY KEY,
                chat_id INTEGER,
                mute_until INTEGER,
                reason TEXT
            )""")

            # 黑名单
            c.execute("""CREATE TABLE IF NOT EXISTS blacklist (
                uid INTEGER PRIMARY KEY,
                reason TEXT,
                date INTEGER
            )""")

            # 转化漏斗（【修复v21.34】事件日志表，支持多次记录）
            c.execute("""CREATE TABLE IF NOT EXISTS conversion_events (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                uid   INTEGER,
                event TEXT,
                ts    INTEGER,
                mode  TEXT DEFAULT ''
            )""")

            # 垃圾信息/反刷记录
            c.execute("""CREATE TABLE IF NOT EXISTS spam_track (
                uid INTEGER PRIMARY KEY,
                msg_count INTEGER DEFAULT 0,
                window_start INTEGER
            )""")

            # 【架构重构v21.44】系统动态状态表
            # 替代 config.json 中的动态字段（如 CURRENT_MODEL_INDEX, IMAGE_POOL 等）
            c.execute("""CREATE TABLE IF NOT EXISTS system_states (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at INTEGER
            )""")

            # 【v4.2.3】群数据统计表
            c.execute("""CREATE TABLE IF NOT EXISTS group_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                chat_id INTEGER DEFAULT 0,
                joined_count INTEGER DEFAULT 0,
                left_count INTEGER DEFAULT 0,
                net_count INTEGER DEFAULT 0,
                total_members INTEGER DEFAULT 0,
                created_at INTEGER
            )""")

            # 【v4.2.3】频道内容追踪表（追踪机器人发的消息浏览量）
            c.execute("""CREATE TABLE IF NOT EXISTS channel_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                message_id INTEGER,
                content_type TEXT DEFAULT 'text',
                posted_at INTEGER,
                initial_views INTEGER DEFAULT 0,
                current_views INTEGER DEFAULT 0,
                last_checked_at INTEGER,
                UNIQUE(chat_id, message_id)
            )""")

            # 【v4.3.0新增】用户勋章表
            c.execute("""CREATE TABLE IF NOT EXISTS user_badges (
                uid INTEGER,
                badge_id TEXT,
                earned_at INTEGER,
                PRIMARY KEY (uid, badge_id)
            )""")

            # 【v4.4.9新增】关键词自动回复表
            c.execute("""CREATE TABLE IF NOT EXISTS keyword_triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                reply_text TEXT NOT NULL,
                reply_type TEXT DEFAULT 'static',
                action_type TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                created_at INTEGER,
                updated_at INTEGER
            )""")
            # 添加关键词索引，加速匹配
            c.execute("CREATE INDEX IF NOT EXISTS idx_keyword_trigger_enabled ON keyword_triggers(enabled)")

            c.execute("""CREATE TABLE IF NOT EXISTS task_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_key TEXT NOT NULL,
                exec_date TEXT NOT NULL,
                exec_ts REAL NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_task_log_key_date ON task_log(task_key, exec_date)")
            
            # 【v4.5.31】防连发：清理重复记录 + 添加UNIQUE约束
            try:
                c.execute("""DELETE FROM task_log WHERE id NOT IN (
                    SELECT MIN(id) FROM task_log GROUP BY task_key, exec_date
                )""")
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_task_log_unique ON task_log(task_key, exec_date)")
            except Exception as e:
                logger.debug(f"task_log唯一索引迁移: {e}")

            # ── 兼容性迁移：旧数据库缺少的列自动补齐 ──────────────────
            try:
                self.conn.execute("SELECT replied FROM reply_tracking LIMIT 0")
            except Exception:
                self.conn.execute("ALTER TABLE reply_tracking ADD COLUMN replied INTEGER DEFAULT 0")
                logger.info("🔄 数据库迁移：reply_tracking 补充 replied 列")

            # 【修复v21.33】reply_tracking 单主键 → 复合主键迁移
            try:
                c = self.conn.cursor()
                c.execute("PRAGMA table_info(reply_tracking)")
                cols = [r[1] for r in c.fetchall()]
                if "chat_id" not in cols:
                    self.conn.execute("ALTER TABLE reply_tracking ADD COLUMN chat_id INTEGER")
                    logger.info("🔄 数据库迁移：reply_tracking 补充 chat_id 列")
            except Exception as e:
                logger.warning(f"🔄 reply_tracking 迁移检查跳过：{e}")
            try:
                self.conn.execute("SELECT conversion_status FROM users LIMIT 0")
            except Exception:
                self.conn.execute("ALTER TABLE users ADD COLUMN conversion_status TEXT DEFAULT 'unknown'")
                logger.info("🔄 数据库迁移：users 补充 conversion_status 列")

            try:
                c.execute("SELECT chat_id FROM group_stats LIMIT 1")
            except Exception:
                c.execute("ALTER TABLE group_stats ADD COLUMN chat_id INTEGER DEFAULT 0")
                logger.info("✅ group_stats表已添加chat_id列")

            self.conn.commit()

            # ── 性能索引（IF NOT EXISTS 幂等）【v4.2.8增强：添加replied索引防止全表扫描】─
            _indexes = [
                "CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active)",
                "CREATE INDEX IF NOT EXISTS idx_users_conv ON users(conversion_status)",
                "CREATE INDEX IF NOT EXISTS idx_levels_points ON user_levels(points DESC)",
                "CREATE INDEX IF NOT EXISTS idx_track_ts ON reply_tracking(ts)",
                "CREATE INDEX IF NOT EXISTS idx_track_chat ON reply_tracking(chat_id)",
                "CREATE INDEX IF NOT EXISTS idx_track_bot_chat ON reply_tracking(bot_msg_id, chat_id)",
                "CREATE INDEX IF NOT EXISTS idx_track_replied ON reply_tracking(ts, replied)",  # 【v4.2.8新增】加速孤儿消息查询
                "CREATE INDEX IF NOT EXISTS idx_cart_ts ON cart_recovery(ts)",
                "CREATE INDEX IF NOT EXISTS idx_mute_until ON mute_records(mute_until)",
                "CREATE INDEX IF NOT EXISTS idx_wake_uid ON wake_up(uid)",
                "CREATE INDEX IF NOT EXISTS idx_puzzle_uid ON puzzle_scores(uid)",
            ]
            for _idx_sql in _indexes:
                self.conn.execute(_idx_sql)
            self.conn.commit()

        logger.info("✅ 数据库初始化完成（含11个性能索引）")

    # ─────────────────────────────── 用户 ────────────────────────────────
    def upsert_user(self, uid: int, name: str, msg_type: str = "group"):
        ts = int(time.time())
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""INSERT OR IGNORE INTO users
                (uid, name, first_seen, last_active) VALUES (?,?,?,?)""",
                (uid, name, ts, ts))
            if msg_type == "group":
                c.execute("UPDATE users SET last_active=?, group_messages=group_messages+1, name=? WHERE uid=?",
                          (ts, name, uid))
            else:
                c.execute("UPDATE users SET last_active=?, private_messages=private_messages+1, name=? WHERE uid=?",
                          (ts, name, uid))
            self.conn.commit()

    def upsert_user_with_points(self, uid: int, name: str, msg_type: str = "group", pts: int = 1):
        ts = int(time.time())
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""INSERT OR IGNORE INTO users
                (uid, name, first_seen, last_active) VALUES (?,?,?,?)""",
                (uid, name, ts, ts))
            if msg_type == "group":
                c.execute("UPDATE users SET last_active=?, group_messages=group_messages+1, name=? WHERE uid=?",
                          (ts, name, uid))
            else:
                c.execute("UPDATE users SET last_active=?, private_messages=private_messages+1, name=? WHERE uid=?",
                          (ts, name, uid))
            c.execute("INSERT OR IGNORE INTO user_levels VALUES (?,1,0,?,?)", (uid, ts, ts))
            c.execute("UPDATE user_levels SET points=points+?, last_active=? WHERE uid=?",
                      (pts, ts, uid))
            c.execute("SELECT points FROM user_levels WHERE uid=?", (uid,))
            total = c.fetchone()[0]
            level = 1
            if total >= 500: level = 4
            elif total >= 100: level = 3
            elif total >= 20: level = 2
            c.execute("UPDATE user_levels SET level=? WHERE uid=?", (level, uid))
            self.conn.commit()

    def get_user(self, uid: int):
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT * FROM users WHERE uid=?", (uid,))
            return c.fetchone()

    def add_keyword(self, uid: int, keyword: str):
        """追加用户画像关键词"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT keywords FROM users WHERE uid=?", (uid,))
            row = c.fetchone()
            if row:
                existing = row[0] or ""
                if keyword not in existing:
                    new_kw = (existing + "," + keyword).strip(",")
                    c.execute("UPDATE users SET keywords=? WHERE uid=?", (new_kw, uid))
            self.conn.commit()

    def get_active_users(self, since_ts: int):
        """获取since_ts之后活跃的用户列表"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT uid, name, keywords FROM users WHERE last_active>?", (since_ts,))
            return c.fetchall()

    def get_inactive_users(self, before_ts: int, exclude_uid: int):
        """获取before_ts之前未活跃的用户（醋意挽回用）"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT uid, name FROM users WHERE last_active<? AND uid!=?",
                      (before_ts, exclude_uid))
            return c.fetchall()

    def reset_last_active(self, uid: int):
        ts = int(time.time())
        with _db_lock:
            self.conn.execute("UPDATE users SET last_active=? WHERE uid=?", (ts, uid))
            self.conn.commit()

    # ─────────────────────────────── 叫醒 ────────────────────────────────
    def set_wake_up(self, uid: int, wake_time: str):
        with _db_lock:
            self.conn.execute("INSERT OR REPLACE INTO wake_up VALUES (?,?)", (uid, wake_time))
            self.conn.commit()

    def get_all_wake_ups(self):
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT uid, wake_time FROM wake_up")
            return c.fetchall()

    # ─────────────────────────────── 寻宝 ────────────────────────────────
    def inc_puzzle_score(self, uid: int) -> tuple:
        """
        尝试增加寻宝积分。每天最多计1次，连续7天凑齐7分可领奖。
        返回 (当前分数, 今日是否已计, 连续天数)
        """
        today = datetime.now(_CST).strftime("%Y-%m-%d")  # 【修复v21.47】使用北京时间
        try:
            with _db_lock:
                c = self.conn.cursor()
                c.execute("INSERT OR IGNORE INTO puzzle_scores VALUES (?,0)", (uid,))
                # 检查今天是否已计分
                c.execute("SELECT 1 FROM puzzle_daily WHERE uid=? AND date=?", (uid, today))
                if c.fetchone():
                    # 今天已计分
                    c.execute("SELECT score FROM puzzle_scores WHERE uid=?", (uid,))
                    return (c.fetchone()[0], True, 0)
                # 今天未计分，加分
                c.execute("INSERT OR REPLACE INTO puzzle_daily VALUES (?,?,?)", (uid, today, int(time.time())))
                c.execute("UPDATE puzzle_scores SET score=score+1 WHERE uid=?", (uid,))
                c.execute("SELECT score FROM puzzle_scores WHERE uid=?", (uid,))
                score = c.fetchone()[0]
                # 计算连续天数（连续7天有记录）
                consecutive = self._calc_consecutive_days(uid)
                if score >= 7:
                    c.execute("UPDATE puzzle_scores SET score=0 WHERE uid=?", (uid,))
                    self.conn.commit()
                    return (7, False, consecutive)
                self.conn.commit()
                return (score, False, consecutive)
        except Exception as e:
            logger.error(f"寻宝积分操作失败 uid={uid}: {e}")
            return (0, False, 0)

    def _calc_consecutive_days(self, uid: int) -> int:
        """计算用户连续签到天数（由调用方保证在_db_lock内调用，不再重复获取锁）"""
        c = self.conn.cursor()
        c.execute("SELECT date FROM puzzle_daily WHERE uid=? ORDER BY date DESC", (uid,))
        dates = [row[0] for row in c.fetchall()]
        if not dates:
            return 0
        count = 1
        from datetime import datetime as dt
        for i in range(1, len(dates)):
            try:
                prev = dt.strptime(dates[i-1], "%Y-%m-%d")
                curr = dt.strptime(dates[i], "%Y-%m-%d")
                if (prev - curr).days == 1:
                    count += 1
                else:
                    break
            except Exception:
                break
        return count

    # ─────────────────────────────── 购物车 ──────────────────────────────
    def set_cart(self, uid: int):
        with _db_lock:
            self.conn.execute("INSERT OR REPLACE INTO cart_recovery VALUES (?,?)",
                             (uid, int(time.time())))
            self.conn.commit()

    def get_expired_carts(self, delay_seconds: int = 86400):
        cutoff = int(time.time()) - delay_seconds
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT uid FROM cart_recovery WHERE ts<?", (cutoff,))
            rows = [r[0] for r in c.fetchall()]
            if rows:
                # 【v4.3.2修复S-09】添加长度限制，防止IN子句过长
                rows = rows[:100]
                self.conn.execute(f"DELETE FROM cart_recovery WHERE uid IN ({','.join('?'*len(rows))})",
                                 rows)
                self.conn.commit()
            return rows

    # ─────────────────────────────── 阅后即焚 ────────────────────────────
    def track_reply(self, bot_msg_id: int, chat_id: int, user_msg_id: int):
        """记录机器人回复，追踪原消息是否被删（复合主键：bot_msg_id+chat_id）"""
        with _db_lock:
            try:
                if not bot_msg_id or not chat_id or not user_msg_id:
                    logger.error(f"📌 track_reply参数无效: bot={bot_msg_id} chat={chat_id} user={user_msg_id}")
                    return

                ts = int(time.time())
                self.conn.execute("INSERT OR REPLACE INTO reply_tracking (bot_msg_id, chat_id, user_msg_id, ts, replied) VALUES (?,?,?,?,0)",
                                 (bot_msg_id, chat_id, user_msg_id, ts))
                self.conn.commit()
                logger.info(f"📌 阅后即焚追踪成功：bot={bot_msg_id} chat={chat_id} user={user_msg_id} ts={ts}")
            except Exception as e:
                logger.error(f"📌 阅后即焚追踪失败：{e}")

    def mark_replied(self, bot_msg_id: int, chat_id: int = 0):
        """用户回复了机器人的消息，标记为已回复（不自动删除）"""
        with _db_lock:
            if chat_id:
                self.conn.execute("UPDATE reply_tracking SET replied=1 WHERE bot_msg_id=? AND chat_id=?",
                                 (bot_msg_id, chat_id))
            else:
                self.conn.execute("UPDATE reply_tracking SET replied=1 WHERE bot_msg_id=?",
                                 (bot_msg_id,))
            self.conn.commit()

    def get_replies_to(self, user_msg_id: int, chat_id: int):
        """获取机器人对某条消息的所有回复（用于消息被删时同步删除）"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, replied FROM reply_tracking
                         WHERE user_msg_id=? AND chat_id=?""", (user_msg_id, chat_id))
            return c.fetchall()

    def get_recent_unreplied(self, min_age: int = 300, max_age: int = 1800, limit: int = 10):
        """获取最近未回复的消息（用于探测用户是否删消息）
        
        Args:
            min_age: 最小存活秒数（默认5分钟，避免探测刚发的消息）
            max_age: 最大存活秒数（默认30分钟）
            limit: 最多返回条数（防止一次探测太多）
        """
        now = int(time.time())
        since = now - max_age
        until = now - min_age
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                         WHERE ts BETWEEN ? AND ? AND user_msg_id>0 AND replied=0
                         ORDER BY ts ASC LIMIT ?""", (since, until, limit))
            return c.fetchall()

    def get_orphan_messages(self, window: int = 86400):
        """返回超过window秒未被回复的孤儿消息。
        
        【审查修复】只有replied=0的消息才算孤儿。
        用户回复了机器人的消息应该获得豁免，不应被清理。
        注意：不再自动删除数据库记录，由调用方处理（保持职责分离）。
        """
        cutoff = int(time.time()) - window
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                         WHERE ts<? AND user_msg_id>0 AND replied=0""", (cutoff,))
            return c.fetchall()

    def get_unreplied_messages(self):
        """返回所有未被回复的机器人消息（不限时间，用于清群无人理）"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                         WHERE replied=0""")
            return c.fetchall()

    def get_ignored_messages(self, min_age: int = 1800):
        """智能判断「真正无人理」的消息：
        - replied=0（没人显式回复）
        - 且消息已存在超过 min_age 秒（默认30分钟，避免误删刚发的）
        - 返回 (bot_msg_id, chat_id, user_msg_id)
        """
        cutoff = int(time.time()) - min_age
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                         WHERE replied=0 AND ts<?""", (cutoff,))
            return c.fetchall()

    def get_all_tracked_messages(self, window: int = 86400):
        """返回窗口内的所有追踪消息（不限replied状态，用于清全部回复）"""
        now = int(time.time())
        since = now - window
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                         WHERE ts>?""", (since,))
            return c.fetchall()

    def get_unconfirmed_messages(self, window: int = 86400):
        """返回window时间内未被回复的追踪消息（探测原消息是否还在）。
        
        【审查修复v21.47】
        - 窗口从1小时扩大到24小时，修复23小时探测盲区
        - 按时间倒序，确保优先探测新消息
        - 尊重"豁免保护"：只有replied=0的消息才需要探测
        """
        now = int(time.time())
        since = now - window
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                         WHERE ts>? AND user_msg_id>0 AND replied=0 ORDER BY ts DESC""", (since,))
            return c.fetchall()

    def delete_tracked(self, bot_msg_id: int, chat_id: int = 0):
        """删除阅后即焚追踪记录"""
        with _db_lock:
            if chat_id:
                self.conn.execute("DELETE FROM reply_tracking WHERE bot_msg_id=? AND chat_id=?", (bot_msg_id, chat_id))
            else:
                self.conn.execute("DELETE FROM reply_tracking WHERE bot_msg_id=?", (bot_msg_id,))
            self.conn.commit()

    # ─────────────────────────────── 等级/积分 ───────────────────────────
    def get_user_points(self, uid: int):
        """查询单用户积分，返回int或None（不存在时）"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT points FROM user_levels WHERE uid=?", (uid,))
            row = c.fetchone()
            return row[0] if row else None

    def add_points(self, uid: int, pts: int):
        ts = int(time.time())
        with _db_lock:
            c = self.conn.cursor()
            c.execute("INSERT OR IGNORE INTO user_levels VALUES (?,1,0,?,?)", (uid, ts, ts))
            c.execute("UPDATE user_levels SET points=points+?, last_active=? WHERE uid=?",
                      (pts, ts, uid))
            c.execute("SELECT points FROM user_levels WHERE uid=?", (uid,))
            total = c.fetchone()[0]
            level = 1
            if total >= 500: level = 4
            elif total >= 100: level = 3
            elif total >= 20: level = 2
            c.execute("UPDATE user_levels SET level=? WHERE uid=?", (level, uid))
            self.conn.commit()

    def get_leaderboard(self, limit: int = 10):
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT u.uid, u.name, COALESCE(ul.points,0), COALESCE(ul.level,1)
                         FROM users u LEFT JOIN user_levels ul ON u.uid=ul.uid
                         ORDER BY COALESCE(ul.points,0) DESC LIMIT ?""", (limit,))
            return c.fetchall()

    # ─────────────────────────────── 禁言 ────────────────────────────────
    def mute_user(self, uid: int, chat_id: int, minutes: int, reason: str = "违反群规"):
        until = int(time.time()) + minutes * 60
        with _db_lock:
            self.conn.execute("INSERT OR REPLACE INTO mute_records VALUES (?,?,?,?)",
                             (uid, chat_id, until, reason))
            self.conn.commit()

    def is_muted(self, uid: int) -> bool:
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT mute_until FROM mute_records WHERE uid=?", (uid,))
            row = c.fetchone()
            if row:
                if row[0] > int(time.time()):
                    return True
                self.conn.execute("DELETE FROM mute_records WHERE uid=?", (uid,))
                self.conn.commit()
            return False

    # ─────────────────────────────── 黑名单 ──────────────────────────────
    def blacklist_add(self, uid: int, reason: str = "垃圾信息"):
        with _db_lock:
            self.conn.execute("INSERT OR IGNORE INTO blacklist VALUES (?,?,?)",
                             (uid, reason, int(time.time())))
            self.conn.commit()

    def is_blacklisted(self, uid: int) -> bool:
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT 1 FROM blacklist WHERE uid=?", (uid,))
            return c.fetchone() is not None

    # ─────────────────────────────── 转化漏斗（事件化） ───────────────────
    def log_conversion_event(self, uid: int, event: str, mode: str = ""):
        """event: touched | interested | consulted | paid"""
        with _db_lock:
            self.conn.execute(
                "INSERT INTO conversion_events(uid, event, ts, mode) VALUES (?, ?, ?, ?)",
                (uid, event, int(time.time()), mode)
            )
            self.conn.commit()

    def get_funnel_summary(self):
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT
                COUNT(DISTINCT CASE WHEN event='touched'    THEN uid END),
                COUNT(DISTINCT CASE WHEN event='interested' THEN uid END),
                COUNT(DISTINCT CASE WHEN event='consulted'  THEN uid END),
                COUNT(DISTINCT CASE WHEN event='paid'       THEN uid END)
                FROM conversion_events""")
            return c.fetchone()

    # ─────────────────────────────── 反刷 ────────────────────────────────
    def check_spam(self, uid: int, limit: int, window: int = 60) -> bool:
        """返回True代表触发刷屏阈值"""
        now = int(time.time())
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT msg_count, window_start FROM spam_track WHERE uid=?", (uid,))
            row = c.fetchone()
            if not row or now - row[1] > window:
                self.conn.execute("INSERT OR REPLACE INTO spam_track VALUES (?,1,?)", (uid, now))
                self.conn.commit()
                return False
            count = row[0] + 1
            self.conn.execute("UPDATE spam_track SET msg_count=? WHERE uid=?", (count, uid))
            self.conn.commit()
            return count >= limit

    # ─────────────────────────────── 简报 ────────────────────────────────
    def get_daily_report(self) -> dict:
        ts = int(time.time())
        day_ago = ts - 86400
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT COUNT(*) FROM users WHERE last_active>?", (day_ago,))
            active = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users WHERE first_seen>?", (day_ago,))
            new_users = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users")
            total = c.fetchone()[0]
            funnel = self.get_funnel_summary()
            c.execute("""SELECT u.name, COALESCE(ul.points,0) FROM users u
                         LEFT JOIN user_levels ul ON u.uid=ul.uid
                         ORDER BY COALESCE(ul.points,0) DESC LIMIT 5""")
            top5 = c.fetchall()
            c.execute("SELECT COUNT(*) FROM blacklist")
            blacklist_cnt = c.fetchone()[0]
        return {
            "active": active,
            "new_users": new_users,
            "total": total,
            "funnel": funnel or (0,0,0,0),
            "top5": top5,
            "blacklist": blacklist_cnt,
        }

    # ─────────────────────────────── 画像简报 ────────────────────────────
    def get_user_profile(self, uid: int) -> dict | None:
        """获取用户完整画像数据，用于「查看画像」指令"""
        with _db_lock:
            c = self.conn.cursor()
            # 用户基础信息
            c.execute("SELECT * FROM users WHERE uid=?", (uid,))
            row = c.fetchone()
            if not row:
                return None
            user_data = {
                "uid": row[0],
                "name": row[1],
                "first_seen": row[2],
                "last_active": row[3],
                "group_messages": row[4],
                "private_messages": row[5],
                "keywords": row[6] or "",
                "conversion_status": row[7] or "unknown",
            }
            # 等级积分
            c.execute("""SELECT level, points FROM user_levels WHERE uid=?""", (uid,))
            lv_row = c.fetchone()
            user_data["level"] = lv_row[0] if lv_row else 1
            user_data["points"] = lv_row[1] if lv_row else 0
            # 转化漏斗（从事件表聚合）
            c.execute("""SELECT
                COUNT(CASE WHEN event='touched'    THEN 1 END),
                COUNT(CASE WHEN event='interested' THEN 1 END),
                COUNT(CASE WHEN event='consulted'  THEN 1 END),
                COUNT(CASE WHEN event='paid'       THEN 1 END)
                FROM conversion_events WHERE uid=?""", (uid,))
            fn_row = c.fetchone()
            user_data["funnel"] = {
                "touched": fn_row[0] if fn_row else 0,
                "interested": fn_row[1] if fn_row else 0,
                "consulted": fn_row[2] if fn_row else 0,
                "paid": fn_row[3] if fn_row else 0,
            }
            # 活跃时段分析
            c.execute("SELECT last_active FROM users WHERE uid=?", (uid,))
            la_row = c.fetchone()
            if la_row and la_row[0]:
                hour = datetime.fromtimestamp(la_row[0], _CST).hour
                if 0 <= hour < 6:
                    user_data["active_time"] = "深夜活跃"
                elif 6 <= hour < 12:
                    user_data["active_time"] = "上午活跃"
                elif 12 <= hour < 18:
                    user_data["active_time"] = "下午活跃"
                else:
                    user_data["active_time"] = "晚间活跃"
            else:
                user_data["active_time"] = "未知"
            return user_data

    def get_all_user_profiles(self) -> list:
        """获取所有用户的画像数据列表，用于批量分析（优化为单次JOIN查询）"""
        with _db_lock:
            c = self.conn.cursor()
            # 【修复】：用 JOIN 一条 SQL 查出所有数据，避免 N+1 查询风暴
            c.execute("""
                SELECT u.uid, u.name, u.first_seen, u.last_active,
                       u.group_messages, u.private_messages, u.keywords, u.conversion_status,
                       COALESCE(ul.level, 1), COALESCE(ul.points, 0),
                       COALESCE(ft.touched, 0), COALESCE(ft.interested, 0),
                       COALESCE(ft.consulted, 0), COALESCE(ft.paid, 0)
                FROM users u
                LEFT JOIN user_levels ul ON u.uid = ul.uid
                LEFT JOIN (
                    SELECT uid,
                        COUNT(CASE WHEN event='touched'    THEN 1 END) AS touched,
                        COUNT(CASE WHEN event='interested' THEN 1 END) AS interested,
                        COUNT(CASE WHEN event='consulted'  THEN 1 END) AS consulted,
                        COUNT(CASE WHEN event='paid'       THEN 1 END) AS paid
                    FROM conversion_events GROUP BY uid
                ) ft ON u.uid = ft.uid
                ORDER BY u.last_active DESC
            """)
            rows = c.fetchall()
        
        profiles = []
        for r in rows:
            hour = datetime.fromtimestamp(r[3], _CST).hour if r[3] else 0
            if 0 <= hour < 6: active_time = "深夜活跃"
            elif 6 <= hour < 12: active_time = "上午活跃"
            elif 12 <= hour < 18: active_time = "下午活跃"
            else: active_time = "晚间活跃"

            profiles.append({
                "uid": r[0], "name": r[1], "first_seen": r[2], "last_active": r[3],
                "group_messages": r[4], "private_messages": r[5], "keywords": r[6] or "",
                "conversion_status": r[7] or "unknown",
                "level": r[8], "points": r[9],
                "funnel": {"touched": r[10], "interested": r[11], "consulted": r[12], "paid": r[13]},
                "active_time": active_time
            })
        return profiles

    # ─────────────────────────────── 系统动态状态 ─────────────────────────
    def get_system_state(self, key: str, default=None):
        """
        获取系统动态状态（从数据库读取，替代 config.json 中的动态字段）。
        
        Args:
            key: 状态键名
            default: 默认值（不存在时返回）
        
        Returns:
            状态值（字符串），或 default
        
        使用场景：
            - CURRENT_MODEL_INDEX: 当前使用的模型索引
            - IMAGE_POOL: 图片池缓存
            - VOICE_POOL: 语音池缓存
            - _LAST_LEAK_WEEK: 上次背刺泄密的周号
        """
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT value FROM system_states WHERE key=?", (key,))
            row = c.fetchone()
            if row:
                return row[0]
            return default

    def set_system_state(self, key: str, value):
        """
        设置系统动态状态（写入数据库，不修改 config.json）。
        
        Args:
            key: 状态键名
            value: 状态值（会自动转为字符串存储）
        """
        with _db_lock:
            ts = int(time.time())
            self.conn.execute(
                "INSERT OR REPLACE INTO system_states (key, value, updated_at) VALUES (?, ?, ?)",
                (key, str(value), ts)
            )
            self.conn.commit()
            logger.debug(f"📌 系统状态更新: {key}={value}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v4.2.3】群数据统计
    # ═══════════════════════════════════════════════════════════════════════════

    def record_group_join(self, chat_id: int = 0):
        """记录用户入群"""
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT joined_count FROM group_stats WHERE date=? AND chat_id=?", (today, chat_id))
            row = c.fetchone()
            if row:
                c.execute("UPDATE group_stats SET joined_count=joined_count+1 WHERE date=? AND chat_id=?", (today, chat_id))
            else:
                c.execute("INSERT INTO group_stats (date, joined_count, left_count, net_count, chat_id, created_at) VALUES (?,1,0,1,?,?)",
                         (today, chat_id, int(time.time())))
            self.conn.commit()

    def record_group_left(self, chat_id: int = 0):
        """记录用户离群"""
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT left_count FROM group_stats WHERE date=? AND chat_id=?", (today, chat_id))
            row = c.fetchone()
            if row:
                c.execute("UPDATE group_stats SET left_count=left_count+1, net_count=net_count-1 WHERE date=? AND chat_id=?", (today, chat_id))
            else:
                c.execute("INSERT INTO group_stats (date, joined_count, left_count, net_count, chat_id, created_at) VALUES (?,0,1,-1,?,?)",
                         (today, chat_id, int(time.time())))
            self.conn.commit()

    def update_group_total_members(self, total: int, chat_id: int = 0):
        """更新群成员总数"""
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT id FROM group_stats WHERE date=? AND chat_id=?", (today, chat_id))
            row = c.fetchone()
            if row:
                c.execute("UPDATE group_stats SET total_members=? WHERE date=? AND chat_id=?", (total, today, chat_id))
            else:
                c.execute("INSERT INTO group_stats (date, joined_count, left_count, net_count, total_members, chat_id, created_at) VALUES (?,0,0,0,?,?,?)",
                         (today, total, chat_id, int(time.time())))
            self.conn.commit()

    def get_group_stats(self, days: int = 7) -> list:
        """获取最近N天的群统计"""
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT date, joined_count, left_count, net_count, total_members
                         FROM group_stats ORDER BY date DESC LIMIT ?""", (days,))
            return c.fetchall()

    def get_group_stats_by_date(self, target_date: str = None) -> list:
        """获取指定日期的群统计"""
        if not target_date:
            target_date = datetime.now(_CST).strftime("%Y-%m-%d")
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT date, chat_id, joined_count, left_count, net_count, total_members
                         FROM group_stats WHERE date = ?""", (target_date,))
            return c.fetchall()

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v4.2.3】频道内容追踪
    # ═══════════════════════════════════════════════════════════════════════════

    def track_channel_message(self, chat_id: int, message_id: int, content_type: str = "text"):
        """记录机器人发的频道/群消息，用于追踪浏览量"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""INSERT OR IGNORE INTO channel_tracking
                         (chat_id, message_id, content_type, posted_at, initial_views, current_views, last_checked_at)
                         VALUES (?,?,?,?,0,0,?)""",
                     (chat_id, message_id, content_type, int(time.time()), int(time.time())))
            self.conn.commit()

    def update_channel_views(self, chat_id: int, message_id: int, views: int):
        """更新消息浏览量"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""UPDATE channel_tracking SET current_views=?, last_checked_at=?
                         WHERE chat_id=? AND message_id=?""",
                     (views, int(time.time()), chat_id, message_id))
            self.conn.commit()

    def get_channel_tracking(self, chat_id: int = 0, limit: int = 20) -> list:
        """获取频道内容表现数据"""
        with _db_lock:
            c = self.conn.cursor()
            if chat_id:
                c.execute("""SELECT chat_id, message_id, content_type, posted_at, current_views
                             FROM channel_tracking WHERE chat_id=? ORDER BY posted_at DESC LIMIT ?""",
                         (chat_id, limit))
            else:
                c.execute("""SELECT chat_id, message_id, content_type, posted_at, current_views
                             FROM channel_tracking ORDER BY posted_at DESC LIMIT ?""", (limit,))
            return c.fetchall()

    def get_channel_stats_summary(self) -> dict:
        """获取频道统计摘要"""
        with _db_lock:
            c = self.conn.cursor()
            # 【v4.3.2修复S-02】每次execute后立即保存fetchone结果，不重复调用
            c.execute("SELECT COUNT(*) FROM channel_tracking")
            row = c.fetchone()
            total_posts = row[0] if row else 0
            # 总浏览量
            c.execute("SELECT COALESCE(SUM(current_views),0) FROM channel_tracking")
            row = c.fetchone()
            total_views = row[0] if row else 0
            # 今日发布数
            today = datetime.now(_CST).strftime("%Y-%m-%d")
            c.execute("SELECT COUNT(*) FROM channel_tracking WHERE date(posted_at, 'unixepoch', '+8 hours')=?", (today,))
            row = c.fetchone()
            today_posts = row[0] if row else 0
            # 平均浏览量
            avg_views = total_views // max(total_posts, 1)
        return {
            "total_posts": total_posts,
            "total_views": total_views,
            "today_posts": today_posts,
            "avg_views": avg_views
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v4.5.25】日报增强查询
    # ═══════════════════════════════════════════════════════════════════════════

    def get_daily_active_users(self, date_str: str = None) -> int:
        """获取指定日期活跃用户数（last_active在当天内的用户）"""
        if not date_str:
            date_str = datetime.now(_CST).strftime("%Y-%m-%d")
        with _db_lock:
            c = self.conn.cursor()
            day_start = int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
            day_end = day_start + 86400
            c.execute("SELECT COUNT(*) FROM users WHERE last_active>=? AND last_active<?", (day_start, day_end))
            row = c.fetchone()
            return row[0] if row else 0

    def get_daily_bot_messages(self, date_str: str = None) -> int:
        """获取指定日期Bot发送的消息数（从channel_tracking表）"""
        if not date_str:
            date_str = datetime.now(_CST).strftime("%Y-%m-%d")
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT COUNT(*) FROM channel_tracking WHERE date(posted_at, 'unixepoch', '+8 hours')=?", (date_str,))
            row = c.fetchone()
            return row[0] if row else 0

    def get_daily_replies(self, date_str: str = None) -> int:
        """获取指定日期用户回复Bot消息数（从reply_tracking表）"""
        if not date_str:
            date_str = datetime.now(_CST).strftime("%Y-%m-%d")
        with _db_lock:
            c = self.conn.cursor()
            day_start = int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
            day_end = day_start + 86400
            c.execute("SELECT COUNT(*) FROM reply_tracking WHERE ts>=? AND ts<? AND replied=1", (day_start, day_end))
            row = c.fetchone()
            return row[0] if row else 0

    def get_group_total_members_latest(self, chat_id: int = 0) -> int:
        """获取群成员总数（取最近一条记录的total_members）"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT total_members FROM group_stats WHERE chat_id=? ORDER BY date DESC LIMIT 1", (chat_id,))
            row = c.fetchone()
            return row[0] if row and row[0] else 0

    def get_weekly_group_stats(self, start_date: str, end_date: str) -> dict:
        """获取指定日期范围的群统计汇总"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT COALESCE(SUM(joined_count),0), COALESCE(SUM(left_count),0),
                         COALESCE(SUM(net_count),0), AVG(total_members)
                         FROM group_stats WHERE date>=? AND date<=? AND chat_id=0""",
                     (start_date, end_date))
            row = c.fetchone()
            if row:
                return {"joined": row[0], "left": row[1], "net": row[2], "avg_members": int(row[3] or 0)}
            return {"joined": 0, "left": 0, "net": 0, "avg_members": 0}

    def get_weekly_channel_member_stats(self, chat_id: int, start_date: str, end_date: str) -> dict:
        """获取指定频道在日期范围内的成员数变化"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT MIN(total_members), MAX(total_members), AVG(total_members)
                         FROM group_stats WHERE chat_id=? AND date>=? AND date<=?""",
                     (chat_id, start_date, end_date))
            row = c.fetchone()
            if row and row[2]:
                return {"min": row[0] or 0, "max": row[1] or 0, "avg": int(row[2])}
            return {"min": 0, "max": 0, "avg": 0}

    def get_channel_posts_in_range(self, chat_id: int, start_ts: int, end_ts: int) -> dict:
        """获取频道在时间范围内的发帖和浏览量统计"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""SELECT COUNT(*), COALESCE(SUM(current_views),0)
                         FROM channel_tracking WHERE chat_id=? AND posted_at>=? AND posted_at<?""",
                     (chat_id, start_ts, end_ts))
            row = c.fetchone()
            if row:
                return {"posts": row[0], "views": row[1], "avg_views": row[1] // max(row[0], 1)}
            return {"posts": 0, "views": 0, "avg_views": 0}

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v4.3.0新增】活跃勋章系统
    # ═══════════════════════════════════════════════════════════════════════════

    def earn_badge(self, uid: int, badge_id: str) -> bool:
        """
        授予用户勋章（已拥有则忽略）
        
        Args:
            uid: 用户ID
            badge_id: 勋章ID
        
        Returns:
            True表示新获得勋章，False表示已有
        """
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT 1 FROM user_badges WHERE uid=? AND badge_id=?", (uid, badge_id))
            if c.fetchone():
                return False  # 已有
            c.execute("INSERT INTO user_badges VALUES (?,?,?)", (uid, badge_id, int(time.time())))
            self.conn.commit()
            logger.info(f"🏅 授予勋章: uid={uid} badge={badge_id}")
            return True

    def get_user_badges(self, uid: int) -> list:
        """获取用户所有勋章"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT badge_id, earned_at FROM user_badges WHERE uid=? ORDER BY earned_at DESC", (uid,))
            return c.fetchall()

    def get_all_badges_leaderboard(self, limit: int = 10) -> list:
        """获取拥有最多勋章的用户排行榜"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""
                SELECT u.uid, u.name, COUNT(b.badge_id) as badge_count
                FROM users u
                LEFT JOIN user_badges b ON u.uid = b.uid
                GROUP BY u.uid
                ORDER BY badge_count DESC
                LIMIT ?
            """, (limit,))
            return c.fetchall()

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v4.4.9新增】关键词自动回复系统
    # ═══════════════════════════════════════════════════════════════════════════

    def add_keyword_trigger(self, keyword: str, reply_text: str, reply_type: str = "static", action_type: str = ""):
        """
        添加关键词触发规则
        """
        with _db_lock:
            ts = int(time.time())
            c = self.conn.cursor()
            c.execute("""
                INSERT INTO keyword_triggers (keyword, reply_text, reply_type, action_type, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
            """, (keyword, reply_text, reply_type, action_type, ts, ts))
            self.conn.commit()
            logger.info(f"🔑 添加关键词触发: {keyword}")

    def get_all_keyword_triggers(self) -> list:
        """获取所有启用的关键词触发规则"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""
                SELECT id, keyword, reply_text, reply_type, action_type, enabled, created_at, updated_at
                FROM keyword_triggers
                WHERE enabled = 1
                ORDER BY id DESC
            """)
            rows = c.fetchall()
            return [
                {
                    "id": r[0],
                    "keyword": r[1],
                    "reply_text": r[2],
                    "reply_type": r[3],
                    "action_type": r[4],
                    "enabled": r[5],
                    "created_at": r[6],
                    "updated_at": r[7]
                }
                for r in rows
            ]

    def delete_keyword_trigger(self, trigger_id: int):
        """删除关键词触发规则"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("DELETE FROM keyword_triggers WHERE id = ?", (trigger_id,))
            self.conn.commit()
            logger.info(f"🔑 删除关键词触发: id={trigger_id}")

    def update_keyword_trigger(self, trigger_id: int, **kwargs):
        """更新关键词触发规则"""
        with _db_lock:
            ts = int(time.time())
            c = self.conn.cursor()
            allowed_fields = ["keyword", "reply_text", "reply_type", "action_type", "enabled"]
            set_clause = []
            params = []
            for field, value in kwargs.items():
                if field in allowed_fields:
                    set_clause.append(f"{field} = ?")
                    params.append(value)
            if not set_clause:
                return
            set_clause.append("updated_at = ?")
            params.extend([ts, trigger_id])
            sql = f"UPDATE keyword_triggers SET {', '.join(set_clause)} WHERE id = ?"
            c.execute(sql, params)
            self.conn.commit()
            logger.info(f"🔑 更新关键词触发: id={trigger_id}")

    def match_keyword_trigger(self, text: str) -> list:
        """
        匹配关键词触发规则（返回匹配到的所有规则，按优先级排序）
        
        Args:
            text: 用户输入的文本
            
        Returns:
            [{"id": int, "keyword": str, ...}]
        """
        text_lower = text.lower()
        all_triggers = self.get_all_keyword_triggers()
        matched = []
        for trigger in all_triggers:
            if trigger["keyword"].lower() in text_lower:
                matched.append(trigger)
        return matched

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v4.3.9】任务执行日志（持久化去重）
    # ═══════════════════════════════════════════════════════════════════════════

    def claim_task(self, task_key: str) -> bool:
        """【v4.5.32】数据库级原子抢占：跨进程防重核心防线
        纯INSERT OR IGNORE + UNIQUE索引，无SELECT（SELECT会引入竞态窗口）
        SQLite的UNIQUE约束保证跨进程原子性：后到者插入被拒绝
        返回True表示抢占成功，False表示已被抢占（同次或历史执行）"""
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        ts = time.time()
        try:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO task_log (task_key, exec_date, exec_ts) VALUES (?, ?, ?)",
                (task_key, today, ts)
            )
            self.conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            logger.warning(f"claim_task失败: {e}")
            return False

    def is_task_executed_today(self, task_key: str) -> bool:
        """查询任务今日是否已执行"""
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        with _db_lock:
            try:
                row = self.conn.execute(
                    "SELECT 1 FROM task_log WHERE task_key=? AND exec_date=? LIMIT 1",
                    (task_key, today)
                ).fetchone()
                return row is not None
            except Exception as e:
                logger.warning(f"is_task_executed_today失败: {e}")
                return False

    def cleanup_old_task_log(self, days: int = 7):
        """清理超过N天的任务执行记录"""
        cutoff = (datetime.now(_CST) - timedelta(days=days)).strftime("%Y-%m-%d")
        with _db_lock:
            try:
                cur = self.conn.execute("DELETE FROM task_log WHERE exec_date < ?", (cutoff,))
                self.conn.commit()
                if cur.rowcount > 0:
                    logger.info(f"🧹 清理{cur.rowcount}条过期task_log记录(>{days}天)")
            except Exception as e:
                logger.warning(f"cleanup_old_task_log失败: {e}")

    def cleanup_old_records(self, cutoff: int):
        """清理过期的追踪记录（线程安全）"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("DELETE FROM reply_tracking WHERE ts < ?", (cutoff,))
            deleted_track = c.rowcount
            c.execute("DELETE FROM spam_track WHERE COALESCE(window_start,0) < ?", (cutoff,))
            deleted_spam = c.rowcount
            c.execute("DELETE FROM puzzle_daily WHERE ts < ?", (cutoff,))
            deleted_puzzle = c.rowcount
            self.conn.commit()
        return deleted_track, deleted_spam, deleted_puzzle

    def get_tracking_stats(self):
        """获取追踪统计（线程安全）"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("SELECT COUNT(*) FROM reply_tracking")
            total = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM reply_tracking WHERE replied=0")
            unreplied = c.fetchone()[0]
        return total, unreplied


