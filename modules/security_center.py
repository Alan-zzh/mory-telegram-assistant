# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/security_center.py  ·  群安全中心                            ║
║                                                                        ║
║  功能：统一的群组安全风险评估与管理总览                               ║
║                                                                        ║
║  风险评分系统：                                                         ║
║    - 广告风险（昵称/头像/简介/消息模式）                               ║
║    - 刷屏风险（消息频率/重复度/时段异常）                              ║
║    - 违规内容风险（敏感词/NSFW/仇恨言论）                              ║
║    - 账号异常风险（新号/无头像/无用户名/入群模式）                     ║
║                                                                        ║
║  安全总览：                                                             ║
║    - 今日风险事件数                                                    ║
║    - 当前高风险用户数                                                  ║
║    - 近7日风险趋势                                                     ║
║    - 各维度风险占比                                                    ║
║                                                                        ║
║  自动处置：                                                             ║
║    - 低风险：静默标记+观察                                              ║
║    - 中风险：警告+临时限制                                              ║
║    - 高风险：自动禁言+管理员审核                                        ║
║    - 极高风险：立即封禁+历史清理                                        ║
║                                                                        ║
║  默认关闭：SECURITY_CENTER_CONFIG.enabled = false                     ║
║  被调用：main.py → 安全检测统一入口                                   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
import re
import ast
from datetime import datetime, timezone, timedelta
from collections import deque

from core.logging_util import get_logger

logger = get_logger("security_center")

_CST = timezone(timedelta(hours=8))

DEFAULT_CONFIG = {
    "enabled": False,
    "low_risk_threshold": 30,
    "medium_risk_threshold": 60,
    "high_risk_threshold": 80,
    "critical_risk_threshold": 90,
    "auto_action_medium": "warn",      # warn/mute/none
    "auto_action_high": "mute",        # mute/ban/none
    "auto_action_critical": "ban",     # ban/mute/none
    "mute_minutes_medium": 30,
    "mute_minutes_high": 1440,
    "notify_admin_on_high": True,
    "risk_decay_hours": 24,            # 风险分每24小时衰减一半
}

# 风险因子权重
RISK_WEIGHTS = {
    "ad_username": 15,      # 昵称含广告关键词
    "ad_bio": 20,           # 简介含广告
    "ad_avatar_text": 18,   # 头像有文字
    "ad_message": 25,       # 发广告消息
    "spam_frequency": 20,   # 刷屏频率
    "spam_duplicate": 15,   # 重复内容
    "sensitive_word": 20,   # 敏感词
    "nsfw_image": 30,       # NSFW图片
    "hate_speech": 25,      # 仇恨言论
    "new_account": 10,      # 新号
    "no_avatar": 5,         # 无头像
    "no_username": 8,       # 无用户名
    "raid_pattern": 25,     # 突袭模式入群
    "channel_forward": 12,  # 转发频道消息
    "url_suspicious": 15,   # 可疑链接
}


def _get_config(config: dict) -> dict:
    merged = dict(DEFAULT_CONFIG)
    user_cfg = config.get("SECURITY_CENTER_CONFIG", {})
    merged.update(user_cfg)
    return merged


def _is_enabled(config: dict) -> bool:
    return _get_config(config).get("enabled", False)


