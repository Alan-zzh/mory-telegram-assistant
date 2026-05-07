# 项目：universal_ai_router | 版本：v1.0.0 | 日期：2026-04-23 | 功能：API适配层
"""
API适配层 - 统一封装不同AI服务商的请求和响应格式
支持：通义千问、OpenAI、Anthropic Claude、Gemini
"""

import json
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timezone, timedelta

import requests

# 日志配置
logger = logging.getLogger(__name__)

# 北京时间时区
_CST = timezone(timedelta(hours=8))


@dataclass
class UnifiedResponse:
    """统一响应格式 - 所有适配器返回相同结构"""
    content: str = ""                    # 文本内容
    model: str = ""                      # 模型名称
    input_tokens: int = 0                # 输入token数
    output_tokens: int = 0               # 输出token数
    cost: float = 0.0                    # 成本
    provider: str = ""                   # API来源
    raw_response: Optional[Dict] = None  # 原始响应
    success: bool = True                 # 请求是否成功
    error_message: str = ""              # 错误信息


class BaseAdapter(ABC):
    """API适配器抽象基类"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: int = 30,
        model: str = ""
    ):
        """
        初始化适配器
        :param api_key: API密钥
        :param base_url: API基础URL
        :param timeout: 请求超时时间（秒）
        :param model: 模型名称
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.model = model
        self._session = requests.Session()

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头 - 子类可重写"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    @abstractmethod
    def build_request(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> Dict[str, Any]:
        """
        构建请求数据 - 子类必须实现
        :param messages: 消息列表
        :param kwargs: 其他参数
        :return: 请求体字典
        """
        pass

    @abstractmethod
    def parse_response(self, response: Dict) -> UnifiedResponse:
        """
        解析响应数据 - 子类必须实现
        :param response: 原始响应字典
        :return: 统一响应格式
        """
        pass

    @abstractmethod
    def handle_error(self, status_code: int, response_text: str) -> str:
        """
        处理错误 - 子类必须实现
        :param status_code: HTTP状态码
        :param response_text: 响应文本
        :return: 错误信息字符串
        """
        pass

    def request(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> UnifiedResponse:
        """
        执行HTTP请求
        :param messages: 消息列表
        :param kwargs: 其他参数
        :return: 统一响应格式
        """
        try:
            # 构建请求
            request_data = self.build_request(messages, **kwargs)
            headers = self._get_headers()

            # 记录请求日志
            logger.debug(f"[{self.__class__.__name__}] 请求: {json.dumps(request_data, ensure_ascii=False)[:200]}...")

            # 发送请求
            start_time = time.time()
            # 通义千问使用 /completions 端点
            endpoint = "/completions" if self.__class__.__name__ == "TongyiAdapter" else "/chat/completions"
            response = self._session.post(
                f"{self.base_url}{endpoint}",
                headers=headers,
                json=request_data,
                timeout=self.timeout
            )
            elapsed_time = time.time() - start_time

            logger.info(f"[{self.__class__.__name__}] 响应状态: {response.status_code}, 耗时: {elapsed_time:.2f}s")

            # 处理响应
            if response.status_code == 200:
                response_data = response.json()
                result = self.parse_response(response_data)
                result.provider = self.__class__.__name__.replace("Adapter", "").lower()
                return result
            else:
                error_msg = self.handle_error(response.status_code, response.text)
                return UnifiedResponse(
                    success=False,
                    error_message=error_msg,
                    provider=self.__class__.__name__.replace("Adapter", "").lower(),
                    raw_response={"status_code": response.status_code, "body": response.text[:1000]}
                )

        except requests.Timeout:
            error_msg = f"请求超时（{self.timeout}秒）"
            logger.error(f"[{self.__class__.__name__}] {error_msg}")
            return UnifiedResponse(success=False, error_message=error_msg, raw_response={"status_code": 408})

        except requests.RequestException as e:
            error_msg = f"网络请求异常: {str(e)}"
            logger.error(f"[{self.__class__.__name__}] {error_msg}")
            return UnifiedResponse(success=False, error_message=error_msg, raw_response={"status_code": 599})

        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            logger.error(f"[{self.__class__.__name__}] {error_msg}")
            return UnifiedResponse(success=False, error_message=error_msg, raw_response={"status_code": 500})

    def __del__(self):
        """清理Session资源"""
        if hasattr(self, '_session'):
            self._session.close()


class TongyiAdapter(BaseAdapter):
    """通义千问适配器"""

    def build_request(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> Dict[str, Any]:
        """构建通义千问格式的请求"""
        request_data = {
            "model": self.model or "qwen3.5-plus",
            "input": {
                "messages": messages
            }
        }

        # 添加可选参数
        if kwargs.get("temperature"):
            request_data["parameters"] = {"temperature": kwargs["temperature"]}

        if kwargs.get("max_tokens"):
            if "parameters" not in request_data:
                request_data["parameters"] = {}
            request_data["parameters"]["max_tokens"] = kwargs["max_tokens"]

        if kwargs.get("stream"):
            request_data["parameters"]["stream"] = kwargs["stream"]

        return request_data

    def parse_response(self, response: Dict) -> UnifiedResponse:
        """解析通义千问格式的响应"""
        try:
            # 通义千问响应格式
            output_text = ""
            input_tokens = 0
            output_tokens = 0

            if "output" in response and "choices" in response["output"]:
                choices = response["output"]["choices"]
                if choices and len(choices) > 0:
                    output_text = choices[0].get("text", "") or choices[0].get("content", "")

            if "usage" in response:
                usage = response["usage"]
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)

            model_name = response.get("model", self.model)

            return UnifiedResponse(
                content=output_text,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                raw_response=response
            )

        except Exception as e:
            logger.error(f"[TongyiAdapter] 解析响应失败: {e}")
            return UnifiedResponse(success=False, error_message=f"响应解析失败: {e}")

    def handle_error(self, status_code: int, response_text: str) -> str:
        """处理通义千问错误"""
        try:
            error_data = json.loads(response_text)
            error_msg = error_data.get("error", {}).get("message", response_text)
        except:
            error_msg = response_text

        error_map = {
            400: f"请求参数错误: {error_msg}",
            401: "API密钥无效或已过期",
            403: "请求被拒绝，权限不足",
            429: "请求频率超限，请稍后重试",
            500: "服务器内部错误",
            503: "服务暂时不可用"
        }

        return error_map.get(status_code, f"请求失败({status_code}): {error_msg}")


class OpenAIAdapter(BaseAdapter):
    """OpenAI适配器"""

    def build_request(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> Dict[str, Any]:
        """构建OpenAI格式的请求"""
        request_data = {
            "model": self.model or "gpt-4o",
            "messages": messages
        }

        # 添加可选参数
        if kwargs.get("temperature") is not None:
            request_data["temperature"] = kwargs["temperature"]

        if kwargs.get("max_tokens"):
            request_data["max_tokens"] = kwargs["max_tokens"]

        if kwargs.get("stream"):
            request_data["stream"] = kwargs["stream"]

        if kwargs.get("top_p"):
            request_data["top_p"] = kwargs["top_p"]

        if kwargs.get("stop"):
            request_data["stop"] = kwargs["stop"]

        return request_data

    def parse_response(self, response: Dict) -> UnifiedResponse:
        """解析OpenAI格式的响应"""
        try:
            choices = response.get("choices", [])
            output_text = ""

            if choices and len(choices) > 0:
                message = choices[0].get("message", {})
                output_text = message.get("content", "")

            usage = response.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

            model_name = response.get("model", self.model)

            return UnifiedResponse(
                content=output_text,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                raw_response=response
            )

        except Exception as e:
            logger.error(f"[OpenAIAdapter] 解析响应失败: {e}")
            return UnifiedResponse(success=False, error_message=f"响应解析失败: {e}")

    def handle_error(self, status_code: int, response_text: str) -> str:
        """处理OpenAI错误"""
        try:
            error_data = json.loads(response_text)
            error_msg = error_data.get("error", {}).get("message", response_text)
        except:
            error_msg = response_text

        error_map = {
            400: f"请求参数错误: {error_msg}",
            401: "API密钥无效或已过期",
            403: "请求被拒绝，权限不足",
            404: "模型不存在或不可用",
            429: "请求频率超限，请稍后重试",
            500: "服务器内部错误",
            503: "服务暂时不可用"
        }

        return error_map.get(status_code, f"请求失败({status_code}): {error_msg}")


class AnthropicAdapter(BaseAdapter):
    """Anthropic Claude适配器"""

    def _get_headers(self) -> Dict[str, str]:
        """获取Anthropic请求头"""
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }

    def build_request(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> Dict[str, Any]:
        """构建Anthropic格式的请求"""
        # 将messages转换为Anthropic格式
        anthropic_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            if role == "system":
                # Anthropic使用单独的system字段
                continue
            elif role == "assistant":
                role = "assistant"
            else:
                role = "user"

            anthropic_messages.append({
                "role": role,
                "content": msg.get("content", "")
            })

        request_data = {
            "model": self.model or "claude-3-5-sonnet",
            "messages": anthropic_messages,
            "max_tokens": kwargs.get("max_tokens", 4096)
        }

        # 处理system消息
        for msg in messages:
            if msg.get("role") == "system":
                request_data["system"] = msg.get("content", "")
                break

        # 添加可选参数
        if kwargs.get("temperature") is not None:
            request_data["temperature"] = kwargs["temperature"]

        if kwargs.get("stream"):
            request_data["stream"] = kwargs["stream"]

        if kwargs.get("top_p"):
            request_data["top_p"] = kwargs["top_p"]

        if kwargs.get("stop"):
            request_data["stop_sequences"] = kwargs["stop"] if isinstance(kwargs["stop"], list) else [kwargs["stop"]]

        return request_data

    def parse_response(self, response: Dict) -> UnifiedResponse:
        """解析Anthropic格式的响应"""
        try:
            output_text = ""

            if "content" in response:
                for block in response["content"]:
                    if block.get("type") == "text":
                        output_text = block.get("text", "")
                        break

            usage = response.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

            model_name = response.get("model", self.model)

            return UnifiedResponse(
                content=output_text,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                raw_response=response
            )

        except Exception as e:
            logger.error(f"[AnthropicAdapter] 解析响应失败: {e}")
            return UnifiedResponse(success=False, error_message=f"响应解析失败: {e}")

    def handle_error(self, status_code: int, response_text: str) -> str:
        """处理Anthropic错误"""
        try:
            error_data = json.loads(response_text)
            error_msg = error_data.get("error", {}).get("message", response_text)
        except:
            error_msg = response_text

        error_map = {
            400: f"请求参数错误: {error_msg}",
            401: "API密钥无效或已过期",
            403: "请求被拒绝，权限不足",
            404: "模型不存在或不可用",
            429: "请求频率超限，请稍后重试",
            500: "服务器内部错误",
            503: "服务暂时不可用"
        }

        return error_map.get(status_code, f"请求失败({status_code}): {error_msg}")


class GeminiAdapter(BaseAdapter):
    """Google Gemini适配器"""

    def _get_headers(self) -> Dict[str, str]:
        """获取Gemini请求头"""
        return {
            "Content-Type": "application/json"
        }

    def build_request(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> Dict[str, Any]:
        """构建Gemini格式的请求"""
        # 将messages转换为Gemini格式
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            # Gemini只支持model和user角色
            if role == "system":
                continue
            elif role == "assistant":
                role = "model"
            else:
                role = "user"

            contents.append({
                "role": role,
                "parts": [{"text": msg.get("content", "")}]
            })

        request_data = {
            "contents": contents
        }

        # 处理system指令
        for msg in messages:
            if msg.get("role") == "system":
                request_data["systemInstruction"] = {
                    "parts": [{"text": msg.get("content", "")}]
                }
                break

        # 添加生成配置
        generation_config = {}
        if kwargs.get("temperature") is not None:
            generation_config["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens"):
            generation_config["maxOutputTokens"] = kwargs["max_tokens"]
        if kwargs.get("top_p"):
            generation_config["topP"] = kwargs["top_p"]
        if kwargs.get("top_k"):
            generation_config["topK"] = kwargs["top_k"]

        if generation_config:
            request_data["generationConfig"] = generation_config

        return request_data

    def request(
        self,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> UnifiedResponse:
        """Gemini使用不同的端点路径"""
        try:
            request_data = self.build_request(messages, **kwargs)
            headers = self._get_headers()

            # Gemini API端点格式
            model_name = self.model or "gemini-1.5-flash"
            url = f"{self.base_url}/models/{model_name}:generateContent"

            # 添加API_KEY到URL
            url = f"{url}?key={self.api_key}"

            logger.debug(f"[GeminiAdapter] 请求: {json.dumps(request_data, ensure_ascii=False)[:200]}...")

            start_time = time.time()
            response = self._session.post(
                url,
                headers=headers,
                json=request_data,
                timeout=self.timeout
            )
            elapsed_time = time.time() - start_time

            logger.info(f"[GeminiAdapter] 响应状态: {response.status_code}, 耗时: {elapsed_time:.2f}s")

            if response.status_code == 200:
                response_data = response.json()
                result = self.parse_response(response_data)
                result.provider = "gemini"
                return result
            else:
                error_msg = self.handle_error(response.status_code, response.text)
                return UnifiedResponse(success=False, error_message=error_msg, provider="gemini", raw_response={"status_code": response.status_code, "body": response.text[:1000]})

        except requests.Timeout:
            error_msg = f"请求超时（{self.timeout}秒）"
            logger.error(f"[GeminiAdapter] {error_msg}")
            return UnifiedResponse(success=False, error_message=error_msg, provider="gemini", raw_response={"status_code": 408})

        except requests.RequestException as e:
            error_msg = f"网络请求异常: {str(e)}"
            logger.error(f"[GeminiAdapter] {error_msg}")
            return UnifiedResponse(success=False, error_message=error_msg, provider="gemini", raw_response={"status_code": 599})

        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            logger.error(f"[GeminiAdapter] {error_msg}")
            return UnifiedResponse(success=False, error_message=error_msg, provider="gemini", raw_response={"status_code": 500})

    def parse_response(self, response: Dict) -> UnifiedResponse:
        """解析Gemini格式的响应"""
        try:
            output_text = ""

            if "candidates" in response:
                candidates = response["candidates"]
                if candidates and len(candidates) > 0:
                    content = candidates[0].get("content", {})
                    if content and "parts" in content:
                        for part in content["parts"]:
                            if "text" in part:
                                output_text = part["text"]
                                break

            # Gemini的使用量统计
            usage_metadata = response.get("usageMetadata", {})
            input_tokens = usage_metadata.get("promptTokenCount", 0)
            output_tokens = usage_metadata.get("candidatesTokenCount", 0)

            model_name = response.get("modelVersion", self.model)

            return UnifiedResponse(
                content=output_text,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                raw_response=response
            )

        except Exception as e:
            logger.error(f"[GeminiAdapter] 解析响应失败: {e}")
            return UnifiedResponse(success=False, error_message=f"响应解析失败: {e}")

    def handle_error(self, status_code: int, response_text: str) -> str:
        """处理Gemini错误"""
        try:
            error_data = json.loads(response_text)
            error_msg = error_data.get("error", {}).get("message", response_text)
        except:
            error_msg = response_text

        error_map = {
            400: f"请求参数错误: {error_msg}",
            401: "API密钥无效或已过期",
            403: "请求被拒绝，权限不足",
            404: "模型不存在或不可用",
            429: "请求频率超限，请稍后重试",
            500: "服务器内部错误",
            503: "服务暂时不可用"
        }

        return error_map.get(status_code, f"请求失败({status_code}): {error_msg}")


class AdapterFactory:
    """适配器工厂类"""

    _adapters: Dict[str, type] = {
        "tongyi": TongyiAdapter,
        "openai": OpenAIAdapter,
        "anthropic": AnthropicAdapter,
        "gemini": GeminiAdapter
    }

    @classmethod
    def get_adapter(
        cls,
        api_type: str,
        api_key: str,
        base_url: str,
        timeout: int = 30,
        model: str = ""
    ) -> BaseAdapter:
        """
        获取适配器实例
        :param api_type: API类型（tongyi/openai/anthropic/gemini）
        :param api_key: API密钥
        :param base_url: API基础URL
        :param timeout: 请求超时时间
        :param model: 模型名称
        :return: 适配器实例
        :raises ValueError: 不支持的API类型
        """
        api_type_lower = api_type.lower()
        if api_type_lower not in cls._adapters:
            supported = ", ".join(cls._adapters.keys())
            raise ValueError(f"不支持的API类型: {api_type}，支持的类型: {supported}")

        adapter_class = cls._adapters[api_type_lower]
        return adapter_class(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            model=model
        )

    @classmethod
    def register_adapter(cls, api_type: str, adapter_class: type):
        """
        注册新的适配器
        :param api_type: API类型标识
        :param adapter_class: 适配器类
        """
        if not issubclass(adapter_class, BaseAdapter):
            raise TypeError("适配器类必须继承自BaseAdapter")
        cls._adapters[api_type.lower()] = adapter_class

    @classmethod
    def get_supported_types(cls) -> List[str]:
        """获取所有支持的API类型"""
        return list(cls._adapters.keys())


def create_unified_response(
    content: str = "",
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost: float = 0.0,
    provider: str = "",
    raw_response: Optional[Dict] = None,
    success: bool = True,
    error_message: str = ""
) -> UnifiedResponse:
    """
    创建一个统一响应格式的实例
    :return: UnifiedResponse对象
    """
    return UnifiedResponse(
        content=content,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost,
        provider=provider,
        raw_response=raw_response,
        success=success,
        error_message=error_message
    )


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    input_price: float,
    output_price: float
) -> float:
    """
    计算API调用成本
    :param input_tokens: 输入token数
    :param output_tokens: 输出token数
    :param input_price: 输入单价（每token价格）
    :param output_price: 输出单价（每token价格）
    :return: 总成本
    """
    return (input_tokens * input_price) + (output_tokens * output_price)
