"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/optimizer.py  ·  轻量级优化引擎 v1.0                              ║
║                                                                        ║
║  只保留3个经过验证的有效模块：                                          ║
║    1. 熔断器（Circuit Breaker）—— 连续失败自动拉黑+冷却恢复           ║
║    2. 语义缓存（Semantic Cache）—— 相同query命中缓存，省API费         ║
║    3. 令牌桶限流（Token Bucket）—— 防止429雪崩                        ║
║                                                                        ║
║  设计原则：非侵入式，不替换ai.ask，只在ask内部做hook                   ║
║  激活方式：AIEngine.__init__ 末尾自动初始化                           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import hashlib
import time
import threading
import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from core.logging_util import get_logger

logger = get_logger("optimizer")


# ════════════════════════ 1. 熔断器 ════════════════════════════════════

class CircuitBreaker:
    """
    模型级熔断器。
    
    逻辑：
    - 每个模型独立计数连续失败次数
    - 连续失败 >= threshold（默认3次）→ 熔断（OPEN状态）
    - 熔断后 cooldown 秒（默认300s=5分钟）内不再尝试该模型
    - 冷却结束后 → 半开（HALF_OPEN），允许1次试探
    - 试探成功 → 关闭（CLOSED），计数归零
    - 试探失败 → 重新打开（OPEN），重新计时
    
    与 AIEngine 原有黑名单的关系：
    - 黑名单 = 永久拉黑（没钱/403/402等确定性问题）
    - 熔断 = 临时拉黑（超时/429/500等暂时性问题，会自动恢复）
    - 两者独立运作，互不冲突
    """
    
    CLOSED = "closed"      # 正常工作
    OPEN = "open"          # 熔断中，拒绝请求
    HALF_OPEN = "half_open" # 冷却结束，允许试探
    
    def __init__(self, threshold: int = 3, cooldown: int = 300):
        self.threshold = threshold   # 连续几次失败触发熔断
        self.cooldown = cooldown     # 冷却时间（秒）
        # {model_name: {"state": str, "fail_count": int, "last_failure": float}}
        self._circuits = {}
        self._lock = threading.Lock()
    
    def is_available(self, model_name: str) -> bool:
        """检查模型是否可用（未被熔断）"""
        with self._lock:
            c = self._circuits.get(model_name)
            if not c:
                return True
            
            if c["state"] == self.CLOSED:
                return True
            
            if c["state"] == self.OPEN:
                # 检查冷却期是否已过
                if time.time() - c["last_failure"] >= self.cooldown:
                    c["state"] = self.HALF_OPEN
                    logger.info(f"🔧 熔断器[{model_name}] 冷却结束→HALF_OPEN，允许试探")
                    return True
                return False
            
            # HALF_OPEN：允许一次试探
            return True
    
    def record_success(self, model_name: str):
        """记录成功调用"""
        with self._lock:
            c = self._circuits.get(model_name)
            if c:
                c["fail_count"] = 0
                c["state"] = self.CLOSED
    
    def record_failure(self, model_name: str):
        """记录失败调用"""
        with self._lock:
            c = self._circuits.setdefault(model_name, {
                "state": self.CLOSED,
                "fail_count": 0,
                "last_failure": 0,
            })
            
            c["fail_count"] += 1
            c["last_failure"] = time.time()
            
            if c["state"] == self.HALF_OPEN:
                # 试探失败，重新熔断
                c["state"] = self.OPEN
                logger.warning(f"⚡ 熔断器[{model_name}] 试探失败→重新OPEN，冷却{self.cooldown}s")
            elif c["fail_count"] >= self.threshold:
                c["state"] = self.OPEN
                logger.warning(
                    f"⚡ 熔断器[{model_name}] 触发！连续{c['fail_count']}次失败"
                    f"→OPEN，冷却{self.cooldown}s"
                )
    
    def get_status(self, model_name: str) -> dict:
        """获取指定模型的熔断状态"""
        with self._lock:
            c = self._circuits.get(model_name)
            if not c:
                return {"state": self.CLOSED, "fail_count": 0}
            return dict(c)
    
    def get_all_status(self) -> dict:
        """获取所有模型的熔断状态"""
        with self._lock:
            return {k: {"state": v["state"], "fail_count": v["fail_count"]} 
                    for k, v in self._circuits.items()}
    
    def reset(self, model_name: str):
        """手动重置指定模型的熔断器（管理员指令用）"""
        with self._lock:
            if model_name in self._circuits:
                self._circuits[model_name] = {
                    "state": self.CLOSED,
                    "fail_count": 0,
                    "last_failure": 0,
                }
                logger.info(f"✅ 熔断器[{model_name}] 已手动重置")
                return True
            return False


