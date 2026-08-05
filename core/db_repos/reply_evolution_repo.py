# -*- coding: utf-8 -*-
"""人工审核的回复风格样本库。

这里保存的是管理员主动编写的风格提示，不收集或回灌用户原文。样本只有在
“已审核 + 已启用”两个条件都满足时才允许进入 AI 提示词。
"""
from __future__ import annotations

import re
import time
from typing import Any

from core.logging_util import get_logger

logger = get_logger("db.reply_evolution")

# 样本场景分组：chat（普通聊天）/ greeting（问候）/ engage（搭讪承接）/ faq（FAQ 问答）/ broadcast（播报文案）
VALID_SCENES = ("chat", "greeting", "engage", "faq", "broadcast")


def normalize_scene(scene: str | None) -> str | None:
    """规整并校验 scene；非法值返回 None（表示不过滤 / 使用默认 chat）。"""
    if scene is None:
        return None
    scene = str(scene).strip().lower()
    if scene in VALID_SCENES:
        return scene
    return None


_UNSAFE_STYLE_PATTERNS = (
    (r"[（(][^）)\n]{0,80}(?:歪头|托腮|凑近|眨眼|嘟嘴|伸懒腰|看窗外|内心|心里)[^）)\n]{0,80}[）)]", "动作或内心旁白"),
    (r"\*[^*\n]{0,80}(?:歪头|托腮|凑近|眨眼|嘟嘴|伸懒腰|看窗外|内心|心里)[^*\n]{0,80}\*", "动作描写"),
    (r"(?:4k|原档|独家|保证|包过|限时|仅剩|最后\d|手慢无|福利|库存)", "未经核验的商品事实或稀缺承诺"),
    (r"(?:大家都|好多人都|老粉都懂|别人都在|都说|错过就没)", "虚假社交证明或施压"),
    (r"(?:@moryselect.*@morychannelbot|@morychannelbot.*@moryselect)", "同一示例含冲突 CTA"),
    (r"(?:我是(?:真人|人类)|不是(?:ai|机器人|程序|模型)|绝对不是)", "真人或反 AI 身份口径"),
)


def validate_reply_style_sample(style_text: str, max_len: int = 500) -> tuple[bool, str]:
    """返回样本能否进入待审库；不安全的文案连待审库也不接收。"""
    text = str(style_text or "").strip()
    if not 8 <= len(text) <= max_len:
        return False, f"风格样本长度必须在 8 到 {max_len} 个字符之间"
    lowered = text.lower()
    for pattern, reason in _UNSAFE_STYLE_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return False, f"样本包含{reason}"
    return True, ""


def validate_feed_sample_safety(user_text: str, mory_text: str) -> tuple[bool, str]:
    """投喂样本安全校验：两段均 5-500 字，且拒绝动作旁白/营销承诺等敏感词。

    仿照 ai_reply_handler._UNVERIFIED_SALES_CLAIM_PATTERN 的思路，
    保证/包过/限时福利 等未经核验的商品承诺一律拒绝，连待审库也不接收。
    """
    for label, text in (("用户话术", user_text), ("Mory回复", mory_text)):
        t = str(text or "").strip()
        if not 5 <= len(t) <= 500:
            return False, f"{label}长度必须在 5 到 500 个字符之间"
    lowered = f"{user_text} {mory_text}".lower()
    for pattern, reason in _UNSAFE_STYLE_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return False, f"样本包含{reason}"
    return True, ""


