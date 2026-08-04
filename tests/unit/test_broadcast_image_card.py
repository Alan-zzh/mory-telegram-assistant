# -*- coding: utf-8 -*-
"""播报图片卡（PIL）v5.38.16 新增优化项 smoke 测试。

覆盖：
- 6 类 payload 适配器：almanac/tarot/iching/news/greeting/scheduled
- font() LRU cache 命中
- CTA label ↔ image_label 强绑定一致性（遍历文案池）
- 单区块异常隔离：注入坏 block 后 draw_card 仍能出图
- draw_card 真实出图（PNG 存在 + size>0）
- deploy_vps 文件过滤：超体积+路径黑名单跳过
"""

from __future__ import annotations

import os
import random
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# 6 类 payload 构造 smoke
# ---------------------------------------------------------------------------

def test_almanac_payload_has_blocks_tags_and_footer():
    from core.broadcast_image_payload import build_almanac_image_payload

    mystic = {
        "title": "早间 · 今日黄历",
        "kicker": "今日宜忌",
        "meta": "2026-08-03｜农历六月二十",
        "blocks": [
            {"heading": "📌 宜", "lines": [("宜", "祭祀·祈福·出行"), ("忌", "动土·安葬")]},
            {"heading": "冲煞值日", "lines": [("冲煞", "冲猴煞北"), ("值日", "天刑")]},
            {"heading": "今日运势", "lines": [("综合", "平"), ("财运", "吉")]},
        ],
        "hours": [
            ("子时", "23-01", "吉"), ("丑时", "01-03", "凶"),
            ("寅时", "03-05", "吉"), ("卯时", "05-07", "凶"),
        ],
        "wealth_direction": "正北",
        "joy_direction": "东北",
        "insight": "今日宜静不宜动，保持平常心。",
    }
    payload = build_almanac_image_payload(mystic)
    assert payload["title"].endswith("黄历")
    assert payload["date_text"] == "六月二十"
    # style 映射：宜忌→two_column，冲煞→key_value，其余→list
    styles = [b["style"] for b in payload["blocks"]]
    assert styles == ["two_column", "key_value", "list"]
    assert len(payload["tags"]) == 4
    assert payload["tags"][0][1] in ("吉", "凶")
    assert ("财神方位", "正北") in payload["footer_lines"]
    assert ("喜神方位", "东北") in payload["footer_lines"]
    assert payload["insight"]


def test_tarot_payload_normalizes_energy_block_to_key_value():
    from core.broadcast_image_payload import build_tarot_image_payload

    mystic = {
        "mode": "tarot",
        "blocks": [
            {"heading": "🎴 三张牌阵", "lines": [("过去", "愚者"), ("现在", "魔术师"), ("未来", "女祭司")]},
            {"heading": "今日能量", "lines": [("元素", "风"), ("数字", "1")]},
        ],
    }
    payload = build_tarot_image_payload(mystic)
    assert [b["style"] for b in payload["blocks"]] == ["list", "key_value"]
    for b in payload["blocks"]:
        # 所有 heading 的 emoji 前缀都被 strip
        assert not any(ch in b["heading"] for ch in "🎴✨")


def test_iching_payload_normalizes_gua_meaning_to_key_value():
    from core.broadcast_image_payload import build_iching_image_payload

    mystic = {
        "mode": "iching",
        "blocks": [
            {"heading": "☯️ 本卦", "lines": [("卦名", "乾为天"), ("爻辞", "元亨利贞")]},
            {"heading": "卦意解读", "lines": [("上九", "亢龙有悔")]},
        ],
    }
    payload = build_iching_image_payload(mystic)
    assert [b["style"] for b in payload["blocks"]] == ["list", "key_value"]
    assert payload["title"] == "晚间 · 易经一卦"


