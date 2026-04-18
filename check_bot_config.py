# -*- coding: utf-8 -*-
"""深度诊断：webhook冲突、pending updates、消息接收状态"""
import paramiko
import json

def main():
    env = {}
    with open('.env', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()

    host = env.get('VPS_HOST', '43.159.168.175')
    port = int(env.get('VPS_SSH_PORT', 22))
    user = env.get('VPS_SSH_USER', 'root')
    pwd = env.get('VPS_SSH_PASS', '')

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, port=port, username=user, password=pwd, timeout=15)

    # 完整脚本，避免urllib命名空间问题
    remote_script = '''import json, urllib.request as urq, ssl, time
from urllib.parse import urlencode

with open('/root/mory/config.json', 'r') as f:
    c = json.load(f)
TOKEN = c['TOKEN']
GID = c['GROUP_ID']
ADMIN = c['ADMIN_ID']

ctx = ssl.create_default_context()

def api(method, params=None):
    url = "https://api.telegram.org/bot%s/%s" % (TOKEN, method)
    if params:
        url += "?" + urlencode(params)
    req = urq.Request(url)
    try:
        resp = urq.urlopen(req, timeout=20, context=ctx)
        return json.loads(resp.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}

print("=" * 60)
print("DEEP DIAGNOSIS - v3")
print("=" * 60)

# 1. Webhook status (CRITICAL!)
print("\\n[1] Webhook Status:")
r = api("getWebhookInfo")
if r.get('ok'):
    info = r['result']
    has_webhook = bool(info.get('url'))
    print("  Has webhook: %s" % has_webhook)
    if has_webhook:
        print("  !!! WEBHOOK IS SET - THIS BLOCKS POLLING !!!")
        print("  URL: %s" % info.get('url'))
    else:
        print("  OK: No webhook (polling mode active)")
    pending = info.get('pending_update_count', 0)
    last_err = info.get('last_error_message') or 'None'
    print("  Pending updates: %d" % pending)
    print("  Last error: %s" % str(last_err)[:100])
else:
    print("  ERROR: %s" % r)

# 2. Send test message to group  
print("\\n[2] Send Test Message to Group:")
r = api("sendMessage", {"chat_id": GID, "text": "[Diagnostic Test] Bot check %s" % time.strftime("%H:%M:%S")})
if r.get('ok'):
    msg_id = r['result']['message_id']
    print("  SUCCESS! msg_id=%d" % msg_id)
    print("  >>> LOOK IN YOUR GROUP for [Diagnostic Test] message!")
else:
    print("  FAILED: %s" % r)

# 3. Get bot full info
print("\\n[3] Bot Full Info:")
r = api("getMe")
if r.get('ok'):
    b = r['result']
    for k, v in sorted(b.items()):
        print("  %s: %s" % (k, v))

# 4. Group chat member status
print("\\n[4] Group Member Status:")
bot_id = r['result']['id'] if r.get('ok') else 0
if bot_id:
    r2 = api("getChatMember", {"chat_id": GID, "user_id": bot_id})
    if r2.get('ok'):
        m = r2['result']
        for k, v in sorted(m.items()):
            print("  %s: %s" % (k, v))

# 5. Check getUpdates
print("\\n[5] Pending Updates:")
r3 = api("getUpdates", {"limit": 5, "timeout": 0})
if r3.get('ok'):
    ups = r3.get('result', [])
    print("  Count: %d" % len(ups))
    for u in ups[:3]:
        keys = list(u.keys() - {'update_id'})
        t = keys[0] if keys else '?'
        d = u.get(t, {})
        if isinstance(d, dict):
            fu = d.get('from', {})
            n = fu.get('first_name', '?')
            tx = d.get('text', '')[:30]
            ct = d.get('chat', {}).get('id', '?')
            print("  id=%s type=%s from=%s text=%s chat=%s" % (u['update_id'], t, n, tx, ct))
        else:
            print("  id=%s type=%s" % (u['update_id'], t))

print("\\n" + "=" * 60)
'''

    sftp = ssh.open_sftp()
    try:
        with sftp.file('/tmp/deep_diag.py', 'w') as f:
            f.write(remote_script.encode('utf-8'))
    finally:
        sftp.close()

    stdin, stdout, stderr = ssh.exec_command('python3 /tmp/deep_diag.py', timeout=45)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')

    if out:
        safe = out.encode('ascii', errors='replace').decode('ascii')
        print(safe)
    if err.strip():
        safe_err = err.encode('ascii', errors='replace').decode('ascii')
        print("STDERR:\n%s" % safe_err)

    ssh.close()

if __name__ == '__main__':
    main()
