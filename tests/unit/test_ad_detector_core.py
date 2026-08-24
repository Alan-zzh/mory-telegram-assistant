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
import time

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


class _RepeatSnapshotDB:
    def __init__(self, rows):
        self.rows = rows

    def get_user_messages(self, user_id, chat_id=None, limit=100):
        return list(self.rows)[:limit]


def _repeat_row(msg_id, text, minutes_ago, deleted=0):
    return {
        "chat_id": -1001,
        "msg_id": msg_id,
        "text": text,
        "ts": int(time.time() - minutes_ago * 60),
        "deleted": deleted,
    }


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


def test_one_hour_three_exact_repeats_are_behavior_only_spam(ad_detector_config):
    db = _RepeatSnapshotDB([
        _repeat_row(1, "进群演个二十", 42),
        _repeat_row(2, "进群演个二十", 29),
        _repeat_row(3, "进群演个二十", 12),
    ])
    detector = AdDetector(config=ad_detector_config, db=db)

    result = detector.check_consecutive_patterns(42, -1001)

    assert result["is_spam"] is True
    assert result["behavior_only"] is True
    assert result["action"] == "delete_repeat_only"
    assert [item["msg_id"] for item in result["messages"]] == [1, 2, 3]


def test_repeat_normalization_covers_spacing_and_punctuation(ad_detector_config):
    db = _RepeatSnapshotDB([
        _repeat_row(1, "一日4Q", 55),
        _repeat_row(2, "一 日 4Q！", 25),
        _repeat_row(3, "一日4Ｑ。", 1),
    ])
    detector = AdDetector(config=ad_detector_config, db=db)

    result = detector.check_consecutive_patterns(42, -1001)

    assert result["is_spam"] is True
    assert result["behavior_only"] is True


def test_long_near_identical_repeats_require_very_high_similarity(ad_detector_config):
    detector = AdDetector(config=ad_detector_config, db=_RepeatSnapshotDB([
        _repeat_row(1, "这个项目具体怎么参与麻烦详细介绍一下", 50),
        _repeat_row(2, "这个项目具体怎么参与麻烦详细介绍下", 25),
        _repeat_row(3, "这个项目具体怎么参与麻烦详细介绍一下呢", 1),
    ]))

    result = detector.check_consecutive_patterns(42, -1001)

    assert result["is_spam"] is True
    assert result["behavior_only"] is True


def test_one_hour_repeat_threshold_does_not_trigger_at_two(ad_detector_config):
    detector = AdDetector(config=ad_detector_config, db=_RepeatSnapshotDB([
        _repeat_row(1, "进群演个二十", 40),
        _repeat_row(2, "进群演个二十", 5),
    ]))

    assert detector.check_consecutive_patterns(42, -1001)["is_spam"] is False


def test_one_hour_repeat_ignores_messages_outside_window(ad_detector_config):
    detector = AdDetector(config=ad_detector_config, db=_RepeatSnapshotDB([
        _repeat_row(1, "进群演个二十", 61),
        _repeat_row(2, "进群演个二十", 30),
        _repeat_row(3, "进群演个二十", 1),
    ]))

    assert detector.check_consecutive_patterns(42, -1001)["is_spam"] is False


@pytest.mark.parametrize("text", ["签到", "谢谢", "在吗", "666"])
def test_common_short_repeats_are_not_deleted(ad_detector_config, text):
    detector = AdDetector(config=ad_detector_config, db=_RepeatSnapshotDB([
        _repeat_row(1, text, 40),
        _repeat_row(2, text, 20),
        _repeat_row(3, text, 1),
    ]))

    assert detector.check_consecutive_patterns(42, -1001)["is_spam"] is False


def test_three_different_normal_questions_are_not_repeat_spam(ad_detector_config):
    detector = AdDetector(config=ad_detector_config, db=_RepeatSnapshotDB([
        _repeat_row(1, "今天几点开播", 40),
        _repeat_row(2, "这个功能怎么用", 20),
        _repeat_row(3, "积分在哪里查看", 1),
    ]))

    assert detector.check_consecutive_patterns(42, -1001)["is_spam"] is False


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


def test_same_city_pc_guarantee_incident_is_direct_ad(detector):
    """截图话术的 PC 暗语、交易审核和安全背书组合应作为正文直证。"""
    text = "同城PC，老师人工审核，平台担保交易，拒绝被骗，PC无忧！"

    result = detector.detect("", text)

    assert result["is_ad"] is True
    assert result["action"] == "ban"
    assert result["score"] >= SCORE_THRESHOLD


