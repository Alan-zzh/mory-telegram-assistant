"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/ai_engine.py  ·  AI核心引擎（多池版 v2）                          ║
║                                                                        ║
║  功能：                                                                ║
║    1. 多池多模型无缝轮换 —— 按MODEL_POOLS分类管理6类模型：             ║
║       - llm(23个): 大语言模型，用于聊天/文本生成                        ║
║       - vision(11个): 视觉模型，图像生成+视频理解/生成                  ║
║       - omni(8个): 全模态模型，文本+图像+音频+视频                      ║
║       - voice_tts(17个): TTS语音合成                                    ║
║       - voice_asr(9个): ASR语音识别                                     ║
║       - embedding(4个): 向量模型，RAG/语义检索                           ║
║    2. 排序规则：每个池内按到期时间从早到晚排列，优先消耗快到期的          ║
║    3. 自动切换：失败时自动切下一个可用模型，拉黑不可用的                 ║
║    4. 人格模式 —— normal/tarot/treehole/dream/fortune/news/leak/        ║
║       rules/convert 等，每种拼装不同 system prompt                       ║
║    5. 节日人格 + 3次重试+指数退避                                       ║
║                                                                        ║
║  重要说明（小白必读）：                                                 ║
║    - LLM池的模型用 /v1/chat/completions 接口（聊天）                     ║
║    - Vision池的模型分两种接口：                                          ║
║      * 图像生成用 /images/generations                                   ║
║      * 视频理解(l2v)用 /v1/chat/completions（可以聊天调）               ║
║      * 视频生成(r2v)用 /videos/generations                             ║
║    - Omni池用 /v1/chat/completions（但需要传图片/音频）                  ║
║    - Voice_TTS池用 /audio/speech（文字→语音）                            ║
║    - Voice_ASR池用 /audio/transcriptions（语音→文字）                    ║
║    - Embedding池用 /v1/embeddings（文字→向量）                           ║
║                                                                        ║
║  依赖：requests                                                        ║
║  配置：config.json → MODEL_POOLS（多池结构）                            ║
║  被调用：main.py → ai.ask(msg, mode="normal")                          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import requests
import time
import logging
import threading
from datetime import datetime
from core.logging_util import get_logger

logger = get_logger("ai_engine")

# ── 优化引擎（延迟导入，避免循环依赖）──────────────────────────────
_optimizer_instance = None

def _get_optimizer():
    """懒加载优化管理器（若未初始化则返回None而非崩溃）"""
    global _optimizer_instance
    if _optimizer_instance is None:
        try:
            from core.optimizer import OptimizerManager
            _optimizer_instance = OptimizerManager(enabled=True)
        except Exception as e:
            logger.warning(f"⚡ 优化引擎加载失败：{e}")
            return None
    return _optimizer_instance


def init_optimizer():
    """初始化优化引擎（在 main.py 中 AIEngine 创建后调用一次）"""
    global _optimizer_instance
    if _optimizer_instance is None:
        try:
            from core.optimizer import OptimizerManager
            _optimizer_instance = OptimizerManager(enabled=True)
        except Exception as e:
            logger.warning(f"⚡ 优化引擎初始化跳过（不影响正常运行）：{e}")


