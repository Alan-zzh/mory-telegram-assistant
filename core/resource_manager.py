"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/resource_manager.py  ·  线程安全资源管理器 v1.0                    ║
║                                                                        ║
║  功能：                                                                ║
║    1. 为共享资源（bot / ai / db / config）提供互斥锁，避免多线程竞争   ║
║    2. 提供安全的上下文管理器，确保资源访问后锁被释放                    ║
║    3. 支持异步任务执行，隔离长时间运行的任务与主循环                    ║
║                                                                        ║
║  使用场景：                                                            ║
║    - auto_tasks.py 后台任务需要安全访问 bot、ai、db 等共享对象          ║
║    - 主线程与后台任务之间的资源竞争避免                                 ║
║    - 长时间运行的任务（新闻获取、AI生成）在独立线程中执行，不阻塞主循环  ║
║                                                                        ║
║  设计原则：                                                            ║
║    - 最小侵入性：不改变现有模块的接口，仅作为包装层                    ║
║    - 线程安全：每个资源独立锁，细粒度控制                              ║
║    - 异常安全：即使任务抛出异常，锁也会被正确释放                       ║
║    - 超时保护：防止死锁，设置获取锁的超时时间                           ║
║                                                                        ║
║  用法示例：                                                            ║
║    with rm.locked('bot'):                                              ║
║        rm.bot.send_message(chat_id, text)                              ║
║                                                                        ║
║    rm.execute_task(func, args, resources=['bot', 'ai'])                ║
║                                                                        ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import threading
import time
from typing import Any, Callable, List, Optional
from core.logging_util import get_logger

logger = get_logger("resource_manager")

