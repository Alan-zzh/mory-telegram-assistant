# -*- coding: utf-8 -*-
"""
漏斗状态机 —— 4阶段转化追踪 + 乐观锁并发保护

状态流转:
  touched → interested → carted → converted
  (任何状态在长期不活跃后可重置为 touched)

并发保护:
  - 乐观锁: version 列，UPDATE 时 WHERE version=? 防并发覆盖
  - 全局互斥锁: 所有写操作持有 self._db.lock（与现有架构一致）
  - 状态降级不允许: 只能向前流转，不能倒退（除非显式 reset）

使用方式:
  from core.funnel_state_machine import FunnelStateMachine
  fsm = FunnelStateMachine(db)
  fsm.transition(uid, "interested")  # touched → interested
  state = fsm.get_state(uid)         # 查询当前状态
"""

import math
import os
import time
from core.logging_util import get_logger

logger = get_logger("funnel")

# ── 时间衰减归因参数（阶段3-E）──
# 衰减系数 lambda=0.1，半衰期 ≈ ln(2)/0.1 ≈ 6.93 小时
TIME_DECAY_LAMBDA = 0.1

# ── 合法状态枚举 ──
VALID_STATES = ("touched", "interested", "carted", "converted")

# ── 状态流转规则（只能向前，不能向后）──
# key=当前状态, value=允许转换到的状态集合
# 【TRAE SOLO CN v5.18.3审计修复】converted 允许转回 carted，支持复购场景
TRANSITION_MAP = {
    None:          {"touched"},                           # 新用户
    "touched":     {"interested", "carted", "converted"}, # 可以跳过中间状态
    "interested":  {"carted", "converted"},
    "carted":      {"converted"},
    "converted":   {"carted"},                             # 复购：允许重新进入购物车
}


def _get_default_bot_id() -> str:
    """获取默认 Bot ID（从环境变量读取，默认 mory）"""
    return os.environ.get("BOT_ID", "mory")


