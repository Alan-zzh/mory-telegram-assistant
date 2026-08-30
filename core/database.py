"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/database.py  ·  SQLite线程安全数据层（精简版）                     ║
║                                                                        ║
║  功能：                                                                ║
║    统一管理所有持久化数据。所有模块通过 main.py 创建的 db 单例访问。     ║
║    业务方法已拆分到 core/db_repos/ 下的7个Repo类。                     ║
║    通过 __getattr__ 委托实现100%向后兼容。                             ║
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

import logging
import sqlite3
from threading import RLock
from datetime import timedelta, timezone

# 【修复v21.47】统一使用北京时间，避免时区混乱导致每日重置错误
_CST = timezone(timedelta(hours=8))
from core.logging_util import get_logger

logger = get_logger("database")

# 全局互斥锁，确保并发写入安全（RLock 可重入，避免 redpacket/lucky_wheel 锁内调用 add_points 死锁）
_db_lock = RLock()


class DB:
    """
    统一数据管理器（线程安全）。
    所有模块通过单例 `db` 访问。
    业务方法已拆分到7个Repo，通过 __getattr__ 委托实现向后兼容。
    """

    def __init__(self, db_file: str):
        self.db_file = db_file
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.lock = _db_lock  # 暴露全局锁给Repo使用
        # 【修复】：开启 WAL 模式，提升多线程下 SQLite 并发性能，杜绝 Locked 报错
        self.conn.execute("PRAGMA journal_mode=WAL;")
        # 【v4.3.2修复F-07】WAL自动checkpoint，防止WAL文件无限增长
        self.conn.execute("PRAGMA wal_autocheckpoint=1000;")
        # 【TRAE SOLO CN v5.18.3审计修复】busy_timeout=30s，高并发写锁等待，杜绝 database is locked
        self.conn.execute("PRAGMA busy_timeout=30000;")
        # 【TRAE SOLO CN v5.18.3】WAL 模式下 synchronous=NORMAL 安全且更快
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        # 【v5.31.x 优化】小库（2.6MB）内存常驻 + 内存映射，降低读 IO 与 CPU 页拷贝：
        # cache_size 负值=KB，-4000 ≈ 4MB 页缓存（库全驻留）；mmap 256MB 让 SQLite 直接 mmap 文件。
        self.conn.execute("PRAGMA cache_size=-4000;")
        self.conn.execute("PRAGMA mmap_size=268435456;")
        self._init_tables()
        # 【v5.32.0 重构】移除 WriteQueueConnectionProxy 包装，回归原生 SQLite 连接。
        # WAL + busy_timeout=30s + synchronous=NORMAL 已足够应对单 VPS 群组助手的并发量。
        # 写队列的 4 层抽象（WriteQueue + DBConnectionProxy + _FakeCursor + 核心表区分）
        # 超出场景需要，且非技术维护者无法理解"非核心写被静默丢弃"的语义。
        # 【v5.41.0】write_queue 空壳兼容层及其监控消费点已全部删除；
        # 写负载观测以 task_execution_history 与 WAL checkpoint 尺寸为准。
        self._real_conn = self.conn  # 保留引用兼容（部分代码用 db._real_conn 访问真实连接）
        # 初始化8个Repo实例
        from core.db_repos import UserRepo, GroupRepo, PointsRepo, TrackingRepo, ConfigRepo, SocialRepo, QuestionRepo, RelayRepo, ABTestRepo, SalesRepo, ReplyEvolutionRepo, ConversationContextRepo, TaskExecHistoryRepo, AdEnforcementRepo
        self.users = UserRepo(self)
        self.groups = GroupRepo(self)
        self.points = PointsRepo(self)
        self.tracking = TrackingRepo(self)
        self.config = ConfigRepo(self)
        self.social = SocialRepo(self)
        self.questions = QuestionRepo(self)
        self.relay = RelayRepo(self)
        self.ab_test = ABTestRepo(self)
        self.sales = SalesRepo(self)
        self.reply_evolution = ReplyEvolutionRepo(self)
        self.conversation_context = ConversationContextRepo(self)
        self.task_exec_history = TaskExecHistoryRepo(self)
        self.ad_enforcement = AdEnforcementRepo(self)

        # 【v5.31.1 第一层防御：启动自检】扫描所有 Repo 实例的 public 方法，
        # 验证每个方法都在 _REPO_METHOD_MAP 中注册。缺失则直接启动失败，
        # 杜绝"方法漏注册→AttributeError→静默吞错→生产全灭"模式（v5.30.1/v5.30.3/v5.31.0 同坑复发 3 次）。
        self._self_check_repo_methods()

    # 【v4.3.2修复F-05】添加close()方法，确保SQLite连接正确关闭
    # 【v5.31.2 修复】移除 getattr(self, '_logger', logger)，会触发 __getattr__ 委托机制
    # 输出 CRITICAL 日志"DB 方法不存在：'_logger' 未在 _REPO_METHOD_MAP 注册"
    # 【v5.31.2 二次修复】close() 和 __del__() 用 self.__dict__.get('conn') 避免触发 __getattr__
    # 当 DB 实例被 GC 时 __dict__ 可能已被清空，self.conn 会 fallthrough 到 __getattr__ 委托机制
    def close(self):
        """关闭数据库连接，释放资源"""
        with _db_lock:
            try:
                conn = self.__dict__.get('conn')
                if conn:
                    conn.close()
                    logger.info("✅ 数据库连接已关闭")
            except Exception as e:
                logger.warning(f"数据库关闭异常：{e}")

    def __del__(self):
        """析构时自动关闭连接（安全版本：用 __dict__.get 避免触发 __getattr__ 委托机制）"""
        try:
            conn = self.__dict__.get('conn')
            if conn:
                with _db_lock:
                    conn.close()
        except Exception as e:
            try:
                logger.debug(f"操作异常: {e}")
            except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
                logging.getLogger(__name__).debug(f'非致命忽略: {_e}')

    def reconnect(self):
        """关闭后重新连接数据库（用于备份恢复后重建连接）。

        【P0-NEW-09 修复】_restore_db_from_backup 调用 close() 后必须重建连接，
        否则后续所有操作抛 ProgrammingError: Cannot operate on a closed database。

        复用 __init__ 中的连接建立、PRAGMA、建表与代理包装逻辑；
        不重新初始化 Repo（Repo 持有 self 引用，会自动使用新连接）。
        """
        with _db_lock:
            # 1. 安全关闭旧连接（可能已被 close() 关闭）
            try:
                old_conn = self.__dict__.get('conn')
                if old_conn:
                    old_conn.close()
            except Exception as e:
                logger.warning(f"reconnect 关闭旧连接异常（已忽略）: {e}")
            # 2. 重建真实连接并应用 PRAGMA（与 __init__ 保持一致）
            self.conn = sqlite3.connect(self.db_file, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA wal_autocheckpoint=1000;")
            self.conn.execute("PRAGMA busy_timeout=30000;")
            self.conn.execute("PRAGMA synchronous=NORMAL;")
            self.conn.execute("PRAGMA cache_size=-4000;")
            self.conn.execute("PRAGMA mmap_size=268435456;")
            # 3. 建表（幂等）
            self._init_tables()
            # 4. 回归原生连接（v5.32.0 移除 WriteQueueConnectionProxy）
            self._real_conn = self.conn
            logger.info("✅ 数据库连接已重建")

    # ──────────────────────────── 异常处理辅助 ──────────────────────────
    def _log_db_error(self, operation: str, error: Exception, level: str = "warning", context: str = ""):
        """
        【v4.18 统一异常处理】数据库操作异常的集中日志记录

        Args:
            operation: 操作描述（如"ALTER TABLE", "INSERT INTO points_log"）
            error: 异常对象
            level: 日志级别（"warning", "error", "critical"）
            context: 额外上下文信息（如 uid、task_name 等）
        """
        msg = f"数据库操作失败: {operation}"
        if context:
            msg += f" | {context}"
        msg += f" | 错误: {str(error)[:100]}"

        if level == "warning":
            logger.warning(msg)
        elif level == "error":
            logger.error(msg)
        elif level == "critical":
            logger.critical(msg)
            # 严重故障上报管理员
            try:
                from tasks.support.fault_reporter import report_fault
                report_fault("数据库严重错误", msg, "🚨")
            except Exception as e:
                logger.debug(f"操作异常: {e}")
        else:
            logger.warning(msg)

    # ─────────────────────────────── 初始化 ──────────────────────────────
    def _safe_add_column(self, cursor, table: str, column: str, definition: str):
        """[TRAE SOLO CN] v5.19.0 幂等添加列：用 PRAGMA 检查列存在性，避免 ALTER TABLE 重复执行报错"""
        # 注：PRAGMA/ALTER TABLE 属于 DDL，SQLite 不支持参数化表名/列名。
        # table/column/definition 由内部 _init_tables() 传入字面量，来源可信，无注入风险。
        cursor.execute(f"PRAGMA table_info({table})")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if column not in existing_cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            logger.info(f"✅ 列已添加: {table}.{column}")

    def _init_tables(self):
        """初始化全部数据表（v5.38.69 拆分为域方法；建表语句与顺序保持不变）。"""
        self._init_tables_users()
        self._init_tables_groups()
        self._init_tables_growth()
        self._init_tables_commerce()
        self._init_tables_misc()
        self._init_tables_misc_2()
        self._init_tables_misc_3()
        self._init_tables_misc_4()
        self._init_tables_misc_5()
        self._init_tables_misc_6()
        self._init_tables_misc_7()
        self._init_tables_misc_8()
        self._init_tables_misc_9()
        self._init_tables_misc_10()
        self._init_tables_misc_11()
        self._init_tables_platform_support()
        self._init_tables_performance_indexes()
        logger.info("✅ 数据库初始化完成")
    def _init_tables_users(self):
        """建表分片 1/15（逐字迁移自原 _init_tables）。"""
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

            # 购物车挽回（旧表，保留兼容）
            c.execute("""CREATE TABLE IF NOT EXISTS cart_recovery (
                uid INTEGER PRIMARY KEY,
                ts INTEGER
            )""")

            # 漏斗状态机（v5.20.0 - 4阶段转化追踪 + 乐观锁并发保护）
            c.execute("""CREATE TABLE IF NOT EXISTS funnel_state (
                uid INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'touched',
                state_ts INTEGER NOT NULL DEFAULT 0,
                version INTEGER NOT NULL DEFAULT 1,
                recovery_stage INTEGER NOT NULL DEFAULT 0,
                recovery_ts INTEGER NOT NULL DEFAULT 0,
                bot_id TEXT NOT NULL DEFAULT 'mory',
                PRIMARY KEY (uid, bot_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_funnel_state_state ON funnel_state(state)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_funnel_state_recovery ON funnel_state(state, recovery_stage, recovery_ts)")

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

            # 全局黑名单（广告封禁专用，跨群生效）
            c.execute("""CREATE TABLE IF NOT EXISTS global_blacklist (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                added_by INTEGER,
                added_at TEXT
            )""")

            # 转化漏斗（【修复v21.34】事件日志表，支持多次记录）
            c.execute("""CREATE TABLE IF NOT EXISTS conversion_events (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                uid   INTEGER,
                event TEXT,
                ts    INTEGER,
                mode  TEXT DEFAULT '',
                source TEXT DEFAULT '',
                campaign_id TEXT DEFAULT '',
                attribution_model TEXT DEFAULT '',
                weight REAL DEFAULT 0,
                is_memory_assisted INTEGER DEFAULT 0
            )""")
            self.conn.commit()
    def _init_tables_groups(self):
        """建表分片 2/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            # [TRAE SOLO CN] v5.12.3 新增：conversions 转化追踪表（AGENTS.md 商业闭环核心表）
            c.execute("""CREATE TABLE IF NOT EXISTS conversions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER,
                event TEXT,
                value REAL DEFAULT 0,
                chat_id INTEGER DEFAULT 0,
                ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conversions_uid ON conversions(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conversions_event ON conversions(event)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conversion_events_uid ON conversion_events(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conversion_events_event ON conversion_events(event)")

            # [TRAE SOLO CN] v5.12.3 补充：conversion_events 表索引（加速漏斗查询和用户维度查询）
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

            # 【v4.9.5新增】入群/离群去重日志表（用于幂等性保护）
            c.execute("""CREATE TABLE IF NOT EXISTS group_join_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                chat_id INTEGER DEFAULT 0,
                user_id INTEGER,
                ts INTEGER
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_group_join_log ON group_join_log(date, chat_id, user_id)")
            c.execute("""CREATE TABLE IF NOT EXISTS group_left_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                chat_id INTEGER DEFAULT 0,
                user_id INTEGER,
                ts INTEGER
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_group_left_log ON group_left_log(date, chat_id, user_id)")

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

            # 【v4.9.5新增】频道原生内容追踪表（追踪频道内所有消息，非仅Bot消息）
            c.execute("""CREATE TABLE IF NOT EXISTS channel_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                message_id INTEGER,
                posted_at INTEGER,
                views INTEGER DEFAULT 0,
                forwards INTEGER DEFAULT 0,
                content_type TEXT DEFAULT 'text',
                UNIQUE(chat_id, message_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_channel_posts_chat_date ON channel_posts(chat_id, posted_at)")

            # 【v4.9.6新增】频道成员快照表（用于日报/周报/月报的新增/离开计算）
            c.execute("""CREATE TABLE IF NOT EXISTS channel_member_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                member_count INTEGER,
                snapshot_date TEXT,
                created_at INTEGER,
                UNIQUE(chat_id, snapshot_date)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_channel_member_snapshot ON channel_member_snapshot(chat_id, snapshot_date)")

            # 【v4.13.1新增】验证码记录表
            c.execute("""CREATE TABLE IF NOT EXISTS verification_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                answer TEXT,
                ts INTEGER,
                verify_date TEXT,
                passed INTEGER DEFAULT 0,
                UNIQUE(chat_id, user_id, verify_date)
            )""")

            # 【v4.13.1新增】联邦封禁表
            c.execute("""CREATE TABLE IF NOT EXISTS federation_bans (
                user_id INTEGER PRIMARY KEY,
                banned_by INTEGER,
                reason TEXT,
                chat_id INTEGER,
                ts INTEGER
            )""")

            # 【v4.13.1新增】夜间模式设置表
            c.execute("""CREATE TABLE IF NOT EXISTS night_mode_settings (
                chat_id INTEGER PRIMARY KEY,
                start_hour INTEGER DEFAULT 23,
                end_hour INTEGER DEFAULT 7,
                enabled INTEGER DEFAULT 0
            )""")

            self.conn.commit()
    def _init_tables_growth(self):
        """建表分片 3/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            # 【v4.13.1新增】欢迎配置表
            c.execute("""CREATE TABLE IF NOT EXISTS welcome_configs (
                chat_id INTEGER PRIMARY KEY,
                welcome_text TEXT,
                goodbye_text TEXT,
                rules_text TEXT,
                enable_welcome INTEGER DEFAULT 1,
                enable_goodbye INTEGER DEFAULT 0,
                enable_rules INTEGER DEFAULT 0,
                clean_welcome INTEGER DEFAULT 0,
                media_file_id TEXT
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
            c.execute("CREATE INDEX IF NOT EXISTS idx_keyword_trigger_enabled ON keyword_triggers(enabled)")

            # 添加关键词索引，加速匹配
            # 【v5.12.0新增】孤儿播报追踪表（升级/早安午安晚安/定时播报等，30S或链式互删）
            # 复合主键 (chat_id, category)：每个群每个播报类型只保留最新一条
            # [Trae CN] 用于"发新消息删旧消息"互删机制和孤儿播报30S自动删除
            c.execute("""CREATE TABLE IF NOT EXISTS broadcast_tracking (
                chat_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                msg_id INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                PRIMARY KEY (chat_id, category)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_broadcast_tracking_ts ON broadcast_tracking(ts)")

            # 【v5.12.0新增】孤儿清理日志表 - 记录每次 _job_burn_orphan 执行的统计
            # [Trae CN] 用于 Dashboard /api/orphan/stats 可视化和运维审计
            c.execute("""CREATE TABLE IF NOT EXISTS orphan_cleanup_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at INTEGER NOT NULL,
                found_count INTEGER NOT NULL DEFAULT 0,
                deleted_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                error TEXT DEFAULT NULL,
                trigger TEXT DEFAULT 'scheduled'  -- scheduled / manual / force
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_orphan_cleanup_log_run_at ON orphan_cleanup_log(run_at)")

            c.execute("""CREATE TABLE IF NOT EXISTS task_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_key TEXT NOT NULL,
                exec_date TEXT NOT NULL,
                exec_ts REAL NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_task_log_key_date ON task_log(task_key, exec_date)")

            # 【v5.38.9 修复】task_execution_history 真实任务执行审计表
            # task_log 是分布式锁表,任务执行后 DELETE 释放,基于它算"成功率"必然 100% 失真。
            # 此表由 TaskTransactionManager 在 __enter__/__exit__ 写入真实状态(running/success/failed/aborted),
            # /api/health/task-success-rate 读取真实成功率。migration 0004 同步建表,此处幂等兜底。
            c.execute("""CREATE TABLE IF NOT EXISTS task_execution_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_key TEXT NOT NULL,
                exec_date TEXT NOT NULL,
                start_ts INTEGER NOT NULL,
                end_ts INTEGER,
                status TEXT NOT NULL,
                error_msg TEXT,
                duration_ms INTEGER
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_task_exec_key_date ON task_execution_history(task_key, exec_date)")

            # 私聊 /start 与群聊首次 @ 的一次性欢迎状态。仅真实送达后标记 delivered；
            # pending 由原子抢占创建，失败时释放，进程中断后可超时恢复。
            c.execute("""CREATE TABLE IF NOT EXISTS onboarding_deliveries (
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                surface TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                claimed_at INTEGER NOT NULL,
                delivered_at INTEGER,
                PRIMARY KEY (uid, chat_id, surface)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_onboarding_status ON onboarding_deliveries(status, claimed_at)")

            # [v5.14.0新增] 商业搭讪事件表 - 记录 Bot 主动搭讪用户的完整链路
            # 用于 Dashboard /api/engage/* 可视化、转化追踪、运营复盘
            c.execute("""CREATE TABLE IF NOT EXISTS proactive_engage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                uname TEXT NOT NULL DEFAULT '',
                msg TEXT NOT NULL DEFAULT '',
                matched_keyword TEXT NOT NULL DEFAULT '',
                reply_text TEXT NOT NULL DEFAULT '',
                ts INTEGER NOT NULL,
                converted INTEGER NOT NULL DEFAULT 0
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_proactive_engage_log_uid ON proactive_engage_log(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_proactive_engage_log_ts ON proactive_engage_log(ts)")

            try:
                c.execute("""DELETE FROM task_log WHERE id NOT IN (
                    SELECT MIN(id) FROM task_log GROUP BY task_key, exec_date
                )""")
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_task_log_unique ON task_log(task_key, exec_date)")
            except Exception as e:
                # [v5.31.2 P0-2 加固] 索引创建失败会导致 claim_task 防重机制失效，不能静默吞掉
                logger.error(f"🚨 task_log UNIQUE 索引创建失败，防重机制可能失效: {e}")
                try:
                    from tasks.support.fault_reporter import report_fault
                    report_fault("task_log 索引异常", f"UNIQUE 索引创建失败: {e}", "🚨")
                except Exception as report_error:
                    logger.debug(f"task_log 索引异常上报失败: {report_error}")

            # 【v4.5.31】防连发：清理重复记录 + 添加UNIQUE约束
            c.execute("""CREATE TABLE IF NOT EXISTS reply_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_msg_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                feedback TEXT NOT NULL,
                ts INTEGER NOT NULL,
                UNIQUE(bot_msg_id, chat_id, user_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_reply_feedback_ts ON reply_feedback(ts)")

            # ── 【v4.14新增】签到/商城/红包/抽奖/认证/标签/统计表 ──────
            c.execute("""CREATE TABLE IF NOT EXISTS checkin_records (
                uid INTEGER NOT NULL,
                date TEXT NOT NULL,
                continuous_days INTEGER DEFAULT 1,
                current_streak INTEGER DEFAULT 0,
                points_earned INTEGER DEFAULT 0,
                ts INTEGER NOT NULL,
                UNIQUE(uid, date)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_checkin_uid ON checkin_records(uid)")

            c.execute("""CREATE TABLE IF NOT EXISTS invite_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inviter_uid INTEGER NOT NULL,
                invitee_uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_invite_inviter ON invite_records(inviter_uid)")

            self.conn.commit()
    def _init_tables_commerce(self):
        """建表分片 4/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS coupon_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'points',
                value INTEGER NOT NULL DEFAULT 0,
                days INTEGER NOT NULL DEFAULT 0,
                expires_at INTEGER NOT NULL DEFAULT 0,
                claimed_by INTEGER DEFAULT 0,
                claimed_at INTEGER DEFAULT 0,
                used_at INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL,
                UNIQUE(code)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_coupon_code ON coupon_claims(code)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_coupon_claimed_by ON coupon_claims(claimed_by)")

            c.execute("""CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                points_cost INTEGER NOT NULL,
                stock INTEGER DEFAULT -1,
                description TEXT DEFAULT '',
                category TEXT DEFAULT 'default',
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS exchange_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                item_name TEXT DEFAULT '',
                points_cost INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                status TEXT DEFAULT 'pending'
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_exchange_uid ON exchange_records(uid)")

            c.execute("""CREATE TABLE IF NOT EXISTS redpackets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                total_points INTEGER NOT NULL,
                count INTEGER NOT NULL,
                remaining INTEGER NOT NULL,
                mode TEXT DEFAULT 'random',
                msg_id INTEGER DEFAULT 0,
                expired INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS redpacket_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                redpacket_id INTEGER NOT NULL,
                uid INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                UNIQUE(redpacket_id, uid)
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS lotteries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                prize TEXT NOT NULL,
                prize_count INTEGER DEFAULT 1,
                duration_min INTEGER DEFAULT 60,
                end_ts INTEGER NOT NULL,
                msg_id INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS lottery_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lottery_id INTEGER NOT NULL,
                uid INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                UNIQUE(lottery_id, uid)
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS certified_users (
                uid INTEGER PRIMARY KEY,
                certified_by INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS user_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                tag TEXT NOT NULL,
                added_by INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                UNIQUE(uid, tag)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_usertags_uid ON user_tags(uid)")

            c.execute("""CREATE TABLE IF NOT EXISTS user_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                note TEXT NOT NULL,
                added_by INTEGER NOT NULL,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_usernotes_uid ON user_notes(uid)")

            c.execute("""CREATE TABLE IF NOT EXISTS speech_daily (
                uid INTEGER NOT NULL,
                date TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (uid, date, chat_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_speech_uid_date ON speech_daily(uid, date)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_speech_date_chat ON speech_daily(date, chat_id)")

            # ── 【v4.15新增】积分增强/AFK/任务/成就/盲盒/转盘表 ──────
            # 【v4.17.0新增】日报按日期+群组查询的复合索引
            c.execute("""CREATE TABLE IF NOT EXISTS points_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                change_amount INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                source TEXT NOT NULL,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_points_log_uid ON points_log(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_points_log_uid_ts ON points_log(uid, ts)")

            self.conn.commit()
    def _init_tables_misc(self):
        """建表分片 5/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS afk_status (
                uid INTEGER PRIMARY KEY,
                reason TEXT DEFAULT '',
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS daily_quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                date TEXT NOT NULL,
                quest_type TEXT NOT NULL,
                completed INTEGER DEFAULT 0,
                ts INTEGER NOT NULL,
                UNIQUE(uid, date, quest_type)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_daily_quests_uid_date ON daily_quests(uid, date)")

            c.execute("""CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                achievement_id TEXT NOT NULL,
                earned_at INTEGER NOT NULL,
                UNIQUE(uid, achievement_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_achievements_uid ON achievements(uid)")

            c.execute("""CREATE TABLE IF NOT EXISTS blind_box_prizes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                probability REAL NOT NULL DEFAULT 1.0,
                prize_type TEXT NOT NULL DEFAULT 'points',
                value INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS lucky_wheel_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                date TEXT NOT NULL,
                reward INTEGER NOT NULL DEFAULT 0,
                spin_count INTEGER NOT NULL DEFAULT 1,
                ts INTEGER NOT NULL,
                UNIQUE(uid, date)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_lucky_wheel_uid_date ON lucky_wheel_results(uid, date)")
            self._safe_add_column(c, "lucky_wheel_results", "spin_count", "INTEGER NOT NULL DEFAULT 1")

            # ── 【v4.16新增】高级群管功能表 ──────
            # 兼容旧表：幂等添加 spin_count 列（避免 duplicate column 反复报错）
            c.execute("""CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                warned_by INTEGER NOT NULL,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_warnings_uid_chat ON warnings(uid, chat_id)")

            c.execute("""CREATE TABLE IF NOT EXISTS message_locks (
                chat_id INTEGER NOT NULL,
                lock_type TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL,
                PRIMARY KEY (chat_id, lock_type)
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS group_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                note_name TEXT NOT NULL,
                content TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                UNIQUE(chat_id, note_name)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_group_notes_chat ON group_notes(chat_id)")

            c.execute("""CREATE TABLE IF NOT EXISTS custom_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                cmd_name TEXT NOT NULL,
                response TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                UNIQUE(chat_id, cmd_name)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_custom_cmds_chat ON custom_commands(chat_id)")

            c.execute("""CREATE TABLE IF NOT EXISTS scheduled_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                send_time TEXT NOT NULL,
                content TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                enabled INTEGER DEFAULT 1
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_chat ON scheduled_messages(chat_id)")

            c.execute("""CREATE TABLE IF NOT EXISTS vote_kicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                target_uid INTEGER NOT NULL,
                initiator_id INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                yes_votes TEXT DEFAULT '',
                no_votes TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                msg_id INTEGER DEFAULT 0,
                end_ts INTEGER NOT NULL,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_vote_kicks_chat ON vote_kicks(chat_id)")

            # ── 【v4.17新增】主流Bot功能补齐表 ──────
            c.execute("""CREATE TABLE IF NOT EXISTS clean_service_settings (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            self.conn.commit()
    def _init_tables_misc_2(self):
        """建表分片 6/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS disabled_commands (
                chat_id INTEGER NOT NULL,
                cmd_name TEXT NOT NULL,
                ts INTEGER NOT NULL,
                PRIMARY KEY (chat_id, cmd_name)
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                operator_uid INTEGER NOT NULL,
                target_uid INTEGER DEFAULT 0,
                action TEXT NOT NULL,
                reason TEXT DEFAULT '',
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_admin_logs_chat ON admin_logs(chat_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_admin_logs_ts ON admin_logs(ts)")

            c.execute("""CREATE TABLE IF NOT EXISTS deleted_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                uid INTEGER NOT NULL,
                content TEXT DEFAULT '',
                content_type TEXT DEFAULT 'text',
                msg_id INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_deleted_msgs_chat ON deleted_messages(chat_id)")

            # [TRAE SOLO CN] v5.15.3 新增：消息追踪表 message_snapshots（AGENTS.md 教训 #17 落实）
            # Bot API 无法枚举群历史消息，删除历史消息必须依赖此表的 msg_id 记录
            # 之前 v5.15.2 P1 拦截只 return True 静默吞了，没记 msg_id → 18:36 教白嫖消息删不掉
            c.execute("""CREATE TABLE IF NOT EXISTS message_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                msg_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                text TEXT DEFAULT '',
                ts INTEGER NOT NULL,
                is_ad INTEGER DEFAULT 0,
                deleted INTEGER DEFAULT 0,
                auto_delete_due_at INTEGER DEFAULT 0,
                auto_delete_status TEXT DEFAULT '',
                auto_delete_keyword TEXT DEFAULT '',
                auto_delete_attempts INTEGER DEFAULT 0,
                auto_delete_error TEXT DEFAULT '',
                UNIQUE(chat_id, msg_id)
            )""")
            self._safe_add_column(c, "message_snapshots", "auto_delete_due_at", "INTEGER DEFAULT 0")
            self._safe_add_column(c, "message_snapshots", "auto_delete_status", "TEXT DEFAULT ''")
            self._safe_add_column(c, "message_snapshots", "auto_delete_keyword", "TEXT DEFAULT ''")
            self._safe_add_column(c, "message_snapshots", "auto_delete_attempts", "INTEGER DEFAULT 0")
            self._safe_add_column(c, "message_snapshots", "auto_delete_error", "TEXT DEFAULT ''")
            c.execute("CREATE INDEX IF NOT EXISTS idx_msg_snapshots_chat_ts ON message_snapshots(chat_id, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_msg_snapshots_user ON message_snapshots(user_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_msg_snapshots_ad ON message_snapshots(is_ad, deleted)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_msg_snapshots_auto_delete ON message_snapshots(auto_delete_status, auto_delete_due_at)")

            c.execute("""CREATE TABLE IF NOT EXISTS connected_chats (
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                PRIMARY KEY (uid)
            )""")

            # ── 【v4.18新增】主流Bot完整功能补齐表 ──────
            c.execute("""CREATE TABLE IF NOT EXISTS antiflood_settings (
                chat_id INTEGER PRIMARY KEY,
                window INTEGER DEFAULT 5,
                threshold INTEGER DEFAULT 5,
                mute_duration INTEGER DEFAULT 60,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS approved_users (
                chat_id INTEGER NOT NULL,
                uid INTEGER NOT NULL,
                approved_by INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                PRIMARY KEY (chat_id, uid)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_approved_chat ON approved_users(chat_id)")

            c.execute("""CREATE TABLE IF NOT EXISTS blocklist_modes (
                chat_id INTEGER PRIMARY KEY,
                mode TEXT DEFAULT 'delete',
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS force_subscribe (
                chat_id INTEGER PRIMARY KEY,
                channel_username TEXT DEFAULT '',
                channel_id INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                trigger_ts INTEGER NOT NULL,
                content TEXT DEFAULT '',
                sent INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_reminders_uid ON reminders(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_reminders_trigger ON reminders(trigger_ts)")

            c.execute("""CREATE TABLE IF NOT EXISTS anti_channel_settings (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS nsfw_settings (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                threshold REAL DEFAULT 0.7,
                ts INTEGER NOT NULL
            )""")

            # ── 【v5.0.0设置面板完全体新增】配置表补齐 ──────
            self.conn.commit()
    def _init_tables_misc_3(self):
        """建表分片 7/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            # 警告设置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS warning_settings (
                chat_id INTEGER PRIMARY KEY,
                warn_limit INTEGER DEFAULT 3,
                warn_action TEXT DEFAULT 'mute',
                warn_duration INTEGER DEFAULT 3600,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 慢速模式（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS slow_mode_config (
                chat_id INTEGER PRIMARY KEY,
                interval INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # 举报配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS report_settings (
                chat_id INTEGER PRIMARY KEY,
                cooldown INTEGER DEFAULT 300,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 投票踢人配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS votekick_config (
                chat_id INTEGER PRIMARY KEY,
                min_yes INTEGER DEFAULT 5,
                min_ratio REAL DEFAULT 0.6,
                duration INTEGER DEFAULT 300,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 反突袭配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS anti_raid_config (
                chat_id INTEGER PRIMARY KEY,
                threshold INTEGER DEFAULT 5,
                window INTEGER DEFAULT 60,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # 盲盒配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS blind_box_config (
                chat_id INTEGER PRIMARY KEY,
                cost INTEGER DEFAULT 50,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # 转盘配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS lucky_wheel_config (
                chat_id INTEGER PRIMARY KEY,
                cost INTEGER DEFAULT 30,
                free_spins INTEGER DEFAULT 1,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # 红包配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS redpacket_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                min_amount INTEGER DEFAULT 1,
                max_amount INTEGER DEFAULT 100,
                ts INTEGER NOT NULL
            )""")

            # 抽奖配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS lottery_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 签到配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS checkin_config (
                chat_id INTEGER PRIMARY KEY,
                base_points INTEGER DEFAULT 5,
                streak_bonus TEXT DEFAULT '{"3":5,"7":15}',
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 商城配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS shop_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 优惠券配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS coupon_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            self.conn.commit()
    def _init_tables_misc_4(self):
        """建表分片 8/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            # 打赏配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS tip_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                min_amount INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 每日任务配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS daily_quest_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # 成就配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS achievement_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # 积分衰减配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS points_decay_config (
                chat_id INTEGER PRIMARY KEY,
                rate REAL DEFAULT 0.01,
                minimum INTEGER DEFAULT 10,
                enabled INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")

            # AFK配置（按群）
            c.execute("""CREATE TABLE IF NOT EXISTS afk_config (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                ts INTEGER NOT NULL
            )""")

            # 【v5.0.0新增】广告检测追踪表（持久化可疑用户评分）
            c.execute("""CREATE TABLE IF NOT EXISTS ad_suspicious_users (
                user_id INTEGER PRIMARY KEY,
                score INTEGER DEFAULT 0,
                first_seen TEXT,
                messages TEXT DEFAULT '[]',
                updated_at INTEGER
            )""")

            # 广告处置根因、说明卡和自助复检账本；不保存完整 Bio/私聊原文。
            c.execute("""CREATE TABLE IF NOT EXISTS ad_enforcement_events (
                event_id TEXT PRIMARY KEY,
                root_event_id TEXT NOT NULL,
                parent_event_id TEXT DEFAULT '',
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                source_message_id INTEGER DEFAULT 0,
                source_type TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                reason_summary TEXT NOT NULL,
                evidence_level TEXT NOT NULL,
                evidence_json TEXT DEFAULT '[]',
                enforcement_status TEXT DEFAULT 'pending',
                muted INTEGER DEFAULT 0,
                blacklisted INTEGER DEFAULT 0,
                deleted_count INTEGER DEFAULT 0,
                notice_message_id INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                attempt_count INTEGER DEFAULT 0,
                last_attempt_at INTEGER DEFAULT 0,
                resolved_at INTEGER DEFAULT 0,
                resolution TEXT DEFAULT '',
                recovery_json TEXT DEFAULT '{}'
            )""")
            c.execute("""CREATE INDEX IF NOT EXISTS idx_ad_events_user_open
                         ON ad_enforcement_events(user_id, resolved_at, expires_at)""")
            c.execute("""CREATE INDEX IF NOT EXISTS idx_ad_events_notice
                         ON ad_enforcement_events(user_id, chat_id, root_event_id, notice_message_id)""")

            # [TRAE SOLO CN] v5.8.1 新增：群成员追踪表（渐进式构建完整成员列表）
            c.execute("""CREATE TABLE IF NOT EXISTS group_members (
                uid INTEGER,
                chat_id INTEGER,
                username TEXT DEFAULT '',
                display_name TEXT DEFAULT '',
                bio TEXT DEFAULT '',
                status TEXT DEFAULT 'member',
                first_seen INTEGER,
                last_checked INTEGER,
                PRIMARY KEY (uid, chat_id)
            )""")

            # ── 兼容性迁移：旧数据库缺少的列自动补齐 ──────────────────
            try:
                self.conn.execute("SELECT replied FROM reply_tracking LIMIT 0")
            except Exception as e:
                self._log_db_error("SELECT replied FROM reply_tracking", e, "warning", "检查列是否存在")
                self.conn.execute("ALTER TABLE reply_tracking ADD COLUMN replied INTEGER DEFAULT 0")
                logger.info("🔄 数据库迁移：reply_tracking 补充 replied 列")

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
            except Exception as e:
                self._log_db_error("SELECT conversion_status FROM users", e, "warning", "检查列是否存在")
                self.conn.execute("ALTER TABLE users ADD COLUMN conversion_status TEXT DEFAULT 'unknown'")
                logger.info("🔄 数据库迁移：users 补充 conversion_status 列")

            try:
                c.execute("SELECT chat_id FROM group_stats LIMIT 1")
            except Exception as e:
                self._log_db_error("SELECT chat_id FROM group_stats", e, "warning", "检查列是否存在")
                c.execute("ALTER TABLE group_stats ADD COLUMN chat_id INTEGER DEFAULT 0")
                logger.info("✅ group_stats表已添加chat_id列")

            self._safe_add_column(c, "checkin_records", "current_streak", "INTEGER DEFAULT 0")

            # ── [v5.15.0新增] 问题追踪与FAQ蒸馏表 ──────
            # 【修复v21.33】reply_tracking 单主键 → 复合主键迁移
            # checkin_records 补充 current_streak 列
            # 用户问题记录表（记录每条用户提问，用于FAQ蒸馏和问题分析）
            c.execute("""CREATE TABLE IF NOT EXISTS user_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                question_text TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT '',
                intent TEXT NOT NULL DEFAULT '',
                keyword_tag TEXT NOT NULL DEFAULT '',
                question_category TEXT NOT NULL DEFAULT 'other',
                is_convert INTEGER NOT NULL DEFAULT 0,
                ai_reply_summary TEXT NOT NULL DEFAULT '',
                faq_hit_id INTEGER DEFAULT 0,
                answer_source TEXT NOT NULL DEFAULT '',
                answer_ref TEXT NOT NULL DEFAULT '',
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_questions_uid ON user_questions(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_questions_ts ON user_questions(ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_questions_category ON user_questions(question_category)")

            # FAQ知识库表（审核通过的FAQ条目，用于智能匹配回复）
            c.execute("""CREATE TABLE IF NOT EXISTS faq_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_pattern TEXT NOT NULL DEFAULT '',
                question_category TEXT NOT NULL DEFAULT 'other',
                answer_template TEXT NOT NULL DEFAULT '',
                ai_polish INTEGER NOT NULL DEFAULT 1,
                match_mode TEXT NOT NULL DEFAULT 'keyword',
                priority INTEGER NOT NULL DEFAULT 0,
                hit_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'approved',
                created_by TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_faq_knowledge_category ON faq_knowledge(question_category)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_faq_knowledge_status ON faq_knowledge(status)")

            # FAQ候选表（高频问题自动蒸馏生成，待人工审核）
            c.execute("""CREATE TABLE IF NOT EXISTS faq_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_pattern TEXT NOT NULL DEFAULT '',
                question_category TEXT NOT NULL DEFAULT 'other',
                sample_questions TEXT NOT NULL DEFAULT '',
                frequency INTEGER NOT NULL DEFAULT 0,
                mode TEXT NOT NULL DEFAULT '',
                intent TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                reviewed_by TEXT NOT NULL DEFAULT '',
                reviewed_at INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_faq_candidates_status ON faq_candidates(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_faq_candidates_category ON faq_candidates(question_category)")

            # 中继会话追踪（双向通信：管理员回复转发消息时查找原始用户）
            c.execute("""CREATE TABLE IF NOT EXISTS relay_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_chat_id INTEGER,
                admin_msg_id INTEGER,
                user_id INTEGER,
                user_chat_id INTEGER,
                source_type TEXT DEFAULT 'private',
                ts INTEGER DEFAULT 0
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_relay_admin_msg ON relay_sessions(admin_chat_id, admin_msg_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_relay_ts ON relay_sessions(ts)")

            self.conn.commit()
    def _init_tables_misc_5(self):
        """建表分片 9/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            # 用户画像表（Telegram API 2026 适配 - 支持个性化播报）
            c.execute("""CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                tags TEXT DEFAULT '[]',
                level INTEGER DEFAULT 0,
                interests TEXT DEFAULT '[]',
                last_interaction TIMESTAMP,
                conversation_rounds INTEGER DEFAULT 0,
                memory_summary TEXT DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_profiles_level ON user_profiles(level)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_profiles_tags ON user_profiles(tags)")

            # 按钮样式表（Telegram API 2026 适配 - 彩色按钮配置）
            c.execute("""CREATE TABLE IF NOT EXISTS button_styles (
                button_id TEXT PRIMARY KEY,
                style TEXT DEFAULT 'default',
                icon_custom_emoji_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")

            # A/B 测试统计表（v5.18.0 - HTML vs Rich Message 转化率对比）
            c.execute("""CREATE TABLE IF NOT EXISTS ab_test_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                format_version TEXT NOT NULL,
                sent_count INTEGER DEFAULT 0,
                conversion_count INTEGER DEFAULT 0,
                ts INTEGER DEFAULT 0,
                UNIQUE(group_name, format_version)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_ab_test_group ON ab_test_stats(group_name, format_version)")
            self._normalize_ab_test_stats(c)
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_ab_test_stats_group_format ON ab_test_stats(group_name, format_version)")

            # 按钮点击统计表（v5.18.0 - 追踪不同样式按钮点击率）
            c.execute("""CREATE TABLE IF NOT EXISTS button_click_stats (
                button_id TEXT NOT NULL,
                style TEXT DEFAULT 'default',
                impressions INTEGER DEFAULT 0,
                clicks INTEGER DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (button_id, style)
            )""")

            # [TRAE SOLO CN] 追溯扫描日志表（用于冷却机制）
            c.execute("""CREATE TABLE IF NOT EXISTS retroactive_scan_log (
                ts REAL NOT NULL,
                scanned INTEGER DEFAULT 0,
                ads_found INTEGER DEFAULT 0,
                deleted INTEGER DEFAULT 0
            )""")

            self._safe_add_column(c, "user_profiles", "activity_score", "REAL DEFAULT 0.0")
            self._safe_add_column(c, "user_profiles", "flirt_affinity", "REAL DEFAULT 0.0")
            self._safe_add_column(c, "user_profiles", "spend_tendency", "REAL DEFAULT 0.0")
            self._safe_add_column(c, "user_profiles", "resistance_idx", "REAL DEFAULT 0.5")
            self._safe_add_column(c, "user_profiles", "peak_hours", "TEXT DEFAULT '[]'")
            self._safe_add_column(c, "user_profiles", "persona_tags", "TEXT DEFAULT '[]'")

            self._safe_add_column(c, "user_profiles", "lifecycle_stage", "TEXT DEFAULT 'New'")

            self._safe_add_column(c, "user_profiles", "conv_turn_count", "INTEGER DEFAULT 0")
            self._safe_add_column(c, "user_profiles", "conv_last_active", "TIMESTAMP")
            self._safe_add_column(c, "user_profiles", "memory_summary", "TEXT DEFAULT ''")
            self._safe_add_column(c, "user_profiles", "version", "INTEGER NOT NULL DEFAULT 1")

            # ── [TRAE SOLO CN] v5.19.0 A/B 测试与 Telemetry 表 ──────
            # [TRAE SOLO CN] v5.19.0 新增：user_profiles 扩展 6 列（动态画像标签系统）
            # ALTER TABLE ADD COLUMN 不支持 IF NOT EXISTS，用 PRAGMA 检查列存在性实现幂等
            # [v5.26.0] 用户生命周期阶段标签（New/Active/Silent/Churning/Lost）
            # [v5.33] 对话轮次持久化（递进引导重启不重置）
            # 注：SQLite 不允许 ALTER TABLE ADD COLUMN 带 CURRENT_TIMESTAMP 非常量默认值，
            # 改为允许 NULL，由 update_conversation_turn() 在 UPDATE 时显式赋值。
            c.execute("""CREATE TABLE IF NOT EXISTS ab_experiments (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                description TEXT DEFAULT '',
                variant_a_name TEXT DEFAULT 'A',
                variant_b_name TEXT DEFAULT 'B',
                variant_a_config TEXT DEFAULT '{}',
                variant_b_config TEXT DEFAULT '{}',
                traffic_split INTEGER DEFAULT 50,
                scope TEXT DEFAULT 'private',
                status TEXT DEFAULT 'running',
                start_time INTEGER DEFAULT 0,
                end_time INTEGER DEFAULT 0,
                rolled_back_at INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT 0
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS ab_user_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                chat_id INTEGER DEFAULT 0,
                variant TEXT NOT NULL DEFAULT 'A',
                assigned_at INTEGER DEFAULT 0,
                UNIQUE(experiment_id, user_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_ab_assign_exp_user ON ab_user_assignments(experiment_id, user_id)")

            c.execute("""CREATE TABLE IF NOT EXISTS telemetry_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER DEFAULT 0,
                experiment_id TEXT DEFAULT '',
                variant TEXT DEFAULT '',
                event_type TEXT NOT NULL,
                event_value REAL DEFAULT 0,
                event_meta TEXT DEFAULT '{}',
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_exp ON telemetry_events(experiment_id, variant, event_type, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_user ON telemetry_events(user_id, ts)")

            c.execute("""CREATE TABLE IF NOT EXISTS conversation_telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER DEFAULT 0,
                experiment_id TEXT DEFAULT '',
                variant TEXT DEFAULT '',
                message_text TEXT DEFAULT '',
                bot_reply_text TEXT DEFAULT '',
                intent TEXT DEFAULT '',
                sentiment TEXT DEFAULT '',
                round_num INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_conv_telemetry_exp ON conversation_telemetry(experiment_id, variant, ts)")

            # 独立于增长遥测：短期承接文本 + 结构化 CTA/拒绝状态。
            # raw_event_text=false 时仍可跨重启承接，但不会把原文写入 telemetry。
            c.execute("""CREATE TABLE IF NOT EXISTS business_conversation_context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                user_text TEXT NOT NULL DEFAULT '',
                assistant_text TEXT NOT NULL DEFAULT '',
                intent TEXT NOT NULL DEFAULT '',
                conversion_target TEXT NOT NULL DEFAULT 'none',
                conversion_reason TEXT NOT NULL DEFAULT '',
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_business_context_recent ON business_conversation_context(user_id, chat_id, ts)")
            c.execute("""CREATE TABLE IF NOT EXISTS conversation_conversion_state (
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                opt_out_until INTEGER NOT NULL DEFAULT 0,
                custom_context_until INTEGER NOT NULL DEFAULT 0,
                preview_context_until INTEGER NOT NULL DEFAULT 0,
                recent_cta_target TEXT NOT NULL DEFAULT '',
                recent_cta_at INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(user_id, chat_id)
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS weekly_ab_report (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT NOT NULL,
                experiment_id TEXT NOT NULL,
                variant_a_ctr REAL DEFAULT 0,
                variant_b_ctr REAL DEFAULT 0,
                variant_a_conversion REAL DEFAULT 0,
                variant_b_conversion REAL DEFAULT 0,
                top_positive_features TEXT DEFAULT '[]',
                top_negative_features TEXT DEFAULT '[]',
                recommendation TEXT DEFAULT '',
                generated_at INTEGER DEFAULT 0,
                UNIQUE(week_start, experiment_id)
            )""")

            self.conn.commit()
    def _init_tables_misc_6(self):
        """建表分片 10/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS ab_guardian_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                alert_reason TEXT DEFAULT '',
                threshold_value REAL DEFAULT 0,
                actual_value REAL DEFAULT 0,
                action_taken TEXT DEFAULT '',
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_guardian_exp ON ab_guardian_log(experiment_id, ts)")

            # ── [阶段2-C] 多模型路由 A/B 测试指标表 ──────────────────
            # 记录每次 AI 调用的延迟/成本/转化，按 group 聚合分析模型效能
            c.execute("""CREATE TABLE IF NOT EXISTS ab_test_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL DEFAULT 0,
                group_name TEXT NOT NULL DEFAULT '',
                model TEXT DEFAULT '',
                latency_ms REAL DEFAULT 0,
                cost REAL DEFAULT 0,
                converted INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_ab_metrics_group ON ab_test_metrics(group_name, model, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_ab_metrics_ts ON ab_test_metrics(ts)")

            # ── [v5.26.0] 内容质量评估表（LLM-as-a-Judge）──────────
            # 存储 LLM 评估的对话质量评分（自然度/相关性/人格一致性）
            c.execute("""CREATE TABLE IF NOT EXISTS interaction_quality_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                naturalness_score INTEGER NOT NULL CHECK(naturalness_score BETWEEN 1 AND 5),
                relevance_score INTEGER NOT NULL CHECK(relevance_score BETWEEN 1 AND 5),
                persona_score INTEGER NOT NULL CHECK(persona_score BETWEEN 1 AND 5),
                evaluated_at INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                UNIQUE(conversation_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_quality_scores_evaluated_at ON interaction_quality_scores(evaluated_at)")

            # 人工审核的风格样本：不保存原始用户事件，也绝不自动改写提示词。
            # [Agent G] 增加 scene 分组列：chat/greeting/engage/faq/broadcast
            c.execute("""CREATE TABLE IF NOT EXISTS reply_style_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL DEFAULT '',
                style_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
                enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
                created_by TEXT NOT NULL DEFAULT '',
                reviewed_by TEXT NOT NULL DEFAULT '',
                review_note TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                reviewed_at INTEGER NOT NULL DEFAULT 0,
                scene TEXT NOT NULL DEFAULT 'chat'
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_reply_style_samples_active ON reply_style_samples(status, enabled, reviewed_at)")
            self._safe_add_column(c, "reply_style_samples", "scene", "TEXT NOT NULL DEFAULT 'chat'")
            c.execute("CREATE INDEX IF NOT EXISTS idx_reply_style_samples_scene ON reply_style_samples(scene)")

            # ── [阶段3-E] RBAC 权限变更审批流表 ──────────────────
            # [Agent G] 兼容旧库：已存在的表缺 scene 列时幂等补列（配合 0005 迁移）
            # 记录每次权限变更申请的完整生命周期：申请/审批/拒绝/取消
            # 审批通过后由 dashboard/rbac_approval.py 同步更新 user_roles 表
            c.execute("""CREATE TABLE IF NOT EXISTS permission_change_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requester_id INTEGER NOT NULL,
                target_user_id INTEGER NOT NULL,
                requested_role TEXT NOT NULL,
                reason TEXT,
                status TEXT DEFAULT 'pending',
                approver_id INTEGER,
                approved_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_perm_req_status ON permission_change_requests(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_perm_req_target ON permission_change_requests(target_user_id)")

            # ── [v5.24.0 阶段3-C] 多 Bot 任务分工编排路由表 ──────────────
            # 静态路由表：决定哪个 Bot 负责哪个群组的哪些模块
            # allowed_modules 为 JSON 数组，如 ["group_chat","scheduled_broadcast","direct_sales"]
            # 详见 core/bot_routing.py
            c.execute("""CREATE TABLE IF NOT EXISTS bot_group_routing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                allowed_modules TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bot_id, chat_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_bot_routing_chat ON bot_group_routing(chat_id, is_active)")

            # ── [v5.34.0] 销售中心表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS sales_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sku TEXT DEFAULT '',
                category TEXT DEFAULT 'default',
                price REAL NOT NULL DEFAULT 0,
                description TEXT DEFAULT '',
                stock INTEGER DEFAULT -1,
                sort_order INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON sales_products(category, is_active)")

            c.execute("""CREATE TABLE IF NOT EXISTS sales_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT NOT NULL UNIQUE,
                uid INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                status TEXT DEFAULT 'pending',
                chat_id INTEGER DEFAULT 0,
                source TEXT DEFAULT 'group',
                referrer_uid INTEGER DEFAULT 0,
                note TEXT DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_orders_uid ON sales_orders(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON sales_orders(status, created_at)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON sales_orders(created_at)")

            c.execute("""CREATE TABLE IF NOT EXISTS sales_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                event TEXT NOT NULL,
                chat_id INTEGER DEFAULT 0,
                product_id INTEGER DEFAULT 0,
                value REAL DEFAULT 0,
                note TEXT DEFAULT '',
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sales_events_uid ON sales_events(uid, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sales_events_event ON sales_events(event, ts)")

            c.execute("""CREATE TABLE IF NOT EXISTS sales_commissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_uid INTEGER NOT NULL,
                order_id INTEGER NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                rate REAL DEFAULT 0.1,
                status TEXT DEFAULT 'pending',
                created_at INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_commissions_referrer ON sales_commissions(referrer_uid)")

            # ── [v5.34.0] 安全中心表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS user_risk_profile (
                uid INTEGER PRIMARY KEY,
                risk_score INTEGER DEFAULT 0,
                risk_factors TEXT DEFAULT '{}',
                risk_updated_at INTEGER DEFAULT 0
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                chat_id INTEGER DEFAULT 0,
                risk_score INTEGER DEFAULT 0,
                action TEXT DEFAULT '',
                detail TEXT DEFAULT '',
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sec_events_uid ON security_events(uid, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sec_events_type ON security_events(event_type, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sec_events_ts ON security_events(ts)")

            # ── [v5.34.0] 托管管理表 ─────────────────────────────
            self.conn.commit()
    def _init_tables_misc_7(self):
        """建表分片 11/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS managed_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL UNIQUE,
                group_name TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                plan TEXT DEFAULT 'basic',
                status TEXT DEFAULT 'active',
                expire_at INTEGER DEFAULT 0,
                contact TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_mg_customer ON managed_groups(customer_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_mg_status ON managed_groups(status)")

            c.execute("""CREATE TABLE IF NOT EXISTS managed_group_features (
                mg_id INTEGER NOT NULL,
                feature TEXT NOT NULL,
                enabled INTEGER DEFAULT 0,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (mg_id, feature)
            )""")

            # ── [v5.34.0] 内容排查表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS content_violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                message_type TEXT DEFAULT 'text',
                violations TEXT DEFAULT '',
                risk_level TEXT DEFAULT 'low',
                detail TEXT DEFAULT '',
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_violations_uid ON content_violations(uid, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_violations_chat ON content_violations(chat_id, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_violations_ts ON content_violations(ts)")

            # ── [v5.34.0] 网编会员表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS user_membership (
                uid INTEGER PRIMARY KEY,
                tier TEXT DEFAULT 'free',
                expire_at INTEGER DEFAULT 0,
                sub_type TEXT DEFAULT '',
                auto_renew INTEGER DEFAULT 0,
                total_spent REAL DEFAULT 0,
                joined_at INTEGER DEFAULT 0,
                updated_at INTEGER DEFAULT 0
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS membership_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                tier TEXT NOT NULL,
                duration_days INTEGER NOT NULL DEFAULT 0,
                amount REAL DEFAULT 0,
                sub_type TEXT DEFAULT 'manual',
                status TEXT DEFAULT 'active',
                created_at INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_membership_uid ON membership_subscriptions(uid)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_membership_status ON membership_subscriptions(status)")

            # ── [v5.35.0] 群聊设置表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '{}',
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 入群设置表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS join_settings (
                chat_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '{}',
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 群组命令表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS group_commands (
                chat_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '{}',
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 机器人设置表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS bot_settings (
                bot_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '{}',
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 阿福会员表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS afool_member (
                uid INTEGER PRIMARY KEY,
                level TEXT DEFAULT 'free',
                points INTEGER DEFAULT 0,
                experience INTEGER DEFAULT 0,
                expire_at INTEGER DEFAULT 0,
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 超级阿福表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS super_afool (
                uid INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                tier TEXT DEFAULT 'standard',
                expire_at INTEGER DEFAULT 0,
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 机器人列表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS bot_list (
                bot_id INTEGER PRIMARY KEY,
                name TEXT DEFAULT '',
                token TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at INTEGER NOT NULL,
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 新成员观察期表 ─────────────────────────────
            self.conn.commit()
    def _init_tables_misc_8(self):
        """建表分片 12/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS new_member_probation (
                chat_id INTEGER PRIMARY KEY,
                duration INTEGER DEFAULT 300,
                enabled INTEGER DEFAULT 0,
                welcome_message TEXT DEFAULT '',
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 群聊举报表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS group_report (
                chat_id INTEGER PRIMARY KEY,
                keywords TEXT DEFAULT '[]',
                enabled INTEGER DEFAULT 0,
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 词云表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS word_cloud (
                chat_id INTEGER PRIMARY KEY,
                color_scheme TEXT DEFAULT 'default',
                hour_limit INTEGER DEFAULT 1,
                enabled INTEGER DEFAULT 0,
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 语言白名单表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS language_whitelist (
                chat_id INTEGER PRIMARY KEY,
                languages TEXT DEFAULT '[]',
                enabled INTEGER DEFAULT 0,
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 强制关注频道表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS force_channel (
                chat_id INTEGER PRIMARY KEY,
                channel_id INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 0,
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 有效发言表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS valid_speak (
                chat_id INTEGER PRIMARY KEY,
                min_length INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 0,
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 聊天积分消耗表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS chat_points_cost (
                chat_id INTEGER PRIMARY KEY,
                cost_per_message INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 0,
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 自动规则表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS auto_rules (
                chat_id INTEGER PRIMARY KEY,
                rules TEXT DEFAULT '[]',
                enabled INTEGER DEFAULT 0,
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 用户标记表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS user_marking (
                uid INTEGER,
                chat_id INTEGER,
                tags TEXT DEFAULT '[]',
                updated_at INTEGER,
                PRIMARY KEY (uid, chat_id)
            )""")

            # ── [v5.35.0] 群组待办表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS group_todo (
                chat_id INTEGER PRIMARY KEY,
                todos TEXT DEFAULT '[]',
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 邀请链接管理表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS invite_link_manager (
                chat_id INTEGER PRIMARY KEY,
                links TEXT DEFAULT '[]',
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 关联频道表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS channel_link (
                chat_id INTEGER PRIMARY KEY,
                channel_id INTEGER DEFAULT 0,
                enabled INTEGER DEFAULT 0,
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 群安全中心表 ─────────────────────────────
            self.conn.commit()
    def _init_tables_misc_9(self):
        """建表分片 13/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS group_safety_center (
                chat_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '{}',
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 主动消息推送表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS group_message_push (
                chat_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '{}',
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 群管处罚中心表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS punishment_center (
                chat_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '{}',
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 娱乐功能表 ─────────────────────────────
            c.execute("""CREATE TABLE IF NOT EXISTS entertainment_games (
                chat_id INTEGER PRIMARY KEY,
                games TEXT DEFAULT '{}',
                enabled INTEGER DEFAULT 0,
                updated_at INTEGER
            )""")

            # ── [v5.35.0] 36 个新模块补表（模块 SQL 引用，_init_tables 原未定义）─
            # 通用规则：updated_at INTEGER 允许 NULL，主键参照模块 SQL 使用方式
            c.execute("""CREATE TABLE IF NOT EXISTS global_ad_blacklist (
                id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '[]'
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS member_info (
                user_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '{}'
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS bot_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT DEFAULT '{}'
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS user_points (
                user_id INTEGER PRIMARY KEY,
                points INTEGER DEFAULT 0
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS chat_points_usage (
                chat_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '{}'
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS group_configs (
                chat_id INTEGER,
                key TEXT,
                value TEXT,
                updated_at INTEGER,
                PRIMARY KEY (chat_id, key)
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS config_templates (
                name TEXT PRIMARY KEY,
                data TEXT DEFAULT '{}'
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS config_template_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT DEFAULT '{}',
                created_at INTEGER
            )""")

            self.conn.commit()
    def _init_tables_misc_10(self):
        """建表分片 14/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS group_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT DEFAULT '{}'
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS member_actions (
                chat_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '[]'
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS groups (
                chat_id INTEGER PRIMARY KEY
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS migration_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT DEFAULT '[]'
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS user_props (
                user_id INTEGER,
                prop_name TEXT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, prop_name)
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS image_records (
                chat_id INTEGER,
                message_id INTEGER,
                user_id INTEGER,
                file_id TEXT,
                file_unique_id TEXT,
                data TEXT,
                is_favorite INTEGER,
                is_approved INTEGER,
                upload_time INTEGER,
                PRIMARY KEY (chat_id, message_id)
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS invite_links (
                chat_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '[]'
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS content_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                message_id INTEGER,
                content_type TEXT,
                user_id INTEGER,
                content TEXT,
                data TEXT,
                created_at INTEGER
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS join_records (
                chat_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '[]'
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS message_library (
                title TEXT PRIMARY KEY,
                category TEXT DEFAULT 'default',
                data TEXT DEFAULT '{}',
                used_count INTEGER DEFAULT 0,
                created_at INTEGER
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS probation_members (
                chat_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '[]'
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS punishment_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                action_type TEXT,
                data TEXT DEFAULT '{}',
                created_at INTEGER
            )""")

            self.conn.commit()
    def _init_tables_misc_11(self):
        """建表分片 15/15（逐字迁移自原 _init_tables）。"""
        with _db_lock:
            c = self.conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS user_exp (
                user_id INTEGER PRIMARY KEY,
                exp INTEGER DEFAULT 0
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS user_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_name TEXT,
                obtained_at INTEGER
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS message_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                text TEXT,
                created_at INTEGER
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS premium_usage (
                id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '{}'
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS user_marks (
                user_id INTEGER PRIMARY KEY,
                data TEXT DEFAULT '[]'
            )""")

            # 【挑刺修复·任务3】/scan_ads 追溯扫描日志表（幂等建表，raw SQL 不走 _REPO_METHOD_MAP）
            c.execute("""CREATE TABLE IF NOT EXISTS scan_ads_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL,
                group_id INTEGER NOT NULL,
                start_ts INTEGER NOT NULL,
                end_ts INTEGER,
                status TEXT NOT NULL,
                scanned INTEGER DEFAULT 0,
                ads_found INTEGER DEFAULT 0,
                deleted INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                error_msg TEXT
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_scan_ads_log_group ON scan_ads_log(group_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_scan_ads_log_start ON scan_ads_log(start_ts)")

            # 验证码会话持久化表（双写策略：内存优先读，SQLite 用于重启恢复）
            # 解决 Bot 重启时内存会话丢失导致永久禁言无人解禁的问题
            c.execute("""CREATE TABLE IF NOT EXISTS verification_sessions (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                answer TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                timeout_ts REAL NOT NULL,
                msg_id INTEGER,
                mode TEXT NOT NULL,
                user_name TEXT,
                started_ts INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_verif_timeout ON verification_sessions(timeout_ts)")

            self.conn.commit()

            self.conn.commit()

    def _init_tables_platform_support(self):
        """平台观测、治理与 RBAC 表；唯一 schema 所有者。"""
        with _db_lock:
            c = self.conn.cursor()

            # 运行时成本观测。此前由成本守卫和 Dashboard 各自懒建，导致首次
            # 读取表面成功、实际无统一迁移记录；现在统一由本方法创建。
            c.execute("""CREATE TABLE IF NOT EXISTS llm_cost_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER,
                model_name TEXT,
                task_type TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                estimated_cost REAL,
                tier TEXT,
                timestamp INTEGER
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_llm_cost_logs_timestamp ON llm_cost_logs(timestamp)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_llm_cost_logs_uid_timestamp ON llm_cost_logs(uid, timestamp)")

            # 调度持久指标。它是历史观测，不是 APScheduler 当前注册表。
            c.execute("""CREATE TABLE IF NOT EXISTS scheduler_metrics (
                job_id TEXT PRIMARY KEY,
                last_status TEXT,
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                miss_count INTEGER DEFAULT 0,
                last_run INTEGER,
                last_duration INTEGER,
                last_error TEXT,
                synced_at INTEGER NOT NULL
            )""")

            c.execute("""CREATE TABLE IF NOT EXISTS zombie_scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                operator_uid INTEGER NOT NULL,
                zombie_uids TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                msg_id INTEGER DEFAULT 0,
                ts INTEGER NOT NULL
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_zombie_scans_chat_status ON zombie_scans(chat_id, status, ts)")

            # Dashboard RBAC 三表。权限种子仍由 dashboard.audit 在表为空时写入，
            # 但所有 DDL 都必须在这里及对应 Alembic 迁移中。
            c.execute("""CREATE TABLE IF NOT EXISTS user_roles (
                user_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'viewer',
                assigned_by TEXT,
                assigned_at TIMESTAMP
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role)")
            c.execute("""CREATE TABLE IF NOT EXISTS role_permissions (
                role TEXT NOT NULL,
                permission TEXT NOT NULL,
                assigned_by TEXT,
                assigned_at TIMESTAMP,
                PRIMARY KEY (role, permission)
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                operator_id INTEGER,
                operator_name TEXT,
                role TEXT,
                permission TEXT,
                endpoint TEXT,
                method TEXT,
                allowed INTEGER,
                ip TEXT,
                payload_summary TEXT
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_ts ON audit_logs(ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_operator_ts ON audit_logs(operator_id, ts)")

            # 以下列此前由业务模块按请求路径懒补；旧库仍在 DB 初始化时幂等升级。
            self._safe_add_column(c, "conversion_events", "source", "TEXT DEFAULT ''")
            self._safe_add_column(c, "conversion_events", "campaign_id", "TEXT DEFAULT ''")
            self._safe_add_column(c, "conversion_events", "attribution_model", "TEXT DEFAULT ''")
            self._safe_add_column(c, "conversion_events", "weight", "REAL DEFAULT 0")
            self._safe_add_column(c, "conversion_events", "is_memory_assisted", "INTEGER DEFAULT 0")
            self.conn.commit()

    def _normalize_ab_test_stats(self, cursor):
        """合并历史重复统计行，使 Repo 的 UPSERT 冲突目标真实存在。"""
        duplicate_groups = cursor.execute(
            "SELECT group_name, format_version, MIN(id), SUM(sent_count), "
            "SUM(conversion_count), MAX(ts) FROM ab_test_stats "
            "GROUP BY group_name, format_version HAVING COUNT(*) > 1"
        ).fetchall()
        for group_name, format_version, keep_id, sent_count, conversion_count, latest_ts in duplicate_groups:
            cursor.execute(
                "UPDATE ab_test_stats SET sent_count=?, conversion_count=?, ts=? WHERE id=?",
                (sent_count or 0, conversion_count or 0, latest_ts or 0, keep_id),
            )
            cursor.execute(
                "DELETE FROM ab_test_stats WHERE group_name=? AND format_version=? AND id<>?",
                (group_name, format_version, keep_id),
            )
        if duplicate_groups:
            logger.warning("已合并 %s 组重复 A/B 统计记录以启用唯一 UPSERT", len(duplicate_groups))

    def _init_tables_performance_indexes(self):
        """常用查询的性能索引（幂等）。"""
        with _db_lock:
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

    # ──────────────────────────── 向后兼容委托 ──────────────────────────
    _REPO_METHOD_MAP = {
        # user_repo
        'upsert_user': 'users', 'upsert_user_with_points': 'users', 'get_user': 'users',
        'add_keyword': 'users', 'get_active_users': 'users', 'get_inactive_users': 'users',
        'reset_last_active': 'users', 'update_last_active': 'users', 'earn_badge': 'users', 'get_user_badges': 'users',
        'get_all_badges_leaderboard': 'users', 'get_user_profile': 'users',
        'get_user_persona_profile': 'users',
        'get_all_user_profiles': 'users', 'delete_user': 'users',
        # [v5.33] 对话轮次持久化（递进引导重启不重置）
        'update_conversation_turn': 'users', 'get_conversation_turn': 'users',
        # group_repo
        'record_group_join': 'groups', 'record_group_left': 'groups',
        'update_group_total_members': 'groups', 'get_group_stats': 'groups',
        'get_group_stats_by_date': 'groups', 'get_group_stats_by_chat_id': 'groups',
        'get_weekly_group_stats': 'groups', 'get_weekly_channel_member_stats': 'groups',
        'calibrate_group_stats': 'groups', 'get_group_total_members_latest': 'groups',
        'mute_user': 'groups', 'is_muted': 'groups',
        'blacklist_add': 'groups', 'blacklist_remove': 'groups', 'is_blacklisted': 'groups',
        'check_spam': 'groups',
        # [v5.28.3 新增] 以下 4 个方法一直漏注册导致 message_snapshots 全为空
        'snapshot_message': 'groups',
        'mark_message_ad': 'groups',
        'mark_message_deleted': 'groups',
        'queue_keyword_message_delete': 'groups',
        'get_due_keyword_message_deletes': 'groups',
        'get_keyword_message_cleanup_candidates': 'groups',
        'resolve_keyword_message_delete': 'groups',
        'get_keyword_message_delete_state': 'groups',
        'get_user_messages': 'groups',
        'get_user_undeleted_messages': 'groups',
        'get_user_ad_messages': 'groups',
        'record_channel_member_snapshot': 'groups', 'get_channel_member_changes': 'groups',
        'get_channel_weekly_member_changes': 'groups', 'get_channel_monthly_member_changes': 'groups',
        'upsert_group_member': 'groups', 'remove_group_member': 'groups',
        'get_group_member_count': 'groups', 'get_all_group_member_ids': 'groups',
        # points_repo
        'get_user_points': 'points', 'add_points': 'points',
        'get_points_log': 'points', 'get_today_speech_points': 'points',
        'get_leaderboard': 'points', 'get_daily_report': 'points',
        # tracking_repo
        'track_reply': 'tracking', 'mark_replied': 'tracking', 'get_replies_to': 'tracking',
        'track_bot_message': 'tracking',  # [Trae CN v5.12.0补] 之前漏注册，导致 _send_and_track 报属性错误
        'get_recent_unreplied': 'tracking', 'get_orphan_messages': 'tracking',
        'get_unreplied_messages': 'tracking', 'get_ignored_messages': 'tracking',
        'get_all_tracked_messages': 'tracking', 'get_unconfirmed_messages': 'tracking',
        'delete_tracked': 'tracking', 'get_expired_channel_messages': 'tracking',
        'delete_bot_message_records': 'tracking', 'get_tracking_stats': 'tracking',
        'cleanup_old_records': 'tracking',
        'cleanup_channel_tracking_orphan': 'tracking',  # [Bug-03 修复] channel_tracking 孤儿清理
        'track_channel_message': 'tracking', 'update_channel_views': 'tracking',
        'get_channel_tracking': 'tracking', 'get_channel_stats_summary': 'tracking',
        'get_daily_active_users': 'tracking', 'get_daily_bot_messages': 'tracking',
        'get_daily_replies': 'tracking',
        'track_channel_post': 'tracking', 'update_channel_post_views': 'tracking',
        'get_channel_post_stats': 'tracking', 'get_channel_recent_posts': 'tracking',
        'get_channel_top_posts': 'tracking', 'get_channel_avg_views': 'tracking',
        'get_channel_posts_in_range': 'tracking', 'get_channel_daily_stats': 'tracking',
        # tracking_repo - v5.11.0 孤儿播报追踪
        'track_broadcast': 'tracking', 'get_last_broadcast': 'tracking',
        'delete_broadcast': 'tracking', 'cleanup_old_broadcasts': 'tracking',
        # tracking_repo - v5.12.0 孤儿清理监控
        'log_orphan_cleanup': 'tracking', 'get_last_orphan_cleanup': 'tracking',
        'get_orphan_cleanup_history': 'tracking', 'get_orphan_stats': 'tracking',
        # tracking_repo - v5.14.0 商业搭讪事件
        'log_proactive_engage': 'tracking', 'get_recent_engages': 'tracking',
        'get_engaged_stats': 'tracking',
        # config_repo
        'get_system_state': 'config', 'set_system_state': 'config',
        'has_onboarding_delivery': 'config',
        'claim_onboarding_delivery': 'config',
        'complete_onboarding_delivery': 'config',
        'release_onboarding_delivery': 'config',
        'add_keyword_trigger': 'config', 'get_all_keyword_triggers': 'config',
        'delete_keyword_trigger': 'config', 'update_keyword_trigger': 'config',
        'match_keyword_trigger': 'config',
        'claim_task': 'config', 'is_task_executed_today': 'config',
        'release_task': 'config',  # [v5.31.0 修复 Bug A] 之前漏注册，scheduled_broadcast.py 6 处调用全部静默失效
        'cleanup_old_task_log': 'config',
        # [v5.31.2 修复] 健康审计方法漏注册，导致 _job_proactive_audit / _compute_health_score CRITICAL 告警
        'check_integrity': 'config', 'get_recent_task_logs': 'config',
        # social_repo
        'set_wake_up': 'social', 'get_all_wake_ups': 'social',
        'inc_puzzle_score': 'social', '_calc_consecutive_days': 'social',
        'set_cart': 'social', 'get_expired_carts': 'social',
        'log_conversion_event': 'social', 'get_user_consult_count': 'social',
        'get_funnel_summary': 'social',
        'record_feedback': 'social', 'get_feedback_stats': 'social', 'get_recent_feedback': 'social',
        # question_repo - v5.15.0 问题追踪与FAQ蒸馏
        'log_question': 'questions', 'update_question_reply': 'questions',
        'get_question_stats': 'questions', 'get_top_questions': 'questions',
        'get_category_distribution': 'questions', 'get_questions': 'questions',
        'search_faq': 'questions', 'increment_faq_hit': 'questions',
        'create_faq_candidate': 'questions', 'get_pending_candidates': 'questions',
        'approve_candidate': 'questions', 'reject_candidate': 'questions',
        'get_faq_knowledge': 'questions', 'add_faq_knowledge': 'questions',
        'update_faq_knowledge': 'questions', 'delete_faq_knowledge': 'questions',
        'distill_candidates': 'questions',
        # relay_repo
        'save_session': 'relay', 'find_by_admin_msg': 'relay', 'clean_expired': 'relay',
        # ab_test_repo [v5.30.3 修复] 之前整个 repo 17 个方法漏注册，导致 A/B 测试持久化和增长遥测全部静默失效
        'create_experiment': 'ab_test', 'get_experiment': 'ab_test',
        'list_experiments': 'ab_test', 'update_experiment_status': 'ab_test',
        'assign_user_variant': 'ab_test', 'get_user_variant': 'ab_test',
        'get_assignment_stats': 'ab_test',
        'log_telemetry': 'ab_test', 'log_conversation_telemetry': 'ab_test',
        'get_conversion_funnel': 'ab_test', 'get_daily_kpi_series': 'ab_test',
        'get_top_features': 'ab_test',
        'log_guardian_alert': 'ab_test', 'get_recent_guardian_alerts': 'ab_test',
        'save_weekly_report': 'ab_test', 'get_weekly_reports': 'ab_test',
        # user_repo 扩展 [v5.30.3 修复] 画像/AB统计/按钮统计 8 个方法漏注册
        'upsert_user_profile': 'users', 'list_user_profiles': 'users',
        'record_ab_test_sent': 'users', 'record_ab_test_conversion': 'users',
        'get_ab_test_stats': 'users',
        'record_button_impression': 'users', 'record_button_click': 'users',
        'get_button_stats': 'users',
        # social_repo 扩展 [v5.30.3 修复] 购物车挽回 5 个方法漏注册
        'init_cart_recovery': 'social', 'advance_recovery_stage': 'social',
        'get_pending_cart_recoveries': 'social', 'cancel_cart_recovery': 'social',
        'log_paid': 'social',
        # sales_repo [v5.34.0 新增] 销售中心数据层
        'add_product': 'sales', 'update_product': 'sales', 'list_products': 'sales', 'get_product': 'sales',
        'create_order': 'sales', 'update_order_status': 'sales', 'get_user_orders': 'sales', 'get_order_stats': 'sales',
        'track_sales_event': 'sales', 'get_funnel_stats': 'sales',
        'add_commission': 'sales', 'get_commission_stats': 'sales',
        # reply_evolution_repo：管理员审核过的安全风格样本，运行时只读 approved + enabled。
        'create_reply_style_sample': 'reply_evolution',
        'list_reply_style_samples': 'reply_evolution',
        'review_reply_style_sample': 'reply_evolution',
        'set_reply_style_sample_enabled': 'reply_evolution',
        'get_approved_reply_style_samples': 'reply_evolution',
        # conversation_context_repo：短期业务承接与拒绝状态，和遥测原文隔离。
        'get_recent_business_context': 'conversation_context',
        'get_conversion_state': 'conversation_context',
        'set_conversion_opt_out': 'conversation_context',
        'clear_conversion_opt_out': 'conversation_context',
        'record_business_context': 'conversation_context',
        'cleanup_expired_business_context': 'conversation_context',
        # task_exec_history_repo：真实任务执行审计,替代 task_log 算成功率。
        'record_task_start': 'task_exec_history',
        'record_task_success': 'task_exec_history',
        'record_task_failure': 'task_exec_history',
        'record_task_abort': 'task_exec_history',
        'get_success_rate': 'task_exec_history',
        # 【P1-2】僵尸 running 清理(启动时调用) + 【P2-1】历史记录 TTL 清理
        'cleanup_zombie_running': 'task_exec_history',
        'cleanup_old_history': 'task_exec_history',
        # ad_enforcement_repo：处置根因、双按钮说明卡和本人自助复检。
        'create_ad_enforcement_event': 'ad_enforcement',
        'get_ad_enforcement_event': 'ad_enforcement',
        'get_open_ad_root_event': 'ad_enforcement',
        'claim_ad_group_notice': 'ad_enforcement',
        'get_active_ad_notice': 'ad_enforcement',
        'set_ad_event_enforcement': 'ad_enforcement',
        'set_ad_event_notice': 'ad_enforcement',
        'claim_ad_recheck': 'ad_enforcement',
        'resolve_ad_event': 'ad_enforcement',
        'list_unresolved_ad_events': 'ad_enforcement',
    }

    # ──────────────────────────── v5.31.1 第一层防御：启动自检 ──────────────────────────
    # Repo 属性名 → _REPO_METHOD_MAP 中注册的 repo key 的映射
    _REPO_ATTR_MAP = {
        'users': 'users', 'groups': 'groups', 'points': 'points',
        'tracking': 'tracking', 'config': 'config', 'social': 'social',
        'questions': 'questions', 'relay': 'relay', 'ab_test': 'ab_test',
        'sales': 'sales',
        'reply_evolution': 'reply_evolution',
        'conversation_context': 'conversation_context',
        'task_exec_history': 'task_exec_history',
        'ad_enforcement': 'ad_enforcement',
    }
    def _self_check_repo_methods(self):
        """启动时自检：扫描所有 Repo 实例的 public 方法，验证每个方法都在 _REPO_METHOD_MAP 中注册。

        杜绝 v5.30.1/v5.30.3/v5.31.0 同坑复发 3 次：
        - v5.30.1 漏 4 个方法 → message_snapshots 30+ 版本空表
        - v5.30.3 漏 30 个方法 → 增长/A-B/画像全失效
        - v5.31.0 漏 1 个方法 → 播报全灭

        自检逻辑：
        1. 遍历所有 Repo 实例（users/groups/points/tracking/config/social/questions/relay/ab_test）
        2. 收集每个 Repo 的所有 public 方法（不以 _ 开头、callable、非 class/property）
        3. 排除 __init__/close 等 DB 自有方法和不应暴露的内部方法
        4. 检查每个方法是否在 _REPO_METHOD_MAP 中且映射到正确的 repo
        5. 同时反向检查：_REPO_METHOD_MAP 中注册的方法是否在对应 Repo 中真实存在（防拼写错误）
        6. 任何不匹配 → RuntimeError 阻止启动
        """
        missing = []  # Repo 中存在但 _REPO_METHOD_MAP 未注册的方法
        orphaned = []  # _REPO_METHOD_MAP 中注册但 Repo 中不存在的方法（拼写错误/已删除）

        # 正向检查：Repo 方法 → _REPO_METHOD_MAP
        for attr_name, repo_key in self._REPO_ATTR_MAP.items():
            repo_instance = getattr(self, attr_name, None)
            if repo_instance is None:
                continue
            for method_name in dir(repo_instance):
                if method_name.startswith('_'):
                    continue
                attr = getattr(repo_instance, method_name, None)
                if not callable(attr):
                    continue
                # 排除继承自 object 的方法
                if method_name in ('conn', 'lock', 'db_file'):
                    continue
                # 检查是否在 MAP 中
                mapped_repo = self._REPO_METHOD_MAP.get(method_name)
                if mapped_repo is None:
                    missing.append(f"{attr_name}.{method_name}()")
                elif mapped_repo != repo_key:
                    missing.append(f"{attr_name}.{method_name}() → mapped to '{mapped_repo}' but should be '{repo_key}'")

        # 反向检查：_REPO_METHOD_MAP → Repo 方法是否真实存在
        repo_instances = {
            'users': self.users, 'groups': self.groups, 'points': self.points,
            'tracking': self.tracking, 'config': self.config, 'social': self.social,
            'questions': self.questions, 'relay': self.relay, 'ab_test': self.ab_test,
            'sales': self.sales, 'reply_evolution': self.reply_evolution,
            'conversation_context': self.conversation_context,
            'task_exec_history': self.task_exec_history,
            'ad_enforcement': self.ad_enforcement,
        }
        for method_name, repo_key in self._REPO_METHOD_MAP.items():
            repo_instance = repo_instances.get(repo_key)
            if repo_instance is None:
                orphaned.append(f"{method_name}() → repo '{repo_key}' not found")
                continue
            if not hasattr(repo_instance, method_name):
                orphaned.append(f"{method_name}() → registered to '{repo_key}' but method does not exist")

        errors = []
        if missing:
            errors.append(f"❌ DB 启动自检失败：{len(missing)} 个 Repo 方法未在 _REPO_METHOD_MAP 注册（将导致 AttributeError + 静默吞错）:\n  " +
                          "\n  ".join(missing))
        if orphaned:
            errors.append(f"⚠️ DB 启动自检警告：{len(orphaned)} 个 _REPO_METHOD_MAP 注册项在 Repo 中不存在（拼写错误或方法已删除）:\n  " +
                          "\n  ".join(orphaned))

        if errors:
            for e in errors:
                logger.critical(e)
            # missing 是致命错误，阻止启动；orphaned 是警告但也阻止启动防止拼写错误
            raise RuntimeError(
                f"DB _REPO_METHOD_MAP 自检失败：{len(missing)} missing, {len(orphaned)} orphaned。"
                f"请检查 core/database.py _REPO_METHOD_MAP 注册。\n缺失: {missing}\n孤儿: {orphaned}"
            )

        total_methods = sum(
            len([m for m in dir(getattr(self, a)) if not m.startswith('_') and callable(getattr(getattr(self, a), m, None))])
            for a in self._REPO_ATTR_MAP
        )
        logger.info(f"✅ DB 启动自检通过：{len(self._REPO_METHOD_MAP)} 个委托方法映射到 {len(self._REPO_ATTR_MAP)} 个 Repo，共 {total_methods} public 方法全覆盖")

    def __getattr__(self, name):
        repo_name = self._REPO_METHOD_MAP.get(name)
        if repo_name:
            return getattr(getattr(self, repo_name), name)
        # 【v5.31.1 第二层防御】方法不存在时输出 CRITICAL 日志含调用栈，
        # 即使被 except Exception 吞掉，日志中也有明确记录（杜绝静默失败）
        import traceback
        stack = traceback.format_stack()[-5:-1]  # 取最近4层调用栈（不含自身）
        logger.critical(
            f"🚨 DB 方法不存在：'{name}' 未在 _REPO_METHOD_MAP 注册！\n"
            f"调用栈:\n{''.join(stack)}"
        )
        raise AttributeError(f"'DB' object has no attribute '{name}' (not registered in _REPO_METHOD_MAP; check core/database.py)")
