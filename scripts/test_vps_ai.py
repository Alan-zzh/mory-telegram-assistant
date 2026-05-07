# -*- coding: utf-8 -*-
import paramiko, sys, io, os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.vps_config import ssh_connect, VPS_PATH

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(ssh)

def run(cmd, timeout=30):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return stdout.read().decode('utf-8', errors='replace').strip()

# Check channel_tracking data (for content stats)
print("=== channel_tracking (content views) ===")
out = run("cd " + VPS_PATH + " && python3 << 'PYEOF'\n"
    "import sqlite3\n"
    "db = sqlite3.connect('mory.db')\n"
    "\n"
    "rows = db.execute('SELECT chat_id, message_id, content_type, current_views FROM channel_tracking LIMIT 10').fetchall()\n"
    "print('Total tracked:', db.execute('SELECT COUNT(*) FROM channel_tracking').fetchone()[0])\n"
    "for r in rows:\n"
    "    print('  chat={} msg={} type={} views={}'.format(r[0], r[1], r[2], r[3]))\n"
    "\n"
    "total_views = db.execute('SELECT SUM(current_views) FROM channel_tracking').fetchone()[0] or 0\n"
    "print('Total views:', total_views)\n"
    "\n"
    "db.close()\n"
    "PYEOF")
print(out)

# Check group_stats data
print("\n=== group_stats ===")
out = run("cd " + VPS_PATH + " && python3 << 'PYEOF'\n"
    "import sqlite3\n"
    "db = sqlite3.connect('mory.db')\n"
    "\n"
    "rows = db.execute('SELECT date, chat_id, joined_count, left_count, net_count, total_members FROM group_stats').fetchall()\n"
    "print('Total rows:', len(rows))\n"
    "for r in rows:\n"
    "    print('  date={} chat={} joined={} left={} net={} total={}'.format(r[0], r[1], r[2], r[3], r[4], r[5]))\n"
    "\n"
    "db.close()\n"
    "PYEOF")
print(out)

# Check today's date in VPS timezone
print("\n=== VPS current date ===")
out = run("date")
print(out)

ssh.close()