class ResourceManager:
    """
    线程安全资源管理器。

    管理以下共享资源（由外部传入）：
    - bot: Telegram bot 实例（pyTelegramBotAPI）
    - ai: AIEngine 实例
    - db: DB 数据库实例
    - config: 配置字典（只读）
    - save_config_fn: 保存配置的函数（可调用）

    为每个资源提供独立的锁，并通过上下文管理器确保安全访问。
    """

    def __init__(self, bot=None, ai=None, db=None, config=None, save_config_fn=None):
        """
        初始化资源管理器。

        Args:
            bot: Telegram bot 实例（必须）
            ai: AIEngine 实例（必须）
            db: DB 数据库实例（必须）
            config: 配置字典（必须）
            save_config_fn: 保存配置的函数（可选）
        """
        self._bot = bot
        self._ai = ai
        self._db = db
        self._config = config
        self._save_config_fn = save_config_fn

        # 为每个资源创建独立的锁
        self._locks = {
            'bot': threading.RLock(),
            'ai': threading.RLock(),
            'db': threading.RLock(),  # 注意：database.py 已有自己的锁，此处作为额外保护
            'config': threading.RLock(),
        }

        # 任务执行线程池（简化版：使用单个后台线程执行长时间任务）
        self._task_queue = []
        self._task_lock = threading.Lock()
        self._task_thread = None
        self._task_running = False

        logger.info("🛡️  资源管理器初始化完成")

    @property
    def bot(self):
        """获取 bot 实例（使用前应通过 locked('bot') 加锁）"""
        return self._bot

    @property
    def ai(self):
        """获取 ai 实例（使用前应通过 locked('ai') 加锁）"""
        return self._ai

    @property
    def db(self):
        """获取 db 实例（使用前应通过 locked('db') 加锁）"""
        return self._db

    @property
    def config(self):
        """获取配置字典（只读，使用前应通过 locked('config') 加锁）"""
        return self._config

    @property
    def save_config_fn(self):
        """获取保存配置的函数（使用前应通过 locked('config') 加锁）"""
        return self._save_config_fn

    def locked(self, resource_name: str, timeout: float = 30.0):
        """
        返回一个上下文管理器，用于安全地访问指定资源。

        Args:
            resource_name: 资源名称，'bot'、'ai'、'db'、'config' 之一
            timeout: 获取锁的超时时间（秒），超时则抛出 TimeoutError

        Returns:
            上下文管理器，在 with 块内资源锁已被获取

        Usage:
            with rm.locked('bot'):
                rm.bot.send_message(...)
        """
        lock = self._locks.get(resource_name)
        if lock is None:
            raise ValueError(f"未知资源: {resource_name}")

        class _ResourceLock:
            def __init__(self, lock, timeout):
                self.lock = lock
                self.timeout = timeout
                self.acquired = False

            def __enter__(self):
                if not self.lock.acquire(timeout=self.timeout):
                    raise TimeoutError(f"获取资源 {resource_name} 锁超时")
                self.acquired = True
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                if self.acquired:
                    self.lock.release()
                return False  # 不吞异常

        return _ResourceLock(lock, timeout)

    def locked_multi(self, resource_names: List[str], timeout: float = 30.0):
        """
        同时锁定多个资源（按字母顺序获取锁，避免死锁）。

        Args:
            resource_names: 资源名称列表，如 ['bot', 'ai']
            timeout: 获取每个锁的超时时间（秒）

        Returns:
            上下文管理器，在 with 块内所有资源锁已被获取
        """
        # 按字母顺序排序，确保全局一致的加锁顺序，防止死锁
        sorted_names = sorted(resource_names)
        locks = []
        for name in sorted_names:
            lock = self._locks.get(name)
            if lock is None:
                raise ValueError(f"未知资源: {name}")
            locks.append(lock)

        class _MultiResourceLock:
            def __init__(self, locks, timeout):
                self.locks = locks
                self.timeout = timeout
                self.acquired = []

            def __enter__(self):
                for i, lock in enumerate(self.locks):
                    if not lock.acquire(timeout=self.timeout):
                        # 超时：释放已获得的锁
                        for acquired_lock in self.acquired:
                            acquired_lock.release()
                        raise TimeoutError(f"获取第 {i+1} 个资源锁超时")
                    self.acquired.append(lock)
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                # 按相反顺序释放锁
                for lock in reversed(self.acquired):
                    lock.release()
                return False

        return _MultiResourceLock(locks, timeout)

    def execute_task(self, func: Callable, args: tuple = (), kwargs: dict = None,
                     resources: List[str] = None, timeout: float = 30.0) -> Any:
        """
        在资源锁的保护下执行任务，支持超时。

        Args:
            func: 要执行的函数
            args: 位置参数
            kwargs: 关键字参数
            resources: 需要锁定的资源列表，为 None 时不加锁
            timeout: 任务执行超时时间（秒）

        Returns:
            函数返回值，若超时则返回 None

        Raises:
            TimeoutError: 任务执行超时
            Exception: 函数抛出的异常
        """
        if kwargs is None:
            kwargs = {}

        def _wrapped():
            if resources:
                with self.locked_multi(resources, timeout=30.0):
                    return func(*args, **kwargs)
            else:
                return func(*args, **kwargs)

        # 创建一个线程来执行任务，以便我们可以设置超时
        result_container = []
        exception_container = []

        def _worker():
            try:
                result = _wrapped()
                result_container.append(result)
            except Exception as e:
                exception_container.append(e)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            # 【P1-NEW-06】任务超时后 worker 线程仍运行，持有的资源锁不释放
            logger.critical(
                f"🚨 任务 {func.__name__} 执行超时（{timeout}秒），"
                f"worker 线程仍在后台运行，资源锁可能未释放。"
                f"其他任务尝试获取同一资源可能被阻塞。"
            )
            # 尝试通知运维
            try:
                from tasks.support.fault_reporter import get_fault_reporter
                reporter = get_fault_reporter()
                if reporter:
                    reporter.report(
                        "task_timeout_lock_stuck",
                        f"任务 {func.__name__} 超时后资源锁未释放",
                        severity="🚨",
                    )
            except Exception:
                pass  # 通知失败不加重原问题
            raise TimeoutError(f"任务执行超时: {timeout}秒")

        if exception_container:
            raise exception_container[0]

        return result_container[0] if result_container else None

    def submit_background_task(self, func: Callable, args: tuple = (), kwargs: dict = None,
                               resources: List[str] = None, name: str = "background_task"):
        """
        提交一个后台任务，该任务将在独立的线程中执行，不阻塞调用者。
        任务执行失败会记录日志，但不会影响主循环。

        Args:
            func: 要执行的函数
            args: 位置参数
            kwargs: 关键字参数
            resources: 需要锁定的资源列表
            name: 任务名称，用于日志记录

        Returns:
            threading.Thread: 已启动的后台线程对象
        """
        if kwargs is None:
            kwargs = {}

        def _wrapped():
            try:
                logger.info(f"🔧 后台任务开始: {name}")
                if resources:
                    with self.locked_multi(resources, timeout=10.0):
                        func(*args, **kwargs)
                else:
                    func(*args, **kwargs)
                logger.info(f"✅ 后台任务完成: {name}")
            except Exception as e:
                logger.error(f"❌ 后台任务失败 {name}: {e}", exc_info=True)

        thread = threading.Thread(target=_wrapped, daemon=True, name=f"BG-{name}")
        thread.start()
        return thread