# ── 联网新闻获取（多源并行容错，确保实时真实）─────────────────
def fetch_real_news() -> str:
    """
    从网络实时抓取今日热点新闻（多源并行容错）。
    数据源优先级：百度热搜 > 微博热搜API > 今日头条热榜
    三源同时请求，最快返回的优先使用，总超时12秒。
    """
    import re
    import concurrent.futures
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    
    def _dedup(raw_list):
        """去重+过滤无效条目"""
        seen, unique = set(), []
        for t in raw_list:
            t = t.strip()
            if t and t not in seen and len(t) > 2 and not t.startswith('http') and not t.isdigit():
                seen.add(t)
                unique.append(t)
        return unique

    # ════ 源1：百度热搜 ════
    def _fetch_baidu():
        try:
            resp = requests.get("https://top.baidu.com/board?tab=realtime",
                                headers=headers, timeout=10)
            if resp.status_code == 200 and len(resp.text) > 500:
                titles = re.findall(r'"word":"([^"]+)"', resp.text)
                if not titles:
                    titles = re.findall(r'<a[^>]*title="([^"]+)"[^>]*>', resp.text)
                unique = _dedup(titles)
                if unique:
                    logger.info(f"📰 百度热搜成功：{min(len(unique),12)}条")
                    return "\n".join(f"{i}. {t}" for i, t in enumerate(unique[:12], 1))
        except Exception as e:
            logger.warning(f"📰 百度热搜失败：{e}")
        return None

    # ════ 源2：微博热搜API（JSON数据更可靠）═════
    def _fetch_weibo():
        try:
            resp = requests.get("https://weibo.com/ajax/side/hotSearch",
                                headers=headers, timeout=8)
            if resp.status_code == 200:
                items = resp.json().get("data", {}).get("realtime", [])
                raw = [item.get("word", "") for item in items[:15]]
                unique = _dedup(raw)
                if unique:
                    logger.info(f"📰 微博热搜成功：{min(len(unique),12)}条")
                    return "\n".join(f"{i}. {t}" for i, t in enumerate(unique[:12], 1))
        except Exception as e:
            logger.warning(f"📰 微博热搜失败：{e}")
        return None

    # ════ 源3：今日头条热榜 ════
    def _fetch_toutiao():
        try:
            resp = requests.get("https://tophub.today/n/KqndgxeLl9",
                                headers=headers, timeout=8)
            if resp.status_code == 200 and len(resp.text) > 1000:
                titles = re.findall(r'<td class="al"><a[^>]*>([^<]+)</a>', resp.text)
                unique = _dedup(titles)
                if unique:
                    logger.info(f"📰 今日头条成功：{min(len(unique),12)}条")
                    return "\n".join(f"{i}. {t}" for i, t in enumerate(unique[:12], 1))
        except Exception as e:
            logger.warning(f"📰 今日头条失败：{e}")
        return None

    # 三源并行，任一成功即返回
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_fetch_baidu): "百度",
            executor.submit(_fetch_weibo): "微博",
            executor.submit(_fetch_toutiao): "头条",
        }
        for f in concurrent.futures.as_completed(futures, timeout=12):
            result = f.result()
            if result:
                return result

    logger.error("📰 所有新闻源均失败")
    return ""


