# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/memory_summarizer.py  ·  混合记忆摘要引擎（v5.23.0 P3-7）          ║
║                                                                            ║
║  功能：                                                                    ║
║    当用户与 Bot 互动超过 1 小时未活跃后，后台线程异步调用廉价 LLM，        ║
║    总结这段对话中用户表现出的新特征，存入 user_profiles.memory_summary。    ║
║    下次对话时将该摘要拼入 Prompt，实现低成本跨会话记忆。                    ║
║                                                                            ║
║  设计原则：                                                                ║
║    - 异步执行，不阻塞主对话流程                                            ║
║    - 廉价模型优先（Qwen-Flash / GPT-4o-mini）                              ║
║    - 摘要限 200 字，防止 Prompt 膨胀                                       ║
║    - 失败静默，不影响主流程                                                ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import re
import time
import threading
from collections import deque
from datetime import datetime, timezone, timedelta

from core.logging_util import get_logger

logger = get_logger("memory_summarizer")

_CST = timezone(timedelta(hours=8))

# 摘要冷却时间（秒）：同一用户 1 小时内只摘要一次
_SUMMARY_COOLDOWN = 3600

# [v5.24.0 阶段3-A] 双重触发参数
_IDLE_THRESHOLD = 1800      # 静默期 30 分钟 → 判定会话结束，触发摘要
_ROUND_THRESHOLD = 15       # 单次连续交互超过 15 轮 → 强制触发摘要
_MAX_BUFFER_PER_USER = 30   # 每用户内存消息缓冲上限（最近 30 条）

# 最近摘要记录（uid → last_summary_ts）
_recent_summaries = {}
_recent_lock = threading.Lock()

# [v5.24.0 阶段3-A] 每用户消息缓冲 + 会话追踪
# _user_msg_buffer: uid → deque([{role, content, ts}])
# _user_last_ts:    uid → 上次消息时间戳
# _user_rounds:     uid → 当前会话轮数（user+assistant 各算一轮的一半，这里按 user 消息计数）
_user_msg_buffer = {}
_user_last_ts = {}
_user_rounds = {}
_session_lock = threading.Lock()

# [v5.24.0 阶段3-C] 摘要质量校验统计（线程安全）
_validation_stats = {
    "total_validated": 0,
    "passed": 0,
    "failed": 0,
    "last_fail_reason": "",
}
_validation_stats_lock = threading.Lock()

# [v5.24.0 阶段3-C] 幻觉黑名单正则（编译一次复用）
# 包含：AI 自我认知词 / LLM 拒绝词 / System Prompt 泄露词
_HALLUCINATION_PATTERNS = [
    re.compile(r"作为AI"),
    re.compile(r"我是一个AI"),
    re.compile(r"Mory是一个机器人"),
    re.compile(r"人工智能助手"),
    re.compile(r"无法"),
    re.compile(r"不能"),
    re.compile(r"抱歉"),
    re.compile(r"你是Mory"),
    re.compile(r"人设"),
    re.compile(r"prompt", re.IGNORECASE),
    re.compile(r"指令"),
]

# 纯 JSON 检测正则：以 { 或 [ 开头并以对应符号结尾
_JSON_PATTERN = re.compile(r'^\s*[\{\[].*[\}\]]\s*$', re.DOTALL)

# 连续重复字符检测：同一字符连续出现 >3 次（即 4 次及以上）
_REPEAT_PATTERN = re.compile(r'(.)\1{3,}')


def should_summarize(uid: int) -> bool:
    """检查用户是否需要摘要（冷却时间外）"""
    with _recent_lock:
        last_ts = _recent_summaries.get(uid, 0)
        return time.time() - last_ts > _SUMMARY_COOLDOWN


def mark_summarized(uid: int):
    """标记用户已摘要"""
    with _recent_lock:
        _recent_summaries[uid] = time.time()
        # 清理超过 2 小时的记录
        cutoff = time.time() - 7200
        expired = [k for k, v in _recent_summaries.items() if v < cutoff]
        for k in expired:
            del _recent_summaries[k]


