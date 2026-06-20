# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/ab_testing.py  ·  A/B 测试引擎（v1.0）                            ║
║                                                                        ║
║  功能：                                                                ║
║    1. 稳定哈希分流 —— 按 user_id / chat_id 哈希，保证同一实体始终同组    ║
║    2. 实验生命周期管理 —— 创建 / 运行 / 暂停 / 回滚                     ║
║    3. Prompt 注入 —— 根据 variant 动态修改 system prompt               ║
║    4. 穿帮防护 —— 群播报按 chat 分流，私聊/群回复按 user 分流           ║
║                                                                        ║
║  被调用：core/ai_engine.py, modules/scheduled_broadcast.py              ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import hashlib
import time
from typing import Optional

from core.logging_util import get_logger

logger = get_logger("ab_testing")


class ABTestEngine:
    """A/B 测试引擎：分流 + Prompt 注入 + 实验管理"""

    def __init__(self, db, config: dict):
        self.db = db
        self.config = config
        self._ab_cfg = config.get("AB_TEST_CONFIG", {})
        self._enabled = bool(self._ab_cfg.get("enabled", False))

    def _hash_entity(self, entity_id: int, experiment_id: str, salt: str = "mory_ab_v1") -> int:
        """稳定哈希，保证同一实体在同一实验下始终得到相同分组"""
        raw = f"{salt}:{experiment_id}:{entity_id}"
        return int(hashlib.md5(raw.encode("utf-8")).hexdigest(), 16)

    def _determine_variant(self, experiment_id: str, entity_id: int, traffic_split: int = 50) -> str:
        """根据实体 ID 和流量比例决定 variant"""
        h = self._hash_entity(entity_id, experiment_id)
        bucket = h % 100
        return "B" if bucket < traffic_split else "A"

    def get_variant(self, experiment_id: str, user_id: int = 0, chat_id: int = 0) -> Optional[str]:
        """
        获取用户/群在指定实验下的 variant。
        若实验未启用或不存在，返回 None。
        """
        if not self._enabled:
            return None

        exp = self._get_experiment_config(experiment_id)
        if not exp or not exp.get("enabled", False):
            return None

        # 已回滚或停止的实验不再分配新用户，但保留老用户分组
        db_exp = None
        if self.db and hasattr(self.db, "get_experiment"):
            try:
                db_exp = self.db.get_experiment(experiment_id)
            except Exception as e:
                logger.debug(f"获取实验配置失败: {e}")

        scope = exp.get("scope", "private")
        traffic_split = exp.get("traffic_split", 50)

        # 穿帮防护：群播报按 chat 分流；私聊/群回复按 user 分流
        if scope == "broadcast" and chat_id != 0:
            entity_id = chat_id
        else:
            entity_id = user_id if user_id != 0 else chat_id

        if entity_id == 0:
            return None

        # 查持久化分配
        if self.db and hasattr(self.db, "get_user_variant"):
            try:
                assigned = self.db.get_user_variant(experiment_id, entity_id)
                if assigned:
                    # 实验已回滚：老用户继续看到原版本，但标记为 rolled_back
                    if db_exp and db_exp.get("status") == "rolled_back":
                        return assigned
                    return assigned
            except Exception as e:
                logger.debug(f"查询用户分组失败: {e}")

        # 新分配
        variant = self._determine_variant(experiment_id, entity_id, traffic_split)

        # 实验已回滚：新用户全部分到 A（对照组）
        if db_exp and db_exp.get("status") == "rolled_back":
            variant = "A"

        # 持久化
        if self.db and hasattr(self.db, "assign_user_variant"):
            try:
                self.db.assign_user_variant(experiment_id, entity_id, chat_id, variant)
            except Exception as e:
                logger.debug(f"持久化分组失败: {e}")

        return variant

    def get_prompt_injection(self, experiment_id: str, variant: str) -> str:
        """获取指定实验 variant 的 system prompt 注入片段"""
        exp = self._get_experiment_config(experiment_id)
        if not exp:
            return ""
        key = "variant_a" if variant == "A" else "variant_b"
        cfg = exp.get(key, {})
        return cfg.get("system_prompt_append", "")

    def inject_prompt(self, experiment_id: str, base_prompt: str, user_id: int = 0, chat_id: int = 0) -> str:
        """
        高阶接口：根据实验和实体自动分流并注入 prompt。
        返回修改后的 system prompt。
        """
        variant = self.get_variant(experiment_id, user_id, chat_id)
        if not variant:
            return base_prompt
        injection = self.get_prompt_injection(experiment_id, variant)
        if not injection:
            return base_prompt
        return f"{base_prompt}\n\n【A/B实验注入：{experiment_id} / 组{variant}】\n{injection}"

    def log_exposure(self, experiment_id: str, user_id: int, chat_id: int = 0):
        """记录曝光事件"""
        variant = self.get_variant(experiment_id, user_id, chat_id)
        if variant and self.db and hasattr(self.db, "log_telemetry"):
            try:
                self.db.log_telemetry(user_id, chat_id, experiment_id, variant, "exposure")
            except Exception as e:
                logger.debug(f"曝光埋点失败: {e}")

    def _get_experiment_config(self, experiment_id: str) -> Optional[dict]:
        """从 config.json 获取实验配置"""
        experiments = self._ab_cfg.get("experiments", [])
        for exp in experiments:
            if exp.get("id") == experiment_id:
                return exp
        return None

    def list_running_experiments(self) -> list:
        """列出当前配置中启用的实验"""
        if not self._enabled:
            return []
        return [exp for exp in self._ab_cfg.get("experiments", []) if exp.get("enabled", False)]

    def sync_experiments_to_db(self):
        """将 config.json 中的实验定义同步到数据库（幂等）"""
        if not self.db or not hasattr(self.db, "create_experiment"):
            return
        for exp in self._ab_cfg.get("experiments", []):
            eid = exp.get("id")
            if not eid:
                continue
            try:
                self.db.create_experiment(
                    experiment_id=eid,
                    name=exp.get("name", eid),
                    description=exp.get("description", ""),
                    variant_a=exp.get("variant_a", {"label": "A"}),
                    variant_b=exp.get("variant_b", {"label": "B"}),
                    traffic_split=exp.get("traffic_split", 50),
                    scope=exp.get("scope", "private"),
                )
            except Exception as e:
                logger.debug(f"同步实验到数据库失败: {e}")