# ════════════════════════ 2. 语义缓存 ════════════════════════════════════

class SemanticCache:
    """
    基于查询内容哈希的轻量缓存。
    
    逻辑：
    - 对 question 做 MD5 哈希作为 key
    - 相同问题在 TTL 内直接返回缓存结果，不调 API
    - LRU策略：最多缓存 max_entries 条，超出的淘汰最老的
    - 只缓存正常成功的响应，错误/空响应不缓存
    
    适用场景：
    - 群里多人问相似的问题（"多少钱""怎么买""群规是什么"）
    - 新闻播报同一时间段多次触发
    - 问候语在同一段时间内内容相近
    
    不缓存的场景：
    - hook/nudge/convert 等「必须每次不同」的模式
    - 带 seed 参数的调用（seed本身就是防重复的）
    - 连续对话的反问（依赖上下文）
    """
    
    # 这些模式的输出要求每次都不同，永远不缓存
    NO_CACHE_MODES = {"hook", "nudge", "convert", "convert_soft"}
    
    def __init__(self, ttl: int = 3600, max_entries: int = 200):
        self.ttl = ttl            # 缓存有效期（秒），默认1小时
        self.max_entries = max_entries  # 最大缓存条数
        self._cache: OrderedDict[str, dict] = OrderedDict()  # {hash: {text, time, mode, hits}}
        self._lock = threading.Lock()
        
        # 统计
        self._hits = 0
        self._misses = 0
    
    @staticmethod
    def _make_key(question: str, mode: str) -> str:
        """生成缓存key：MD5(question + mode）"""
        raw = f"{mode}:::{question}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()
    
    def should_cache(self, mode: str, seed: int = 0) -> bool:
        """判断该调用是否应该走缓存"""
        if mode in self.NO_CACHE_MODES:
            return False
        if seed > 0:
            return False
        return True
    
    def get(self, question: str, mode: str) -> str | None:
        """查缓存，命中返回文本，未命中返回None"""
        if not self.should_cache(mode):
            return None
        
        key = self._make_key(question, mode)
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if time.time() - entry["time"] <= self.ttl:
                    entry["hits"] += 1
                    self._hits += 1
                    # LRU：移到末尾（最近访问）
                    self._cache.move_to_end(key)
                    logger.debug(f"📦 缓存命中: mode={mode}, key={key[:8]}..., "
                                f"已命中{entry['hits']}次")
                    return entry["text"]
                else:
                    # 过期了，删除
                    del self._cache[key]
            
            self._misses += 1
            return None
    
    def put(self, question: str, mode: str, text: str):
        """写入缓存"""
        if not self.should_cache(mode) or not text:
            return
        
        key = self._make_key(question, mode)
        with self._lock:
            # 如果已存在则更新（原地修改，保留LRU位置）
            if key in self._cache:
                self._cache[key]["text"] = text
                self._cache[key]["time"] = time.time()
                self._cache[key]["mode"] = mode
                self._cache[key]["hits"] = 0
                self._cache.move_to_end(key)
                return
            
            # 超出上限，淘汰最老的
            while len(self._cache) >= self.max_entries:
                evicted_key, _ = self._cache.popitem(last=False)
            
            self._cache[key] = {"text": text, "time": time.time(), 
                                 "mode": mode, "hits": 0}
    
    def invalidate(self, pattern: str = None):
        """
        清除缓存。
        pattern=None: 全部清除
        pattern=模式名: 只清除该模式的缓存
        """
        with self._lock:
            if pattern is None:
                count = len(self._cache)
                self._cache.clear()
                logger.info(f"🗑️ 缓存已全部清除（{count}条）")
                return count
            
            to_remove = [k for k, v in self._cache.items() if v["mode"] == pattern]
            for k in to_remove:
                del self._cache[k]
            logger.info(f"🗑️ 缓存已清除模式'{pattern}'（{len(to_remove)}条）")
            return len(to_remove)
    
    def get_stats(self) -> dict:
        """获取缓存统计信息"""
        with self._lock:
            total = len(self._cache)
            by_mode = {}
            for v in self._cache.values():
                m = v["mode"]
                by_mode[m] = by_mode.get(m, 0) + 1
            
            return {
                "total_entries": total,
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / max(1, self._hits + self._misses), 3),
                "by_mode": by_mode,
            }