# ───────────────────── 风险评分计算 ─────────────────────
class RiskScorer:
    """用户风险评分器"""

    def __init__(self, db=None, config: dict = None):
        self.db = db
        self.config = config or {}
        # 内存缓存：{uid: {"score": int, "factors": {}, "updated_at": ts}}
        self._cache = {}
        self._max_cache = 5000

    def _decay_score(self, cached: dict) -> int:
        """风险分随时间衰减"""
        now = int(time.time())
        elapsed = now - cached.get("updated_at", now)
        cfg = _get_config(self.config)
        decay_half = cfg.get("risk_decay_hours", 24) * 3600
        if elapsed <= 0 or decay_half <= 0:
            return cached.get("score", 0)
        # 指数衰减：每 decay_half 秒减一半
        import math
        factor = 0.5 ** (elapsed / decay_half)
        return int(cached.get("score", 0) * factor)

    def get_risk_score(self, uid: int) -> int:
        """获取用户当前风险分（含衰减）"""
        cached = self._cache.get(uid)
        if not cached:
            # 尝试从数据库加载
            if self.db and hasattr(self.db, 'groups'):
                try:
                    row = self.db.conn.execute(
                        "SELECT risk_score, risk_factors, risk_updated_at FROM user_risk_profile WHERE uid=?",
                        (uid,)
                    ).fetchone()
                    if row:
                        cached = {
                            "score": row[0] or 0,
                            "factors": ast.literal_eval(row[1]) if row[1] else {},
                            "updated_at": row[2] or int(time.time())
                        }
                        self._cache[uid] = cached
                except Exception as e:
                    logger.debug(f"加载风险档案失败: {e}")
        if not cached:
            return 0
        return self._decay_score(cached)

    def add_risk(self, uid: int, factor: str, note: str = "") -> int:
        """
        添加风险因子，返回更新后的总分
        """
        weight = RISK_WEIGHTS.get(factor, 5)
        cached = self._cache.get(uid, {"score": 0, "factors": {}, "updated_at": int(time.time())})

        # 衰减后再加
        current = self._decay_score(cached)
        new_score = min(100, current + weight)

        cached["score"] = new_score
        cached["factors"][factor] = cached["factors"].get(factor, 0) + weight
        cached["updated_at"] = int(time.time())

        # 限制缓存大小
        if len(self._cache) > self._max_cache:
            oldest = min(self._cache.keys(), key=lambda k: self._cache[k].get("updated_at", 0))
            del self._cache[oldest]

        self._cache[uid] = cached

        # 持久化到数据库（容错）
        if self.db:
            try:
                now = int(time.time())
                self.db.conn.execute(
                    """INSERT INTO user_risk_profile (uid, risk_score, risk_factors, risk_updated_at)
                       VALUES (?,?,?,?)
                       ON CONFLICT(uid) DO UPDATE SET
                       risk_score=excluded.risk_score,
                       risk_factors=excluded.risk_factors,
                       risk_updated_at=excluded.risk_updated_at""",
                    (uid, new_score, str(cached["factors"]), now)
                )
                self.db.conn.commit()
            except Exception as e:
                logger.debug(f"风险档案持久化失败: {e}")

        return new_score

    def get_risk_level(self, score: int) -> str:
        """根据分数获取风险等级"""
        cfg = _get_config(self.config)
        if score >= cfg.get("critical_risk_threshold", 90):
            return "critical"
        elif score >= cfg.get("high_risk_threshold", 80):
            return "high"
        elif score >= cfg.get("medium_risk_threshold", 60):
            return "medium"
        elif score >= cfg.get("low_risk_threshold", 30):
            return "low"
        return "safe"

    def clear_risk(self, uid: int) -> bool:
        """清除用户风险分；返回真实清除结果，失败时如实上抛给调用方而非假成功"""
        if not self.db:
            logger.warning(f"清除风险档案跳过：评分器未挂载数据库 uid={uid}")
            self._cache.pop(uid, None)
            return True
        from core.database import _db_lock
        with _db_lock:
            try:
                self.db.conn.execute("DELETE FROM user_risk_profile WHERE uid=?", (uid,))
                self.db.conn.commit()
            except Exception as e:
                # 不吞错：删除失败必须让管理员知道，否则缓存清了、库里残留会"复活"
                logger.error(f"清除风险档案失败 uid={uid}: {e}")
                return False
        self._cache.pop(uid, None)
        return True


# 全局评分器单例（延迟初始化）
_scorer_instance = None


def get_scorer(db=None, config: dict = None) -> RiskScorer:
    global _scorer_instance
    if _scorer_instance is None:
        _scorer_instance = RiskScorer(db, config)
    return _scorer_instance


