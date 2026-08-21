#!/usr/bin/env python3
"""用当前规则回放历史广告快照，只输出脱敏候选，不自动解封。"""

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.ad_detector import AdDetector


def replay(db_path: Path, limit: int = 5000) -> dict:
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    rows = conn.execute(
        """SELECT chat_id,msg_id,user_id,text,ts
           FROM message_snapshots WHERE is_ad=1
           ORDER BY ts DESC LIMIT ?""",
        (int(limit),),
    ).fetchall()
    conn.close()
    detector = AdDetector(config={"AD_AI_REVIEW_ENABLED": False})
    candidates = []
    still_ads = 0
    for chat_id, msg_id, user_id, text, ts in rows:
        value = str(text or "")
        result = detector.detect(username="", msg=value, bio="")
        if result.get("is_ad"):
            still_ads += 1
            continue
        candidates.append({
            "chat_id": int(chat_id), "msg_id": int(msg_id), "user_id": int(user_id),
            "ts": int(ts), "text_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "new_score": int(result.get("score", 0) or 0),
            "new_evidence": result.get("evidence") or [],
            "decision": "manual_review_candidate",
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "message_snapshots.is_ad=1",
        "replayed": len(rows), "still_ad": still_ads,
        "candidate_count": len(candidates), "candidates": candidates,
        "privacy": "message text omitted; SHA-256 only",
        "auto_restore_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="mory.db")
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()
    report = replay(Path(args.db), args.limit)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("replayed", "still_ad", "candidate_count", "auto_restore_count")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
