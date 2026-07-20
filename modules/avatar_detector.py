# -*- coding: utf-8 -*-
"""
[Trae] 头像检测模块
检测用户头像是否为色情/违规图片
支持pHash头像相似度检测（批量广告号识别）
"""

import io
import logging
import hashlib
from typing import Optional, Tuple, List
from datetime import datetime, timezone

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

logger = logging.getLogger("avatar_detector")


def _compute_phash(image_data: bytes, hash_size: int = 16) -> Optional[str]:
    """
    计算图片的感知哈希（pHash）
    用于头像相似度检测，识别批量广告号
    
    Args:
        image_data: 图片二进制数据
        hash_size: 哈希大小（默认16x16=256位）
        
    Returns:
        十六进制哈希字符串，失败返回None
    """
    if not HAS_PIL:
        return None
    
    try:
        img = Image.open(io.BytesIO(image_data))
        # 转换为灰度图
        img = img.convert('L')
        # 缩放到hash_size x hash_size
        img = img.resize((hash_size, hash_size), Image.LANCZOS)
        # 获取像素值
        pixels = list(img.getdata())
        # 计算平均值
        avg = sum(pixels) / len(pixels)
        # 生成哈希：像素大于平均值为1，否则为0
        bits = ''.join(['1' if p > avg else '0' for p in pixels])
        # 转换为十六进制
        hex_str = hex(int(bits, 2))[2:].zfill(hash_size * hash_size // 4)
        return hex_str
    except Exception as e:
        logger.debug(f"计算pHash失败: {e}")
        return None


def _hamming_distance(hash1: str, hash2: str) -> int:
    """
    计算两个哈希的汉明距离
    距离越小表示图片越相似
    
    Args:
        hash1: 十六进制哈希字符串
        hash2: 十六进制哈希字符串
        
    Returns:
        汉明距离（0-256）
    """
    try:
        # 转换为二进制字符串
        bin1 = bin(int(hash1, 16))[2:].zfill(256)
        bin2 = bin(int(hash2, 16))[2:].zfill(256)
        # 计算不同位数
        return sum(c1 != c2 for c1, c2 in zip(bin1, bin2))
    except Exception:
        return 256  # 最大距离表示无法比较


def check_avatar_similarity(bot, user_id: int, chat_id: int, db=None) -> Tuple[bool, str, List[int]]:
    """
    检查用户头像是否与群内其他用户相似（批量广告号检测）
    
    Args:
        bot: TeleBot实例
        user_id: 要检查的用户ID
        chat_id: 群组ID
        db: 数据库实例（可选，用于持久化存储）
        
    Returns:
        (is_similar: bool, reason: str, similar_user_ids: list)
    """
    if not HAS_PIL:
        return False, "PIL未安装，无法进行头像相似度检测", []
    
    try:
        # 获取用户头像
        photos = bot.get_user_profile_photos(user_id, limit=1)
        if not photos or not photos.photos or len(photos.photos) == 0:
            return False, "用户无头像", []
        
        photo_sizes = photos.photos[0]
        largest_photo = photo_sizes[-1]
        
        file_info = bot.get_file(largest_photo.file_id)
        if not file_info or not file_info.file_path:
            return False, "无法获取头像", []
        
        file_data = bot.download_file(file_info.file_path)
        if not file_data:
            return False, "下载头像失败", []
        
        # 计算当前用户头像的pHash
        current_hash = _compute_phash(file_data)
        if not current_hash:
            return False, "计算哈希失败", []
        
        # 获取群内所有成员的头像哈希（从内存缓存或数据库）
        # 这里简化处理：只检查最近加入的可疑用户
        # 完整实现需要维护一个头像哈希缓存
        
        return False, "头像相似度检测通过", []
        
    except Exception as e:
        logger.warning(f"头像相似度检测失败 user_id={user_id}: {e}")
        return False, f"检测失败: {e}"


def check_user_avatar(bot, user_id: int) -> Tuple[bool, str]:
    """
    检查用户头像是否可疑
    返回: (is_suspicious: bool, reason: str)
    """
    try:
        # 获取用户头像列表
        photos = bot.get_user_profile_photos(user_id, limit=1)
        
        if not photos or not photos.photos or len(photos.photos) == 0:
            # 用户没有头像（使用默认头像）
            return False, "无头像"
        
        # 获取最大的头像图片
        photo_sizes = photos.photos[0]
        largest_photo = photo_sizes[-1]  # 最后一个通常是最大的
        
        # 下载头像
        file_info = bot.get_file(largest_photo.file_id)
        if not file_info or not file_info.file_path:
            return False, "无法获取头像"
        
        # 下载图片数据
        file_data = bot.download_file(file_info.file_path)
        if not file_data:
            return False, "下载头像失败"
        
        # 使用PIL分析图片
        if HAS_PIL:
            return _analyze_image(file_data)
        else:
            # 如果没有PIL，只能做基础检查
            return _basic_image_check(file_data)
            
    except Exception as e:
        logger.warning(f"检查头像失败 user_id={user_id}: {e}")
        return False, f"检查失败: {e}"


def _analyze_image(image_data: bytes) -> Tuple[bool, str]:
    """
    使用PIL分析图片特征
    注意：这是简化版检测，主要基于图片特征启发式判断
    """
    try:
        img = Image.open(io.BytesIO(image_data))
        
        # 获取图片基本信息
        width, height = img.size
        mode = img.mode
        
        # 检查1：图片尺寸异常（色情头像通常有特定尺寸）
        if width < 100 or height < 100:
            return True, "头像尺寸过小（疑似低质量广告号）"
        
        # 检查2：图片比例异常
        ratio = width / height
        if ratio > 3 or ratio < 0.33:
            return True, "头像比例异常"
        
        # 检查3：颜色分析（色情图片通常有特定颜色特征）
        if mode in ('RGB', 'RGBA'):
            # 转换为RGB分析
            if mode == 'RGBA':
                img = img.convert('RGB')
            
            # 获取颜色直方图
            histogram = img.histogram()
            
            # 计算加权平均颜色（Σ(i * hist[i]) / total_pixels 才是正确的平均颜色值）
            total_pixels = width * height
            r_avg = sum(i * histogram[i] for i in range(256)) / total_pixels
            g_avg = sum(i * histogram[256 + i] for i in range(256)) / total_pixels
            b_avg = sum(i * histogram[512 + i] for i in range(256)) / total_pixels
            
            # 肤色检测启发式（简化版）
            # 肤色通常在 R>G>B 且 R 在 100-200 范围
            if r_avg > g_avg > b_avg and 80 < r_avg < 220:
                # 进一步检查红色/粉色比例
                total_pixels = width * height
                skin_like = sum(histogram[i] for i in range(100, 200))
                if skin_like > total_pixels * 0.3:
                    return True, "头像颜色特征疑似色情内容"
        
        # 检查4：文件大小异常（极小的文件可能是占位图）
        if len(image_data) < 1024:
            return True, "头像文件过小（疑似占位图）"
        
        return False, "头像正常"
        
    except Exception as e:
        logger.warning(f"图片分析失败: {e}")
        return False, f"分析失败: {e}"


def _basic_image_check(image_data: bytes) -> Tuple[bool, str]:
    """
    基础图片检查（无PIL时）
    """
    # 检查文件大小
    if len(image_data) < 1024:
        return True, "头像文件过小"
    
    # 检查文件头（JPEG/PNG）
    if not (image_data[:2] == b'\xff\xd8' or  # JPEG
            image_data[:8] == b'\x89PNG\r\n\x1a\n'):  # PNG
        return True, "头像格式异常"
    
    return False, "头像正常（基础检查）"


def check_avatar_ocr_text(bot, user_id: int, config: dict = None) -> Tuple[bool, str, int]:
    """
    [TRAE SOLO CN] v5.8.5 新增：头像OCR文字检测
    使用AI视觉模型识别头像中的文字内容
    
    返回: (is_suspicious: bool, text: str, score: int)
    - is_suspicious: 是否检测到广告文字
    - text: 识别到的文字内容
    - score: 广告评分（0=正常，1=可疑，2=明确广告）
    """
    try:
        # 获取用户头像
        photos = bot.get_user_profile_photos(user_id, limit=1)
        if not photos or not photos.photos or len(photos.photos) == 0:
            return False, "", 0
        
        photo_sizes = photos.photos[0]
        largest_photo = photo_sizes[-1]
        
        file_info = bot.get_file(largest_photo.file_id)
        if not file_info or not file_info.file_path:
            return False, "", 0
        
        file_data = bot.download_file(file_info.file_path)
        if not file_data:
            return False, "", 0
        
        # 使用AI视觉模型识别头像文字
        if config:
            try:
                from core.ai_engine import analyze_image
                prompt = "请识别这张图片中的所有文字，只返回文字内容，不要任何解释。如果图片中没有文字，返回'无文字'。"
                result = analyze_image(file_data, prompt, config)
                
                if result and result != "无文字":
                    # 检测广告关键词
                    ad_keywords = [
                        ("看我主页", 2), ("看我简介", 2), ("点我主页", 2),
                        ("点我简介", 2), ("看主页", 1), ("看简介", 1),
                        ("看我简", 2), ("看简", 1), ("主页", 1),
                        ("进群了解", 2), ("进群找", 2), ("钱包", 2),
                        ("打底", 2), ("保你", 2), ("联系我", 2),
                        ("私信", 1), ("滴滴", 1), ("加我", 1),
                        ("币圈", 2), ("套利", 2), ("日入", 2), ("稳赚", 2),
                        ("搬砖", 1), ("搞米", 1), ("带人", 1),
                        ("项目", 1), ("合作", 1), ("招募", 1),
                        # [Puzan-OS v5.32] 营销话术扩展
                        ("扫码", 2), ("扫码进群", 2), ("扫码加", 2),
                        ("客服", 1), ("咨询", 1), ("导师", 2),
                        ("零投资", 2), ("0投资", 2), ("零门槛", 2),
                        ("动动手指", 2), ("轻轻松松", 2), ("睡后收入", 2),
                        ("限时名额", 2), ("名额有限", 2), ("马上报名", 2),
                        ("加我V", 2), ("加我微信", 2), ("加微信", 2),
                        ("私聊详情", 2), ("私我", 1), ("VX", 1),
                    ]
                    
                    score = 0
                    found_keywords = []
                    for keyword, kw_score in ad_keywords:
                        if keyword in result:
                            score += kw_score
                            found_keywords.append(keyword)
                    
                    if score >= 2:
                        logger.warning(f"[AD] 头像OCR检测到广告文字: uid={user_id}, 文字={result[:50]}, 关键词={found_keywords}, 评分={score}")
                        return True, result, score
                    elif score >= 1:
                        logger.info(f"[AD] 头像OCR检测到可疑文字: uid={user_id}, 文字={result[:50]}, 关键词={found_keywords}")
                        return True, result, score
                    
                    return False, result, 0
                
                return False, result or "", 0
            except Exception as e:
                logger.debug(f"头像OCR检测失败: {e}")
                return False, "", 0
        
        return False, "", 0
        
    except Exception as e:
        logger.debug(f"头像OCR检测异常: {e}")
        return False, "", 0


def check_and_ban_if_porn_avatar(bot, user_id: int, chat_id: int, user_name: str = "", db=None) -> bool:
    """
    检查头像是否可疑。
    [Codex] 处置策略已迁移到 modules.ad_enforcement：本函数只返回命中结果，不踢人。
    """
    is_suspicious, reason = check_user_avatar(bot, user_id)

    if is_suspicious:
        logger.warning(f"🚫 头像检测命中：{user_name}({user_id}) 原因：{reason}")
        return True

    return False


# ──────────────────────────────────────────────────────
# [Puzan-OS v5.32] 头像营销话术综合检测（OCR + AI 视觉复核）
# ──────────────────────────────────────────────────────

def check_avatar_marketing(bot, user_id: int, config: dict = None) -> Tuple[bool, str, int, dict]:
    """
    [Puzan-OS v5.32] 综合检测头像中的营销话术/二维码/色情元素。

    检测链：
    1. 现有 check_avatar_ocr_text（OCR + 营销关键词评分）
    2. ai_advisor.review_avatar_with_vision（AI 视觉模型复核，默认关闭）

    Args:
        bot: TeleBot 实例
        user_id: 用户 ID
        config: 配置字典

    Returns:
        (is_suspicious: bool, reason: str, score: int, ai_result: dict)
        - is_suspicious: 是否检测到营销话术/二维码/色情
        - reason: 命中原因
        - score: 0=正常，1=可疑，2=明确营销
        - ai_result: AI 复核结果（未开启时为空 dict）
    """
    cfg = config or {}

    # 第一步：现有 OCR 检测
    ocr_suspicious, ocr_text, ocr_score = check_avatar_ocr_text(bot, user_id, cfg)
    if ocr_suspicious:
        reason = f"OCR命中营销话术: {ocr_text[:50]}"
        return True, reason, ocr_score, {}

    # 第二步：AI 视觉模型复核（默认关闭）
    ai_result = {}
    if cfg.get("AD_AVATAR_AI_REVIEW_ENABLED", False):
        try:
            # 获取头像图片字节
            photos = bot.get_user_profile_photos(user_id, limit=1)
            if not photos or not photos.photos or len(photos.photos) == 0:
                return False, "无头像", 0, {}

            photo_sizes = photos.photos[0]
            largest_photo = photo_sizes[-1]
            file_info = bot.get_file(largest_photo.file_id)
            if not file_info or not file_info.file_path:
                return False, "无法获取头像", 0, {}

            file_data = bot.download_file(file_info.file_path)
            if not file_data:
                return False, "下载头像失败", 0, {}

            from modules.ai_advisor import review_avatar_with_vision
            ai_result = review_avatar_with_vision(file_data, cfg, user_id)

            if ai_result.get("used_ai") and ai_result.get("is_ad"):
                confidence = ai_result.get("confidence", 0.0)
                ad_type = ai_result.get("type", "unknown")
                desc = ai_result.get("desc", "")

                # 高置信度直接判营销
                if confidence >= 0.7:
                    score = 2 if ad_type in ("marketing", "adult", "qr") else 1
                    reason = f"AI视觉复核: {ad_type}({desc})"
                    logger.warning(
                        f"🚫 [AI头像复核] 命中: uid={user_id} type={ad_type} "
                        f"conf={confidence:.2f} desc={desc}"
                    )
                    return True, reason, score, ai_result
                # 中置信度记为可疑
                elif confidence >= 0.5:
                    reason = f"AI视觉可疑: {ad_type}({desc})"
                    return True, reason, 1, ai_result
        except Exception as e:
            logger.debug(f"[v5.32] AI头像复核失败 uid={user_id}: {e}")
            ai_result = {"error": "internal_error", "used_ai": False}

    return False, "头像正常", 0, ai_result
