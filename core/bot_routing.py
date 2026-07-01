# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/bot_routing.py  ·  多 Bot 任务分工编排（v5.24.0 阶段3-C）          ║
║                                                                            ║
║  功能：                                                                    ║
║    通过静态路由表 bot_group_routing，让多 Bot 实例按群组分工，             ║
║    避免多 Bot 同时响应同一群组同一模块造成职能冲突。                      ║
║                                                                            ║
║  设计原则：                                                                ║
║    - 默认放行（向后兼容）：路由表无该群组记录时返回 True                   ║
║    - 配置开关 BOT_ROUTING_ENABLED 默认 False，关闭时全部放行              ║
║    - 失败静默降级：DB 异常时返回默认策略，不阻断主流程                     ║
║    - 复用 shared_db 的连接管理，避免新增连接                                ║
║                                                                            ║
║  使用：                                                                    ║
║    from core.bot_routing import init_router, should_handle                ║
║    init_router(CONFIG)                                                     ║
║    if not should_handle(bot_id, chat_id, "group_chat"):                   ║
║        return  # 当前 Bot 不负责该群组，静默退出                           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import json
import threading
from typing import Optional, List, Dict

from core.logging_util import get_logger

logger = get_logger("bot_routing")


class BotRouter:
    """多 Bot 群组路由管理器

    通过 bot_group_routing 表存储 (bot_id, chat_id) → allowed_modules 的映射，
    决定哪个 Bot 负责哪个群组的哪些模块。

    表结构（在 core/database.py 的 _init_tables 中同步建表）：
        bot_group_routing(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER NOT NULL,           -- Telegram Bot 的 user_id
            chat_id INTEGER NOT NULL,          -- 群组 chat_id（负数）
            allowed_modules TEXT NOT NULL,     -- JSON 数组
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(bot_id, chat_id)
        )
    """

    def __init__(self, config: dict):
        self.config = config or {}
        # 路由总开关，默认关闭（向后兼容）
        self.enabled = bool(self.config.get("BOT_ROUTING_ENABLED", False))
        # 默认策略：群组无路由记录时，"allow" 放行 / "deny" 拒绝
        self.default_policy = str(self.config.get("BOT_ROUTING_DEFAULT_POLICY", "allow")).lower()
        if self.default_policy not in ("allow", "deny"):
            self.default_policy = "allow"
        self._lock = threading.Lock()

    # ── 连接获取 ──────────────────────────────────────────────────────
    def _get_conn(self):
        """获取数据库连接

        优先复用 shared_db 的共享连接（多 Bot 共享同一张表），
        失败时回退到 None，调用方按默认策略降级。
        """
        try:
            from core.shared_db import _get_shared_conn
            return _get_shared_conn()
        except Exception as e:
            logger.warning(f"获取共享连接失败: {e}")
            return None

    def _ensure_table(self, conn) -> bool:
        """幂等确保路由表存在（防御首次调用或旧库）"""
        if conn is None:
            return False
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_group_routing (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    allowed_modules TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(bot_id, chat_id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_bot_routing_chat "
                "ON bot_group_routing(chat_id, is_active)"
            )
            conn.commit()
            return True
        except Exception as e:
            logger.warning(f"确保 bot_group_routing 表失败: {e}")
            return False

    # ── 核心查询 ──────────────────────────────────────────────────────
    def should_handle(self, bot_id: int, chat_id: int, module_name: str) -> bool:
        """判断当前 Bot 是否应该处理该群组的该模块

        决策逻辑：
            1. BOT_ROUTING_ENABLED=False → 直接放行（向后兼容）
            2. 路由表无该群组记录 → 按默认策略（allow/deny）
            3. 该群组有路由记录但当前 bot_id 无记录 → 按默认策略
            4. 当前 bot_id 有记录但 is_active=0 → 拒绝
            5. allowed_modules 列表包含 module_name → 放行
            6. 否则 → 拒绝

        Args:
            bot_id: Telegram Bot 的 user_id
            chat_id: 群组 chat_id（通常为负数）
            module_name: 模块名，如 "group_chat" / "scheduled_broadcast" / "direct_sales"

        Returns:
            True 放行，False 拒绝
        """
        # 总开关关闭：全部放行
        if not self.enabled:
            return True

        # 私聊（chat_id >= 0）默认放行，路由只针对群组
        if chat_id >= 0:
            return True

        try:
            conn = self._get_conn()
            if not self._ensure_table(conn):
                # DB 不可用：按默认策略降级
                return self.default_policy == "allow"

            with self._lock:
                # 查询该群组所有活跃路由
                rows = conn.execute(
                    "SELECT bot_id, allowed_modules, is_active FROM bot_group_routing "
                    "WHERE chat_id=? AND is_active=1",
                    (chat_id,)
                ).fetchall()

                # 该群组无任何路由记录：按默认策略
                if not rows:
                    return self.default_policy == "allow"

                # 查找当前 bot_id 的路由
                current_row = None
                for r in rows:
                    if r["bot_id"] == bot_id:
                        current_row = r
                        break

                # 当前 bot_id 无路由记录：按默认策略
                if current_row is None:
                    return self.default_policy == "allow"

                # 解析 allowed_modules
                try:
                    allowed_modules = json.loads(current_row["allowed_modules"])
                    if not isinstance(allowed_modules, list):
                        allowed_modules = []
                except (ValueError, TypeError):
                    allowed_modules = []

                # 模块在允许列表中 → 放行
                return module_name in allowed_modules
        except Exception as e:
            logger.warning(f"should_handle 查询失败 bot={bot_id} chat={chat_id} module={module_name}: {e}")
            # 异常时按默认策略降级，不阻断主流程
            return self.default_policy == "allow"

    def get_active_bot_for_module(self, chat_id: int, module_name: str) -> Optional[int]:
        """获取该群组该模块的活跃 Bot ID

        Args:
            chat_id: 群组 chat_id
            module_name: 模块名

        Returns:
            活跃 Bot ID，无匹配返回 None
        """
        if not self.enabled:
            return None
        try:
            conn = self._get_conn()
            if not self._ensure_table(conn):
                return None
            with self._lock:
                rows = conn.execute(
                    "SELECT bot_id, allowed_modules FROM bot_group_routing "
                    "WHERE chat_id=? AND is_active=1",
                    (chat_id,)
                ).fetchall()
                for r in rows:
                    try:
                        allowed = json.loads(r["allowed_modules"])
                        if isinstance(allowed, list) and module_name in allowed:
                            return r["bot_id"]
                    except (ValueError, TypeError):
                        continue
            return None
        except Exception as e:
            logger.warning(f"get_active_bot_for_module 失败 chat={chat_id} module={module_name}: {e}")
            return None

    # ── 路由管理 ──────────────────────────────────────────────────────
    def assign_bot(self, bot_id: int, chat_id: int,
                   allowed_modules: list, is_active: int = 1) -> bool:
        """分配/更新路由

        Args:
            bot_id: Telegram Bot 的 user_id
            chat_id: 群组 chat_id
            allowed_modules: 允许的模块列表，如 ["group_chat","scheduled_broadcast"]
            is_active: 1 启用 / 0 停用

        Returns:
            True 成功，False 失败
        """
        try:
            conn = self._get_conn()
            if not self._ensure_table(conn):
                return False
            modules_json = json.dumps(list(allowed_modules), ensure_ascii=False)
            with self._lock:
                # UPSERT：存在则更新，不存在则插入
                conn.execute("""
                    INSERT INTO bot_group_routing
                        (bot_id, chat_id, allowed_modules, is_active, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(bot_id, chat_id) DO UPDATE SET
                        allowed_modules=excluded.allowed_modules,
                        is_active=excluded.is_active,
                        updated_at=CURRENT_TIMESTAMP
                """, (bot_id, chat_id, modules_json, int(is_active)))
                conn.commit()
            logger.info(f"✅ 路由已分配 bot={bot_id} chat={chat_id} modules={allowed_modules} active={is_active}")
            return True
        except Exception as e:
            logger.warning(f"assign_bot 失败 bot={bot_id} chat={chat_id}: {e}")
            return False

    def remove_routing(self, bot_id: int, chat_id: int) -> bool:
        """删除路由

        Args:
            bot_id: Telegram Bot 的 user_id
            chat_id: 群组 chat_id

        Returns:
            True 成功，False 失败
        """
        try:
            conn = self._get_conn()
            if not self._ensure_table(conn):
                return False
            with self._lock:
                conn.execute(
                    "DELETE FROM bot_group_routing WHERE bot_id=? AND chat_id=?",
                    (bot_id, chat_id)
                )
                conn.commit()
            logger.info(f"✅ 路由已删除 bot={bot_id} chat={chat_id}")
            return True
        except Exception as e:
            logger.warning(f"remove_routing 失败 bot={bot_id} chat={chat_id}: {e}")
            return False

    def list_routing(self, chat_id: Optional[int] = None) -> List[Dict]:
        """列出路由

        Args:
            chat_id: 可选，指定群组 chat_id 过滤；None 列出全部

        Returns:
            路由字典列表
        """
        try:
            conn = self._get_conn()
            if not self._ensure_table(conn):
                return []
            with self._lock:
                if chat_id is None:
                    rows = conn.execute(
                        "SELECT bot_id, chat_id, allowed_modules, is_active, "
                        "created_at, updated_at FROM bot_group_routing "
                        "ORDER BY chat_id, bot_id"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT bot_id, chat_id, allowed_modules, is_active, "
                        "created_at, updated_at FROM bot_group_routing "
                        "WHERE chat_id=? ORDER BY bot_id",
                        (chat_id,)
                    ).fetchall()
            result = []
            for r in rows:
                try:
                    modules = json.loads(r["allowed_modules"])
                except (ValueError, TypeError):
                    modules = []
                result.append({
                    "bot_id": r["bot_id"],
                    "chat_id": r["chat_id"],
                    "allowed_modules": modules,
                    "is_active": bool(r["is_active"]),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                })
            return result
        except Exception as e:
            logger.warning(f"list_routing 失败: {e}")
            return []


# ── 模块级单例 ──────────────────────────────────────────────────────
_router_instance: Optional[BotRouter] = None
_router_lock = threading.Lock()


def init_router(config: dict):
    """初始化路由器单例（main.py 启动时调用）

    Args:
        config: CONFIG 字典
    """
    global _router_instance
    with _router_lock:
        try:
            _router_instance = BotRouter(config)
            # 启动时幂等确保表存在（即使 shared_db 未初始化也不报错）
            if _router_instance.enabled:
                conn = _router_instance._get_conn()
                _router_instance._ensure_table(conn)
                logger.info(
                    f"✅ BotRouter 已初始化 enabled={_router_instance.enabled} "
                    f"default_policy={_router_instance.default_policy}"
                )
            else:
                logger.info("✅ BotRouter 已初始化（功能关闭，全部放行）")
        except Exception as e:
            logger.warning(f"⚡ BotRouter 初始化失败: {e}")
            _router_instance = None


def get_router() -> Optional[BotRouter]:
    """获取路由器单例"""
    return _router_instance


def should_handle(bot_id: int, chat_id: int, module_name: str) -> bool:
    """便捷函数：判断当前 Bot 是否应该处理该群组的该模块

    路由器未初始化或异常时返回 True（向后兼容，不阻断主流程）。
    """
    router = _router_instance
    if router is None:
        return True
    return router.should_handle(bot_id, chat_id, module_name)


def get_active_bot_for_module(chat_id: int, module_name: str) -> Optional[int]:
    """便捷函数：获取该群组该模块的活跃 Bot ID"""
    router = _router_instance
    if router is None:
        return None
    return router.get_active_bot_for_module(chat_id, module_name)
