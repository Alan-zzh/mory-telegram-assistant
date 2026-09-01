#!/usr/bin/env python3
"""配置三处同步差集断言脚本（阶段 4 步骤 20）。

检查三处同步关系（AGENTS.md 配置同步规则）：
  config.json.example 顶层键  ↔  dashboard/api/config_api.py ALLOWED_CONFIG_FIELDS（含 natural_cmd ALL_CONFIGS update）
断言 a：example 非敏感业务键 ⊆ 白名单（敏感键 / 元键 / EXEMPT_KEYS 显式豁免）
断言 b：白名单中无 example 不存在的幽灵键
不一致则退出码 1（供 CI / pre-commit 断言）；一致则退出码 0。

用法：
    python scripts/check_config_sync.py
"""
from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config_compat import NESTED_CONFIG_PSEUDO_FIELDS, REMOVED_CONFIG_FIELDS

CONFIG_EXAMPLE = ROOT / "config.json.example"
CONFIG_API = ROOT / "dashboard" / "api" / "config_api.py"
NATURAL_CMD = ROOT / "modules" / "natural_cmd.py"

# 敏感键豁免标记：键名（大写后）含 TOKEN / API_KEY / SECRET / PASSWORD / KEY 的
# 视为敏感键，允许不在白名单（保持只读，防 Dashboard 端篡改凭据）。
# 注意：ADMIN_IDS、ADMIN_ID、GROUP_ID 等业务键不含上述子串，不在豁免范围。
_SENSITIVE_MARKERS = ("TOKEN", "API_KEY", "SECRET", "PASSWORD", "KEY")

