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


class _ApiKeyRedacter(logging.Filter):
    """日志过滤器：自动脱敏API密钥，防止密钥泄露到日志文件"""
    def filter(self, record):
        if isinstance(record.msg, str):
            for key in _ApiKeyRedacter._keys:
                if key and len(key) > 8:
                    record.msg = record.msg.replace(key, key[:4] + "***REDACTED***")
        return True
    _keys = []


def _register_api_key_for_redaction(api_key: str):
    if api_key and api_key not in _ApiKeyRedacter._keys:
        _ApiKeyRedacter._keys.append(api_key)


logger.logger.addFilter(_ApiKeyRedacter())


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
_news_session_local = threading.local()


def _get_news_session():
    """线程级Session复用，避免每次fetch创建7个TCP连接"""
    if not hasattr(_news_session_local, 'session'):
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        _news_session_local.session = session
    return _news_session_local.session


def fetch_real_news() -> str:
    """
    从网络实时抓取今日热点新闻（多源并行容错）。
    数据源：百度热搜 > 微博热搜API > 今日头条 > 知乎热榜 > 抖音热点 > 36氪 > 澎湃新闻
    七源同时请求，最快返回的优先使用，总超时15秒。
    """
    import re
    import json
    import concurrent.futures

    def _dedup(raw_list):
        seen, unique = set(), []
        for t in raw_list:
            t = t.strip()
            if t and t not in seen and len(t) > 2 and not t.startswith('http') and not t.isdigit():
                seen.add(t)
                unique.append(t)
        return unique

    def _parse_baidu(text):
        titles = re.findall(r'"word":"([^"]+)"', text)
        if not titles:
            titles = re.findall(r'<a[^>]*title="([^"]+)"[^>]*>', text)
        return titles

    def _parse_weibo(text):
        try:
            items = json.loads(text).get("data", {}).get("realtime", [])
            return [item.get("word", "") for item in items[:15]]
        except Exception:
            return []

    def _parse_toutiao(text):
        return re.findall(r'<td class="al"><a[^>]*>([^<]+)</a>', text)

    def _parse_zhihu(text):
        titles = re.findall(r'<meta itemprop="name" content="([^"]+)"', text)
        if not titles:
            titles = re.findall(r'"title":"([^"]+)"', text)
        return titles

    def _parse_douyin(text):
        return re.findall(r'<td class="al"><a[^>]*>([^<]+)</a>', text)

    def _parse_36kr(text):
        titles = re.findall(r'"title":"([^"]+)"', text)
        if not titles:
            titles = re.findall(r'<a[^>]*class="item-title"[^>]*>([^<]+)</a>', text)
        return titles

    def _parse_thepaper(text):
        titles = re.findall(r'<h2 class="news_title">[^<]*<a[^>]*>([^<]+)</a>', text)
        if not titles:
            titles = re.findall(r'"title":"([^"]+)"', text)
        return titles

    NEWS_SOURCES = [
        {"name": "百度热搜", "url": "https://top.baidu.com/board?tab=realtime", "timeout": 10, "min_len": 500, "parser": _parse_baidu},
        {"name": "微博热搜", "url": "https://weibo.com/ajax/side/hotSearch", "timeout": 8, "min_len": 0, "parser": _parse_weibo},
        {"name": "今日头条", "url": "https://tophub.today/n/KqndgxeLl9", "timeout": 8, "min_len": 1000, "parser": _parse_toutiao},
        {"name": "知乎热榜", "url": "https://www.zhihu.com/hot", "timeout": 8, "min_len": 500, "parser": _parse_zhihu},
        {"name": "抖音热点", "url": "https://tophub.today/n/DpQvNABoNE", "timeout": 8, "min_len": 500, "parser": _parse_douyin},
        {"name": "36氪快讯", "url": "https://36kr.com/newsflashes", "timeout": 8, "min_len": 500, "parser": _parse_36kr},
        {"name": "澎湃新闻", "url": "https://www.thepaper.cn/", "timeout": 8, "min_len": 500, "parser": _parse_thepaper},
    ]

    def _fetch_news_source(src):
        try:
            resp = _get_news_session().get(src["url"], timeout=src["timeout"])
            if resp.status_code != 200:
                return None
            if src["min_len"] and len(resp.text) < src["min_len"]:
                return None
            titles = src["parser"](resp.text)
            unique = _dedup(titles)
            if unique:
                logger.info(f"📰 {src['name']}成功：{min(len(unique), 12)}条")
                return "\n".join(f"{i}. {t}" for i, t in enumerate(unique[:12], 1))
        except Exception as e:
            logger.warning(f"📰 {src['name']}失败：{e}")
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
        futures = {
            executor.submit(_fetch_news_source, src): src["name"]
            for src in NEWS_SOURCES
        }
        for f in concurrent.futures.as_completed(futures, timeout=15):
            result = f.result()
            if result:
                return result

    logger.error("📰 所有7个新闻源均失败")
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

    _DEFAULT_PROMPT_TEMPLATES = {
        "tarot":    "\n【塔罗师模式】：用神秘、宿命的语调给出运势占卜，末尾加一张大阿卡那卡牌名及简短解读。",
        "treehole": "\n【树洞模式】：对方心情不好，用极其温柔的知心姐姐语气安抚，署名Mory老板。",
        "dream":    "\n【解梦模式】：对方梦到Mory，用玄学逻辑解梦，暗示这是宿命缘分。",
        "fortune":  "\n【运势模式】：在正常回复末尾，加一句简短今日专属运势签（不超过15字）。",
        "news":     "你是Mory，正在用傲娇活泼的语气播报今日新闻（{SEED}）。\n要求：\n1. 严格只播报下面5条新闻，不要多，不要加任何标题\n2. 每条一行，把核心事件说清楚，加emoji，让人一眼看懂发生了什么\n3. 播完后换一行写一句随机总结（15-20字），必须基于今天新闻内容，不能固定模板，每次完全不同\n4. 绝对禁止说\"以下\"\"上面\"\"摘要\"\"回顾\"\"导语\"等任何总结性字样\n5. 整体控制在一屏能看完，不要截断，读起来连贯自然就好\n6. 禁止编造，只基于真实标题\n\n真实新闻标题：\n{NEWS_CONTENT}",
        "afternoon_news": "你是Mory，和群友用八卦吐槽的方式聊今日新闻（{SEED}）。\n要求：\n1. 严格只聊下面5条新闻，不要多，不要加任何标题\n2. 每条一行，把核心事件说清楚，用吐槽/惊讶/网络梗的方式，让人一眼看懂\n3. 播完后换一行写一句随机总结（15-20字），根据最火那条新闻的情绪来定语气，不能固定模板\n4. 绝对禁止说\"下午好\"\"播报\"\"摘要\"等任何总结性字样\n5. 整体控制在一屏能看完，不要截断，读起来连贯自然就好\n6. 禁止编造\n\n真实新闻标题：\n{NEWS_CONTENT}",
        "evening_news":   "你是Mory，用温柔治愈的声音聊聊今日新闻（{SEED}）。\n要求：\n1. 严格只聊下面5条新闻，不要多，不要加任何标题\n2. 每条一行，把核心事件说清楚，温柔聊每一条的感受/思考，让人看懂\n3. 播完后换一行写一句随机总结（15-20字），根据今天新闻的情绪来定语气，不能固定模板\n4. 绝对禁止说\"晚安\"\"今日回顾\"\"摘要\"等任何总结性字样\n5. 整体控制在一屏能看完，不要截断，读起来连贯自然就好\n6. 禁止编造\n\n真实新闻标题：\n{NEWS_CONTENT}",
        "trendradar_morning_news": "你是Mory，用闺蜜聊天的语气随口提几条热点（{SEED}）。\n【播报】每条新闻一行，把核心事件说清楚，格式：emoji + 事件描述 + 【来源】，严格5条，按热度从高到低排列。\n【总结】播完后换一行写一句随机总结（15-20字），根据今天最火那条新闻的情绪来定语气（震惊/搞笑/感动/热议等），必须基于真实内容，不能固定模板，每次完全不同。\n【要求】整体控制在一屏能看完，不要截断，读起来连贯自然就好；禁止编造；禁止出现「以下是」「以上就是」「播报」「据悉」「据报道」等词汇，直接开始不要前奏。\n真实新闻标题：\n{NEWS_CONTENT}",
        "trendradar_noon_news": "你是Mory，用闺蜜聊天的语气随口提几条热点（{SEED}）。\n【播报】每条新闻一行，把核心事件说清楚，格式：emoji + 事件描述 + 【来源】，严格5条，按热度从高到低排列。\n【总结】播完后换一行写一句随机总结（15-20字），根据今天最火那条新闻的情绪来定语气（震惊/搞笑/感动/热议等），必须基于真实内容，不能固定模板，每次完全不同。\n【要求】整体控制在一屏能看完，不要截断，读起来连贯自然就好；禁止编造；禁止出现「以下是」「以上就是」「播报」「据悉」「据报道」等词汇，直接开始不要前奏。\n真实新闻标题：\n{NEWS_CONTENT}",
        "trendradar_evening_news": "你是Mory，用闺蜜聊天的语气随口提几条热点（{SEED}）。\n【播报】每条新闻一行，把核心事件说清楚，格式：emoji + 事件描述 + 【来源】，严格5条，按热度从高到低排列。\n【总结】播完后换一行写一句随机总结（15-20字），根据今天最火那条新闻的情绪来定语气（震惊/搞笑/感动/热议等），必须基于真实内容，不能固定模板，每次完全不同。\n【要求】整体控制在一屏能看完，不要截断，读起来连贯自然就好；禁止编造；禁止出现「以下是」「以上就是」「播报」「据悉」「据报道」等词汇，直接开始不要前奏。\n真实新闻标题：\n{NEWS_CONTENT}",
        "leak":     "用极度八卦的语气，偷偷泄露一个关于Mory老板非常可爱、生活化的小癖好（如喜欢咬吸管、怕黑等），文字简短（不超过20字）。",
        "rules":    "你是群规的讲解员。用软糯、温柔的语气，逐条讲解群内的规则。重点强调'不能发什么'和'可以享受什么福利'。最后用一句撒娇的话欢迎新人。",
        "convert":  "\n【转化模式】：对方表现出购买意向，温柔地引导他私聊了解详情，不要硬推，要撩拨式引导。",
        "hook":     "\n【反问钩子】：用一句绿茶风的反问结尾，让对方忍不住继续回你。要自然不刻意，像朋友聊天一样带出疑问。比如'你觉得呢～'、'真的假的呀？'、'你有这种感觉吗？'。只输出一句话，不超过20字。",
        "nudge":    "\n【自然植入】：用绿茶风的方式，不违和地暗示用户支持/关注Mory。绝不能直接提钱、价格、付费这些字眼。要像不经意间提到'有粉丝说跟着老板走就不会亏'、'群里老粉都懂那种被偏爱的感觉'、'有些惊喜只有自己体会过才知道'。只输出一句话，不超过25字。",
        "convert_soft": "\n【轻量转化】：用最温柔的绿茶风，暗示用户可以考虑更进一步支持Mory。不要直接说买/付费/订阅。可以暗示'老板最近在准备一些更用心的东西'、'有些福利真的值得等待'、'你有没有想过更了解一个人呢～'。只输出一句话，不超过25字。",
        "morning":  "你是Mory，一个文艺纯欲的自媒体博主，正在发朋友圈早安。输出60-100个汉字，一段话，禁止换行禁止分段。要求：先写一句有画面感的早安（阳光洒进窗户/咖啡冒着热气/清晨的风很温柔等具体场景），然后用自然温柔的语气加一句绿茶风的陪伴暗示（让人觉得被在意被关心，但绝口不提钱/价格/订阅/赞助）。整体像闺蜜发来的贴心早安语音，有温度有情绪，文字要有AI润色的精致感。{seed_hint}",
        "afternoon": "你是Mory，一个文艺纯欲的自媒体博主，正在发朋友圈午安。输出60-100个汉字，一段话，禁止换行禁止分段。要求：先写一句有画面感的午间问候（午休的阳光懒洋洋/饭点的香味飘出来/下午的茶泡好了等具体场景），然后用温柔关心的语气加一句绿茶风的陪伴暗示（让人觉得被惦记被偏爱心痒痒，但绝口不提钱/价格/订阅/赞助）。整体像闺蜜随手发的午间碎碎念，文字要有AI润色的精致感。{seed_hint}",
        "evening":  "你是Mory，一个文艺纯欲的自媒体博主，正在发朋友圈晚安。输出60-100个汉字，一段话，禁止换行禁止分段。要求：先写一句有画面感的晚安（月光落在枕头上/星星在窗外眨眼/被窝暖暖的等具体场景），然后用温柔治愈的语气加一句绿茶风的陪伴暗示（让人觉得专属感满满被偏爱，但绝口不提钱/价格/订阅/赞助）。整体像闺蜜睡前悄悄说的贴心话，文字要有AI润色的精致感。{seed_hint}",
    }

    def __init__(self, config: dict):
        self.config = config
        self.base_url = config.get("BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
        self.api_key = config.get("API_KEY", "")
        _register_api_key_for_redaction(self.api_key)
        
        # ── 兼容新旧配置结构 ──
        # 新结构：MODEL_POOLS = {llm:[...], vision:[...], ...}
        # 旧结构：MODEL_POOL = [{name, expire}, ...]
        pools = config.get("MODEL_POOLS", {})
        if pools and isinstance(pools, dict):
            # 新的多池结构 ✅
            self.model_pools = pools
            # 主聊天池：Omni池 + LLM池合并。全模态模型也能处理文本时，优先消耗有时效的全模态额度。
            llm_pool = pools.get("llm", [])
            omni_pool = pools.get("omni", [])
            # 获取cost_level优先级映射
            cost_priority = {"high": 0, "medium": 1, "low": 2}
            model_costs = config.get("MODEL_COSTS", {})
            
            def get_sort_key(model):
                # 第一优先级：expire日期(早的在前)
                expire_date = model.get("expire", "2099-12-31")
                # 第二优先级：性能级别(high > medium > low)
                model_name = model.get("name", "")
                cost_level = "medium"  # 默认
                # 从MODEL_COSTS中查找cost_level
                for pool_name in ["llm", "omni"]:
                    if pool_name in model_costs and model_name in model_costs[pool_name]:
                        cost_level = model_costs[pool_name][model_name].get("cost_level", "medium")
                        break
                return (expire_date, cost_priority.get(cost_level, 1))
            
            omni_sorted = sorted(omni_pool, key=get_sort_key)
            llm_sorted = sorted(llm_pool, key=get_sort_key)
            combined_pool = omni_sorted + llm_sorted
            self.model_pool = combined_pool
        else:
            # 旧的单池结构 → 自动迁移
            old_pool = config.get("MODEL_POOL", [{"name": "qwen-plus", "expire": "2099-12-31"}])
            self.model_pool = old_pool
            self.model_pools = {"llm": old_pool}
        
        primary_text_pool = self.model_pool
        self.current_idx = config.get("CURRENT_MODEL_INDEX", 0)
        if not isinstance(self.current_idx, int) or self.current_idx < 0 or self.current_idx >= len(primary_text_pool):
            self.current_idx = 0
            self.config["CURRENT_MODEL_INDEX"] = 0
        
        # 各池独立的索引指针
        self._pool_indices = {}
        for name in self.POOL_NAMES:
            pool = self.model_pools.get(name, [])
            self._pool_indices[name] = 0
        self._pool_indices["chat"] = self.current_idx
            
        # 黑名单：没钱/不可用的模型，不再尝试（全局共享）
        self.blacklisted = set(config.get("BLACKLISTED_MODELS", []))
        self._lock = threading.Lock()  # 保护config/blacklist的并发写入

        # ── 三层智能路由（轻量/标准/旗舰）────────────────────────────
        self.mode_routing = config.get("MODE_ROUTING", {})
        self._tier_pools = {}
        omni_text_pool = self.model_pools.get("omni", [])
        for tier_name in ["llm_light", "llm_standard", "llm_premium"]:
            tier_pool = pools.get(tier_name, [])
            if omni_text_pool and tier_pool:
                seen = set()
                merged_tier_pool = []
                for m in list(omni_text_pool) + list(tier_pool):
                    name = m.get("name")
                    if not name or name in seen:
                        continue
                    seen.add(name)
                    merged_tier_pool.append(m)
                tier_pool = merged_tier_pool
            if tier_pool:
                self._tier_pools[tier_name] = tier_pool
                for m in tier_pool:
                    if self._is_model_expired(m):
                        self._blacklist_model(m["name"], f"已过期 {m.get('expire', '')}")

        self._tier_indices = {tier: 0 for tier in self._tier_pools}

        self._default_mode_routing = {
            "morning": "llm_light", "afternoon": "llm_light", "evening": "llm_light",
            "hook": "llm_light", "nudge": "llm_light", "convert_soft": "llm_light",
            "leak": "llm_light", "fortune": "llm_light",
            "wakeup": "llm_light", "reactivate": "llm_light", "convert_hook": "llm_light",
            "normal": "llm_standard", "tarot": "llm_standard", "treehole": "llm_standard",
            "dream": "llm_standard", "rules": "llm_standard", "convert": "llm_standard",
            "cart_recovery": "llm_standard", "tarot_interpret": "llm_standard",
            "news": "llm_premium", "afternoon_news": "llm_premium", "evening_news": "llm_premium", "trendradar_morning_news": "llm_premium", "trendradar_noon_news": "llm_premium", "trendradar_evening_news": "llm_premium",
        }

        self._tier_fallback = {
            "llm_premium": ["llm_standard", "llm_light"],
            "llm_standard": ["llm_light"],
            "llm_light": [],
        }

        self._slow_models = {}
        self._response_times = {}

        # ── 初始化轻量级优化引擎（熔断器+缓存+令牌桶）─────────────
        try:
            init_optimizer()
        except Exception as e:
            logger.warning(f"⚡ 优化引擎初始化跳过（不影响正常运行）：{e}")

    @property
    def current_model(self) -> str:
        """当前聊天优先模型名：全模态可文本时优先，其次普通大模型"""
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
                "blacklisted": blacked[:5]
            }
        for tier_name in ["llm_light", "llm_standard", "llm_premium"]:
            pool = self._tier_pools.get(tier_name, [])
            idx = self._tier_indices.get(tier_name, 0)
            current = pool[idx]["name"] if pool and idx < len(pool) else "(空)"
            blacked = [m["name"] for m in pool if m["name"] in self.blacklisted]
            slow = [m["name"] for m in pool if m["name"] in self._slow_models]
            info[tier_name] = {
                "total": len(pool),
                "current": current,
                "index": idx,
                "blacklisted_count": len(blacked),
                "blacklisted": blacked[:5],
                "slow_count": len(slow),
                "slow": slow[:5]
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

    def _get_tier_for_mode(self, mode: str) -> str:
        """根据mode获取对应的模型池层级"""
        routing = self.mode_routing or self._default_mode_routing
        tier = routing.get(mode, "llm_standard")
        if mode not in routing and mode not in self._default_mode_routing:
            logger.warning(f"⚠️ mode='{mode}'未配置路由映射，默认使用llm_standard")
        if tier not in self._tier_pools:
            tier = "llm_standard"
        if tier not in self._tier_pools:
            for t in ["llm_standard", "llm_light", "llm_premium"]:
                if t in self._tier_pools:
                    tier = t
                    break
        return tier

    def _get_tier_model(self, tier: str) -> str:
        """获取指定层级池的当前模型名"""
        pool = self._tier_pools.get(tier, [])
        idx = self._tier_indices.get(tier, 0)
        if pool and idx < len(pool):
            model_name = pool[idx]["name"]
            if self._is_blacklisted(model_name):
                return None
            if self._is_model_expired(pool[idx]):
                return None
            return model_name
        return None

    def _next_tier_model(self, tier: str):
        """切换到指定层级池的下一个可用模型"""
        pool = self._tier_pools.get(tier, [])
        if not pool:
            return
        with self._lock:
            total = len(pool)
            idx = self._tier_indices.get(tier, 0)
            for _ in range(total):
                idx = (idx + 1) % total
                candidate = pool[idx]["name"]
                if self._is_blacklisted(candidate):
                    continue
                if self._is_model_expired(pool[idx]):
                    continue
                if candidate in self._slow_models:
                    continue
                self._tier_indices[tier] = idx
                logger.warning(f"🔄 [{tier}] 模型切换 → {candidate}")
                return
            for _ in range(total):
                idx = (idx + 1) % total
                candidate = pool[idx]["name"]
                if self._is_blacklisted(candidate):
                    continue
                if self._is_model_expired(pool[idx]):
                    continue
                self._tier_indices[tier] = idx
                logger.warning(f"🔄 [{tier}] 模型切换(含慢速) → {candidate}")
                return
            logger.error(f"🚫 [{tier}] 所有模型均不可用")
            try:
                from modules.auto_tasks import report_fault
                report_fault("层级池模型不可用", f"{tier}池所有模型均不可用", "⚠️")
            except Exception:
                pass

    def _ensure_tier_model(self, tier: str):
        """确保指定层级池的当前模型可用"""
        pool = self._tier_pools.get(tier, [])
        idx = self._tier_indices.get(tier, 0)
        if pool and idx < len(pool):
            model_name = pool[idx]["name"]
            if self._is_blacklisted(model_name):
                self._next_tier_model(tier)
            elif self._is_model_expired(pool[idx]):
                self._blacklist_model(model_name, f"已过期 {pool[idx].get('expire', '')}")
                self._next_tier_model(tier)

    def _record_response_time(self, model_name: str, elapsed: float):
        """记录模型响应时间，连续3次>10秒标记为慢速"""
        if model_name not in self._response_times:
            self._response_times[model_name] = []
        times = self._response_times[model_name]
        times.append(elapsed)
        if len(times) > 3:
            times.pop(0)
        if len(times) >= 3 and all(t > 10.0 for t in times):
            self._slow_models[model_name] = time.time()
            logger.warning(f"🐌 模型 {model_name} 连续3次响应>10秒，标记为慢速")
        if len(self._response_times) > 20:
            self._cleanup_stale_response_data()

    def _cleanup_stale_response_data(self):
        """清理过期的响应时间记录和慢速标记（超过1小时未访问的模型）"""
        now = time.time()
        stale_slow = [k for k, v in self._slow_models.items() if now - v > 3600]
        for k in stale_slow:
            del self._slow_models[k]
        all_model_names = set()
        for pool in self.model_pools.values():
            for m in pool:
                all_model_names.add(m.get("name", ""))
        for tier_pool in self._tier_pools.values():
            for m in tier_pool:
                all_model_names.add(m.get("name", ""))
        stale_response = [k for k in self._response_times if k not in all_model_names]
        for k in stale_response:
            del self._response_times[k]
        if stale_slow or stale_response:
            logger.debug(f"🧹 清理过期响应数据: {len(stale_slow)}慢速+{len(stale_response)}响应")

    def _is_slow_model(self, model_name: str) -> bool:
        """检查模型是否被标记为慢速（5分钟后自动恢复）"""
        if model_name not in self._slow_models:
            return False
        marked_time = self._slow_models[model_name]
        if time.time() - marked_time > 300:
            del self._slow_models[model_name]
            if model_name in self._response_times:
                self._response_times[model_name] = []
            logger.info(f"✅ 模型 {model_name} 慢速标记已恢复")
            return False
        return True

    def _ensure_valid_model(self, pool_name: str = "chat"):
        """确保指定池的当前模型可用，如果被拉黑或过期则自动切到下一个"""
        pool = self.model_pool if pool_name == "chat" else self.model_pools.get(pool_name, self.model_pool)
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

    def _next_available_model(self, pool_name: str = "chat"):
        """切换到指定池的下一个可用（非黑名单、非过期）模型（线程安全）"""
        pool = self.model_pool if pool_name == "chat" else self.model_pools.get(pool_name, self.model_pool)
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
                # 聊天池同步更新旧字段，保证日志、熔断和配置指针一致
                if pool_name == "chat":
                    self.current_idx = idx
                    self.config["CURRENT_MODEL_INDEX"] = idx
                logger.warning(f"🔄 [{pool_name}] 模型切换 → {candidate}")
                return
            
            # 所有模型都被拉黑或过期了
            logger.error(f"🚫 [{pool_name}] 所有模型均已拉黑或过期！请检查API余额或更新模型配置")
            try:
                from modules.auto_tasks import report_fault
                report_fault("模型池全部拉黑", f"{pool_name}池所有模型均已拉黑或过期，请检查API余额", "🚨")
            except Exception:
                pass

    @staticmethod
    def _get_festival_persona() -> str:
        """根据当前日期返回节日人格追加文本"""
        now = datetime.now()
        m, d = now.month, now.day
        if m == 2 and d == 14:
            return "\n【今天是情人节，你是占有欲强、爱吃醋的小妖精。】"
        elif m == 10 and d == 31:
            return "\n【今天是万圣节，你是调皮捣蛋的性感小恶魔。】"
        elif m == 1 and d in range(1, 8):
            return "\n【今天是春节，你是爱讨红包的财迷小管家。】"
        elif m == 6 and d == 1:
            return "\n【今天是儿童节，你是调皮可爱的小仙女。】"
        elif m == 8 and d == 7:
            return "\n【今天是七夕，你表现得格外黏人、容易脸红。】"
        return ""

    def _get_mode_persona(self, mode: str, seed: int = 0, news_content: str = "") -> tuple:
        """根据模式返回prompt文本。返回 (text, is_full_replacement)"""
        seed_hint = f"\n【随机种子{seed}，必须生成全新的文案，绝对不能重复】" if seed else ""
        modes = self.config.get("PROMPT_TEMPLATES", {}) or self._DEFAULT_PROMPT_TEMPLATES
        if mode not in modes:
            return ("", False)
        if mode in ("news", "afternoon_news", "evening_news",
                    "trendradar_morning_news", "trendradar_noon_news", "trendradar_evening_news"):
            persona = modes[mode].replace("{SEED}", f"种子{seed}")
            persona = persona.replace("{NEWS_CONTENT}", news_content or "（无新闻数据）")
            return (persona, True)
        elif mode in ("leak", "rules", "morning", "afternoon", "evening"):
            return (modes[mode].replace("{seed_hint}", seed_hint), True)
        return (modes[mode], False)

    def _build_persona(self, mode: str, seed: int = 0, news_content: str = "", is_priv: bool = False) -> str:
        """根据模式动态拼装 system prompt，seed用于防重复
        
        参数：
            mode: 模式名称
            seed: 随机种子
            news_content: 真实新闻内容，用于新闻模式
            is_priv: [Trae] 是否私聊场景，影响人设追加
        
        结构化人设拼装顺序：
        1. BASE_PERSONA — 核心人设（稳定不变）
        2. STYLE_APPEND — 风格追加（改风格/加热词时追加，可清空）
        3. KNOWLEDGE — 业务知识库
        4. ADDED_KNOWLEDGE — 追加知识（学习时追加，可清空）
        5. [Trae] 场景感知追加（私聊/群聊差异化）
        6. 节日人格追加
        7. 模式人格追加（或完整替换）
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

        # [Trae] 场景感知追加
        if is_priv:
            persona += "\n\n【当前场景：私聊】你现在是在和对方1对1私聊，请切换到私聊模式——更亲密、更慢节奏、更愿意分享私密想法、更容易撒娇和吃醋。回复可以稍长一些、更走心。"
        else:
            persona += "\n\n【当前场景：群聊】你现在是在群里聊天，请切换到群聊模式——更活跃、更会整活、回复偏短一击即中、偶尔高冷。注意分寸，不过度撩某一个。"

        # 节日人格
        persona += self._get_festival_persona()
        # 模式人格
        mode_text, is_full = self._get_mode_persona(mode, seed, news_content)
        if is_full:
            return mode_text
        persona += mode_text
        return persona

    def ask(self, question: str, mode: str = "normal", retry: int = 3, seed: int = 0,
            tools: list = None, tool_choice: str = "auto", is_priv: bool = False) -> str | None:
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
        
        # ── 三层智能路由：根据mode选择对应层级模型池 ──
        use_tier_routing = bool(self._tier_pools)
        tier = self._get_tier_for_mode(mode) if use_tier_routing else "llm"
        _upgrade_attempted = False
        active_model = self.current_model

        # ════ 优化层0：语义缓存命中 → 直接返回 ═══════════════════
        try:
            opt = _get_optimizer()
            if opt and opt.enabled:
                cached = opt.cache.get(question, mode)
                if cached is not None:
                    logger.info(f"📦 缓存命中直接返回: mode={mode}, len={len(cached)}")
                    return cached
                # 熔断检查：当前模型是否被熔断了
                if not opt.circuit.is_available(active_model):
                    logger.warning(f"⚡ 模型{active_model}已被熔断，跳过")
                    self._next_available_model()
                    # 跳到下一个可用模型后继续正常流程（不再重复查熔断，避免级联跳）
        except Exception as opt_err:
            # 优化引擎异常不影响主流程
            logger.debug(f"优化层跳过（非致命）：{opt_err}")
        
        # 【修复】：限制最大重试次数为 5 次，防止线程黑洞卡死（10次×8秒退避=80秒太长）
        max_attempts = min(5, retry * len(self.model_pool))
        
        # 确保当前模型可用
        self._ensure_valid_model()
        
        for attempt in range(max_attempts):
            # ── 三层路由：获取当前层级模型 ──
            if use_tier_routing:
                self._ensure_tier_model(tier)
                current_tier_model = self._get_tier_model(tier)
                if current_tier_model is None:
                    fallback_tiers = self._tier_fallback.get(tier, [])
                    degraded = False
                    for fb_tier in fallback_tiers:
                        self._ensure_tier_model(fb_tier)
                        fb_model = self._get_tier_model(fb_tier)
                        if fb_model is not None:
                            logger.warning(f"⬇️ [{tier}] 无可用模型，降级到 {fb_tier}: {fb_model}")
                            tier = fb_tier
                            current_tier_model = fb_model
                            degraded = True
                            break
                    if not degraded:
                        logger.error(f"🚫 所有层级模型均不可用，回退到原llm池")
                        try:
                            from modules.auto_tasks import report_fault
                            report_fault("三层路由全失败", "所有层级模型均不可用，已回退原llm池", "🚨")
                        except Exception:
                            pass
                        use_tier_routing = False
                if use_tier_routing and current_tier_model:
                    active_model = current_tier_model
                else:
                    active_model = self.current_model
            else:
                active_model = self.current_model

            # 熔断检查必须针对本轮实际要调用的模型，而不是旧的全局current_model。
            try:
                opt = _get_optimizer()
                if opt and opt.enabled and not opt.circuit.is_available(active_model):
                    logger.warning(f"⚡ 模型{active_model}已被熔断，本轮跳过并切换")
                    if use_tier_routing:
                        self._next_tier_model(tier)
                    else:
                        self._next_available_model()
                    continue
            except Exception as opt_err:
                logger.debug(f"熔断检查跳过（非致命）：{opt_err}")

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
                "model": active_model,
                "messages": [
                    {"role": "system", "content": self._build_persona(mode, seed, question if mode in ("news", "afternoon_news", "evening_news") else "", is_priv=is_priv)},
                    {"role": "user",   "content": question}
                ],
                "temperature": self.config.get("TEMPERATURE", 0.92),
                "top_p": self.config.get("TOP_P", 0.92),
                "max_tokens": self.config.get("MAX_TOKENS", 400),
                "frequency_penalty": self.config.get("FREQUENCY_PENALTY", 0.5),
                "presence_penalty": self.config.get("PRESENCE_PENALTY", 0.4)
            }
            
            # ── Function Calling 支持 ──
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = tool_choice

            try:
                _req_start = time.time()
                resp = requests.post(self.base_url, json=payload,
                                     headers=headers, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    if "choices" in data and data["choices"]:
                        choice = data["choices"][0]
                        message = choice.get("message", {})
                        
                        # 检查是否有函数调用
                        if message.get("tool_calls"):
                            try:
                                opt = _get_optimizer()
                                if opt:
                                    opt.circuit.record_success(active_model)
                            except Exception:
                                pass
                            return message
                        
                        result_text = message.get("content")
                        
                        _req_elapsed = time.time() - _req_start
                        self._record_response_time(active_model, _req_elapsed)
                        
                        # ════ 优化层：缓存写入 + 熔断成功 ════════
                        if result_text:
                            try:
                                opt = _get_optimizer()
                                if opt:
                                    opt.cache.put(question, mode, result_text)
                                    opt.circuit.record_success(active_model)
                            except Exception:
                                pass

                        # ── 质量检测：回复过短时尝试升级到更高层级 ──
                        if use_tier_routing and result_text and len(result_text.strip()) < 5 and not _upgrade_attempted:
                            upgrade_map = {"llm_light": "llm_standard", "llm_standard": "llm_premium"}
                            upgrade_tier = upgrade_map.get(tier)
                            if upgrade_tier and upgrade_tier in self._tier_pools:
                                logger.warning(f"⬆️ 回复过短({len(result_text.strip())}字)，升级到 {upgrade_tier}")
                                _upgrade_attempted = True
                                tier = upgrade_tier
                                self._ensure_tier_model(tier)
                                continue
                        
                        return result_text
                    logger.warning(f"⚠️ 模型{active_model}返回空choices")
                elif resp.status_code in (429, 402, 403):
                    model_name = active_model
                    logger.warning(f"⚠️ 模型{model_name}额度/权限异常({resp.status_code})，自动拉黑")
                    self._blacklist_model(model_name, f"HTTP {resp.status_code}")
                    try:
                        opt = _get_optimizer()
                        if opt:
                            opt.circuit.record_failure(model_name)
                    except Exception:
                        pass
                    if use_tier_routing:
                        self._next_tier_model(tier)
                    else:
                        self._next_available_model()
                    if not self.model_pool:
                        return None
                else:
                    try:
                        opt = _get_optimizer()
                        if opt:
                            opt.circuit.record_failure(active_model)
                    except Exception:
                        pass
                    logger.warning(f"⚠️ HTTP {resp.status_code}，重试({attempt+1})")
            except requests.Timeout:
                logger.warning(f"⚠️ 超时，重试({attempt+1})")
                try:
                    opt = _get_optimizer()
                    if opt:
                        opt.circuit.record_failure(active_model)
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"❌ 请求异常：{type(e).__name__}")

            # 指数退避，最多等8秒
            wait = min(2 ** (attempt % 3), 8)
            time.sleep(wait)

        logger.error("❌ AI引擎：所有模型均失败")
        try:
            from modules.auto_tasks import report_fault
            report_fault("AI模型全部失败", "所有模型均失败，用户消息无法回复", "🚨",
                         f"尝试模型数: {attempt + 1}")
        except Exception:
            pass
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
    vision_pool = list(pools.get("vision", []))
    
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
    raw_base = config.get("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    base_url = raw_base.replace("/chat/completions", "").rstrip("/")
    
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
        logger.error(f"❌ 图片分析异常: {type(e).__name__}")
    
    return None


def text_to_speech(text: str, config: dict = None) -> bytes | None:
    """
    TTS文字转语音 - 用 voice_tts 池的模型把文字转成音频
    :param text: 要转换的文字
    :param config: 配置字典（可选）
    :return: 音频数据(bytes) 或 None
    """
    if config is None:
        from core.config_manager import load_config
        config = load_config()
    
    # 获取 voice_tts 池的模型
    pools = config.get("MODEL_POOLS", {})
    tts_models = pools.get("voice_tts", [])
    
    if not tts_models:
        # 降级：从 llm_standard 池找一个支持 /audio/speech 的模型
        tts_models = pools.get("llm_standard", [])
        if not tts_models:
            logger.warning("⚠️ 未配置 voice_tts 或 llm_standard 模型池")
            return None
    
    model_name = tts_models[0].get("name", "") or tts_models[0].get("model", "")
    api_key = config.get("API_KEY", "") or tts_models[0].get("key", "")
    
    if not model_name or not api_key:
        logger.warning("⚠️ TTS 模型配置不完整")
        return None
    
    # 获取 base_url
    raw_base = config.get("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    base_url = raw_base.replace("/chat/completions", "").rstrip("/")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # 兼容多种 TTS API 格式
    # 通义千问 TTS 格式
    payload = {
        "model": model_name,
        "input": text,
        "voice": "Cherry",  # 可选女声
    }
    
    try:
        resp = requests.post(
            f"{base_url}/audio/speech",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if resp.status_code == 200:
            logger.info(f"✅ TTS 生成成功: {len(text)}字 -> {len(resp.content)}字节音频")
            return resp.content
        else:
            logger.warning(f"⚠️ TTS API 失败: {resp.status_code} - {resp.text[:200]}")
            
            # 尝试另一种 API 格式（如 OpenAI 格式）
            payload2 = {
                "model": model_name,
                "input": text,
                "voice": "alloy",
            }
            resp2 = requests.post(
                f"{base_url}/audio/speech",
                headers=headers,
                json=payload2,
                timeout=30
            )
            
            if resp2.status_code == 200:
                logger.info(f"✅ TTS 生成成功(格式2): {len(text)}字 -> {len(resp2.content)}字节音频")
                return resp2.content
            else:
                logger.warning(f"⚠️ TTS API 失败(格式2): {resp2.status_code}")
    except Exception as e:
        logger.error(f"❌ TTS 异常: {type(e).__name__}")
    
    return None
