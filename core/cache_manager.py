"""
core/cache_manager.py - 通用磁盘缓存层

基于 diskcache 实现，适用于 2C4G VPS 场景：
- 数据存磁盘（SQLite），不占应用内存
- 线程安全（diskcache 内部保证）
- 支持 TTL、命名空间、前缀批量失效
- 提供 @cached 装饰器，零侵入缓存函数结果

缓存目录：项目根目录/.cache/
"""

import os
import functools
import threading
from pathlib import Path
from typing import Any, Optional, Callable, cast

import diskcache as dc

from core.logging_util import get_logger

logger = get_logger("cache_manager")

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _PROJECT_ROOT / ".cache"

# 默认 TTL：5 分钟
_DEFAULT_TTL = 300

# 预定义命名空间
NAMESPACES = ("group_config", "user_profile", "blacklist", "keyword_triggers")


class CacheManager:
    """
    磁盘缓存管理器（单例）。

    使用 diskcache.Cache 作为后端：
    - 数据写入磁盘 SQLite，不占内存
    - 线程安全，多读单写无锁竞争
    - 支持 TTL 自动过期

    缓存键格式：{namespace}:{key}
    """

    _instance: Optional["CacheManager"] = None
    _lock = threading.Lock()
    _initialized: bool

    def __new__(cls, *args, **kwargs):
        """单例模式，线程安全。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, cache_dir: Optional[str] = None, default_ttl: int = _DEFAULT_TTL):
        """
        初始化缓存管理器。

        Args:
            cache_dir: 缓存目录路径，默认 项目根/.cache/
            default_ttl: 默认 TTL（秒），默认 300（5 分钟）
        """
        if self._initialized:
            return
        self._initialized = True

        self._cache_dir = str(cache_dir or _CACHE_DIR)
        self._default_ttl = default_ttl

        # 统计计数器（线程安全由 GIL 保证，计数器操作是原子的）
        self._hits = 0
        self._misses = 0

        # 确保缓存目录存在
        os.makedirs(self._cache_dir, exist_ok=True)

        # 初始化 diskcache.Cache（基于 SQLite，线程安全）
        # size_limit=256MB，适合 2C4G VPS
        self._cache = dc.Cache(
            self._cache_dir,
            size_limit=256 * 1024 * 1024,  # 256 MB
            eviction_policy="least-recently-used",
        )

        logger.info(f"CacheManager 初始化完成 | 目录: {self._cache_dir} | 默认TTL: {self._default_ttl}s")

    @classmethod
    def reset(cls):
        """重置单例（仅测试用）。"""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.close()
                cls._instance = None

    def _make_key(self, namespace: str, key: str) -> str:
        """构造带命名空间的缓存键。"""
        return f"{namespace}:{key}"

    def get(self, namespace: str, key: str, default: Any = None) -> Any:
        """
        读取缓存。

        Args:
            namespace: 命名空间（如 group_config）
            key: 缓存键
            default: 未命中时的默认值

        Returns:
            缓存值，未命中返回 default
        """
        full_key = self._make_key(namespace, key)
        value = self._cache.get(full_key, default=default)

        if value is default:
            self._misses += 1
        else:
            self._hits += 1

        return value

    def set(self, namespace: str, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        写入缓存。

        Args:
            namespace: 命名空间
            key: 缓存键
            value: 缓存值（需可 pickle）
            ttl: 过期时间（秒），None 使用默认 TTL
        """
        full_key = self._make_key(namespace, key)
        expire = ttl if ttl is not None else self._default_ttl
        self._cache.set(full_key, value, expire=expire)

    def delete(self, namespace: str, key: str) -> bool:
        """
        删除单条缓存。

        Returns:
            是否删除成功（键存在且被删除返回 True）
        """
        full_key = self._make_key(namespace, key)
        result = self._cache.delete(full_key)
        return result

    def invalidate_prefix(self, namespace: str, prefix: str = "") -> int:
        """
        按前缀批量失效缓存。

        例如 invalidate_prefix("group_config", "12345:") 会删除
        所有 group_config:12345:* 的缓存。

        Args:
            namespace: 命名空间
            prefix: 键前缀，空字符串表示清除整个命名空间

        Returns:
            被删除的缓存数量
        """
        search_key = self._make_key(namespace, prefix)
        count = 0
        # diskcache 的 iterkeys 支持前缀匹配
        for key in list(self._cache.iterkeys()):
            if isinstance(key, str) and key.startswith(search_key):
                if self._cache.delete(key):
                    count += 1
        if count > 0:
            logger.debug(f"前缀失效 | {search_key}* | 删除 {count} 条")
        return count

    def clear(self, namespace: Optional[str] = None) -> int:
        """
        清空缓存。

        Args:
            namespace: 指定命名空间则只清该空间，None 清空全部

        Returns:
            被删除的缓存数量
        """
        if namespace is not None:
            return self.invalidate_prefix(namespace)

        count = len(self._cache)
        self._cache.clear()
        logger.info(f"缓存已全部清空 | 共 {count} 条")
        return count

    def stats(self) -> dict[str, Any]:
        """
        获取缓存统计信息。

        Returns:
            包含命中率、缓存大小、条目数等信息的字典
        """
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0.0

        # diskcache 缓存卷统计
        volume = self._cache.volume()

        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total,
            "hit_rate": round(hit_rate, 2),
            "cache_size_bytes": volume,
            "cache_size_mb": round(volume / 1024 / 1024, 2),
            "entry_count": len(self._cache),
            "cache_dir": self._cache_dir,
            "default_ttl": self._default_ttl,
        }

    def close(self) -> None:
        """关闭缓存（释放 SQLite 连接）。"""
        if hasattr(self, "_cache") and self._cache is not None:
            self._cache.close()
            logger.debug("CacheManager 已关闭")

    def __contains__(self, item: Any) -> bool:
        """支持 in 操作符：("group_config", "key") in cache_manager"""
        if isinstance(item, tuple) and len(item) == 2:
            namespace, key = item
            full_key = self._make_key(namespace, key)
            return full_key in self._cache
        return False