# 显式豁免清单（脚本内常量，逐项注明理由）：
# 1) example 中存在、但无 UI 修改需求、保持只读的业务键；
# 2) 白名单历史遗留键（example 未收录、代码实际使用，保持白名单合法）。
# 禁止为了凑脚本通过而全量扩白名单（安全面）。
EXEMPT_KEYS = {
    # ── 白名单历史遗留键：example 未收录，代码实际使用（config.get 默认），保持白名单合法 ──
    "AD_RULES",  # ad_detector 广告自定义规则
    "ANTI_TEMPLATES",  # ai_engine 人设引擎反模板
    "EMOTION_BUCKETS",  # ai_engine 情绪桶
    "EMOTION_TEMP_MAP",  # ai_engine 动态 LLM 参数映射
    "EMOTION_TRIGGERS",  # ai_engine 情绪触发器
    "MODE_ROUTING",  # ai_engine 三层智能路由
    # ── 无 UI 修改需求，保持只读：A/B 测试与增长由 ab_test_api 独立管理 ──
    "AB_TEST_CONFIG", "AB_TEST_ENABLED", "AB_TEST_GROUP_A_MODEL", "AB_TEST_GROUP_B_MODEL",
    "GROWTH_AB_SPLIT", "GROWTH_OPTIMIZER_ENABLED",
    # ── 管理员/群组 ID：由群管/权限 API 管理，不经通用白名单 ──
    "ADMIN_ID", "ADMIN_IDS", "GROUP_ID", "CHANNEL_IDS",
    # ── 模型/路由内部子配置：models_api / bot_routing_api 独立管理，无通用 UI 修改需求 ──
    "MODEL_POOL_LIGHT", "MODEL_POOL_PREMIUM", "MODEL_POOL_STANDARD",
    "MODEL_ROUTER_ENABLED", "MODEL_ROUTER_OVERRIDE",
    "BOT_ROUTING_ENABLED", "BOT_ROUTING_DEFAULT_POLICY",
    "BLACKLISTED_MODELS", "BLACKLISTED_MODELS_TS", "BASE_URL", "HTTP_CLIENT_CONFIG", "RETRY_CONFIG",
    # ── 成本/限流/运维参数：内部调优，无 UI 修改需求 ──
    "LLM_COST_GUARD_ENABLED", "LLM_COST_USER_HOURLY_LIMIT", "LLM_COST_GLOBAL_HOURLY_LIMIT",
    "LLM_COST_USER_DAILY_LIMIT", "LLM_COST_GLOBAL_DAILY_LIMIT",
    "RATE_LIMIT_USER", "RATE_LIMIT_CHAT", "LOG_RETENTION_DAYS", "DAILY_BACKUP_ENABLED",
    # ── 质量评估/链路追踪/归因/回复演化：由专门 API 或内部管理 ──
    "QUALITY_EVAL_ENABLED", "QUALITY_EVAL_SAMPLE_RATE", "QUALITY_EVAL_DAILY_LIMIT",
    "TRACING_ENABLED", "TRACING_SAMPLE_RATE", "TRACING_SERVICE_NAME", "TRACING_BATCH_MODE",
    "ATTRIBUTION_REPORT_ENABLED", "ATTRIBUTION_MODEL",
    "REPLY_EVOLUTION_CONFIG", "REPLY_CONTRACT_VERSION",
    # ── 人设/提示词内部维护片段：已有 BASE_PERSONA/SYSTEM_PROMPT 等可改，子结构保持只读 ──
    "PERSONA_FRAGMENTS", "FEW_SHOT_EXAMPLES", "STYLE_APPEND", "ADDED_KNOWLEDGE",
    # ── 积分/商城/等级/娱乐模块：群管模块内部 API 管理，无通用 UI 修改需求 ──
    "SHOP_CONFIG", "COUPON_CONFIG", "TIP_CONFIG", "LOTTERY_CONFIG", "LUCKY_WHEEL_CONFIG",
    "REDPACKET_CONFIG", "BLIND_BOX_CONFIG", "DAILY_QUEST_CONFIG", "ACHIEVEMENT_CONFIG",
    "LEVEL_PRIVILEGES", "LEVEL_THRESHOLDS", "LEVEL_TITLES", "POINTS_DECAY", "POINTS_RULES",
    "GAMES_CONFIG", "AFK_CONFIG",
    # ── 群管规则只读（保持默认或由群管 API 管理）：WARNING/VOTEKICK/REPORT/防刷/验证等 ──
    "WARNING_CONFIG", "VOTEKICK_CONFIG", "REPORT_CONFIG", "SLOW_MODE_DEFAULT", "ANTIFLOOD_CONFIG",
    "AUTO_KICK_INACTIVE_DAYS", "AUTO_MUTE_NAMES", "MESSAGE_LOCKS", "NIGHT_MODE_CONFIG",
    "VERIFICATION_CONFIG", "EDIT_DETECT_ENABLE", "EMOJI_MASK_DETECT", "ANTI_DELETE_CONFIG",
    "AD_EXEMPT_CHANNEL_FORWARDS", "AD_CLEANUP_REACTIONS", "AD_DETECT_CONFIG",
    "SPAM_ACTION", "SPAM_WATCH_CONFIG", "NSFW_DETECT_CONFIG",
    "AUTO_REPLY_ENABLE", "RULES_ENABLE", "RULES_TEXT", "GOODBYE_MSG", "GOODBYE_TEXT",
    "WELCOME_CLEAN", "CLEAN_SERVICE_DEFAULT", "VISUAL_DASHBOARD_ENABLE", "EXCHANGE_RATE_ENABLE",
    "ENABLE_VISION_REPLY", "VISION_REPLY_RATE", "VOICE_POOL",
    "NIGHT_HINT_NEUTRAL_REMINDER_ENABLED", "RETROACTIVE_SCAN_ENABLED", "RETROACTIVE_SCAN_RANGE",
    "TELEGRAM_ALLOWED_UPDATES", "TELEGRAM_BUSINESS_CONNECTION_ID",
    "RBAC_APPROVAL_ENABLED", "RBAC_AUDIT_DAY_OF_MONTH", "CART_RECOVERY_CONFIG",
}