def record_message(uid: int, role: str, content: str):
    """[v5.24.0 阶段3-A] 记录单条消息到用户缓冲，更新会话追踪状态

    Args:
        uid: 用户 ID
        role: "user" 或 "assistant"
        content: 消息文本（将截断到 200 字）
    """
    if not uid or not content:
        return
    try:
        content = str(content)[:200]
        now = time.time()
        with _session_lock:
            # 初始化缓冲
            if uid not in _user_msg_buffer:
                _user_msg_buffer[uid] = deque(maxlen=_MAX_BUFFER_PER_USER)
                _user_rounds[uid] = 0
                _user_last_ts[uid] = 0

            # 静默期检测：若距上次消息 >30min，视为新会话开始，重置轮数
            gap = now - _user_last_ts.get(uid, 0)
            if _user_last_ts[uid] > 0 and gap > _IDLE_THRESHOLD:
                _user_rounds[uid] = 0
                logger.debug(f"[MEMORY_TRIGGER] uid={uid} 静默 {int(gap)}s，重置会话轮数")

            # 记录消息
            _user_msg_buffer[uid].append({
                "role": role,
                "content": content,
                "ts": int(now),
            })
            _user_last_ts[uid] = now
            if role == "user":
                _user_rounds[uid] = _user_rounds.get(uid, 0) + 1
    except Exception as e:
        logger.debug(f"记录消息失败 uid={uid}: {e}")


def check_and_trigger(uid: int, db=None) -> bool:
    """[v5.24.0 阶段3-A] 检查双重触发条件，命中则异步摘要

    触发条件（满足任一即触发）：
      A. 静默期：用户 30 分钟无新消息（由定时任务或下次消息到达时检测）
      B. 轮数阈值：单次会话 user 消息数 ≥15

    本函数在每条 user 消息记录后调用，检测条件 B；
    条件 A 由 record_message 内部重置轮数时隐式处理（上一会话已被摘要或丢弃）。

    Returns:
        True 表示已投递异步摘要任务
    """
    try:
        with _session_lock:
            rounds = _user_rounds.get(uid, 0)
            buffer = list(_user_msg_buffer.get(uid, []))

        # 条件 B：轮数阈值
        if rounds < _ROUND_THRESHOLD:
            return False
        if not should_summarize(uid):
            return False
        if len(buffer) < 3:
            return False

        # 命中阈值触发，投递异步摘要
        logger.info(f"[MEMORY_TRIGGER] uid={uid} 轮数={rounds}≥{_ROUND_THRESHOLD}，触发异步摘要")
        summarize_user_memory_async(uid, buffer, db)
        # 触发后重置轮数，避免同一会话重复触发
        with _session_lock:
            _user_rounds[uid] = 0
        return True
    except Exception as e:
        logger.debug(f"触发检查失败 uid={uid}: {e}")
        return False


def trigger_idle_summary(uid: int, db=None) -> bool:
    """[v5.24.0 阶段3-A] 静默期触发：由定时任务调用，检测用户是否已静默 >30min

    若用户已静默且缓冲区有 ≥3 条消息且冷却期外，触发摘要。

    Returns:
        True 表示已投递异步摘要任务
    """
    try:
        now = time.time()
        with _session_lock:
            last_ts = _user_last_ts.get(uid, 0)
            if last_ts == 0:
                return False
            gap = now - last_ts
            if gap < _IDLE_THRESHOLD:
                return False
            buffer = list(_user_msg_buffer.get(uid, []))
            rounds = _user_rounds.get(uid, 0)

        if len(buffer) < 3 or rounds < 2:
            return False
        if not should_summarize(uid):
            return False

        logger.info(f"[MEMORY_TRIGGER] uid={uid} 静默 {int(gap)}s≥{_IDLE_THRESHOLD}s，触发异步摘要")
        summarize_user_memory_async(uid, buffer, db)
        # 清空缓冲，避免下次重复摘要
        with _session_lock:
            _user_msg_buffer[uid].clear()
            _user_rounds[uid] = 0
        return True
    except Exception as e:
        logger.debug(f"静默触发失败 uid={uid}: {e}")
        return False


def scan_idle_users(db=None, max_check: int = 50) -> int:
    """[v5.24.0 阶段3-A] 扫描所有缓冲中的用户，触发已静默 >30min 的摘要

    由定时任务每 5 分钟调用一次。

    Returns:
        触发的摘要任务数
    """
    triggered = 0
    try:
        with _session_lock:
            uids = list(_user_last_ts.keys())
        for uid in uids[:max_check]:
            if trigger_idle_summary(uid, db):
                triggered += 1
    except Exception as e:
        logger.debug(f"静默扫描异常: {e}")
    return triggered