def test_news_payload_builds_numbered_list_and_insight():
    from core.broadcast_image_payload import build_news_image_payload

    text = "1. 第一条新闻\n2. 第二条新闻\n3. 第三条新闻\n4. 第四条\n5. 第五条\n💡 今日看点：科技板块领涨"
    payload = build_news_image_payload(text, time_desc="午间")
    assert payload["title"] == "午间新闻"
    assert len(payload["blocks"]) == 1
    assert len(payload["blocks"][0]["lines"]) == 5
    assert payload["blocks"][0]["lines"][0][0] == "1."
    # insight 去掉了 emoji 前缀
    assert payload["insight"].startswith("今日看点")
    assert "💡" not in payload["insight"]


@pytest.mark.parametrize("period,expected_title", [
    ("morning", "早安"),
    ("afternoon", "午安"),
    ("evening", "晚安"),
    ("night", "晚安"),
])
def test_greeting_payload_maps_period_to_title(period, expected_title):
    from core.broadcast_image_payload import build_greeting_image_payload

    p = build_greeting_image_payload(period, "今天也要元气满满哦～", badge="新的一天")
    assert p["title"] == expected_title
    assert p["kicker"] == "新的一天"
    assert p["insight"] == "今天也要元气满满哦～"


def test_scheduled_payload_strips_emoji_and_applies_vip_title():
    from core.broadcast_image_payload import build_scheduled_image_payload

    item = {
        "title": "☀️ 中午固定播报",
        "content": "午安，今日的内容来啦～",
        "badge": "每日更新",
        "footer": "感谢你的陪伴",
    }
    p = build_scheduled_image_payload(item)
    assert p["title"] == "中午固定播报"
    assert "☀️" not in p["title"]
    assert "午安" in p["insight"]
    assert "感谢你的陪伴" in p["insight"]

    vip = build_scheduled_image_payload(item, user_profile={"tags": ["vip"], "level": 5})
    assert vip["title"] == "精选 · 中午固定播报"


# ---------------------------------------------------------------------------
# font() LRU cache 命中
# ---------------------------------------------------------------------------

def test_font_lru_cache_reuses_same_object_for_same_size_and_style():
    from core.broadcast_image_card import font

    # lru_cache: 相同参数第二次调用返回同一对象（is 相同）
    f1 = font(24, "kai")
    f2 = font(24, "kai")
    assert f1 is f2, "font() LRU 未命中：相同 (size,style) 返回不同对象"
    # 第一次调用后 cache_info hits 会增长
    info = font.cache_info()
    assert info.hits >= 1, f"期望 cache hits>=1，实际 {info}"
    # 不同 size / style 不走缓存（但也不报错）
    f3 = font(24, "hei")
    f4 = font(26, "kai")
    assert f3 is not f1
    assert f4 is not f1


# ---------------------------------------------------------------------------
# CTA 强绑定：遍历文案池全部 (label, image_label) 对，validate_cta_consistency 应通过
# ---------------------------------------------------------------------------

def test_all_cta_pool_entries_pass_consistency_check():
    from core.broadcast_cta import _CTA_POOLS, validate_cta_consistency

    failures = []
    for scene, targets in _CTA_POOLS.items():
        for target, choices in targets.items():
            for idx, (label, img_label, _closing) in enumerate(choices):
                ok, reason = validate_cta_consistency(label, img_label)
                if not ok:
                    failures.append(f"{scene}/{target}[{idx}]: {reason}")
    assert not failures, "以下 CTA 文案池条目一致性校验失败：\n" + "\n".join(failures)


