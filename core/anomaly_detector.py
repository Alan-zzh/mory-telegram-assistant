# -*- coding: utf-8 -*-
"""
core/anomaly_detector.py  ·  异常检测器（Z-Score 滑动窗口）

功能：
  1. Z-Score 算法检测指标异常（纯 Python，无 numpy 依赖）
  2. 滑动窗口限制容量（默认 3 小时数据，按数据点数量上限）
  3. 支持多种指标：ERROR 频率、API 响应延迟、转化率等
  4. 线程安全，可被多模块并发调用
  5. 检测到异常时生成结构化报告，供告警系统消费

使用：
  from core.anomaly_detector import anomaly_detector
  anomaly_detector.add_data_point("error_rate", 0.05)
  result = anomaly_detector.detect_anomaly("error_rate")
  if result["is_anomaly"]:
      send_alert("WARNING", result["title"], result["message"], result["context"])
"""

import math
import threading
import time
from collections import deque
from typing import Optional

from core.logging_util import get_logger

logger = get_logger("anomaly_detector")

# 默认配置
_DEFAULT_WINDOW_SIZE = 200        # 滑动窗口最大数据点数（约 3 小时，按 1 分钟/点估算）
_DEFAULT_ZSCORE_THRESHOLD = 3.0   # Z-Score 阈值，超过判定为异常
_MIN_SAMPLES = 10                 # 最少样本数，低于此值不检测（避免误报）


class _MetricWindow:
    """单个指标的滑动窗口数据容器"""

    def __init__(self, window_size: int, zscore_threshold: float):
        self.window_size = window_size
        self.zscore_threshold = zscore_threshold
        # 存储 (timestamp, value) 元组
        self.data: deque = deque(maxlen=window_size)
        self._lock = threading.Lock()
        # 最近一次异常检测结果（缓存，避免重复计算）
        self.last_check_ts: float = 0.0
        self.last_result: Optional[dict] = None

    def add(self, value: float) -> None:
        """添加一个数据点"""
        with self._lock:
            self.data.append((time.time(), float(value)))

    def detect(self) -> dict:
        """
        执行 Z-Score 异常检测。
        返回结构：
          {
            "is_anomaly": bool,
            "metric_name": str,
            "current_value": float,
            "mean": float,
            "std": float,
            "zscore": float,
            "sample_count": int,
            "threshold": float,
          }
        """
        with self._lock:
            values = [v for _, v in self.data]
            self.last_check_ts = time.time()

        n = len(values)
        result = {
            "is_anomaly": False,
            "current_value": values[-1] if values else 0.0,
            "mean": 0.0,
            "std": 0.0,
            "zscore": 0.0,
            "sample_count": n,
            "threshold": self.zscore_threshold,
        }

        if n < _MIN_SAMPLES:
            # 样本不足，不检测
            return result

        # 计算均值
        mean = sum(values) / n
        # 计算标准差（总体标准差）
        variance = sum((x - mean) ** 2 for x in values) / n
        std = math.sqrt(variance)

        result["mean"] = mean
        result["std"] = std

        if std < 1e-9:
            # 标准差为 0（所有值相同），无异常
            return result

        # 计算最新值的 Z-Score
        current = values[-1]
        zscore = abs(current - mean) / std
        result["current_value"] = current
        result["zscore"] = zscore
        result["is_anomaly"] = zscore > self.zscore_threshold

        return result