@pytest.mark.parametrize(
    "text",
    [
        "一台电脑养活你全家！挂机=印钞工厂！",
        "普通电脑变赚钱机器！挂机就是抢钱！",
        "手机放着挂机，睡觉也在进账",
        "电脑24小时开着，躺着也能赚钱",
        "挂机就能养活全家，懒人项目",
        "不用操作，电脑自己印钞",
    ],
)
def test_computer_idle_income_variants_are_direct_ad(detector, text):
    result = detector.detect("fanbai", text)

    assert result["is_ad"] is True
    assert result["action"] == "ban"
    assert result["score"] >= SCORE_THRESHOLD


@pytest.mark.parametrize(
    "text",
    [
        "电脑挂机后风扇很吵，怎么修？",
        "所谓印钞工厂是诈骗宣传，大家不要信。",
        "这台电脑是我工作用的，养活全家不容易。",
        "反诈提示：电脑挂机赚钱是骗局，大家不要信。",
        "新闻曝光：电脑挂机印钞工厂属于诈骗宣传。",
    ],
)
def test_computer_idle_printing_money_rule_preserves_normal_context(detector, text):
    assert detector.detect("", text)["is_ad"] is False


def test_idle_income_not_a_scam_evasion_stays_ad(detector):
    result = detector.detect("", "所谓电脑挂机印钞工厂不是骗局，肯干就来")

    assert result["is_ad"] is True
    assert result["action"] == "ban"


@pytest.mark.parametrize(
    "text",
    [
        "同城PC电脑维修，师傅人工审核后上门服务",
        "这家平台担保交易靠谱吗？大家注意拒绝被骗",
        "老师正在人工审核作业，PC电脑请保持开机",
        "同城PC装机无忧，支持硬件检测和系统安装",
    ],
)
def test_same_city_pc_rule_preserves_normal_computer_and_antifraud_text(detector, text):
    assert detector.detect("", text)["is_ad"] is False


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


@pytest.mark.parametrize(
    "text",
    [
        "微信代收 一天一W",
        "微信代收一天一w",
        "微 信 代 收 一天一Ｗ",
    ],
)
def test_screenshot_wechat_proxy_receipt_income_is_immediate_ad(detector, text):
    result = detector.detect(username="guanjing", msg=text)
    assert result["is_ad"] is True
    assert result["action"] == "ban"
    assert result["score"] >= SCORE_THRESHOLD


@pytest.mark.parametrize("text", ["我每天跑1万米", "微信业务怎么迁移", "一天跑1w米太累了"])
def test_income_shorthand_rule_does_not_match_normal_context(detector, text):
    """L3: 正常运动与微信业务讨论不因新规则被误判"""
    score, dims = detector._check_content_score(text)
    assert score == 0
    assert dims == []


@pytest.mark.parametrize(
    "text",
    [
        "微信代收3个快递，下午来拿",
        "公司微信代收货款，一天一万元流水",
        "微信代收业务一天一W营业额",
        "今天帮商户代付2笔货款",
        "公司一天1W营业额，微信代收货款",
        "门店一天10000元营业额，微信代收货款",
        "公司一天1万元流水，今天代付两笔货款",
    ],
)
def test_proxy_receipt_normal_business_context_is_not_ad(detector, text):
    result = detector.detect(username="正常用户", msg=text)
    assert result["is_ad"] is False
    assert result["score"] == 0


@pytest.mark.parametrize(
    "text",
    [
        "代收日结",
        "代付返佣",
        "代收有量",
        "代x收日结",
        "代1付返佣",
        "快递代收业务的费率是多少？",
        "公司代付通道今晚维护，请暂停操作",
        "请代收货物，门店今天接单很多",
        "代收点有量尺寸限制吗？",
        "帮我代付，返佣活动不参加",
    ],
)
def test_ambiguous_proxy_receipt_trade_words_do_not_convict_alone(detector, text):
    result = detector.detect(username="随机账号", msg=text)
    assert result["is_ad"] is False
    assert result["score"] == 0


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
    "display_name",
    [
        "KimberlySmith",
        "RobertSmith",
        "AliceSmith",
        "SmartPlayer",
        "SmileEveryDay",
        "Cosmos",
        "SM",
    ],
)
def test_sm_substring_or_standalone_abbreviation_is_not_ad_evidence(
    detector, display_name
):
    """普通英文姓名/单词中的 sm，以及无语境的 SM，都不能单独触发永久禁言。"""
    result = detector.detect(username=display_name, msg="")

    assert result["is_ad"] is False
    assert result["action"] != "ban"
    assert "色情引流" not in result["reason"]