def test_get_broadcast_cta_derives_image_label_from_button_label():
    """强绑定核心：get_broadcast_cta 返回的 image_label 必须等于 strip_visual_emoji(label)，
    即使池子中的 img_label 与派生值不一致也应以派生为准。"""
    from core.broadcast_cta import get_broadcast_cta
    from core.broadcast_image_card import strip_visual_emoji

    cfg = {
        "MYSTIC_BROADCAST_CONFIG": {"cta_enabled": True},
    }
    # (scene, call_kwargs)
    scenes = [
        ("mystic_almanac", {"scene": "mystic", "period": "morning", "mode": "almanac"}),
        ("mystic_tarot", {"scene": "mystic", "period": "afternoon", "mode": "tarot"}),
        ("mystic_iching", {"scene": "mystic", "period": "evening", "mode": "iching"}),
        ("greeting_afternoon", {"scene": "greeting", "period": "afternoon"}),
        ("greeting_night", {"scene": "greeting", "period": "night"}),
        ("scheduled", {"scene": "scheduled", "period": "morning"}),
        ("scheduled_afternoon", {"scene": "scheduled", "period": "afternoon"}),
        ("scheduled_night", {"scene": "scheduled", "period": "night"}),
    ]
    for scene, kwargs in scenes:
        # 用确定性 rng，每次取同一个
        rng = random.Random(42)
        cta = get_broadcast_cta(**kwargs, config=cfg, rng=rng)
        if cta["target"] != "none":
            label = cta["label"]
            derived = strip_visual_emoji(label)
            assert cta["image_label"] == derived or (derived and derived in cta["image_label"]), \
                f"scene={scene} 派生不一致：label={label!r} -> derived={derived!r} vs image_label={cta['image_label']!r}"


# ---------------------------------------------------------------------------
# 区块异常隔离：单 block 抛异常，draw_card 仍能输出完整 PNG
# ---------------------------------------------------------------------------

def test_block_exception_isolation_still_produces_png(tmp_path: Path):
    from core.broadcast_image_card import draw_card

    out = tmp_path / "isolated.png"
    payload = {
        "title": "异常隔离测试",
        "kicker": "smoke",
        "blocks": [
            {"heading": "正常 block", "lines": [("标签A", "值1"), ("标签B", "值2")]},
            # 注入坏 block：lines 里混入无法格式化的对象，list 风格会抛 TypeError/IndexError
            {"heading": "坏 block", "lines": [(None, object()), (123, 456)]},
            {"heading": "正常 block 2", "lines": [("标签C", "值3")]},
        ],
        "insight": "单区块错误不应影响整张卡出图。",
    }
    # 不抛异常就算通过
    path, info = draw_card(payload, str(out), cta="看看预览")
    assert Path(path).exists()
    assert os.path.getsize(path) > 1000
    assert info["height"] >= 1000
    assert info["cta"] == "看看预览"


# ---------------------------------------------------------------------------
# 真实 draw_card 全 6 类出图 smoke
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("card_name", [
    "almanac", "tarot", "iching", "news", "greeting", "scheduled",
])
def test_six_card_render_all_produce_valid_png(tmp_path: Path, card_name: str):
    from core.broadcast_image_payload import (
        build_almanac_image_payload, build_tarot_image_payload,
        build_iching_image_payload, build_news_image_payload,
        build_greeting_image_payload, build_scheduled_image_payload,
    )
    from core.broadcast_image_card import draw_card

    if card_name == "almanac":
        p = build_almanac_image_payload({
            "meta": "｜农历六月二十",
            "blocks": [
                {"heading": "宜", "lines": [("宜", "祭祀·祈福"), ("忌", "动土·嫁娶")]},
            ],
            "hours": [("子时", "23-01", "吉")],
            "wealth_direction": "正东",
            "insight": "今日宜保持专注。",
        })
    elif card_name == "tarot":
        p = build_tarot_image_payload({
            "blocks": [
                {"heading": "三张牌阵", "lines": [("过去", "愚者"), ("现在", "魔术师"), ("未来", "女祭司")]},
            ],
            "insight": "现在是行动的好时机。",
        })
    elif card_name == "iching":
        p = build_iching_image_payload({
            "blocks": [{"heading": "本卦", "lines": [("卦名", "乾为天")]}],
            "insight": "元亨利贞。",
        })
    elif card_name == "news":
        p = build_news_image_payload("1. 新闻A\n2. 新闻B\n3. 新闻C\n💡 三条新闻看今日")
    elif card_name == "greeting":
        p = build_greeting_image_payload("afternoon", "下午好，歇一会。")
    else:  # scheduled
        p = build_scheduled_image_payload({"title": "下午播报", "content": "午安"})

    out = tmp_path / f"{card_name}.png"
    path, info = draw_card(p, str(out))
    assert Path(path).exists()
    sz = os.path.getsize(path)
    assert sz > 1000, f"{card_name} PNG 大小 {sz} 字节，疑似渲染失败"
    assert info["width"] == 800
    assert info["height"] >= 1000


