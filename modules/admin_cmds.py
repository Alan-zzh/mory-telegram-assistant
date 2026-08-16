"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/admin_cmds.py  ·  管理员指令模块                              ║
║                                                                        ║
║  功能：处理所有管理员专属指令。                                         ║
║                                                                        ║
║  【v21.38 自然语言指令】（任何人可用，自动识别）                          ║
║    把回复概率改成20%   -> 修改 REPLY_CHANCE                            ║
║    开启碎片暗号        -> 开启 PUZZLE_ENABLED                          ║
║    关闭碎片暗号        -> 关闭 PUZZLE_ENABLED                           ║
║    把碎片暗号改成888   -> 修改 PUZZLE_WORD                             ║
║    把刷屏限制改成5     -> 修改 SPAM_LIMIT                              ║
║    开启签到/关闭签到   -> 修改 SIGNUP_ENABLED                          ║
║    开启早安/关闭早安   -> 修改 AUTO_GREETING                           ║
║    查看设置            -> 显示当前所有配置状态                           ║
║                                                                        ║
║  管理员指令清单：                                                      ║
║    绑定主人        -> 首次设置管理员（之后只有主人能重新绑）              ║
║    设置人设 [文本]  -> 动态修改机器人的SYSTEM_PROMPT                    ║
║    查看人设         -> 查看当前人设内容（不走AI）                       ║
║    投喂资料 [文本]  -> 追加业务知识库KNOWLEDGE                          ║
║    查看资料         -> 查看当前知识库内容（不走AI）                     ║
║    清空资料         -> 清空知识库                                      ║
║    设置概率 [0-100] -> 修改群聊随机回复概率                             ║
║    查看配置         -> 一次性总览所有配置（不走AI）                     ║
║    代发 @ID 消息   -> 私信任意用户（传话功能）                          ║
║    代发群 消息      -> 以机器人名义发到主群                             ║
║    代发频道 消息    -> 推送到config中所有频道                            ║
║    投票 问题 选项   -> 群里发起投票                                     ║
║    每日简报 /report -> 生成运营数据简报                                 ║
║    排行榜 /rank     -> 积分排行榜                                       ║
║    当前模型 /model  -> 查看所有模型和当前使用                           ║
║    切换模型 [名称]  -> 手动切换AI模型                                  ║
║    /blacklist @ID   -> 拉黑用户                                        ║
║    /mute @ID 分钟   -> 禁言用户（需机器人为群管理员）                    ║
║    清群无人理       -> 立刻删除群里所有无人回复的机器人消息               ║
║    清全部回复       -> 删除群里所有机器人的回复（含被回复的原消息追踪）    ║
║                                                                         ║
║  【v21.17 动态进化系统】                                                 ║
║    加热词 [词汇...]  -> 给热词库追加新词汇，立即生效                     ║
║    查热词           -> 查看当前热词库                                   ║
║    改风格 [描述]    -> 快速调整说话风格（如"更骚一点"/"更温柔"）        ║
║    学知识 [内容]    -> 让机器人学习新知识（追加到SYSTEM_PROMPT）         ║
║    忘记 [关键词]    -> 从知识库中移除包含某关键词的内容                 ║
║    进化 [指令]      -> 高级进化：直接修改任意配置项                      ║
║                                                                        ║
║  被调用：main.py -> handle_admin() 在P6优先级执行                      ║
║  返回值：True=已消费该消息，False=不是管理员指令，继续往下处理           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from core.config_compat import normalize_runtime_config
from core.admin_utils import get_admin_ids, is_admin_user

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from core.broadcast_formatter import build_broadcast_html, looks_like_html
from core.logging_util import get_logger
from core.telebot_compat import send_checklist_compat, send_message_compat, send_poll_compat
from modules.natural_cmd import handle_natural_admin

logger = get_logger("admin_cmds")

_CST = timezone(timedelta(hours=8))


# ════════════════════════════════════════════════════════════════════════
# 公开指令处理函数（任何人可用，权限检查前执行）
# ════════════════════════════════════════════════════════════════════════