class ReplyEvolutionRepo:
    """回复风格样本的显式审核工作流。"""

    def __init__(self, db: Any):
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    @property
    def lock(self):
        return self._db.lock

    def _ensure_schema(self) -> bool:
        """兼容 Dashboard 直连 SQLite 的渐进初始化。"""
        with self.lock:
            try:
                self.conn.execute("""CREATE TABLE IF NOT EXISTS reply_style_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL DEFAULT '',
                    style_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
                    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
                    created_by TEXT NOT NULL DEFAULT '',
                    reviewed_by TEXT NOT NULL DEFAULT '',
                    review_note TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    reviewed_at INTEGER NOT NULL DEFAULT 0,
                    scene TEXT NOT NULL DEFAULT 'chat'
                )""")
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_reply_style_samples_active "
                    "ON reply_style_samples(status, enabled, reviewed_at)"
                )
                self._ensure_scene_column()
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_reply_style_samples_scene "
                    "ON reply_style_samples(scene)"
                )
                self.conn.commit()
                return True
            except Exception as exc:
                logger.warning("初始化回复风格样本库失败: %s", exc)
                return False

    def _ensure_scene_column(self) -> bool:
        """幂等补列：兼容旧库已存在但缺少 scene 列的 reply_style_samples 表。"""
        with self.lock:
            try:
                cols = {
                    row[1]
                    for row in self.conn.execute("PRAGMA table_info(reply_style_samples)").fetchall()
                }
                if "scene" not in cols:
                    self.conn.execute(
                        "ALTER TABLE reply_style_samples ADD COLUMN scene TEXT NOT NULL DEFAULT 'chat'"
                    )
                    self.conn.commit()
                return True
            except Exception as exc:
                logger.warning("补 reply_style_samples.scene 列失败: %s", exc)
                return False

    def create_reply_style_sample(
        self,
        style_text: str = "",
        label: str = "",
        created_by: str = "",
        scene: str = "chat",
        user_text: str = "",
        mory_text: str = "",
    ) -> dict:
        """创建待审样本（永远只生成 pending，不自动启用）。

        传 user_text/mory_text 时为投喂对模式：两段各自做 5-500 字安全校验，
        拼接后的 style_text 长度上限放宽到 1100。
        """
        scene = normalize_scene(scene)
        if scene is None:
            return {"ok": False, "error": "scene 仅支持 chat/greeting/engage/faq/broadcast"}
        if user_text or mory_text:
            ok, reason = validate_feed_sample_safety(user_text, mory_text)
            if not ok:
                return {"ok": False, "error": reason}
            text = str(style_text or "").strip()
            if not 8 <= len(text) <= 1100:
                return {"ok": False, "error": "投喂样本拼接后长度必须在 8 到 1100 个字符之间"}
            ok, reason = validate_reply_style_sample(text, max_len=1100)
            if not ok:
                return {"ok": False, "error": reason}
        else:
            ok, reason = validate_reply_style_sample(style_text)
            if not ok:
                return {"ok": False, "error": reason}
            text = str(style_text or "").strip()
        label = str(label or "").strip()[:80]
        self._ensure_scene_column()
        with self.lock:
            try:
                cursor = self.conn.execute(
                    "INSERT INTO reply_style_samples "
                    "(label, style_text, status, enabled, created_by, scene, created_at) "
                    "VALUES (?, ?, 'pending', 0, ?, ?, ?)",
                    (label, text, str(created_by or "")[:80], scene, int(time.time())),
                )
                self.conn.commit()
                return {"ok": True, "id": int(cursor.lastrowid), "status": "pending"}
            except Exception as exc:
                logger.warning("创建回复风格样本失败: %s", exc)
                return {"ok": False, "error": "保存失败"}

    def list_reply_style_samples(
        self, status: str | None = None, limit: int = 100, scene: str | None = None
    ) -> list[dict]:
        """列表查询；scene 支持过滤，None 表示不过滤。"""
        safe_limit = max(1, min(int(limit or 100), 200))
        scene = normalize_scene(scene)
        self._ensure_scene_column()
        with self.lock:
            if status in {"pending", "approved", "rejected"}:
                if scene:
                    rows = self.conn.execute(
                        "SELECT id, label, style_text, status, enabled, created_by, reviewed_by, "
                        "created_at, reviewed_at, review_note FROM reply_style_samples "
                        "WHERE status=? AND scene=? ORDER BY id DESC LIMIT ?",
                        (status, scene, safe_limit),
                    ).fetchall()
                else:
                    rows = self.conn.execute(
                        "SELECT id, label, style_text, status, enabled, created_by, reviewed_by, "
                        "created_at, reviewed_at, review_note FROM reply_style_samples "
                        "WHERE status=? ORDER BY id DESC LIMIT ?",
                        (status, safe_limit),
                    ).fetchall()
            else:
                if scene:
                    rows = self.conn.execute(
                        "SELECT id, label, style_text, status, enabled, created_by, reviewed_by, "
                        "created_at, reviewed_at, review_note FROM reply_style_samples "
                        "WHERE scene=? ORDER BY id DESC LIMIT ?",
                        (scene, safe_limit),
                    ).fetchall()
                else:
                    rows = self.conn.execute(
                        "SELECT id, label, style_text, status, enabled, created_by, reviewed_by, "
                        "created_at, reviewed_at, review_note FROM reply_style_samples "
                        "ORDER BY id DESC LIMIT ?",
                        (safe_limit,),
                    ).fetchall()
        fields = ("id", "label", "style_text", "status", "enabled", "created_by", "reviewed_by", "created_at", "reviewed_at", "review_note")
        return [dict(zip(fields, row)) for row in rows]

    def review_reply_style_sample(
        self, sample_id: int, status: str, reviewed_by: str = "", review_note: str = "", enabled: bool = False
    ) -> dict:
        if status not in {"approved", "rejected"}:
            return {"ok": False, "error": "审核状态只能为 approved 或 rejected"}
        with self.lock:
            row = self.conn.execute(
                "SELECT style_text FROM reply_style_samples WHERE id=?", (int(sample_id),)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "样本不存在"}
            if status == "approved":
                ok, reason = validate_reply_style_sample(row[0])
                if not ok:
                    return {"ok": False, "error": reason}
            use_enabled = 1 if status == "approved" and bool(enabled) else 0
            self.conn.execute(
                "UPDATE reply_style_samples SET status=?, enabled=?, reviewed_by=?, review_note=?, reviewed_at=? WHERE id=?",
                (status, use_enabled, str(reviewed_by or "")[:80], str(review_note or "")[:300], int(time.time()), int(sample_id)),
            )
            self.conn.commit()
        return {"ok": True, "status": status, "enabled": bool(use_enabled)}

    def set_reply_style_sample_enabled(self, sample_id: int, enabled: bool, reviewed_by: str = "") -> dict:
        with self.lock:
            row = self.conn.execute(
                "SELECT style_text, status FROM reply_style_samples WHERE id=?", (int(sample_id),)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "样本不存在"}
            if enabled:
                if row[1] != "approved":
                    return {"ok": False, "error": "只有已审核通过的样本才能启用"}
                ok, reason = validate_reply_style_sample(row[0])
                if not ok:
                    return {"ok": False, "error": reason}
            self.conn.execute(
                "UPDATE reply_style_samples SET enabled=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                (1 if enabled else 0, str(reviewed_by or "")[:80], int(time.time()), int(sample_id)),
            )
            self.conn.commit()
        return {"ok": True, "enabled": bool(enabled)}

    def get_approved_reply_style_samples(self, limit: int = 3, scene: str | None = None) -> list[str]:
        """运行时唯一读取入口：只返回审核通过且启用的安全样本。

        scene=None 返回全部场景；scene='x' 只返回该场景分组。
        """
        safe_limit = max(1, min(int(limit or 3), 3))
        scene = normalize_scene(scene)
        self._ensure_scene_column()
        with self.lock:
            if scene:
                rows = self.conn.execute(
                    "SELECT style_text FROM reply_style_samples "
                    "WHERE status='approved' AND enabled=1 AND scene=? "
                    "ORDER BY reviewed_at DESC, id DESC LIMIT ?",
                    (scene, safe_limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT style_text FROM reply_style_samples "
                    "WHERE status='approved' AND enabled=1 ORDER BY reviewed_at DESC, id DESC LIMIT ?",
                    (safe_limit,),
                ).fetchall()
        samples: list[str] = []
        for row in rows:
            text = str(row[0] or "").strip()
            ok, _ = validate_reply_style_sample(text)
            if ok:
                samples.append(text)
        return samples