# ---------------------------------------------------------------------------
# deploy_vps 大文件/路径黑名单过滤
# ---------------------------------------------------------------------------

def test_deploy_vps_filters_oversize_and_runtime_cache_paths(monkeypatch, tmp_path: Path):
    """_collect_upload_files 三层过滤：名称/路径/体积。

    通过 monkeypatch ROOT 到临时目录验证过滤逻辑，不依赖真实仓库文件。
    """
    import deploy_vps

    fake_root = tmp_path
    # 伪造 SCAN_DIRS 之一：assets，构造不同大小+路径的假文件
    assets_dir = fake_root / "assets"
    assets_dir.mkdir()
    (assets_dir / "small.png").write_bytes(b"x" * 1024)  # 1KB，通过
    # 超 20MB：应该跳过
    huge = assets_dir / "huge.png"
    huge.write_bytes(b"x" * (21 * 1024 * 1024))
    # runtime/cache（不在 SCAN_DIRS 但如果混在 assets 子目录，路径片段也应跳过）
    bad_sub = assets_dir / "runtime" / "cache"
    bad_sub.mkdir(parents=True)
    (bad_sub / "stale.png").write_bytes(b"stale")
    # __pycache__
    cache = assets_dir / "__pycache__"
    cache.mkdir()
    (cache / "mod.pyc").write_bytes(b"x")

    # ROOT_FILES 不用改，monkeypatch 根目录和扫描目录
    monkeypatch.setattr(deploy_vps, "ROOT", fake_root)
    monkeypatch.setattr(deploy_vps, "ROOT_FILES", [])
    monkeypatch.setattr(deploy_vps, "SCAN_DIRS", ["assets"])
    # SCAN_DIR_EXTS 默认 assets 含 .png/.pyc 不在列表里所以 __pycache__ 不会命中；
    # 我们额外加一个假目录 core，含 .py 来验证 SKIP_PATH_FRAGMENTS
    core = fake_root / "core"
    core.mkdir()
    (core / "ok.py").write_text("print('ok')\n")
    monkeypatch.setattr(deploy_vps, "SCAN_DIRS", ["assets", "core"])

    collected = deploy_vps._collect_upload_files()
    rels = set(collected)
    assert "assets/small.png" in rels
    assert "core/ok.py" in rels
    # 超大文件被过滤
    assert "assets/huge.png" not in rels
    # runtime/cache 路径片段被过滤
    assert "assets/runtime/cache/stale.png" not in rels


def test_is_broadcast_image_enabled_switch_matrix():
    """图片卡开关矩阵：全局关 / 类型关 / 双开 / 空配置。"""
    from core.broadcast_cta import is_broadcast_image_enabled

    section = {"image_card_enabled": True}
    # 全局总闸关闭 → 任何类型都不出图
    assert not is_broadcast_image_enabled({"BROADCAST_IMAGE_CARD_ENABLED": False}, section)
    assert not is_broadcast_image_enabled({}, section)
    assert not is_broadcast_image_enabled(None, section)
    # 全局开 + 类型关 → 不出图
    assert not is_broadcast_image_enabled({"BROADCAST_IMAGE_CARD_ENABLED": True}, {"image_card_enabled": False})
    assert not is_broadcast_image_enabled({"BROADCAST_IMAGE_CARD_ENABLED": True}, {})
    assert not is_broadcast_image_enabled({"BROADCAST_IMAGE_CARD_ENABLED": True}, None)
    # 双开 → 出图
    assert is_broadcast_image_enabled({"BROADCAST_IMAGE_CARD_ENABLED": True}, section)


