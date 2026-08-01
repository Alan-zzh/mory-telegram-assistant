# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/http_client.py  ·  统一HTTP客户端封装                             ║
║                                                                        ║
║  功能：                                                                ║
║    1. 统一的超时管理 - 所有网络请求使用一致的超时配置                    ║
║    2. 自动重试机制 - 网络抖动时自动重试，提升成功率                      ║
║    3. 统一的异常处理 - 完整的异常捕获和日志记录                          ║
║    4. 完整的日志记录 - 便于问题排查和监控                                ║
║    5. 支持请求/响应拦截器 - 可扩展的中间件机制                           ║
║                                                                        ║
║  使用方式：                                                            ║
║    from core.http_client import get_http_client                        ║
║    client = get_http_client()                                          ║
║    data = client.get("https://api.example.com/data", timeout=10)       ║
║                                                                        ║
║  依赖：requests（优先）或 urllib.request（回退）                        ║
║  配置：config.json → HTTP_CLIENT_CONFIG（可选）                         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
import json
import urllib.request
from typing import Optional, Dict, Any, Union, Callable
from core.logging_util import get_logger

logger = get_logger("http_client")


# ──────────────────────────────────────────────────────────────────────────
# 自定义异常类
# ──────────────────────────────────────────────────────────────────────────

class HTTPTimeoutError(Exception):
    """HTTP请求超时异常"""
    pass


class HTTPRequestError(Exception):
    """HTTP请求失败异常"""
    pass


# ──────────────────────────────────────────────────────────────────────────
# HTTP客户端核心类
# ──────────────────────────────────────────────────────────────────────────