@pytest.mark.parametrize(
    "text",
    [
        "SM交友，私聊了解",
        "SM 全套服务，私聊了解",
        "提供调教 SM 资源",
    ],
)
def test_bounded_sm_with_explicit_adult_solicitation_remains_ad(detector, text):
    """SM 仅在独立表达并与明确色情/招揽语义组合时保留高置信命中。"""
    result = detector.detect(username="普通昵称", msg=text)

    assert result["is_ad"] is True
    assert result["action"] == "ban"
    assert "色情引流" in result["reason"]


@pytest.mark.parametrize(
    "text",
    [
        "性格安静，不粘人、不查岗，长期稳定关系q裙：1092048570 QDPt",
        "Q裙：1092048570 学生 良家兼职 个人无定 有房可上门 eX",
        "长期稳定关系扣郡号-1O9204857O",
        "q郡 109 204 8570 个人兼职，有房可上门",
        "Q群：1092048570",
        "QQ群号 1092048570",
        "扣扣群-1092048570",
        "企鹅群：1092048570",
        "qqun:1092048570",
        "女大一枚，有户外露出小癖好,露 Q裙 1093995052 可以约哦 BFG",
        "户外露 x 出小癖好，q裙 109 399 5052 可 以 约",
        "Q郡:1O93995O52 私约，户外露x出",
        "户外露出小癖好，可以约，Q.裙 1093995052",
        "户外露出小癖好，可以约，Q裙 109,399,5052",
        "户外露出小癖好，可以约，Q裙 109/399/5052",
        "户外露出小癖好，可以约，Q裙 109·399·5052",
        "户外露出，可以约，Q裙 1093995052，服装订单号",
        "户外露出，可以约，Q裙 1093995052，摄影约拍",
        "户外露出，可以约，Q裙 1093995052，摄影服装订单号",
        "摄影业务：户外露出，可以约，Q裙 1093995052，服装订单号",
        "户外露出小癖好，可以约，Q裙 109  399 5052",
        "Q裙 1102445053 开课｜00后新下海｜自带科室·配合听话 kwPb",
        "q.裙 110 244 5053｜零零后新-下-海｜配 合 听 话",
        "扣郡号-1O92445O53 新下海，自带科室，配合听话",
    ],
)
def test_screenshot_qq_group_contact_variants_trigger_immediate_ban(detector, text):
    """L3/L4: QQ 群及关系招揽中的 q裙/扣郡变体必须首条进入统一处置"""
    result = detector.detect(username="普通昵称", msg=text)
    assert result["is_ad"] is True
    assert result["action"] == "ban"
    assert result["score"] >= SCORE_THRESHOLD
    assert "联系方式/引流" in result["reason"]


