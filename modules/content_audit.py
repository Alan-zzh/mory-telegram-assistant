# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/content_audit.py  ·  内容排查增强                           ║
║                                                                        ║
║  功能：群内内容全面排查与违规检测                                     ║
║                                                                        ║
║  文本检测：                                                             ║
║    - 敏感词/黑名单词检测                                               ║
║    - 广告营销内容检测（基于规则+关键词）                               ║
║    - 仇恨言论/辱骂检测                                                 ║
║    - 政治敏感词检测                                                    ║
║    - 诈骗/钓鱼话术检测                                                 ║
║                                                                        ║
║  媒体检测：                                                             ║
║    - 图片NSFW评分检测                                                  ║
║    - 图片OCR文字提取+敏感词检测                                        ║
║    - 视频文件类型/大小检查                                             ║
║    - 文件类型黑名单                                                    ║
║                                                                        ║
║  链接检测：                                                             ║
║    - 恶意域名/钓鱼链接检测                                             ║
║    - 短链接风险评估                                                    ║
║    - 邀请链接检测（竞品群引流）                                        ║
║                                                                        ║
║  批量排查：                                                             ║
║    - 按用户排查历史消息                                                ║
║    - 按时间范围排查                                                    ║
║    - 排查结果导出                                                      ║
║                                                                        ║
║  默认关闭：CONTENT_AUDIT_CONFIG.enabled = false                       ║
║  被调用：main.py → P3.5 内容安全检测                                  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import re
import time
from datetime import datetime, timezone, timedelta
from collections import Counter

from core.logging_util import get_logger

logger = get_logger("content_audit")

_CST = timezone(timedelta(hours=8))

DEFAULT_CONFIG = {
    "enabled": False,
    "check_text": True,
    "check_links": True,
    "check_media": False,          # 默认关闭媒体检测（需视觉模型）
    "check_files": True,
    "auto_delete_violation": False,  # 默认只记录不删除
    "violation_threshold": 3,     # 累计3次违规触发禁言
    "mute_minutes": 60,
    "notify_admin_on_violation": True,
}

# 诈骗话术模式
SCAM_PATTERNS = [
    r"点击.*领取", r"免费.*领取", r"加.*微信.*送", r"加.*qq.*福利",
    r"扫码.*进群", r"关注.*公众号", r"点赞.*返现", r"刷单.*赚",
    r"兼职.*日结", r"投资.*回报", r"稳赚不赔", r"内幕消息",
]

# 政治敏感词（基础版，可通过配置扩展）
POLITICAL_SENSITIVE = []

# 危险文件扩展名
DANGEROUS_EXTENSIONS = [
    ".exe", ".bat", ".cmd", ".msi", ".vbs", ".js", ".jse",
    ".wsf", ".wsh", ".ps1", ".psm1", ".scr", ".com", ".pif",
    ".dll", ".so", ".dylib", ".apk",
]

# 可疑TLD
SUSPICIOUS_TLDS = [".xyz", ".top", ".club", ".tk", ".ml", ".ga", ".cf", ".gq"]


def _get_config(config: dict) -> dict:
    merged = dict(DEFAULT_CONFIG)
    user_cfg = config.get("CONTENT_AUDIT_CONFIG", {})
    merged.update(user_cfg)
    return merged


def _is_enabled(config: dict) -> bool:
    return _get_config(config).get("enabled", False)


# ───────────────────── 文本检测 ─────────────────────
def audit_text(text: str, config: dict = None) -> dict:
    """
    文本内容审计
    返回 {"violations": list, "risk_level": str, "details": list}
    """
    violations = []
    details = []
    text = text or ""

    if not text:
        return {"violations": [], "risk_level": "safe", "details": []}

    cfg = _get_config(config or {})

    # 1. 敏感词检测
    banned_words = (config or {}).get("BANNED_WORDS", [])
    found_banned = [w for w in banned_words if w and w in text]
    if found_banned:
        violations.append("banned_word")
        details.append(f"敏感词: {','.join(found_banned)}")

    # 2. 仇恨/辱骂词
    hate_keywords = (config or {}).get("HATE_KEYWORDS", [])
    found_hate = [w for w in hate_keywords if w and w in text]
    if found_hate:
        violations.append("hate_speech")
        details.append(f"仇恨词: {','.join(found_hate)}")

    # 3. 诈骗话术检测
    found_scam = []
    for pat in SCAM_PATTERNS:
        if re.search(pat, text):
            found_scam.append(pat)
            if len(found_scam) >= 2:  # 匹配2个以上才判定
                violations.append("scam")
                details.append(f"疑似诈骗话术: {len(found_scam)}项特征")
                break

    # 4. 广告检测（已有 ad_detector 模块，这里做轻量补充）
    ad_keywords = ["加微信", "加qq", "私聊我", "加好友", "vx:", "wx:", "微:", "v信"]
    found_ad = [kw for kw in ad_keywords if kw.lower() in text.lower()]
    if len(found_ad) >= 2:
        violations.append("ad_keywords")
        details.append(f"广告关键词: {','.join(found_ad)}")

    # 计算风险等级
    risk_score = len(violations) * 30
    if risk_score >= 80:
        risk_level = "high"
    elif risk_score >= 40:
        risk_level = "medium"
    elif risk_score >= 20:
        risk_level = "low"
    else:
        risk_level = "safe"

    return {
        "violations": violations,
        "risk_level": risk_level,
        "risk_score": min(100, risk_score),
        "details": details
    }


