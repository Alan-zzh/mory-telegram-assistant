# -*- coding: utf-8 -*-
"""
[Trae] v5.16.1 广告检测模式补充单测
- USERNAME_PATTERNS: '看我简个'/'看我简jie'/'看简个'/'看我简接' 等变体
- BIO_PATTERNS: '一天保X万'/'数字+打底'/'带X钱包'/'想做兄弟'/'进群找了解' 等核心骗术
"""
import re
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from modules.ad_patterns_encoded import USERNAME_PATTERNS, BIO_PATTERNS


def match_any(patterns, text):
    """返回命中的所有 pattern（不抛异常）"""
    hit = []
    for pat in patterns:
        try:
            if re.search(pat, text, re.IGNORECASE):
                hit.append(pat)
        except re.error:
            pass
    return hit


class TestUsernamePatternV5161:
    """[Trae] v5.16.1 USERNAME_PATTERNS 看简简介 变体"""

    def test_kanwo_jiangejieren_user_case(self):
        """用户最新案例：星河入梦来🐻Pawar 看我简个 - 必须命中"""
        text = "星河入梦来 🐻 Pawar 看我简个"
        hit = match_any(USERNAME_PATTERNS, text)
        assert hit, f"必须命中: {text!r}"

    def test_kanwo_jiange(self):
        """看我简个 - 标准变体"""
        assert match_any(USERNAME_PATTERNS, "看我简个")

    def test_kanwo_jianjie(self):
        """看我简介 - 标准"""
        assert match_any(USERNAME_PATTERNS, "看我简介")

    def test_kanwo_jianjie_pinyin(self):
        """看我简jie - 拼音变体"""
        assert match_any(USERNAME_PATTERNS, "看我简jie")

    def test_kanwo_jianjie_jianjie(self):
        """看我jianjie - 全拼音"""
        assert match_any(USERNAME_PATTERNS, "看我jianjie")

    def test_kanjianjie_yuqi(self):
        """看我简介呀 - 语气词后缀"""
        assert match_any(USERNAME_PATTERNS, "看我简介呀")

    def test_kanjianjie_short(self):
        """看简介 - 简化版本"""
        assert match_any(USERNAME_PATTERNS, "看简介")

    def test_kanwo_zhuye(self):
        """看我主页 - 主页版本"""
        assert match_any(USERNAME_PATTERNS, "看我主页")

    def test_kanjiange_short(self):
        """看简个 - 短变体"""
        assert match_any(USERNAME_PATTERNS, "看简个")

    def test_kanwo_jianjie_variant(self):
        """看我简接 - 变体"""
        assert match_any(USERNAME_PATTERNS, "看我简接")

    def test_kanjianjie_emoji(self):
        """看简介👀 - emoji后缀"""
        assert match_any(USERNAME_PATTERNS, "看简介👀")

    def test_lianwo_daifei(self):
        """联系我带你启飞 - 旧有规则覆盖"""
        assert match_any(USERNAME_PATTERNS, "联系我带你启飞")

    def test_normal_user_not_match(self):
        """辛辛🌸 FF - 正常账号 - 不能误判"""
        assert not match_any(USERNAME_PATTERNS, "辛辛🌸 FF"), "正常账号被误判"

    def test_normal_user2_not_match(self):
        """日常分享生活 - 正常账号 - 不能误判"""
        assert not match_any(USERNAME_PATTERNS, "日常分享生活"), "正常账号被误判"

    def test_normal_user3_not_match(self):
        """摄影爱好者 - 正常账号 - 不能误判"""
        assert not match_any(USERNAME_PATTERNS, "摄影爱好者"), "正常账号被误判"

    def test_normal_user4_not_match(self):
        """学生小李 - 正常账号 - 不能误判"""
        assert not match_any(USERNAME_PATTERNS, "学生小李"), "正常账号被误判"


class TestBioPatternV5161:
    """[Trae] v5.16.1 BIO_PATTERNS 核心骗术关键词"""

    def test_user_first_case(self):
        """用户首案例完整 bio - 必须命中"""
        bio = "带两个钱包的兄弟，只要你肯付出，一天保你一万打底，想做的兄弟，进群找了解:https://t.me/+MSy0o4bsUMlkyjc1"
        hit = match_any(BIO_PATTERNS, bio)
        assert hit, f"必须命中: {bio!r}"

    def test_dai_jiange(self):
        """带两个钱包 - 双钱包骗术"""
        assert match_any(BIO_PATTERNS, "带两个钱包的兄弟")

    def test_yitian_baoni(self):
        """一天保你一万 - 核心骗术"""
        assert match_any(BIO_PATTERNS, "一天保你一万")

    def test_dadi_zhifu(self):
        """一万打底 - 数字+打底"""
        assert match_any(BIO_PATTERNS, "一万打底")

    def test_xiangzuo_xiongdi(self):
        """想做的兄弟 - 招募话术"""
        assert match_any(BIO_PATTERNS, "想做的兄弟看过来")

    def test_jinqun_zhaoliaojie(self):
        """进群找了解 - 进群+了解"""
        assert match_any(BIO_PATTERNS, "进群找了解")

    def test_riru_3k(self):
        """日入3K - 旧有规则"""
        assert match_any(BIO_PATTERNS, "日入3K，有意私聊")

    def test_yitiangan_1000u(self):
        """一天干1000U - 旧有规则"""
        assert match_any(BIO_PATTERNS, "一天干1000U")

    def test_shualiwu_jiunengzhuan(self):
        """刷礼物就能赚 - 旧有规则"""
        assert match_any(BIO_PATTERNS, "刷礼物就能赚")

    def test_huanying_didi(self):
        """欢迎滴滴 - 旧有规则"""
        assert match_any(BIO_PATTERNS, "欢迎私信滴滴")

    def test_tme_link(self):
        """t.me/+... - 旧有规则"""
        assert match_any(BIO_PATTERNS, "Telegram引流：t.me/abc123")

    def test_normal_bio1_not_match(self):
        """今天 6:34 上线 - 正常 - 不能误判"""
        assert not match_any(BIO_PATTERNS, "今天 6:34 上线"), "正常 bio 被误判"

    def test_normal_bio2_not_match(self):
        """这是一段普通自我介绍 - 正常 - 不能误判"""
        assert not match_any(BIO_PATTERNS, "这是一段普通自我介绍"), "正常 bio 被误判"

    def test_normal_bio3_not_match(self):
        """喜欢读书和旅行 - 正常 - 不能误判"""
        assert not match_any(BIO_PATTERNS, "喜欢读书和旅行"), "正常 bio 被误判"

    def test_normal_bio4_not_match(self):
        """日常记录生活点滴 - 正常 - 不能误判"""
        assert not match_any(BIO_PATTERNS, "日常记录生活点滴"), "正常 bio 被误判"