def _handle_bind_master(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 绑定主人 命令（首次ADMIN_ID为0时仅私聊可绑，之后只有主人能重新绑）[Trae] 安全修复：限制私聊才能首次绑定"""
    uid = m.from_user.id
    is_priv = m.chat.type == "private"
    if config.get("ADMIN_ID", 0) == 0:
        if not is_priv:
            mory_bot.reply_and_track(m, "⚠️ 首次绑定主人请私聊机器人操作，群聊中不开放此功能。")
            return True
        config["ADMIN_ID"] = uid
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 绑定成功！主人ID：{uid}")
        logger.info(f"👑 绑定管理员：{uid}")
    elif uid == config.get("ADMIN_ID", 0):
        config["ADMIN_ID"] = uid
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 重新绑定成功！主人ID：{uid}")
        logger.info(f"👑 重新绑定管理员：{uid}")
    else:
        mory_bot.reply_and_track(m, "⛔ 已有主人，无法绑定。")
    return True


def _handle_add_admin(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 添加管理员 命令（通过回复某人的消息来添加其为管理员）"""
    if m.reply_to_message and m.reply_to_message.from_user:
        target_uid = m.reply_to_message.from_user.id
        target_name = m.reply_to_message.from_user.first_name or str(target_uid)
        admin_ids = config.get("ADMIN_IDS", [])
        if isinstance(admin_ids, int):
            admin_ids = [admin_ids]
        if not isinstance(admin_ids, list):
            admin_ids = []
        if admin_id := config.get("ADMIN_ID", 0):
            if admin_id not in admin_ids:
                admin_ids.append(admin_id)
        if target_uid in admin_ids:
            mory_bot.reply_and_track(m, f"⚠️ {target_name} 已经是管理员了。")
        else:
            admin_ids.append(target_uid)
            config["ADMIN_IDS"] = admin_ids
            save_config_fn()
            mory_bot.reply_and_track(m, f"✅ 已将 {target_name}({target_uid}) 添加为管理员。")
            logger.info(f"👑 添加管理员：{target_name}({target_uid})")
    else:
        mory_bot.reply_and_track(m, "⚠️ 请回复某人的消息后发送「添加管理员」。")
    return True


def _handle_view_admins(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 查看管理员列表 命令"""
    admin_ids = config.get("ADMIN_IDS", [])
    admin_id = config.get("ADMIN_ID", 0)
    if isinstance(admin_ids, int):
        admin_ids = [admin_ids]
    if not isinstance(admin_ids, list):
        admin_ids = []
    if admin_id and admin_id not in admin_ids:
        admin_ids.append(admin_id)
    if not admin_ids:
        mory_bot.reply_and_track(m, "⚠️ 当前没有管理员。")
    else:
        lines = [f"👑 管理员列表（共{len(admin_ids)}人）："]
        for i, aid in enumerate(admin_ids, 1):
            role = "👑 主人" if aid == admin_id else "🛡️ 管理员"
            lines.append(f"  {i}. {role}：{aid}")
        mory_bot.reply_and_track(m, "\n".join(lines))
    return True


# ════════════════════════════════════════════════════════════════════════
# 主人指令处理函数（需要 admin 权限，权限检查后执行）
# ════════════════════════════════════════════════════════════════════════

def _handle_set_persona(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 设置人设 命令"""
    new_persona = msg[5:].strip()
    if new_persona:
        # 结构化：写入BASE_PERSONA（核心人设，稳定不变）
        config["BASE_PERSONA"] = new_persona
        # 清空旧字段避免冲突
        config.pop("SYSTEM_PROMPT", None)
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 核心人设已更新：\n{new_persona[:100]}{'...' if len(new_persona)>100 else ''}")
        logger.info(f"📝 核心人设已更新")
    else:
        mory_bot.reply_and_track(m, "⚠️ 格式：设置人设 [人设内容]")
    return True


def _handle_view_persona(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 查看人设 命令（不走AI，直接读config）"""
    chat_id = m.chat.id
    if "BASE_PERSONA" in config:
        persona = config.get("BASE_PERSONA", "(空)")
        style = config.get("STYLE_APPEND", "")
        added = config.get("ADDED_KNOWLEDGE", "")
        knowledge = config.get("KNOWLEDGE", "")
        text = f"📋 当前人设：\n\n{persona}"
        if style:
            text += f"\n\n🎨 风格追加：\n{style}"
        if knowledge:
            text += f"\n\n📚 知识库：\n{knowledge}"
        if added:
            text += f"\n\n📝 追加知识：\n{added}"
    else:
        persona = config.get("SYSTEM_PROMPT", "(空)")
        text = f"📋 当前人设：\n\n{persona}"
    bot.send_message(chat_id, text)
    logger.info("👁️ 管理员查看了人设")
    return True


def _handle_feed_knowledge(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 投喂资料 命令"""
    extra = msg[5:].strip()
    config["KNOWLEDGE"] = config.get("KNOWLEDGE", "") + f"\n{extra}"
    save_config_fn()
    mory_bot.reply_and_track(m, "✅ 知识库已追加。")
    return True


def _handle_view_knowledge(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 查看资料/知识库 命令（不走AI，直接读config）"""
    chat_id = m.chat.id
    knowledge = config.get("KNOWLEDGE", "(空)")
    bot.send_message(chat_id, f"📚 当前知识库：\n\n{knowledge}")
    logger.info("👁️ 管理员查看了知识库")
    return True


# ════════════════════════════════════════════════════════════════════════
# [Agent G] 风格样本投喂（人工审核工作流，只生成 pending，不自动启用）
# ════════════════════════════════════════════════════════════════════════

_SCENE_ALIASES = {
    "chat": "chat", "普通": "chat", "闲聊": "chat", "聊天": "chat",
    "greeting": "greeting", "问候": "greeting", "早安": "greeting",
    "engage": "engage", "搭讪": "engage", "承接": "engage",
    "faq": "faq", "问答": "faq",
    "broadcast": "broadcast", "播报": "broadcast",
}

_FEED_HELP = (
    "📖 风格样本投喂格式：\n"
    "1️⃣ 单条：/投喂 场景:chat 用户话术 | Mory回复\n"
    "2️⃣ 批量：/投喂文件 场景:chat（发送 .txt 文档或直接粘贴文本）\n"
    "批量文本约定（二选一）：\n"
    "  A. 每两行一组：第一行用户话术，第二行 Mory回复，依次配对\n"
    "  B. 前缀配对：user:用户话术 / mory:Mory回复 交替出现\n"
    "场景可选：chat/greeting/engage/faq/broadcast（默认 chat），中文别名也可（普通/问候/搭讪/问答/播报）\n"
    "所有样本都只进入待审队列，由管理员在 Dashboard 审核后才能启用。"
)


def _parse_feed_scene(text: str) -> tuple[str, str]:
    """从命令文本提取 场景:xxx；返回 (scene, error)。显式场景非法时 error 非空。"""
    m = re.search(r"场景\s*[:：]\s*([^\s|，,。]+)", text)
    if not m:
        return "chat", ""
    raw = m.group(1).strip().lower()
    scene = _SCENE_ALIASES.get(raw)
    if scene is None:
        return "", f"场景「{raw}」不支持，可选：chat / greeting / engage / faq / broadcast"
    return scene, ""


def _parse_and_feed_pairs(db, content: str, scene: str, created_by: str) -> tuple[int, int, list[str]]:
    """解析投喂文本并批量入库。返回 (成功数, 孤儿行数, 被拒错误列表)。"""
    from core.db_repos.reply_evolution_repo import validate_feed_sample_safety

    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    pairs: list[tuple[str, str]] = []
    orphan = 0
    pending_user: tuple[int, str] | None = None
    for i, line in enumerate(lines):
        m_user = re.match(r"^(?:user|用户)\s*[:：]\s*(.+)$", line, re.IGNORECASE)
        m_mory = re.match(r"^(?:mory|mory回复)\s*[:：]\s*(.+)$", line, re.IGNORECASE)
        if m_user:
            if pending_user is not None:
                orphan += 1  # 前一个 user 未等到配对，成为孤儿行
            pending_user = (i, m_user.group(1).strip())
        elif m_mory:
            if pending_user is not None:
                pairs.append((pending_user[1], m_mory.group(1).strip()))
                pending_user = None
            else:
                orphan += 1  # 孤儿 mory
        else:
            # 无前缀：按每两行一组配对
            if pending_user is None:
                pending_user = (i, line)
            else:
                pairs.append((pending_user[1], line))
                pending_user = None
    if pending_user is not None:
        orphan += 1

    ok_count = 0
    error_msgs: list[str] = []
    for user_text, mory_text in pairs:
        vok, reason = validate_feed_sample_safety(user_text, mory_text)
        if not vok:
            error_msgs.append(f"「{user_text[:20]}」：{reason}")
            continue
        combined = f"用户：{user_text}\nMory：{mory_text}"
        result = db.create_reply_style_sample(
            combined,
            label=f"投喂-{scene}",
            created_by=created_by,
            scene=scene,
            user_text=user_text,
            mory_text=mory_text,
        )
        if result.get("ok"):
            ok_count += 1
        else:
            error_msgs.append(f"「{user_text[:20]}」：{result.get('error', '保存失败')}")
    return ok_count, orphan, error_msgs


def _handle_feed_style_sample(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 /投喂 场景:chat 用户话术 | Mory回复 命令（单条投喂，只生成 pending）。"""
    text = msg
    # 文件批量命令交给 _handle_feed_style_file，避免前缀误抢
    if text.startswith("/投喂文件") or text.startswith("投喂文件"):
        return False
    for prefix in ("/投喂 ", "投喂样本 ", "投喂样本", "/投喂", "投喂 "):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    if not text:
        mory_bot.reply_and_track(m, _FEED_HELP)
        return True
    scene, scene_err = _parse_feed_scene(text)
    if scene_err:
        mory_bot.reply_and_track(m, f"⚠️ {scene_err}")
        return True
    body = re.sub(r"场景\s*[:：]\s*[^\s|，,。]+", "", text, count=1).strip()
    if "|" not in body:
        mory_bot.reply_and_track(m, "⚠️ 格式：/投喂 场景:chat 用户话术 | Mory回复（用 | 分隔两段）")
        return True
    user_text, mory_text = body.split("|", 1)
    user_text = user_text.strip()
    mory_text = mory_text.strip()
    combined = f"用户：{user_text}\nMory：{mory_text}"
    result = db.create_reply_style_sample(
        combined,
        label=f"投喂-{scene}",
        created_by=str(m.from_user.id),
        scene=scene,
        user_text=user_text,
        mory_text=mory_text,
    )
    if not result.get("ok"):
        mory_bot.reply_and_track(m, f"⚠️ 投喂失败：{result.get('error', '未知原因')}")
        return True
    mory_bot.reply_and_track(m, f"✅ 已投喂 1 条风格样本（场景：{scene}，待人工审核）。")
    logger.info(f"🍼 管理员投喂风格样本 scene={scene} id={result.get('id')}")
    return True


def _handle_feed_style_file(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 /投喂文件 场景:chat：以文档或粘贴文本批量导入风格样本（只生成 pending）。"""
    text = msg
    for prefix in ("/投喂文件", "投喂文件"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    scene, scene_err = _parse_feed_scene(text)
    if scene_err:
        mory_bot.reply_and_track(m, f"⚠️ {scene_err}")
        return True
    content = ""
    if getattr(m, "document", None):
        try:
            file_info = bot.get_file(m.document.file_id)
            raw = bot.download_file(file_info.file_path)
            if not raw:
                mory_bot.reply_and_track(m, "⚠️ 文件内容为空，请检查文件后重试。")
                return True
            content = raw.decode("utf-8", errors="replace")
        except Exception as exc:
            logger.warning(f"投喂文件下载失败: {exc}")
            mory_bot.reply_and_track(m, "⚠️ 文件下载失败，请重试或改用粘贴文本方式。")
            return True
    else:
        content = re.sub(r"^\s*场景\s*[:：]\s*[^\s|，,。]+\s*", "", text)
    if not content.strip():
        mory_bot.reply_and_track(m, _FEED_HELP)
        return True
    ok_count, orphan_count, error_msgs = _parse_and_feed_pairs(db, content, scene, str(m.from_user.id))
    reply = f"✅ 批量投喂完成：成功 {ok_count} 条（场景：{scene}，待人工审核）"
    if orphan_count:
        reply += f"\n⚠️ 跳过无法配对的孤儿行 {orphan_count} 行"
    if error_msgs:
        reply += f"\n⛔ 安全校验拒绝 {len(error_msgs)} 条：" + "\n".join(error_msgs[:3])
    mory_bot.reply_and_track(m, reply)
    logger.info(f"🍼 管理员批量投喂风格样本 scene={scene} ok={ok_count} orphan={orphan_count}")
    return True


def _handle_clear_knowledge(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 清空知识库 命令"""
    chat_id = m.chat.id
    config["KNOWLEDGE"] = ""
    save_config_fn()
    bot.send_message(chat_id, "✅ 知识库已清空。可以重新用「投喂资料 [内容]」添加。")
    logger.info("🗑️ 管理员清空了知识库")
    return True


def _handle_set_rate(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 设置概率 命令"""
    try:
        val = int(msg.split()[1])
        assert 0 <= val <= 100
        config["REPLY_CHANCE"] = val
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 群聊随机回复概率已设为 {val}%")
    except (ValueError, AssertionError):
        mory_bot.reply_and_track(m, "⚠️ 格式：设置概率 [0-100]")
    return True


def _handle_view_config(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 查看全部配置 命令（不走AI，一次性总览）"""
    chat_id = m.chat.id
    pool = config.get("MODEL_POOLS", {}).get("llm", config.get("MODEL_POOL", []))
    idx = config.get("CURRENT_MODEL_INDEX", 0)
    cur_name = pool[idx]["name"] if pool and idx < len(pool) else "未知"
    channels = config.get("CHANNEL_IDS", [])
    ch_text = str(channels) if channels else "未配置"
    status = (
        f"📊 当前配置总览\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 机器人名：{config.get('BOT_NAME', '未设置')}\n"
        f"👑 管理员ID：{config.get('ADMIN_ID', '未绑定')}\n"
        f"💬 主群ID：{config.get('GROUP_ID', '未设置')}\n"
        f"📡 频道：{ch_text}\n"
        f"🎲 回复概率：{config.get('REPLY_CHANCE', 30)}%\n"
        f"🧠 当前模型：{cur_name}\n"
        f"📋 人设长度：{len(config.get('SYSTEM_PROMPT', ''))} 字\n"
        f"📚 知识库长度：{len(config.get('KNOWLEDGE', ''))} 字\n"
        f"🚫 黑名单词：{config.get('BANNED_WORDS', [])}\n"
        f"⚡ 刷屏阈值：{config.get('SPAM_LIMIT', {}).get('messages_per_minute', 10)} 条/分\n"
        f"🧩 寻宝暗号：{config.get('PUZZLE_WORD', '未设置')}\n"
        f"🔒 配置版本：v{config.get('_CONFIG_VERSION', '?')}\n"
        f"📅 配置更新：{config.get('_CONFIG_UPDATED', '?')}\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )
    bot.send_message(chat_id, status)
    logger.info("👁️ 管理员查看了配置总览")
    return True


def _handle_send_to_user(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 代发 @ID 消息 命令（传话给任意用户）"""
    parts = msg.split(" ", 2)
    if len(parts) == 3:
        try:
            target_id = int(parts[1].lstrip("@"))
            content = parts[2]
            text = content if looks_like_html(content) else build_broadcast_html(
                f"{config['BOT_NAME']}捎话",
                content,
                "这条消息由管理员代发。",
                "私信送达",
            )
            send_message_compat(bot, target_id, text, parse_mode="HTML")
            mory_bot.reply_and_track(m, f"✅ 已私信用户 @{parts[1].lstrip('@')}")
            logger.info(f"📨 代发→{target_id}：{content[:50]}")
        except Exception as e:
            mory_bot.reply_and_track(m, f"⚠️ 发送失败：{e}")
    else:
        mory_bot.reply_and_track(m, "⚠️ 格式：代发 @用户ID 消息内容")
    return True


def _handle_send_to_group(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 代发到主群 命令"""
    content = msg[4:].strip()
    try:
        text = content if looks_like_html(content) else build_broadcast_html(
            "群通知",
            content,
            "如需更多细节，Mory稍后会继续跟进。",
            "管理员代发",
        )
        send_message_compat(bot, config["GROUP_ID"], text, parse_mode="HTML")
        mory_bot.reply_and_track(m, "✅ 已发到主群。")
        logger.info(f"📢 代发群：{content[:50]}")
    except Exception as e:
        mory_bot.reply_and_track(m, f"⚠️ 失败：{e}")
    return True


def _handle_send_to_channel(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 代发到频道 命令"""
    content = msg[5:].strip()
    channels = config.get("CHANNEL_IDS", [])
    if not channels:
        mory_bot.reply_and_track(m, "⚠️ 未配置频道ID，请在 config.json 的 CHANNEL_IDS 中添加。")
    else:
        ok, fail = 0, 0
        for ch in channels:
            cid = ch.get("id", 0) if isinstance(ch, dict) else ch
            try:
                text = content if looks_like_html(content) else build_broadcast_html(
                    "频道播报",
                    content,
                    "想看详细入口的话，按频道内指引继续就好。",
                    config.get("BOT_NAME", "Mory"),
                )
                sent = send_message_compat(bot, cid, text, parse_mode="HTML")
                db.track_channel_message(cid, sent.message_id, "text")
                ok += 1
            except Exception as e:
                fail += 1
                logger.warning(f"推送频道失败 cid={cid}：{e}")
        mory_bot.reply_and_track(m, f"✅ 已推送 {ok} 个频道，失败 {fail} 个。")
    return True


def _handle_poll(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 投票 命令"""
    content = msg[3:].strip()
    try:
        if content.startswith("{"):
            poll_cfg = json.loads(content)
            question = str(poll_cfg.get("question", "")).strip()
            options = poll_cfg.get("options", [])
            if isinstance(options, str):
                options = [item.strip() for item in options.split("|") if item.strip()]
            if not question or len(options) < 2:
                mory_bot.reply_and_track(m, "⚠️ JSON投票需要 question 和至少2个 options")
                return True
            send_poll_compat(
                bot,
                config["GROUP_ID"],
                question,
                options,
                is_anonymous=poll_cfg.get("is_anonymous", False),
                type=poll_cfg.get("type"),
                allows_multiple_answers=poll_cfg.get("allows_multiple_answers"),
                correct_option_id=poll_cfg.get("correct_option_id"),
                correct_option_ids=poll_cfg.get("correct_option_ids"),
                explanation=poll_cfg.get("explanation"),
                explanation_parse_mode=poll_cfg.get("explanation_parse_mode"),
                open_period=poll_cfg.get("open_period"),
                close_date=poll_cfg.get("close_date"),
                media=poll_cfg.get("media"),
                description=poll_cfg.get("description"),
                description_parse_mode=poll_cfg.get("description_parse_mode"),
                allows_changing_answer=poll_cfg.get("allows_changing_answer"),
                allows_revoting=poll_cfg.get("allows_revoting"),
                country_codes=poll_cfg.get("country_codes"),
                members_only=poll_cfg.get("members_only"),
                shuffle_options=poll_cfg.get("shuffle_options"),
                hide_results_until_closes=poll_cfg.get("hide_results_until_closes"),
                allow_adding_options=poll_cfg.get("allow_adding_options"),
                allow_paid_broadcast=poll_cfg.get("allow_paid_broadcast"),
                message_effect_id=poll_cfg.get("message_effect_id"),
                direct_messages_topic_id=poll_cfg.get("direct_messages_topic_id"),
                suggested_post_parameters=poll_cfg.get("suggested_post_parameters"),
            )
            mory_bot.reply_and_track(m, "✅ 新版投票已在群里发起。")
            logger.info(f"🗳️ 新版投票：{question}")
        else:
            parts = content.split(" ", 1)
            if len(parts) < 2:
                mory_bot.reply_and_track(m, "⚠️ 格式：投票 问题 选项1 选项2，或 投票 {JSON配置}")
                return True
            question = parts[0]
            options = parts[1].split(" ")
            if len(options) < 2:
                mory_bot.reply_and_track(m, "⚠️ 至少需要2个选项")
                return True
            send_poll_compat(bot, config["GROUP_ID"], question, options, is_anonymous=False)
            mory_bot.reply_and_track(m, "✅ 投票已在群里发起。")
            logger.info(f"🗳️ 投票：{question}")
    except Exception as e:
        mory_bot.reply_and_track(m, f"⚠️ 投票失败：{e}")
    return True


def _handle_checklist(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 新版清单（Telegram Business Checklist）命令"""
    content = msg[3:].strip()
    try:
        if not content.startswith("{"):
            mory_bot.reply_and_track(m, "⚠️ 格式：清单 {JSON配置}")
            return True
        checklist_cfg = json.loads(content)
        business_connection_id = (
            checklist_cfg.get("business_connection_id")
            or config.get("TELEGRAM_BUSINESS_CONNECTION_ID")
            or ""
        )
        if not business_connection_id:
            mory_bot.reply_and_track(m, "⚠️ 未配置 TELEGRAM_BUSINESS_CONNECTION_ID，无法发送 Telegram 清单")
            return True
        checklist = checklist_cfg.get("checklist")
        if not checklist:
            title = str(checklist_cfg.get("title") or "Mory清单").strip()
            tasks = checklist_cfg.get("tasks", [])
            if isinstance(tasks, str):
                tasks = [item.strip() for item in tasks.split("|") if item.strip()]
            checklist = {
                "title": title,
                "tasks": [
                    {"id": idx + 1, "text": task}
                    for idx, task in enumerate(tasks)
                ],
            }
        if not checklist.get("tasks"):
            mory_bot.reply_and_track(m, "⚠️ 清单至少需要1个任务")
            return True
        send_checklist_compat(
            bot,
            business_connection_id,
            config["GROUP_ID"],
            checklist,
            message_effect_id=checklist_cfg.get("message_effect_id"),
            direct_messages_topic_id=checklist_cfg.get("direct_messages_topic_id"),
        )
        mory_bot.reply_and_track(m, "✅ Telegram 清单已发送。")
        logger.info(f"📋 新版清单：{checklist.get('title', '')}")
    except Exception as e:
        mory_bot.reply_and_track(m, f"⚠️ 清单发送失败：{e}")
    return True


def _handle_report(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 每日简报 / /report 命令"""
    chat_id = m.chat.id
    _send_report(bot, chat_id, config, db)
    return True


def _handle_rank(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 排行榜 命令"""
    chat_id = m.chat.id
    board = db.get_leaderboard(10)
    level_names = {1:"新人🌱", 2:"活跃⭐", 3:"VIP💎", 4:"至尊👑"}
    lines = ["🏆 积分排行榜\n"]
    for i, (uid_, name, pts, lv) in enumerate(board, 1):
        lines.append(f"{i}. {name}  {pts}分  {level_names.get(lv,'新人')}")
    bot.send_message(chat_id, "\n".join(lines) or "暂无数据")
    return True


def _handle_view_profile(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 查看画像 命令"""
    chat_id = m.chat.id
    # 解析用户ID
    target_id = None
    parts = msg.split()
    if len(parts) >= 2:
        # 支持 @用户名 或 直接数字ID
        id_str = parts[1].lstrip("@").strip()
        try:
            target_id = int(id_str)
        except ValueError:
            mory_bot.reply_and_track(m, "⚠️ 格式：查看画像 @用户ID 或 查看画像 用户数字ID")
            return True
    else:
        # 没有指定用户，展示最近活跃TOP5画像简报
        mory_bot.reply_and_track(m, "📊 正在生成最近活跃用户的画像简报...")
        profiles = db.get_all_user_profiles()[:5]
        if not profiles:
            bot.send_message(chat_id, "暂无用户数据。")
            return True
        all_lines = ["📋 用户画像简报（最近活跃TOP5）\n━━━━━━━━━━━━━━━━━━━\n"]
        level_names = {1: "新人🌱", 2: "活跃⭐", 3: "VIP💎", 4: "至尊👑"}
        for p in profiles:
            keywords = p["keywords"].replace(",", "、") if p["keywords"] else "暂无"
            fun = p["funnel"]
            status = "已转化" if fun["paid"] else ("咨询中" if fun["consulted"] else ("感兴趣" if fun["interested"] else "观察中"))
            all_lines.append(
                f"👤 {p['name']}(ID:{p['uid']})\n"
                f"   等级：{level_names.get(p['level'], '新人')} | 积分：{p['points']}\n"
                f"   活跃时段：{p['active_time']}\n"
                f"   偏好标签：{keywords}\n"
                f"   群消息：{p['group_messages']}条 | 私聊：{p['private_messages']}条\n"
                f"   转化状态：{status}\n"
            )
        bot.send_message(chat_id, "\n".join(all_lines))
        logger.info("📊 管理员查看了画像简报TOP5")
        return True

    # 查看指定用户画像
    profile = db.get_user_profile(target_id)
    if not profile:
        mory_bot.reply_and_track(m, f"⚠️ 未找到用户 {target_id} 的数据。")
        return True
    level_names = {1: "新人🌱", 2: "活跃⭐", 3: "VIP💎", 4: "至尊👑"}
    keywords = profile["keywords"].replace(",", "、") if profile["keywords"] else "暂无标签"
    fun = profile["funnel"]
    first_date = datetime.fromtimestamp(profile["first_seen"], _CST).strftime("%Y-%m-%d") if profile["first_seen"] else "未知"
    last_date = datetime.fromtimestamp(profile["last_active"], _CST).strftime("%Y-%m-%d %H:%M") if profile["last_active"] else "未知"

    # AI生成个性化营销建议
    suggest = ""
    if fun["interested"] and not fun["paid"]:
        suggest = "\n💡 建议：此用户已表现出购买意向，建议私聊重点推销「" + (
            "黑丝系列" if "黑丝" in keywords or "腿" in keywords
            else "视频内容" if "视频" in keywords
            else "声音内容" if "声音" in keywords
            else "至臻精选"
        ) + "」"

    profile_text = (
        f"📋 用户画像：{profile['name']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID：{profile['uid']}\n"
        f"🎖 等级：{level_names.get(profile['level'], '新人')} | 积分：{profile['points']}\n"
        f"📅 首次加入：{first_date}\n"
        f"🕐 最近活跃：{last_date}\n"
        f"⏰ 活跃时段：{profile['active_time']}\n\n"
        f"💬 消息统计\n"
        f"├─ 群消息：{profile['group_messages']} 条\n"
        f"└─ 私聊消息：{profile['private_messages']} 条\n\n"
        f"🏷 偏好标签：{keywords}\n\n"
        f"🛒 转化漏斗\n"
        f"├─ 接触：{'✅' if fun['touched'] else '❌'}\n"
        f"├─ 感兴趣：{'✅' if fun['interested'] else '❌'}\n"
        f"├─ 咨询：{'✅' if fun['consulted'] else '❌'}\n"
        f"└─ 已转化：{'✅' if fun['paid'] else '❌'}"
        f"{suggest}"
    )
    bot.send_message(chat_id, profile_text)
    logger.info(f"📊 管理员查看画像：{target_id}")
    return True


def _handle_switch_model(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 切换模型（手动）命令"""
    model_name = msg[5:].strip()
    pool = config.get("MODEL_POOLS", {}).get("llm", config.get("MODEL_POOL", []))
    names = [m_["name"] for m_ in pool]
    if model_name in names:
        idx = names.index(model_name)
        config["CURRENT_MODEL_INDEX"] = idx
        save_config_fn()
        ai.current_idx = idx
        mory_bot.reply_and_track(m, f"✅ 已切换到模型：{model_name}")
    else:
        mory_bot.reply_and_track(m, f"⚠️ 未找到该模型。可用：\n" + "\n".join(names))
    return True


def _handle_restore_model(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 模型恢复（从黑名单恢复被拉黑的模型）命令"""
    parts = msg.split()
    if len(parts) >= 2:
        model_name = parts[1]
        if ai._restore_model(model_name):
            save_config_fn()
            ai.current_idx = config.get("CURRENT_MODEL_INDEX", ai.current_idx)
            mory_bot.reply_and_track(m, f"✅ 模型 {model_name} 已从黑名单恢复，可正常使用")
        else:
            mory_bot.reply_and_track(m, f"⚠️ {model_name} 不在黑名单中")
    else:
        # 没指定模型，显示黑名单列表
        blacklisted = list(ai.blacklisted)
        if blacklisted:
            mory_bot.reply_and_track(m, f"🚫 被拉黑的模型：\n" + "\n".join(f"  {m}" for m in blacklisted) + "\n\n格式：模型恢复 [模型名]")
        else:
            mory_bot.reply_and_track(m, "✅ 当前没有被拉黑的模型")
    return True


def _handle_view_model(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 查看当前模型 命令"""
    chat_id = m.chat.id
    pool = config.get("MODEL_POOLS", {}).get("llm", config.get("MODEL_POOL", []))
    idx = config.get("CURRENT_MODEL_INDEX", 0)
    cur = pool[idx] if pool else {}
    blacklisted = getattr(ai, 'blacklisted', set())

    lines = [f"🤖 当前：{cur.get('name','未知')}  到期：{cur.get('expire','')}\n"]
    lines.append("📋 模型池：\n")
    for i, mod in enumerate(pool):
        name = mod.get("name", "?")
        expire = mod.get("expire", "?")
        mark = "→ " if i == idx else "   "
        banned = " 🚫拉黑" if name in blacklisted else ""
        lines.append(f"{mark}{i+1}. {name}  到期:{expire}{banned}")

    blacklisted_list = list(blacklisted) if blacklisted else []
    if blacklisted_list:
        lines.append(f"\n🚫 已拉黑：{', '.join(blacklisted_list)}")
        lines.append("💡 恢复指令：模型恢复 [模型名]")

    bot.send_message(chat_id, "\n".join(lines))
    return True


def _handle_health_check(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 健康检查（一键诊断Bot运行状态）命令"""
    lines = []
    lines.append("🏥 Mory健康检查报告")
    lines.append("━" * 20)
    pool = config.get("MODEL_POOLS", {}).get("llm", config.get("MODEL_POOL", []))
    idx = config.get("CURRENT_MODEL_INDEX", 0)
    cur = pool[idx] if pool else {}
    blacklisted = getattr(ai, 'blacklisted', set())
    cur_name = cur.get('name', '未知')
    lines.append(f"🧠 当前模型：{cur_name}")
    total_models = sum(len(v) for v in config.get("MODEL_POOLS", {}).values() if isinstance(v, list))
    bl_count = len(blacklisted)
    lines.append(f"📦 模型总数：{total_models}  🚫 黑名单：{bl_count}")
    if bl_count > 0:
        lines.append(f"   黑名单：{', '.join(list(blacklisted)[:5])}")
    reply_chance = config.get("REPLY_CHANCE", 10)
    lines.append(f"💬 回复概率：{reply_chance}%")
    auto_greeting = config.get("AUTO_GREETING", False)
    lines.append(f"🌅 早安问候：{'✅' if auto_greeting else '❌'}")
    spam_limit = config.get("SPAM_LIMIT", 5)
    lines.append(f"🛡️ 刷屏限制：{spam_limit}条")
    try:
        user_count = db.get_user_count() if hasattr(db, 'get_user_count') else '?'
        lines.append(f"👥 用户总数：{user_count}")
    except Exception as e:
        logger.warning(f"健康检查-用户总数查询失败: {e}")
    try:
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        today_tasks = 0
        if hasattr(db, 'conn'):
            try:
                row = db.conn.execute("SELECT COUNT(DISTINCT task_key) FROM task_log WHERE exec_date=?", (today,)).fetchone()
                today_tasks = row[0] if row else 0
            except Exception as e:
                logger.warning(f"健康检查-今日任务查询失败: {e}")
        lines.append(f"📋 今日任务：{today_tasks}项已完成")
    except Exception as e:
        logger.warning(f"健康检查-任务统计失败: {e}")
    lines.append("━" * 20)
    issues = []
    if bl_count > 3:
        issues.append("⚠️ 黑名单模型过多，建议恢复或更换")
    if not pool:
        issues.append("🔴 模型池为空！Bot无法回复")
    try:
        expire = cur.get('expire', '2099-12-31')
        from datetime import date as _date
        exp_d = _date.fromisoformat(expire)
        days_left = (exp_d - _date.today()).days
        if days_left <= 3:
            issues.append(f"🔴 当前模型{days_left}天后到期！")
        elif days_left <= 7:
            issues.append(f"⚠️ 当前模型{days_left}天后到期")
    except Exception as e:
        logger.warning(f"健康检查-模型到期检查失败: {e}")
    if reply_chance == 0:
        issues.append("⚠️ 回复概率为0，Bot不会主动回复")
    if not issues:
        lines.append("✅ 一切正常，Mory状态健康！")
    else:
        lines.append("发现问题：")
        for issue in issues:
            lines.append(issue)
    mory_bot.reply_and_track(m, "\n".join(lines))
    return True


def _handle_optimize_status(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 优化引擎诊断指令（v21.25+）"""
    from modules.optimizer_admin import handle_optimize_cmd
    handle_optimize_cmd(bot, mory_bot, m, ai, config)  # 【v4.3.2修复S-04】传入mory_bot
    return True


def _handle_blacklist(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 黑名单管理 命令"""
    try:
        target = int(msg.split()[1].lstrip("@"))
        db.blacklist_add(target, "管理员手动拉黑")
        mory_bot.reply_and_track(m, f"✅ 用户 {target} 已加入黑名单。")
    except (ValueError, IndexError):
        mory_bot.reply_and_track(m, "⚠️ 格式：/blacklist @用户ID")
    return True


def _handle_mute(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 禁言 命令"""
    chat_id = m.chat.id
    parts = msg.split()
    if len(parts) >= 3:
        try:
            target = int(parts[1].lstrip("@"))
            minutes = int(parts[2])
            db.mute_user(target, chat_id, minutes, "管理员禁言")
            # 尝试调用TG原生禁言（需要机器人是群管理员）
            try:
                from telebot.types import ChatPermissions
                until_date = int(__import__("time").time()) + minutes * 60
                bot.restrict_chat_member(chat_id, target,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until_date)
            except Exception as e:
                logger.warning(f"禁言操作失败 uid={target}：{e}")
            mory_bot.reply_and_track(m, f"✅ 已禁言用户 {target} {minutes} 分钟。")
        except (ValueError, IndexError):
            mory_bot.reply_and_track(m, "⚠️ 格式：/mute @用户ID 分钟数")
    return True


def _handle_clear_unreplied(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 清群无人理（立刻删掉群里所有无人互动的机器人消息）命令"""
    try:
        chat_id = m.chat.id
        bot_id = bot.get_me().id

        # 阶段一：清理追踪库中当前群的无人理消息（30分钟以上的才算「真正没人理」）
        rows = db.get_ignored_messages(min_age=1800)  # 30分钟门槛，避免误删刚发的
        deleted = 0
        failed = 0
        handled_ids = set()
        for bot_msg_id, cid, user_msg_id in rows:
            if cid != chat_id:
                continue
            handled_ids.add(bot_msg_id)
            try:
                bot.delete_message(cid, bot_msg_id)
                db.delete_tracked(bot_msg_id)
                deleted += 1
                logger.info(f"🧹 阶段一清理 bot_msg={bot_msg_id}")
            except Exception as e:
                failed += 1
                err_str = str(e).lower()
                if "not found" in err_str or "message to delete not found" in err_str or "message_id_invalid" in err_str:
                    db.delete_tracked(bot_msg_id)
                    failed -= 1
                else:
                    logger.warning(f"🧹 删除失败 bot={bot_msg_id}: {e}")

        # 阶段二：forward探测扫描机器人主动消息（非回复类型的）
        # 从管理员消息往前扫，最多扫1000条，遇到连续30条不存在时停止
        if chat_id < 0:
            try:
                admin_id = config.get("ADMIN_ID", 0)
                if not admin_id:
                    admin_id = m.from_user.id

                # 一次性获取追踪库中所有回复类型消息的bot_msg_id集合（避免N+1查询）
                all_tracked = db.get_all_tracked_messages(86400 * 3)
                reply_bot_ids = set()
                for t_bot, t_cid, t_user in all_tracked:
                    if t_cid == chat_id and t_user != 0:
                        reply_bot_ids.add(t_bot)

                scan_deleted = 0
                scan_total = 0
                not_found_streak = 0  # 连续不存在的计数
                MAX_SCAN = 1000
                MAX_STREAK = 30

                logger.info(f"🧹 阶段二开始扫描，最大扫描{MAX_SCAN}条，连续{MAX_STREAK}条不存在则停止")
                for offset in range(1, MAX_SCAN):
                    mid = m.message_id - offset
                    if mid <= 0:
                        break
                    if mid in handled_ids or mid in reply_bot_ids:
                        not_found_streak = 0
                        continue  # 已处理或是回复消息，跳过

                    try:
                        probe = bot.forward_message(admin_id, chat_id, mid,
                                                     disable_notification=True)
                        bot.delete_message(admin_id, probe.message_id)
                        not_found_streak = 0
                        scan_total += 1
                        if scan_total % 50 == 0:
                            logger.info(f"🧹 已扫描{scan_total}条，删除{scan_deleted}条")

                        # forward成功 + 机器人发的 = 机器人消息
                        if probe.from_user and probe.from_user.id == bot_id:
                            # 检查是否是回复消息（通过forward后的reply_to_message）
                            is_reply = (hasattr(probe, 'reply_to_message') and
                                        probe.reply_to_message is not None)

                            if not is_reply:
                                # 机器人主动消息（非回复），删除！
                                try:
                                    bot.delete_message(chat_id, mid)
                                    scan_deleted += 1
                                    logger.info(f"🧹 阶段二删除 bot_msg={mid} (offset={offset})")
                                except Exception as e:
                                    logger.debug(f"操作异常: {e}")
                    except Exception as fe:
                        err_str = str(fe).lower()
                        if any(k in err_str for k in ["not found", "message_id_invalid", "bad request"]):
                            not_found_streak += 1
                            if not_found_streak >= MAX_STREAK:
                                logger.info(f"🧹 连续{MAX_STREAK}条消息不存在，停止扫描 (offset={offset})")
                                break
                            continue
                        else:
                            logger.warning(f"🧹 扫描异常 offset={offset}: {fe}")
                            break

                deleted += scan_deleted
                logger.info(f"🧹 阶段二完成：扫描{scan_total}条，删除{scan_deleted}条机器人主动消息")
            except Exception as e:
                logger.error(f"🧹 阶段二失败：{e}")

        mory_bot.reply_and_track(m, f"🧹 已清理 {deleted} 条无人互动的消息"
                      f"{'，' + str(failed) + '条删除失败' if failed > 0 else ''}。")
        logger.info(f"🧹 清群无人理完成：删除{deleted}条，失败{failed}条")
    except Exception as e:
        mory_bot.reply_and_track(m, f"⚠️ 清理失败：{e}")
        logger.error(f"🧹 清群无人理失败：{e}")
    return True


def _handle_clear_all_replies(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 清全部回复（删掉群里所有机器人的回复，含已回复的）命令"""
    try:
        rows = db.get_all_tracked_messages(86400)  # 查最近24小时所有追踪记录
        logger.info(f"🧹 清全部回复：查询到 {len(rows)} 条追踪记录")
        deleted = 0
        failed = 0
        for bot_msg_id, cid, user_msg_id in rows:
            try:
                bot.delete_message(cid, bot_msg_id)
                db.delete_tracked(bot_msg_id)
                deleted += 1
            except Exception as e:
                failed += 1
                logger.warning(f"🧹 删除失败 bot={bot_msg_id}: {e}")
        mory_bot.reply_and_track(m, f"🧹 已清理 {deleted} 条机器人回复（最近24小时内）"
                          f"{'，' + str(failed) + '条已失效' if failed else ''}。"
                          f"（追踪库中共{len(rows)}条）")
    except Exception as e:
        mory_bot.reply_and_track(m, f"⚠️ 清理失败：{e}")
        logger.error(f"🧹 清全部回复失败：{e}")
    return True


def _handle_view_tracking(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 查追踪（调试阅后即焚）命令"""
    try:
        now = datetime.now(_CST).strftime("%m-%d %H:%M:%S")
        version = config.get("_CONFIG_VERSION", "?")

        # ── 实时写入测试：验证数据库 reply_tracking 表能正常读写 ──
        test_id = 888888888
        db.track_reply(test_id, -100000000, -100000001)
        test_rows = db.get_all_tracked_messages(60)
        test_ok = any(r[0] == test_id for r in test_rows)
        db.delete_tracked(test_id)
        db_test = "✅ 数据库读写正常" if test_ok else "❌ 数据库写入失败！"

        # ── 验证 monkey-patch 是否生效 ──
        try:
            patch_test = "✅ MoryBot 追踪正常" if hasattr(bot, '_mory_bot_instance') else "⚠️ MoryBot 未挂载"
        except Exception as e:
            logger.warning(f"健康检查-monkey-patch 检测失败: {e}")
            patch_test = "⚠️ 无法检测"

        # 用已有的方法查询
        all_rows = db.get_all_tracked_messages(86400 * 7)
        unreplied_rows = db.get_unreplied_messages()
        orphan_rows = db.get_orphan_messages()
        total = len(all_rows)
        unreplied = len(unreplied_rows)

        if total == 0:
            hint = "⚠️ 追踪为空！请在群里@机器人让它回复一条，然后回来查"
            if not test_ok:
                hint = "❌ 数据库reply_tracking表坏了，需要检查mory.db"
            elif "未生效" in patch_test:
                hint = "❌ bot.reply_to没有被patch，代码版本不对"
        elif unreplied == 0:
            hint = "所有消息都有人回复了（不会被删）"
        else:
            hint = "正常！后台每3分钟自动探测删除"

        mory_bot.reply_and_track(m,
            f"📊 阅后即焚诊断 [{now}] v{version}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"🧪 {db_test}\n"
            f"🧪 {patch_test}\n"
            f"📦 追踪总数（7天）：{total}\n"
            f"⏳ 无人回复：{unreplied}\n"
            f"🕳️ 孤儿（>24h）：{len(orphan_rows)}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"💡 {hint}"
        )
        logger.info(f"📊 查追踪：总数={total} 无人理={unreplied} 孤儿={len(orphan_rows)} db_test={test_ok} patch={patch_test}")
    except Exception as e:
        mory_bot.reply_and_track(m, f"⚠️ 查询失败：{e}")
        logger.error(f"📊 查追踪失败：{e}")
    return True


def _handle_add_hotwords(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 加热词：追加网络热词到STYLE_APPEND 命令"""
    new_words = msg[4:].strip()
    if new_words:
        # 确保已迁移到结构化字段
        _ensure_structured(config)
        style = config.get("STYLE_APPEND", "")
        if len(style) > 3000:
            mory_bot.reply_and_track(m, "⚠️ 风格追加已经很长了，请先用「进化 重置风格」清理一下再调教～")
            return True
        # 追加热词到风格区域
        new_section = f"\n- 热词库更新：{new_words}"
        config["STYLE_APPEND"] = style + new_section
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 热词已添加：「{new_words[:50]}{'...' if len(new_words)>50 else ''}」\n下次回复就会自然用上了～")
        logger.info(f"🔥 加热词：{new_words[:30]}")
    else:
        mory_bot.reply_and_track(m, "⚠️ 格式：加热词 [词汇1 词汇2 词汇3]")
    return True


def _handle_view_hotwords(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 查热词：查看当前热词库 命令"""
    chat_id = m.chat.id
    prompt = config.get("SYSTEM_PROMPT", "")
    import re as _re
    # 提取所有引号内的内容作为热词参考
    quoted = _re.findall(r'"([^"]+)"', prompt)
    hot_lines = [l for l in prompt.split("\n") if "热词" in l or "网感" in l or "梗" in l]
    result = f"🔥 当前热词/风格关键词\n━━━━━━━━━━━━\n"
    if hot_lines:
        result += "\n".join(f"  {l}" for l in hot_lines[:8])
    if quoted and len(quoted) > 5:
        result += f"\n\n📝 引用中的词汇（{min(len(quoted),30)}个）：\n"
        result += "  " + " / ".join(quoted[:30])
    result += f"\n━━━━━━━━━━━━\n💡 用「加热词 xxx」添加"
    bot.send_message(chat_id, result)
    return True


def _handle_change_style(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 改风格：快速调整说话风格 命令"""
    style_desc = msg[4:].strip()
    if style_desc:
        _ensure_structured(config)
        style = config.get("STYLE_APPEND", "")
        if len(style) > 3000:
            mory_bot.reply_and_track(m, "⚠️ 风格追加已经很长了，请先用「进化 重置风格」清理一下再调教～")
            return True
        style_instruction = f"\n【{datetime.now(_CST).strftime('%m/%d %H:%M')}风格调整】：从现在开始，说话风格调整为：{style_desc}。保持这个调整直到主人再次修改。"
        config["STYLE_APPEND"] = style + style_instruction
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 风格已调整为：「{style_desc[:40]}」\n下次对话立刻见效～")
        logger.info(f"🎨 改风格：{style_desc[:30]}")
    else:
        mory_bot.reply_and_track(m, "⚠️ 格式：改风格 [风格描述]\n例：改风格 更温柔知性\n例：改风格 更俏皮一点\n例：改风格 语气柔和但简洁")
    return True


def _handle_undo_teach(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 [Trae] 撤销调教：撤销最近一次人设调教 命令"""
    teaching_log = config.get("TEACHING_LOG", [])
    if not isinstance(teaching_log, list) or not teaching_log:
        mory_bot.reply_and_track(m, "⚠️ 没有调教记录可以撤销")
        return True
    removed = teaching_log.pop()
    style = config.get("STYLE_APPEND", "")
    lines = style.split("\n")
    new_lines = [l for l in lines if "调教指令" not in l or removed.split("] ", 1)[-1] not in l]
    config["STYLE_APPEND"] = "\n".join(new_lines).strip()
    config["TEACHING_LOG"] = teaching_log
    save_config_fn()
    mory_bot.reply_and_track(m, f"✅ 已撤销调教：{removed}")
    logger.info(f"↩️ 撤销调教：{removed}")
    return True


def _handle_view_teach_history(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 [Trae] 查看调教记录 命令"""
    teaching_log = config.get("TEACHING_LOG", [])
    if not isinstance(teaching_log, list) or not teaching_log:
        mory_bot.reply_and_track(m, "📋 暂无调教记录\n\n💡 可以直接用自然语言调教我，比如：\n• 以后对我温柔一点\n• 说话再撩一点\n• 别那么快回复")
        return True
    lines = ["📋 调教记录（最近20条）：", ""]
    for idx, entry in enumerate(teaching_log[-20:], 1):
        lines.append(f"{idx}. {entry}")
    lines.append("")
    lines.append("💡 发送「撤销调教」可撤销最近一条")
    mory_bot.reply_and_track(m, "\n".join(lines))
    return True


def _handle_learn(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 学知识：让机器人学习新知识（写入ADDED_KNOWLEDGE，不影响业务知识库）命令"""
    knowledge = msg.split(" ", 1)[1].strip() if " " in msg else ""
    if knowledge:
        _ensure_structured(config)
        added = config.get("ADDED_KNOWLEDGE", "")
        config["ADDED_KNOWLEDGE"] = added + "\n" + knowledge
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 已学会：「{knowledge[:60]}{'...' if len(knowledge)>60 else ''}」")
        logger.info(f"📚 学习新知识：{knowledge[:30]}")
    else:
        mory_bot.reply_and_track(m, "⚠️ 格式：学习 [知识内容]\n或：学知识 [知识内容]")
    return True


def _handle_forget(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 忘记：从追加知识中移除某内容 命令"""
    keyword = msg.split(" ", 1)[1].strip() if " " in msg else ""
    if keyword:
        removed_count = 0
        # 先搜索ADDED_KNOWLEDGE（追加知识）
        added = config.get("ADDED_KNOWLEDGE", "")
        if added:
            lines = added.split("\n")
            new_lines = [l for l in lines if keyword not in l]
            removed = len(lines) - len(new_lines)
            if removed > 0:
                config["ADDED_KNOWLEDGE"] = "\n".join(new_lines)
                removed_count += removed
        # 再搜索STYLE_APPEND（风格/热词）
        style = config.get("STYLE_APPEND", "")
        if style:
            lines = style.split("\n")
            new_lines = [l for l in lines if keyword not in l]
            removed = len(lines) - len(new_lines)
            if removed > 0:
                config["STYLE_APPEND"] = "\n".join(new_lines)
                removed_count += removed
        save_config_fn()
        if removed_count > 0:
            mory_bot.reply_and_track(m, f"✅ 已删除包含「{keyword}」的 {removed_count} 条内容")
        else:
            mory_bot.reply_and_track(m, f"⚠️ 没找到包含「{keyword}」的内容")
        logger.info(f"🗑️ 忘记知识：{keyword} (删除{removed_count}条)")
    else:
        mory_bot.reply_and_track(m, "⚠️ 格式：忘记 [关键词]\n例：忘记 VIP")
    return True


def _handle_evolve(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 进化：高级动态配置修改 命令"""
    chat_id = m.chat.id
    evo_cmd = msg[3:].strip()

    # 子命令解析
    if evo_cmd.startswith("概率"):
        # 进化概率 20
        parts = evo_cmd.split()
        if len(parts) >= 2:
            try:
                val = int(parts[-1])
                assert 0 <= val <= 100
                config["REPLY_CHANCE"] = val
                save_config_fn()
                mory_bot.reply_and_track(m, f"✅ 回复概率已改为 {val}%")
                logger.info(f"🧬 进化-概率: {val}%")
            except (ValueError, AssertionError):
                mory_bot.reply_and_track(m, "⚠️ 格式：进化概率 [0-100]")
        else:
            mory_bot.reply_and_track(m, f"当前回复概率：{config.get('REPLY_CHANCE', 10)}%\n格式：进化概率 [0-100]")
        return True

    if evo_cmd.startswith("模型"):
        # 进化模型 qwen3.7-max-preview
        parts = evo_cmd.split()
        if len(parts) >= 2:
            model_name = parts[1]
            pool = config.get("MODEL_POOLS", {}).get("llm", config.get("MODEL_POOL", []))
            names = [m["name"] for m in pool]
            if model_name in names:
                idx = names.index(model_name)
                config["CURRENT_MODEL_INDEX"] = idx
                save_config_fn()
                ai.current_idx = idx
                mory_bot.reply_and_track(m, f"✅ 已切换到：{model_name}")
                logger.info(f"🧬 进化-模型: {model_name}")
            else:
                mory_bot.reply_and_track(m, f"⚠️ 未找到该模型。可用：\n" + "\n".join(names))
        else:
            cur_idx = config.get("CURRENT_MODEL_INDEX", 0)
            pool = config.get("MODEL_POOLS", {}).get("llm", config.get("MODEL_POOL", []))
            cur_name = pool[cur_idx]["name"] if pool and cur_idx < len(pool) else "?"
            mory_bot.reply_and_track(m, f"当前模型：{cur_name}\n格式：进化模型 [模型名]")
        return True

    if evo_cmd == "重置人设":
        # 只重置风格追加和追加知识，不动核心人设和业务知识库
        config["STYLE_APPEND"] = ""
        config["ADDED_KNOWLEDGE"] = ""
        config.pop("SYSTEM_PROMPT", None)  # 清除旧字段
        save_config_fn()
        mory_bot.reply_and_track(m, "✅ 风格追加和追加知识已清空，核心人设保持不变")
        logger.info("🧬 进化-重置风格")
        return True

    if evo_cmd.startswith("重置风格"):
        # 只清空风格追加
        _ensure_structured(config)
        old_style = config.get("STYLE_APPEND", "")
        config["STYLE_APPEND"] = ""
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 风格追加已清空（共{len(old_style)}字），核心人设不变")
        logger.info("🧬 进化-重置风格")
        return True

    if evo_cmd.startswith("重置知识"):
        # 只清空追加知识
        _ensure_structured(config)
        old_added = config.get("ADDED_KNOWLEDGE", "")
        config["ADDED_KNOWLEDGE"] = ""
        save_config_fn()
        mory_bot.reply_and_track(m, f"✅ 追加知识已清空（共{len(old_added)}字），业务知识库不变")
        logger.info("🧬 进化-重置知识")
        return True

    if evo_cmd == "状态":
        ver = config.get("_CONFIG_VERSION", "?")
        cur_idx = config.get("CURRENT_MODEL_INDEX", 0)
        pool = config.get("MODEL_POOLS", {}).get("llm", config.get("MODEL_POOL", []))
        cur_model = pool[cur_idx]["name"] if pool and cur_idx < len(pool) else "?"
        reply_chance = config.get("REPLY_CHANCE", 10)
        persona_len = len(config.get("BASE_PERSONA", config.get("SYSTEM_PROMPT", "")))
        style_len = len(config.get("STYLE_APPEND", ""))
        added_len = len(config.get("ADDED_KNOWLEDGE", ""))
        know_len = len(config.get("KNOWLEDGE", ""))

        status = (
            f"🧬 Mory 进化状态面板 v{ver}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 当前模型：{cur_model}\n"
            f"🎲 回复概率：{reply_chance}%\n"
            f"📋 核心人设：{persona_len}字\n"
            f"🎨 风格追加：{style_len}字\n"
            f"📚 业务知识：{know_len}字\n"
            f"📝 追加知识：{added_len}字\n"
            f"🧠 模型池总数：{len(pool)}个\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"可用进化指令：\n"
            f"• 进化概率 [0-100]\n"
            f"• 进化模型 [名称]\n"
            f"• 加热词 [词汇]\n"
            f"• 改风格 [描述]\n"
            f"• 学习 [内容]\n"
            f"• 进化重置风格\n"
            f"• 进化重置知识\n"
            f"• 进化重置人设"
        )
        bot.send_message(chat_id, status)
        return True

    # 默认：把进化内容追加到STYLE_APPEND
    if evo_cmd:
        _ensure_structured(config)
        style = config.get("STYLE_APPEND", "")
        if len(style) > 3000:
            mory_bot.reply_and_track(m, "⚠️ 风格追加已经很长了，请先用「进化 重置风格」清理一下再调教～")
            return True
        evo_text = f"\n【进化指令-{datetime.now(_CST).strftime('%m/%d %H:%M')}】：{evo_cmd}"
        config["STYLE_APPEND"] = style + evo_text
        save_config_fn()
        mory_bot.reply_and_track(m, f"🧬 已进化：「{evo_cmd[:60]}{'...' if len(evo_cmd)>60 else ''}」\n下次对话立刻生效")
        logger.info(f"🧬 进化-自定义: {evo_cmd[:30]}")
    else:
        mory_bot.reply_and_track(
            m,
            "🧬 动态进化系统\n"
            "━━━━━━━━━━━━━━\n"
            "• 加热词 [词汇] — 添加热词\n"
            "• 查热词 — 查看热词库\n"
            "• 改风格 [描述] — 调整风格\n"
            "• 学习 [内容] — 学习新知识\n"
            "• 忘记 [关键词] — 删除内容\n"
            "• 进化概率 [N] — 改回复率\n"
            "• 进化模型 [名] — 切模型\n"
            "• 进化状态 — 查看状态\n"
            "• 进化重置风格 — 清空风格追加\n"
            "• 进化重置知识 — 清空追加知识\n"
            "• 进化重置人设 — 清空风格+知识\n"
            "• 进化 [任意文本] — 追加到风格"
        )
    return True


def _handle_reload_config(bot, mory_bot, m, config: dict, db, ai, save_config_fn, msg: str) -> bool:
    """处理 【v4.3.0新增】热更新配置 命令"""
    try:
        # 重新读取config.json文件
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            new_config = normalize_runtime_config(json.load(f))

        # 更新config（保留内存中已修改的动态字段）
        preserved_keys = ["CURRENT_MODEL_INDEX", "_LAST_LEAK_WEEK", "_POOL_INDICES"]
        for key in preserved_keys:
            if key in config:
                new_config[key] = config[key]

        config.clear()
        config.update(new_config)

        mory_bot.reply_and_track(m, "✅ 配置热更新成功！\n\n📝 以下配置已重新加载：\n• 人设和知识库\n• 回复概率\n• 开关设置\n• 模型池配置\n\n💡 动态状态已保留，无需重启。")
        logger.info("📝 管理员触发配置热更新")
    except Exception as e:
        mory_bot.reply_and_track(m, f"⚠️ 热更新失败：{e}")
        logger.error(f"热更新失败：{e}")
    return True


# ════════════════════════════════════════════════════════════════════════
# 路由表
# ════════════════════════════════════════════════════════════════════════

# 公开指令（任何人可用，权限检查前执行）
_PUBLIC_HANDLERS = [
    (lambda msg: msg.strip() == "绑定主人", _handle_bind_master),
    (lambda msg: msg.strip() == "添加管理员", _handle_add_admin),
    (lambda msg: msg.strip() in ("查看管理员", "管理员列表", "管理员"), _handle_view_admins),
]

# 主人指令（需要 admin 权限，权限检查后执行）
_ADMIN_HANDLERS = [
    (lambda msg: msg.startswith("设置人设 "), _handle_set_persona),
    (lambda msg: msg in ("查看人设", "查看设定", "看人设"), _handle_view_persona),
    (lambda msg: msg.startswith("投喂资料 "), _handle_feed_knowledge),
    (lambda msg: msg.startswith("/投喂文件") or msg.startswith("投喂文件"), _handle_feed_style_file),
    (lambda msg: msg.startswith("/投喂") or msg.startswith("投喂样本") or msg.startswith("投喂 "), _handle_feed_style_sample),
    (lambda msg: msg in ("查看资料", "查看知识库", "看资料", "看知识库"), _handle_view_knowledge),
    (lambda msg: msg in ("清空资料", "清空知识库", "重置资料"), _handle_clear_knowledge),
    (lambda msg: msg.startswith("设置概率 "), _handle_set_rate),
    (lambda msg: msg in ("查看配置", "查看设置", "看配置", "查看状态"), _handle_view_config),
    (lambda msg: msg.startswith("代发 @"), _handle_send_to_user),
    (lambda msg: msg.startswith("代发群 "), _handle_send_to_group),
    (lambda msg: msg.startswith("代发频道 "), _handle_send_to_channel),
    (lambda msg: msg.startswith("投票 "), _handle_poll),
    (lambda msg: msg.startswith("清单 "), _handle_checklist),
    (lambda msg: msg in ("每日简报", "/report"), _handle_report),
    (lambda msg: msg in ("排行榜", "/rank"), _handle_rank),
    (lambda msg: msg.startswith("查看画像"), _handle_view_profile),
    (lambda msg: msg.startswith("切换模型 "), _handle_switch_model),
    (lambda msg: msg.startswith("模型恢复"), _handle_restore_model),
    (lambda msg: msg in ("当前模型", "/model"), _handle_view_model),
    (lambda msg: msg in ("健康检查", "/健康检查", "/health"), _handle_health_check),
    (lambda msg: msg.startswith(("/optimize_status", "/opt_status", "/os",
                                  "/optimize_cache", "/oc",
                                  "/optimize_reset", "/or")), _handle_optimize_status),
    (lambda msg: msg.startswith("/blacklist "), _handle_blacklist),
    (lambda msg: msg.startswith("/mute "), _handle_mute),
    (lambda msg: "清群无人理" in msg or "清掉没人理你" in msg or "删掉没人理你回复的消息" in msg, _handle_clear_unreplied),
    (lambda msg: "清全部回复" in msg or "删掉你回复的消息" in msg, _handle_clear_all_replies),
    (lambda msg: "查追踪" in msg or "查阅后" in msg, _handle_view_tracking),
    (lambda msg: msg.startswith("加热词 "), _handle_add_hotwords),
    (lambda msg: msg in ("查热词", "看热词", "热词库"), _handle_view_hotwords),
    (lambda msg: msg.startswith("改风格 "), _handle_change_style),
    (lambda msg: msg in ("撤销调教", "撤销上次调教", "撤回调教"), _handle_undo_teach),
    (lambda msg: msg in ("查看调教", "调教记录", "看调教"), _handle_view_teach_history),
    (lambda msg: msg.startswith("学习 ") or msg.startswith("学知识 "), _handle_learn),
    (lambda msg: msg.startswith("忘记 ") or msg.startswith("删除知识 "), _handle_forget),
    (lambda msg: msg.startswith("进化 "), _handle_evolve),
    (lambda msg: msg.strip() in ("热更新", "重载配置", "reload", "/reload"), _handle_reload_config),
]


def handle_admin(bot, mory_bot, m, config: dict, db, ai, save_config_fn) -> bool:
    """
    处理管理员专属指令。
    返回 True 表示已消费该消息，主分发器不再继续处理。

    注意：此函数在私聊和群聊中都会执行。
    私聊时所有指令可用；群聊时也可用（防止主人@机器人发指令）。
    """
    msg = m.text or ""
    uid = m.from_user.id

    # ── 【v21.38 权限检查】自然语言指令需要管理员权限 ─────────────────────
    # 先执行权限检查，确保只有管理员能修改配置
    is_admin = is_admin_user(config, uid)

    # 所有用户都能查看帮助指令，但只有管理员能修改配置
    if handle_natural_admin(bot, m, config, save_config_fn, mory_bot=mory_bot, is_admin=is_admin):
        return True

    # ── 以下为公开指令（任何人可用）────────────────────────────────────
    for matcher, handler in _PUBLIC_HANDLERS:
        if matcher(msg):
            if handler(bot, mory_bot, m, config, db, ai, save_config_fn, msg):
                return True

    # ── 以下所有指令只允许主人执行 ────────────────────────────────────────
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if isinstance(admin_ids, int):
        admin_ids = [admin_ids]
    if not isinstance(admin_ids, list):
        admin_ids = []
    # 向下兼容：如果只有ADMIN_ID没有ADMIN_IDS，也加入
    if admin_id and admin_id not in admin_ids:
        admin_ids.append(admin_id)
    if uid not in admin_ids:
        return False

    # ── 主人指令路由 ────────────────────────────────────────────────────
    for matcher, handler in _ADMIN_HANDLERS:
        if matcher(msg):
            if handler(bot, mory_bot, m, config, db, ai, save_config_fn, msg):
                return True

    return False


def _ensure_structured(config: dict):
    """确保config已迁移到结构化人设字段（兼容旧SYSTEM_PROMPT）"""
    if "BASE_PERSONA" not in config and "SYSTEM_PROMPT" in config:
        config["BASE_PERSONA"] = config.pop("SYSTEM_PROMPT")
        config["STYLE_APPEND"] = ""
        config["ADDED_KNOWLEDGE"] = ""


def _send_report(bot, chat_id: int, config: dict, db):
    """生成并发送每日运营简报"""
    data = db.get_daily_report()
    funnel = data["funnel"] or (0, 0, 0, 0)
    top5_lines = "\n".join(
        [f"  {i+1}. {name} — {pts}分" for i, (uid, name, pts, lv) in enumerate(data["top5"])]
    ) or "  暂无"

    conv_rate = 0
    if funnel[0] and funnel[0] > 0:
        conv_rate = round((funnel[3] or 0) / funnel[0] * 100, 1)

    cur_model = ""
    pool = config.get("MODEL_POOLS", {}).get("llm", config.get("MODEL_POOL", []))
    idx = config.get("CURRENT_MODEL_INDEX", 0)
    if pool and idx < len(pool):
        cur_model = pool[idx].get("name", "N/A")

    report = (
        f"╔═══════════════════════════════════╗\n"
        f"║  📊 {config['BOT_NAME']} 私域运营日报\n"
        f"║  {datetime.now(_CST).strftime('%Y-%m-%d %H:%M')}\n"
        f"╚═══════════════════════════════════╝\n"
        f"\n"
        f"👥 人员概览\n"
        f"├─ 24h活跃：{data['active']} 人\n"
        f"├─ 新增用户：{data['new_users']} 人\n"
        f"└─ 累计用户：{data['total']} 人\n"
        f"\n"
        f"🛒 转化漏斗\n"
        f"├─ 接触：{funnel[0]} 人\n"
        f"├─ 感兴趣：{funnel[1]} 人\n"
        f"├─ 咨询：{funnel[2]} 人\n"
        f"├─ 已转化：{funnel[3]} 人\n"
        f"└─ 转化率：{conv_rate}%\n"
        f"\n"
        f"🏆 积分TOP5\n"
        f"{top5_lines}\n"
        f"\n"
        f"🖤 黑名单：{data['blacklist']} 人\n"
        f"🤖 当前模型：{cur_model}"
    )

    bot.send_message(chat_id, report)
    logger.info("📊 简报已发送")
