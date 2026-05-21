# -*- coding: utf-8 -*-
"""
[Trae] 头像检测模块
检测用户头像是否为色情/违规图片
"""

import io
import logging
from typing import Optional, Tuple

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

logger = logging.getLogger("avatar_detector")


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
            
            # 计算平均颜色（简化版）
            r_avg = sum(histogram[0:256]) / 256
            g_avg = sum(histogram[256:512]) / 256
            b_avg = sum(histogram[512:768]) / 256
            
            # 肤色检测启发式（简化版）
            # 肤色通常在 R>G>B 且 R 在 100-200 范围
            if r_avg > g_avg > b_avg and 80 < r_avg < 220:
                # 进一步检查红色/粉色比例
                total_pixels = width * height
                skin_like = sum(1 for i in range(0, 256) if 100 < i < 200 and histogram[i] > total_pixels * 0.01)
                if skin_like > 50:
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


def check_and_ban_if_porn_avatar(bot, user_id: int, chat_id: int, user_name: str = "") -> bool:
    """
    检查头像并禁言（如果检测到色情头像）
    返回: 是否执行了禁言
    """
    is_suspicious, reason = check_user_avatar(bot, user_id)
    
    if is_suspicious:
        try:
            bot.restrict_chat_member(
                chat_id, user_id,
                until_date=0,
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
            )
            logger.warning(f"🚫 头像检测禁言：{user_name}({user_id}) 原因：{reason}")
            return True
        except Exception as e:
            logger.error(f"头像检测禁言失败 {user_name}({user_id}): {e}")
    
    return False
