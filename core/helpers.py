def can_delete_message(config):
    """检查全局消息删除开关是否启用

    ENABLE_MESSAGE_DELETION 控制所有自动消息删除行为：
    - 夜间模式删除、广告检测删除、慢速模式删除、消息锁删除等
    - 不影响管理员手动命令（如 /del, /purge, /scan）
    - 不影响 Bot 自身消息的清理

    Args:
        config: 配置字典

    Returns:
        bool: True 表示允许自动删除消息
    """
    return config.get('ENABLE_MESSAGE_DELETION', False)


def can_orphan_cleanup(config):
    """[v5.12.4] 独立判断：是否启用孤儿消息清理

    与 can_delete_message 完全独立：
    - 孤儿清理（Bot主动消息 + 用户触发Bot回复无人理）→ ORPHAN_CLEANUP_ENABLED
    - 全局消息删除（夜间/广告/慢速等）→ ENABLE_MESSAGE_DELETION

    设计原因：用户希望孤儿消息清理独立可控，不受全局消息删除开关影响。
    默认开启（破例），防止大量孤儿消息堆积在群中。

    Args:
        config: 配置字典

    Returns:
        bool: True 表示允许孤儿清理
    """
    return config.get('ORPHAN_CLEANUP_ENABLED', True)


def get_broadcast_auto_delete_config(config):
    """[Trae CN] 读取孤儿播报自动删除配置

    Args:
        config: 配置字典

    Returns:
        dict: {
            "orphan_seconds": int,           # 孤儿播报（升级/独立播报）N秒后自动删除，0=不删
            "greeting_chain_delete": bool    # 早安/午安/晚安是否互删（发新删旧）
        }
    """
    cfg = config.get("BROADCAST_AUTO_DELETE", {}) or {}
    return {
        "orphan_seconds": int(cfg.get("orphan_seconds", 30) or 0),
        "greeting_chain_delete": bool(cfg.get("greeting_chain_delete", True)),
    }


def safe_delete_broadcast(bot, chat_id, msg_id, label: str = "broadcast"):
    """[Trae CN] 安全删除一条孤儿播报消息（带全局开关检查 + 异常吞咽）

    与 can_delete_message 配合：全局开关关闭时直接跳过，不抛错。
    用于：
    - 升级消息 30S 后自动删除
    - 早安/午安/晚安 链式互删

    Args:
        bot: Telebot实例
        chat_id: 群ID
        msg_id: 消息ID
        label: 日志标签（如 "level_up" / "greeting_morning"）

    Returns:
        bool: True 表示成功删除，False 表示跳过/失败
    """
    try:
        bot.delete_message(chat_id, msg_id)
        return True
    except Exception as e:
        from core.logging_util import get_logger
        get_logger("broadcast_auto_delete").debug(
            f"⏭️ 孤儿播报删除失败（可能已被删/权限不足）[{label}]: chat={chat_id} msg={msg_id} err={e}"
        )
        return False


def format_user_mention(uid, name):
    """生成统一的用户可点击提及链接（HTML格式）

    所有管理员通知统一使用此函数，确保：
    1. 用户名可点击（tg://user 链接），点击即可打开与该用户的对话
    2. HTML 特殊字符正确转义
    3. 名称截断防止过长
    4. 后附纯文本 ID 方便复制

    Args:
        uid: 用户ID（整数）
        name: 用户名（字符串）

    Returns:
        str: HTML格式的可点击用户链接 + ID后缀
             例: '<a href="tg://user?id=123456">张三</a> ID: 123456'
    """
    if not name:
        name = "未知用户"
    # HTML转义（顺序重要：&先转义）
    safe_name = str(name).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:30]
    return f'<a href="tg://user?id={uid}">{safe_name}</a> ID: {uid}'
