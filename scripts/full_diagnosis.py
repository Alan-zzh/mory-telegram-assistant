# -*- coding: utf-8 -*-
"""全面诊断VPS所有功能状态"""
import paramiko, sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS, VPS_PATH, ssh_connect

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(client)

def run(cmd, timeout=30):
    _, out, err = client.exec_command(cmd, timeout=timeout)
    return out.read().decode('utf-8', errors='replace').strip(), err.read().decode('utf-8', errors='replace').strip()

print("="*70)
print("📊 VPS全面功能诊断报告")
print("="*70)

# 1. 检查API密钥
print("\n【1】API密钥检查")
r, _ = run("python3 -c \"import json; c=json.load(open('/root/mory/config.json','r')); ak=c.get('API_KEY',''); aks=c.get('API_KEYS',{}); print('API_KEY字段:', '有值' if ak else '空'); print('API_KEYS字段:', '存在' if aks else '缺失'); print('API_KEY前20字符:', ak[:20] if ak else '无')\"")
print(r)

# 2. 检查问候任务是否成功发送
print("\n【2】早安/午安/晚安问候状态")
r, _ = run("grep -E '早安|午安|晚安|早安问候|午安问候|晚安问候' /root/mory/mory.log | tail -20")
print(r if r else "(无相关日志)")

# 3. 检查新闻播报是否成功发送
print("\n【3】新闻播报状态")
r, _ = run("grep -E '新闻播报|早报|午报|晚报|已发送|发送成功' /root/mory/mory.log | tail -20")
print(r if r else "(无相关日志)")

# 4. 检查每日报告
print("\n【4】每日数据报告状态")
r, _ = run("grep -E '每日报告|每日数据报告|报告失败' /root/mory/mory.log | tail -10")
print(r if r else "(无相关日志)")

# 5. 检查醋意挽回
print("\n【5】醋意挽回状态")
r, _ = run("grep -E '醋意挽回|挽回发送|reactivate' /root/mory/mory.log | tail -10")
print(r if r else "(无相关日志)")

# 6. 检查所有任务调度
print("\n【6】APScheduler任务调度状态")
r, _ = run("grep 'apscheduler' /root/mory/mory.log | tail -30")
print(r if r else "(无相关日志)")

# 7. 检查数据库表结构
print("\n【7】数据库表结构")
r, _ = run("sqlite3 /root/mory/mory.db '.tables'")
print("表列表:", r)
r, _ = run("sqlite3 /root/mory/mory.db '.schema'")
print("完整schema:")
print(r)

# 8. 检查VPS Python环境
print("\n【8】VPS Python环境")
r, _ = run("python3 --version && pip3 list 2>/dev/null | grep -i -E 'openai|httpx|requests|apscheduler'")
print(r)

# 9. 测试网络连通性（API端点）
print("\n【9】API端点连通性测试")
r, _ = run("curl -s --max-time 5 -o /dev/null -w '阿里云: %{http_code}\\n' https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
print(r)
r, _ = run("curl -s --max-time 5 -o /dev/null -w '百度热搜: %{http_code}\\n' https://top.baidu.com/board?tab=realtime")
print(r)
r, _ = run("curl -s --max-time 5 -o /dev/null -w '微博: %{http_code}\\n' https://weibo.com/ajax/side/hotSearch")
print(r)

# 10. 检查本地和VPS代码差异
print("\n【10】本地vs VPS main.py 深夜回复检查")
r, _ = run("grep -n '_generate_late_night\\|hardcoded\\|硬编码' /root/mory/main.py | head -5")
print(r if r else "(无)")

client.close()
print("\n" + "="*70)
print("✅ 诊断完成")
print("="*70)