def load_example_keys() -> set[str]:
    """读取 config.json.example 顶层键集合。"""
    data = json.loads(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
    return set(data.keys())


def _parse_config_api_whitelist(text: str) -> set[str]:
    """正则退化：解析 config_api.py 中 ALLOWED_CONFIG_FIELDS 集合字面量的字符串键。"""
    keys: set[str] = set()
    m = re.search(r"ALLOWED_CONFIG_FIELDS\s*=\s*\{(.*?)\n\}", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            keys.update(re.findall(r'"([^"]+)"', line))
    return keys


def _parse_natural_cmd_all_configs(text: str) -> set[str]:
    """正则退化：解析 natural_cmd.py 中 ALL_CONFIGS 字典键。"""
    keys: set[str] = set()
    m = re.search(r"ALL_CONFIGS\s*=\s*\{(.*?)\n\}", text, re.S)
    if m:
        keys.update(re.findall(r'^\s*"([^"]+)"\s*:', m.group(1), re.M))
    return keys


def load_whitelist() -> tuple[set[str], set[str], str]:
    """加载白名单键集合。

    首选 importlib 加载 dashboard.api.config_api（会触发 flask blueprint 创建，
    可接受），直接取 ALLOWED_CONFIG_FIELDS（已含 ALL_CONFIGS.keys() 的 update）；
    失败则退化为正则解析文件文本提取白名单键，两种方式均保证稳定。
    同时返回 ALL_CONFIGS 声明键集合（natural_cmd 自然语言可配置清单，用于幽灵键判定）。
    """
    try:
        mod = importlib.import_module("dashboard.api.config_api")
        all_configs = set(importlib.import_module("modules.natural_cmd").ALL_CONFIGS.keys())
        return set(mod.ALLOWED_CONFIG_FIELDS), all_configs, "importlib(dashboard.api.config_api)"
    except Exception as exc:  # noqa: BLE001 - 退化路径需兜底
        print(f"[warn] importlib 加载 config_api 失败（{exc}），退化为正则解析")

    keys: set[str] = set()
    all_configs: set[str] = set()
    if CONFIG_API.exists():
        text = CONFIG_API.read_text(encoding="utf-8", errors="ignore")
        keys |= _parse_config_api_whitelist(text)
        # 集合字面量之外的 update(ALL_CONFIGS.keys()) 需补充 natural_cmd 的键
        if "ALLOWED_CONFIG_FIELDS.update(ALL_CONFIGS.keys())" in text:
            try:
                all_configs = set(importlib.import_module("modules.natural_cmd").ALL_CONFIGS.keys())
            except Exception:
                if NATURAL_CMD.exists():
                    all_configs = _parse_natural_cmd_all_configs(
                        NATURAL_CMD.read_text(encoding="utf-8", errors="ignore"))
            keys |= all_configs
    return keys, all_configs, "regex(config_api.py + natural_cmd.py)"


def is_sensitive(key: str) -> bool:
    """敏感键判定：大写后含 TOKEN/API_KEY/SECRET/PASSWORD 子串，
    或含 KEY 且不以 KEYWORDS 结尾（避免误伤 HATE_KEYWORDS、PHOTO_KEYWORDS 等业务键）。"""
    upper = key.upper()
    if any(m in upper for m in ("TOKEN", "API_KEY", "SECRET", "PASSWORD")):
        return True
    return ("KEY" in upper) and not upper.endswith("KEYWORDS")


def main() -> int:
    example_keys = load_example_keys()
    whitelist, all_configs_keys, source = load_whitelist()
    removed_in_example = sorted(example_keys & set(REMOVED_CONFIG_FIELDS))
    removed_in_whitelist = sorted(whitelist & set(REMOVED_CONFIG_FIELDS))
    removed_in_natural = sorted(all_configs_keys & set(REMOVED_CONFIG_FIELDS))
    pseudo_in_example = sorted(example_keys & set(NESTED_CONFIG_PSEUDO_FIELDS))
    pseudo_in_whitelist = sorted(whitelist & set(NESTED_CONFIG_PSEUDO_FIELDS))

    # 豁免集合：敏感键 + 下划线开头元键 + 显式 EXEMPT_KEYS（仅统计 example 侧）
    exempt_total = {k for k in example_keys if k.startswith("_")}
    exempt_total |= {k for k in example_keys if is_sensitive(k)}
    exempt_total |= (EXEMPT_KEYS & example_keys)

    # 断言 a：example 非敏感业务键 ⊆ 白名单
    missing = sorted((example_keys - exempt_total) - whitelist)
    # 断言 b：白名单中无 example 不存在的幽灵键。
    # ALL_CONFIGS 声明键为自然语言可配置清单（合法白名单来源，example 未收录）；
    # EXEMPT_KEYS 中的白名单历史遗留键同样豁免。
    ghost = sorted((whitelist - example_keys - all_configs_keys) - EXEMPT_KEYS)

    print(f"{'检查项':<30}{'数量':>6}  说明")
    print("-" * 72)
    print(f"{'example 顶层键':<26}{len(example_keys):>6}  config.json.example")
    print(f"{'白名单键':<28}{len(whitelist):>6}  {source}")
    print(f"{'敏感/元键豁免':<26}{len(exempt_total):>6}  不在断言 a 范围")
    print()

    if missing:
        print(f"【断言 a 失败】{len(missing)} 个 example 业务键未在白名单：")
        for k in missing:
            print(f"  - {k}")
    else:
        print("【断言 a 通过】example 非敏感业务键均已在白名单中。")

    if ghost:
        print(f"【断言 b 失败】{len(ghost)} 个白名单幽灵键（example 中不存在）：")
        for k in ghost:
            print(f"  - {k}")
    else:
        print("【断言 b 通过】白名单中无 example 不存在的幽灵键。")

    if removed_in_example or removed_in_whitelist or removed_in_natural:
        print("【断言 c 失败】已确认退役字段不得出现在 example、Dashboard 白名单或自然语言配置表：")
        for key in sorted(set(removed_in_example + removed_in_whitelist + removed_in_natural)):
            surfaces = []
            if key in removed_in_example:
                surfaces.append("example")
            if key in removed_in_whitelist:
                surfaces.append("whitelist")
            if key in removed_in_natural:
                surfaces.append("natural")
            print(f"  - {key}: {', '.join(surfaces)}")
    else:
        print("【断言 c 通过】example、Dashboard 白名单与自然语言配置表均未包含已确认退役字段。")

    if pseudo_in_example or pseudo_in_whitelist:
        print("【断言 d 失败】嵌套路由别名只能存在于自然语言配置表：")
        for key in sorted(set(pseudo_in_example + pseudo_in_whitelist)):
            surfaces = []
            if key in pseudo_in_example:
                surfaces.append("example")
            if key in pseudo_in_whitelist:
                surfaces.append("whitelist")
            print(f"  - {key}: {', '.join(surfaces)}")
    else:
        print("【断言 d 通过】嵌套路由别名未进入 example 或 Dashboard 顶层白名单。")

    if exempt_total:
        print(f"\n当前 example 侧豁免键（{len(exempt_total)} 个，保持只读）：")
        for k in sorted(exempt_total):
            print(f"  - {k}")
    if whitelist - example_keys:
        wl_extra = sorted((whitelist - example_keys))
        print(f"\n白名单例外侧键（{len(wl_extra)} 个：ALL_CONFIGS 清单 + EXEMPT_KEYS 历史键，合法）：")
        for k in wl_extra:
            print(f"  - {k}")

    if (
        missing
        or ghost
        or removed_in_example
        or removed_in_whitelist
        or removed_in_natural
        or pseudo_in_example
        or pseudo_in_whitelist
    ):
        issue_count = (
            len(missing) + len(ghost)
            + len(removed_in_example) + len(removed_in_whitelist)
            + len(removed_in_natural) + len(pseudo_in_example)
            + len(pseudo_in_whitelist)
        )
        print(f"\n配置三处同步存在 {issue_count} 处问题，请按规则修正配置契约。")
        return 1
    print("\n配置三处同步一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