def validate_summary(summary: str) -> tuple:
    """[v5.24.0 阶段3-C] 校验记忆摘要质量，防止幻觉/格式错误污染 Prompt

    校验规则（任一不通过即拒绝）：
        A. 长度校验：10-300 字之间（太短无信息量，太长污染 Prompt）
        B. 幻觉黑名单扫描：命中拒绝词则拒绝
           - AI 自我认知词："作为AI" / "我是一个AI" / "Mory是一个机器人" / "人工智能助手"
           - LLM 拒绝词："无法" / "不能" / "抱歉"
           - System Prompt 泄露词："你是Mory" / "人设" / "prompt" / "指令"
        C. 格式校验：不允许纯 JSON（摘要应为自然语言）
        D. 重复度校验：不允许连续重复 >3 次的字符（如 "啊啊啊啊啊啊"）

    Args:
        summary: 待校验的摘要文本

    Returns:
        (is_valid, reason): 校验通过返回 (True, "")，失败返回 (False, 原因说明)
    """
    if not summary or not isinstance(summary, str):
        return (False, "摘要为空或非字符串")

    # A. 长度校验
    length = len(summary)
    if length < 10:
        return (False, f"摘要过短（{length} 字 < 10）")
    if length > 300:
        return (False, f"摘要过长（{length} 字 > 300）")

    # B. 幻觉黑名单扫描
    for pattern in _HALLUCINATION_PATTERNS:
        if pattern.search(summary):
            return (False, f"命中幻觉黑名单关键词: {pattern.pattern}")

    # C. 格式校验：不允许纯 JSON
    if _JSON_PATTERN.match(summary):
        # 进一步尝试 json 解析确认，避免误伤自然语言
        try:
            import json
            json.loads(summary)
            return (False, "摘要为纯 JSON 格式，应为自然语言")
        except Exception:
            pass  # 不是合法 JSON，放行

    # D. 重复度校验：连续重复 >3 次的字符
    if _REPEAT_PATTERN.search(summary):
        return (False, "摘要含连续重复 >3 次的字符")

    return (True, "")


def get_validation_stats() -> dict:
    """[v5.24.0 阶段3-C] 获取摘要质量校验统计，用于监控摘要质量

    Returns:
        {total_validated, passed, failed, last_fail_reason}
    """
    with _validation_stats_lock:
        return dict(_validation_stats)


def _record_validation_result(is_valid: bool, reason: str):
    """[v5.24.0 阶段3-C] 记录单次校验结果到统计（内部辅助函数）"""
    with _validation_stats_lock:
        _validation_stats["total_validated"] += 1
        if is_valid:
            _validation_stats["passed"] += 1
        else:
            _validation_stats["failed"] += 1
            _validation_stats["last_fail_reason"] = reason


def summarize_user_memory_async(uid: int, recent_messages: list, db=None):
    """异步生成用户记忆摘要

    Args:
        uid: 用户 ID
        recent_messages: 最近对话消息列表 [{"role": "user"/"assistant", "content": "..."}]
        db: DB 实例（用于读写 user_profiles 表）
    """
    if not should_summarize(uid):
        return

    if not recent_messages or len(recent_messages) < 3:
        return  # 消息太少不值得摘要

    # 启动后台线程
    t = threading.Thread(
        target=_summarize_worker,
        args=(uid, recent_messages, db),
        name=f"MemorySummarizer-{uid}",
        daemon=True,
    )
    t.start()