# ════════════════════════ 3. 令牌桶限流 ════════════════════════════════════

class TokenBucket:
    """
    令牌桶限流器 —— 防止短时间内API调用过多导致429雪崩。
    
    逻辑：
    - 桶容量 capacity 个令牌，每秒 refill_rate 个令牌补充
    - 每次 API 调用前 acquire(1)，拿到令牌才放行
    - 桶空了就等待直到有令牌（或超时放弃）
    - 全局单桶，所有模型共享
    
    参数说明：
    - capacity=10: 桶最多存10个令牌（即突发最多允许10次并发调用）
    - refill_rate=2: 每秒补2个令牌（即平均每秒最多2次API调用）
    - 这对 DashScope 的免费额度足够友好
    """
    
    def __init__(self, capacity: int = 10, refill_rate: float = 2.0):
        self.capacity = capacity
        self.refill_rate = refill_rate  # 每秒补充令牌数
        self._tokens = float(capacity)
        self._last_refill = time.time()
        self._lock = threading.Lock()
        
        # 统计
        self._total_acquired = 0
        self._total_rejected = 0
    
    def _refill(self):
        """补充令牌（内部方法，必须在锁内调用）"""
        now = time.time()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(
                self.capacity,
                self._tokens + elapsed * self.refill_rate
            )
            self._last_refill = now
    
    def acquire(self, timeout: float = 5.0) -> bool:
        """
        获取一个令牌。
        timeout: 最大等待秒数（超时返回False）
        """
        deadline = time.time() + timeout
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._total_acquired += 1
                    return True
                
                # 计算需要等多久
                wait_time = (1.0 - self._tokens) / self.refill_rate
            
            # 桶空了，等待一会儿再试
            remaining = deadline - time.time()
            if remaining <= 0:
                self._total_rejected += 1
                logger.warning("⚠️ 令牌桶：等待超时，本次API调用被限流丢弃")
                return False
            
            time.sleep(min(wait_time, 0.1))
    
    
    def try_acquire(self) -> bool:
        """非阻塞式获取令牌，桶空立即返回False"""
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self._total_acquired += 1
                return True
            return False
    
    def get_stats(self) -> dict:
        """获取令牌桶统计"""
        with self._lock:
            self._refill()
            return {
                "available_tokens": round(self._tokens, 2),
                "capacity": self.capacity,
                "refill_per_sec": self.refill_rate,
                "total_acquired": self._total_acquired,
                "total_rejected": self._total_rejected,
            }


# ════════════════════════ 优化管理器 ══════════════════════════════════════

class OptimizerManager:
    """
    优化模块统一管理器。
    
    将三个优化模块整合为一个入口，供 ai_engine.py 调用。
    初始化后通过 manager.circuit / manager.cache / manager.limiter 访问各模块。
    """
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        
        # 三个核心模块
        self.circuit = CircuitBreaker(threshold=3, cooldown=300)
        self.cache = SemanticCache(ttl=86400, max_entries=200)
        self.limiter = TokenBucket(capacity=10, refill_rate=2.0)
        
        logger.info("⚡ 优化引擎初始化完成：熔断器 + 语义缓存(TTL=24h,200条) + 令牌桶(10桶/2每秒)")
    
    def get_full_report(self) -> dict:
        """生成完整诊断报告（管理员指令用）"""
        return {
            "enabled": self.enabled,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "circuit_breaker": self.circuit.get_all_status(),
            "cache": self.cache.get_stats(),
            "rate_limiter": self.limiter.get_stats(),
        }
