# -*- coding: utf-8 -*-
"""
广告检测核心逻辑测试 - 覆盖 L0-L4 多层检测

测试层级：
- L0: 零宽字符清理
- L1: 文本规范化（全角数字/繁体转简体）
- L2: 用户名特征检测
- L3: 内容评分（关键词维度）
- L4: 组合判定（多维度联合评分）
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from modules.ad_detector import AdDetector, check_username_suspicious, SCORE_THRESHOLD


# ──────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────

@pytest.fixture
def detector(ad_detector_config):
    """创建 AdDetector 实例（无数据库）"""
    return AdDetector(config=ad_detector_config, db=None)


# ──────────────────────────────────────────────────────
# L0: 零宽字符清理
# ──────────────────────────────────────────────────────

def test_clean_zero_width_removes_hidden_chars(detector):
    """L0: 零宽字符被正确清理"""
    text = "只\u200d搞\u200cU无\u2060套\u200d路"
    cleaned, count = detector._clean_zero_width(text)
    assert "搞" in cleaned
    assert "套" in cleaned
    assert count > 0


def test_clean_zero_width_empty_input(detector):
    """L0: 空字符串返回原值和 0 计数"""
    cleaned, count = detector._clean_zero_width("")
    assert cleaned == ""
    assert count == 0


def test_clean_zero_width_normal_text_unchanged(detector):
    """L0: 正常文本不被误改"""
    text = "今天天气不错"
    cleaned, count = detector._clean_zero_width(text)
    assert cleaned == text
    assert count == 0


# ──────────────────────────────────────────────────────
# L1: 文本规范化
# ──────────────────────────────────────────────────────

def test_normalize_fullwidth_digits(detector):
    """L1: 全角数字转半角"""
    text = "刷单秒钻０１２３"
    result = detector._normalize_ad_evasion(text)
    assert "0123" in result


def test_normalize_traditional_to_simplified(detector):
    """L1: 繁体字转简体"""
    text = "賺錢"
    result = detector._normalize_ad_evasion(text)
    assert result == "赚钱"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("一日 9Oo+", "一日 900+"),
        ("一日 4oO＋", "一日 400+"),
        ("一日 ｌＯＯＯ＋", "一日 1000+"),
        ("𝟙日 𝟡Oo＋", "1日 900+"),
        ("型号 O90", "型号 O90"),
        ("Emilia Potts", "Emilia Potts"),
        ("每天 BOSS+副本", "每天 BOSS+副本"),
    ],
)
def test_normalize_o_as_zero_only_inside_plus_number_tokens(detector, text, expected):
    """L1: 视觉等价字符与收益数字形近字受限规范化，不破坏英文和型号"""
    assert detector._normalize_ad_evasion(text) == expected


# ──────────────────────────────────────────────────────
# L2: 用户名特征检测
# ──────────────────────────────────────────────────────

def test_username_suspicious_look_profile():
    """L2: '看简介'变体用户名被识别为可疑"""
    is_sus, reason = check_username_suspicious("看简介")
    assert is_sus is True
    assert reason != ""


def test_username_normal_not_suspicious():
    """L2: 正常用户名不被误判"""
    is_sus, reason = check_username_suspicious("张三")
    assert is_sus is False


def test_check_username_hits_builtin_rule(detector):
    """L2: AdDetector._check_username 命中内置引流规则"""
    matches = detector._check_username("看简介")
    assert len(matches) > 0


def test_check_username_empty_returns_empty(detector):
    """L2: 空用户名返回空列表"""
    matches = detector._check_username("")
    assert matches == []


def test_screenshot_traditional_look_earn_username_hits_builtin_rule(detector):
    """L2: 截图显示名“看我賺米”规范化后必须命中高置信引流规则"""
    is_suspicious, reason = check_username_suspicious("看我賺米")
    normalized = detector._normalize_ad_evasion("看我賺米")
    assert is_suspicious is True
    assert reason
    assert normalized == "看我赚米"
    assert detector._check_username(normalized)


# ──────────────────────────────────────────────────────
# L3: 内容评分
# ──────────────────────────────────────────────────────

def test_content_score_ad_message(detector):
    """L3: 含广告关键词的消息评分 > 0"""
    score, dims = detector._check_content_score("加我微信日赚千元")
    assert score > 0
    assert len(dims) > 0


def test_content_score_normal_message(detector):
    """L3: 正常消息评分为 0"""
    score, dims = detector._check_content_score("今天天气真不错")
    assert score == 0
    assert dims == []


def test_content_score_empty_message(detector):
    """L3: 空消息评分为 0"""
    score, dims = detector._check_content_score("")
    assert score == 0


@pytest.mark.parametrize("text", ["1天1w米", "微信业务日1w米人"])
def test_screenshot_income_shorthand_scores_as_ad(detector, text):
    """L3: 截图中的“时间+数字+w+米”收益黑话必须达到即时处置阈值"""
    score, dims = detector._check_content_score(text)
    assert score >= SCORE_THRESHOLD
    assert "赚钱承诺" in dims[0]


@pytest.mark.parametrize("text", ["我每天跑1万米", "微信业务怎么迁移", "一天跑1w米太累了"])
def test_income_shorthand_rule_does_not_match_normal_context(detector, text):
    """L3: 正常运动与微信业务讨论不因新规则被误判"""
    score, dims = detector._check_content_score(text)
    assert score == 0
    assert dims == []


@pytest.mark.parametrize(
    "text",
    [
        "一日 9Oo+",
        "一日 4oO+",
        "一日 90o+",
        "一日 900+",
        "一天 800＋",
        "每天 1200+",
    ],
)
def test_screenshot_daily_income_plus_shorthand_scores_as_ad(detector, text):
    """L3: 截图及同日生产出现的 O/0 混写日收益短句必须达到即时处置阈值"""
    normalized = detector._normalize_ad_evasion(text)
    score, dims = detector._check_content_score(normalized)
    assert score >= SCORE_THRESHOLD
    assert "赚钱承诺" in dims[0]


@pytest.mark.parametrize(
    "text",
    [
        "我一天走了900+步",
        "一天900+步",
        "每天写900+字",
        "一日900+米训练",
        "今天订单90o+条",
        "型号90O+已经停售",
    ],
)
def test_daily_income_plus_rule_does_not_match_normal_metrics(detector, text):
    """L3: 运动、学习、订单与型号数字不因 O/0 规范化或加号被误判"""
    normalized = detector._normalize_ad_evasion(text)
    score, dims = detector._check_content_score(normalized)
    assert score == 0
    assert dims == []


@pytest.mark.parametrize(
    ("text", "expected_dimension"),
    [
        ("日1入 lOOO+", "赚钱承诺"),
        ("１日 ｌＯＯＯ＋", "赚钱承诺"),
        ("一x天 8O0元", "赚钱承诺"),
        ("加1微x信", "联系方式/引流"),
        ("兼1职 日结 500元", "招募/拉人"),
        ("日结 500元，兼x职", "招募/拉人"),
        ("特1码有量，找庄", "灰色产业"),
        ("六x彩1合，有量找靠谱庄", "灰色产业"),
        ("裸1聊", "色情引流"),
        ("约x炮", "色情引流"),
        ("跑1分 接单返佣", "加密货币/洗钱"),
        ("刷x单 日结佣金", "加密货币/洗钱"),
        ("返佣接单，跑x分", "加密货币/洗钱"),
        ("洗8钱", "加密货币/洗钱"),
    ],
)
def test_context_limited_obfuscated_ad_templates_trigger_immediate_ban(
    detector, text, expected_dimension
):
    """L3/L4: 六类数字/字母拆字广告需命中对应强语义维度并在首条封禁"""
    result = detector.detect(username="普通昵称", msg=text)
    assert result["is_ad"] is True
    assert result["action"] == "ban"
    assert result["score"] >= SCORE_THRESHOLD
    assert expected_dimension in result["reason"]


@pytest.mark.parametrize(
    "text",
    [
        "跑1分后休息一下",
        "刷1单正常订单后核对库存",
        "招聘系统的 X1 字段设计",
        "兼职经历写在简历里",
        "代理型号 X1 的售后问题",
        "六盒彩色积木有六块",
        "特码字段用于单元测试",
        "我每天打 BOSS+副本",
        "空调维修提供上门服务",
        "联x系是数学里的关系符号写法",
    ],
)
def test_context_limited_obfuscated_templates_do_not_ban_ambiguous_normal_text(
    detector, text
):
    """L4: 歧义词、产品型号、运动游戏和正常服务缺少第二广告锚点时不得误封"""
    result = detector.detect(username="普通用户", msg=text)
    assert result["is_ad"] is False
    assert result["action"] != "ban"


@pytest.mark.parametrize(
    "text",
    [
        "港澳1-49特码有量，有收的吗?",
        "港澳1-49特码有量，有收的庄吗？",
        "六码名单有量，找靠谱庄",
        "六彩合单子有量，找靠谱庄",
    ],
)
def test_screenshot_lottery_trade_slang_scores_as_gray_industry(detector, text):
    """L3: 截图及生产原文中的彩票交易黑话必须首条达到即时处置阈值"""
    score, dims = detector._check_content_score(text)
    assert score >= SCORE_THRESHOLD
    assert "灰色产业" in dims[0]


@pytest.mark.parametrize(
    "text",
    [
        "港澳通行证1-49号窗口有号，有收资料的吗？",
        "名单有六个人，找靠谱的农庄",
        "新闻讨论：所谓港澳特码只是非法宣传用语",
        "六码名单已公开用于数学教学",
    ],
)
def test_lottery_trade_rule_does_not_match_normal_context(detector, text):
    """L3: 普通港澳、名单、农庄及新闻讨论不因组合规则被误判"""
    score, dims = detector._check_content_score(text)
    assert score == 0
    assert dims == []


# ──────────────────────────────────────────────────────
# L4: 组合判定
# ──────────────────────────────────────────────────────

def test_detect_clear_ad_returns_is_ad_true(detector):
    """L4: 明确广告消息被判定为广告"""
    result = detector.detect(
        username="看简介",
        msg="加我微信，日赚千元，私信联系",
    )
    assert result["is_ad"] is True
    assert result["score"] >= SCORE_THRESHOLD


def test_detect_normal_message_not_ad(detector):
    """L4: 正常消息不被判定为广告"""
    result = detector.detect(
        username="普通用户",
        msg="大家好，今天天气不错",
    )
    assert result["is_ad"] is False


def test_detect_returns_expected_structure(detector):
    """L4: detect() 返回结构包含所有必要字段"""
    result = detector.detect(username="test", msg="hello")
    required_keys = {"is_ad", "score", "action", "matched_rules", "reason"}
    assert required_keys.issubset(result.keys())


def test_detect_zero_width_ad_still_caught(detector):
    """L4: 零宽字符拆散的广告词仍被检测"""
    result = detector.detect(
        username="正常用户",
        msg="加\u200d我\u200c微\u2060信",
    )
    # 清理后应能检测到联系方式维度
    assert result["score"] > 0


def test_detect_stats_increment_on_ad(detector):
    """L4: 检测到广告后统计计数递增"""
    initial = detector.stats.get("total_detected", 0)
    detector.detect(username="看简介", msg="加我微信日赚千元")
    assert detector.stats["total_detected"] > initial


@pytest.mark.parametrize("text", ["1天1w米", "微信业务日1w米人"])
def test_screenshot_ad_samples_trigger_immediate_ban(detector, text):
    """L4: 截图显示名与两条原文均应直接进入统一封禁链"""
    result = detector.detect(username="看我賺米", msg=text)
    assert result["is_ad"] is True
    assert result["action"] == "ban"
    assert result["score"] >= SCORE_THRESHOLD


@pytest.mark.parametrize(
    "text",
    [
        "港澳1-49特码有量，有收的吗?",
        "港澳1-49特码有量，有收的庄吗？",
        "六码名单有量，找靠谱庄",
        "六彩合单子有量，找靠谱庄",
    ],
)
def test_screenshot_lottery_ads_trigger_immediate_ban_on_first_message(detector, text):
    """L4: 彩票交易广告不能依赖重复消息或累计追踪，首条必须直接封禁"""
    result = detector.detect(username="财神", msg=text)
    assert result["is_ad"] is True
    assert result["action"] == "ban"
    assert result["score"] >= SCORE_THRESHOLD
    assert "灰色产业" in result["reason"]


@pytest.mark.parametrize("text", ["一日 9Oo+", "一日 4oO+", "一日 900+"])
def test_screenshot_daily_income_ads_trigger_immediate_ban(detector, text):
    """L4: O/0 混写日收益广告必须首条直接封禁，不能进入累计观察"""
    result = detector.detect(username="Emilia Potts", msg=text)
    assert result["is_ad"] is True
    assert result["action"] == "ban"
    assert result["score"] >= SCORE_THRESHOLD
    assert "赚钱承诺" in result["reason"]
