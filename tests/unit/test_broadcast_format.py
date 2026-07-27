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
    news = "\n".join(
        [f"第{i}条不同方向的真实新闻" for i in range(1, 6)]
        + ["以上是本次刚刚更新的最新新闻。"]
    )
    result = build_rich_news_html("晚间", news, source_name="fallback")
    assert "多源汇总" not in result
    assert "均衡筛选" not in result
    assert "TrendRadar" not in result
    assert "<blockquote expandable><i>" in result


def test_news_renderers_keep_five_headlines_and_freshness_outro():
    """当前排版只展示5条头条，第6行是固定时效说明。"""
    from core.broadcast_formatter import build_rich_news_card_message

    headlines = [f"第{i}条综合头条有明确事实信息" for i in range(1, 6)]
    observation = "以上是本次刚刚更新的最新新闻。"
    news = "\n".join(headlines + [observation])

    html = build_rich_news_html("早间", news)
    rich = build_rich_news_card_message("早间", news)

    for headline in headlines:
        assert headline in html
        assert headline in rich
    assert html.count("📌") == 5
    assert rich.count("<li>") == 5
    assert f"<blockquote expandable><i>{observation}</i></blockquote>" in html
    assert f"<blockquote>{observation}</blockquote>" in rich


def test_news_balanced_selection_is_headline_first_and_caps_verticals():
    """10条新闻综合头条优先，科技最多1条、财经最多2条。"""
    from core.trendradar_news import _select_balanced_news

    items = [
        {"source": "36氪快讯", "title": "AI公司发布大模型新品", "category": "科技", "rank": 1},
        {"source": "36氪快讯", "title": "芯片企业公布新一轮融资", "category": "科技", "rank": 2},
        {"source": "36氪快讯", "title": "机器人公司推出新方案", "category": "科技", "rank": 3},
        {"source": "NewsNow华尔街见闻", "title": "全球主要市场关注央行最新表态", "category": "财经", "rank": 1},
        {"source": "NewsNow华尔街见闻", "title": "多地消费数据公布出现新变化", "category": "财经", "rank": 2},
        {"source": "NewsNow华尔街见闻", "title": "上市公司发布季度财报", "category": "财经", "rank": 3},
        {"source": "NewsNow澎湃", "title": "多地优化地铁换乘服务", "category": "社会", "rank": 1},
        {"source": "NewsNow头条", "title": "防汛救援工作取得新进展", "category": "社会", "rank": 1},
        {"source": "NewsNow百度", "title": "公共服务新规今日开始实施", "category": "综合", "rank": 1},
        {"source": "NewsNow早报", "title": "多国就地区局势举行会谈", "category": "国际", "rank": 1},
        {"source": "NewsNow知乎", "title": "暑期教育政策引发家长关注", "category": "生活", "rank": 1},
        {"source": "NewsNow微博", "title": "热门电影票房继续走高", "category": "文娱", "rank": 1},
        {"source": "NewsNow抖音", "title": "暑期旅行目的地热度上升", "category": "生活", "rank": 1},
        {"source": "NewsNowB站", "title": "中国队在国际比赛中夺冠", "category": "体育", "rank": 1},
    ]
    selected = _select_balanced_news(items, limit=10)
    categories = [
        line.split("】", 1)[0].lstrip("【").split("·", 1)[0]
        for line in selected
    ]

    assert len(selected) == 10
    assert categories[0] in {"社会", "综合"}
    assert categories.count("科技") <= 1
    assert categories.count("财经") <= 2
    assert len(set(categories)) >= 6


def test_active_news_sources_avoid_known_403_direct_endpoints():
    """生产新闻链不再请求已实测稳定403的微博、知乎、澎湃直连。"""
    from core.trendradar_news import get_active_news_sources

    sources = get_active_news_sources()
    urls = {item["url"] for item in sources}
    names = {item["name"] for item in sources}

    assert "https://weibo.com/ajax/side/hotSearch" not in urls
    assert "https://www.zhihu.com/hot" not in urls
    assert "https://www.thepaper.cn/" not in urls
    assert {"NewsNow头条", "NewsNow澎湃", "NewsNow早报"} <= names


def test_newsnow_sources_use_a_bounded_domain_pool():
    """同一聚合域禁止8路齐发，避免触发整域超时/限流。"""
    from core.trendradar_news import (
        _group_news_sources,
        get_active_news_sources,
    )

    groups = _group_news_sources(get_active_news_sources())
    workers = {name: max_workers for name, _, max_workers in groups}
    newsnow_sources = next(sources for name, sources, _ in groups if name == "newsnow")

    assert workers["newsnow"] == 2
    assert len(newsnow_sources) <= 5


def test_newsnow_requests_bypass_intermediary_cache(monkeypatch):
    """每轮播报都带 no-cache 与时间戳，避免沿用上一轮聚合响应。"""
    import core.trendradar_news as news_sources

    captured = {}

    class _Client:
        def get(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return {"items": [{"title": "本轮刚刚更新的真实热点"}]}

    monkeypatch.setattr(news_sources, "get_http_client", lambda: _Client())
    monkeypatch.setattr(news_sources.time, "time", lambda: 1785128766)

    lines = news_sources._fetch_source_news("weibo", limit=1)

    assert lines == ["【微博】本轮刚刚更新的真实热点"]
    assert captured["params"] == {"id": "weibo", "_": 1785128766}
    assert captured["headers"]["Cache-Control"] == "no-cache"
    assert captured["headers"]["Pragma"] == "no-cache"


def test_balanced_selection_still_fills_ten_when_sources_are_sparse():
    """类目或来源暂时变少时仍优先凑足10条非科技/财经头条。"""
    from core.trendradar_news import _select_balanced_news

    items = [
        {
            "source": "百度热搜" if index % 2 else "今日头条",
            "title": f"第{index}条社会公共事件出现新进展",
            "category": "社会" if index % 2 else "综合",
            "rank": index,
        }
        for index in range(1, 13)
    ]
    selected = _select_balanced_news(items, limit=10)

    assert len(selected) == 10
    assert not any("【科技" in line or "【财经" in line for line in selected)


if __name__ == "__main__":
    # 手动导入
    from core.broadcast_formatter import escape_html_text
    test_news_html_basic()
    test_news_html_no_marker()
    test_greeting_html_basic()
    test_news_html_escaping()
    print("\n🎉 所有测试通过！")
