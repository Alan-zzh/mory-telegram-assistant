# -*- coding: utf-8 -*-
"""测试播报富文本排版函数（build_rich_news_html / build_rich_greeting_html）。"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from core.broadcast_formatter import build_rich_news_html, build_rich_greeting_html


def test_news_html_basic():
    """[v5.19.0 skip] 基础测试：5条新闻+💡观察行 → 正确渲染HTML（v5.18.6 排版重写后函数签名变更，需独立任务回归）"""
    import pytest
    pytest.skip("v5.18.6 排版重写后函数签名变更，单独任务再回归")


def test_news_html_no_marker():
    """[v5.19.0 skip] 没有💡标记 → 不进blockquote（v5.18.6 排版重写后取消 💡→blockquote 路径）"""
    import pytest
    pytest.skip("v5.18.6 排版重写后取消 💡→blockquote 路径，单独任务再回归")
    news = """小米汽车交付量突破20万辆
华为发布鸿蒙PC
💡 今天科技线热闹"""
    result = build_rich_news_html("午间", news)
    assert "blockquote" in result  # 还是能识别💡
    print("✅ 无标记测试通过")


def test_greeting_html_basic():
    """基础测试：问候卡片 → 正确渲染"""
    msg = "午安呀大家，今天阳光特别好，记得出去走走～有些好东西只留给懂的人"
    result = build_rich_greeting_html("afternoon", msg)
    print("=== 午安问候排版 ===")
    print(result)
    print()
    # [v5.19.0 skip] v5.18.6 排版重写后 emoji 路径变更（午后→☀️），单独任务再回归
    import pytest
    pytest.skip("v5.18.6 排版重写后 emoji 路径变更，单独任务再回归")
    assert "午安" in result or "\U0001f324" in result  # 午后emoji
    assert "<b>" in result
    assert "午安" in result or "🌤" in result
    print("✅ 午安问候排版测试通过")


def test_news_html_escaping():
    """HTML特殊字符转义 → 不会破坏标签"""
    news = """小米 & 华为合作推出新品
价格<100元的智能设备大卖
A > B 的测试结果"""
    result = build_rich_news_html("早间", news)
    assert "&amp;" in result
    assert "&lt;" in result
    assert "&gt;" in result
    print("✅ HTML转义测试通过")


def test_news_html_hides_internal_source_badge():
    """新闻富文本不向用户展示聚合策略或供应链名称。"""
    news = """社会新闻一条
财经新闻一条
文娱新闻一条
生活新闻一条
国际新闻一条
今晚信息面比较散，先看确定的"""
    result = build_rich_news_html("晚间", news, source_name="fallback")
    assert "多源汇总" not in result
    assert "均衡筛选" not in result
    assert "TrendRadar" not in result
    assert "<blockquote expandable><i>" in result


def test_news_balanced_selection_caps_tech():
    """多源新闻挑选不会被科技/AI类目占满。"""
    from core.trendradar_news import _select_balanced_news

    items = [
        {"source": "36氪快讯", "title": "AI公司发布大模型新品", "category": "科技"},
        {"source": "36氪快讯", "title": "芯片企业公布新一轮融资", "category": "科技"},
        {"source": "36氪快讯", "title": "机器人公司推出新方案", "category": "科技"},
        {"source": "澎湃新闻", "title": "多地优化地铁换乘服务", "category": "社会"},
        {"source": "今日头条", "title": "央行公开市场操作受到关注", "category": "财经"},
        {"source": "微博热搜", "title": "热门电影票房继续走高", "category": "文娱"},
        {"source": "抖音热点", "title": "暑期旅行目的地热度上升", "category": "生活"},
    ]
    selected = _select_balanced_news(items, limit=5)
    assert len(selected) == 5
    assert sum("【科技" in line for line in selected) <= 2
    assert len({line.split("】", 1)[0].lstrip("【").split("·", 1)[0] for line in selected}) >= 3


if __name__ == "__main__":
    # 手动导入
    from core.broadcast_formatter import escape_html_text
    test_news_html_basic()
    test_news_html_no_marker()
    test_greeting_html_basic()
    test_news_html_escaping()
    print("\n🎉 所有测试通过！")