class FunnelStateMachine:
    """4阶段漏斗状态机，带乐观锁并发保护"""

    def __init__(self, db):
        """
        db: DB实例，通过 db.conn 和 db.lock 访问连接和锁
        """
        self._db = db
        self._default_bot_id = _get_default_bot_id()

    @property
    def conn(self):
        return self._db.conn

    @property
    def lock(self):
        return self._db.lock

    # ── 状态查询 ──

    def get_state(self, uid: int, bot_id: str = None) -> dict:
        """查询用户当前漏斗状态，返回 {state, state_ts, version, recovery_stage, recovery_ts}

        [v5.24.0] bot_id 参数支持多 Bot 隔离，默认用当前 Bot ID
        """
        if bot_id is None:
            bot_id = self._default_bot_id
        with self.lock:
            c = self.conn.cursor()
            c.execute(
                "SELECT state, state_ts, version, recovery_stage, recovery_ts "
                "FROM funnel_state WHERE uid=? AND bot_id=?",
                (uid, bot_id)
            )
            row = c.fetchone()
            if row is None:
                return {"state": None, "state_ts": 0, "version": 0,
                        "recovery_stage": 0, "recovery_ts": 0}
            return {
                "state": row[0],
                "state_ts": row[1],
                "version": row[2],
                "recovery_stage": row[3],
                "recovery_ts": row[4],
            }

    def is_state(self, uid: int, state: str, bot_id: str = None) -> bool:
        """检查用户是否处于指定状态"""
        return self.get_state(uid, bot_id)["state"] == state

    # ── 状态转换（带乐观锁）──

    def transition(self, uid: int, new_state: str, mode: str = "", bot_id: str = None,
                   is_memory_assisted: bool = False) -> bool:
        """
        将用户状态转换到 new_state。
        返回 True=成功, False=被拒绝（状态不允许或并发冲突）。

        [v5.24.0] bot_id 参数支持多 Bot 隔离
        [阶段3-A] is_memory_assisted 标记本次转化是否由记忆系统辅助（memory_summary 注入）

        并发保护:
          1. 全局互斥锁（self.lock）确保同一时刻只有一个线程写
          2. 乐观锁（version）确保基于最新状态做决策
          3. 状态降级自动拒绝
        """
        if new_state not in VALID_STATES:
            logger.error(f"非法状态 '{new_state}'，uid={uid}")
            return False

        if bot_id is None:
            bot_id = self._default_bot_id

        with self.lock:
            c = self.conn.cursor()

            # 1. 读取当前状态（带版本号）
            c.execute(
                "SELECT state, version FROM funnel_state WHERE uid=? AND bot_id=?",
                (uid, bot_id)
            )
            row = c.fetchone()

            if row is None:
                current_state = None
                current_version = 0
            else:
                current_state = row[0]
                current_version = row[1]

            # 2. 检查状态流转是否合法
            allowed = TRANSITION_MAP.get(current_state, set())
            if new_state not in allowed:
                logger.debug(
                    f"漏斗状态转换被拒绝: uid={uid} bot={bot_id} {current_state} → {new_state}"
                )
                return False

            # 3. 乐观锁写入（WHERE version = 当前版本）
            now_ts = int(time.time())
            new_version = current_version + 1

            if row is None:
                # 首次插入
                c.execute(
                    "INSERT INTO funnel_state (uid, state, state_ts, version, bot_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (uid, new_state, now_ts, new_version, bot_id)
                )
            else:
                # 乐观锁更新
                c.execute(
                    "UPDATE funnel_state SET state=?, state_ts=?, version=? "
                    "WHERE uid=? AND bot_id=? AND version=?",
                    (new_state, now_ts, new_version, uid, bot_id, current_version)
                )
                if c.rowcount == 0:
                    # 版本号不匹配 → 并发冲突
                    logger.warning(
                        f"漏斗乐观锁冲突: uid={uid} bot={bot_id} version={current_version}"
                    )
                    self.conn.commit()
                    return False

            self.conn.commit()

            # 4. 同步写入事件日志（兼容现有 conversion_events 表）
            # [阶段3-A] 传递 is_memory_assisted 标志，用于记忆归因分析
            self._log_event(uid, new_state, mode, is_memory_assisted=is_memory_assisted)

            logger.info(f"漏斗: uid={uid} bot={bot_id} {current_state} → {new_state}")
            return True

    def reset_state(self, uid: int, bot_id: str = None) -> bool:
        """
        强制重置用户状态为 touched（用于长期不活跃用户回归）。
        注意：这会清除挽回阶段数据。
        """
        if bot_id is None:
            bot_id = self._default_bot_id
        with self.lock:
            c = self.conn.cursor()
            now_ts = int(time.time())
            c.execute(
                "UPDATE funnel_state SET state='touched', state_ts=?, "
                "recovery_stage=0, recovery_ts=0, version=version+1 "
                "WHERE uid=? AND bot_id=?",
                (now_ts, uid, bot_id)
            )
            self.conn.commit()
            return c.rowcount > 0

    # ── 购物车挽回调度的状态管理 ──

    def set_recovery_stage(self, uid: int, stage: int, next_ts: int, bot_id: str = None) -> bool:
        """
        设置购物车挽回阶段。
        stage: 1=15分钟, 2=2小时, 3=24小时
        next_ts: 下次触发的时间戳
        返回 True=成功
        """
        if bot_id is None:
            bot_id = self._default_bot_id
        with self.lock:
            c = self.conn.cursor()
            c.execute(
                "UPDATE funnel_state SET recovery_stage=?, recovery_ts=?, "
                "version=version+1 WHERE uid=? AND bot_id=? AND state='carted'",
                (stage, next_ts, uid, bot_id)
            )
            self.conn.commit()
            return c.rowcount > 0

    def get_pending_recoveries(self, now_ts: int = None, bot_id: str = None) -> list:
        """
        获取所有到达触发时间的购物车挽回用户。
        返回 [(uid, recovery_stage), ...]
        """
        if bot_id is None:
            bot_id = self._default_bot_id
        if now_ts is None:
            now_ts = int(time.time())
        with self.lock:
            c = self.conn.cursor()
            c.execute(
                "SELECT uid, recovery_stage FROM funnel_state "
                "WHERE state='carted' AND recovery_stage < 3 "
                "AND recovery_ts > 0 AND recovery_ts <= ? AND bot_id=?",
                (now_ts, bot_id)
            )
            return [(row[0], row[1]) for row in c.fetchall()]

    def cancel_recovery(self, uid: int, bot_id: str = None) -> bool:
        """
        取消购物车挽回（用户已转化时调用）。
        将 recovery_stage 设为 99（已完成标记）。
        """
        if bot_id is None:
            bot_id = self._default_bot_id
        with self.lock:
            c = self.conn.cursor()
            c.execute(
                "UPDATE funnel_state SET recovery_stage=99, version=version+1 "
                "WHERE uid=? AND bot_id=?",
                (uid, bot_id)
            )
            self.conn.commit()
            return c.rowcount > 0

    # ── 统计查询 ──

    def get_funnel_counts(self) -> dict:
        """获取各阶段用户数（DISTINCT）"""
        with self.lock:
            c = self.conn.cursor()
            counts = {}
            for state in VALID_STATES:
                c.execute(
                    "SELECT COUNT(DISTINCT uid) FROM funnel_state WHERE state=?",
                    (state,)
                )
                counts[state] = c.fetchone()[0]
            return counts

    def get_stale_carts(self, hours: int = 24) -> list:
        """
        获取超过指定小时仍处于 carted 状态的用户。
        返回 [(uid, state_ts), ...]
        """
        cutoff = int(time.time()) - hours * 3600
        with self.lock:
            c = self.conn.cursor()
            c.execute(
                "SELECT uid, state_ts FROM funnel_state "
                "WHERE state='carted' AND state_ts < ?",
                (cutoff,)
            )
            return c.fetchall()

    # ── 内部方法 ──

    def _log_event(self, uid: int, event: str, mode: str = "", source: str = "", campaign_id: str = "",
                   is_memory_assisted: bool = False):
        """写入 conversion_events 日志表（兼容现有查询）

        [v5.23.0 P1-4] 增加 source 和 campaign_id 字段支持归因分析
        [阶段3-E] 增加 attribution_model 和 weight 字段支持时间衰减归因
        [阶段3-A] 增加 is_memory_assisted 字段支持记忆系统归因
        source: 触发来源（broadcast/private/group/manual）
        campaign_id: 追踪活动 ID（如 bc_20260617_2230）
        attribution_model: 归因模型（last_touch/time_decay），由归因分析回填
        weight: 主归因 campaign 的权重占比（0-1），由归因分析回填
        is_memory_assisted: 本次转化是否由记忆系统辅助（memory_summary 注入）
        """
        try:
            _mem_flag = 1 if is_memory_assisted else 0
            self.conn.execute(
                "INSERT INTO conversion_events(uid, event, ts, mode, source, campaign_id, is_memory_assisted) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uid, event, int(time.time()), mode, source, campaign_id, _mem_flag)
            )
        except Exception as e:
            logger.error(f"漏斗事件日志写入失败 uid={uid} event={event}: {e}")

    def attribute_conversion(self, uid: int, window_hours: int = 48, use_time_decay: bool = None) -> dict:
        """【v5.23.0 P1-4 / 阶段3-E】转化归因分析

        支持两种归因模型：
        - last_touch（默认）：末次触达，取转化前最后一次 interested/carted 事件
        - time_decay：时间衰减，按 exp(-lambda*hours_ago) 加权分配

        use_time_decay:
            None（默认）→ 读取 config.ATTRIBUTION_MODEL 决定（默认 last_touch）
            True → 强制使用 time_decay
            False → 强制使用 last_touch

        Returns:
            last_touch 模型:
                {uid, attributed_source, attributed_campaign_id,
                 attributed_event, attributed_ts, conversion_ts,
                 attribution_model: "last_touch"}
            time_decay 模型: 见 attribute_conversion_time_decay 返回结构
        """
        # 决定使用的归因模型（None 时读配置，向后兼容默认 last_touch）
        if use_time_decay is None:
            try:
                from core.bot_initializer import load_config
                model = load_config().get('ATTRIBUTION_MODEL', 'last_touch')
            except Exception:
                model = 'last_touch'
            use_time_decay = (model == 'time_decay')

        if use_time_decay:
            return self.attribute_conversion_time_decay(uid, window_hours=window_hours)

        # ── 末次触达归因（原逻辑保持不变）──
        try:
            with self.lock:
                c = self.conn.cursor()
                # 找到最近一次 converted 事件
                c.execute(
                    "SELECT ts FROM conversion_events WHERE uid=? AND event='converted' ORDER BY ts DESC LIMIT 1",
                    (uid,)
                )
                conv_row = c.fetchone()
                if not conv_row:
                    return {"uid": uid, "attribution_model": "last_touch",
                            "attributed_source": None, "attributed_campaign_id": None}
                conversion_ts = conv_row[0]

                # 回溯 window_hours 小时内的最后一次 interested/carted 事件
                window_start = conversion_ts - window_hours * 3600
                c.execute(
                    "SELECT event, ts, source, campaign_id FROM conversion_events "
                    "WHERE uid=? AND event IN ('interested', 'carted') "
                    "AND ts BETWEEN ? AND ? "
                    "ORDER BY ts DESC LIMIT 1",
                    (uid, window_start, conversion_ts)
                )
                attr_row = c.fetchone()
                if not attr_row:
                    return {"uid": uid, "attribution_model": "last_touch",
                            "attributed_source": None, "attributed_campaign_id": None,
                            "conversion_ts": conversion_ts}

                return {
                    "uid": uid,
                    "attribution_model": "last_touch",
                    "attributed_source": attr_row[2] or "unknown",
                    "attributed_campaign_id": attr_row[3] or "",
                    "attributed_event": attr_row[0],
                    "attributed_ts": attr_row[1],
                    "conversion_ts": conversion_ts,
                }
        except Exception as e:
            logger.error(f"归因分析失败 uid={uid}: {e}")
            return {"uid": uid, "attribution_model": "last_touch",
                    "attributed_source": None, "attributed_campaign_id": None}

    def attribute_conversion_time_decay(self, uid: int, window_hours: int = 48) -> dict:
        """【阶段3-E】时间衰减归因模型

        回溯用户在转化前 window_hours 小时内的所有 interested/carted 事件，
        按时间衰减权重 weight = exp(-lambda * hours_ago) 计算每个 campaign 的归因占比。
        lambda = 0.1（半衰期约 7 小时）。

        算法:
            1. 找到最近一次 converted 事件作为转化点
            2. 回溯 window_hours 内所有 interested/carted 事件
            3. 每个事件权重 = exp(-0.1 * 距转化的小时数)
            4. 按 campaign_id 分组累加权重
            5. 主归因 campaign = 权重最大的 campaign
            6. 各 campaign 权重占比 = 该 campaign 权重 / 总权重
            7. 回填 attribution_model='time_decay' 和 weight 到 converted 事件

        Returns:
            {
                "uid": uid,
                "attribution_model": "time_decay",
                "attributed_source": "broadcast"/"private"/...,
                "attributed_campaign_id": "bc_xxx",
                "attributed_event": "interested"/"carted",
                "attributed_ts": 1234567890,
                "conversion_ts": 1234567890,
                "campaign_weights": {campaign_id: weight_ratio, ...},  # 各 campaign 权重占比
                "total_weight": float,  # 总权重（归一化前）
            }
        """
        try:
            with self.lock:
                c = self.conn.cursor()
                # 找到最近一次 converted 事件
                c.execute(
                    "SELECT ts FROM conversion_events WHERE uid=? AND event='converted' ORDER BY ts DESC LIMIT 1",
                    (uid,)
                )
                conv_row = c.fetchone()
                if not conv_row:
                    return {"uid": uid, "attribution_model": "time_decay",
                            "attributed_source": None, "attributed_campaign_id": None,
                            "campaign_weights": {}, "total_weight": 0.0}
                conversion_ts = conv_row[0]

                # 回溯 window_hours 内的所有 interested/carted 事件（按时间升序）
                window_start = conversion_ts - window_hours * 3600
                c.execute(
                    "SELECT event, ts, source, campaign_id FROM conversion_events "
                    "WHERE uid=? AND event IN ('interested', 'carted') "
                    "AND ts BETWEEN ? AND ? "
                    "ORDER BY ts ASC",
                    (uid, window_start, conversion_ts)
                )
                rows = c.fetchall()
                if not rows:
                    return {"uid": uid, "attribution_model": "time_decay",
                            "attributed_source": None, "attributed_campaign_id": None,
                            "conversion_ts": conversion_ts,
                            "campaign_weights": {}, "total_weight": 0.0}

                # 按 campaign_id 分组累加时间衰减权重
                campaign_weights = {}  # {campaign_id: weight}
                campaign_meta = {}     # {campaign_id: (event, ts, source)} 各 campaign 最近一次触达
                total_weight = 0.0

                for event, ts, source, campaign_id in rows:
                    hours_ago = (conversion_ts - ts) / 3600.0
                    if hours_ago < 0:
                        hours_ago = 0
                    weight = math.exp(-TIME_DECAY_LAMBDA * hours_ago)
                    # campaign_id 为空时归入 "unknown" 桶
                    cid = campaign_id if campaign_id else "unknown"
                    campaign_weights[cid] = campaign_weights.get(cid, 0.0) + weight
                    total_weight += weight
                    # 记录每个 campaign 最近（ts 最大）的触达事件，用于主归因候选
                    if cid not in campaign_meta or ts > campaign_meta[cid][1]:
                        campaign_meta[cid] = (event, ts, source or "unknown")

                if total_weight <= 0:
                    return {"uid": uid, "attribution_model": "time_decay",
                            "attributed_source": None, "attributed_campaign_id": None,
                            "conversion_ts": conversion_ts,
                            "campaign_weights": {}, "total_weight": 0.0}

                # 主归因 campaign = 权重最大的 campaign
                primary_cid = max(campaign_weights, key=campaign_weights.get)
                primary_event, primary_ts, primary_source = campaign_meta[primary_cid]

                # 计算各 campaign 权重占比
                campaign_ratios = {cid: round(w / total_weight, 6)
                                   for cid, w in campaign_weights.items()}

                # 回填 attribution_model 和 weight 到最近一次 converted 事件
                primary_weight = campaign_ratios.get(primary_cid, 0.0)
                try:
                    self.conn.execute(
                        "UPDATE conversion_events SET attribution_model='time_decay', weight=? "
                        "WHERE uid=? AND event='converted' AND ts=?",
                        (primary_weight, uid, conversion_ts)
                    )
                    self.conn.commit()
                except Exception as e:
                    logger.debug(f"归因字段回填失败 uid={uid}: {e}")

                return {
                    "uid": uid,
                    "attribution_model": "time_decay",
                    "attributed_source": primary_source,
                    "attributed_campaign_id": primary_cid if primary_cid != "unknown" else "",
                    "attributed_event": primary_event,
                    "attributed_ts": primary_ts,
                    "conversion_ts": conversion_ts,
                    "campaign_weights": campaign_ratios,
                    "total_weight": round(total_weight, 6),
                }
        except Exception as e:
            logger.error(f"时间衰减归因分析失败 uid={uid}: {e}")
            return {"uid": uid, "attribution_model": "time_decay",
                    "attributed_source": None, "attributed_campaign_id": None,
                    "campaign_weights": {}, "total_weight": 0.0}

    def get_attribution_report(self, days: int = 7) -> list:
        """【v5.23.0 P1-4 / 阶段3-E】获取归因报表

        返回最近 days 天内所有转化用户的归因结果。
        每条记录新增 attribution_model 字段，标识使用的归因模型。
        time_decay 模型额外返回 campaign_weights（各 campaign 权重占比）。

        注意: 锁内只查询 uid 列表，归因分析在锁外逐个调用，
        避免 Lock 不可重入导致的死锁（原实现在锁内调用 attribute_conversion）。
        """
        try:
            # 锁内仅查询 uid 列表
            with self.lock:
                c = self.conn.cursor()
                cutoff = int(time.time()) - days * 86400
                c.execute(
                    "SELECT DISTINCT uid FROM conversion_events WHERE event='converted' AND ts > ?",
                    (cutoff,)
                )
                uids = [row[0] for row in c.fetchall()]

            # 锁外逐个调用归因分析（attribute_conversion 内部自带锁）
            report = []
            for uid in uids:
                attr = self.attribute_conversion(uid, window_hours=48)
                # 确保每条记录都有 attribution_model 字段（向后兼容旧记录）
                if "attribution_model" not in attr:
                    attr["attribution_model"] = "last_touch"
                report.append(attr)
            return report
        except Exception as e:
            logger.error(f"归因报表生成失败: {e}")
            return []

    def get_memory_attribution_report(self, days: int = 7) -> dict:
        """【阶段3-A】记忆系统转化归因报表

        对比 is_memory_assisted=1（记忆辅助）vs is_memory_assisted=0（无记忆）的会话：
          - carted 转化率（interested→carted）
          - converted 转化率（carted→converted）
          - 提升比率 = memory_assisted 转化率 / non_assisted 转化率

        算法:
            1. 按 is_memory_assisted 分组统计各阶段事件数
            2. carted_rate = carted 事件数 / interested 事件数
            3. converted_rate = converted 事件数 / carted 事件数
            4. lift_ratio = memory_assisted_rate / non_assisted_rate（分母为 0 时返回 0）

        Returns:
            {
                "memory_assisted": {"carted_rate": float, "converted_rate": float, "count": int},
                "non_assisted":    {"carted_rate": float, "converted_rate": float, "count": int},
                "lift_ratio":      {"carted": float, "converted": float},
                "days": int
            }
        """
        empty = {
            "memory_assisted": {"carted_rate": 0.0, "converted_rate": 0.0, "count": 0},
            "non_assisted":    {"carted_rate": 0.0, "converted_rate": 0.0, "count": 0},
            "lift_ratio":      {"carted": 0.0, "converted": 0.0},
            "days": days,
        }
        try:
            with self.lock:
                c = self.conn.cursor()
                cutoff = int(time.time()) - days * 86400
                # 按 is_memory_assisted 分组统计各阶段事件数
                # COALESCE 兼容旧记录（无该列时默认 0）
                c.execute(
                    "SELECT COALESCE(is_memory_assisted, 0) AS mem_flag, "
                    "SUM(CASE WHEN event='interested' THEN 1 ELSE 0 END) AS interested_n, "
                    "SUM(CASE WHEN event='carted'    THEN 1 ELSE 0 END) AS carted_n, "
                    "SUM(CASE WHEN event='converted' THEN 1 ELSE 0 END) AS converted_n, "
                    "COUNT(*) AS total_n "
                    "FROM conversion_events WHERE ts > ? AND event IN ('interested','carted','converted') "
                    "GROUP BY mem_flag",
                    (cutoff,)
                )
                rows = c.fetchall()

            # 解析两组数据
            stats = {0: {"interested": 0, "carted": 0, "converted": 0, "total": 0},
                     1: {"interested": 0, "carted": 0, "converted": 0, "total": 0}}
            for mem_flag, interested_n, carted_n, converted_n, total_n in rows:
                flag = int(mem_flag)
                if flag in stats:
                    stats[flag]["interested"] = interested_n or 0
                    stats[flag]["carted"] = carted_n or 0
                    stats[flag]["converted"] = converted_n or 0
                    stats[flag]["total"] = total_n or 0

            # 计算转化率（百分比）
            def _rate(num, den):
                return round(num / den * 100, 2) if den > 0 else 0.0

            ma = stats[1]   # memory_assisted
            na = stats[0]   # non_assisted

            ma_carted_rate = _rate(ma["carted"], ma["interested"])
            ma_converted_rate = _rate(ma["converted"], ma["carted"])
            na_carted_rate = _rate(na["carted"], na["interested"])
            na_converted_rate = _rate(na["converted"], na["carted"])

            # 提升比率 = memory_assisted_rate / non_assisted_rate
            def _lift(numerator, denominator):
                return round(numerator / denominator, 2) if denominator > 0 else 0.0

            lift_carted = _lift(ma_carted_rate, na_carted_rate)
            lift_converted = _lift(ma_converted_rate, na_converted_rate)

            return {
                "memory_assisted": {
                    "carted_rate": ma_carted_rate,
                    "converted_rate": ma_converted_rate,
                    "count": ma["total"],
                    "interested": ma["interested"],
                    "carted": ma["carted"],
                    "converted": ma["converted"],
                },
                "non_assisted": {
                    "carted_rate": na_carted_rate,
                    "converted_rate": na_converted_rate,
                    "count": na["total"],
                    "interested": na["interested"],
                    "carted": na["carted"],
                    "converted": na["converted"],
                },
                "lift_ratio": {
                    "carted": lift_carted,
                    "converted": lift_converted,
                },
                "days": days,
            }
        except Exception as e:
            logger.error(f"记忆归因报表生成失败: {e}")
            return empty
