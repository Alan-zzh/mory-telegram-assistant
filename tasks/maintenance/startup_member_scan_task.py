"""启动时对数据库已知群成员执行当前广告规则扫描。"""

from builtins import ExceptionGroup
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.startup_member_scan")

_CST = timezone(timedelta(hours=8))


class StartupMemberScanTask(BaseTask):
    """可选的启动成员扫描；默认关闭，避免重启时意外触发批量治理。"""

    @property
    def task_id(self) -> str:
        return "startup_member_scan"

    def schedule(self) -> List[Dict[str, Any]]:
        return []

    def execute(self, ctx: TaskContext) -> None:
        config = self.rm.config
        if not config.get("STARTUP_MEMBER_SCAN_ENABLED", False):
            logger.info("[启动扫描] STARTUP_MEMBER_SCAN_ENABLED=false，跳过")
            return

        hour_key = datetime.now(_CST).strftime("%Y-%m-%d_%H")
        with TaskTransactionManager(
            f"startup_member_scan_{hour_key}",
            self.rm.db,
            resources=None,
            min_interval_sec=3600,
        ) as tx:
            if not tx.claimed:
                return

            group_ids: list[int] = []
            gid = config.get("GROUP_ID", 0)
            if gid:
                group_ids = [int(gid)]
            else:
                managed = config.get("MANAGED_GROUPS", [])
                if isinstance(managed, int):
                    group_ids = [managed]
                elif isinstance(managed, list):
                    group_ids = [int(item) for item in managed if item]

            if not group_ids:
                logger.info("[启动扫描] 未找到管理群组，跳过")
                return

            from modules.member_ad_scan import scan_known_group_members

            enforce = bool(config.get("STARTUP_MEMBER_SCAN_ENFORCE", False))
            totals = {
                "discovered": 0,
                "checked": 0,
                "high_confidence": 0,
                "enforced": 0,
                "weak_only": 0,
            }
            failures: list[Exception] = []

            for chat_id in group_ids:
                try:
                    result = scan_known_group_members(
                        bot=self.rm.bot,
                        db=self.rm.db,
                        config=config,
                        chat_id=chat_id,
                        enforce=enforce,
                    )
                    counts = result.get("counts", {})
                    for key in totals:
                        totals[key] += int(counts.get(key, 0) or 0)
                    logger.info(
                        "[启动扫描] 群%s discovered=%s checked=%s candidates=%s enforced=%s mode=%s",
                        chat_id,
                        counts.get("discovered", 0),
                        counts.get("checked", 0),
                        counts.get("high_confidence", 0),
                        counts.get("enforced", 0),
                        result.get("mode"),
                    )
                except ExceptionGroup as exc:
                    logger.error("[启动扫描] 群%s扫描失败: %s", chat_id, exc)
                    failures.extend(exc.exceptions)
                except Exception as exc:
                    logger.error("[启动扫描] 群%s扫描失败: %s", chat_id, exc)
                    failures.append(exc)

            admin_id = int(config.get("ADMIN_ID", 0) or 0)
            if admin_id and (totals["checked"] > 0 or totals["high_confidence"] > 0):
                try:
                    self.rm.bot.send_message(
                        admin_id,
                        "🔍 启动成员扫描完成\n"
                        f"📊 群组：{len(group_ids)}\n"
                        f"👥 已知：{totals['discovered']}\n"
                        f"✅ 实查：{totals['checked']}\n"
                        f"⚠️ 高置信：{totals['high_confidence']}\n"
                        f"🚫 已处置：{totals['enforced']}\n"
                        f"模式：{'处置' if enforce else '仅报告'}",
                    )
                except Exception as exc:
                    logger.error("[启动扫描] 管理员摘要发送失败: %s", exc)
                    failures.append(exc)

            if totals["discovered"] > 0 and totals["checked"] == 0:
                failures.append(RuntimeError("startup_member_scan_zero_coverage"))
            if failures:
                raise ExceptionGroup("启动成员扫描失败或降级", failures)
