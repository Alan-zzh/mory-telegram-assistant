# -*- coding: utf-8 -*-
"""问题追踪功能域数据操作"""
import time
import re
from datetime import datetime

from core.logging_util import get_logger
from core.db_repos._constants import _CST

logger = get_logger("db.question")


class QuestionRepo:
    """问题追踪与FAQ蒸馏数据库操作"""

    def __init__(self, db):
        """db: DB实例，通过 db.conn 和 db.lock 访问连接和锁"""
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    @property
    def lock(self):
        return self._db.lock

    # ─────────────────────────────── 用户问题记录 ────────────────────────────

    def log_question(self, uid, chat_id, question_text, mode='', intent='',
                     keyword_tag='', question_category='other', is_convert=0):
        """记录一条用户提问，返回新行id

        Args:
            uid: 用户ID
            chat_id: 群ID
            question_text: 问题文本（截断到500字符）
            mode: 对话模式
            intent: 意图标签
            keyword_tag: 命中关键词标签
            question_category: 问题分类
            is_convert: 是否转化（0/1）

        Returns:
            新插入行的id，失败返回0
        """
        with self.lock:
            try:
                cur = self.conn.cursor()
                cur.execute(
                    """INSERT INTO user_questions
                       (uid, chat_id, question_text, mode, intent, keyword_tag,
                        question_category, is_convert, ai_reply_summary, faq_hit_id, ts)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (int(uid), int(chat_id), str(question_text)[:500],
                     str(mode), str(intent), str(keyword_tag),
                     str(question_category), int(is_convert), '', 0, int(time.time())),
                )
                self.conn.commit()
                return cur.lastrowid
            except Exception as e:
                logger.error(f"记录用户提问失败：{e}")
                return 0

    def update_question_reply(self, question_id, ai_reply_summary, faq_hit_id=0) -> bool:
        """更新问题的AI回复摘要和FAQ命中ID

        Args:
            question_id: 问题记录ID
            ai_reply_summary: AI回复摘要（截断到200字符）
            faq_hit_id: 命中的FAQ知识库ID

        Returns:
            True=成功，False=失败
        """
        with self.lock:
            try:
                self.conn.execute(
                    """UPDATE user_questions
                       SET ai_reply_summary=?, faq_hit_id=?
                       WHERE id=?""",
                    (str(ai_reply_summary)[:200], int(faq_hit_id), int(question_id)),
                )
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"更新问题回复摘要失败：{e}")
                return False

    def get_question_stats(self):
        """获取问题统计概览

        Returns:
            {
                total_count: 总问题数,
                today_count: 今日问题数,
                faq_hit_rate: FAQ命中率（百分比）,
                category_distribution: {分类: 数量},
                top_questions: [{question_text, count}, ...] 前20高频问题
            }
        """
        try:
            c = self.conn.cursor()
            # 总数
            c.execute("SELECT COUNT(*) FROM user_questions")
            total = c.fetchone()[0]
            # 今日（CST 0点起）
            today_start = int(datetime.now(_CST).replace(
                hour=0, minute=0, second=0, microsecond=0).timestamp())
            c.execute("SELECT COUNT(*) FROM user_questions WHERE ts>=?", (today_start,))
            today = c.fetchone()[0]
            # FAQ命中率
            c.execute("SELECT COUNT(*) FROM user_questions WHERE faq_hit_id>0")
            faq_hit = c.fetchone()[0]
            faq_hit_rate = (faq_hit / total * 100) if total > 0 else 0.0
            # 分类分布
            c.execute("""SELECT question_category, COUNT(*) FROM user_questions
                         GROUP BY question_category ORDER BY COUNT(*) DESC""")
            category_distribution = {r[0]: r[1] for r in c.fetchall()}
            # 高频问题TOP20
            c.execute("""SELECT question_text, COUNT(*) as cnt FROM user_questions
                         GROUP BY question_text ORDER BY cnt DESC LIMIT 20""")
            top_questions = [{"question_text": r[0], "count": r[1]} for r in c.fetchall()]
            return {
                "total_count": total,
                "today_count": today,
                "faq_hit_rate": round(faq_hit_rate, 2),
                "category_distribution": category_distribution,
                "top_questions": top_questions,
            }
        except Exception as e:
            logger.error(f"获取问题统计失败：{e}")
            return {
                "total_count": 0,
                "today_count": 0,
                "faq_hit_rate": 0.0,
                "category_distribution": {},
                "top_questions": [],
            }

    def get_top_questions(self, limit=20, days=7):
        """获取高频问题列表

        Args:
            limit: 返回条数
            days: 统计最近N天

        Returns:
            [{question_text, count, mode, intent, question_category}, ...]
        """
        try:
            cutoff = int(time.time()) - days * 86400
            c = self.conn.cursor()
            c.execute(
                """SELECT question_text, COUNT(*) as cnt,
                          mode, intent, question_category
                   FROM user_questions WHERE ts>=?
                   GROUP BY question_text ORDER BY cnt DESC LIMIT ?""",
                (cutoff, limit),
            )
            return [
                {
                    "question_text": r[0],
                    "count": r[1],
                    "mode": r[2],
                    "intent": r[3],
                    "question_category": r[4],
                }
                for r in c.fetchall()
            ]
        except Exception as e:
            logger.error(f"获取高频问题失败：{e}")
            return []

    def get_category_distribution(self, days=7):
        """获取问题分类分布

        Args:
            days: 统计最近N天

        Returns:
            {分类: 数量}
        """
        try:
            cutoff = int(time.time()) - days * 86400
            c = self.conn.cursor()
            c.execute(
                """SELECT question_category, COUNT(*) FROM user_questions
                   WHERE ts>=? GROUP BY question_category ORDER BY COUNT(*) DESC""",
                (cutoff,),
            )
            return {r[0]: r[1] for r in c.fetchall()}
        except Exception as e:
            logger.error(f"获取分类分布失败：{e}")
            return {}

    def get_questions(self, limit=50, offset=0, category='', days=7):
        """获取问题列表

        Args:
            limit: 每页条数
            offset: 偏移量
            category: 按分类筛选（空=全部）
            days: 最近N天

        Returns:
            [{id, uid, chat_id, question_text, mode, intent, keyword_tag,
              question_category, is_convert, ai_reply_summary, faq_hit_id, ts}, ...]
        """
        try:
            cutoff = int(time.time()) - days * 86400
            c = self.conn.cursor()
            if category:
                c.execute(
                    """SELECT id, uid, chat_id, question_text, mode, intent,
                              keyword_tag, question_category, is_convert,
                              ai_reply_summary, faq_hit_id, ts
                       FROM user_questions
                       WHERE ts>=? AND question_category=?
                       ORDER BY ts DESC LIMIT ? OFFSET ?""",
                    (cutoff, category, limit, offset),
                )
            else:
                c.execute(
                    """SELECT id, uid, chat_id, question_text, mode, intent,
                              keyword_tag, question_category, is_convert,
                              ai_reply_summary, faq_hit_id, ts
                       FROM user_questions
                       WHERE ts>=?
                       ORDER BY ts DESC LIMIT ? OFFSET ?""",
                    (cutoff, limit, offset),
                )
            rows = c.fetchall()
            return [
                {
                    "id": r[0], "uid": r[1], "chat_id": r[2],
                    "question_text": r[3], "mode": r[4], "intent": r[5],
                    "keyword_tag": r[6], "question_category": r[7],
                    "is_convert": r[8], "ai_reply_summary": r[9],
                    "faq_hit_id": r[10], "ts": r[11],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"获取问题列表失败：{e}")
            return []

    # ─────────────────────────────── FAQ知识库 ────────────────────────────

    def search_faq(self, question_text, mode='', intent=''):
        """搜索FAQ知识库，返回匹配的FAQ条目列表

        匹配逻辑：
        1. match_mode='keyword': question_pattern中的词出现在question_text中
        2. match_mode='exact': question_pattern与question_text完全匹配
        3. 同时按question_category匹配（如果mode/intent能映射到分类）
        结果按priority DESC, hit_count DESC排序

        Args:
            question_text: 用户问题文本
            mode: 对话模式
            intent: 意图标签

        Returns:
            [{id, question_pattern, question_category, answer_template,
              ai_polish, match_mode, priority, hit_count}, ...]
        """
        try:
            c = self.conn.cursor()
            # 获取所有已审核的FAQ条目
            c.execute(
                """SELECT id, question_pattern, question_category, answer_template,
                          ai_polish, match_mode, priority, hit_count
                   FROM faq_knowledge WHERE status='approved'""",
            )
            all_faqs = c.fetchall()
            matched = []
            for row in all_faqs:
                faq_id, pattern, cat, answer, ai_polish, match_mode, priority, hit_count = row
                is_match = False
                # 关键词匹配：pattern中的词出现在question_text中
                if match_mode == 'keyword':
                    # 将pattern拆分为词，检查是否都在question_text中
                    keywords = pattern.strip().split()
                    if keywords and all(kw in question_text for kw in keywords):
                        is_match = True
                # 精确匹配
                elif match_mode == 'exact':
                    if pattern.strip() == question_text.strip():
                        is_match = True
                # 分类匹配：mode/intent映射到question_category
                # 只允许“未配置 pattern”的条目做纯分类兜底；有 pattern 的条目
                # 必须先通过 keyword/exact 命中，否则整类消息都会被同 category
                # 的固定答案抢答（结构性答非所问）。
                if not is_match and mode and cat == mode and not (pattern or "").strip():
                    is_match = True
                if not is_match and intent and cat == intent and not (pattern or "").strip():
                    is_match = True

                if is_match:
                    matched.append({
                        "id": faq_id,
                        "question_pattern": pattern,
                        "question_category": cat,
                        "answer_template": answer,
                        "ai_polish": ai_polish,
                        "match_mode": match_mode,
                        "priority": priority,
                        "hit_count": hit_count,
                    })
            # 按priority DESC, hit_count DESC排序
            matched.sort(key=lambda x: (-x["priority"], -x["hit_count"]))
            return matched
        except Exception as e:
            logger.error(f"搜索FAQ失败：{e}")
            return []

    def increment_faq_hit(self, faq_id) -> bool:
        """增加FAQ条目的命中计数

        Returns:
            True=成功，False=失败
        """
        with self.lock:
            try:
                self.conn.execute(
                    "UPDATE faq_knowledge SET hit_count=hit_count+1 WHERE id=?",
                    (int(faq_id),),
                )
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"增加FAQ命中计数失败：{e}")
                return False

    def get_faq_knowledge(self, limit=50, offset=0, category='', status='approved'):
        """获取FAQ知识库列表

        Args:
            limit: 每页条数
            offset: 偏移量
            category: 按分类筛选（空=全部）
            status: 按状态筛选

        Returns:
            [{id, question_pattern, question_category, answer_template,
              ai_polish, match_mode, priority, hit_count, status,
              created_by, created_at, updated_at}, ...]
        """
        try:
            c = self.conn.cursor()
            if category:
                c.execute(
                    """SELECT id, question_pattern, question_category, answer_template,
                              ai_polish, match_mode, priority, hit_count, status,
                              created_by, created_at, updated_at
                       FROM faq_knowledge
                       WHERE status=? AND question_category=?
                       ORDER BY priority DESC, hit_count DESC LIMIT ? OFFSET ?""",
                    (status, category, limit, offset),
                )
            else:
                c.execute(
                    """SELECT id, question_pattern, question_category, answer_template,
                              ai_polish, match_mode, priority, hit_count, status,
                              created_by, created_at, updated_at
                       FROM faq_knowledge
                       WHERE status=?
                       ORDER BY priority DESC, hit_count DESC LIMIT ? OFFSET ?""",
                    (status, limit, offset),
                )
            rows = c.fetchall()
            return [
                {
                    "id": r[0], "question_pattern": r[1],
                    "question_category": r[2], "answer_template": r[3],
                    "ai_polish": r[4], "match_mode": r[5],
                    "priority": r[6], "hit_count": r[7],
                    "status": r[8], "created_by": r[9],
                    "created_at": r[10], "updated_at": r[11],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"获取FAQ知识库失败：{e}")
            return []

    def add_faq_knowledge(self, question_pattern, question_category, answer_template,
                          ai_polish=1, match_mode='keyword', priority=0,
                          created_by='admin'):
        """新增FAQ知识库条目

        Returns:
            新插入行的id，失败返回0
        """
        with self.lock:
            try:
                now = int(time.time())
                cur = self.conn.cursor()
                cur.execute(
                    """INSERT INTO faq_knowledge
                       (question_pattern, question_category, answer_template,
                        ai_polish, match_mode, priority, hit_count, status,
                        created_by, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,0,'approved',?,?,?)""",
                    (str(question_pattern), str(question_category),
                     str(answer_template), int(ai_polish), str(match_mode),
                     int(priority), str(created_by), now, now),
                )
                self.conn.commit()
                return cur.lastrowid
            except Exception as e:
                logger.error(f"新增FAQ知识库失败：{e}")
                return 0

    def update_faq_knowledge(self, faq_id, **kwargs) -> bool:
        """更新FAQ知识库条目的指定字段

        支持更新的字段：answer_template, ai_polish, match_mode, priority,
                       status, question_pattern, question_category

        Returns:
            True=成功，False=失败（含无可更新字段的情况）
        """
        allowed = {'answer_template', 'ai_polish', 'match_mode', 'priority',
                   'status', 'question_pattern', 'question_category'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        with self.lock:
            try:
                updates['updated_at'] = int(time.time())
                set_clause = ', '.join(f"{k}=?" for k in updates)
                values = list(updates.values()) + [int(faq_id)]
                self.conn.execute(
                    f"UPDATE faq_knowledge SET {set_clause} WHERE id=?", values,
                )
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"更新FAQ知识库失败：{e}")
                return False

    def delete_faq_knowledge(self, faq_id) -> bool:
        """删除FAQ知识库条目

        Returns:
            True=成功，False=失败
        """
        with self.lock:
            try:
                self.conn.execute("DELETE FROM faq_knowledge WHERE id=?", (int(faq_id),))
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"删除FAQ知识库失败：{e}")
                return False

    # ─────────────────────────────── FAQ候选 ────────────────────────────

    def create_faq_candidate(self, question_pattern, question_category,
                             sample_questions, frequency, mode='', intent=''):
        """创建FAQ候选条目（待审核）

        Args:
            question_pattern: 问题模式
            question_category: 问题分类
            sample_questions: 样本问题（JSON字符串）
            frequency: 出现频次
            mode: 对话模式
            intent: 意图标签

        Returns:
            新插入行的id，失败返回0
        """
        with self.lock:
            try:
                cur = self.conn.cursor()
                cur.execute(
                    """INSERT INTO faq_candidates
                       (question_pattern, question_category, sample_questions,
                        frequency, mode, intent, status, reviewed_by,
                        reviewed_at, created_at)
                       VALUES (?,?,?,?,?,?,'pending','',0,?)""",
                    (str(question_pattern), str(question_category),
                     str(sample_questions), int(frequency),
                     str(mode), str(intent), int(time.time())),
                )
                self.conn.commit()
                return cur.lastrowid
            except Exception as e:
                logger.error(f"创建FAQ候选失败：{e}")
                return 0

    def get_pending_candidates(self):
        """获取待审核的FAQ候选列表

        Returns:
            [{id, question_pattern, question_category, sample_questions,
              frequency, mode, intent, status, created_at}, ...]
        """
        try:
            c = self.conn.cursor()
            c.execute(
                """SELECT id, question_pattern, question_category, sample_questions,
                          frequency, mode, intent, status, created_at
                   FROM faq_candidates WHERE status='pending'
                   ORDER BY frequency DESC, created_at DESC""",
            )
            rows = c.fetchall()
            return [
                {
                    "id": r[0], "question_pattern": r[1],
                    "question_category": r[2], "sample_questions": r[3],
                    "frequency": r[4], "mode": r[5], "intent": r[6],
                    "status": r[7], "created_at": r[8],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"获取待审核候选失败：{e}")
            return []

    def approve_candidate(self, candidate_id, answer_template='', ai_polish=1,
                          reviewed_by='admin'):
        """审核通过FAQ候选，将其转入FAQ知识库

        Args:
            candidate_id: 候选ID
            answer_template: 回答模板
            ai_polish: 是否AI润色
            reviewed_by: 审核人

        Returns:
            新FAQ知识库条目的id，失败返回0
        """
        with self.lock:
            try:
                # 读取候选信息
                c = self.conn.cursor()
                c.execute(
                    """SELECT question_pattern, question_category, mode, intent
                       FROM faq_candidates WHERE id=?""",
                    (int(candidate_id),),
                )
                row = c.fetchone()
                if not row:
                    logger.warning(f"FAQ候选不存在：id={candidate_id}")
                    return 0
                pattern, category, mode, intent = row
                # 更新候选状态
                now = int(time.time())
                self.conn.execute(
                    """UPDATE faq_candidates
                       SET status='approved', reviewed_by=?, reviewed_at=?
                       WHERE id=?""",
                    (str(reviewed_by), now, int(candidate_id)),
                )
                # 插入FAQ知识库
                cur = self.conn.cursor()
                cur.execute(
                    """INSERT INTO faq_knowledge
                       (question_pattern, question_category, answer_template,
                        ai_polish, match_mode, priority, hit_count, status,
                        created_by, created_at, updated_at)
                       VALUES (?,?,?,?,'keyword',0,0,'approved',?,?,?)""",
                    (pattern, category, str(answer_template),
                     int(ai_polish), str(reviewed_by), now, now),
                )
                self.conn.commit()
                return cur.lastrowid
            except Exception as e:
                logger.error(f"审核通过FAQ候选失败：{e}")
                return 0

    def reject_candidate(self, candidate_id, reviewed_by='admin'):
        """拒绝FAQ候选

        Args:
            candidate_id: 候选ID
            reviewed_by: 审核人
        """
        with self.lock:
            try:
                now = int(time.time())
                self.conn.execute(
                    """UPDATE faq_candidates
                       SET status='rejected', reviewed_by=?, reviewed_at=?
                       WHERE id=?""",
                    (str(reviewed_by), now, int(candidate_id)),
                )
                self.conn.commit()
            except Exception as e:
                logger.error(f"拒绝FAQ候选失败：{e}")

    # ─────────────────────────────── FAQ蒸馏 ────────────────────────────

    def distill_candidates(self, min_frequency=2, days=7):
        """从用户问题中蒸馏高频问题，生成FAQ候选

        扫描最近N天的user_questions，按分类+模式+意图分组，
        在每组内按归一化文本聚合相似问题，
        频次>=min_frequency的组创建FAQ候选（去重）。

        Args:
            min_frequency: 最低频次阈值
            days: 扫描最近N天

        Returns:
            新创建的候选数量
        """
        try:
            cutoff = int(time.time()) - days * 86400
            c = self.conn.cursor()
            c.execute(
                """SELECT question_text, question_category, mode, intent
                   FROM user_questions WHERE ts>=?""",
                (cutoff,),
            )
            rows = c.fetchall()
            if not rows:
                return 0

            # 按 (category, mode, intent) 分组，组内按归一化文本聚合
            groups = {}
            for question_text, category, mode, intent in rows:
                # 归一化：小写 + 去除标点
                normalized = re.sub(r'[^\w\s]', '', question_text.lower()).strip()
                key = (category, mode, intent)
                if key not in groups:
                    groups[key] = {}
                if normalized not in groups[key]:
                    groups[key][normalized] = {
                        "pattern": normalized,
                        "samples": [],
                        "count": 0,
                    }
                groups[key][normalized]["samples"].append(question_text)
                groups[key][normalized]["count"] += 1

            # 筛选频次>=min_frequency的，创建候选
            new_count = 0
            for (category, mode, intent), text_map in groups.items():
                for normalized, info in text_map.items():
                    if info["count"] < min_frequency:
                        continue
                    # 检查是否已存在相同pattern的候选
                    c.execute(
                        """SELECT id FROM faq_candidates
                           WHERE question_pattern=? AND question_category=?""",
                        (normalized, category),
                    )
                    if c.fetchone():
                        continue
                    # 保留最多5个样本问题
                    samples = info["samples"][:5]
                    import json
                    sample_str = json.dumps(samples, ensure_ascii=False)
                    cid = self.create_faq_candidate(
                        question_pattern=normalized,
                        question_category=category,
                        sample_questions=sample_str,
                        frequency=info["count"],
                        mode=mode,
                        intent=intent,
                    )
                    if cid > 0:
                        new_count += 1

            return new_count
        except Exception as e:
            logger.error(f"FAQ蒸馏失败：{e}")
            return 0