# ───────────────────── 安全事件记录 ─────────────────────
def log_security_event(db, uid: int, event_type: str, chat_id: int = 0,
                       risk_score: int = 0, action: str = "", detail: str = ""):
    """记录安全事件（带容错）"""
    if not db:
        return
    try:
        now = int(time.time())
        db.conn.execute(
            """INSERT INTO security_events (uid, event_type, chat_id, risk_score, action, detail, ts)
               VALUES (?,?,?,?,?,?,?)""",
            (uid, event_type, chat_id, risk_score, action, detail[:500] if detail else "", now)
        )
        db.conn.commit()
    except Exception as e:
        logger.debug(f"记录安全事件失败: {e}")


# ───────────────────── 安全总览统计 ─────────────────────
def get_security_overview(db, days: int = 7) -> dict:
    """获取安全总览数据"""
    if not db:
        return {}
    since = int(time.time()) - days * 86400
    try:
        # 今日事件数
        today_start = int(datetime.now(_CST).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        today_events = db.conn.execute(
            "SELECT COUNT(*) FROM security_events WHERE ts>=?", (today_start,)
        ).fetchone()[0]

        # 高风险用户数
        high_risk_users = db.conn.execute(
            "SELECT COUNT(*) FROM user_risk_profile WHERE risk_score>=80"
        ).fetchone()[0]

        # 事件类型分布
        type_dist = {}
        rows = db.conn.execute(
            "SELECT event_type, COUNT(*) FROM security_events WHERE ts>=? GROUP BY event_type",
            (since,)
        ).fetchall()
        for r in rows:
            type_dist[r[0]] = r[1]

        # 每日趋势
        daily = []
        rows = db.conn.execute(
            """SELECT DATE(datetime(ts, 'unixepoch', 'localtime')) as d, COUNT(*)
               FROM security_events WHERE ts>=? GROUP BY d ORDER BY d""",
            (since,)
        ).fetchall()
        for r in rows:
            daily.append({"date": r[0], "count": r[1]})

        # 处置统计
        actions = {}
        rows = db.conn.execute(
            "SELECT action, COUNT(*) FROM security_events WHERE ts>=? AND action!='' GROUP BY action",
            (since,)
        ).fetchall()
        for r in rows:
            actions[r[0]] = r[1]

        return {
            "days": days,
            "today_events": today_events,
            "high_risk_users": high_risk_users,
            "event_type_dist": type_dist,
            "daily_trend": daily,
            "action_stats": actions,
        }
    except Exception as e:
        logger.warning(f"获取安全总览失败: {e}")
        return {}


# ───────────────────── 消息安全检测入口 ─────────────────────
def check_message_security(bot, m, config: dict, db) -> dict:
    """
    统一消息安全检测入口
    返回 {"risk_score": int, "risk_level": str, "action": str, "reason": str}
    """
    if not _is_enabled(config):
        return {"risk_score": 0, "risk_level": "safe", "action": "none", "reason": ""}

    scorer = get_scorer(db, config)
    uid = m.from_user.id if m.from_user else 0
    chat_id = m.chat.id if m.chat else 0
    text = m.text or m.caption or ""

    total_added = 0
    reasons = []

    # 1. 敏感词检测
    banned_words = config.get("BANNED_WORDS", [])
    for word in banned_words:
        if word and word in text:
            scorer.add_risk(uid, "sensitive_word", f"敏感词:{word}")
            total_added += RISK_WEIGHTS["sensitive_word"]
            reasons.append(f"敏感词:{word}")
            break

    # 2. 链接检测
    urls = re.findall(r'https?://\S+', text)
    if urls:
        # 简单的可疑链接判断（含 t.me/+ 邀请链接或短链接）
        suspicious = [u for u in urls if ('t.me/' in u and '+' in u) or len(u) < 30]
        if suspicious:
            scorer.add_risk(uid, "url_suspicious", f"可疑链接:{len(suspicious)}个")
            total_added += RISK_WEIGHTS["url_suspicious"]
            reasons.append("可疑链接")

    # 3. 转发频道消息
    if getattr(m, 'forward_from_chat', None) and m.forward_from_chat.type == 'channel':
        scorer.add_risk(uid, "channel_forward")
        total_added += RISK_WEIGHTS["channel_forward"]
        reasons.append("转发频道")

    current_score = scorer.get_risk_score(uid)
    level = scorer.get_risk_level(current_score)

    # 决定处置动作
    cfg = _get_config(config)
    action = "none"
    if level == "critical":
        action = cfg.get("auto_action_critical", "ban")
    elif level == "high":
        action = cfg.get("auto_action_high", "mute")
    elif level == "medium":
        action = cfg.get("auto_action_medium", "warn")

    # 记录事件
    if total_added > 0:
        log_security_event(db, uid, "message_check", chat_id,
                          current_score, action, "; ".join(reasons))

    return {
        "risk_score": current_score,
        "risk_level": level,
        "action": action,
        "reason": "; ".join(reasons)
    }


# ───────────────────── 管理员命令 ─────────────────────
def handle_admin_cmd(bot, m, config: dict, db, args: list) -> bool:
    """管理员安全中心命令"""
    if not _is_enabled(config):
        return False

    uid = m.from_user.id
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if uid != admin_id and uid not in admin_ids:
        return False

    if not args:
        return False

    cmd = args[0]

    try:
        if cmd == "总览" or cmd == "overview":
            overview = get_security_overview(db, 7)
            lines = ["🛡️ 安全中心总览（近7天）："]
            lines.append(f"  今日风险事件：{overview.get('today_events', 0)} 件")
            lines.append(f"  高风险用户：{overview.get('high_risk_users', 0)} 人")
            dist = overview.get('event_type_dist', {})
            if dist:
                lines.append("")
                lines.append("  事件类型分布：")
                for k, v in sorted(dist.items(), key=lambda x: -x[1])[:5]:
                    lines.append(f"    {k}: {v}")
            actions = overview.get('action_stats', {})
            if actions:
                lines.append("")
                lines.append("  处置统计：")
                for k, v in actions.items():
                    lines.append(f"    {k}: {v}")
            bot.reply_to(m, "\n".join(lines))

        elif cmd == "风险" and len(args) >= 2:
            target_uid = int(args[1])
            scorer = get_scorer(db, config)
            score = scorer.get_risk_score(target_uid)
            level = scorer.get_risk_level(score)
            level_text = {"safe": "安全", "low": "低风险", "medium": "中风险",
                         "high": "高风险", "critical": "极高风险"}.get(level, level)
            bot.reply_to(m, f"⚠️ 用户 {target_uid} 风险评分：{score} 分（{level_text}）")

        elif cmd == "清除" and len(args) >= 2:
            target_uid = int(args[1])
            scorer = get_scorer(db, config)
            if scorer.clear_risk(target_uid):
                bot.reply_to(m, f"✅ 已清除用户 {target_uid} 的风险记录")
            else:
                bot.reply_to(m, f"⚠️ 清除用户 {target_uid} 风险记录失败（数据库异常），详情见服务器日志")

        elif cmd == "高风险":
            rows = db.conn.execute(
                "SELECT uid, risk_score, risk_updated_at FROM user_risk_profile WHERE risk_score>=60 ORDER BY risk_score DESC LIMIT 20"
            ).fetchall()
            if not rows:
                bot.reply_to(m, "✅ 当前没有中高风险用户")
                return True
            lines = ["⚠️ 中高风险用户列表（前20）："]
            for r in rows:
                date = datetime.fromtimestamp(r[2], _CST).strftime("%m-%d %H:%M") if r[2] else ""
                lines.append(f"  {r[0]} - {r[1]}分 - 更新于{date}")
            bot.reply_to(m, "\n".join(lines))

        else:
            bot.reply_to(m,
                "🛡️ 安全中心命令：\n"
                "  安全 总览\n"
                "  安全 风险 <用户ID>\n"
                "  安全 高风险\n"
                "  安全 清除 <用户ID>"
            )
        return True
    except Exception as e:
        logger.warning(f"security_center admin cmd 异常: {e}")
        return True