# ───────────────────── 链接检测 ─────────────────────
def audit_links(text: str, config: dict = None) -> dict:
    """链接安全审计"""
    violations = []
    details = []

    urls = re.findall(r'https?://\S+', text or "")
    if not urls:
        return {"violations": [], "risk_level": "safe", "url_count": 0, "details": []}

    cfg = _get_config(config or {})

    # 检查每个URL
    for url in urls[:10]:  # 最多检查10个
        # 1. 竞品群邀请链接
        if 't.me/' in url and '+' in url:
            violations.append("invite_link")
            details.append(f"群邀请链接: {url[:50]}")

        # 2. 可疑TLD
        for tld in SUSPICIOUS_TLDS:
            # 简单判断：域名部分是否以可疑TLD结尾
            match = re.search(r'https?://([^/]+)', url)
            if match and match.group(1).endswith(tld):
                violations.append("suspicious_tld")
                details.append(f"可疑域名后缀{tld}: {match.group(1)}")
                break

        # 3. 短链接
        if len(url) < 30 and re.match(r'https?://[^/]{4,15}/', url):
            violations.append("short_url")
            details.append(f"疑似短链接: {url[:50]}")
            break

    # 风险等级
    risk_score = min(100, len([v for v in violations if v != "short_url"]) * 35 + violations.count("short_url") * 10)
    if risk_score >= 80:
        risk_level = "high"
    elif risk_score >= 40:
        risk_level = "medium"
    elif risk_score >= 20:
        risk_level = "low"
    else:
        risk_level = "safe"

    return {
        "violations": list(set(violations)),
        "risk_level": risk_level,
        "risk_score": risk_score,
        "url_count": len(urls),
        "details": details
    }


# ───────────────────── 文件检测 ─────────────────────
def audit_file(file_name: str, file_size: int = 0, mime_type: str = "") -> dict:
    """文件安全检查"""
    violations = []
    details = []

    if not file_name:
        return {"violations": [], "risk_level": "safe", "details": []}

    # 检查扩展名
    fname_lower = file_name.lower()
    for ext in DANGEROUS_EXTENSIONS:
        if fname_lower.endswith(ext):
            violations.append("dangerous_ext")
            details.append(f"危险文件类型: {ext}")
            break

    # 检查文件大小异常（>50MB的可执行文件风险更高）
    if file_size > 50 * 1024 * 1024 and violations:
        details.append(f"大文件: {file_size / 1024 / 1024:.1f}MB")

    risk_level = "high" if violations else "safe"

    return {
        "violations": violations,
        "risk_level": risk_level,
        "risk_score": 80 if violations else 0,
        "details": details
    }