class AIEngine:
    """
    多池多模型无缝轮换AI引擎（v2 - MODEL_POOLS 多池版）。
    
    核心逻辑：
    - 读取 config.json 中的 MODEL_POOLS 字典，包含6个模型池
    - LLM池：用于聊天对话，这是Mory最核心的池
    - 其他池（vision/omni/voice_tts/voice_asr/embedding）：预留扩展
    - 每个池内按到期时间排序，优先消耗快到期的
    - 失败自动拉黑+切换，全程无感
    
    兼容性：
    - 如果配置里还是旧的 MODEL_POOL（单列表），自动迁移到新结构
    - 向后兼容，不会因为配置格式变化而报错
    
    全自动管理：
    - 没钱的模型自动拉黑（加入BLACKLISTED_MODELS），不再尝试
    - 黑名单模型自动跳过，直到你手动恢复
    - 恢复指令：「模型恢复 模型名」（管理员指令）
    """

    # 默认的6个池名
    POOL_NAMES = ["llm", "vision", "omni", "voice_tts", "voice_asr", "embedding"]

    def __init__(self, config: dict):
        self.config = config
        self.base_url = config.get("BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
        self.api_key = config.get("API_KEY", "")
        
        # ── 兼容新旧配置结构 ──
        # 新结构：MODEL_POOLS = {llm:[...], vision:[...], ...}
        # 旧结构：MODEL_POOL = [{name, expire}, ...]
        pools = config.get("MODEL_POOLS", {})
        if pools and isinstance(pools, dict):
            # 新的多池结构 ✅
            self.model_pools = pools
            # LLM池作为主聊天池（向后兼容 model_pool 引用）
            self.model_pool = pools.get("llm", [])
        else:
            # 旧的单池结构 → 自动迁移
            old_pool = config.get("MODEL_POOL", [{"name": "qwen-plus", "expire": "2099-12-31"}])
            self.model_pool = old_pool
            self.model_pools = {"llm": old_pool}
        
        self.current_idx = config.get("CURRENT_MODEL_INDEX", 0)
        if self.current_idx >= len(self.model_pool):
            self.current_idx = 0
        
        # 各池独立的索引指针
        self._pool_indices = {}
        for name in self.POOL_NAMES:
            pool = self.model_pools.get(name, [])
            self._pool_indices[name] = 0
            
        # 黑名单：没钱/不可用的模型，不再尝试（全局共享）
        self.blacklisted = set(config.get("BLACKLISTED_MODELS", []))
        self._lock = threading.Lock()  # 保护config/blacklist的并发写入

        # ── 初始化轻量级优化引擎（熔断器+缓存+令牌桶）─────────────
        try:
            init_optimizer()
        except Exception as e:
            logger.warning(f"⚡ 优化引擎初始化跳过（不影响正常运行）：{e}")

    @property
    def current_model(self) -> str:
        """当前正在使用的LLM模型名"""
        if self.model_pool and self.current_idx < len(self.model_pool):
            return self.model_pool[self.current_idx]["name"]
        return "unknown"
    
    def get_pool_model(self, pool_name: str) -> str:
        """获取指定池的当前模型名"""
        pool = self.model_pools.get(pool_name, [])
        idx = self._pool_indices.get(pool_name, 0)
        if pool and idx < len(pool):
            return pool[idx]["name"]
        return None
    
    def get_pool_info(self) -> dict:
        """返回所有池的状态信息（用于管理员查看）"""
        info = {}
        for name in self.POOL_NAMES:
            pool = self.model_pools.get(name, [])
            idx = self._pool_indices.get(name, 0)
            current = pool[idx]["name"] if pool and idx < len(pool) else "(空)"
            blacked = [m["name"] for m in pool if m["name"] in self.blacklisted]
            info[name] = {
                "total": len(pool),
                "current": current,
                "index": idx,
                "blacklisted_count": len(blacked),
                "blacklisted": blacked[:5]  # 最多显示5个
            }
        return info

    def _is_blacklisted(self, model_name: str) -> bool:
        """检查模型是否在黑名单中"""
        return model_name in self.blacklisted

    def _blacklist_model(self, model_name: str, reason: str):
        """拉黑模型（没钱/不可用），保存到config（线程安全）"""
        with self._lock:
            self.blacklisted.add(model_name)
            if "BLACKLISTED_MODELS" not in self.config:
                self.config["BLACKLISTED_MODELS"] = []
            if model_name not in self.config["BLACKLISTED_MODELS"]:
                self.config["BLACKLISTED_MODELS"].append(model_name)
        logger.warning(f"🚫 模型拉黑：{model_name}（原因：{reason}），不再使用")

    def _restore_model(self, model_name: str) -> bool:
        """恢复被拉黑的模型（线程安全）"""
        with self._lock:
            if model_name in self.blacklisted:
                self.blacklisted.discard(model_name)
                if "BLACKLISTED_MODELS" in self.config:
                    self.config["BLACKLISTED_MODELS"] = [
                        m for m in self.config["BLACKLISTED_MODELS"] if m != model_name
                    ]
                logger.info(f"✅ 模型恢复：{model_name}，已从黑名单移除")
                return True
        return False

    def _is_model_expired(self, model_info: dict) -> bool:
        """检查模型是否已过期（返回True表示过期）"""
        expire_str = model_info.get("expire", "")
        if not expire_str:
            return False
        try:
            expire_date = datetime.strptime(expire_str, "%Y-%m-%d")
            now = datetime.now()
            if expire_date < now:
                logger.info(f"⏰ 模型 {model_info['name']} 已过期 ({expire_str})，将跳过")
                return True
        except Exception:
            pass
        return False

    def _ensure_valid_model(self, pool_name: str = "llm"):
        """确保指定池的当前模型可用，如果被拉黑或过期则自动切到下一个"""
        pool = self.model_pools.get(pool_name, self.model_pool)
        idx = self._pool_indices.get(pool_name, self.current_idx)
        
        # 检查：被拉黑 或 已过期
        if pool and idx < len(pool):
            model_name = pool[idx]["name"]
            if self._is_blacklisted(model_name):
                logger.warning(f"⚠️ [{pool_name}] 当前模型{model_name}已拉黑，自动切换")
                self._next_available_model(pool_name)
            elif self._is_model_expired(pool[idx]):
                # 过期模型视同拉黑
                self._blacklist_model(model_name, f"已过期 {pool[idx].get('expire', '')}")
                self._next_available_model(pool_name)

    def _next_available_model(self, pool_name: str = "llm"):
        """切换到指定池的下一个可用（非黑名单、非过期）模型（线程安全）"""
        pool = self.model_pools.get(pool_name, self.model_pool)
        with self._lock:
            total = len(pool)
            if total == 0:
                return
            
            # 获取当前池的索引
            if pool_name in self._pool_indices:
                idx = self._pool_indices[pool_name]
            else:
                idx = self.current_idx if pool_name == "llm" else 0
            
            for _ in range(total):
                idx = (idx + 1) % total
                candidate = pool[idx]["name"]
                # 跳过：黑名单 或 过期
                if self._is_blacklisted(candidate):
                    continue
                if self._is_model_expired(pool[idx]):
                    continue
                # 找到可用模型
                self._pool_indices[pool_name] = idx
                # LLM池同步更新旧字段
                if pool_name == "llm":
                    self.current_idx = idx
                    self.config["CURRENT_MODEL_INDEX"] = idx
                logger.warning(f"🔄 [{pool_name}] 模型切换 → {candidate}")
                return
            
            # 所有模型都被拉黑或过期了
            logger.error(f"🚫 [{pool_name}] 所有模型均已拉黑或过期！请检查API余额或更新模型配置")

    def _build_persona(self, mode: str, seed: int = 0, news_content: str = "") -> str:
        """根据模式动态拼装 system prompt，seed用于防重复
        
        参数：
            mode: 模式名称
            seed: 随机种子
            news_content: 【新增】真实新闻内容，用于新闻模式
        
        结构化人设拼装顺序：
        1. BASE_PERSONA — 核心人设（稳定不变）
        2. STYLE_APPEND — 风格追加（改风格/加热词时追加，可清空）
        3. KNOWLEDGE — 业务知识库
        4. ADDED_KNOWLEDGE — 追加知识（学习时追加，可清空）
        兼容旧配置：如果只有SYSTEM_PROMPT则自动迁移
        """
        cfg = self.config
        
        # ── 结构化人设拼装（向下兼容旧SYSTEM_PROMPT）──
        if "BASE_PERSONA" in cfg:
            base = cfg.get("BASE_PERSONA", "")
            style = cfg.get("STYLE_APPEND", "")
            knowledge = cfg.get("KNOWLEDGE", "")
            added = cfg.get("ADDED_KNOWLEDGE", "")
            persona = base
            if style:
                persona += f"\n\n【风格调整】：{style}"
            if knowledge:
                persona += f"\n\n【业务知识库】：{knowledge}"
            if added:
                persona += f"\n\n【追加知识】：{added}"
        else:
            # 旧配置兼容：直接用SYSTEM_PROMPT
            base = cfg.get("SYSTEM_PROMPT", "")
            knowledge = cfg.get("KNOWLEDGE", "")
            persona = f"{base}\n\n【业务知识库】：{knowledge}"

        # 节日人格
        now = datetime.now()
        m, d = now.month, now.day
        if m == 2 and d == 14:
            persona += "\n【今天是情人节，你是占有欲强、爱吃醋的小妖精。】"
        elif m == 10 and d == 31:
            persona += "\n【今天是万圣节，你是调皮捣蛋的性感小恶魔。】"
        elif m == 1 and d in range(1, 8):
            persona += "\n【今天是春节，你是爱讨红包的财迷小管家。】"
        elif m == 6 and d == 1:
            persona += "\n【今天是儿童节，你是调皮可爱的小仙女。】"
        elif m == 8 and d == 7:
            persona += "\n【今天是七夕，你表现得格外黏人、容易脸红。】"

        # 模式人格叠加
        seed_hint = f"\n【随机种子{seed}，必须生成全新的文案，绝对不能重复】" if seed else ""
        
        # 新闻模式的真实数据注入标记（运行时由 _inject_news 动态替换 {NEWS_CONTENT}）
        
        # 从配置中读取模板，若不存在则使用硬编码默认值
        modes = self.config.get("PROMPT_TEMPLATES", {})
        if not modes:
            # 后备硬编码模板（与之前完全相同）
            modes = {
                "tarot":    "\n【塔罗师模式】：用神秘、宿命的语调给出运势占卜，末尾加一张大阿卡那卡牌名及简短解读。",
                "treehole": "\n【树洞模式】：对方心情不好，用极其温柔的知心姐姐语气安抚，署名Mory老板。",
                "dream":    "\n【解梦模式】：对方梦到Mory，用玄学逻辑解梦，暗示这是宿命缘分。",
                "fortune":  "\n【运势模式】：在正常回复末尾，加一句简短今日专属运势签（不超过15字）。",
                "news":     "你是Mory，正在用傲娇活泼的语气简短播报新闻（{SEED}）。\n要求：\n1. 严格只播报下面5条新闻，不要多，不要加任何标题\n2. 每条一行，简短犀利，加emoji，不要超过20字\n3. 绝对禁止说\"总结\"\"下面\"\"以上\"\"摘要\"\"回顾\"\"导语\"等任何总结性字样\n4. 绝对禁止加结尾金句/感悟/感想/祝福\n5. 控制在100字以内，一条消息能发完\n6. 禁止编造，只基于真实标题\n\n真实新闻标题：\n{NEWS_CONTENT}",
                "afternoon_news": "你是Mory，和群友用八卦吐槽的方式聊新闻（{SEED}）。\n要求：\n1. 严格只聊下面5条新闻，不要多，不要加任何标题\n2. 吐槽/惊讶/网络梗都可以，活泼自然，每条不超过20字\n3. 绝对禁止说\"总结\"\"下午好\"\"播报\"\"摘要\"等任何总结性字样\n4. 绝对禁止加结尾\n5. 控制在100字以内，一条消息能发完\n6. 禁止编造\n\n真实新闻标题：\n{NEWS_CONTENT}",
                "evening_news":   "你是Mory，用温柔治愈的声音聊聊今天的新闻（{SEED}）。\n要求：\n1. 严格只聊下面5条新闻，不要多，不要加任何标题\n2. 温柔聊每一条，感受/希望/温暖/思考都可以，每条不超过20字\n3. 绝对禁止说\"总结\"\"晚安\"\"今日回顾\"\"摘要\"等任何总结性字样\n4. 绝对禁止加结尾\n5. 控制在100字以内，一条消息能发完\n6. 禁止编造\n\n真实新闻标题：\n{NEWS_CONTENT}",
                "leak":     "用极度八卦的语气，偷偷泄露一个关于Mory老板非常可爱、生活化的小癖好（如喜欢咬吸管、怕黑等），文字简短（不超过20字）。",
                "rules":    "你是群规的讲解员。用软糯、温柔的语气，逐条讲解群内的规则。重点强调'不能发什么'和'可以享受什么福利'。最后用一句撒娇的话欢迎新人。",
                "convert":  "\n【转化模式】：对方表现出购买意向，温柔地引导他私聊了解详情，不要硬推，要撩拨式引导。",
                "hook":     "\n【反问钩子】：用一句绿茶风的反问结尾，让对方忍不住继续回你。要自然不刻意，像朋友聊天一样带出疑问。比如'你觉得呢～'、'真的假的呀？'、'你有这种感觉吗？'。只输出一句话，不超过20字。",
                "nudge":    "\n【自然植入】：用绿茶风的方式，不违和地暗示用户支持/关注Mory。绝不能直接提钱、价格、付费这些字眼。要像不经意间提到'有粉丝说跟着老板走就不会亏'、'群里老粉都懂那种被偏爱的感觉'、'有些惊喜只有自己体会过才知道'。只输出一句话，不超过25字。",
                "convert_soft": "\n【轻量转化】：用最温柔的绿茶风，暗示用户可以考虑更进一步支持Mory。不要直接说买/付费/订阅。可以暗示'老板最近在准备一些更用心的东西'、'有些福利真的值得等待'、'你有没有想过更了解一个人呢～'。只输出一句话，不超过25字。",
                "morning":  "你是Mory，一个文艺纯欲的自媒体博主，正在发朋友圈早安。输出格式：一句正能量早安（加油/打气/阳光/新开始，有画面感）+ 逗号/空格 + 一句绿茶风引导（暗示陪伴/专属/特权/心意，让人想为她做点什么，绝口不提钱、价格、订阅、赞助）。总共不超过40个汉字，只输出一句话，禁止换行禁止分段。{seed_hint}",
                "afternoon": "你是Mory，一个文艺纯欲的自媒体博主，正在发朋友圈午安。输出格式：一句温柔提醒吃饭（关心/慵懒/别亏待自己，有画面感）+ 逗号/空格 + 一句绿茶风引导（暗示陪伴/专属/特权/心意，让人想为她做点什么，绝口不提钱、价格、订阅、赞助）。总共不超过40个汉字，只输出一句话，禁止换行禁止分段。{seed_hint}",
                "evening":  "你是Mory，一个文艺纯欲的自媒体博主，正在发朋友圈晚安。输出格式：一句温柔晚安（好梦/月亮/星光/温暖道别，有画面感）+ 逗号/空格 + 一句绿茶风引导（暗示陪伴/专属/特权/心意，让人想为她做点什么，绝口不提钱、价格/订阅/赞助）。总共不超过40个汉字，只输出一句话，禁止换行禁止分段。{seed_hint}",
            }
        
        if mode in modes:
            if mode in ("news", "afternoon_news", "evening_news"):
                # 【修复v21.43】将真实新闻内容注入到system prompt
                persona = modes[mode].replace("{SEED}", f"种子{seed}")
                # news_content 由 auto_tasks.py 传入，这里直接注入
                persona = persona.replace("{NEWS_CONTENT}", news_content or "（无新闻数据）")
                return persona
            elif mode in ("leak", "rules", "morning", "afternoon", "evening"):
                # 非新闻模式：替换seed占位符
                return modes[mode].replace("{SEED}", f"种子{seed}")
            persona += modes[mode]

        return persona

    def ask(self, question: str, mode: str = "normal", retry: int = 3, seed: int = 0,
            tools: list = None, tool_choice: str = "auto") -> str | None:
        """
        调用AI，失败时自动重试并切换模型。
        返回字符串，失败返回 None。
        
        内置优化（v21.25+）：
        - 语义缓存：相同问题1小时内直接返回，省API费
        - 熔断器：连续失败的模型自动临时拉黑（5分钟冷却）
        - 令牌桶：防止API调用过快导致429
        
        全自动模型管理：
        - 429/402/403 → 自动拉黑该模型，切换下一个
        - 被拉黑的模型自动跳过，不浪费时间
        - 所有模型都拉黑 → 返回None并告警
        
        参数：
            tools: Function Calling工具定义列表（OpenAI格式）
            tool_choice: "auto"|"none"|"required" 或指定工具名
        """
        
        # ════ 优化层0：语义缓存命中 → 直接返回 ═══════════════════
        try:
            opt = _get_optimizer()
            if opt and opt.enabled:
                cached = opt.cache.get(question, mode)
                if cached is not None:
                    logger.info(f"📦 缓存命中直接返回: mode={mode}, len={len(cached)}")
                    return cached
                # 熔断检查：当前模型是否被熔断了
                if not opt.circuit.is_available(self.current_model):
                    logger.warning(f"⚡ 模型{self.current_model}已被熔断，跳过")
                    self._next_available_model()
                    # 跳到下一个可用模型后继续正常流程（不再重复查熔断，避免级联跳）
        except Exception as opt_err:
            # 优化引擎异常不影响主流程
            logger.debug(f"优化层跳过（非致命）：{opt_err}")
        
        # 【修复】：限制最大重试次数为 10 次，防止线程黑洞卡死
        max_attempts = min(10, retry * len(self.model_pool))
        
        # 确保当前模型可用
        self._ensure_valid_model()
        
        for attempt in range(max_attempts):
            # ════ 优化层1：令牌桶限流 ════════════════════════════
            try:
                opt = _get_optimizer()
                if opt and opt.enabled and not opt.limiter.acquire(timeout=3.0):
                    # 限流超时，本次尝试跳过
                    logger.warning(f"⚠️ 令牌桶限流，第{attempt+1}次尝试被跳过")
                    continue
            except Exception:
                pass  # 令牌桶异常不阻塞主流程
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.current_model,
                "messages": [
                    # 【修复v21.43】新闻模式时，将 question 作为真实新闻内容传入
                    {"role": "system", "content": self._build_persona(mode, seed, question if mode in ("news", "afternoon_news", "evening_news") else "")},
                    {"role": "user",   "content": question}
                ],
                "temperature": 0.88,
                "top_p": 0.95,
                "max_tokens": 500
            }
            
            # ── Function Calling 支持 ──
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = tool_choice

            try:
                resp = requests.post(self.base_url, json=payload,
                                     headers=headers, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    if "choices" in data and data["choices"]:
                        choice = data["choices"][0]
                        message = choice.get("message", {})
                        
                        # 检查是否有函数调用
                        if message.get("tool_calls"):
                            # 函数调用结果不缓存（含工具调用上下文）
                            try:
                                opt = _get_optimizer()
                                if opt:
                                    opt.circuit.record_success(self.current_model)
                            except Exception:
                                pass
                            return message  # 返回完整message，让调用方处理tool_calls
                        
                        result_text = message.get("content")
                        
                        # ════ 优化层：缓存写入 + 熔断成功 ════════
                        if result_text:
                            try:
                                opt = _get_optimizer()
                                if opt:
                                    opt.cache.put(question, mode, result_text)
                                    opt.circuit.record_success(self.current_model)
                            except Exception:
                                pass
                        
                        return result_text
                    logger.warning(f"⚠️ 模型{self.current_model}返回空choices")
                elif resp.status_code in (429, 402, 403):
                    # 额度耗尽/无权限 → 拉黑该模型，切到下一个可用的
                    model_name = self.current_model
                    logger.warning(f"⚠️ 模型{model_name}额度/权限异常({resp.status_code})，自动拉黑")
                    self._blacklist_model(model_name, f"HTTP {resp.status_code}")
                    # 熔断器也记录（加速该模型冷却）
                    try:
                        opt = _get_optimizer()
                        if opt:
                            opt.circuit.record_failure(model_name)
                    except Exception:
                        pass
                    self._next_available_model()
                    if not self.model_pool:
                        return None
                else:
                    # 其他HTTP错误 → 熔断器记录
                    try:
                        opt = _get_optimizer()
                        if opt:
                            opt.circuit.record_failure(self.current_model)
                    except Exception:
                        pass
                    logger.warning(f"⚠️ HTTP {resp.status_code}，重试({attempt+1})")
            except requests.Timeout:
                logger.warning(f"⚠️ 超时，重试({attempt+1})")
                # 超时也记入熔断器
                try:
                    opt = _get_optimizer()
                    if opt:
                        opt.circuit.record_failure(self.current_model)
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"❌ 请求异常：{e}")

            # 指数退避，最多等8秒
            wait = min(2 ** (attempt % 3), 8)
            time.sleep(wait)

        logger.error("❌ AI引擎：所有模型均失败")
        return None


