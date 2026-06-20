#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
健康检查脚本 - 检查 Mory小助理服务状态

检查项：
1. /api/health 端点响应
2. systemd 服务状态
3. 端口监听状态

返回：healthy / unhealthy
"""

import sys
import os
import json
import paramiko
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.vps_config import ssh_connect

# 配置文件路径
CONFIG_PATH = Path(__file__).parent / "rollback_config.json"


def load_config():
    """加载回滚配置"""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def check_health_endpoint(health_url, ssh_client):
    """检查 /api/health 端点"""
    try:
        # 通过 SSH 在 VPS 上执行 curl
        stdin, stdout, stderr = ssh_client.exec_command(
            f"curl -s -w '\\n%{{http_code}}' {health_url}"
        )
        result = stdout.read().decode().strip()
        lines = result.split('\n')
        http_code = lines[-1] if lines else "000"
        body = '\n'.join(lines[:-1]) if len(lines) > 1 else ""
        
        if http_code == "200":
            try:
                data = json.loads(body)
                return {
                    "status": "healthy",
                    "endpoint": "ok",
                    "version": data.get("version", "unknown")
                }
            except json.JSONDecodeError:
                return {"status": "healthy", "endpoint": "ok"}
        else:
            return {"status": "unhealthy", "endpoint": "failed", "http_code": http_code}
    except Exception as e:
        return {"status": "unhealthy", "endpoint": "failed", "error": str(e)}


def check_systemd_service(service_name, ssh_client):
    """检查 systemd 服务状态"""
    try:
        stdin, stdout, stderr = ssh_client.exec_command(
            f"systemctl is-active {service_name}"
        )
        status = stdout.read().decode().strip()
        
        if status == "active":
            return {"status": "healthy", "service": service_name, "state": "active"}
        else:
            return {"status": "unhealthy", "service": service_name, "state": status}
    except Exception as e:
        return {"status": "unhealthy", "service": service_name, "error": str(e)}


def check_port_listening(port, ssh_client):
    """检查端口是否在监听"""
    try:
        stdin, stdout, stderr = ssh_client.exec_command(
            f"ss -tlnp | grep :{port}"
        )
        result = stdout.read().decode().strip()
        
        if result:
            return {"status": "healthy", "port": port, "listening": True}
        else:
            return {"status": "unhealthy", "port": port, "listening": False}
    except Exception as e:
        return {"status": "unhealthy", "port": port, "error": str(e)}


def main():
    """主函数：执行所有健康检查"""
    config = load_config()
    
    # 从 URL 提取端口
    health_url = config["health_check_url"]
    port = int(health_url.split(":")[2].split("/")[0]) if ":" in health_url else 80
    
    print("=== Mory小助理健康检查 ===\n")
    
    # 建立 SSH 连接
    client = paramiko.SSHClient()
    ssh_connect(client)
    
    # 1. 检查健康端点
    print("1. 检查健康端点...")
    endpoint_result = check_health_endpoint(health_url, client)
    print(f"   状态: {endpoint_result['status']}")
    print(f"   详情: {endpoint_result}\n")
    
    # 2. 检查 systemd 服务
    print("2. 检查 systemd 服务...")
    services_result = []
    for service in config["services"]:
        result = check_systemd_service(service, client)
        services_result.append(result)
        print(f"   {service}: {result['status']} ({result.get('state', result.get('error', 'unknown'))})")
    print()
    
    # 3. 检查端口监听
    print("3. 检查端口监听...")
    port_result = check_port_listening(port, client)
    print(f"   端口 {port}: {port_result['status']}")
    print()
    
    client.close()
    
    # 汇总结果
    all_healthy = (
        endpoint_result["status"] == "healthy" and
        all(s["status"] == "healthy" for s in services_result) and
        port_result["status"] == "healthy"
    )
    
    overall_status = "healthy" if all_healthy else "unhealthy"
    
    print("=" * 50)
    print(f"总体状态: {overall_status.upper()}")
    print("=" * 50)
    
    return {
        "overall": overall_status,
        "endpoint": endpoint_result,
        "services": services_result,
        "port": port_result
    }


if __name__ == "__main__":
    result = main()
    sys.exit(0 if result["overall"] == "healthy" else 1)
