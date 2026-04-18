#!/usr/bin/env python3
"""Check VPS database tables and sample data"""
import paramiko, sys, json, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import ssh_connect

def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_connect(c)
    
    # Upload and run the check script
    sftp = c.open_sftp()
    script = '''
import sqlite3, json
conn = sqlite3.connect("/root/mory/mory.db")
cu = conn.cursor()
cu.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cu.fetchall()]
result = {}
for t in tables:
    count = cu.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    cols = [r[1] for r in cu.execute(f"PRAGMA table_info({t})").fetchall()]
    sample = []
    if count > 0:
        rows = cu.execute(f"SELECT * FROM {t} LIMIT 3").fetchall()
        sample = [dict(zip(cols, row)) for row in rows]
        # Convert non-serializable types
        for s in sample:
            for k,v in s.items():
                if not isinstance(v, (str,int,float,bool,type(None))):
                    s[k] = str(v)
    result[t] = {"count": count, "columns": cols, "sample": sample}
print(json.dumps(result, ensure_ascii=False, default=str))
conn.close()
'''
    with sftp.open('/tmp/_check_db.py', 'w') as f:
        f.write(script)
    sftp.close()
    
    stdin, stdout, stderr = c.exec_command('python3 /tmp/_check_db.py', timeout=15)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    
    if out:
        data = json.loads(out)
        for t, info in data.items():
            print(f"\n=== {t} ({info['count']} rows) ===")
            print(f"  Columns: {', '.join(info['columns'])}")
            if info['sample']:
                for i, row in enumerate(info['sample'][:2]):
                    print(f"  Sample {i+1}: {json.dumps(row, ensure_ascii=False)[:200]}")
    if err:
        print(f"ERROR: {err[:500]}", file=sys.stderr)
    
    c.close()

if __name__ == '__main__':
    main()