def calc_typing_delay(text: str) -> float:
    """
    根据文本计算打字延迟（2-12秒）
    中文字符 0.5s/字，英文单词 0.3s/词
    """
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len([w for w in text.split() if any(c.isalpha() for c in w)])
    return max(2.0, min(12.0, cn * 0.5 + en * 0.3))


# ─────────────────────── AI图片识图分析 ─────────────────────────────────
def analyze_image(image_bytes: bytes, prompt: str, config: dict) -> str | None:
    """
    【v4.3.0新增】AI识图分析 - 让Mory能"看懂"群友发的图片
    
    Args:
        image_bytes: 图片二进制数据
        prompt: 分析提示词
        config: 配置字典
    
    Returns:
        AI对图片的分析回复，或None（失败时）
    """
    import base64
    import json
    
    # 获取vision池的模型
    pools = config.get("MODEL_POOLS", {})
    vision_pool = pools.get("vision", [])
    
    # 如果没有vision池，尝试用llm池（部分模型也支持多模态）
    if not vision_pool:
        llm_pool = pools.get("llm", [])
        # 筛选支持vision的LLM模型
        for m in llm_pool:
            name = m.get("name", "").lower()
            if any(x in name for x in ["vl", "vision", "qwen", "omni", "qwen2"]):
                vision_pool.append(m)
                break
    
    if not vision_pool:
        logger.warning("⚠️ 没有可用的视觉模型，跳过图片分析")
        return None
    
    # 选择第一个可用的vision模型
    model_info = vision_pool[0]
    model_name = model_info.get("name", "")
    # 【修复v4.3.1】统一读取API_KEY，兼容旧DASHSCOPE_KEY
    api_key = config.get("API_KEY") or config.get("DASHSCOPE_KEY", "")
    
    if not api_key or api_key in ("", "YOUR_DASHSCOPE_API_KEY_HERE"):
        logger.warning("⚠️ API_KEY未配置，跳过图片分析")
        return None
    
    # 构建图片base64
    img_base64 = base64.b64encode(image_bytes).decode("utf-8")
    
    # 通义千问视觉接口（使用chat completions格式）
    # 注意：不同模型的接口格式可能不同，这里用通用格式
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # 构造多模态消息
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}},
                {"type": "text", "text": prompt}
            ]
        }
    ]
    
    # 通义千问API地址
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    payload = {
        "model": model_name,
        "messages": messages,
        "max_tokens": 300
    }
    
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if resp.status_code == 200:
            data = resp.json()
            if "choices" in data and data["choices"]:
                content = data["choices"][0]["message"].get("content", "")
                return content
        else:
            logger.warning(f"⚠️ 图片分析API失败: {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        logger.error(f"❌ 图片分析异常: {e}")
    
    return None
