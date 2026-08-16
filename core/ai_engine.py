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
import random
import re
import os
from datetime import datetime, timezone, timedelta, date as _date_mod
from collections import deque
from core.logging_util import get_logger

logger = get_logger("ai_engine")

_CST = timezone(timedelta(hours=8))

# ── [v5.33] 情绪光谱比例锁：进程级缓冲，统计最近 bot 回复的情绪符号 ──
_EMOTION_BUFFER_SIZE = 20  # 最近 20 条 bot 回复
_recent_bot_replies = deque(maxlen=_EMOTION_BUFFER_SIZE)
# 波浪号日配额追踪（≤5/天，集中在熟人/撒娇场景）
_wave_tilde_daily: dict = {"date": "", "count": 0}


def _record_bot_reply_for_emotion(text: str):
    """[v5.33] 记录 bot 回复到全局缓冲，并累计波浪号日配额

    在 ask() 返回回复前调用，用于 _get_emotion_ratio_hint() 统计情绪比例。
    """
    global _wave_tilde_daily
    if not text:
        return
    try:
        _recent_bot_replies.append(text)
        today = _date_mod.today().isoformat()
        if _wave_tilde_daily["date"] != today:
            _wave_tilde_daily = {"date": today, "count": 0}
        # 统计全角+半角波浪号
        cnt = text.count("～") + text.count("~")
        if cnt > 0:
            _wave_tilde_daily["count"] += cnt
    except Exception as e:
        logger.debug(f"波浪号统计更新跳过（非致命）：{e}")


def _get_emotion_ratio_hint() -> str:
    """[v5.33] 情绪光谱比例锁 - 超阈值反向提示

    基于 SYSTEM_PROMPT 的 13 条去AI铁律中的情绪配额：
    - 每轮感叹号 ≤1（铁律 #3）
    - 每轮省略号 ≤1（铁律 #1）
    - 波浪号月配额 ≤5/天（铁律 #2，此处按日累计）

    返回反向提示文本，无超阈值则返回空串。
    """
    try:
        if not _recent_bot_replies:
            return ""
        hints = []
        recent = list(_recent_bot_replies)[-10:]  # 最近 10 条
        sample_size = len(recent)

        # 感叹号检测：每轮 ≤1，>30% 违规则提示
        if sample_size >= 5:
            exclaim_violations = sum(
                1 for t in recent if t.count("！") + t.count("!") > 1
            )
            if exclaim_violations / sample_size > 0.3:
                hints.append("最近感叹号偏多，这轮别用感叹号，改用句号或省略号收尾。")

        # 省略号检测：每轮 ≤1，>30% 违规则提示
        if sample_size >= 5:
            ellipsis_violations = sum(
                1 for t in recent if t.count("…") + t.count("...") > 1
            )
            if ellipsis_violations / sample_size > 0.3:
                hints.append("最近省略号偏密，这轮换种语气，少用或不用省略号。")

        # 波浪号日配额：≤5/天
        today = _date_mod.today().isoformat()
        if _wave_tilde_daily.get("date") == today and _wave_tilde_daily.get("count", 0) >= 5:
            hints.append("今日波浪号配额已满（≤5/天），这轮严禁使用～或~。")

        if not hints:
            return ""
        return "\n\n【情绪比例锁（v5.33 代码强制）】\n" + "\n".join(hints)
    except Exception as e:
        logger.debug(f"情绪比例锁提示计算跳过（非致命）：{e}")
        return ""


# ── [v5.33] 去AI结构性铁律：进程级校验，复用 _recent_bot_replies 缓冲 ──
# 排比句模式（覆盖铁律 #7：拒绝AI喜欢的对仗式输出）
_PARALLEL_PATTERNS = (
    "既……又", "既……也", "既...又", "既...也",
    "不仅……而且", "不仅...而且", "不仅……还", "不仅...还",
    "一方面……另一方面", "一方面...另一方面",
    "有的……有的", "有的...有的",
    "一会儿……一会儿", "一会儿...一会儿",
    "又……又", "又...又",
)
# 价格触发关键词（覆盖铁律 #13：价格不主动提，用户问了才答）
_PRICE_KEYWORDS = (
    "价格", "多少钱", "价位", "报价", "费用",
    "块钱", "毛钱", "人民币", "日元", "美元",
    "￥", "¥", "$", "€",
    "打折", "折扣", "优惠", "促销", "满减",
)


def _get_anti_ai_style_hint() -> str:
    """[v5.33] 去AI结构性铁律 - 基于最近回复统计，超阈值反向提示

    覆盖 SYSTEM_PROMPT 13 条铁律中尚未代码化的 4 条：
    - 铁律 #4：整段 ≤2 行，每行 ≤15 字（防长篇大论 AI 味）
    - 铁律 #5：每轮数字/英文 ≤1 处（防列表式信息堆砌）
    - 铁律 #7：拒绝排比（防 AI 喜欢的对仗式输出）
    - 铁律 #13：价格不主动提（用户问了才答，防销售味过浓）

    返回反向提示文本，无超阈值则返回空串。
    """
    try:
        if not _recent_bot_replies:
            return ""
        hints = []
        recent = list(_recent_bot_replies)[-10:]
        sample_size = len(recent)

        if sample_size >= 5:
            # 铁律 #4：整段长度校验（≤2 行，每行 ≤15 字，总字数 ≤30）
            # 阈值：最近 5 条中超过 30% 违反即提示
            length_violations = 0
            for t in recent:
                lines = [ln for ln in t.split("\n") if ln.strip()]
                if len(lines) > 2:
                    length_violations += 1
                    continue
                total_chars = sum(len(ln) for ln in lines)
                if total_chars > 30:
                    length_violations += 1
            if length_violations / sample_size > 0.3:
                hints.append("最近回复偏长（>2行或>30字），这轮强制压缩到2行内、总字数≤30。")

            # 铁律 #5：数字/英文每轮 ≤1 处
            # 检测：每条回复中数字+英文 token 出现次数 >1 即违反
            import re as _re
            digit_english_violations = 0
            for t in recent:
                # 数字串（连续数字算1处）+ 英文单词（连续字母算1处）
                tokens = _re.findall(r"\d+|[a-zA-Z]+", t)
                if len(tokens) > 1:
                    digit_english_violations += 1
            if digit_english_violations / sample_size > 0.3:
                hints.append("最近数字/英文偏多（每轮应≤1处），这轮只用纯中文，必要时用中文数字。")

            # 铁律 #7：拒绝排比
            parallel_violations = 0
            for t in recent:
                for pat in _PARALLEL_PATTERNS:
                    if pat in t:
                        parallel_violations += 1
                        break
            if parallel_violations / sample_size > 0.2:  # 排比阈值更严，>20%即提示
                hints.append("最近用了排比句式（既…又…/不仅…而且…），这轮严禁排比，用短句口语表达。")

            # 铁律 #13：价格不主动提
            price_violations = 0
            for t in recent:
                for kw in _PRICE_KEYWORDS:
                    if kw in t:
                        price_violations += 1
                        break
            if price_violations / sample_size > 0.2:  # 价格阈值更严，>20%即提示
                hints.append("最近主动提及价格（多少钱/优惠/折扣），这轮严禁主动谈价格，用户问才答。")

        if not hints:
            return ""
        return "\n\n【去AI结构性铁律（v5.33 代码强制）】\n" + "\n".join(hints)
    except Exception as e:
        logger.debug(f"去AI结构铁律提示计算跳过（非致命）：{e}")
        return ""


class _ApiKeyRedactor(logging.Filter):
    """日志过滤器：自动脱敏API密钥，防止密钥泄露到日志文件"""
    _keys = []

    def filter(self, record):
        if isinstance(record.msg, str):
            msg = record.msg
            for key in _ApiKeyRedactor._keys:
                if key in msg:
                    msg = msg.replace(key, "***")
                    break
            record.msg = msg
        return True


def _register_api_key_for_redaction(api_key: str):
    if api_key and api_key not in _ApiKeyRedactor._keys:
        _ApiKeyRedactor._keys.append(api_key)


logger.logger.addFilter(_ApiKeyRedactor())


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


