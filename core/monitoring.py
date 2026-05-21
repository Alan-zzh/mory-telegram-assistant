# -*- coding: utf-8 -*-
"""
系统监控模块

提供：
1. 系统资源监控（CPU、内存、磁盘、网络）
2. 应用性能监控（响应时间、错误率、API调用）
3. 业务指标监控（消息处理、用户活跃度）
4. 告警机制
5. 监控数据收集和存储
"""

import os
import time
import psutil
import threading
import json
from datetime import datetime
from typing import Dict, List, Optional
from core.logging_util import get_monitor_logger, get_logger

class SystemMonitor:
    """系统监控类"""
    
    def __init__(self):
        self.logger = get_monitor_logger()
        self.app_logger = get_logger('main')
        self.metrics = {
            'system': {},
            'app': {},
            'business': {}
        }
        self.alert_thresholds = {
            'cpu': 80,  # CPU使用率阈值（%）
            'memory': 85,  # 内存使用率阈值（%）
            'disk': 90,  # 磁盘使用率阈值（%）
            'response_time': 5,  # 响应时间阈值（秒）
            'error_rate': 5,  # 错误率阈值（%）
            'api_failures': 10,  # API失败次数阈值
        }
        self.monitoring_interval = 60  # 监控间隔（秒）
        self.history_data = []  # 历史监控数据
        self.max_history = 1000  # 最大历史数据量
        self.running = False
        self.thread = None
        
    def start(self):
        """启动监控线程"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.thread.start()
            self.logger.info("🚀 系统监控已启动")
    
    def stop(self):
        """停止监控线程"""
        if self.running:
            self.running = False
            if self.thread:
                self.thread.join(timeout=5)
            self.logger.info("⏹️ 系统监控已停止")
    
    def _monitor_loop(self):
        """监控主循环"""
        while self.running:
            try:
                # 收集监控数据
                self.collect_metrics()
                
                # 检查告警
                self.check_alerts()
                
                # 清理历史数据
                self._cleanup_history()
                
                time.sleep(self.monitoring_interval)
            except Exception as e:
                self.logger.error(f"监控循环异常: {e}")
                time.sleep(self.monitoring_interval)
    
    def collect_metrics(self):
        """收集监控指标"""
        # 系统指标
        self.metrics['system'] = self._collect_system_metrics()
        
        # 应用指标（从应用日志和状态中收集）
        self.metrics['app'] = self._collect_app_metrics()
        
        # 业务指标
        self.metrics['business'] = self._collect_business_metrics()
        
        # 记录监控数据
        self._record_metrics()
    
    def _collect_system_metrics(self) -> Dict:
        """收集系统资源指标"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            network = psutil.net_io_counters()
            
            return {
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_used_mb': memory.used / (1024 * 1024),
                'memory_total_mb': memory.total / (1024 * 1024),
                'disk_percent': disk.percent,
                'disk_used_gb': disk.used / (1024 * 1024 * 1024),
                'disk_total_gb': disk.total / (1024 * 1024 * 1024),
                'network_sent_mb': network.bytes_sent / (1024 * 1024),
                'network_recv_mb': network.bytes_recv / (1024 * 1024),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            self.logger.error(f"收集系统指标失败: {e}")
            return {}
    
    def _collect_app_metrics(self) -> Dict:
        """收集应用性能指标"""
        # 这里可以从应用状态中收集指标
        # 例如：响应时间、错误率、API调用次数等
        return {
            'response_time': 0.0,  # 待实现
            'error_rate': 0.0,  # 待实现
            'api_calls': 0,  # 待实现
            'api_failures': 0,  # 待实现
            'timestamp': datetime.now().isoformat()
        }
    
    def _collect_business_metrics(self) -> Dict:
        """收集业务指标"""
        # 这里可以从业务逻辑中收集指标
        # 例如：消息处理量、用户活跃度、转化率等
        return {
            'messages_processed': 0,  # 待实现
            'active_users': 0,  # 待实现
            'conversion_rate': 0.0,  # 待实现
            'timestamp': datetime.now().isoformat()
        }
    
    def check_alerts(self):
        """检查告警条件"""
        # 系统告警
        system = self.metrics.get('system', {})
        if system:
            if system.get('cpu_percent', 0) > self.alert_thresholds['cpu']:
                self._trigger_alert('CPU使用率过高', f"CPU使用率: {system['cpu_percent']}%")
            
            if system.get('memory_percent', 0) > self.alert_thresholds['memory']:
                self._trigger_alert('内存使用率过高', f"内存使用率: {system['memory_percent']}%")
            
            if system.get('disk_percent', 0) > self.alert_thresholds['disk']:
                self._trigger_alert('磁盘使用率过高', f"磁盘使用率: {system['disk_percent']}%")
        
        # 应用告警
        app = self.metrics.get('app', {})
        if app:
            if app.get('response_time', 0) > self.alert_thresholds['response_time']:
                self._trigger_alert('响应时间过长', f"响应时间: {app['response_time']}秒")
            
            if app.get('error_rate', 0) > self.alert_thresholds['error_rate']:
                self._trigger_alert('错误率过高', f"错误率: {app['error_rate']}%")
            
            if app.get('api_failures', 0) > self.alert_thresholds['api_failures']:
                self._trigger_alert('API失败次数过多', f"API失败次数: {app['api_failures']}")
    
    def _trigger_alert(self, title: str, message: str):
        """触发告警"""
        alert_info = {
            'title': title,
            'message': message,
            'level': 'warning',
            'timestamp': datetime.now().isoformat()
        }
        
        self.logger.warning(f"[告警] {title}: {message}")
        
        try:
            from modules.auto_tasks import report_fault
            report_fault(f"系统资源告警: {title}", message, "⚠️")
        except Exception:
            pass
    
    def _record_metrics(self):
        """记录监控数据"""
        metrics_data = {
            'timestamp': datetime.now().isoformat(),
            'metrics': self.metrics.copy()
        }
        
        self.history_data.append(metrics_data)
        
        # 记录到监控日志
        self.logger.info(f"监控数据: {json.dumps(metrics_data, ensure_ascii=False)}")
    
    def _cleanup_history(self):
        """清理历史数据"""
        if len(self.history_data) > self.max_history:
            self.history_data = self.history_data[-self.max_history:]
    
    def get_metrics(self) -> Dict:
        """获取当前监控指标"""
        return self.metrics.copy()
    
    def get_history(self, limit: int = 100) -> List[Dict]:
        """获取历史监控数据"""
        return self.history_data[-limit:]
    
    def get_status(self) -> Dict:
        """获取监控状态"""
        return {
            'running': self.running,
            'interval': self.monitoring_interval,
            'history_count': len(self.history_data),
            'last_update': datetime.now().isoformat()
        }

# 全局监控实例
_system_monitor = None


def get_system_monitor() -> SystemMonitor:
    """获取系统监控实例"""
    global _system_monitor
    if _system_monitor is None:
        _system_monitor = SystemMonitor()
    return _system_monitor


def start_monitoring():
    """启动监控"""
    monitor = get_system_monitor()
    monitor.start()


def stop_monitoring():
    """停止监控"""
    monitor = get_system_monitor()
    monitor.stop()


def get_monitoring_status():
    """获取监控状态"""
    monitor = get_system_monitor()
    return monitor.get_status()


def get_current_metrics():
    """获取当前监控指标"""
    monitor = get_system_monitor()
    return monitor.get_metrics()


__all__ = [
    'SystemMonitor',
    'get_system_monitor',
    'start_monitoring',
    'stop_monitoring',
    'get_monitoring_status',
    'get_current_metrics',
]