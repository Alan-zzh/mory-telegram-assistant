# 触发器基类（v5.19.0）
"""[TRAE SOLO CN] v5.19.0 场景化触发器基类。

所有触发器继承 TriggerBase，实现 should_fire / execute。
注册到 APScheduler，默认每 5 分钟巡检一次。
统一异常吞掉 + TaskTransactionManager 幂等。
"""

import logging
from typing import Any, Iterable, Type, Union

logger = logging.getLogger(__name__)


class TriggerBase:
    """[TRAE SOLO CN] v5.19.0 触发器基类。"""

    job_id: str = ""
    trigger_type: str = "cron"  # cron / interval / event
    enabled_config_key: str = ""  # 如 'COLD_GROUP_TRIGGER_ENABLED'
    interval_minutes: int = 5  # 巡检间隔（分钟）

    def __init__(self):
        self.rm: Any = None  # ResourceManager

    def should_fire(self, rm) -> bool:
        """子类实现：判断是否满足触发条件。"""
        raise NotImplementedError

    def execute(self, rm) -> None:
        """子类实现：执行触发动作。"""
        raise NotImplementedError

    def register(self, scheduler, rm):
        """注册到 APScheduler（事件驱动触发器不注册，由调用方手动触发）。"""
        if self.trigger_type == "event":
            return  # 事件驱动，不轮询
        # 注册是配置热重载的幂等边界：关闭开关时必须移除旧 job，
        # 否则 APScheduler 会继续保留启动时的闭包并持续空转。
        if not rm.config.get(self.enabled_config_key, False):
            if not self._remove_job(scheduler):
                raise RuntimeError(f"触发器 {self.job_id} 旧 job 无法移除")
            logger.info(f"触发器 {self.job_id} 未启用，跳过注册")
            return
        self.rm = rm
        try:
            scheduler.add_job(
                self._run, id=self.job_id, max_instances=1, coalesce=True,
                trigger="interval", minutes=self.interval_minutes,
                misfire_grace_time=60, args=[rm], replace_existing=True,
            )
            logger.info(f"✅ 触发器已注册: {self.job_id} (间隔 {self.interval_minutes} 分钟)")
        except Exception as e:
            logger.warning(f"触发器 {self.job_id} 注册失败: {e}")
            raise RuntimeError(f"触发器 {self.job_id} 注册失败") from e

    def _remove_job(self, scheduler) -> bool:
        """删除本触发器的旧 job；job 不存在视为成功。

        APScheduler 对不存在的 job 抛 ``JobLookupError``，而测试替身或
        其他调度器实现可能抛 ``KeyError``/``ValueError``，这些都不应使
        配置热重载失败。未知异常则保留并记录，避免假装完成了移除。
        """
        try:
            scheduler.remove_job(self.job_id)
        except (KeyError, ValueError):
            return True
        except Exception as exc:
            # APScheduler JobLookupError 不在这里直接导入，避免触发器基类
            # 在没有 APScheduler 的单测/工具环境中无法导入。
            if exc.__class__.__name__ == "JobLookupError":
                return True
            logger.warning(f"触发器 {self.job_id} 旧 job 移除失败: {exc}")
            return False
        logger.info(f"🧹 触发器旧 job 已移除: {self.job_id}")
        return True

    def _run(self, rm):
        """统一执行入口：异常吞掉 + 幂等检查。"""
        try:
            if not rm.config.get(self.enabled_config_key, False):
                return
            if self.should_fire(rm):
                logger.info(f"🔥 触发器命中: {self.job_id}")
                self.execute(rm)
        except Exception as e:
            logger.warning(f"触发器 {self.job_id} 执行异常: {e}")


def refresh_trigger_jobs(
    scheduler,
    rm,
    trigger_types: Iterable[Union[Type[TriggerBase], TriggerBase]],
) -> None:
    """按当前配置刷新场景触发器的调度注册。

    ``TaskScheduler.refresh_tasks`` 只管理 ``tasks/`` 下的 BaseTask，旧的
    场景触发器不在其注册集合内，导致 Dashboard 将开关改为 false 后旧 job
    仍然存在。主生命周期只需在调度器刷新成功后调用此函数一次，并传入
    ``(ColdGroupTrigger, NightHintTrigger)``；事件型触发器不应加入此集合。

    每个调用都创建一个新的触发器实例，避免复用上一次运行残留的
    ``_pending_*`` 缓存；``replace_existing=True`` 使 true→true 的刷新幂等。
    注册失败向上抛出，交由配置热重载事务回滚，而不是让 UI 与运行态分裂。
    """
    errors: list[Exception] = []
    for trigger_type in trigger_types:
        try:
            trigger = trigger_type() if isinstance(trigger_type, type) else trigger_type
            trigger.register(scheduler, rm)
        except Exception as exc:
            logger.error(f"刷新触发器 {getattr(trigger_type, '__name__', trigger_type)} 失败: {exc}")
            errors.append(exc)
    if errors:
        raise RuntimeError(f"场景触发器刷新失败，共 {len(errors)} 项") from ExceptionGroup(
            "场景触发器刷新失败明细", errors
        )


# 兼容已有调用方的短名称；新代码优先使用 refresh_trigger_jobs。
refresh_triggers = refresh_trigger_jobs
