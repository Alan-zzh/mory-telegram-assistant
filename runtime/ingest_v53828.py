# -*- coding: utf-8 -*-
"""v5.38.28 VPS 录入：54 组人设样本（清旧插新）+ INPUT_HINTS + PRICE_LIST 社交解锁 2 阶。"""
from __future__ import annotations

import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paramiko

from core.vps_config import VPS_PATH, ssh_connect


def main() -> int:
    b64_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preset_payload_b64_v53828.txt")
    with open(b64_path, encoding="ascii") as f:
        b64 = f.read().strip()
    payload = base64.b64decode(b64).decode("utf-8")

    # VPS 侧执行脚本（base64 载荷内嵌，避免引号转义）
    remote = f"""
# -*- coding: utf-8 -*-
import json, sys, time
sys.path.insert(0, ".")
from core.database import DB

DATA = json.loads({json.dumps(payload)})
db = DB("mory.db")
conn = db.conn

# 1. 清旧：删除旧 12 组预设（label 以 "预设-" 开头）与同 user_text 的重复
cur = conn.execute("DELETE FROM reply_style_samples WHERE label LIKE '预设-%' OR label LIKE 'v5.38.28-%'")
print("OLD_DELETED=", cur.rowcount)

# 2. 插入 54 组
now = int(time.time())
inserted = 0
for scene, user_text, mory_text, override in DATA["samples"]:
    style_text = f"用户：{{user_text}}\\nMory：{{mory_text}}"
    label = f"v5.38.28-{{scene}}-{{user_text[:10]}}"
    note = "管理员确认放行（含真实业务词/傲娇话术/短句用户话语）" if override else ""
    conn.execute(
        "INSERT INTO reply_style_samples (label, style_text, status, enabled, created_by, scene, created_at, review_note) "
        "VALUES (?, ?, 'pending', 0, 'admin', ?, ?, ?)",
        (label, style_text, scene, now, note),
    )
    inserted += 1
conn.commit()
print("INSERTED=", inserted)

# 3. INPUT_HINTS 写入 config.json（safe 方式：读改写）
import json as _json
cfg_path = "config.json"
with open(cfg_path, encoding="utf-8") as f:
    cfg = _json.load(f)
cfg["INPUT_HINTS"] = DATA["input_hints"]
with open(cfg_path, "w", encoding="utf-8") as f:
    _json.dump(cfg, f, ensure_ascii=False, indent=2)
print("INPUT_HINTS_SET=", len(DATA["input_hints"]))

# 4. PRICE_LIST 社交解锁 2 阶
pl = cfg.get("PRICE_LIST", {{}})
for key, val in DATA["price_overrides"].items():
    if val is None:
        pl.pop(key, None)
        print("PRICE_DELETED=", key)
    else:
        pl[key] = {{"price": val["price"], "note": val["note"]}}
        print("PRICE_SET=", key, val["price"])
with open(cfg_path, "w", encoding="utf-8") as f:
    _json.dump(cfg, f, ensure_ascii=False, indent=2)
print("PRICE_OK")

# 5. 验证
rows = conn.execute("SELECT COUNT(*), status FROM reply_style_samples GROUP BY status").fetchall()
print("STATUS=", rows)
"""
    # base64 包装远程脚本
    remote_b64 = base64.b64encode(remote.encode("utf-8")).decode("ascii")

    c = paramiko.SSHClient()
    ssh_connect(c, timeout=15)

    def run(cmd: str, timeout: int = 60) -> str:
        stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        return out + ("\nSTDERR: " + err[:600] if err else "")

    # 上传并执行
    upload = (
        f"cd {VPS_PATH} && echo {remote_b64} | base64 -d > runtime/_v53828_ingest.py && "
        f"python3 runtime/_v53828_ingest.py"
    )
    print(run(upload, timeout=120))
    run(f"rm -f {VPS_PATH}/runtime/_v53828_ingest.py")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
