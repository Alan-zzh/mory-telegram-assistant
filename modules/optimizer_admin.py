"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/optimizer_admin.py  ·  优化引擎管理员指令                     ║
║                                                                        ║
║  提供3个 Telegram 管理员指令，查看/管理优化引擎状态：                  ║
║    /optimize_status   — 完整诊断报告（熔断+缓存+限流）                ║
║    /optimize_cache    — 缓存命中率统计                                ║
║    /optimize_reset    — 手动重置指定模型熔断器                        ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import logging

logger = logging.getLogger("optimizer_admin")


def handle_optimize_cmd(bot, message, ai_engine, config: dict):
    """
    处理优化相关管理员指令。
    由 admin_cmds.py 调用，返回 True 表示已处理。
    
    指令格式：
      /optimize_status          — 完整报告
      /optimize_status cache    — 只看缓存
      /optimize_status circuit  — 只看熔断器  
      /optimize_status limiter  — 只看令牌桶
      /optimize_cache           — 缓存详情
      /optimize_reset 模型名    — 重置熔断器
    """
    from core.ai_engine import _get_optimizer
    
    msg_text = (message.text or "").strip()
    parts = msg_text.split()
    cmd = parts[0] if parts else ""
    arg = parts[1] if len(parts) > 1 else ""
    
    # 获取优化器实例
    try:
        opt = _get_optimizer()
        if not opt or not opt.enabled:
            mory_bot.reply_and_track(message, "⚡ 优化引擎未启用或初始化失败")
            return True
    except Exception as e:
        mory_bot.reply_and_track(message, f"⚠️ 优化引擎异常：{e}")
        return True
    
    # ════ /optimize_status ════════════════════════════════
    if cmd in ("/optimize_status", "/opt_status", "/os"):
        report = opt.get_full_report()
        
        if arg == "cache":
            # 只展示缓存信息
            s = report["cache"]
            text = (
                f"📦 **语义缓存状态**\n\n"
                f"缓存条数：{s['total_entries']}/{s['max_entries']}\n"
                f"TTL有效期：{s['ttl_seconds']}秒（{s['ttl_seconds']//60}分钟）\n"
                f"命中次数：{s['hits']}\n"
                f"未命中：{s['misses']}\n"
                f"命中率：{s['hit_rate']*100:.1f}%\n\n"
            )
            if s["by_mode"]:
                mode_lines = "\n".join(f"  {m}: {c}条" for m, c in s["by_mode"].items())
                text += f"**按模式分布：**\n{mode_lines}"
            else:
                text += "（暂无缓存数据）"
            
        elif arg == "circuit":
            # 只展示熔断器信息
            circuits = report["circuit_breaker"]
            if not circuits:
                text = "🔧 **熔断器状态**\n\n所有模型正常，无熔断记录。"
            else:
                lines = ["🔧 **熔断器状态**\n"]
                for name, info in circuits.items():
                    state_icon = {"closed": "✅", "open": "🔴", "half_open": "🟡"}
                    icon = state_icon.get(info["state"], "❓")
                    lines.append(
                        f"{icon} `{name}` — 状态:{info['state']}"
                        f" | 连续失败:{info['fail_count']}次"
                    )
                text = "\n".join(lines)
                
        elif arg == "limiter":
            # 只展示令牌桶
            s = report["rate_limiter"]
            text = (
                f"🪙 **令牌桶限流**\n\n"
                f"可用令牌：{s['available_tokens']}/{s['capacity']}\n"
                f"补充速率：{s['refill_per_sec']}个/秒\n"
                f"总通过：{s['total_acquired']}次\n"
                f"总拒绝：{s['total_rejected']}次"
            )
            
        else:
            # 完整报告（默认）
            c = report["cache"]
            cb_items = report["circuit_breaker"]
            r = report["rate_limiter"]
            
            open_count = sum(1 for v in cb_items.values() if v["state"] == "open")
            half_count = sum(1 for v in cb_items.values() if v["state"] == "half_open")
            
            text = (
                f"⚡ **Mory 优化引擎诊断报告**\n"
                f"`{report['timestamp']}`\n\n"
                f"📦 **语义缓存**\n"
                f"  条数: {c['total_entries']}/{c['max_entries']} | "
                f"命中率: {c['hit_rate']*100:.1f}% | "
                f"命中: {c['hits']}/未命: {c['misses']}\n\n"
                f"🔧 **熔断器**\n"
                f"  正常: {len(cb_items)-open_count-half_count} | "
                f"熔断中: {open_count} | 试探中: {half_count}\n\n"
                f"🪙 **令牌桶**\n"
                f"  令牌: {r['available_tokens']:.1f}/{r['capacity']} | "
                f"通过: {r['total_acquired']} | "
                f"拒绝: {r['total_rejected']}"
            )
        
        mory_bot.reply_and_track(message, text)
        return True
    
    # ════ /optimize_cache ════════════════════════════════
    elif cmd in ("/optimize_cache", "/oc"):
        if arg and arg.lower() in ("clear", "clean", "reset", "清空", "清除"):
            count = opt.cache.invalidate()
            mory_bot.reply_and_track(message, f"🗑️ 已清除全部缓存（{count}条）")
            return True
        
        stats = opt.cache.get_stats()
        text = (
            f"📦 **语义缓存详情**\n\n"
            f"当前条数：{stats['total_entries']} / {stats['max_entries']}\n"
            f"TTL有效期：{stats['ttl_seconds']}秒\n"
            f"━━━━━━━━━━━━━━━\n"
            f"命中：{stats['hits']}次\n"
            f"未命中：{stats['misses']}次\n"
            f"命中率：{stats['hit_rate']*100:.1f}%\n"
            f"━━━━━━━━━━━━━━━\n"
        )
        
        if stats["by_mode"]:
            text += "**按模式分布：**\n"
            for mode, count in sorted(stats["by_mode"].items(), key=lambda x: -x[1]):
                text += f"  • {mode}: {count}条\n"
        else:
            text += "\n_暂无缓存数据，等待AI调用后自动积累_\n"
        
        text += "\n💡 提示：用 `/optimize_cache clear` 可手动清空缓存"
        mory_bot.reply_and_track(message, text)
        return True
    
    # ════ /optimize_reset ════════════════════════════════
    elif cmd in ("/optimize_reset", "/or"):
        if not arg:
            # 列出所有被熔断的模型供选择
            all_status = opt.circuit.get_all_status()
            broken = [name for name, info in all_status.items() 
                      if info["state"] in ("open", "half_open")]
            if not broken:
                mory_bot.reply_and_track(message, "✅ 当前没有模型处于熔断状态，无需重置。")
            else:
                lines = ["🔴 **以下模型已被熔断：**\n"]
                for name in broken:
                    info = opt.circuit.get_status(name)
                    lines.append(f"• `{name}` — 连续失败{info['fail_count']}次\n"
                               f"  用 `/optimize_reset {name}` 重置")
                mory_bot.reply_and_track(message, "\n".join(lines))
            return True
        
        # 重置指定模型
        model_name = arg
        if opt.circuit.reset(model_name):
            mory_bot.reply_and_track(message, f"✅ 熔断器已重置：`{model_name}`\n该模型将恢复正常使用。")
        else:
            mory_bot.reply_and_track(message, f"ℹ️ `{model_name}` 不在熔断记录中，无需重置。")
        return True
    
    return False