def _summarize_worker(uid: int, messages: list, db):
    """摘要工作线程"""
    try:
        mark_summarized(uid)

        # 构建摘要 prompt
        conversation_text = "\n".join([
            f"{'用户' if m.get('role') == 'user' else 'Mory'}: {m.get('content', '')[:100]}"
            for m in messages[-20:]  # 最多取最近 20 条
        ])

        prompt = f"""请总结以下对话中用户表现出的特征，限 200 字内。重点提取：
1. 兴趣偏好（如喜欢塔罗/树洞/购物/照片等）
2. 消费倾向（如对价格敏感/高消费意愿/抗拒付费等）
3. 沟通风格（如话多/话少/直接/含蓄/夜间活跃等）
4. 特殊记忆点（如提到过的重要信息）

对话内容：
{conversation_text}

请直接输出总结，不要加前缀，限 200 字："""

        # 调用廉价 LLM
        summary = _call_cheap_llm(prompt)
        if not summary or len(summary) < 10:
            logger.debug(f"用户 {uid} 记忆摘要为空，跳过")
            return

        # 限制 200 字
        summary = summary[:200]

        # [v5.24.0 阶段3-C] 质量校验：写入 DB 前校验摘要，防止幻觉/格式错误污染 Prompt
        is_valid, reason = validate_summary(summary)
        _record_validation_result(is_valid, reason)
        if not is_valid:
            # 校验失败：记录警告日志（含失败原因 + 摘要片段），不写入 DB，保留旧摘要
            logger.warning(
                f"[MEMORY_VALIDATE_FAIL] uid={uid} 摘要校验失败: {reason} | 片段: {summary[:80]!r}"
            )
            return

        # 存入 user_profiles.memory_summary
        if db:
            _save_memory_summary(db, uid, summary)
            logger.info(f"✅ 用户 {uid} 记忆摘要已更新: {summary[:50]}...")

    except Exception as e:
        logger.debug(f"用户 {uid} 记忆摘要生成失败: {e}")


def _call_cheap_llm(prompt: str) -> str:
    """调用廉价 LLM 生成摘要"""
    try:
        from core.ai_engine import AIEngine
        ai = AIEngine.get_instance() if hasattr(AIEngine, 'get_instance') else None
        if not ai:
            # 回退：直接用 ask
            from core.bot_initializer import get_global_context
            ctx = get_global_context()
            ai = ctx.ai if ctx else None
        if not ai:
            return ""

        # 用 light 模型（最廉价）
        result = ai.ask(prompt, mode="normal")
        return result or ""
    except Exception as e:
        logger.debug(f"LLM 调用失败: {e}")
        return ""


def _save_memory_summary(db, uid: int, summary: str):
    """保存记忆摘要到 user_profiles 表"""
    try:
        with db.lock:
            c = db.conn.cursor()
            # 幂等添加 memory_summary 列
            try:
                c.execute("ALTER TABLE user_profiles ADD COLUMN memory_summary TEXT DEFAULT ''")
            except Exception:
                pass  # 幂等添加列：列已存在则跳过  # 列已存在

            # 更新 memory_summary
            c.execute(
                "UPDATE user_profiles SET memory_summary=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                (summary, uid)
            )
            if c.rowcount == 0:
                # 用户画像不存在，创建
                c.execute(
                    "INSERT OR IGNORE INTO user_profiles (user_id, memory_summary, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                    (uid, summary)
                )
            db.conn.commit()
    except Exception as e:
        # 【v5.31.2 修复】用户记忆丢失应告警，否则用户画像逐渐失真无人知晓
        logger.warning(f"保存记忆摘要失败 uid={uid}: {e}")


def get_memory_summary(db, uid: int) -> str:
    """获取用户记忆摘要（用于拼入 Prompt）"""
    try:
        with db.lock:
            c = db.conn.cursor()
            # 确保列存在
            try:
                c.execute("ALTER TABLE user_profiles ADD COLUMN memory_summary TEXT DEFAULT ''")
            except Exception:
                pass  # 幂等添加列：列已存在则跳过
            c.execute("SELECT memory_summary FROM user_profiles WHERE user_id=?", (uid,))
            row = c.fetchone()
            return row[0] if row and row[0] else ""
    except Exception:
        return ""


# ════════════════════════════════════════════════════════════════════════
#  [v5.24.0 阶段3-B] 新用户冷启动：种子画像摘要（零 LLM 调用）
# ════════════════════════════════════════════════════════════════════════