class AnomalyDetector:
    """
    异常检测器：管理多个指标的滑动窗口与 Z-Score 检测。
    线程安全，支持并发 add_data_point / detect_anomaly。
    """

    def __init__(
        self,
        default_window_size: int = _DEFAULT_WINDOW_SIZE,
        default_zscore_threshold: float = _DEFAULT_ZSCORE_THRESHOLD,
    ):
        self.default_window_size = default_window_size
        self.default_zscore_threshold = default_zscore_threshold
        self._windows: dict[str, _MetricWindow] = {}
        self._lock = threading.Lock()
        # 最近一次异常报告缓存
        self._last_anomaly_report: list[dict] = []
        self._report_lock = threading.Lock()

    def _get_or_create_window(self, metric_name: str) -> _MetricWindow:
        """懒加载指标窗口（首次访问时创建）"""
        window = self._windows.get(metric_name)
        if window is None:
            with self._lock:
                # 双重检查
                window = self._windows.get(metric_name)
                if window is None:
                    window = _MetricWindow(
                        window_size=self.default_window_size,
                        zscore_threshold=self.default_zscore_threshold,
                    )
                    self._windows[metric_name] = window
                    logger.debug(f"[异常检测] 初始化指标窗口: {metric_name} (窗口={self.default_window_size})")
        return window

    def add_data_point(self, metric_name: str, value: float) -> None:
        """
        添加一个数据点。
        metric_name: 指标名称（如 "error_rate", "api_latency", "conversion_rate"）
        value: 指标值（浮点数）
        """
        try:
            window = self._get_or_create_window(metric_name)
            window.add(value)
        except Exception as e:
            logger.error(f"[add_data_point 异常] metric={metric_name}: {type(e).__name__}: {e}")

    def detect_anomaly(self, metric_name: str) -> dict:
        """
        检测指定指标的异常。
        返回：
          {
            "is_anomaly": bool,
            "metric_name": str,
            "current_value": float,
            "mean": float,
            "std": float,
            "zscore": float,
            "sample_count": int,
            "threshold": float,
            "title": str,      # 异常时生成的告警标题
            "message": str,    # 异常时生成的告警消息
            "context": dict,   # 异常时生成的告警上下文
          }
        """
        try:
            window = self._get_or_create_window(metric_name)
            result = window.detect()
            result["metric_name"] = metric_name

            # 生成告警文本（无论是否异常，便于上层直接消费）
            if result["is_anomaly"]:
                result["title"] = f"指标异常检测：{metric_name}"
                result["message"] = (
                    f"Z-Score={result['zscore']:.2f}（阈值 {result['threshold']:.1f}），"
                    f"当前值={result['current_value']:.4f}，"
                    f"均值={result['mean']:.4f}，标准差={result['std']:.4f}，"
                    f"样本数={result['sample_count']}"
                )
                result["context"] = {
                    "metric_name": metric_name,
                    "current_value": result["current_value"],
                    "mean": result["mean"],
                    "std": result["std"],
                    "zscore": result["zscore"],
                    "threshold": result["threshold"],
                    "sample_count": result["sample_count"],
                }
                # 记录到异常报告
                with self._report_lock:
                    self._last_anomaly_report.append({
                        "ts": time.time(),
                        "metric_name": metric_name,
                        "zscore": result["zscore"],
                        "current_value": result["current_value"],
                    })
                    # 只保留最近 50 条异常记录
                    if len(self._last_anomaly_report) > 50:
                        self._last_anomaly_report = self._last_anomaly_report[-50:]
                logger.warning(
                    f"[异常检测] {metric_name} Z-Score={result['zscore']:.2f} "
                    f"超过阈值 {result['threshold']:.1f}，当前值={result['current_value']:.4f}"
                )
            else:
                result["title"] = ""
                result["message"] = ""
                result["context"] = {}

            return result
        except Exception as e:
            logger.error(f"[detect_anomaly 异常] metric={metric_name}: {type(e).__name__}: {e}")
            return {
                "is_anomaly": False,
                "metric_name": metric_name,
                "current_value": 0.0,
                "mean": 0.0,
                "std": 0.0,
                "zscore": 0.0,
                "sample_count": 0,
                "threshold": self.default_zscore_threshold,
                "title": "",
                "message": "",
                "context": {},
            }

    def detect_all(self) -> list[dict]:
        """
        检测所有已注册指标的异常。
        返回异常结果列表（仅包含 is_anomaly=True 的指标）。
        """
        anomalies = []
        with self._lock:
            metric_names = list(self._windows.keys())
        for metric_name in metric_names:
            result = self.detect_anomaly(metric_name)
            if result["is_anomaly"]:
                anomalies.append(result)
        return anomalies

    def get_anomaly_report(self) -> dict:
        """
        获取异常报告摘要。
        返回：
          {
            "total_metrics": int,
            "anomaly_count": int,
            "recent_anomalies": list,
            "metrics_summary": dict,
          }
        """
        with self._lock:
            metric_names = list(self._windows.keys())

        metrics_summary = {}
        anomaly_count = 0
        for metric_name in metric_names:
            window = self._windows.get(metric_name)
            if window is None:
                continue
            with window._lock:
                n = len(window.data)
                last_val = window.data[-1][1] if window.data else 0.0
            metrics_summary[metric_name] = {
                "sample_count": n,
                "latest_value": last_val,
            }
            # 快速检测是否异常
            result = self.detect_anomaly(metric_name)
            if result["is_anomaly"]:
                anomaly_count += 1

        with self._report_lock:
            recent = list(self._last_anomaly_report)

        return {
            "total_metrics": len(metric_names),
            "anomaly_count": anomaly_count,
            "recent_anomalies": recent,
            "metrics_summary": metrics_summary,
        }

    def get_stats(self) -> dict:
        """获取检测器统计信息"""
        with self._lock:
            metric_names = list(self._windows.keys())
        stats = {}
        for metric_name in metric_names:
            window = self._windows.get(metric_name)
            if window is None:
                continue
            with window._lock:
                stats[metric_name] = {
                    "sample_count": len(window.data),
                    "window_size": window.window_size,
                    "threshold": window.zscore_threshold,
                    "last_check_ts": window.last_check_ts,
                }
        return stats


# 模块级单例（懒加载）
_instance: Optional[AnomalyDetector] = None
_instance_lock = threading.Lock()


def _get_instance() -> AnomalyDetector:
    """懒加载单例"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AnomalyDetector()
                logger.info("✅ 异常检测器已初始化（Z-Score 滑动窗口）")
    return _instance


def get_anomaly_detector() -> AnomalyDetector:
    """获取异常检测器单例（外部统一入口）"""
    return _get_instance()


class _AnomalyDetectorProxy:
    """懒加载代理，兼容 from core.anomaly_detector import anomaly_detector。"""

    def __getattr__(self, name):
        return getattr(_get_instance(), name)

    def __repr__(self):
        return "<AnomalyDetectorProxy>"


# 便捷别名
anomaly_detector = _AnomalyDetectorProxy()