# ════════════════════════ 装饰器 ════════════════════════════════════


def cached(namespace: str, ttl: Optional[int] = None, key_func: Optional[Callable[..., Any]] = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    函数结果缓存装饰器。

    用法：
        @cached("group_config", ttl=600)
        def get_group_config(group_id):
            ...

        @cached("user_profile", key_func=lambda uid, name: f"{uid}_{name}")
        def get_user(uid, name):
            ...

    Args:
        namespace: 缓存命名空间，用于隔离不同业务域的缓存
        ttl: 过期时间（秒），None 使用 CacheManager 默认 TTL（300s）
        key_func: 自定义缓存键生成函数，接收与目标函数相同的参数。
                  不提供时使用函数名 + 所有位置参数 + 所有关键字参数。

    Returns:
        装饰后的函数，附带 cache_clear/cache_get/cache_set 方法

    Example:
        >>> @cached("user", ttl=60)
        ... def get_user(uid):
        ...     return db.query(uid)
        >>> get_user(123)  # 首次调用，执行函数并缓存
        >>> get_user(123)  # 缓存命中，直接返回
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache = CacheManager()

            # 生成缓存键
            if key_func is not None:
                raw_key = key_func(*args, **kwargs)
            else:
                # 默认键：函数名 + 位置参数 + 排序后的关键字参数
                parts = [func.__name__]
                parts.extend(str(a) for a in args)
                for k in sorted(kwargs.keys()):
                    parts.append(f"{k}={kwargs[k]}")
                raw_key = ":".join(parts)

            # 尝试读缓存
            result = cache.get(namespace, raw_key)
            if result is not None:
                return result

            # 未命中，执行函数
            result = func(*args, **kwargs)

            # 写入缓存（只缓存非 None 结果）
            if result is not None:
                cache.set(namespace, raw_key, result, ttl=ttl)

            return result

        # 暴露缓存操作方法，方便外部手动控制
        wrapper_any = cast(Any, wrapper)
        wrapper_any.cache_clear = lambda: cache_clear_for_func(namespace, func.__name__)
        wrapper_any.cache_get = lambda key: CacheManager().get(namespace, key)
        wrapper_any.cache_set = lambda key, value, t=None: CacheManager().set(namespace, key, value, ttl=t or ttl)

        return wrapper_any
    return decorator


def cache_clear_for_func(namespace: str, func_name: str) -> int:
    """清除指定命名空间下某函数的所有缓存。"""
    cache = CacheManager()
    return cache.invalidate_prefix(namespace, f"{func_name}:")


# ════════════════════════ 便捷函数 ════════════════════════════════════


def get_cache() -> CacheManager:
    """获取 CacheManager 单例（懒初始化）。"""
    return CacheManager()