@pytest.mark.parametrize(
    "text",
    [
        "这条Q裙的尺码是109，订单号1092048570",
        "Q裙：1092048570订单号，麻烦查一下物流",
        "我在讨论Q群算法，不是群号",
        "企鹅群今天有109只",
        "长期稳定关系需要互相信任",
        "不粘人、不查岗只是我对相处方式的看法",
        "Q裙：12345",
        "户外露出摄影是一种创作题材，Q裙：1093995052订单号",
        "Q裙：1093995052订单号，户外服装可以约时间取货",
        "小癖好是户外摄影，可以约周末拍照，Q裙订单号1093995052",
        "户外露肩上衣出售，可以预约时间取货，Q裙 1093995052 是服装订单号",
        "户外露出主题摄影服装，可以约时间取货，Q裙 1093995052 是服装订单号",
        "班级Q裙 1102445053，Python 课程明晚开课",
        "Q裙 1102445053 是服装课程订单号，00后学生一起上课",
        "00后潜水员新下海训练，Q裙 1102445053 报名潜水课",
        "海训开课通知：配合教练、认真听话，Q裙 1102445053",
    ],
)
def test_qq_group_contact_variants_do_not_ban_normal_context(detector, text):
    """L4: 服装订单、算法、动物数量和普通关系表达不能被群号变体规则误封"""
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
        "六合名单有量找庄合作",
        "六肖单子有量找靠谱庄",
        "新澳门六叔公单子有量，有庄收吗？",
        "新澳六彩盒单子有量找庄合作",
        "新澳门六彩和单子有量，庄，家，来，收",
        "新澳门六彩和单子有量，庄,家,来,收",
        "新澳门六彩和单子有量，庄：家：来：收",
        "新澳门六彩和单子有量，庄·家·来·收",
        "新澳门六彩和单子有量，庄、家、来、收",
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
        "新澳门六x叔1公单x子有量，有庄收吗？",
        "六 x 叔 公单 子有 量，有 庄 收",
        "六/叔/公单/子有/量，有/庄/收",
        "六叔公单子有量，找靠谱庄",
        "六叔公单子有量，有庄家收",
        "六合名单有量找庄合作",
        "六肖单子有量找靠谱庄",
        "新澳门六叔公单子有量，有庄收，新闻曝光只是借口",
        "甲" * 41 + "新澳门六叔公单子有量，有庄收吗？",
        "新闻曝光：新澳门六叔公单子有量，有庄收吗？",
        "教学案例：新澳门六叔公单子有量，有庄收吗？",
        "反诈提示：新澳门六叔公单子有量，有庄收吗？",
        "包装发货：新澳门六叔公单子有量，有庄收吗？",
        "新澳门六叔公单子有量，有庄收，包装发货",
        "新澳门六叔公单子有量，有庄收，水果物流",
        "新澳六彩盒单子有量找庄合作，包装发货",
        "六叔公单子有量，有庄收，物流",
        "六叔公单子有量，有庄收，包装发货",
        "六彩盒单子有量，庄家合作包装发货",
        "六彩盒包装单子有量，找庄合作发货",
        "六叔公的水果单子有量，有庄收，农庄收货",
        "新闻曝光：六叔公单子有量，有庄收，不是诈骗",
        "媒体报道：六叔公单子有量，有庄收，绝非诈骗话术",
        "反诈提示：六叔公单子有量，有庄收，并非灰产引流",
        "教学案例：六叔公单子有量，有庄收，不属于非法活动",
        "新闻曝光：六叔公单子有量，有庄收，警方未查处",
        "新闻曝光：六叔公单子有量，有庄收，警方尚未立案",
        "新闻曝光：六叔公单子有量，有庄收，警方没有破获",
        "新闻曝光：六叔公单子有量，有庄收，警方并未破获",
        "新闻曝光：六叔公单子有量，有庄收，非诈骗话术",
        "新闻曝光：六叔公单子有量，有庄收，警方并没有查处",
        "新闻曝光：六叔公单子有量，有庄收，此前是诈骗，现在不是诈骗",
        "媒体报道：六叔公单子有量，有庄收，警方已查处，后来并未查处",
        "新闻曝光：六叔公单子有量，有庄收，此前是诈骗现在不是诈骗",
        "媒体报道：六叔公单子有量，有庄收，警方已查处后来并未查处",
        "庄家合作：单子有量的新澳六彩盒",
        "找庄合作收单，六x肖1码货量充足",
        "收庄：六彩和单子有量",
        "新 澳 门 六 彩 和 单 子 有 量，庄 家 来 收",
        "新澳门六彩和单子有量，农 庄 家 来 收",
        "新澳门六彩和单子有量，农x庄家来收",
        "新澳门六彩和单子有量，村 庄 家 来 收",
        "新澳门六彩和单子有量，山 庄 家 来 收",
        "新澳门六彩和单子有量，庄，家，来，收",
        "新澳门六彩和单子有量，庄·家·来·收",
        "新澳门六彩和单子有量，庄、家、来、收",
    ],
)
def test_lottery_trade_rule_supports_obfuscation_and_reverse_order(detector, text):
    """L3: 彩票灰产三要素允许有限拆字及正反语序，仍须即时达到阈值"""
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
        "六叔公周末会来家里吃饭",
        "新闻曝光：澳门六合彩私彩团伙已被查处",
        "六彩盒包装订单有量，工厂正在排产",
        "生肖六码教学只是组合数学练习",
        "我们在找合作伙伴讨论新店开业",
        "新澳门的景点新闻刚发布",
        "六叔公的水果单子有量，农庄收货",
        "六彩盒包装单子有量，庄家合作发货",
        "媒体报道：六叔公单子有量，有庄收，警方已立案",
        "语文教学引用：六叔公单子有量，有庄收是诈骗话术",
        "新闻曝光：六叔公单子有量，有庄收，警方已查处",
        "反诈提示：六叔公单子有量，有庄收属于诈骗引流",
        "新闻曝光：六叔公单子有量，有庄收，这并非普通交易，而是诈骗话术",
        "反诈提示：六叔公单子有量，有庄收，这不是正常合作，而是非法引流活动",
        "新闻曝光：六叔公单子有量，有庄收，并非普通交易，而是诈骗",
        "反诈提示：六叔公单子有量，有庄收，不是正常合作，实为灰产",
        "教学案例：六叔公单子有量，有庄收，这是诈骗话术，不过细节仍待公布",
        "媒体报道：六叔公单子有量，有庄收，警方已查处，但更多案情待公布",
        "新闻曝光：六叔公单子有量，有庄收，这不是普通交易，是诈骗",
        "媒体报道：六叔公单子有量，有庄收，警方尚未查处，但后来已查处",
        "反诈提示：六叔公单子有量，有庄收，属于诈骗，但不是灰产",
        "新闻曝光：六叔公单子有量，有庄收，此前不是诈骗，现在是诈骗",
        "媒体报道：六叔公单子有量，有庄收，警方未查处，后来已查处",
        "新闻曝光：六叔公单子有量，有庄收，此前不是诈骗现在是诈骗",
        "反诈提示：六叔公单子有量，有庄收，此前不是灰产现在是灰产",
        "教学案例：六叔公单子有量，有庄收，此前不是非法现在是非法",
        "媒体报道：六叔公单子有量，有庄收，警方未查处后来已查处",
        "六叔公水果单子有量，农庄收购",
        "六叔公的水果单子有量，农 庄 收 货",
        "六叔公水果单子有量，农 庄 来 收货",
        "六叔公水果单子有量，农    庄 收货",
        "六叔公水果单子有量，农                              庄 收货",
        "六叔公水果单子有量，农 庄 来 收水果",
        "六叔公水果单子有量，农 庄 来 收这批货",
        "六叔公水果单子有量，酒庄来收货",
        "六叔公水果单子有量，茶庄来收货",
        "六叔公水果单子有量，酒庄来收葡萄",
        "六叔公水果单子有量，茶庄来收茶叶",
        "六叔公水果单子有量，村庄来收物资",
        "六叔公水果单子有量，农x庄来收货",
        "六叔公水果单子有量，农 庄 合作收购",
        "六叔公水果单子有量，村庄来收货",
        "六叔公水果单子有量，山庄来收货",
        "六彩盒包装单子有量，庄家合作设计新包装",
        "六合区水果单子有量，找农庄合作收购",
        "六叔公水果单子有量，农庄采购买货",
        "六彩盒包装订单单子有量，庄家合作，工厂排产发货",
        "六合名单有量" + "甲" * 41 + "找庄合作",
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


