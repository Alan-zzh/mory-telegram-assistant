# -*- coding: utf-8 -*-
"""列出 reply_style_samples 预设样本与 keyword 高频触发词（供用户对照填写）。只读。"""
from __future__ import annotations

import sqlite3
import sys

DB_PATH = "mory.db"


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    print("== reply_style_samples ==")
    try:
        rows = conn.execute(
            "SELECT scene, user_text, mory_text, status FROM reply_style_samples ORDER BY id DESC LIMIT 30"
        ).fetchall()
        for r in rows:
            print(f" - [{r[3]}] {r[0]} | 用户: {str(r[1])[:40]} | Mory: {str(r[2])[:50]}")
        if not rows:
            print("(本地库为空，样本已录入 VPS 生产库)")
    except Exception as e:
        print("err:", e)
    print("== keyword_triggers 高频触发词 ==")
    try:
        rows = conn.execute(
            "SELECT keyword, hit_count FROM keyword_triggers ORDER BY hit_count DESC LIMIT 25"
        ).fetchall()
        for r in rows:
            print(f"  [{r[1]}] {str(r[0])[:50]}")
    except Exception as e:
        print("err:", e)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