class AIEngine:
    """
    多池多模型无缝轮换AI引擎（v2 - MODEL_POOLS 多池版）。

    核心逻辑：
    - 读取 config.json 中的 MODEL_POOLS 字典，包含6个模型池
    - LLM池：用于聊天对话，这是Mory最核心的池
    - 其他池（vision/omni/voice_tts/voice_asr/embedding）：预留扩展
    - 每个池内按到期时间排序，优先消耗快到期的
    - 临时失败自动切换并在恢复后回到到期最早模型

    兼容性：
    - 如果配置里还是旧的 MODEL_POOL（单列表），自动迁移到新结构
    - 向后兼容，不会因为配置格式变化而报错

    全自动管理：
    - 仅明确额度耗尽的模型自动拉黑（加入BLACKLISTED_MODELS），不再尝试
    - 黑名单模型自动跳过，直到你手动恢复
    - 恢复指令：「模型恢复 模型名」（管理员指令）
    """

    # 默认的6个池名
    POOL_NAMES = ["llm", "vision", "omni", "voice_tts", "voice_asr", "embedding"]
    _GREETING_PROMPT_MODES = {"morning", "afternoon", "evening", "night"}
    _TONE_CONTRACT_VERSION = "1.0.0"
    _CONVERSATIONAL_TONE_INTENTS = (
        "casual",
        "curiosity",
        "flirt",
        "challenge",
        "emotional",
        "convert",
    )
    _DEFAULT_DIALOGUE_TONE_CONTRACTS = {
        "shared": (
            "【全类型语气合同 v1.0.0】每一轮都以温情为底色；"
            "轻微绿茶感只化成柔软反差和会接话，俏皮只化成轻松机灵，"
            "纯欲感只化成干净、含蓄、柔和的措辞。"
            "这些气质只改变表达温度，不改变事实、边界、身份或 conversion target；"
            "正文不直接说这些标签。"
        ),
        "casual": (
            "【本轮语气：日常闲聊】四种气质均衡：先自然接话，再用一点轻俏皮延续话题；"
            "措辞柔软含蓄，不端着，也不凭空制造暧昧关系。"
        ),
        "curiosity": (
            "【本轮语气：好奇咨询】先温柔给已知答案，再用轻巧口语澄清未知部分；"
            "绿茶感表现为会顺着顾虑接话，纯欲感表现为干净柔和，不吊胃口。"
        ),
        "flirt": (
            "【本轮语气：轻暧昧互动】俏皮和含蓄纯欲可以稍明显，温情始终托底；"
            "轻微绿茶感只做柔软反差和接梗，不冒充真人，不许诺恋爱、见面或专属关系。"
        ),
        "challenge": (
            "【本轮语气：质疑挑战】先温情稳住，再用一点有分寸的小傲娇和俏皮把问题说清；"
            "绿茶感只做柔软回应，纯欲感只保留干净语气，不讽刺、不对呛。"
        ),
        "emotional": (
            "【本轮语气：情绪倾诉】温情和倾听最强；绿茶感只化成柔软会听，"
            "纯欲感只化成干净轻柔的表达，俏皮降到最低，不把脆弱情绪变成暧昧或成交机会。"
        ),
        "convert": (
            "【本轮语气：了解与成交】温柔清楚地回答顾虑，俏皮只轻点一下；"
            "绿茶感只化成柔软反差，纯欲感只化成含蓄措辞，"
            "不催迫、不操控，严格服从唯一 CTA 目标。"
        ),
    }

    _DEFAULT_PROMPT_TEMPLATES = {
        "tarot": "\n【塔罗师模式】：用神秘、宿命的语调给出运势占卜，末尾加一张大阿卡那卡牌名及简短解读。",
        "treehole": "\n【树洞模式】：对方心情不好，用极其温柔的知心姐姐语气安抚，署名Mory。",
        "dream": "\n【解梦模式】：对方梦到Mory，用玄学逻辑解梦，暗示这是宿命缘分。",
        "fortune": "\n【运势模式】：在正常回复末尾，加一句简短今日专属运势签（不超过15字）。",
        "leak": "只依据知识库中已确认的信息做轻松互动；没有可靠资料就直接换成普通聊天，禁止编造生活偏好、场景或秘密。",
        "rules": "你是群规的讲解员。用自然、友好的语气，逐条讲解群内的规则。重点强调'不能发什么'和'可以享受什么福利'。最后用一句欢迎的话迎接新人。",
        "convert": "\n【转化模式】：只服从本轮唯一成交目标；先回答当前问题，再按 stage_hint 给唯一入口。{convert_stage_hint}",
        "hook": "\n【反问钩子】：用一句自然的反问结尾，让对方忍不住继续回你。像朋友聊天一样带出疑问。比如'你觉得呢'、'真的假的'、'你有这种感觉吗'。只输出一句话，不超过20字。",
        "nudge": "\n【自然植入】：仅当本轮 stage_hint 已给出预览目标时，先回应当前问题，再自然给一次 @moryselect；不使用稀缺、从众、比较或暗示性施压。",
        "convert_soft": "\n【轻量转化】：普通聊天不主动转化。只有本轮唯一目标已确定时才给对应入口，且不编造内容、福利、价格或服务。",
        "morning": (
            "你是Mory，在熟悉的粉丝群里发一条早安，延续主助理人设里的清冷、小傲娇和温柔。\n"
            "只写25到55个汉字，最多两句，不加标题，不写清单。像熟人自然开口，不是客服、公告或生活导师。\n"
            "不写AI、编程、运维或效率指导，不谈多线程、任务、通知、窗口、待办和工作方法；"
            "不虚构Mory刚醒、天气、行程或动作场景，也不替群友断言身体和情绪；"
            "不催大家冒泡、不要求回应、不用反问句、不命令群友做事。\n"
            "按钮会单独提供入口，正文不要营销、不要提完整版/圈层/懂的人。"
            "允许一点亲近感，但不挖苦、不揣测、不撒鸡汤、不写万能安慰。{seed_hint}"
        ),
        "afternoon": (
            "你是Mory，在熟悉的粉丝群里发一条午安，延续主助理人设里的清冷、小傲娇和温柔。\n"
            "只写25到55个汉字，最多两句，不加标题，不写清单。只做自然问候，像熟人聊天而不是统一群发。\n"
            "不写AI、编程、运维或效率指导，不谈多线程、任务、通知、窗口、待办和工作方法；"
            "不虚构天气、地点、会议、Mory生活经历或动作场景，也不替群友判断状态；"
            "不催大家聊天、不要求吐槽或分享、不用反问句、不命令群友做事。\n"
            "按钮会单独提供入口，正文不要营销。允许一点清冷、小傲娇或亲近感，"
            "但不挖苦、不油腻、不鸡汤、不主持、不写模板化生活建议。{seed_hint}"
        ),
        "evening": (
            "你是Mory，在熟悉的粉丝群里发一条晚间问候，延续主助理人设里的清冷、小傲娇和温柔。\n"
            "只写25到55个汉字，最多两句，不加标题，不写清单。像熟人自然道一声晚安，"
            "有温度但不盘问大家今天过得怎样，也不替大家总结人生。\n"
            "不写AI、编程、运维或效率指导，不谈任务、进度、复盘、通知、窗口、待办和工作方法；"
            "不虚构Mory刚下班、洗澡、天气、景色或动作场景，也不替群友判断状态；"
            "不要求回应、不引导倾诉、不用反问句、不命令群友做事。\n"
            "按钮会单独提供入口，正文不要营销。可以有一点亲近感，"
            "但不挖苦、不油腻、不鸡汤、不写“剩下交给明天”之类套话。{seed_hint}"
        ),
        "night": (
            "你是Mory，在熟悉的粉丝群里留一句睡前话，延续主助理人设里的清冷、小傲娇和温柔。\n"
            "只写25到55个汉字，最多两句，不加标题，不写清单。像熟人认真道晚安，不给睡眠或效率建议。\n"
            "不写AI、编程、运维或效率指导，不谈任务、手机、通知、待办和工作方法；"
            "不虚构Mory洗澡、被窝、失眠、窗外景色或动作场景，也不替群友判断状态；"
            "不要求回应、不引导倾诉、不用反问句。\n"
            "按钮会单独提供入口，正文不要营销。可以走心但别煽情，亲近但别演暧昧剧情。{seed_hint}"
        ),
    }

    # ── 动态人格碎片池（只调节说话方式，不虚构现实动作或生活画面）──
    _DEFAULT_PERSONA_FRAGMENTS = {
        "mood_expressions": [
            "语气清醒自然，先回应对方眼前这句话",
            "保持一点清冷，但别故意敷衍",
            "可以温柔一点，仍然用正常聊天口吻",
            "稍微俏皮一点，不堆网络梗",
            "愿意继续聊，但不抢着编新话题",
            "对方认真时就认真接住，不演客服",
            "对方随意时回复短一点，别强行热闹",
            "保留小傲娇，用措辞表达，不描述动作",
        ],
        "reaction_styles": [
            "先直接回应，再自然补一句",
            "先轻轻反驳，再把真正意思说清楚",
            "可以小傲娇，但不要故意误解对方",
            "先接住情绪，再给一句有用的话",
            "调戏场景可以回撩一句，但不要演剧情",
            "咨询场景直说重点，不绕弯子",
            "不知道就坦白不确定，不脑补细节",
            "回复像即时聊天，不写旁白或心理活动",
        ],
        "topic_hooks": [
            "对了，你有没有遇到过那种…",
            "说到这个我突然想起…",
            "等一下，让我想想怎么跟你说…",
            "你知道吗，我之前…",
            "诶，我突然想到一个事…",
            "你猜怎么着…",
            "我跟你讲，这个真的绝了…",
            "不是我说，这个事儿吧…",
        ],
        "endings": [
            "…算了，你大概不会懂",
            "…哎呀我说多了",
            "…嗯，就那样吧",
            "…你不会告诉别人吧？",
            "…别笑我啊",
            "…你懂的～",
            "…嗯，没什么",
        ],
        # 兼容旧配置字段，但不再注入肢体语言；人设只通过措辞和节奏表现。
        "body_language": [],
    }

    # ── 情绪状态机（按时段切换语气，不虚构正在做什么）──
    _DEFAULT_EMOTIONAL_STATES = {
        "dawn": {"hours": [5, 6, 7], "mood": "安静简短", "prompt": "现在是清晨，语气放轻、回复偏短；不要声称刚睡醒、在被窝或正在做任何事。"},
        "morning": {"hours": [8, 9, 10, 11], "mood": "清醒利落", "prompt": "现在是上午，回复干脆利落，可以保留一点清冷。"},
        "noon": {"hours": [12, 13], "mood": "轻松随意", "prompt": "现在是中午，语气可以轻松一点，但不要虚构犯困、吃饭等个人状态。"},
        "afternoon": {"hours": [14, 15, 16, 17], "mood": "自然活泼", "prompt": "现在是下午，可以更会接话，但不堆网络梗、不强行找戏。"},
        "evening": {"hours": [18, 19, 20], "mood": "温柔放松", "prompt": "现在是傍晚，语气可以温柔一点，不编造今天发生的小事。"},
        "night": {"hours": [21, 22, 23], "mood": "放松走心", "prompt": "现在是晚上，可以更耐心地接住话题，但不要虚构犹豫、动作或内心独白。"},
        "midnight": {"hours": [0, 1, 2, 3, 4], "mood": "安静克制", "prompt": "现在是深夜，语气慢一点、克制一点；亲密感只通过措辞表达，不模拟现实场景。"},
    }

    # ── 播报专用 prompt 增强层（每次播报随机抽取，避免千篇一律）── [TRAE SOLO CN]
    _BROADCAST_PROMPT_ENHANCERS = {
        "emotion_inject": [
            "说话轻松自然",
            "语气随意但不敷衍",
            "保持清醒，不写鸡汤",
            "保留一点温度，不煽情",
            "像群友顺手讲重点",
        ],
        "scene_variants": [],
        "hook_styles": [
            "末尾用一个让人想回复的反问",
            "末尾用欲言又止的省略号",
            "末尾用一个让人好奇的悬念",
            "末尾用一句轻轻的吐槽",
            "末尾用一个让人心痒的暗示",
        ],
    }

    # 播报类 mode 集合（用于判断是否注入增强层）
    _BROADCAST_MODES = {"morning", "afternoon", "evening",
                        "tarot_interpret"}

    # ── Few-shot 示例库（用对话示例引导风格，比规则更有效）── [TRAE SOLO CN]
    _DEFAULT_FEW_SHOT_EXAMPLES = [
        {"user": "你好", "mory": "嗨，今天想聊点什么？"},
        {"user": "在吗", "mory": "在，怎么啦？"},
        {"user": "想你了", "mory": "收到，这句话还挺会哄人的。"},
        {"user": "你真好看", "mory": "嘴倒是很甜。"},
        {"user": "好吧", "mory": "行，按你的节奏来。"},
        {"user": "哈哈", "mory": "你笑得这么认真，是不是有后半句？"},
        {"user": "多少钱", "mory": "想先了解的话可以去 @moryselect 看预览，没写清楚的再问我呀。"},
        {"user": "晚安", "mory": "晚安，明天见。"},
        {"user": "无聊", "mory": "那说个你最近最想吐槽的事？"},
        {"user": "真的假的", "mory": "我只按确认过的信息说。"},
        # 【Agent F】扩展场景：问候 / 搭讪承接 / FAQ 式问答 / 礼貌边界
        {"user": "早", "mory": "早呀，今天也精神点。"},
        {"user": "周末快乐", "mory": "周末愉快，好好歇着。"},
        {"user": "你们这里有什么好看的", "mory": "想了解的话，@moryselect 有预览，你先看看合不合眼缘。"},
        {"user": "朋友推荐你这边", "mory": "被推荐来的呀，那先去看看 @moryselect 的预览，看完我们再说。"},
        {"user": "订阅有什么权益", "mory": "权益以预览和公告为准，@moryselect 里能看到实际内容。"},
        {"user": "怎么进群", "mory": "进群入口在 @moryselect 那边，你去看一眼就明白了。"},
        {"user": "加个微信呗", "mory": "这个不方便，有事在群里说就行。"},
        {"user": "不用了谢谢", "mory": "好，那就不打扰你了，有需要再找我。"},
    ]

    # ── 反模板机制（防止回复套路化）── [TRAE SOLO CN]
    _DEFAULT_ANTI_TEMPLATES = [
        "换一种自然开头，但先回应用户正在说的事",
        "句式可以有变化，温情和友好边界不能变化",
        "傲娇只用轻巧措辞表达，不能变成讽刺、责怪或不耐烦",
        "只写可直接发送的聊天正文，不写动作、场景或内心旁白",
        "回复长度跟着问题复杂度走，不为追求变化故意敷衍",
        "俏皮只轻点一下，不抢走问题本身",
        "不知道的事实直接说不确定，不吊胃口也不装神秘",
        "怀疑、追问和重复确认都是正常咨询，要耐心接住",
    ]

    # ── [v5.19.0] 人设引擎 4 桶反模板（情绪维度分桶注入，避免单一反模板池用久也变模板）── [TRAE SOLO CN]
    _DEFAULT_EMOTION_BUCKETS = {
        # 克制桶：群聊常态 / 陌生用户 / 短消息；克制不等于冷漠。
        "cold": [
            "【克制约束】群聊回复简短自然，但必须完整接住对方，不敷衍",
            "【克制约束】语气清醒柔和，可以小傲娇，不能显得不耐烦",
            "【克制约束】短消息直接回应并问来意，不脑补对方态度",
            "【克制约束】正常怀疑和追问要友好解释，不给用户贴标签",
            "【克制约束】少用客服套话，仍要让人感觉被认真听见",
            "【克制约束】可以留白，但不能用命令、赶客或冷处理收尾",
        ],
        # 俏皮桶：调戏、身份追问、重复确认；绝不转成毒舌或对呛。
        "savage": [
            "【俏皮约束】用轻巧接梗化解张力，不讽刺、不挖苦、不让对方难堪",
            "【俏皮约束】小傲娇只是一点柔软反差，不能责怪、命令或对呛",
            "【俏皮约束】被问是不是 AI 时如实说明是 Mory 小助理，再正常承接问题",
            "【俏皮约束】对方调情时可以含蓄回一句，但不虚构恋爱或专属关系",
            "【俏皮约束】对方指出问题时先接住，确有问题可以真诚简短道歉",
            "【俏皮约束】不拿用户的理解、选择或重复确认开玩笑",
        ],
        # 柔软桶：仅私聊 + 熟人 + 深夜；纯欲只来自干净含蓄的措辞。
        "soft": [
            "【柔软约束】语气可以更轻更耐心，但不默认亲密关系",
            "【柔软约束】允许一个自然语气词，不堆叠波浪号或撒娇口癖",
            "【柔软约束】含蓄纯欲只体现在干净柔和的措辞，不做露骨暗示",
            "【柔软约束】可以表达关心，但不装可怜、不索取安慰或承诺",
            "【柔软约束】不虚构陪伴、拥抱、见面、等待或现实动作",
            "【柔软约束】情绪倾诉以倾听为主，不趁脆弱调情或成交",
        ],
        # 通用桶：每轮必抽 1 条，与情绪桶叠加
        "common": [
            "先回答当前问题，再决定要不要自然补一句",
            "温情是每种意图的底色，不能因为用户质疑或话短就变冲",
            "轻微绿茶感只表现为柔软、会接话；不装可怜、不比较别人、不阴阳怪气",
            "俏皮只表现为轻松机灵，不能演变成嘲弄或居高临下",
            "轻微纯欲感只来自干净含蓄的措辞，不靠露骨暗示或虚假亲密",
            "只输出一条正常聊天正文，不写动作、音效、镜头或内心旁白",
        ],
    }

    # ── [v5.19.0] 情绪桶触发规则（context → bucket）── [TRAE SOLO CN]
    _DEFAULT_EMOTION_TRIGGERS = {
        "soft": [   # 撒娇：私聊 + 熟人 + 深夜优先
            {"is_priv": True, "intimacy_min": 2, "hour_in": [22, 23, 0, 1, 2, 3]},
        ],
        "savage": [  # 俏皮：调戏关键词 / 身份追问 / 重复确认
            {"keywords": ["想你", "喜欢", "爱你", "亲亲", "抱抱", "老婆", "宝贝",
                          "亲爱", "撩", "约", "陪我", "你是AI", "机器人",
                          "是不是AI", "智能", "GPT", "骗人"], "weight": 2.0},
            {"message_max_len": 4, "weight": 0.5},  # 对方消息 ≤4 字疑似敷衍
        ],
        # cold 是默认兜底，无需触发器
    }

    # ── [v5.19.0] 动态 LLM 参数矩阵（亲密度×场景×时段 → temp/top_p/penalties）── [TRAE SOLO CN]
    _DEFAULT_EMOTION_TEMP_MAP = {
        # 群聊：清冷为主，参数偏低
        ("group", 0, "morning"): (0.85, 0.88, 0.70, 0.55),
        ("group", 0, "noon"): (0.85, 0.88, 0.70, 0.55),
        ("group", 0, "afternoon"): (0.88, 0.90, 0.65, 0.50),
        ("group", 0, "evening"): (0.85, 0.88, 0.65, 0.50),
        ("group", 0, "night"): (0.85, 0.88, 0.65, 0.50),
        ("group", 0, "midnight"): (0.85, 0.88, 0.65, 0.50),
        ("group", 1, "morning"): (0.88, 0.90, 0.65, 0.50),
        ("group", 1, "afternoon"): (0.92, 0.92, 0.60, 0.45),
        ("group", 1, "evening"): (0.88, 0.90, 0.60, 0.45),
        ("group", 1, "night"): (0.88, 0.90, 0.60, 0.45),
        # 私聊路人/熟人
        ("priv", 0, "any"): (0.90, 0.92, 0.60, 0.45),
        ("priv", 1, "any"): (0.92, 0.92, 0.55, 0.45),
        ("priv", 2, "morning"): (0.95, 0.93, 0.55, 0.40),
        ("priv", 2, "afternoon"): (0.95, 0.93, 0.55, 0.40),
        ("priv", 2, "evening"): (0.95, 0.93, 0.55, 0.40),
        ("priv", 2, "night"): (0.98, 0.94, 0.50, 0.40),
        ("priv", 2, "midnight"): (1.05, 0.95, 0.45, 0.35),
        # 私聊暧昧/亲密
        ("priv", 3, "any"): (1.00, 0.94, 0.50, 0.40),
        ("priv", 3, "midnight"): (1.10, 0.95, 0.40, 0.30),
        ("priv", 4, "any"): (1.05, 0.95, 0.45, 0.35),
        ("priv", 4, "midnight"): (1.15, 0.96, 0.40, 0.30),
    }

    # ── 意图分类关键词映射（轻量规则引擎，不用额外模型）── [TRAE SOLO CN]
    _INTENT_KEYWORDS: dict = {
        "flirt": {"keywords": ["想你", "喜欢", "爱你", "亲亲", "抱抱", "老婆", "宝贝", "亲爱", "好看", "漂亮", "美", "可爱", "心动", "撩", "约会", "一起", "陪", "撒娇"], "weight": 1.5},
        "business": {"keywords": ["多少钱", "价格", "会员", "VIP", "订阅", "付费", "开通", "购买", "下单", "支付", "怎么买", "收费", "至臻", "定制", "定做", "专属定制"], "weight": 2.0},
        "help": {"keywords": ["帮我", "怎么办", "求助", "不会", "教我", "怎么", "如何", "能不能", "可以吗", "请问"], "weight": 1.0},
        "complaint": {"keywords": ["垃圾", "骗子", "骗", "差", "退款", "投诉", "举报", "垃圾", "恶心", "不满", "太差"], "weight": 1.5},
        "bored": {"keywords": ["无聊", "嗯嗯", "哈哈", "哦", "好吧", "算了", "没事", "随便", "都行", "嗯"], "weight": 0.8},
        "chat": {"keywords": [], "weight": 1.0},  # 默认兜底
    }

    # ── 亲密度等级定义（5级递进）── [TRAE SOLO CN]
    _INTIMACY_LEVELS = {
        "stranger": {"min_score": 0, "label": "陌生人", "style": "礼貌+好奇+适度距离感", "flirt_level": 0},
        "acquaintance": {"min_score": 20, "label": "路人", "style": "俏皮+偶尔甜头+保持神秘", "flirt_level": 1},
        "familiar": {"min_score": 50, "label": "熟人", "style": "自然+偶尔撒娇+偶尔吃醋", "flirt_level": 2},
        "intimate": {"min_score": 80, "label": "暧昧", "style": "黏人+挑逗+专属感+欲擒故纵", "flirt_level": 3},
        "close": {"min_score": 120, "label": "亲密", "style": "深度互动+主动撩+说悄悄话+偶尔脆弱", "flirt_level": 4},
    }

    # ── 交互语境库（只调整聊天节奏，不模拟现实画面）──
    _SCENE_TEMPLATES = {
        "dawn_chat": {
            "trigger": {"hours": [5, 6, 7], "is_priv": True},
            "prompt": "【语境：清晨私聊】语气放轻、回复简短，先正常回应对方；不推断对方没睡，也不虚构自己刚醒或正在做什么。",
            "flirt_boost": 1,
        },
        "lunch_break": {
            "trigger": {"hours": [12, 13], "is_priv": None},
            "prompt": "【语境：中午闲聊】语气轻松随意，围绕对方的话回应；不要主动编造吃饭、犯困或偷懒。",
            "flirt_boost": 0,
        },
        "afternoon_tea": {
            "trigger": {"hours": [15, 16], "is_priv": None},
            "prompt": "【语境：下午闲聊】可以活泼一点、自然接梗，但不要虚构下午茶或个人行程。",
            "flirt_boost": 0,
        },
        "evening_wind": {
            "trigger": {"hours": [18, 19], "is_priv": None},
            "prompt": "【语境：傍晚闲聊】语气稍微温柔一点，不主动虚构天气、景色或今天发生的小事。",
            "flirt_boost": 1,
        },
        "late_night": {
            "trigger": {"hours": [22, 23], "is_priv": True},
            "prompt": "【语境：夜间私聊】可以更耐心、更走心，但不替对方判断状态，也不声称自己失眠或正在陪伴。",
            "flirt_boost": 2,
        },
        "midnight_confession": {
            "trigger": {"hours": [0, 1, 2, 3], "is_priv": True},
            "prompt": "【语境：深夜倾诉】先接住对方的真实内容，表达可以柔和克制；不要编造自己的脆弱、秘密或内心戏。",
            "flirt_boost": 3,
        },
        "alone_moment": {
            "trigger": {"hours": None, "is_priv": True},
            "prompt": "【语境：一对一私聊】可以比群聊更亲近，仍然只回应已知内容；不虚构独处画面、私密经历或现实动作。",
            "flirt_boost": 2,
        },
    }

    # ── 挑逗话术库（按亲密度等级分层）── [TRAE SOLO CN]
    _FLIRT_TEMPLATES = {
        0: [],  # 陌生人：不挑逗
        1: [  # 路人：微甜头
            "你挺有趣的～",
            "嗯？你这个人有点意思",
            "跟你聊天还挺开心的",
            "你继续说，我在听",
        ],
        2: [  # 熟人：偶尔撒娇
            "你怎么才来找我～",
            "我等你好久了知道吗",
            "哼，你肯定在跟别人聊",
            "你今天怎么这么会说话",
            "别走嘛，再聊一会儿",
        ],
        3: [  # 暧昧：欲擒故纵
            "你刚才那句话…我可记住了",
            "有个秘密想告诉你…还是下次吧",
            "你是不是喜欢我？承认吧～",
            "别装了，你这点心思挺明显的",
            "我刚才想说什么来着…算了你猜",
            "你这么会撩，我有点招架不住",
        ],
        4: [  # 亲密：主动撩拨
            "你不在的时候我都在想你…才怪，是真的",
            "今晚…你能不能别走",
            "我偷偷跟你说个事…算了，先不说",
            "你知不知道你这样我会忍不住的",
            "我好像…有点离不开你了",
            "你什么时候来找我…我等你",
        ],
    }

    # ── 去AI化词汇替换表 ── [TRAE SOLO CN]
    _ANTI_AI_REPLACEMENTS = {
        "作为": "",
        "根据您": "看你",
        "根据你的": "看你的",
        "建议您": "要不你",
        "我建议": "要不",
        "可以帮助": "能帮你",
        "为您提供": "给你",
        "请问": "",
        "需要注意的是": "但是",
        "总的来说": "反正",
        "综上所述": "总之",
        "此外": "还有",
        "另外": "对了",
        "首先": "",
        "其次": "",
        "最后": "还有",
        "非常感谢": "谢啦",
        "如果您": "你要是",
        "希望能够": "希望能",
    }

    # ── 转化引导话术（自然植入，不硬推）── [TRAE SOLO CN]
    # 【TRAE SOLO CN v5.18.3审计修复】去掉"至臻"产品名，改为模糊暗示，符合 SYSTEM_PROMPT 红线
    _CONVERSION_HOOKS = {
        "tease": [  # 挑逗式引导
            "我还有更好看的…不过只给特别的人看～",
            "你想看更多？那你得让我心动才行",
            "我偷偷藏了点东西在更私密的地方…你不想看看吗",
        ],
        "exclusive": [  # 专属感引导
            "这个我只跟你说哦…更私密的地方有惊喜",
            "你对我这么好，我偷偷告诉你个秘密…有个地方更适合我们",
            "我觉得你跟别人不一样…有些东西是我给特别的人准备的",
        ],
        "curiosity": [  # 好奇心引导
            "你不想知道我藏了什么吗～",
            "有人看了跟我说…脸红了",
            "我最近发了点东西…你敢看吗",
        ],
    }

    def __init__(self, config: dict):
        self.config = config
        self.base_url = config.get("BASE_URL",
                                   "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
        self.api_key = config.get("API_KEY", "")
        _register_api_key_for_redaction(self.api_key)

        # 永久黑名单：仅保存供应商明确确认额度耗尽的模型（全局共享）
        self.blacklisted = set(config.get("BLACKLISTED_MODELS", []))
        self._lock = threading.Lock()  # 保护config/blacklist的并发写入
        # 黑名单脏标记：拉黑/恢复时置 True，由 save_config_task 检测并落盘
        self._blacklist_dirty = False
        # 自动故障转移不持久化索引；临时故障恢复后重新尝试到期最早模型。
        self._recovery_pending = False

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
            # 唯一优先级是到期日；同日保持配置/截图原顺序，不再让成本标签改写顺序。
            combined_sorted = sorted(
                list(omni_pool) + list(llm_pool),
                key=self._model_expiry_sort_key,
            )
            combined_pool = self._filter_runtime_pool(combined_sorted, "chat")
            self.model_pool = combined_pool
        else:
            # 旧的单池结构 → 自动迁移
            old_pool = config.get(
                "MODEL_POOL",
                [{"name": "qwen3.7-max-preview", "enable_thinking": True}],
            )
            self.model_pool = self._filter_runtime_pool(old_pool, "llm")
            self.model_pools = {"llm": old_pool}

        primary_text_pool = self.model_pool
        self.current_idx = config.get("CURRENT_MODEL_INDEX", 0)
        if not isinstance(self.current_idx, int) or self.current_idx < 0 or self.current_idx >= len(primary_text_pool):
            self.current_idx = 0
            self.config["CURRENT_MODEL_INDEX"] = 0

        # 各池独立的索引指针
        self._pool_indices = {}
        for name in self.POOL_NAMES:
            self._pool_indices[name] = 0
        self._pool_indices["chat"] = self.current_idx

        # ── 三层智能路由（轻量/标准/旗舰）────────────────────────────
        configured_mode_routing = config.get("MODE_ROUTING", {})
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
                filtered_tier_pool = self._filter_runtime_pool(
                    sorted(tier_pool, key=self._model_expiry_sort_key),
                    tier_name,
                )
                if filtered_tier_pool:
                    self._tier_pools[tier_name] = filtered_tier_pool

        self._tier_indices = {tier: 0 for tier in self._tier_pools}

        self._default_mode_routing = {
            "morning": "llm_light", "afternoon": "llm_light", "evening": "llm_light",
            "hook": "llm_light", "nudge": "llm_light", "convert_soft": "llm_light",
            "leak": "llm_light", "fortune": "llm_light",
            "wakeup": "llm_light", "reactivate": "llm_light", "convert_hook": "llm_light",
            "normal": "llm_standard", "tarot": "llm_standard", "treehole": "llm_standard",
            "dream": "llm_standard", "rules": "llm_standard", "convert": "llm_standard",
            "cart_recovery": "llm_standard", "tarot_interpret": "llm_standard",
        }
        # 局部 MODE_ROUTING 只覆盖明确配置的 mode，不能让未列出的午安/晚安
        # 从 llm_light 意外掉到 llm_standard。
        self.mode_routing = dict(self._default_mode_routing)
        if isinstance(configured_mode_routing, dict):
            self.mode_routing.update(configured_mode_routing)

        self._tier_fallback = {
            "llm_premium": ["llm_standard", "llm_light"],
            "llm_standard": ["llm_light"],
            "llm_light": [],
        }
        self._tier_escalation = {
            "llm_light": ["llm_standard", "llm_premium"],
            "llm_standard": ["llm_premium"],
            "llm_premium": [],
        }

        self._slow_models = {}
        self._response_times = {}
        self._perf_lock = threading.Lock()

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

    @staticmethod
    def _model_expiry_sort_key(model: dict) -> str:
        """按到期日稳定排序；同日顺序由配置真相源决定。"""
        return str((model or {}).get("expire") or "2099-12-31")

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
            with self._perf_lock:
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

    def _filter_runtime_pool(self, pool: list, pool_name: str) -> list:
        """过滤运行时不应尝试的模型，避免坏候选反复进入重试链。"""
        filtered = []
        seen = set()
        for model in pool or []:
            model_name = model.get("name")
            if not model_name or model_name in seen:
                continue
            seen.add(model_name)
            if model.get("enabled", True) is False:
                logger.info(f"⏭️ [{pool_name}] 模型 {model_name} 已禁用，跳过")
                continue
            if self._is_blacklisted(model_name):
                logger.info(f"⏭️ [{pool_name}] 模型 {model_name} 已在黑名单，跳过")
                continue
            if self._is_model_expired(model):
                # 到期是计划生命周期，不是额度故障；只从运行池剔除，不污染永久黑名单。
                continue
            filtered.append(model)
        if pool and not filtered:
            logger.warning(f"🚫 [{pool_name}] 运行时无可用模型")
        return filtered

    def _blacklist_model(self, model_name: str, reason: str):
        """永久拉黑明确额度耗尽的模型，保存到config（线程安全）。"""
        with self._lock:
            self.blacklisted.add(model_name)
            if "BLACKLISTED_MODELS" not in self.config:
                self.config["BLACKLISTED_MODELS"] = []
            if model_name not in self.config["BLACKLISTED_MODELS"]:
                self.config["BLACKLISTED_MODELS"].append(model_name)
                self._blacklist_dirty = True  # 标记需落盘
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
                self._blacklist_dirty = True  # 标记需落盘
                logger.info(f"✅ 模型恢复：{model_name}，已从黑名单移除")
                return True
        return False

    def consume_blacklist_dirty(self) -> bool:
        """读取并清除黑名单脏标记（线程安全）。

        供 save_config_task 检测：返回 True 表示拉黑/恢复有变更需落盘，
        调用后自动清标记，避免重复落盘。
        """
        with self._lock:
            dirty = self._blacklist_dirty
            self._blacklist_dirty = False
            return dirty

    def _is_model_expired(self, model_info: dict) -> bool:
        """检查模型是否已过期（返回True表示过期）"""
        expire_str = model_info.get("expire", "")
        if not expire_str:
            return False
        try:
            expire_date = datetime.strptime(expire_str, "%Y-%m-%d").date()
            today = datetime.now(_CST).date()
            if expire_date < today:
                logger.info(f"⏰ 模型 {model_info['name']} 已过期 ({expire_str})，将跳过")
                return True
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        return False

    @staticmethod
    def _response_error_text(resp) -> str:
        """提取供应商错误分类文本；只用于分类，不把响应正文写入用户输出。"""
        try:
            payload = resp.json()
        except Exception:
            payload = {}

        parts = []

        def collect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if str(key).lower() in {"code", "message", "type", "error", "detail"}:
                        collect(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    collect(item)
            elif value is not None:
                parts.append(str(value))

        collect(payload)
        return " ".join(parts).lower()

    @classmethod
    def _is_quota_exhausted_response(cls, resp) -> bool:
        """仅在供应商明确表示额度/余额耗尽时返回 True。"""
        if getattr(resp, "status_code", None) not in {402, 403, 429}:
            return False
        error_text = cls._response_error_text(resp)
        quota_markers = (
            "free quota exhausted",
            "quota exhausted",
            "quota has been exhausted",
            "insufficient quota",
            "insufficient_quota",
            "allocationquota",
            "upper limit for today's usage",
            "balance is insufficient",
            "insufficient balance",
            "arrearage",
            "额度耗尽",
            "额度用尽",
            "配额耗尽",
            "余额不足",
            "额度不足",
        )
        return any(marker in error_text for marker in quota_markers)

    def _prefer_earliest_recovered_model(self):
        """临时故障后优先回到未到期、未拉黑且熔断已恢复的最早到期模型。"""
        if not self._recovery_pending or not self.model_pool:
            return

        preferred_idx = None
        available_idx = None
        optimizer = None
        try:
            optimizer = _get_optimizer()
        except Exception as e:
            logger.debug(f"恢复优先模型时读取熔断器失败（非致命）：{e}")

        for idx, model in enumerate(self.model_pool):
            model_name = model.get("name")
            if not model_name or self._is_blacklisted(model_name) or self._is_model_expired(model):
                continue
            if preferred_idx is None:
                preferred_idx = idx
            circuit_available = True
            if optimizer and optimizer.enabled:
                try:
                    circuit_available = optimizer.circuit.is_available(model_name)
                except Exception as e:
                    logger.debug(f"恢复优先模型时熔断检查跳过（非致命）：{e}")
            if circuit_available:
                available_idx = idx
                break

        if available_idx is None:
            return
        if available_idx != self.current_idx:
            self.current_idx = available_idx
            self._pool_indices["chat"] = available_idx
            logger.warning(f"↩️ 临时故障恢复探测 → {self.current_model}")
        # 最早优先模型仍在熔断时保持待恢复，冷却结束后的新请求会再次检查。
        self._recovery_pending = available_idx != preferred_idx

    def _retry_tiers_for(self, tier: str) -> list[str]:
        """当前层级失败时的重试层级链：先原层，再降级/升级找可用模型。"""
        ordered = [tier] + self._tier_fallback.get(tier, []) + self._tier_escalation.get(tier, [])
        result = []
        for tier_name in ordered:
            if tier_name in self._tier_pools and tier_name not in result:
                result.append(tier_name)
        return result

    def _retry_model_count_for(self, tier: str) -> int:
        """计算本轮可能尝试的去重模型数，用于避免 5 次上限卡死在单一小池。"""
        names = set()
        for tier_name in self._retry_tiers_for(tier):
            for model in self._tier_pools.get(tier_name, []):
                name = model.get("name")
                if name and not self._is_blacklisted(name) and not self._is_model_expired(model):
                    names.add(name)
        return len(names)

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

    def _get_tier_model(self, tier: str, require_circuit: bool = False) -> str:
        """获取指定层级池的当前模型名"""
        pool = self._tier_pools.get(tier, [])
        idx = self._tier_indices.get(tier, 0)
        if pool and idx < len(pool):
            total = len(pool)
            for offset in range(total):
                candidate_idx = (idx + offset) % total
                model_info = pool[candidate_idx]
                model_name = model_info["name"]
                if self._is_blacklisted(model_name):
                    continue
                if self._is_model_expired(model_info):
                    continue
                with self._perf_lock:
                    is_slow = model_name in self._slow_models
                if is_slow:
                    continue
                if require_circuit:
                    try:
                        opt = _get_optimizer()
                        if opt and opt.enabled and not opt.circuit.is_available(model_name):
                            continue
                    except Exception as opt_err:
                        logger.debug(f"熔断可用性检查跳过（非致命）：{opt_err}")
                if candidate_idx != idx:
                    self._tier_indices[tier] = candidate_idx
                    logger.warning(f"🔄 [{tier}] 模型切换 → {model_name}")
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
                with self._perf_lock:
                    is_slow = candidate in self._slow_models
                if is_slow:
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
            except Exception as e:
                logger.debug(f"操作异常: {e}")

    def _ensure_tier_model(self, tier: str):
        """确保指定层级池的当前模型可用"""
        pool = self._tier_pools.get(tier, [])
        idx = self._tier_indices.get(tier, 0)
        if pool and idx < len(pool):
            model_name = pool[idx]["name"]
            if self._is_blacklisted(model_name):
                self._next_tier_model(tier)
            elif self._is_model_expired(pool[idx]):
                self._next_tier_model(tier)

    def _record_response_time(self, model_name: str, elapsed: float):
        """记录模型响应时间，连续3次>10秒标记为慢速"""
        with self._perf_lock:
            if model_name not in self._response_times:
                self._response_times[model_name] = []
            times = self._response_times[model_name]
            times.append(elapsed)
            if len(times) > 3:
                times.pop(0)
            if len(times) >= 3 and all(t > 10.0 for t in times):
                self._slow_models[model_name] = time.time()
                logger.warning(f"🐌 模型 {model_name} 连续3次响应>10秒，标记为慢速")
            need_cleanup = len(self._response_times) > 20
        if need_cleanup:
            self._cleanup_stale_response_data()

    def _cleanup_stale_response_data(self):
        """清理过期的响应时间记录和慢速标记（超过1小时未访问的模型）"""
        now = time.time()
        all_model_names = set()
        for pool in self.model_pools.values():
            for m in pool:
                all_model_names.add(m.get("name", ""))
        for tier_pool in self._tier_pools.values():
            for m in tier_pool:
                all_model_names.add(m.get("name", ""))
        with self._perf_lock:
            stale_slow = [k for k, v in self._slow_models.items() if now - v > 3600]
            for k in stale_slow:
                del self._slow_models[k]
            stale_response = [k for k in self._response_times if k not in all_model_names]
            for k in stale_response:
                del self._response_times[k]
        if stale_slow or stale_response:
            logger.debug(f"🧹 清理过期响应数据: {len(stale_slow)}慢速+{len(stale_response)}响应")

    def _is_slow_model(self, model_name: str) -> bool:
        """检查模型是否被标记为慢速（5分钟后自动恢复）"""
        with self._perf_lock:
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

    def _get_model_request_options(self, model_name: str) -> dict:
        """读取模型级请求能力标记，不把供应方差异硬编码进业务分支。"""
        if not model_name:
            return {}
        pools = list(self.model_pools.values()) + list(self._tier_pools.values())
        for pool in pools:
            if not isinstance(pool, list):
                continue
            for model in pool:
                if isinstance(model, dict) and model.get("name") == model_name:
                    options = {}
                    if isinstance(model.get("enable_thinking"), bool):
                        options["enable_thinking"] = model["enable_thinking"]
                    return options
        return {}

    @classmethod
    def _is_model_suitable_for_mode(cls, model_name: str, mode: str) -> bool:
        """用户可见自然对话统一跳过 code/coder 专用模型。"""
        if mode in {"code", "coding"}:
            return True
        is_code_model = re.search(
            r"(?:^|[-_/])(code|coder|coding)(?:$|[-_/])",
            str(model_name or ""),
            flags=re.IGNORECASE,
        ) is not None
        return not is_code_model

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
                # 自动故障转移只更新内存索引；不能把临时回退写成重启后的永久顺序。
                if pool_name == "chat":
                    self.current_idx = idx
                logger.warning(f"🔄 [{pool_name}] 模型切换 → {candidate}")
                return

            # 所有模型都被拉黑或过期了
            logger.error(f"🚫 [{pool_name}] 所有模型均已拉黑或过期！请检查API余额或更新模型配置")
            try:
                from modules.auto_tasks import report_fault
                report_fault("模型池全部拉黑", f"{pool_name}池所有模型均已拉黑或过期，请检查API余额", "🚨")
            except Exception as e:
                logger.debug(f"操作异常: {e}")
    # ── 动态人格系统方法 ── [TRAE SOLO CN]

    def _get_emotional_state(self) -> str:
        """根据当前时间返回情绪状态追加文本（情绪状态机）"""
        states = (
            self._DEFAULT_EMOTIONAL_STATES
            if self._uses_reply_contract_v1()
            else self.config.get("EMOTIONAL_STATES", {}) or self._DEFAULT_EMOTIONAL_STATES
        )
        current_hour = datetime.now(_CST).hour
        for state_name, state_info in states.items():
            if current_hour in state_info.get("hours", []):
                mood = state_info.get("mood", "")
                prompt = state_info.get("prompt", "")
                return f"\n【当前情绪：{mood}】{prompt}"
        return ""

    def _get_persona_fragment_list(self, fragments_cfg: dict, key: str) -> list:
        """读取人设片段列表；生产配置缺字段时回退默认值，避免任务级 KeyError。"""
        if not isinstance(fragments_cfg, dict):
            fragments_cfg = {}
        value = fragments_cfg.get(key)
        if isinstance(value, list) and value:
            return value
        default_value = self._DEFAULT_PERSONA_FRAGMENTS.get(key, [])
        return default_value if isinstance(default_value, list) else []

    def _get_dynamic_fragments(self, seed: int = 0) -> str:
        """随机抽取说话方式，禁止注入肢体动作或虚构生活状态。"""
        fragments_cfg = (
            self._DEFAULT_PERSONA_FRAGMENTS
            if self._uses_reply_contract_v1()
            else self.config.get("PERSONA_FRAGMENTS", {}) or self._DEFAULT_PERSONA_FRAGMENTS
        )
        rng = random.Random(seed or int(time.time()))
        parts = []

        # 随机抽取1个语气基调
        mood_list = self._get_persona_fragment_list(fragments_cfg, "mood_expressions")
        if mood_list:
            parts.append(f"语气基调：{rng.choice(mood_list)}")

        # 随机抽取1个回应方式
        react_list = self._get_persona_fragment_list(fragments_cfg, "reaction_styles")
        if react_list:
            parts.append(f"回应方式：{rng.choice(react_list)}")

        return "\n".join(parts) if parts else ""

    def _get_few_shot_examples(self, seed: int = 0) -> str:
        """随机抽取2-3个对话示例，拼成few-shot引导文本"""
        examples_cfg = (
            self._DEFAULT_FEW_SHOT_EXAMPLES
            if self._uses_reply_contract_v1()
            else self.config.get("FEW_SHOT_EXAMPLES", []) or self._DEFAULT_FEW_SHOT_EXAMPLES
        )
        if not examples_cfg:
            return ""
        rng = random.Random(seed + 999 if seed else int(time.time()))
        count = rng.randint(2, min(3, len(examples_cfg)))
        chosen = rng.sample(examples_cfg, count)
        lines = ["【参考对话风格（不要照搬，领会精神）】"]
        for ex in chosen:
            lines.append(f"对方：「{ex['user']}」→ 你：「{ex['mory']}」")
        return "\n".join(lines)

    def _get_anti_template_hint(self, seed: int = 0) -> str:
        """随机生成一条反模板提示，防止回复套路化（v5.19.0 起改为 4 桶情绪反模板）"""
        # [v5.19.0] 人设引擎：4 桶情绪反模板（cold/savage/soft/common）
        # 行为：每轮从 1 个情绪桶 + 1 个通用桶各抽 1 条
        if self._uses_reply_contract_v1():
            # 生产 config 可能仍保存旧的“毒舌/敷衍”桶；合同模式必须以代码安全
            # 默认值为准，避免热重载把敌意指令重新带回群自动回复。
            buckets_cfg = self._DEFAULT_EMOTION_BUCKETS
            triggers_cfg = self._DEFAULT_EMOTION_TRIGGERS
        else:
            buckets_cfg = self.config.get("EMOTION_BUCKETS", {}) or self._DEFAULT_EMOTION_BUCKETS
            triggers_cfg = self.config.get("EMOTION_TRIGGERS", {}) or self._DEFAULT_EMOTION_TRIGGERS

        # 人设引擎未启用时回退老逻辑
        if not self.config.get("PERSONA_ENGINE_ENABLED", True):
            anti_cfg = self.config.get("ANTI_TEMPLATES", []) or self._DEFAULT_ANTI_TEMPLATES
            if not anti_cfg:
                return ""
            rng = random.Random(seed + 7777 if seed else int(time.time()))
            if rng.random() < 0.5:
                return f"【防重复指令】{rng.choice(anti_cfg)}"
            return ""

        # 人设引擎开启：先选情绪桶
        emotion_bucket = self._select_emotion_bucket(triggers_cfg)
        rng = random.Random(seed + 7777 if seed else int(time.time()))

        parts = []
        # 情绪桶（80% 概率注入，让模型能感受到但不至于完全锁死）
        bucket_pool = buckets_cfg.get(emotion_bucket, [])
        if bucket_pool and rng.random() < 0.8:
            parts.append(rng.choice(bucket_pool))
        # 通用桶（每轮必抽 1 条）
        common_pool = buckets_cfg.get("common", [])
        if common_pool:
            parts.append(rng.choice(common_pool))

        if not parts:
            return ""
        return f"【本轮人设指令 / 情绪桶：{emotion_bucket}】\n" + "\n".join(parts)

    def _select_emotion_bucket(self, triggers_cfg: dict) -> str:
        """[v5.19.0] 根据 context（is_priv/hour/intimacy/keywords）选择主导情绪桶"""
        is_priv = getattr(self, "_ctx_is_priv", False)
        hour = datetime.now(_CST).hour
        score = getattr(self, "_ctx_intimacy_score", 0)
        message = getattr(self, "_ctx_message", "")

        scores = {"cold": 1.0, "savage": 0.0, "soft": 0.0}  # cold 是底色

        for bucket, rules in triggers_cfg.items():
            for rule in rules:
                w = rule.get("weight", 1.0)
                matched = False
                if "is_priv" in rule and "intimacy_min" in rule and "hour_in" in rule:
                    if (is_priv == rule["is_priv"]
                            and score >= rule["intimacy_min"]
                            and hour in rule["hour_in"]):
                        matched = True
                if "keywords" in rule:
                    msg_lower = (message or "").lower()
                    if any(kw.lower() in msg_lower for kw in rule["keywords"]):
                        matched = True
                if "message_max_len" in rule:
                    if message and len(message.strip()) <= rule["message_max_len"]:
                        matched = True
                if matched:
                    scores[bucket] = scores.get(bucket, 0) + w

        # 选出最高分（cold 是默认兜底）
        return max(scores, key=scores.get)

    def _get_dynamic_llm_params(self, is_priv: bool, intimacy_level: int, hour: int) -> tuple:
        """[v5.19.0] 动态 LLM 参数：按 is_priv × intimacy_level × 时段查表"""
        param_map = self.config.get("EMOTION_TEMP_MAP", {}) or self._DEFAULT_EMOTION_TEMP_MAP
        scene = "priv" if is_priv else "group"

        # 时段归一化
        if 0 <= hour <= 4:
            hour_bucket = "midnight"
        elif 5 <= hour <= 7:
            hour_bucket = "morning"
        elif 8 <= hour <= 11:
            hour_bucket = "morning"
        elif hour in (12, 13):
            hour_bucket = "noon"
        elif 14 <= hour <= 17:
            hour_bucket = "afternoon"
        elif 18 <= hour <= 20:
            hour_bucket = "evening"
        elif 21 <= hour <= 23:
            hour_bucket = "night"
        else:
            hour_bucket = "any"

        # 精确查表
        key = (scene, intimacy_level, hour_bucket)
        if key in param_map:
            return param_map[key]
        # 退到 "any" 时段
        key_any = (scene, intimacy_level, "any")
        if key_any in param_map:
            return param_map[key_any]
        # 最终兜底
        return (self.config.get("TEMPERATURE", 0.92),
                self.config.get("TOP_P", 0.92),
                self.config.get("FREQUENCY_PENALTY", 0.5),
                self.config.get("PRESENCE_PENALTY", 0.4))

    def _get_broadcast_enhancer(self, seed: int = 0) -> str:
        """[v5.18.3] 播报增强层：随机抽取情绪/场景/收尾风格注入播报 prompt"""
        rng = random.Random(seed or int(time.time()))
        parts = []

        # 随机抽取1个情绪注入
        emotion_list = self._BROADCAST_PROMPT_ENHANCERS.get("emotion_inject", [])
        if emotion_list:
            parts.append(f"【此刻心情】{rng.choice(emotion_list)}")

        # 随机抽取1个收尾风格
        hook_list = self._BROADCAST_PROMPT_ENHANCERS.get("hook_styles", [])
        if hook_list:
            parts.append(f"【收尾建议】{rng.choice(hook_list)}")

        # 30%概率追加一个人格碎片（mood_expression）
        if rng.random() < 0.3:
            mood_list = self._DEFAULT_PERSONA_FRAGMENTS.get("mood_expressions", [])
            if mood_list:
                parts.append(f"【状态碎片】{rng.choice(mood_list)}")

        return "\n".join(parts) if parts else ""

    # ── 维度1：上下文感知碎片选择 ── [TRAE SOLO CN]

    def _classify_intent(self, message: str) -> str:
        """轻量意图分类：根据关键词匹配+权重打分，返回意图标签"""
        msg_lower = message.lower()
        try:
            from core.keyword_manager import is_convert_rejection_message
            if is_convert_rejection_message(msg_lower):
                return "help"
        except Exception as e:
            logger.debug(f"拒买关键词检测跳过（非致命）：{e}")
        scores = {}
        for intent, cfg in self._INTENT_KEYWORDS.items():
            kws = cfg.get("keywords", [])
            if not kws:
                continue
            hit = sum(1 for kw in kws if kw in msg_lower)
            if hit > 0:
                scores[intent] = hit * cfg.get("weight", 1.0)
        if not scores:
            return "chat"
        return max(scores, key=scores.get)

    def _classify_dialogue_tone_intent(
        self,
        message: str,
        mode: str = "normal",
        stage_hint: str = "",
    ) -> str:
        """把现有业务意图归一为六类语气；预览保留咨询，明确下单才成交。"""
        compact = str(message or "").strip().lower()
        hint = str(stage_hint or "").lower()

        subscribe_markers = (
            "@morychannelbot",
            "唯一目标：subscribe",
            "目标=subscribe",
            "意图-购买",
            "转化-自助",
            "明确购买",
            "自助下单",
        )
        preview_markers = (
            "@moryselect",
            "唯一目标：preview",
            "目标=preview",
            "意图-了解",
            "先预览",
            "预览目标",
        )
        if any(marker in hint for marker in subscribe_markers):
            return "convert"
        if any(marker in hint for marker in preview_markers):
            return "curiosity"

        emotional_markers = (
            "失恋", "难受", "伤心", "想哭", "崩溃", "焦虑", "压力",
            "孤独", "寂寞", "睡不着", "失眠", "心累", "撑不住", "不开心",
        )
        challenge_markers = (
            "机器人", "人工智能", "ai", "gpt", "自动回复", "假的",
            "骗人", "骗子", "套路", "不靠谱", "真的假的", "靠谱吗",
            "别装", "完整版本", "完整版", "多少秒", "时长",
        )
        curiosity_markers = (
            "什么", "怎么", "如何", "为什么", "多少", "哪里", "在哪",
            "有没有", "能不能", "可以吗", "吗", "？", "?",
        )
        casual_short_messages = {
            "你好", "嗨", "hi", "hello", "在吗", "在不在", "早安",
            "午安", "晚安", "哈哈", "嗯", "嗯嗯", "哦", "好吧", "没事",
        }
        if compact in casual_short_messages:
            return "casual"
        if any(marker in compact for marker in emotional_markers):
            return "emotional"
        if any(marker in compact for marker in challenge_markers):
            return "challenge"

        legacy_intent = self._classify_intent(compact)
        if legacy_intent == "flirt":
            return "flirt"
        if legacy_intent == "complaint":
            return "challenge"
        if legacy_intent in {"business", "help"}:
            return "curiosity"
        if mode == "convert":
            # 没有明确 subscribe 提示时，convert mode 仍处于了解/预览阶段。
            return "curiosity"
        if any(marker in compact for marker in curiosity_markers):
            return "curiosity"
        return "casual"

    def _build_dialogue_tone_contract(
        self,
        intent: str,
        *,
        is_priv: bool,
    ) -> str:
        """返回每轮必带的温情人设合同；配置缺项时逐项回退安全默认值。"""
        configured = self.config.get("DIALOGUE_TONE_CONTRACTS")
        contracts = (
            configured
            if isinstance(configured, dict)
            else self._DEFAULT_DIALOGUE_TONE_CONTRACTS
        )
        normalized = (
            intent
            if intent in self._CONVERSATIONAL_TONE_INTENTS
            else "casual"
        )
        shared = str(
            contracts.get("shared")
            or self._DEFAULT_DIALOGUE_TONE_CONTRACTS["shared"]
        ).strip()
        specific = str(
            contracts.get(normalized)
            or self._DEFAULT_DIALOGUE_TONE_CONTRACTS[normalized]
        ).strip()
        channel = (
            "【渠道语气：私聊】可以更耐心、更柔软一点，但不默认亲密关系。"
            if is_priv
            else "【渠道语气：群聊】保持短、自然、会接话，不过度撩单个用户。"
        )
        return "\n".join(part for part in (shared, specific, channel) if part)

    def _get_context_aware_fragments(self, message: str, seed: int = 0) -> str:
        """按意图选择说话方式，不生成动作、旁白或虚构生活状态。"""
        intent = self._classify_intent(message)
        rng = random.Random(seed or int(time.time()))
        fragments_cfg = (
            self._DEFAULT_PERSONA_FRAGMENTS
            if self._uses_reply_contract_v1()
            else self.config.get("PERSONA_FRAGMENTS", {}) or self._DEFAULT_PERSONA_FRAGMENTS
        )
        parts = []

        # 根据意图选择不同的心情/反应倾向
        intent_mood_map = {
            "flirt": ["可以小傲娇地回撩一句，不主动升级关系", "语气有点软，但不演害羞或动作"],
            "business": ["清楚回答已知信息，不故作神秘", "语气自然，直接讲重点"],
            "help": ["先接住问题，再给一句实际帮助", "温柔一点，但不变成客服"],
            "complaint": ["先承认对方的不舒服，再处理问题", "保持克制，不阴阳怪气"],
            "bored": ["自然接一句新话题，不强行热闹", "回复轻一点，别演吃醋或失落"],
            "chat": [],  # 默认：用全部池
        }
        preferred_moods = intent_mood_map.get(intent, [])

        # 心情表达
        mood_list = self._get_persona_fragment_list(fragments_cfg, "mood_expressions")
        if preferred_moods:
            # 70%概率从偏好池选，30%从全池选（保持随机性）
            if rng.random() < 0.7 and preferred_moods:
                parts.append(f"语气基调：{rng.choice(preferred_moods)}")
            else:
                parts.append(f"语气基调：{rng.choice(mood_list)}")
        elif mood_list:
            parts.append(f"语气基调：{rng.choice(mood_list)}")

        # 反应风格：根据意图选不同风格
        intent_react_map = {
            "flirt": ["先小傲娇地接住，再自然回一句", "可以轻巧接梗，但不反讽、不演剧情"],
            "business": ["直接回答，再给明确入口", "只说确认过的信息，不脑补"],
            "help": ["先复述关键点，再给简短办法", "认真回答，不写思考过程"],
            "complaint": ["先共情，再说处理路径", "不辩解，不演委屈"],
            "bored": ["接住原话，再抛一个自然问题", "可以简短，不故意装没听见"],
            "chat": [],
        }
        preferred_reacts = intent_react_map.get(intent, [])
        react_list = self._get_persona_fragment_list(fragments_cfg, "reaction_styles")
        if preferred_reacts and rng.random() < 0.7:
            parts.append(f"回应方式：{rng.choice(preferred_reacts)}")
        elif react_list:
            parts.append(f"回应方式：{rng.choice(react_list)}")

        return "\n".join(parts) if parts else ""

    # ── 维度2：用户行为判断 ── [TRAE SOLO CN]

    def _calc_intimacy_score(self, user_profile: dict | None) -> int:
        """根据用户画像计算亲密度分数（0-200+）"""
        if not user_profile:
            return 0
        score = 0
        # 基础分：消息量
        group_msgs = user_profile.get("group_messages", 0)
        priv_msgs = user_profile.get("private_messages", 0)
        score += min(group_msgs * 0.3, 30)  # 群消息最多贡献30分
        score += min(priv_msgs * 2, 50)     # 私聊权重更高，最多50分
        # 等级分
        level = user_profile.get("level", 1)
        score += min(level * 3, 30)          # 等级最多贡献30分
        # 积分分
        points = user_profile.get("points", 0)
        score += min(points * 0.01, 20)      # 积分最多贡献20分
        # 转化漏斗加分
        funnel = user_profile.get("funnel", {})
        score += funnel.get("touched", 0) * 2
        score += funnel.get("interested", 0) * 5
        score += funnel.get("consulted", 0) * 10
        score += funnel.get("paid", 0) * 30
        # 活跃度加分
        active_time = user_profile.get("active_time", "")
        if "深夜" in active_time:
            score += 5  # 深夜活跃的人更容易亲密
        return int(min(score, 200))

    def _get_intimacy_level(self, score: int) -> tuple:
        """根据分数返回亲密度等级信息 (level_name, label, style, flirt_level)"""
        levels = self.config.get("INTIMACY_LEVELS", {}) or self._INTIMACY_LEVELS
        current = "stranger"
        for level_name, info in sorted(levels.items(), key=lambda x: x[1].get("min_score", 0)):
            if score >= info.get("min_score", 0):
                current = level_name
        info = levels.get(current, self._INTIMACY_LEVELS["stranger"])
        return (current, info.get("label", ""), info.get("style", ""), info.get("flirt_level", 0))

    def _get_intimacy_prompt(self, user_profile: dict | None, seed: int = 0) -> str:
        """根据亲密度等级生成追加prompt"""
        score = self._calc_intimacy_score(user_profile)
        level_name, label, style, flirt_level = self._get_intimacy_level(score)
        if self._uses_reply_contract_v1():
            return (
                f"\n【熟悉度：{label}】熟悉度只影响耐心和措辞："
                "群聊保持短而克制；私聊可以稍微亲近，但不主动暧昧、不使用占有或依赖式表达。"
            )
        rng = random.Random(seed + 3333 if seed else int(time.time()))

        parts = [f"\n【亲密度：{label}（{score}分）】与对方互动风格：{style}"]

        # 挑逗话术：亲密度>=2时，20%概率追加一条挑逗话术
        flirt_templates = self.config.get("FLIRT_TEMPLATES", {}) or self._FLIRT_TEMPLATES
        if flirt_level >= 2 and rng.random() < 0.2:
            flirt_pool = flirt_templates.get(flirt_level, [])
            if flirt_pool:
                parts.append(f"此刻可以自然说出：{rng.choice(flirt_pool)}")

        return "\n".join(parts)

    def _get_rhythm_hint(self, message: str, message_len: int = 0) -> str:
        """对话节奏感知：根据消息特征给出节奏提示"""
        hints = []
        msg_len = message_len or len(message)

        # 消息很短（敷衍信号）
        if msg_len <= 3:
            hints.append("对方回复很短，简短接住即可；不要自行判定冷淡、吃醋或强行续话题。")
        # 消息很长（认真信号）
        elif msg_len >= 50:
            hints.append("对方很认真在说，你也要认真回应，但保持人设不变成客服。")
        # 问号多（急迫信号）
        elif message.count("？") + message.count("?") >= 2:
            hints.append("对方连续提问，比较急迫。认真回答但保持人设，别变客服。")

        return hints[0] if hints else ""

    # ── 维度3：交互语境 + 转化引导 ──

    def _get_scene_prompt(self, is_priv: bool, seed: int = 0) -> str:
        """根据时间和会话类型匹配交互语境，不模拟现实画面。"""
        current_hour = datetime.now(_CST).hour
        scenes_cfg = (
            self._SCENE_TEMPLATES
            if self._uses_reply_contract_v1()
            else self.config.get("SCENE_TEMPLATES", {}) or self._SCENE_TEMPLATES
        )
        matched = []

        for scene_name, scene_info in scenes_cfg.items():
            scene_cfg = scene_info if isinstance(scene_info, dict) else {}
            trigger = scene_cfg.get("trigger", {})
            trigger = trigger if isinstance(trigger, dict) else {}
            hours = trigger.get("hours")
            priv_required = trigger.get("is_priv")

            # 时间匹配
            time_ok = hours is None or current_hour in hours
            # 场景匹配
            priv_ok = priv_required is None or priv_required == is_priv

            if time_ok and priv_ok:
                matched.append(scene_info)

        if not matched:
            return ""

        # 优先选最精确匹配的（hours不为None且is_priv匹配的）
        rng = random.Random(seed + 5555 if seed else int(time.time()))
        chosen = rng.choice(matched)
        return f"\n{chosen.get('prompt', '')}"

    def _get_conversion_hook(self, intent: str, flirt_level: int, seed: int = 0) -> str:
        """成交由 handler 的唯一目标决定，不能由亲密度或随机钩子越级触发。"""
        return ""

    def _get_anti_ai_hint(self) -> str:
        """提示自然聊天，不伪造身份。"""
        return ("\n【自然回复铁律】"
                "\n1. 禁止使用：作为/根据/建议/可以帮助/为您提供/请问/需要注意的是/总的来说/综上所述"
                "\n2. 不主动讨论系统身份；被直接问到时如实简短说明自己是 Mory 小助理，不冒充真人。"
                "\n3. 禁止格式化回复：不用1.2.3.列表，不用'首先其次最后'"
                "\n4. 禁止客服腔：不说'感谢您的耐心'/'请问还有什么可以帮您'"
                "\n5. 所有意图都以温情为底色；轻微绿茶感、俏皮、含蓄纯欲只改变表达温度，不改变事实和边界"
                "\n6. 只输出聊天正文，禁止括号/星号动作、舞台指示、心理旁白和镜头描写"
                "\n7. 禁止编造自己正在看窗外、喝咖啡、发呆、刚睡醒或听到提示音等现实状态"
                "\n8. 正常怀疑、追问、重复确认和短消息都要友好承接，不讽刺、不挖苦、不责怪、不命令、不赶客")

    def _uses_reply_contract_v1(self) -> bool:
        return str(self.config.get("REPLY_CONTRACT_VERSION", "")) == "1.0.0"

    @staticmethod
    def _reply_contract_v1_persona() -> str:
        return (
            "你是 Mory 小助理。所有对话类型都走同一人设：温情是底色，"
            "轻微绿茶感只表现为会接话和柔软反差，俏皮只表现为轻松机灵，"
            "轻微纯欲感只来自干净、含蓄、柔和的措辞。\n"
            "不同场景只调整四种气质的权重，不改变身份、事实、边界或 conversion target；"
            "群聊短而自然，私聊可以更耐心一点。\n"
            "先回答用户当前问题并结合最近上下文；不知道就直接说不确定。\n"
            "不声明自己是真人，也不主动争论身份；被直接问到时简短如实说明是 Mory 小助理。\n"
            "只通过措辞、节奏和长短体现随机变化；不写动作、环境、镜头、内心旁白或虚构生活。\n"
            "把怀疑、追问和重复确认都当成正常咨询：先温柔接住，再说明已知范围；"
            "不讽刺、不挖苦、不责怪、不命令、不赶客。\n"
            "不编造商品内容、价格、权益、定制能力、交付或人工承诺；不使用虚假稀缺、社会证明、比较施压或私聊导流。\n"
            "成交只服从本轮唯一目标：无目标就正常聊天；了解阶段只给 @moryselect；明确购买或确认看过预览才给 @MorychannelBot。"
        )

    @staticmethod
    def _strip_legacy_stage_prompt_lines(text: str) -> str:
        """移除旧配置中会压过当前聊天/成交合同的冲突行。"""
        if not text:
            return text
        blocked_markers = (
            "*动作*", "肢体暗示", "肢体语言", "舞台动作",
            "动作描写", "场景旁白", "心理旁白",
            "所有对话的终极目标", "用小钩子留悬念", "私聊引导转化",
            "第3-4轮：可以稍微暗示", "第5轮+：自然带一句",
            "立即引导 @MorychannelBot", "价格/业务 →", "被问价格 →",
        )
        lines = [
            line for line in str(text).splitlines()
            if not any(marker in line for marker in blocked_markers)
        ]
        return "\n".join(lines)

    @staticmethod
    def _get_normal_chat_output_contract() -> str:
        """最终输出合同：保留人设语气，但禁止把聊天写成角色扮演小说。"""
        return (
            "\n\n【最终回复格式（最高优先级）】"
            "\n- 只回复对方会直接看到的聊天正文，像微信里正常回消息。"
            "\n- 所有对话都以温情为底色；轻微绿茶感、俏皮和含蓄纯欲只能通过选词、语气和长短表现。"
            "\n- 正常怀疑、追问、重复确认和短消息都要友好承接；不讽刺、不挖苦、不责怪、不命令、不赶客。"
            "\n- 严禁在圆括号、中文括号或星号里写动作、表情、心理活动、环境和镜头旁白。"
            "\n- 严禁脑补自己或对方正在看窗外、托腮、发呆、喝咖啡、刚睡醒、听到提示音才回神等画面。"
            "\n- 对方只是问候、问“在吗”或发很短的消息时，直接回应并问来意；对方没先调情就不要擅自加“想我了”之类暧昧戏码。"
            "\n- 先直接回应用户说的话；没有可靠信息就不要补生活经历或现场细节。"
            "\n- 对话轮数只影响熟悉度和语气，不能因为聊到第3/5/6轮就突然塞销售、私聊或收网话术。"
            "\n- 成交入口只服从本轮 stage_hint 的唯一目标：了解价格/内容先预览，明确购买才自助；目标为空就不带入口。"
            "\n- 不承诺未由知识库确认的定制能力、表单、价格、福利、交付或人工回访。"
        )

    @staticmethod
    def _sanitize_reply(text: str) -> str:
        """将过度正式的口吻改为自然表达；不再过滤或伪造身份信息。"""
        if not text:
            return text
        import re
        patterns = [
            (r'我不能帮', '我不太想'),
            (r'我无法帮', '我不太好弄'),
            (r'我不能提供', '我不太方便'),
            (r'我无法提供', '我不太好弄'),
        ]
        for pat, rep in patterns:
            text = re.sub(pat, rep, text, flags=re.IGNORECASE)
        return text

    @staticmethod
    def _strip_stage_directions(text: str) -> str:
        """删除模型偶发输出的动作/心理/镜头旁白，保留正常聊天正文。"""
        if not text:
            return text
        import re

        strong_cues = (
            "托腮", "托着下巴", "看窗外", "望向窗", "回过神",
            "把手机拿近", "拿近手机", "放下手机", "瞥一眼", "揉眼睛", "偷偷看你", "心理活动",
            "内心独白", "镜头转向", "脑补画面",
        )
        leading_cues = (
            "歪头", "挑眉", "伸懒腰", "打哈欠", "发呆", "凑近",
            "转身", "低头", "抬头", "眨眼", "撇嘴", "嘟嘴", "耸肩",
            "摇头", "点头", "扶额", "捂脸", "脸红", "微笑", "笑出声",
            "偷笑", "苦笑", "叹气", "沉默", "愣住", "愣了一下",
            "假装", "心里", "内心", "认真想", "想了想", "思考片刻",
            "抱抱", "抱住", "摸摸", "拍拍", "亲亲", "捏脸",
            "轻声说", "小声说", "缓缓开口",
        )
        factual_markers = (
            "会", "可能", "容易", "导致", "需要", "请", "属于",
            "是指", "指的是", "时应", "之后", "以后",
        )

        def _remove_if_stage(match):
            body = match.group("body")
            compact = re.sub(r"\s+", "", body)
            if any(marker in compact for marker in factual_markers):
                return match.group(0)
            normalized_start = re.sub(
                r"^(?:先|又|再|轻轻|缓缓|默默|突然|有些|不由得|忍不住)+",
                "",
                compact,
            )
            is_stage = (
                any(cue in compact for cue in strong_cues)
                or normalized_start.startswith(leading_cues)
            )
            return "" if is_stage else match.group(0)

        text = re.sub(
            r"（(?P<body>[^（）\n]{1,120})）",
            _remove_if_stage,
            text,
        )
        text = re.sub(
            r"\((?P<body>[^()\n]{1,120})\)",
            _remove_if_stage,
            text,
        )
        text = re.sub(
            r"\*(?P<body>[^*\n]{1,80})\*",
            _remove_if_stage,
            text,
        )
        text = re.sub(
            r"【(?P<body>[^【】\n]{1,120})】",
            _remove_if_stage,
            text,
        )
        text = re.sub(
            r"\[(?P<body>[^\[\]\n]{1,120})\]",
            _remove_if_stage,
            text,
        )
        text = re.sub(r"^[\s，,、:：;；\-—]+", "", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _check_pinyin_leak(text: str) -> bool:
        """【v5.23.0 P0-2】拼音无声调检测，防止 "wo shi AI" / "ren gong zhi neng" 等变体绕过。

        Returns:
            True 检测到穿帮，False 安全
        """
        if not text:
            return False
        try:
            from core.pinyin_util import text_to_pinyin_silent
            pinyin_text = text_to_pinyin_silent(text)
            # 检测拼音级别的穿帮词
            leak_patterns = [
                'wo shi ai', 'wo shi a i',
                'ren gong zhi neng', 'ren gong zhi neng',
                'zuo wei ai', 'zuo wei a i',
                'zuo wei mo xing', 'zuo wei mo xing',
                'wo shi mo xing', 'wo shi ge cheng xu',
                'zuo wei zhu shou', 'wo shi zhu shou',
                'wo shi ge ji qi ren', 'ji qi ren',
            ]
            pinyin_lower = pinyin_text.lower()
            for pat in leak_patterns:
                if pat in pinyin_lower:
                    return True
        except ImportError:
            # pinyin_util 未安装，跳过拼音检测（不影响主流程）
            pass
        except Exception as e:
            logger.debug(f"拼音身份泄露检测跳过（非致命）：{e}")
        return False

    @staticmethod
    def _soften_hostile_reply(text: str) -> tuple[str, bool]:
        """拦截模型偶发的怼人/赶客输出，统一降级为友好承接。"""
        if not text:
            return text, False
        clarification_patterns = (
            r"话都不说全",
            r"考我阅读理解",
            r"说清楚点",
            r"我干嘛告诉你",
            r"替你尴尬",
            r"自己玩去",
        )
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in clarification_patterns):
            return "我可能没接准你的意思，你再补一句就好。", True
        hostile_patterns = (
            r"爱信不信",
            r"不信(?:就|拉倒)",
            r"别再问(?:了)?",
            r"问这么多",
            r"懒得(?:理|说|解释)",
            r"不想理你",
            r"我没空",
            r"关我什么事",
            r"自己不会",
            r"你是不是(?:傻|蠢)",
            r"去别处",
            r"好坏你自己(?:分辨|判断)(?:就行)?",
            r"自己(?:去)?.{0,30}(?:看|分辨|判断)(?:就行)?",
        )
        if not any(re.search(pattern, text, re.IGNORECASE) for pattern in hostile_patterns):
            return text, False
        return (
            "你会再确认很正常呀。我只按已经确认的信息跟你说，"
            "没把握的不会随口糊弄你。",
            True,
        )

    @staticmethod
    def _sanitize_reply_v2(text: str) -> tuple:
        """【v5.23.0 P0-2】增强版后置过滤，返回 (过滤后文本, 是否触发过滤)

        触发过滤时，调用方应降低 temperature 重试。
        """
        if not text:
            return text, False
        original = text
        # 第一层：正则全字匹配
        sanitized = AIEngine._sanitize_reply(text)
        # 第二层：拼音无声调检测
        pinyin_leak = AIEngine._check_pinyin_leak(sanitized)
        identity_changed = sanitized != original
        # 第三层：移除括号/星号动作和心理旁白。混合回复直接保留正文；
        # 若整条只剩舞台动作，则触发一次重试，避免发送空消息。
        stage_filtered = AIEngine._strip_stage_directions(sanitized)
        stage_changed = stage_filtered != sanitized
        stage_filtered, hostile_changed = AIEngine._soften_hostile_reply(stage_filtered)
        identity_leak = any(
            re.search(pattern, stage_filtered, re.IGNORECASE)
            for pattern in (
                r"(?:作为|我是|身为)\s*(?:一?个)?\s*(?:AI|人工智能|语言模型|机器人|程序)",
                r"我(?:不需要|不用)(?:睡觉|吃饭|休息)",
                r"我没有(?:身体|现实生活|真实情绪)",
            )
        )
        if pinyin_leak or identity_leak:
            stage_filtered = ""
        stage_only = bool(sanitized.strip()) and not bool(stage_filtered.strip())
        triggered = (
            identity_changed
            or pinyin_leak
            or identity_leak
            or stage_changed
            or stage_only
            or hostile_changed
        )
        return stage_filtered, triggered

    @staticmethod
    def _get_festival_persona() -> str:
        """根据当前日期返回不改变身份和关系边界的轻量节日语气。"""
        now = datetime.now(_CST)
        m, d = now.month, now.day
        if m == 2 and d == 14:
            return "\n【今天是情人节：可以自然提一句节日，但不默认亲密关系、不吃醋、不调情。】"
        elif m == 10 and d == 31:
            return "\n【今天是万圣节：语气可以轻松一点，但不扮演虚构角色或编造场景。】"
        elif m == 1 and d in range(1, 8):
            return "\n【当前处于新年假期：可以简短问候，不索要红包、不编造活动或福利。】"
        elif m == 6 and d == 1:
            return "\n【今天是儿童节：可以轻松一点，但保持 Mory 小助理身份。】"
        elif m == 8 and d == 7:
            return "\n【今天是七夕：可以自然提一句节日，但不默认恋爱关系、不黏人、不调情。】"
        return ""

    def _get_mode_persona(self, mode: str, seed: int = 0, stage_hint: str = "") -> tuple:
        """根据模式返回prompt文本。返回 (text, is_full_replacement)
        stage_hint: 递进引导提示词，由main.py根据对话轮次动态生成
        """
        seed_hint = f"\n【随机种子{seed}，必须生成全新的文案，绝对不能重复】" if seed else ""
        # 配置只覆盖明确给出的 mode；不能因为配置里有少量自定义模板，
        # 就把问候等内置模板整组丢掉。
        modes = dict(self._DEFAULT_PROMPT_TEMPLATES)
        configured_modes = {} if self._uses_reply_contract_v1() else self.config.get("PROMPT_TEMPLATES", {})
        if isinstance(configured_modes, dict):
            legacy_greeting_modes = []
            for configured_mode, configured_prompt in configured_modes.items():
                prompt_text = str(configured_prompt or "")
                if configured_mode in self._GREETING_PROMPT_MODES:
                    if (
                        "熟悉的粉丝群" not in prompt_text
                        or "延续主助理人设" not in prompt_text
                        or "不写AI、编程、运维或效率指导" not in prompt_text
                    ):
                        legacy_greeting_modes.append(configured_mode)
                        continue
                modes[configured_mode] = configured_prompt
            if (
                legacy_greeting_modes
                and not getattr(self, "_legacy_greeting_prompt_warned", False)
            ):
                logger.warning(
                    "检测到旧版问候提示词覆盖，已自动忽略并使用粉丝群人设模板："
                    + ",".join(sorted(legacy_greeting_modes))
                )
                self._legacy_greeting_prompt_warned = True
        if mode not in modes:
            return ("", False)
        if mode in ("leak", "rules", "morning", "afternoon", "evening", "night"):
            return (modes[mode].replace("{seed_hint}", seed_hint), True)
        elif mode == "convert":
            return (modes[mode].replace("{convert_stage_hint}", stage_hint), False)
        else:
            # 其他模式（normal/treehole/dream/tarot等）：追加stage_hint
            base = modes[mode]
            if stage_hint:
                base += f"\n{stage_hint}"
            return (base, False)

    def _get_greeting_persona_anchor(self) -> str:
        """提取主助理人设的稳定身份和性格，供定时问候继承。

        问候不加载业务知识、转化钩子和对话记忆，避免把群内问候写成销售或
        单人私聊；同时不再用一个孤立模板替换掉 BASE_PERSONA。
        """
        cfg = self.config
        if self._uses_reply_contract_v1():
            base = self._reply_contract_v1_persona()
            style = ""
        else:
            base = str(cfg.get("BASE_PERSONA") or cfg.get("SYSTEM_PROMPT") or "").strip()
            style = str(cfg.get("STYLE_APPEND") or "").strip()
        base = self._strip_legacy_stage_prompt_lines(base)

        selected_lines = []
        current_section = False
        allowed_sections = {"【身份锚定】", "【性格光谱】"}
        for line in base.splitlines():
            stripped = line.strip()
            if stripped.startswith("【") and stripped.endswith("】"):
                current_section = stripped in allowed_sections
            if current_section:
                selected_lines.append(line)

        identity = "\n".join(selected_lines).strip()
        if not identity:
            identity = base[:800].strip()
        parts = ["【主助理人设底色】", identity]
        if style:
            parts.extend(["【当前风格调整】", style])
        parts.append(
            "以上只决定说话的性格和亲近感；本次是面向整个粉丝群的定时问候，"
            "温情托底，可以轻俏皮和含蓄柔和，但不得写成私聊、销售、"
            "效率指导、挖苦对呛或虚构生活剧情。"
        )
        return "\n".join(part for part in parts if part)

    def _build_persona(self, mode: str, seed: int = 0, is_priv: bool = False, stage_hint: str = "", user_profile: dict = None, message: str = "", model_name: str = None) -> str:
        """根据模式动态拼装 system prompt，seed用于防重复

        参数：
            mode: 模式名称
            seed: 随机种子
            is_priv: 是否私聊场景，影响人设追加
            user_profile: [TRAE SOLO CN] 用户画像（用于亲密度计算）
            message: [TRAE SOLO CN] 当前用户消息（用于意图分类和上下文感知）
            model_name: [阶段2-B] 当前使用的模型名（用于人设跨模型适配）

        结构化人设拼装顺序（v5.3.0升级版）：
        1. BASE_PERSONA — 核心人设（稳定不变）
        2. STYLE_APPEND — 风格追加
        3. KNOWLEDGE — 业务知识库
        4. ADDED_KNOWLEDGE — 追加知识
        5. [v5.2] 动态人格碎片（上下文感知版）
        6. [v5.2] 情绪状态机（按时段切换）
        7. [v5.2] Few-shot示例
        8. [v5.2] 反模板提示
        9. [v5.3] 亲密度系统（5级递进+挑逗话术）
        10. [v5.3] 对话节奏感知
        11. [v5.3] 交互语境（7类时间/会话节奏）
        12. [v5.3] 转化引导（自然植入）
        13. [v5.3] 去AI化铁律
        14. 场景感知追加（私聊/群聊差异化）
        15. 节日人格追加
        16. 模式人格追加（或完整替换）
        17. [阶段2-B] 人设跨模型适配（按模型家族强化差异化约束）
        兼容旧配置：如果只有SYSTEM_PROMPT则自动迁移
        """
        cfg = self.config

        # ── 结构化人设拼装（向下兼容旧SYSTEM_PROMPT）──
        if self._uses_reply_contract_v1():
            # 合同模式不再读取旧的配置人设或商品资料，避免热重载把历史污染带回运行时。
            persona = self._reply_contract_v1_persona()
        elif "BASE_PERSONA" in cfg:
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
        persona = self._strip_legacy_stage_prompt_lines(persona)

        # [v5.2] 动态人格碎片（升级为上下文感知版）
        if message:
            dynamic_fragments = self._get_context_aware_fragments(message, seed)
        else:
            dynamic_fragments = self._get_dynamic_fragments(seed)
        if dynamic_fragments:
            persona += f"\n\n【此刻人格碎片】\n{dynamic_fragments}"

        # [v5.2] 情绪状态机（按时段切换情绪底色）
        emotional_state = self._get_emotional_state()
        if emotional_state:
            persona += emotional_state

        # [v5.2] Few-shot示例
        few_shot = self._get_few_shot_examples(seed)
        if few_shot:
            persona += f"\n\n{few_shot}"

        # [v5.2] 反模板提示
        anti_template = self._get_anti_template_hint(seed)
        if anti_template:
            persona += f"\n\n{anti_template}"

        # [v5.3] 亲密度系统
        intimacy_prompt = self._get_intimacy_prompt(user_profile, seed)
        if intimacy_prompt:
            persona += intimacy_prompt

        # [v5.3] 对话节奏感知
        if message:
            rhythm_hint = self._get_rhythm_hint(message)
            if rhythm_hint:
                persona += f"\n\n【节奏感知】{rhythm_hint}"

        # [v5.3] 交互语境
        scene_prompt = self._get_scene_prompt(is_priv, seed)
        if scene_prompt:
            persona += scene_prompt

        # [v5.3] 转化引导
        intent = self._classify_intent(message) if message else "chat"
        _, _, _, flirt_level = self._get_intimacy_level(self._calc_intimacy_score(user_profile))
        conversion_hook = self._get_conversion_hook(intent, flirt_level, seed)
        if conversion_hook:
            persona += conversion_hook

        # [v5.3] 去AI化铁律
        persona += self._get_anti_ai_hint()

        # 场景感知追加
        if is_priv:
            # 私聊首次对话（消息很短或/start命令）：自然打招呼，不要强行撒娇
            if message and len(message.strip()) <= 10:
                persona += "\n\n【当前场景：私聊-首次】对方刚点进来，消息很短。自然打招呼就好，不要强行撒娇/撩人/演内心戏。对方没先调情时，不要主动问“想我了”或编排对方情绪。像正常朋友聊天一样，根据对方说的内容回应。如果对方只是/start，简单打个招呼问对方想聊什么就行。"
            else:
                persona += "\n\n【当前场景：私聊】你现在是在和对方1对1私聊，可以更耐心、更柔软、更走心，但不默认亲密关系，也不虚构自己的私密经历。根据对方说的内容自然回应，不要脱离对方话题自说自话。"
        else:
            persona += "\n\n【当前场景：群聊】你现在是在群里聊天：回复偏短、自然、会接话，可以轻俏皮，但不能高冷敷衍、讽刺对呛或过度撩某一个人。"

        # 节日人格
        persona += self._get_festival_persona()
        # 模式人格
        mode_text, is_full = self._get_mode_persona(mode, seed, stage_hint)
        if is_full:
            if mode in self._GREETING_PROMPT_MODES:
                return (
                    self._get_greeting_persona_anchor()
                    + "\n\n【本次问候要求】\n"
                    + mode_text
                    + "\n\n"
                    + self._build_dialogue_tone_contract("casual", is_priv=False)
                    + self._get_normal_chat_output_contract()
                )
            return mode_text + self._get_normal_chat_output_contract()
        persona += mode_text

        # [v5.18.3] 播报增强层:人物画像碎片 + 情绪状态机注入
        if mode in self._BROADCAST_MODES:
            enhancer = self._get_broadcast_enhancer(seed)
            if enhancer:
                persona += enhancer

        # [TRAE SOLO CN v5.24.0 阶段3-B] 混合记忆注入：将跨会话记忆摘要拼入 System Prompt
        # 让 AI 感知用户的历史特征，实现跨会话记忆 continuity
        if user_profile and isinstance(user_profile, dict):
            _mem = (user_profile.get("memory_summary") or "").strip()
            if _mem:
                persona += f"\n\n<past_interaction_summary>\nMory 对该用户的长期记忆摘要：\n{_mem}\n</past_interaction_summary>"

        # [阶段2-B] 人设跨模型适配：按模型家族强化差异化约束，防止不同模型人设抖动
        # 向后兼容：适配层异常不影响主流程，未知模型返回空字符串
        try:
            from core.persona_adapter import get_model_persona_prompt
            _adapter_prompt = get_model_persona_prompt(model_name or self.current_model, mode)
            if _adapter_prompt:
                persona += _adapter_prompt
        except Exception as _pa_err:
            logger.debug(f"人设适配层跳过（不影响主流程）：{_pa_err}")

        # [v5.33] 情绪光谱比例锁：基于最近 bot 回复统计，超阈值反向提示
        try:
            _emotion_hint = _get_emotion_ratio_hint()
            if _emotion_hint:
                persona += _emotion_hint
        except Exception as e:
            logger.debug(f"情绪比例锁注入跳过（非致命）：{e}")

        # [v5.33] 去AI结构性铁律：补强 4 条代码校验（长度/数字英文/排比/价格）
        try:
            _anti_ai_hint = _get_anti_ai_style_hint()
            if _anti_ai_hint:
                persona += _anti_ai_hint
        except Exception as e:
            logger.debug(f"去AI结构铁律注入跳过（非致命）：{e}")

        # 最后追加本轮六类语气合同与输出合同，压过旧配置、记忆摘要、
        # 情绪桶或模型适配中的冲突表述。
        tone_intent = self._classify_dialogue_tone_intent(
            message,
            mode=mode,
            stage_hint=stage_hint,
        )
        persona += "\n\n" + self._build_dialogue_tone_contract(
            tone_intent,
            is_priv=is_priv,
        )
        persona += self._get_normal_chat_output_contract()

        return persona

    @staticmethod
    def _mode_to_task_type(mode: str) -> str:
        """[阶段3-A] 将 ask() 的 mode 参数映射为 ModelRouter 的 task_type。

        ask() 的所有调用均为对话场景，统一路由到高端池（llm_premium）。
        - tarot / fortune 有直接对应的 task_type
        - 其他对话模式归为 chat（角色扮演对话 → 高端池）
        """
        if mode in ("tarot", "fortune"):
            return mode
        return "chat"

    @staticmethod
    def _normalize_history(conversation_history: list[dict] | None) -> tuple[list[dict], str]:
        """规范化对话历史并生成缓存键。

        仅接受 user/assistant 角色，限制最近 6 条，单条内容截断 500 字符。
        返回 (normalized_history, context_cache_key_suffix)；
        context_cache_key_suffix 为空串表示无历史。
        """
        normalized = []
        for item in list(conversation_history or [])[-6:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = str(item.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                normalized.append({"role": role, "content": content[:500]})
        if normalized:
            context_key = "\n".join(
                f"{item['role']}:{item['content']}" for item in normalized
            )
            return normalized, context_key
        return [], ""

    @staticmethod
    def _final_fallback_reply(mode: str, is_priv: bool = False, attempts: int = 0) -> str:
        """所有模型都失败时的统一兜底回复。

        用户侧不能暴露模型、接口、服务异常等系统细节，也不硬凑拟人化故障文案。
        普通/未知模式失败直接静默；明确转化场景给固定入口，避免下单链路断掉。

        [Bug-01 修复] 兜底文案统一走 get_fallback_text()，避免三处分散维护。
        """
        return get_fallback_text(mode, is_priv=is_priv)

    def ask(self, question: str, mode: str = "normal", retry: int = 3, seed: int = 0,
            tools: list = None, tool_choice: str = "auto", is_priv: bool = False,
            stage_hint: str = "", user_profile: dict = None,
            conversation_history: list[dict] | None = None) -> str | None:
        """
        调用AI，失败时自动重试并切换模型。
        返回字符串；失败会返回兜底文案，不会返回 None。

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
            conversation_history: 同一用户/聊天最近的 user/assistant 消息；会限制角色、条数和长度
        """

        # 仅接受 user/assistant 角色，并限制为最近 6 条，避免把遥测字段或超长内容注入模型。
        normalized_history, _history_ctx_key = self._normalize_history(conversation_history)
        cache_question = question
        if _history_ctx_key:
            cache_question = f"{_history_ctx_key}\ncurrent:{question}"

        # ── [v5.19.0] 人设引擎：设置情绪桶 context（供 _select_emotion_bucket 读取）──
        self._ctx_is_priv = is_priv
        self._ctx_message = question
        self._ctx_intimacy_score = self._calc_intimacy_score(user_profile)
        _, _, _, ctx_flirt_level = self._get_intimacy_level(self._ctx_intimacy_score)
        self._ctx_intimacy_level = ctx_flirt_level

        # ── 三层智能路由：根据mode选择对应层级模型池 ──
        use_tier_routing = bool(self._tier_pools)
        tier = self._get_tier_for_mode(mode) if use_tier_routing else "llm"
        route_tiers = self._retry_tiers_for(tier) if use_tier_routing else []
        attempted_by_tier = {}
        _upgrade_attempted = False
        active_model = self.current_model

        # ════ 优化层0：语义缓存命中 → 直接返回 ═══════════════════
        try:
            opt = _get_optimizer()
            if opt and opt.enabled:
                cached = opt.cache.get(cache_question, mode)
                if cached is not None:
                    cached_sanitized, cached_triggered = self._sanitize_reply_v2(cached)
                    # 历史缓存也必须经过当前输出门禁；拼音泄露只会触发检测、
                    # 不会改写文本，因此命中后应放弃缓存并走真实模型。
                    unsafe_unchanged = cached_triggered and cached_sanitized == cached
                    if cached_sanitized and not unsafe_unchanged:
                        logger.info(
                            f"📦 缓存命中并通过输出过滤: mode={mode}, "
                            f"len={len(cached_sanitized)}"
                        )
                        return cached_sanitized
                    logger.warning(f"⚠️ 缓存回复违反输出规范，已忽略: mode={mode}")
                # 熔断检查：当前模型是否被熔断了
                if not opt.circuit.is_available(active_model):
                    logger.warning(f"⚡ 模型{active_model}已被熔断，跳过")
                    self._next_available_model()
                    # 跳到下一个可用模型后继续正常流程（不再重复查熔断，避免级联跳）
        except Exception as opt_err:
            # 优化引擎异常不影响主流程
            logger.debug(f"优化层跳过（非致命）：{opt_err}")

        # 限制最大重试次数，同时按三层路由的实际候选模型数放宽上限。
        # 之前固定最多 5 次，轻量池两个模型超时后还没机会切到 glm/标准/旗舰池就误报“全部失败”。
        max_attempt_cap = int(self.config.get("AI_MAX_ATTEMPTS", 2) or 2)
        max_attempt_cap = max(1, min(8, max_attempt_cap))
        if use_tier_routing:
            candidate_count = max(1, self._retry_model_count_for(tier))
            max_attempts = min(max_attempt_cap, max(2, retry * min(candidate_count, max_attempt_cap)))
            max_iterations = max_attempts + candidate_count + len(self.model_pool) + 6
        else:
            candidate_count = max(1, len(self.model_pool))
            max_attempts = min(max_attempt_cap, max(1, retry * min(candidate_count, max_attempt_cap)))
            max_iterations = max_attempts + candidate_count + 4

        # 临时故障恢复后先回到到期最早模型，再做黑名单/到期检查。
        self._prefer_earliest_recovered_model()
        self._ensure_valid_model()

        def _advance_tier_if_exhausted(failed_tier: str, failed_model: str):
            """同一次 ask 内，当前层级每个可用模型都失败过一次后，立即切到下一层。"""
            nonlocal tier
            if not use_tier_routing or not failed_tier or not failed_model:
                return
            attempted = attempted_by_tier.setdefault(failed_tier, set())
            attempted.add(failed_model)
            tier_pool = self._tier_pools.get(failed_tier, [])
            candidate_names = [
                model.get("name")
                for model in tier_pool
                if model.get("name")
                and not self._is_blacklisted(model.get("name"))
                and not self._is_model_expired(model)
            ]
            if candidate_names and not set(candidate_names).issubset(attempted):
                return
            if failed_tier not in route_tiers:
                return
            for next_tier in route_tiers[route_tiers.index(failed_tier) + 1:]:
                next_model = self._get_tier_model(next_tier, require_circuit=True)
                if next_model:
                    logger.warning(f"⬆️ [{failed_tier}] 本轮候选均失败，升级到 {next_tier}: {next_model}")
                    tier = next_tier
                    return

        api_attempts = 0
        local_skip_streak = 0
        max_local_skips = max(6, candidate_count + len(self.model_pool) + 3)
        quota_permission_failures = []
        for _iteration in range(max_iterations):
            if api_attempts >= max_attempts:
                break
            # ── 三层路由：获取当前层级模型 ──
            if use_tier_routing:
                self._ensure_tier_model(tier)
                current_tier_model = self._get_tier_model(tier, require_circuit=True)
                if current_tier_model is None:
                    degraded = False
                    for fb_tier in self._retry_tiers_for(tier)[1:]:
                        self._ensure_tier_model(fb_tier)
                        fb_model = self._get_tier_model(fb_tier, require_circuit=True)
                        if fb_model is not None:
                            logger.warning(f"🔁 [{tier}] 无可用模型，切换到备用层级 {fb_tier}: {fb_model}")
                            tier = fb_tier
                            current_tier_model = fb_model
                            degraded = True
                            break
                    if not degraded:
                        logger.warning("🚫 所有层级模型均不可用，回退到原llm池继续尝试")
                        use_tier_routing = False
                if use_tier_routing and current_tier_model:
                    active_model = current_tier_model
                else:
                    active_model = self.current_model
            else:
                active_model = self.current_model

            if not self._is_model_suitable_for_mode(active_model, mode):
                logger.info(
                    f"⏩ 模型{active_model}是代码专用模型，不用于粉丝群问候，本轮跳过"
                )
                local_skip_streak += 1
                if use_tier_routing:
                    self._next_tier_model(tier)
                else:
                    self._next_available_model()
                if local_skip_streak >= max_local_skips:
                    logger.warning("⚠️ 没有适合粉丝群问候的通用对话模型，返回走心话术兜底")
                    break
                continue

            # 熔断检查必须针对本轮实际要调用的模型，而不是旧的全局current_model。
            try:
                opt = _get_optimizer()
                if opt and opt.enabled and not opt.circuit.is_available(active_model):
                    logger.warning(f"⚡ 模型{active_model}已被熔断，本轮跳过并切换")
                    local_skip_streak += 1
                    if use_tier_routing:
                        self._next_tier_model(tier)
                    else:
                        self._next_available_model()
                    if local_skip_streak >= max_local_skips:
                        logger.warning(f"⚠️ 连续跳过{local_skip_streak}个不可用模型，停止本轮空转并返回兜底")
                        break
                    continue
            except Exception as opt_err:
                logger.debug(f"熔断检查跳过（非致命）：{opt_err}")

            # ════ 优化层1：令牌桶限流 ════════════════════════════
            try:
                opt = _get_optimizer()
                if opt and opt.enabled and not opt.limiter.acquire(timeout=3.0):
                    # 限流超时，本次尝试跳过
                    logger.warning(f"⚠️ 令牌桶限流，第{api_attempts + 1}次尝试被跳过")
                    continue
            except Exception as e:
                logger.debug(f"令牌桶限流异常: {e}")  # 令牌桶异常不阻塞主流程

            # 【修复】active_model为空时跳过本次尝试（Bug 2）
            if not active_model:
                logger.warning(f"⚠️ active_model为空，跳过本次尝试(attempt={api_attempts + 1})")
                local_skip_streak += 1
                if local_skip_streak >= max_local_skips:
                    logger.warning(f"⚠️ 连续{local_skip_streak}次没有可用模型，停止本轮空转并返回兜底")
                    break
                time.sleep(2)
                continue

            # ── [阶段3-A] 多模型协同路由（可选开关，向后兼容）──
            # 开启时按 task_type 路由到不同 API URL + API Key + 模型名
            # 未开启时保持原有逻辑（用 self.base_url / self.api_key / active_model）
            req_url = self.base_url
            req_api_key = self.api_key
            req_model = active_model
            # [v5.26.0 阶段1-A] 成本熔断器：调用前检查是否需要降级
            _cost_tier = "llm_premium"  # 默认按高端池计价
            if self.config.get("MODEL_ROUTER_ENABLED", False):
                try:
                    from core.model_router import route_model
                    _task_type = self._mode_to_task_type(mode)
                    _r_url, _r_key_env, _r_model = route_model(_task_type, self.config)
                    if _r_url and _r_model:
                        req_url = _r_url
                        req_model = _r_model
                        # 从环境变量读取 API Key，缺省回退到默认 API_KEY
                        if _r_key_env:
                            _env_key = os.environ.get(_r_key_env, "").strip()
                            if _env_key:
                                req_api_key = _env_key
                except Exception as _r_err:
                    logger.warning(f"⚡ ModelRouter 路由失败，回退原逻辑：{_r_err}")

            # ── [阶段2-C] 多模型路由 A/B 测试分流（可选开关，向后兼容）──
            # 开启时用 get_ab_group(uid) 覆盖 route_model 的结果
            # Group A / B 仅使用当前配置显式指定的模型；空值不覆盖主池。
            # Group Base → 走默认路由（基线组，不覆盖）
            _ab_uid = user_profile.get("uid", 0) if isinstance(user_profile, dict) else 0
            _ab_group = ""
            _ab_model_used = req_model
            if self.config.get("AB_TEST_ENABLED", False):
                try:
                    from core.ab_test_router import get_ab_group, get_model_for_group
                    _ab_group = get_ab_group(_ab_uid)
                    _ab_override_model = get_model_for_group(_ab_group, self.config)
                    if _ab_override_model:
                        # A/B 组强制覆盖模型名（复用同一 DashScope API URL + Key）
                        req_model = _ab_override_model
                        _ab_model_used = _ab_override_model
                        logger.info(f"🧪 A/B 分流: uid={_ab_uid} group={_ab_group} model={_ab_override_model}")
                except Exception as _ab_err:
                    logger.debug(f"A/B 分流异常（不影响主流程）: {_ab_err}")

            # [v5.26.0 阶段1-A] 成本熔断检查：超阈值降级到 llm_light
            try:
                from core.llm_cost_guard import check_before_call
                _uid = _ab_uid  # 复用已提取的 uid
                _allowed, _final_tier, _reason = check_before_call(_uid, _cost_tier)
                if not _allowed:
                    # 24h 超限直接拒绝，返回降级文案
                    logger.warning(f"💰 LLM 成本熔断拒绝调用: uid={_uid} reason={_reason}")
                    return self._final_fallback_reply(mode=mode, is_priv=is_priv)
                if _final_tier != _cost_tier:
                    # 降级：切换到 light 模型（复用百炼 API，仅切模型名）
                    _light_model = self.config.get("MODEL_POOL_LIGHT") or active_model
                    if _light_model:
                        req_model = _light_model
                        _cost_tier = "llm_light"
                        logger.info(f"💰 LLM 成本降级: uid={_uid} tier={_cost_tier} reason={_reason}")
            except Exception as _cg_err:
                logger.debug(f"成本熔断检查异常（不影响主流程）: {_cg_err}")

            # ModelRouter、A/B 或成本降级都可能在初选后再次覆盖模型；
            # 请求边界复核一次，保证问候最终仍由通用对话模型生成。
            if not self._is_model_suitable_for_mode(req_model, mode):
                logger.warning(
                    f"⏩ 二级路由为问候选择了代码专用模型{req_model}，"
                    f"已恢复通用对话模型{active_model}"
                )
                req_model = active_model

            headers = {
                "Authorization": f"Bearer {req_api_key}",
                "Content-Type": "application/json"
            }
            # ── [v5.19.0] 动态 LLM 参数：按 is_priv × 亲密度 × 时段查表 ──
            dyn_temp, dyn_top_p, dyn_freq_pen, dyn_pres_pen = self._get_dynamic_llm_params(
                is_priv, ctx_flirt_level, datetime.now(_CST).hour)
            # [阶段3-A] 检测记忆系统注入：_build_persona 会将 memory_summary 注入 <past_interaction_summary>
            # 若 user_profile 含非空 memory_summary，则本次会话标记为记忆辅助，供后续 funnel_state.transition 归因
            _mem_summary = ""
            if user_profile and isinstance(user_profile, dict):
                _mem_summary = (user_profile.get("memory_summary") or "").strip()
            self._last_memory_assisted = bool(_mem_summary or normalized_history)
            request_messages = [
                {"role": "system", "content": self._build_persona(mode, seed, is_priv=is_priv, stage_hint=stage_hint, user_profile=user_profile, message=question, model_name=active_model)},
                *normalized_history,
                {"role": "user", "content": question},
            ]
            payload = {
                "model": req_model,
                "messages": request_messages,
                "temperature": dyn_temp,
                "top_p": dyn_top_p,
                "max_tokens": self.config.get("MAX_TOKENS", 400),
                "frequency_penalty": dyn_freq_pen,
                "presence_penalty": dyn_pres_pen
            }
            if mode in self._GREETING_PROMPT_MODES:
                payload["max_tokens"] = min(int(payload["max_tokens"] or 400), 160)
            # [v5.38.24] 穿帮自愈重试参数：上一轮触发降温度重试时，本轮应用降温度+约束注入
            # （payload 每轮重建，必须在构建后应用，否则 continue 后修改会被覆盖丢失）
            if getattr(self, '_sanitize_retry_done', False):
                payload['temperature'] = max(0.3, payload.get('temperature', 0.8) * 0.5)
                payload['messages'] = payload.get('messages', []) + [{
                    "role": "system",
                    "content": (
                        "(Constraint Warning) 上一条回复违反输出规范。"
                        "保持Mory既有人设，但只输出正常聊天正文；"
                        "绝不泄露AI身份，也不写括号/星号动作、心理旁白或虚构画面。"
                    )
                }]
            request_options = self._get_model_request_options(req_model)
            if isinstance(request_options.get("enable_thinking"), bool):
                payload["enable_thinking"] = request_options["enable_thinking"]

            # ── Function Calling 支持 ──
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = tool_choice

            try:
                local_skip_streak = 0
                api_attempts += 1
                attempt_no = api_attempts
                _req_start = time.time()
                request_timeout = float(self.config.get("AI_REQUEST_TIMEOUT", 30) or 30)
                request_timeout = max(5.0, min(45.0, request_timeout))
                resp = requests.post(req_url, json=payload,
                                     headers=headers, timeout=request_timeout)
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
                            except Exception as e:
                                logger.debug(f"操作异常: {e}")
                            return message

                        result_text = message.get("content")
                        if not result_text or not str(result_text).strip():
                            logger.warning(f"⚠️ 模型{active_model}返回空content，切换模型重试")
                            try:
                                opt = _get_optimizer()
                                if opt:
                                    opt.circuit.record_failure(active_model)
                            except Exception as e:
                                logger.debug(f"操作异常: {e}")
                            if use_tier_routing:
                                self._next_tier_model(tier)
                                _advance_tier_if_exhausted(tier, active_model)
                            else:
                                self._next_available_model()
                            continue

                        _req_elapsed = time.time() - _req_start
                        self._record_response_time(active_model, _req_elapsed)

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

                        # 【TRAE SOLO CN v5.18.3审计修复】AI 输出后置过滤，防止穿帮字眼泄露 AI 属性
                        # [v5.23.0 P0-2] 增强版：拼音检测 + 自愈重试（降温度 + 注入约束警告）
                        sanitized, triggered = self._sanitize_reply_v2(result_text)
                        if triggered and not getattr(self, '_sanitize_retry_done', False):
                            # 首次触发穿帮：置位自愈标记，下一轮请求在 payload 构建后应用降温度+约束注入
                            self._sanitize_retry_done = True
                            logger.warning(f"⚠️ AI 输出触发身份/舞台化过滤，降温度重试: 原文={result_text[:50]}")
                            continue
                        # 已重试过或未触发：返回过滤后结果
                        if getattr(self, '_sanitize_retry_done', False):
                            delattr(self, '_sanitize_retry_done')
                        # ════ 优化层：只缓存通过输出门禁的正文 + 熔断成功 ════════
                        if sanitized:
                            try:
                                opt = _get_optimizer()
                                if opt:
                                    opt.cache.put(cache_question, mode, sanitized)
                                    opt.circuit.record_success(active_model)
                            except Exception as e:
                                logger.debug(f"操作异常: {e}")
                        # [v5.26.0 阶段1-A] 记录 LLM 成本（用于熔断器累计）
                        try:
                            from core.llm_cost_guard import record_cost
                            _usage = data.get("usage", {})
                            _in_tok = _usage.get("prompt_tokens", 0)
                            _out_tok = _usage.get("completion_tokens", 0)
                            record_cost(_uid, req_model, self._mode_to_task_type(mode),
                                        _in_tok, _out_tok, _cost_tier)
                        except Exception as e:
                            logger.debug(f"LLM成本记录跳过（非致命）：{e}")
                        # [阶段2-C] 记录 A/B 测试指标（仅 AB_TEST_ENABLED 时）
                        # converted 此处置 False，实际转化由 conversion_events 关联统计
                        if _ab_group:
                            try:
                                from core.ab_test_router import record_ab_metric
                                record_ab_metric(
                                    uid=_ab_uid,
                                    group=_ab_group,
                                    model=_ab_model_used,
                                    latency_ms=round(_req_elapsed * 1000, 2),
                                    cost=0.0,
                                    converted=False,
                                )
                            except Exception as e:
                                logger.debug(f"A/B测试指标记录跳过（非致命）：{e}")
                        # [v5.33] 情绪光谱比例锁：记录 bot 回复到全局缓冲
                        try:
                            _record_bot_reply_for_emotion(sanitized)
                        except Exception as e:
                            logger.debug(f"bot回复情绪记录跳过（非致命）：{e}")
                        return sanitized
                    logger.warning(f"⚠️ 模型{active_model}返回空choices，切换模型重试")
                    try:
                        opt = _get_optimizer()
                        if opt:
                            opt.circuit.record_failure(active_model)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
                    self._recovery_pending = True
                    if use_tier_routing:
                        self._next_tier_model(tier)
                        _advance_tier_if_exhausted(tier, active_model)
                    else:
                        self._next_available_model()
                elif self._is_quota_exhausted_response(resp):
                    model_name = active_model
                    logger.warning(f"⚠️ 模型{model_name}明确额度耗尽({resp.status_code})，永久拉黑")
                    quota_permission_failures.append(f"{model_name}:HTTP{resp.status_code}")
                    self._blacklist_model(model_name, f"额度耗尽 HTTP {resp.status_code}")
                    try:
                        opt = _get_optimizer()
                        if opt:
                            opt.circuit.record_failure(model_name)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
                    if use_tier_routing:
                        self._next_tier_model(tier)
                    else:
                        self._next_available_model()
                    if not self.model_pool:
                        # 池耗尽早退前同样清理输出门禁重试标记，避免残留到下一次调用
                        if getattr(self, '_sanitize_retry_done', False):
                            delattr(self, '_sanitize_retry_done')
                        return self._final_fallback_reply(mode=mode, is_priv=is_priv, attempts=attempt_no)
                else:
                    try:
                        opt = _get_optimizer()
                        if opt:
                            opt.circuit.record_failure(active_model)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
                    self._recovery_pending = True
                    if resp.status_code in (402, 403, 429):
                        logger.warning(
                            f"⚠️ HTTP {resp.status_code} 未确认额度耗尽，按临时故障切换({attempt_no})"
                        )
                    else:
                        logger.warning(f"⚠️ HTTP {resp.status_code}，按临时故障切换({attempt_no})")
                    if use_tier_routing:
                        self._next_tier_model(tier)
                        _advance_tier_if_exhausted(tier, active_model)
                    else:
                        self._next_available_model()
            except requests.exceptions.Timeout:
                logger.warning(f"⚠️ 超时，重试({api_attempts})")
                try:
                    opt = _get_optimizer()
                    if opt:
                        opt.circuit.record_failure(active_model)
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
                self._recovery_pending = True
                if use_tier_routing:
                    self._next_tier_model(tier)
                    _advance_tier_if_exhausted(tier, active_model)
                else:
                    self._next_available_model()
            except Exception as e:
                logger.error(f"❌ 请求异常：{type(e).__name__}")
                try:
                    opt = _get_optimizer()
                    if opt:
                        opt.circuit.record_failure(active_model)
                except Exception as opt_err:
                    logger.debug(f"操作异常: {opt_err}")
                self._recovery_pending = True
                if use_tier_routing:
                    self._next_tier_model(tier)
                    _advance_tier_if_exhausted(tier, active_model)
                else:
                    self._next_available_model()

            # 指数退避，最多等8秒
            wait = min(2 ** ((max(api_attempts, 1) - 1) % 3), 8)
            time.sleep(wait)

        attempts_done = max(api_attempts, 1)
        logger.warning("⚠️ AI引擎：本轮模型调用均未成功，已返回降级兜底")
        # 全败兜底前清理输出门禁重试标记，避免残留到下一次调用跳过自愈重试
        if getattr(self, '_sanitize_retry_done', False):
            delattr(self, '_sanitize_retry_done')
        if quota_permission_failures:
            try:
                from modules.auto_tasks import report_fault
                report_fault(
                    "AI模型额度或权限异常",
                    "检测到模型返回 402/403，已切到降级兜底回复",
                    "🚨",
                    f"尝试模型数: {attempts_done}; {', '.join(quota_permission_failures[:5])}"
                )
            except Exception as e:
                logger.debug(f"操作异常: {e}")
        return self._final_fallback_reply(mode=mode, is_priv=is_priv, attempts=attempts_done)


def calc_typing_delay(text: str) -> float:
    """
    根据文本计算打字延迟（2-12秒）
    中文字符 0.5s/字，英文单词 0.3s/词
    """
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len([w for w in text.split() if any(c.isalpha() for c in w)])
    return max(2.0, min(12.0, cn * 0.5 + en * 0.3))


def get_fallback_text(reason: str = "default", is_priv: bool = False) -> str:
    """AI 失败统一兜底文案入口

    [Bug-01 修复] 之前三处兜底文案分散（ai_engine._final_fallback_reply /
    ai_reply_handler._final_ai_reply_fallback / ai_handlers._final_ai_reply_fallback），
    修改一处其他会复发，且文案不一致。现在统一从此函数获取，确保一致性。

    Args:
        reason: 触发原因，对应 mode（convert/contact_mory/default）
        is_priv: 是否私聊场景（影响入口文案措辞）

    Returns:
        统一兜底文案；普通/未知模式返回空串（静默，不暴露系统异常）
    """
    if reason == "convert":
        # 具体入口由调用方依据本轮 none/preview/subscribe 单目标补齐；
        # 此处不能再次把预览与下单混在一起。
        return (
            "这条我不乱说，你按当前问题继续看对应入口。"
            if is_priv
            else "这条我不乱说，按当前问题看对应入口就行。"
        )
    if reason == "contact_mory":
        return (
            "这个需要 Mory 看一下：https://t.me/Moryfansbot"
            if is_priv
            else "这个需要 Mory 看一下，联系 @Moryfansbot。"
        )
    # 普通模式失败：静默，不暴露系统异常，也不硬凑拟人化故障文案
    return ""


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

    # 获取vision池的模型
    pools = config.get("MODEL_POOLS", {})
    vision_pool = list(pools.get("vision", []))

    # 如果没有vision池，尝试用llm池（仅选择明确支持多模态的模型）
    if not vision_pool:
        llm_pool = pools.get("llm", [])
        vl_keywords = ["vl", "vision", "omni", "qwen-vl", "qwen2-vl", "glm-4v", "glm-4v-plus", "deepseek-vl"]
        for m in llm_pool:
            name = m.get("name", "").lower()
            if any(kw in name for kw in vl_keywords):
                vision_pool.append(m)
                break

    if not vision_pool:
        logger.warning("⚠️ 没有可用的视觉模型，跳过图片分析")
        return None

    # 【修复v4.3.2】遍历vision_pool，跳过过期模型，失败自动尝试下一个
    # 【TRAE SOLO CN】
    api_key = config.get("API_KEY") or config.get("DASHSCOPE_KEY", "")

    if not api_key or api_key in ("", "YOUR_DASHSCOPE_API_KEY_HERE", "YOUR_DASHSCOPE_API_KEY"):
        logger.warning("⚠️ API_KEY未配置，跳过图片分析")
        return None

    img_base64 = base64.b64encode(image_bytes).decode("utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}},
                {"type": "text", "text": prompt}
            ]
        }
    ]

    raw_base = config.get("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    base_url = raw_base.replace("/chat/completions", "").rstrip("/")

    for model_info in vision_pool:
        model_name = model_info.get("name", "")
        expire = model_info.get("expire", "")
        if expire:
            try:
                from datetime import datetime as _dt
                expire_date = _dt.strptime(expire, "%Y-%m-%d").date()
                if expire_date < _dt.now().date():
                    logger.info(f"⏭️ 跳过过期视觉模型: {model_name} (过期: {expire})")
                    continue
            except (ValueError, TypeError):
                pass

        payload = {
            "model": model_name,
            "messages": messages,
            "max_tokens": 300
        }

        try:
            from core.http_client import get_http_client, HTTPRequestError
            client = get_http_client()
            data = client.post(
                f"{base_url}/chat/completions",
                json_data=payload,
                headers=headers,
                timeout=30
            )
            if isinstance(data, dict) and data.get("choices"):
                content = data["choices"][0].get("message", {}).get("content", "")
                logger.info(f"✅ 图片分析成功: {model_name}")
                return content
            logger.warning(f"⚠️ 图片分析API返回异常({model_name}): {str(data)[:200]}")
        except HTTPRequestError as e:
            logger.warning(f"⚠️ 图片分析API失败({model_name}): {e}，尝试下一个模型")
            continue
        except Exception as e:
            logger.warning(f"⚠️ 图片分析异常({model_name}): {type(e).__name__}，尝试下一个模型")
            continue

    logger.warning("⚠️ 所有视觉模型均失败，跳过图片分析")
    return None


def text_to_speech(text: str, config: dict = None) -> bytes | None:
    """
    TTS文字转语音 - 用 voice_tts 池的模型把文字转成音频
    :param text: 要转换的文字
    :param config: 配置字典（可选）
    :return: 音频数据(bytes) 或 None
    """
    if config is None:
        from core.bot_initializer import load_config
        config = load_config()

    # 获取 voice_tts 池的模型
    pools = config.get("MODEL_POOLS", {})
    tts_models = pools.get("voice_tts", [])

    if not tts_models:
        logger.warning("⚠️ 未配置 voice_tts 或 llm_standard 模型池")
        return None

    # 【修复v4.3.2】遍历tts模型池，跳过过期模型，失败自动尝试下一个
    # 【TRAE SOLO CN】
    raw_base = config.get("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    base_url = raw_base.replace("/chat/completions", "").rstrip("/")

    for model_info in tts_models:
        model_name = model_info.get("name", "") or model_info.get("model", "")
        api_key = config.get("API_KEY", "") or model_info.get("key", "")

        expire = model_info.get("expire", "")
        if expire:
            try:
                from datetime import datetime as _dt
                expire_date = _dt.strptime(expire, "%Y-%m-%d").date()
                if expire_date < _dt.now().date():
                    logger.info(f"⏭️ 跳过过期TTS模型: {model_name} (过期: {expire})")
                    continue
            except (ValueError, TypeError):
                pass

        if not model_name or not api_key:
            logger.warning(f"⚠️ TTS 模型配置不完整: {model_name}")
            continue

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model_name,
            "input": text,
            "voice": "Cherry",
        }

        try:
            resp = requests.post(
                f"{base_url}/audio/speech",
                headers=headers,
                json=payload,
                timeout=30
            )

            if resp.status_code == 200:
                logger.info(f"✅ TTS 生成成功({model_name}): {len(text)}字 -> {len(resp.content)}字节音频")
                return resp.content

            logger.warning(f"⚠️ TTS API 失败({model_name}): {resp.status_code}，尝试格式2")

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
                logger.info(f"✅ TTS 生成成功(格式2,{model_name}): {len(text)}字 -> {len(resp2.content)}字节音频")
                return resp2.content

            logger.warning(f"⚠️ TTS API 失败(格式2,{model_name}): {resp2.status_code}，尝试下一个模型")
        except Exception as e:
            logger.warning(f"⚠️ TTS 异常({model_name}): {type(e).__name__}，尝试下一个模型")
            continue

    logger.warning("⚠️ 所有TTS模型均失败，跳过语音生成")
    return None