class ABTestGuardian:
    """A/B 测试守护：阈值检查与自动回滚"""

    def __init__(self, db, config: dict):
        self.db = db
        self.config = config
        self._ab_cfg = config.get("AB_TEST_CONFIG", {})
        self._enabled = bool(self._ab_cfg.get("enabled", False))

    def check_all(self) -> list:
        """检查所有运行中实验的指标，返回触发的告警列表"""
        alerts = []
        if not self._enabled or not self.db:
            return alerts

        engine = ABTestEngine(self.db, self.config)
        for exp in engine.list_running_experiments():
            eid = exp.get("id")
            guardian_cfg = exp.get("guardian", {})
            try:
                alerts.extend(self._check_experiment(eid, guardian_cfg))
            except Exception as e:
                logger.warning(f"守护检查异常 {eid}: {e}")
        return alerts

    def _check_experiment(self, experiment_id: str, guardian_cfg: dict) -> list:
        """对单个实验进行阈值检查"""
        alerts = []
        if not hasattr(self.db, "get_conversion_funnel"):
            return alerts

        # 取最近 24h 数据做实时检查
        end_ts = int(time.time())
        start_ts = end_ts - 86400
        funnel = self.db.get_conversion_funnel(experiment_id, start_ts, end_ts)

        a = funnel.get("A", {})
        b = funnel.get("B", {})

        # 1. 退群率阈值
        max_leave_delta = guardian_cfg.get("max_group_leave_rate_delta", 0.05)
        a_leave_rate = a.get("churn_rate", 0)
        b_leave_rate = b.get("churn_rate", 0)
        if a_leave_rate > 0 and b_leave_rate > a_leave_rate * (1 + max_leave_delta / max(a_leave_rate, 0.001)):
            alerts.append({
                "experiment_id": experiment_id,
                "alert_type": "churn_rate",
                "alert_reason": f"B组退群率({b_leave_rate:.2f}%)显著高于A组({a_leave_rate:.2f}%)",
                "threshold_value": max_leave_delta,
                "actual_value": b_leave_rate - a_leave_rate,
                "bad_variant": "B",
            })
        elif b_leave_rate > 0 and a_leave_rate > b_leave_rate * (1 + max_leave_delta / max(b_leave_rate, 0.001)):
            alerts.append({
                "experiment_id": experiment_id,
                "alert_type": "churn_rate",
                "alert_reason": f"A组退群率({a_leave_rate:.2f}%)显著高于B组({b_leave_rate:.2f}%)",
                "threshold_value": max_leave_delta,
                "actual_value": a_leave_rate - b_leave_rate,
                "bad_variant": "A",
            })

        # 2. 投诉率阈值
        max_complaint_rate = guardian_cfg.get("max_complaint_rate", 0.03)
        for variant, data in ("A", a), ("B", b):
            exposed = data.get("exposed", 0)
            # 投诉数需要从 telemetry 单独查，这里用 funnel 里没包含，先简化：
            # 实际实现时 guardian 会调用更细粒度的 SQL
            # 为保持接口简洁，此处预留逻辑，由外部任务补充查询
            pass

        # 3. 转化率下降阈值
        min_conversion_ratio = guardian_cfg.get("min_conversion_rate_ratio", 0.5)
        a_conv = a.get("conversion_rate", 0)
        b_conv = b.get("conversion_rate", 0)
        if a_conv > 0 and b_conv < a_conv * min_conversion_ratio:
            alerts.append({
                "experiment_id": experiment_id,
                "alert_type": "conversion_drop",
                "alert_reason": f"B组转化率({b_conv:.2f}%)低于A组({a_conv:.2f}%)的{min_conversion_ratio*100:.0f}%",
                "threshold_value": min_conversion_ratio,
                "actual_value": b_conv / max(a_conv, 0.0001),
                "bad_variant": "B",
            })
        elif b_conv > 0 and a_conv < b_conv * min_conversion_ratio:
            alerts.append({
                "experiment_id": experiment_id,
                "alert_type": "conversion_drop",
                "alert_reason": f"A组转化率({a_conv:.2f}%)低于B组({b_conv:.2f}%)的{min_conversion_ratio*100:.0f}%",
                "threshold_value": min_conversion_ratio,
                "actual_value": a_conv / max(b_conv, 0.0001),
                "bad_variant": "A",
            })

        return alerts

    def rollback(self, experiment_id: str, reason: str = "") -> bool:
        """自动回滚实验：将实验状态设为 rolled_back，并记录日志"""
        if not self.db or not hasattr(self.db, "update_experiment_status"):
            return False
        try:
            ok = self.db.update_experiment_status(experiment_id, "rolled_back")
            if ok:
                self.db.log_guardian_alert(
                    experiment_id, "auto_rollback",
                    reason or "触发守护阈值，自动回滚", 0.0, 0.0, "rolled_back"
                )
                logger.warning(f"[AB Guardian] 实验 {experiment_id} 已自动回滚: {reason}")
            return ok
        except Exception as e:
            logger.warning(f"回滚实验失败: {e}")
            return False
