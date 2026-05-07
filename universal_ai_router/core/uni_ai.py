# 项目：universal_ai_router | 版本：v1.0.0 | 日期：2026-04-23 | 功能：统一AI接口
"""
UniversalAI 统一接口 - 整合路由器、适配器工厂、账号管理器
提供 chat/image/audio/video/embed 等统一接口
"""

import logging
import base64
import time
from typing import Dict, List, Optional, Any, Union, Callable

from .router import Router, TaskType, get_router
from .api_adapter import (
    AdapterFactory, UnifiedResponse, create_unified_response, calculate_cost
)
from .account_manager import AccountManager, get_account_manager
from .config_manager import get_config_manager

logger = logging.getLogger(__name__)


class UniversalAI:
    """
    统一AI接口类
    整合路由器、API适配器工厂、账号管理器
    提供一致的调用接口
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化统一AI接口
        :param config_path: 配置文件路径
        """
        # 1. 加载配置
        self.config_manager = get_config_manager(config_path)
        self.config_manager.load_config()
        self.config_manager.validate_config()

        # 2. 初始化路由器
        self.router = get_router(config_path)

        # 3. 初始化API适配器工厂（使用已有的AdapterFactory）
        self.adapter_factory = AdapterFactory

        # 4. 初始化账号管理器
        self.account_manager = get_account_manager(self.config_manager)

        # 默认配置参数
        self.default_params = {
            "temperature": 0.7,
            "max_tokens": 4096,
            "top_p": 1.0,
            "seed": None,
            "timeout": 30
        }

        logger.info("UniversalAI 初始化完成")

    def _update_params(self, **kwargs) -> Dict[str, Any]:
        """合并默认参数和用户参数"""
        params = self.default_params.copy()
        for key, value in kwargs.items():
            if value is not None:
                params[key] = value
        return params

    def _do_request(
        self,
        model: Dict[str, Any],
        task_type: TaskType,
        messages: Optional[List[Dict[str, str]]] = None,
        stream_handler: Optional[Callable] = None,
        **kwargs
    ) -> UnifiedResponse:
        """
        执行AI请求的内部方法
        :param model: 模型配置
        :param task_type: 任务类型
        :param messages: 消息列表
        :param stream_handler: 流式处理回调
        :param kwargs: 其他参数
        :return: 统一响应格式
        """
        provider_name = model.get("provider", "")
        model_name = model.get("name", "")
        provider_config = self.config_manager.get_provider_config(provider_name)

        if not provider_config:
            logger.error(f"提供商配置不存在: {provider_name}")
            return create_unified_response(
                success=False,
                error_message=f"提供商配置不存在: {provider_name}"
            )

        # 获取API配置
        api_type = provider_config.get("api_type", "tongyi")
        base_url = provider_config.get("base_url", "")
        timeout = kwargs.get("timeout", self.default_params["timeout"])

        # 从账号管理器获取可用账号
        account_result = self.account_manager.get_next_account(provider_name)
        if account_result is None:
            logger.error(f"提供商 {provider_name} 没有可用账号")
            return create_unified_response(
                success=False,
                error_message=f"提供商 {provider_name} 没有可用账号"
            )

        account_index, api_key = account_result

        try:
            # 创建适配器
            adapter = self.adapter_factory.get_adapter(
                api_type=api_type,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                model=model_name
            )

            # 根据任务类型构建请求
            if task_type == TaskType.TEXT:
                # 文字聊天
                request_params = self._build_text_params(messages, **kwargs)
            elif task_type == TaskType.IMAGE:
                # 图像理解
                request_params = self._build_image_params(messages, **kwargs)
            elif task_type == TaskType.AUDIO:
                # 语音识别
                request_params = self._build_audio_params(messages, **kwargs)
            elif task_type == TaskType.VIDEO:
                # 视频理解
                request_params = self._build_video_params(messages, **kwargs)
            elif task_type == TaskType.EMBEDDING:
                # 向量嵌入
                request_params = self._build_embedding_params(messages, **kwargs)
            else:
                request_params = messages or []

            # 执行请求
            if stream_handler:
                # 流式响应处理
                response = self._handle_stream(adapter, request_params, stream_handler)
            else:
                response = adapter.request(request_params, **kwargs)

            # 处理响应
            response = self._handle_response(response, model)

            # 记录使用
            if response.success:
                self.account_manager.mark_account_success(provider_name, account_index)
                self._log_usage(
                    model_name=model_name,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    model_config=model
                )
            else:
                status_code = None
                if isinstance(response.raw_response, dict):
                    status_code = response.raw_response.get("status_code")
                self.account_manager.mark_account_failed(provider_name, account_index, status_code)

            return response

        except Exception as e:
            logger.error(f"请求执行异常: {e}")
            self.account_manager.mark_account_failed(provider_name, account_index)
            return create_unified_response(
                success=False,
                error_message=f"请求执行异常: {str(e)}"
            )

    def _build_text_params(self, messages: List[Dict[str, str]], **kwargs) -> List[Dict[str, str]]:
        """构建文本请求参数"""
        return messages

    def _build_image_params(self, messages: List[Dict[str, str]], **kwargs) -> List[Dict[str, str]]:
        """构建图像理解请求参数"""
        # 通义千问等视觉模型支持图片消息格式
        return messages

    def _build_audio_params(self, messages: List[Dict[str, str]], **kwargs) -> List[Dict[str, str]]:
        """构建语音识别请求参数"""
        return messages

    def _build_video_params(self, messages: List[Dict[str, str]], **kwargs) -> List[Dict[str, str]]:
        """构建视频理解请求参数"""
        return messages

    def _build_embedding_params(self, messages: List[Dict[str, str]], **kwargs) -> List[Dict[str, str]]:
        """构建向量嵌入请求参数"""
        return messages

    def _handle_stream(
        self,
        adapter,
        request_params: List[Dict[str, str]],
        stream_handler: Callable[[str], None]
    ) -> UnifiedResponse:
        """处理流式响应"""
        try:
            full_content = []
            for chunk in adapter.request_stream(request_params):
                if chunk:
                    full_content.append(chunk)
                    if stream_handler:
                        stream_handler(chunk)

            content = "".join(full_content)
            return create_unified_response(
                content=content,
                model=adapter.model,
                success=True
            )
        except Exception as e:
            logger.error(f"流式响应处理异常: {e}")
            return create_unified_response(
                success=False,
                error_message=f"流式响应处理异常: {str(e)}"
            )

    def _handle_response(self, response: UnifiedResponse, model: Dict[str, Any]) -> UnifiedResponse:
        """处理和规范化响应"""
        if response.success:
            # 计算成本
            cost = calculate_cost(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                input_price=model.get("input_price", 0),
                output_price=model.get("output_price", 0)
            )
            response.cost = cost
            response.model = model.get("name", response.model)

        return response

    def _log_usage(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        model_config: Dict[str, Any]
    ) -> None:
        """记录使用日志"""
        total_tokens = input_tokens + output_tokens
        logger.info(
            f"[使用统计] 模型: {model_name}, "
            f"输入Token: {input_tokens}, 输出Token: {output_tokens}, "
            f"总计: {total_tokens}"
        )

    # ==================== 核心接口 ====================

    def chat(
        self,
        text: str,
        model: Optional[str] = None,
        strategy: Optional[str] = None,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> UnifiedResponse:
        """
        文字聊天接口
        :param text: 用户输入文本
        :param model: 指定模型（可选，自动路由）
        :param strategy: 路由策略（cost/performance/balanced）
        :param system_prompt: 系统提示词
        :param kwargs: 其他参数（temperature, max_tokens, top_p, seed, timeout）
        :return: 统一响应格式
        """
        params = self._update_params(**kwargs)

        # 构建消息列表
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": text})

        # 如果指定了模型，查找模型配置
        if model:
            model_config = self._find_model_config(model, TaskType.TEXT)
            if model_config:
                return self._do_request(model_config, TaskType.TEXT, messages, **params)

        # 自动路由选择模型
        route_result = self.router.route(text, TaskType.TEXT, strategy)
        if not route_result:
            return create_unified_response(
                success=False,
                error_message="没有可用的模型"
            )

        # 尝试每个模型直到成功
        for model_config in route_result:
            response = self._do_request(model_config, TaskType.TEXT, messages, **params)
            if response.success:
                return response

        return create_unified_response(
            success=False,
            error_message="所有模型请求均失败"
        )

    def image(
        self,
        image_data: Union[bytes, str],
        prompt: Optional[str] = None,
        model: Optional[str] = None
    ) -> UnifiedResponse:
        """
        图像理解接口
        :param image_data: 图片数据（bytes或base64字符串）
        :param prompt: 图像理解提示
        :param model: 指定模型
        :return: 统一响应格式
        """
        # 转换图片数据为base64
        if isinstance(image_data, bytes):
            image_b64 = base64.b64encode(image_data).decode("utf-8")
        else:
            image_b64 = image_data

        # 构建消息
        messages = []
        if prompt:
            messages.append({"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image;base64,{image_b64}"}}
            ]})
        else:
            messages.append({"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image;base64,{image_b64}"}}
            ]})

        # 如果指定了模型
        if model:
            model_config = self._find_model_config(model, TaskType.IMAGE)
            if model_config:
                return self._do_request(model_config, TaskType.IMAGE, messages)

        # 自动路由
        route_result = self.router.route(image_data, TaskType.IMAGE)
        if not route_result:
            return create_unified_response(
                success=False,
                error_message="没有可用的视觉模型"
            )

        # 尝试每个模型直到成功
        for model_config in route_result:
            response = self._do_request(model_config, TaskType.IMAGE, messages)
            if response.success:
                return response

        return create_unified_response(
            success=False,
            error_message="所有视觉模型请求均失败"
        )

    def audio(
        self,
        audio_data: bytes,
        prompt: Optional[str] = None,
        model: Optional[str] = None
    ) -> UnifiedResponse:
        """
        语音识别接口
        :param audio_data: 音频数据（bytes）
        :param prompt: 识别提示
        :param model: 指定模型
        :return: 统一响应格式
        """
        # 转换音频为base64
        audio_b64 = base64.b64encode(audio_data).decode("utf-8")

        # 构建消息
        messages = []
        if prompt:
            messages.append({"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "audio", "audio": {"url": f"data:audio;base64,{audio_b64}"}}
            ]})
        else:
            messages.append({"role": "user", "content": [
                {"type": "audio", "audio": {"url": f"data:audio;base64,{audio_b64}"}}
            ]})

        # 如果指定了模型
        if model:
            model_config = self._find_model_config(model, TaskType.AUDIO)
            if model_config:
                return self._do_request(model_config, TaskType.AUDIO, messages)

        # 自动路由
        route_result = self.router.route(audio_data, TaskType.AUDIO)
        if not route_result:
            return create_unified_response(
                success=False,
                error_message="没有可用的语音识别模型"
            )

        # 尝试每个模型直到成功
        for model_config in route_result:
            response = self._do_request(model_config, TaskType.AUDIO, messages)
            if response.success:
                return response

        return create_unified_response(
            success=False,
            error_message="所有语音识别模型请求均失败"
        )

    def video(
        self,
        video_data: bytes,
        prompt: Optional[str] = None,
        model: Optional[str] = None
    ) -> UnifiedResponse:
        """
        视频理解接口
        :param video_data: 视频数据（bytes）
        :param prompt: 视频理解提示
        :param model: 指定模型
        :return: 统一响应格式
        """
        # 转换视频为base64
        video_b64 = base64.b64encode(video_data).decode("utf-8")

        # 构建消息
        messages = []
        if prompt:
            messages.append({"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "video_url", "video_url": {"url": f"data:video;base64,{video_b64}"}}
            ]})
        else:
            messages.append({"role": "user", "content": [
                {"type": "video_url", "video_url": {"url": f"data:video;base64,{video_b64}"}}
            ]})

        # 如果指定了模型
        if model:
            model_config = self._find_model_config(model, TaskType.VIDEO)
            if model_config:
                return self._do_request(model_config, TaskType.VIDEO, messages)

        # 自动路由
        route_result = self.router.route(video_data, TaskType.VIDEO)
        if not route_result:
            return create_unified_response(
                success=False,
                error_message="没有可用的视频理解模型"
            )

        # 尝试每个模型直到成功
        for model_config in route_result:
            response = self._do_request(model_config, TaskType.VIDEO, messages)
            if response.success:
                return response

        return create_unified_response(
            success=False,
            error_message="所有视频理解模型请求均失败"
        )

    def embed(
        self,
        text: str,
        model: Optional[str] = None
    ) -> UnifiedResponse:
        """
        向量嵌入接口
        :param text: 文本
        :param model: 指定模型
        :return: 统一响应格式
        """
        messages = [{"role": "user", "content": text}]

        # 如果指定了模型
        if model:
            model_config = self._find_model_config(model, TaskType.EMBEDDING)
            if model_config:
                return self._do_request(model_config, TaskType.EMBEDDING, messages)

        # 自动路由
        route_result = self.router.route(text, TaskType.EMBEDDING)
        if not route_result:
            return create_unified_response(
                success=False,
                error_message="没有可用的向量模型"
            )

        # 尝试每个模型直到成功
        for model_config in route_result:
            response = self._do_request(model_config, TaskType.EMBEDDING, messages)
            if response.success:
                return response

        return create_unified_response(
            success=False,
            error_message="所有向量模型请求均失败"
        )

    # ==================== 辅助方法 ====================

    def _find_model_config(self, model_name: str, task_type: TaskType) -> Optional[Dict[str, Any]]:
        """根据模型名称查找模型配置"""
        pool_name = Router.TASK_POOL_MAPPING.get(task_type)
        if not pool_name:
            return None

        models = self.config_manager.get_models_by_pool(pool_name)
        for model in models:
            if model.get("name") == model_name:
                return model

        return None

    def set_default_param(self, key: str, value: Any) -> None:
        """设置默认参数"""
        if key in self.default_params:
            self.default_params[key] = value
            logger.info(f"默认参数已更新: {key} = {value}")

    def get_default_params(self) -> Dict[str, Any]:
        """获取当前默认参数"""
        return self.default_params.copy()


# ==================== 全局单例 ====================

_universal_ai_instance: Optional[UniversalAI] = None


def get_universal_ai(config_path: Optional[str] = None) -> UniversalAI:
    """
    获取UniversalAI全局单例
    :param config_path: 配置文件路径（仅首次生效）
    :return: UniversalAI实例
    """
    global _universal_ai_instance
    if _universal_ai_instance is None:
        _universal_ai_instance = UniversalAI(config_path)
    return _universal_ai_instance


def reset_universal_ai() -> None:
    """重置UniversalAI全局单例（用于测试或重新加载）"""
    global _universal_ai_instance
    _universal_ai_instance = None
    logger.info("UniversalAI 全局单例已重置")