class HTTPClient:
    """
    统一HTTP客户端
    
    提供统一的网络请求接口，支持：
    - GET/POST 请求
    - 自动重试机制
    - 统一超时管理
    - 完整的异常处理和日志记录
    - 请求/响应拦截器（可扩展）
    """
    
    # 默认配置
    DEFAULT_TIMEOUT = 10  # 默认超时10秒
    DEFAULT_RETRY_TIMES = 2  # 默认重试2次
    DEFAULT_RETRY_DELAY = 1  # 默认重试延迟1秒
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化HTTP客户端
        
        Args:
            config: 配置字典，可覆盖默认配置
                {
                    "default_timeout": 10,      # 默认超时时间（秒）
                    "retry_times": 2,           # 默认重试次数
                    "retry_delay": 1,           # 默认重试延迟（秒）
                    "enable_logging": True      # 是否启用日志记录
                }
        """
        # 初始化配置，使用默认值
        self.config = {
            "default_timeout": self.DEFAULT_TIMEOUT,
            "retry_times": self.DEFAULT_RETRY_TIMES,
            "retry_delay": self.DEFAULT_RETRY_DELAY,
            "enable_logging": True
        }
        
        # 合并用户配置
        if config:
            self.config.update(config)
        
        # 请求拦截器列表（用于在请求前修改参数）
        self.request_interceptors = []
        # 响应拦截器列表（用于在响应后处理数据）
        self.response_interceptors = []
    
    def add_request_interceptor(self, interceptor: Callable):
        """
        添加请求拦截器
        
        拦截器会在每次请求前执行，可以修改请求参数（如添加认证头）
        
        Args:
            interceptor: 拦截器函数，接收 request_params 字典，返回修改后的字典
        """
        self.request_interceptors.append(interceptor)
    
    def add_response_interceptor(self, interceptor: Callable):
        """
        添加响应拦截器
        
        拦截器会在每次响应后执行，可以修改响应数据
        
        Args:
            interceptor: 拦截器函数，接收 (response, request_params)，返回修改后的响应
        """
        self.response_interceptors.append(interceptor)
    
    def _execute_request_interceptors(self, request_params: Dict) -> Dict:
        """执行所有请求拦截器"""
        for interceptor in self.request_interceptors:
            request_params = interceptor(request_params)
        return request_params
    
    def _execute_response_interceptors(self, response: Any, request_params: Dict) -> Any:
        """执行所有响应拦截器"""
        for interceptor in self.response_interceptors:
            response = interceptor(response, request_params)
        return response
    
    def get(
        self,
        url: str,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        timeout: Optional[int] = None,
        retry_times: Optional[int] = None,
        retry_delay: Optional[float] = None,
        raw_text: bool = False,
        log_final_failure: bool = True,
    ) -> Union[Dict, str]:
        """
        发送GET请求
        
        Args:
            url: 请求URL
            params: 查询参数（会自动拼接到URL）
            headers: 请求头
            timeout: 超时时间（秒），None则使用默认值
            retry_times: 重试次数，None则使用默认值
            retry_delay: 重试延迟（秒），None则使用默认值
            raw_text: 是否返回原始响应文本（默认False返回解析后的字典）
            
        Returns:
            响应数据字典，或原始响应文本（raw_text=True时）
            
        Raises:
            HTTPTimeoutError: 请求超时
            HTTPRequestError: 请求失败
        """
        return self._request(
            method="GET",
            url=url,
            params=params,
            headers=headers,
            timeout=timeout,
            retry_times=retry_times,
            retry_delay=retry_delay,
            raw_text=raw_text,
            log_final_failure=log_final_failure,
        )
    
    def post(
        self,
        url: str,
        data: Optional[Union[Dict, str, bytes]] = None,
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        timeout: Optional[int] = None,
        retry_times: Optional[int] = None,
        retry_delay: Optional[float] = None,
        raw_text: bool = False
    ) -> Union[Dict, str]:
        """
        发送POST请求
        
        Args:
            url: 请求URL
            data: 请求体数据（字典、字符串或字节）
            json_data: JSON格式的请求体数据（会自动设置Content-Type）
            headers: 请求头
            timeout: 超时时间（秒）
            retry_times: 重试次数
            retry_delay: 重试延迟（秒）
            raw_text: 是否返回原始响应文本（默认False返回解析后的字典）
            
        Returns:
            响应数据字典，或原始响应文本（raw_text=True时）
            
        Raises:
            HTTPTimeoutError: 请求超时
            HTTPRequestError: 请求失败
        """
        return self._request(
            method="POST",
            url=url,
            data=data,
            json_data=json_data,
            headers=headers,
            timeout=timeout,
            retry_times=retry_times,
            retry_delay=retry_delay,
            raw_text=raw_text
        )
    
    def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        data: Optional[Union[Dict, str, bytes]] = None,
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        timeout: Optional[int] = None,
        retry_times: Optional[int] = None,
        retry_delay: Optional[float] = None,
        raw_text: bool = False,
        log_final_failure: bool = True,
    ) -> Union[Dict, str]:
        """
        内部请求方法（带重试机制）
        
        实现核心请求逻辑：
        1. 使用配置的默认值
        2. 执行请求拦截器
        3. 重试逻辑（失败后自动重试）
        4. 执行响应拦截器
        5. 完整的异常处理和日志记录
        
        Args:
            method: 请求方法（GET/POST）
            url: 请求URL
            params: 查询参数
            data: 请求体数据
            json_data: JSON格式的请求体数据
            headers: 请求头
            timeout: 超时时间
            retry_times: 重试次数
            retry_delay: 重试延迟
            raw_text: 是否返回原始响应文本
            
        Returns:
            响应数据字典，或原始响应文本（raw_text=True时）
        """
        # 使用配置的默认值
        timeout = timeout or self.config["default_timeout"]
        retry_times = self.config["retry_times"] if retry_times is None else retry_times
        retry_delay = retry_delay or self.config["retry_delay"]
        
        # 构建请求参数
        request_params = {
            "method": method,
            "url": url,
            "params": params,
            "data": data,
            "json_data": json_data,
            "headers": headers,
            "timeout": timeout,
            "raw_text": raw_text
        }
        
        # 执行请求拦截器
        request_params = self._execute_request_interceptors(request_params)
        
        # 重试逻辑
        last_error = None
        for attempt in range(retry_times + 1):
            try:
                # 执行实际请求
                response = self._do_request(request_params)
                # 执行响应拦截器
                response = self._execute_response_interceptors(response, request_params)
                return response
            except Exception as e:
                last_error = e
                # 重试中的日志降级为 debug，避免污染 journalctl 触发监控误报
                # 只有最终失败才在下方打 error
                if self.config["enable_logging"]:
                    logger.debug(
                        f"HTTP请求失败 (尝试 {attempt + 1}/{retry_times + 1}): "
                        f"{method} {url} - {str(e)[:100]}"
                    )
                # 如果还有重试机会，等待后重试
                if attempt < retry_times:
                    time.sleep(retry_delay)
        
        # 所有重试都失败，抛出异常
        error_msg = f"HTTP请求失败: {method} {url} - {str(last_error)[:100]}"
        if self.config["enable_logging"] and log_final_failure:
            logger.error(error_msg)
        raise HTTPRequestError(error_msg) from last_error
    
    def _do_request(self, request_params: Dict) -> Union[Dict, str]:
        """
        执行实际的HTTP请求
        
        优先使用 requests 库（功能更强），如果未安装则回退到 urllib
        
        Args:
            request_params: 请求参数字典
            
        Returns:
            响应数据字典，或原始响应文本（raw_text=True时）
        """
        method = request_params["method"]
        url = request_params["url"]
        params = request_params.get("params")
        data = request_params.get("data")
        json_data = request_params.get("json_data")
        headers = request_params.get("headers")
        timeout = request_params["timeout"]
        raw_text = request_params.get("raw_text", False)
        
        # 构建完整URL（带查询参数）
        if params:
            from urllib.parse import urlencode
            query_string = urlencode(params)
            url = f"{url}?{query_string}" if "?" not in url else f"{url}&{query_string}"
        
        # 优先使用 requests 库
        try:
            import requests
            return self._do_request_with_requests(
                method, url, data, json_data, headers, timeout, raw_text
            )
        except ImportError:
            # 回退到 urllib
            return self._do_request_with_urllib(
                method, url, data, json_data, headers, timeout, raw_text
            )
    
    def _do_request_with_requests(
        self,
        method: str,
        url: str,
        data: Optional[Union[Dict, str, bytes]],
        json_data: Optional[Dict],
        headers: Optional[Dict],
        timeout: int,
        raw_text: bool = False
    ) -> Union[Dict, str]:
        """
        使用 requests 库发送请求
        
        Args:
            method: 请求方法
            url: 请求URL
            data: 请求体数据
            json_data: JSON格式的请求体数据
            headers: 请求头
            timeout: 超时时间
            raw_text: 是否返回原始响应文本
            
        Returns:
            响应数据字典，或原始响应文本（raw_text=True时）
        """
        import requests
        
        # 默认请求头
        default_headers = {
            "User-Agent": "MoryAssistant/1.0"
        }
        if headers:
            default_headers.update(headers)
        
        # 发送请求
        if method.upper() == "GET":
            resp = requests.get(url, headers=default_headers, timeout=timeout)
        elif method.upper() == "POST":
            if json_data:
                resp = requests.post(url, json=json_data, headers=default_headers, timeout=timeout)
            else:
                resp = requests.post(url, data=data, headers=default_headers, timeout=timeout)
        else:
            raise HTTPRequestError(f"不支持的HTTP方法: {method}")
        
        # 检查响应状态（非2xx会抛出异常）
        resp.raise_for_status()
        
        # 如果请求原始文本，直接返回
        if raw_text:
            if self.config["enable_logging"]:
                logger.info(f"HTTP请求成功: {method} {url} - 状态码: {resp.status_code} (原始文本)")
            return resp.text
        
        # 解析响应
        try:
            result = resp.json()
        except ValueError:
            # 如果不是JSON，返回文本
            result = {"text": resp.text}
        
        # 记录成功日志
        if self.config["enable_logging"]:
            logger.info(f"HTTP请求成功: {method} {url} - 状态码: {resp.status_code}")
        
        return result
    
    def _do_request_with_urllib(
        self,
        method: str,
        url: str,
        data: Optional[Union[Dict, str, bytes]],
        json_data: Optional[Dict],
        headers: Optional[Dict],
        timeout: int,
        raw_text: bool = False
    ) -> Union[Dict, str]:
        """
        使用 urllib 库发送请求（回退方案）
        
        Args:
            method: 请求方法
            url: 请求URL
            data: 请求体数据
            json_data: JSON格式的请求体数据
            headers: 请求头
            timeout: 超时时间
            raw_text: 是否返回原始响应文本
            
        Returns:
            响应数据字典，或原始响应文本（raw_text=True时）
        """
        # 默认请求头
        default_headers = {
            "User-Agent": "MoryAssistant/1.0"
        }
        if headers:
            default_headers.update(headers)
        
        # 处理请求体
        body = None
        if json_data:
            body = json.dumps(json_data).encode("utf-8")
            default_headers["Content-Type"] = "application/json"
        elif data:
            if isinstance(data, dict):
                from urllib.parse import urlencode
                body = urlencode(data).encode("utf-8")
            elif isinstance(data, str):
                body = data.encode("utf-8")
            else:
                body = data
        
        # 创建请求
        req = urllib.request.Request(url, data=body, headers=default_headers)
        
        # 发送请求并处理异常
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_text = resp.read().decode("utf-8")
                if raw_text:
                    if self.config["enable_logging"]:
                        logger.info(f"HTTP请求成功: {method} {url} (原始文本)")
                    return resp_text
                result = json.loads(resp_text)
        except urllib.error.HTTPError as e:
            raise HTTPRequestError(f"HTTP错误: {e.code} - {e.reason}")
        except urllib.error.URLError as e:
            if isinstance(e.reason, TimeoutError):
                raise HTTPTimeoutError(f"请求超时: {url}")
            raise HTTPRequestError(f"URL错误: {e.reason}")
        except Exception as e:
            raise HTTPRequestError(f"请求异常: {str(e)[:100]}")
        
        # 记录成功日志
        if self.config["enable_logging"]:
            logger.info(f"HTTP请求成功: {method} {url}")
        
        return result


# ──────────────────────────────────────────────────────────────────────────
# 全局HTTP客户端实例管理
# ──────────────────────────────────────────────────────────────────────────

_http_client = None


def get_http_client(config: Optional[Dict] = None) -> HTTPClient:
    """
    获取全局HTTP客户端实例（单例模式）
    
    Args:
        config: 配置字典（仅在首次调用时生效）
        
    Returns:
        HTTPClient 实例
    """
    global _http_client
    if _http_client is None:
        _http_client = HTTPClient(config)
    return _http_client


def init_http_client(config: Optional[Dict] = None):
    """
    初始化全局HTTP客户端
    
    在 main.py 启动时调用，确保HTTP客户端使用正确的配置
    
    Args:
        config: 配置字典
    """
    global _http_client
    _http_client = HTTPClient(config)
    logger.info(f"HTTP客户端已初始化: 超时={config.get('default_timeout', 10)}s, "
                f"重试={config.get('retry_times', 2)}次")
