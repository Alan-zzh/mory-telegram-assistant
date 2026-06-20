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