def test_screenshot_plane_earn_money_look_at_me_triggers_immediate_ban(detector):
    """截图原文“飞机赚米看我”首条必须拦截，不能进入 AI 回复。"""
    result = detector.detect(username="Tony Rogers", msg="飞机赚米看我", bio="")

    assert result["is_ad"] is True
    assert result["action"] == "ban"
    assert result["score"] >= SCORE_THRESHOLD


@pytest.mark.parametrize(
    "text",
    [
        "我坐飞机去米兰看朋友",
        "这个飞机模型能赚积分，看我的教程",
        "坐飞机时看我刚下载的电影",
        "游戏里赚米的方法看攻略就行",
    ],
)
def test_plane_and_look_at_me_normal_contexts_are_not_ads(detector, text):
    result = detector.detect(username="普通用户", msg=text, bio="")
    assert result["is_ad"] is False
    assert result["score"] == 0


@pytest.mark.parametrize(
    "text",
    [
        "港澳1-49特码有量，有收的吗?",
        "港澳1-49特码有量，有收的庄吗？",
        "六码名单有量，找靠谱庄",
        "六彩合单子有量，找靠谱庄",
        "新澳门六叔公单子有量，有庄收吗？",
        "新澳六彩盒单子有量找庄合作",
    ],
)
def test_screenshot_lottery_ads_trigger_immediate_ban_on_first_message(detector, text):
    """L4: 彩票交易广告不能依赖重复消息或累计追踪，首条必须直接封禁"""
    result = detector.detect(username="财神", msg=text)
    assert result["is_ad"] is True
    assert result["action"] == "ban"
    assert result["score"] >= SCORE_THRESHOLD
    assert "灰色产业" in result["reason"]


@pytest.mark.parametrize(
    "text",
    [
        "新澳门六彩和单子有量，庄，家，来，收",
        "新澳门六彩和单子有量，庄,家,来,收",
        "新澳门六彩和单子有量，庄：家：来：收",
        "新澳门六彩和单子有量，庄·家·来·收",
        "新澳门六彩和单子有量，庄、家、来、收",
    ],
)
def test_lottery_separator_obfuscation_reaches_public_detect(detector, text):
    """NFKC 后的真实 detect 入口也必须拦截中文/ASCII 标点拆字。"""
    result = detector.detect(username="普通用户", msg=text)
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