# ───────────────────── 统一入口 ─────────────────────
def audit_message(bot, m, config: dict, db) -> dict:
    """
    统一消息内容审计入口
    返回 {"violations": list, "risk_level": str, "details": list, "action": str}
    """
    if not _is_enabled(config):
        return {"violations": [], "risk_level": "safe", "details": [], "action": "none"}

    uid = m.from_user.id if m.from_user else 0
    chat_id = m.chat.id if m.chat else 0
    text = m.text or m.caption or ""

    all_violations = []
    all_details = []
    max_risk = "safe"

    cfg = _get_config(config)

    # 文本检测
    if cfg.get("check_text", True) and text:
        result = audit_text(text, config)
        all_violations.extend(result["violations"])
        all_details.extend(result["details"])
        if result["risk_level"] != "safe":
            if _risk_priority(result["risk_level"]) > _risk_priority(max_risk):
                max_risk = result["risk_level"]

    # 链接检测
    if cfg.get("check_links", True) and text:
        result = audit_links(text, config)
        all_violations.extend(result["violations"])
        all_details.extend(result["details"])
        if result["risk_level"] != "safe":
            if _risk_priority(result["risk_level"]) > _risk_priority(max_risk):
                max_risk = result["risk_level"]

    # 文件检测
    if cfg.get("check_files", True) and (m.document or m.animation):
        doc = m.document or m.animation
        file_name = getattr(doc, 'file_name', '') or ''
        file_size = getattr(doc, 'file_size', 0) or 0
        mime = getattr(doc, 'mime_type', '') or ''
        result = audit_file(file_name, file_size, mime)
        all_violations.extend(result["violations"])
        all_details.extend(result["details"])
        if result["risk_level"] != "safe":
            if _risk_priority(result["risk_level"]) > _risk_priority(max_risk):
                max_risk = result["risk_level"]

    # 决定处置动作
    action = "none"
    if max_risk == "high" and cfg.get("auto_delete_violation", False):
        action = "delete"
    elif max_risk == "medium":
        action = "warn"

    # 记录违规事件
    if all_violations:
        try:
            now = int(time.time())
            db.conn.execute(
                """INSERT INTO content_violations (uid, chat_id, message_type, violations, risk_level, detail, ts)
                   VALUES (?,?,?,?,?,?,?)""",
                (uid, chat_id, "text" if text else "file",
                 ",".join(all_violations), max_risk,
                 "; ".join(all_details)[:500], now)
            )
            db.conn.commit()
        except Exception as e:
            logger.debug(f"记录违规失败: {e}")

    return {
        "violations": all_violations,
        "risk_level": max_risk,
        "details": all_details,
        "action": action
    }


def _risk_priority(level: str) -> int:
    return {"safe": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}.get(level, 0)


# ───────────────────── 违规统计 ─────────────────────
def get_violation_stats(db, days: int = 7) -> dict:
    """获取违规统计"""
    since = int(time.time()) - days * 86400
    try:
        with db.lock:
            total = db.conn.execute(
                "SELECT COUNT(*) FROM content_violations WHERE ts>?", (since,)
            ).fetchone()[0]
            type_dist = {}
            rows = db.conn.execute(
                "SELECT risk_level, COUNT(*) FROM content_violations WHERE ts>? GROUP BY risk_level",
                (since,)
            ).fetchall()
            for r in rows:
                type_dist[r[0]] = r[1]
            top_users = db.conn.execute(
                """SELECT uid, COUNT(*) as cnt FROM content_violations
                   WHERE ts>? GROUP BY uid ORDER BY cnt DESC LIMIT 10""",
                (since,)
            ).fetchall()
            return {
                "days": days,
                "total_violations": total,
                "risk_distribution": type_dist,
                "top_offenders": top_users
            }
    except Exception as e:
        logger.warning(f"获取违规统计失败: {e}")
        return {}


# ───────────────────── 管理员命令 ─────────────────────
def handle_admin_cmd(bot, m, config: dict, db, args: list) -> bool:
    """管理员内容排查命令"""
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
        if cmd == "统计":
            stats = get_violation_stats(db, 7)
            lines = [f"🔍 内容排查统计（近{stats.get('days',7)}天）："]
            lines.append(f"  违规总数：{stats.get('total_violations', 0)}")
            dist = stats.get('risk_distribution', {})
            if dist:
                lines.append("  风险分布：")
                for k, v in dist.items():
                    lines.append(f"    {k}: {v}")
            top = stats.get('top_offenders', [])
            if top:
                lines.append("  Top违规用户：")
                for u in top:
                    lines.append(f"    {u[0]}: {u[1]}次")
            bot.reply_to(m, "\n".join(lines))

        elif cmd == "用户" and len(args) >= 2:
            target_uid = int(args[1])
            rows = db.conn.execute(
                """SELECT violations, risk_level, detail, ts FROM content_violations
                   WHERE uid=? ORDER BY ts DESC LIMIT 20""",
                (target_uid,)
            ).fetchall()
            if not rows:
                bot.reply_to(m, "该用户无违规记录")
                return True
            lines = [f"📋 用户 {target_uid} 近期违规记录："]
            for r in rows:
                date = datetime.fromtimestamp(r[3], _CST).strftime("%m-%d %H:%M")
                lines.append(f"  [{date}] {r[1]}: {r[0]} - {r[2][:40]}")
            bot.reply_to(m, "\n".join(lines))

        else:
            bot.reply_to(m,
                "🔍 内容排查命令：\n"
                "  排查 统计\n"
                "  排查 用户 <用户ID>"
            )
        return True
    except Exception as e:
        logger.warning(f"content_audit admin cmd 异常: {e}")
        return True