# ---------------------------------------------------------------------------
# build_broadcast_image_card 缓存命中短路 + 原子写入
# ---------------------------------------------------------------------------

def _broadcast_cache_dir() -> str:
    """计算 build_broadcast_image_card 实际使用的缓存目录（runtime/cache/broadcast）。"""
    from core import broadcast_image_card

    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(broadcast_image_card.__file__))),
        "runtime", "cache", "broadcast",
    )


def _cleanup_card_files(cache_key: str) -> None:
    """清理测试生成的缓存文件（含可能的 .tmp 残留），避免污染真实缓存。"""
    safe_key = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(cache_key))[:80]
    for suffix in (".png", ".png.tmp"):
        p = os.path.join(_broadcast_cache_dir(), f"{safe_key}{suffix}")
        if os.path.isfile(p):
            os.remove(p)


def test_build_card_cache_reuse_same_day():
    """同 cache_key 二次调用应命中缓存短路：mtime 保持不变（同日幂等，不重绘）。"""
    from core.broadcast_image_card import build_broadcast_image_card

    payload = {
        "title": "缓存复用测试",
        "kicker": "smoke",
        "blocks": [{"heading": "内容", "lines": [("标签A", "值1")]}],
    }
    key = f"_test_cache_reuse_{os.getpid()}"
    _cleanup_card_files(key)
    out_path = None
    try:
        p1 = build_broadcast_image_card(payload, cache_key=key, min_height=1000, cta_text="")
        assert p1 and os.path.isfile(p1)
        out_path = p1
        # 把 mtime 拨到 1 小时前（仍在 24h 窗口内）：若第二次命中短路则文件不会被重写
        old = time.time() - 3600
        os.utime(p1, (old, old))
        mtime_before = os.path.getmtime(p1)

        p2 = build_broadcast_image_card(payload, cache_key=key, min_height=1000, cta_text="")
        assert p2 == p1
        assert os.path.getmtime(p1) == mtime_before, "缓存未命中：二次调用重写了文件"
    finally:
        _cleanup_card_files(key)
        assert out_path is None or not os.path.isfile(out_path), "测试残留未清理干净"


def test_build_card_atomic_replace():
    """生成完成后目录中不应残留 .tmp 临时文件（原子替换成功）。"""
    from core.broadcast_image_card import build_broadcast_image_card

    payload = {
        "title": "原子写入测试",
        "kicker": "smoke",
        "blocks": [{"heading": "内容", "lines": [("标签B", "值2")]}],
    }
    key = f"_test_atomic_replace_{os.getpid()}"
    _cleanup_card_files(key)
    out_path = None
    try:
        p = build_broadcast_image_card(payload, cache_key=key, min_height=1000, cta_text="")
        assert p and os.path.isfile(p)
        out_path = p
        # 目录中不应有该 key 对应的 .tmp 残留
        assert not os.path.isfile(p + ".tmp"), "存在 .tmp 残留，原子替换未生效"
    finally:
        _cleanup_card_files(key)


# ---------------------------------------------------------------------------
# _stable_seed 确定性种子（md5 替代内置 hash，消除跨进程漂移）
# ---------------------------------------------------------------------------

def test_stable_seed_deterministic():
    """同参数两次调用 seed 相等；不同参数大概率不同（只断言不等，不断言具体值）。"""
    from core.broadcast_cta import _stable_seed

    s1 = _stable_seed("mystic", "morning", "almanac")
    s2 = _stable_seed("mystic", "morning", "almanac")
    assert s1 == s2, "同参数两次调用 seed 不一致，确定性被破坏"
    # 不同参数 md5 碰撞概率可忽略，直接断言不等
    s3 = _stable_seed("mystic", "morning", "iching")
    assert s3 != s1
    # 返回 0..2^32 区间内的正整数
    assert 0 <= s1 < 0x100000000
    assert 0 <= s3 < 0x100000000
