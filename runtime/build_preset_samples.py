# -*- coding: utf-8 -*-
"""预设样本定义 + 安全校验 + 生成 VPS 录入脚本（base64 载荷）。

用法：
  python runtime/build_preset_samples.py
  输出：
    1. 本地校验结果（validate_feed_sample_safety + 人设红线）
    2. payload_base64.txt（供 SSH 在 VPS 执行录入）
"""
from __future__ import annotations

import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PRESET_SAMPLES = [
    # (scene, user_text, mory_text)  用户话术保持真实高频短句但满足 >=5 字校验
    ("chat", "在吗，有空聊两句吗", "在，怎么啦？"),
    ("chat", "有点想你了", "收到，这句话还挺会哄人的。"),
    ("chat", "今天好无聊啊", "那说个你最近最想吐槽的事？"),
    ("greeting", "早上好啊大家", "早，今天按自己的节奏来就行，不用跟谁比。"),
    ("greeting", "晚安，好梦", "晚安，明天见。"),
    ("engage", "你们这多少钱", "价格的事不急着定，先看看 @moryselect 里的预览值不值，你看完我们再慢慢说。"),
    ("engage", "想问问怎么订阅", "想订阅的话，先去 @moryselect 看看预览和说明，觉得合适再继续。"),
    ("engage", "有什么权益", "权益以预览和公告为准，@moryselect 里能看到实际内容。"),
    ("faq", "怎么签到啊", "发简体\"签到\"两个字就行。"),
    ("faq", "我被误封了怎么办", "别急，把你的情况和群号发给我，我帮你查一下。"),
    ("faq", "能帮我算一卦吗", "可以呀，你先把想问的事压成一句话，我帮你看看。"),
    ("broadcast", "今天的黄历怎么说", "今天的宜忌和方位早上都发过啦，没看到的话我再说一遍。"),
]

VPS_PAYLOAD = r'''
# -*- coding: utf-8 -*-
"""VPS 端录入预设样本（pending）。由 build_preset_samples.py 生成。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db_repos.reply_evolution_repo import validate_feed_sample_safety
from core.database import DB

SAMPLES = __SAMPLES__

db = DB("mory.db")  # ingest 脚本在 VPS_PATH 下执行，工作目录即项目根
repo = db.reply_evolution
ok_count = 0
errors = []
for scene, user_text, mory_text in SAMPLES:
    vok, reason = validate_feed_sample_safety(user_text, mory_text)
    if not vok:
        errors.append(f"[{scene}] {user_text}: {reason}")
        continue
    combined = f"用户：{user_text}\nMory：{mory_text}"
    result = repo.create_reply_style_sample(
        combined, label=f"预设-{scene}", created_by="admin",
        scene=scene, user_text=user_text, mory_text=mory_text,
    )
    if result.get("ok"):
        ok_count += 1
    else:
        errors.append(f"[{scene}] {user_text}: {result.get('error', 'save fail')}")
print(f"INSERT_OK={ok_count} ERRORS={len(errors)}")
for e in errors:
    print("ERR:", e)
'''

# 人设红线本地校验：禁区词
from tasks.support.message_templates import MessageTemplates  # noqa: E402

_BAN = MessageTemplates.GREETING_STYLE_BAN


def main() -> int:
    from core.db_repos.reply_evolution_repo import validate_feed_sample_safety

    print("== 本地校验 ==")
    all_ok = True
    for scene, user_text, mory_text in PRESET_SAMPLES:
        vok, reason = validate_feed_sample_safety(user_text, mory_text)
        ban_hits = [b for b in _BAN if b in user_text or b in mory_text]
        if not vok:
            print(f"  FAIL [{scene}] {user_text}: {reason}")
            all_ok = False
        if ban_hits:
            print(f"  BAN  [{scene}] {user_text}: {ban_hits}")
            all_ok = False
        if not all_ok:
            continue
        print(f"  OK   [{scene}] {user_text} -> {mory_text[:30]}")
    print("LOCAL_VALIDATE", "PASS" if all_ok else "FAIL")

    payload = VPS_PAYLOAD.replace("__SAMPLES__", json.dumps(PRESET_SAMPLES, ensure_ascii=False))
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "runtime", "preset_payload_b64.txt")
    with open(out, "w", encoding="ascii") as f:
        f.write(b64)
    print(f"PAYLOAD_SAVED={out} (len={len(b64)})")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
