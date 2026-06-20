# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/pinyin_util.py  ·  拼音无声调转换工具（v5.23.0 P0-2）               ║
║                                                                            ║
║  功能：                                                                    ║
║    将中文文本转为无声调拼音，用于检测 "wo shi AI" 等变体穿帮。              ║
║                                                                            ║
║  依赖：                                                                    ║
║    优先使用 pypinyin（若已安装），否则回退到内置简易映射表。                ║
║    简易映射表覆盖常见穿帮词，不追求全字符覆盖。                             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

# 内置简易拼音映射表（覆盖穿帮检测所需的高频字）
# 不追求完整，只覆盖"我是人工智能/作为AI模型/助手/程序/机器人"等穿帮场景
_SIMPLIFIED_PINYIN = {
    # 我是
    '我': 'wo', '是': 'shi', '的': 'de', '了': 'le', '在': 'zai',
    # 人工智能
    '人': 'ren', '工': 'gong', '智': 'zhi', '能': 'neng',
    # 作为
    '作': 'zuo', '为': 'wei',
    # 模型
    '模': 'mo', '型': 'xing',
    # 助手
    '助': 'zhu', '手': 'shou',
    # 程序
    '程': 'cheng', '序': 'xu',
    # 机器人
    '机': 'ji', '器': 'qi',
    # 其他高频
    '一': 'yi', '个': 'ge', '这': 'zhe', '那': 'na', '不': 'bu',
    '会': 'hui', '可': 'ke', '以': 'yi', '有': 'you', '没': 'mei',
    '说': 'shuo', '话': 'hua', '给': 'gei', '想': 'xiang', '要': 'yao',
    '能': 'neng', '够': 'gou', '帮': 'bang', '忙': 'mang',
    '请': 'qing', '问': 'wen', '答': 'da', '回': 'hui', '复': 'fu',
    '大': 'da', '小': 'xiao', '多': 'duo', '少': 'shao',
    '好': 'hao', '坏': 'huai', '对': 'dui', '错': 'cuo',
    '来': 'lai', '去': 'qu', '上': 'shang', '下': 'xia',
    '前': 'qian', '后': 'hou', '里': 'li', '外': 'wai',
    '他': 'ta', '她': 'ta', '它': 'ta', '们': 'men',
    '你': 'ni', '您': 'nin', '谁': 'shui', '什': 'shen', '么': 'me',
    '怎': 'zen', '样': 'yang', '为': 'wei', '啥': 'sha',
    # 穿帮相关
    '系': 'xi', '统': 'tong', '软': 'ruan', '件': 'jian',
    '代': 'dai', '码': 'ma', '算': 'suan', '法': 'fa',
    '自': 'zi', '动': 'dong', '运': 'yun', '行': 'xing',
}

# 尝试导入 pypinyin
try:
    from pypinyin import lazy_pinyin, Style
    _HAS_PYPINYIN = True
except ImportError:
    _HAS_PYPINYIN = False


def text_to_pinyin_silent(text: str) -> str:
    """
    将中文文本转为无声调拼音字符串（词间用空格分隔）。

    Args:
        text: 中文文本

    Returns:
        无声调拼音字符串，如 "wo shi ai" / "ren gong zhi neng"

    依赖策略：
        1. 优先用 pypinyin（完整覆盖）
        2. 回退到内置简易映射表（覆盖穿帮检测高频字）
    """
    if not text:
        return ""

    if _HAS_PYPINYIN:
        try:
            parts = lazy_pinyin(text, style=Style.NORMAL)
            return " ".join(parts)
        except Exception:
            pass

    # 回退：内置简易映射表
    result = []
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            pinyin = _SIMPLIFIED_PINYIN.get(char, '')
            if pinyin:
                result.append(pinyin)
        elif char.isalpha() or char.isspace():
            result.append(char.lower())
    return " ".join(result)


def has_pinyin_leak(text: str, leak_patterns: list = None) -> bool:
    """
    检测文本拼音中是否包含穿帮词。

    Args:
        text: 待检测文本
        leak_patterns: 穿帮词拼音列表，默认使用内置列表

    Returns:
        True 检测到穿帮，False 安全
    """
    if not text:
        return False

    if leak_patterns is None:
        leak_patterns = [
            'wo shi ai', 'wo shi a i',
            'ren gong zhi neng',
            'zuo wei ai', 'zuo wei a i',
            'zuo wei mo xing', 'wo shi mo xing',
            'wo shi ge cheng xu', 'zuo wei zhu shou',
            'wo shi zhu shou', 'wo shi ge ji qi ren',
            'ji qi ren', 'zuo wei ge cheng xu',
        ]

    pinyin_text = text_to_pinyin_silent(text).lower()
    for pat in leak_patterns:
        if pat in pinyin_text:
            return True
    return False