def seed_initial_memory(uid: int, first_message: str, db=None) -> bool:
    """[v5.24.0 阶段3-B] 新用户首条消息冷启动：生成种子画像摘要

    零成本冷启动（不调用 LLM，纯规则分析），让 AI 在首轮对话就有差异化互动方向。
    幂等：已有 memory_summary 则跳过；失败静默降级。

    Args:
        uid: 用户 ID
        first_message: 用户首条消息文本
        db: DB 实例（需有 get_user_profile / upsert_user_profile 方法）

    Returns:
        True 表示已写入种子摘要，False 表示跳过（已有摘要或失败）
    """
    if not uid or not first_message or not db:
        return False
    try:
        # 幂等检查：已有 memory_summary 则跳过
        existing_profile = db.get_user_persona_profile(uid)
        if existing_profile and (existing_profile.get("memory_summary") or "").strip():
            return False

        # 基于首条消息生成种子画像摘要（纯规则分析，零 LLM 调用）
        seed_summary = _generate_seed_summary(first_message)
        if not seed_summary:
            return False

        # 写入 memory_summary（保留其他画像字段不变）
        # 若无现有画像，构造最小默认画像
        profile = existing_profile or {
            "user_id": uid,
            "tags": [],
            "level": 0,
            "interests": [],
            "conversation_rounds": 0,
            "activity_score": 0.0,
            "flirt_affinity": 0.0,
            "spend_tendency": 0.0,
            "resistance_idx": 0.5,
            "peak_hours": [],
            "persona_tags": [],
        }
        profile["memory_summary"] = seed_summary
        db.upsert_user_profile(profile)
        logger.info(f"🌱 [SEED_MEMORY] uid={uid} 种子画像已生成: {seed_summary[:60]}...")
        return True
    except Exception as e:
        logger.debug(f"种子画像生成失败 uid={uid}: {e}")
        return False


def _generate_seed_summary(first_message: str) -> str:
    """[v5.24.0 阶段3-B] 基于首条消息的规则分析，生成种子画像摘要

    分析维度：
    - 消息长度 → 短句/中等/长文
    - 语气词 → 礼貌用语检测
    - 问句 → 好奇/主动信号
    - 表情 → 活泼/严肃

    推测用户状态：好奇/观望/主动/被动
    输出格式："新用户首次交互，表现为[状态]，消息特征：[特征]。建议互动方向：[方向]。"

    Returns:
        种子画像摘要文本（≤100 字）
    """
    if not first_message or not isinstance(first_message, str):
        return ""

    msg = first_message.strip()
    if not msg:
        return ""

    # 消息长度分析
    msg_len = len(msg)
    if msg_len <= 10:
        length_feature = "短句"
    elif msg_len <= 50:
        length_feature = "中等"
    else:
        length_feature = "长文"

    # 问句检测（中英文问号 + 疑问词）
    has_question = any(c in msg for c in ["?", "？"]) or \
                   any(w in msg for w in ["怎么", "什么", "为什么", "如何", "吗", "呢", "哪", "是不是", "能不能"])

    # 表情检测（常见 emoji 子串匹配）
    emoji_chars = "😀😄😊😍🥰😘😎🤔😅😂🤣🙂😉😋🤩🥳😭😢😡👍👏💪❤💕💖🔥✨🌟💰🎁"
    has_emoji = any(e in msg for e in emoji_chars)

    # 礼貌用语检测（热情/主动信号）
    msg_lower = msg.lower()
    warm_words = ["你好", "哈喽", "嗨", "hello", "hi", "谢谢", "感谢", "麻烦", "请问"]
    has_warm = any(w in msg_lower for w in warm_words)

    # 推测用户状态 + 建议互动方向
    if has_question and has_emoji:
        user_state = "好奇"
        interaction = "主动引导"
    elif has_question:
        user_state = "主动"
        interaction = "热情回应"
    elif has_emoji or has_warm:
        user_state = "主动"
        interaction = "热情回应"
    elif length_feature == "长文":
        user_state = "观望"
        interaction = "保持观察"
    else:
        user_state = "被动"
        interaction = "主动引导"

    # 消息特征描述
    features = []
    if has_question:
        features.append("问句")
    features.append(length_feature)
    if has_emoji:
        features.append("带表情")
    if has_warm:
        features.append("礼貌用语")
    feature_text = "/".join(features) if features else "普通"

    return (
        f"新用户首次交互，表现为{user_state}，"
        f"消息特征：{feature_text}。"
        f"建议互动方向：{interaction}。"
    )
