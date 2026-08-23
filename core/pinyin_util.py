# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/pinyin_util.py  ·  拼音无声调转换工具（v5.23.0 P0-2）               ║
║                                                                            ║
║  功能：                                                                    ║
║    将中文文本转为无声调拼音，用于检测 "wo shi AI" 等变体穿帮。              ║
║                                                                            ║
║  依赖（v5.41.0）：                                                         ║
║    统一使用 pypinyin（已列入 requirements.in 正式依赖）。                   ║
║    历史上的内置简易映射表（约82字 + 重复键）已删除——                        ║
║    手写映射表是自造轮子且有覆盖缺口，pypinyin 为成熟开源实现。              ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import logging

from pypinyin import lazy_pinyin, Style

logger = logging.getLogger(__name__)


def text_to_pinyin_silent(text: str) -> str:
    """
    将中文文本转为无声调拼音字符串（词间用空格分隔）。

    Args:
        text: 中文文本

    Returns:
        无声调拼音字符串，如 "wo shi ai" / "ren gong zhi neng"
    """
    if not text:
        return ""
    return " ".join(lazy_pinyin(text, style=Style.NORMAL))
