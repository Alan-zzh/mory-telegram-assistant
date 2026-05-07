# 项目：universal_ai_router | 版本：v1.0.0 | 日期：2026-04-23 | 功能：账号管理器
"""
账号管理器 - 负责多账号轮询、故障转移、配额追踪
"""

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

# 日志记录器
try:
    from ..logging_util import get_logger
    logger = get_logger("account_manager")
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("account_manager")


class AccountStatus(Enum):
    """账号状态枚举"""
    ACTIVE = "active"
    QUOTA_EXHAUSTED = "quota_exhausted"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class AccountInfo:
    """账号信息数据类"""
    api_key: str
    name: str
    enabled: bool = True
    status: str = "active"  # active / quota_exhausted / error
    last_used: Optional[float] = None  # 时间戳
    use_count: int = 0
    error_count: int = 0
    success_count: int = 0
    total_tokens: int = 0
    quota_limit: Optional[int] = None  # 配额上限
    weight: int = 1  # 加权轮询权重
    cooldown_until: Optional[float] = None  # 临时冷却到期时间

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccountInfo":
        """从字典创建"""
        return cls(**data)


class AccountManager:
    """账号管理器类"""

    def __init__(self, config_manager=None, state_file: Optional[str] = None):
        """
        初始化账号管理器
        :param config_manager: 配置管理器实例
        :param state_file: 账号状态持久化文件路径
        """
        self.config_manager = config_manager
        self._lock = threading.RLock()  # 可重入锁，保护账号状态

        # 账号状态存储: {provider: {account_index: AccountInfo}}
        self._accounts: Dict[str, Dict[int, AccountInfo]] = {}

        # 轮询指针: {provider: current_index}
        self._round_robin_index: Dict[str, int] = {}

        # 状态持久化文件
        if state_file is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            state_file = os.path.join(base_dir, "data", "account_states.json")
        self.state_file = state_file

        # 故障阈值
        self._error_threshold = 3  # 连续错误次数阈值
        self._quota_exhausted_threshold = 5  # 配额耗尽重试次数

        # 告警回调
        self._alert_callback: Optional[callable] = None

        # 初始化加载
        self._initialize_accounts()
        self._load_state()

    def _initialize_accounts(self) -> None:
        """从配置管理器加载账号信息"""
        if self.config_manager is None:
            return

        try:
            providers = self.config_manager.get_all_providers()
            for provider in providers:
                provider_config = self.config_manager.get_provider_config(provider)
                if not provider_config:
                    continue

                self._accounts[provider] = {}
                accounts_config = provider_config.get("accounts", [])

                for idx, acc_config in enumerate(accounts_config):
                    account = AccountInfo(
                        api_key=acc_config.get("api_key", ""),
                        name=acc_config.get("name", f"{provider}_account_{idx}"),
                        enabled=acc_config.get("enabled", True),
                        quota_limit=acc_config.get("quota_limit"),
                        weight=acc_config.get("weight", 1),
                        status="active" if acc_config.get("enabled", True) else "disabled"
                    )
                    self._accounts[provider][idx] = account

                # 初始化轮询指针
                self._round_robin_index[provider] = 0

            logger.info(f"账号管理器初始化完成，加载了 {len(providers)} 个提供者")
        except Exception as e:
            logger.error(f"初始化账号管理器失败: {e}")

    def _load_state(self) -> None:
        """从文件加载账号状态"""
        if not os.path.exists(self.state_file):
            return

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)

            for provider, accounts_state in state_data.get("accounts", {}).items():
                if provider not in self._accounts:
                    continue
                for idx, acc_state in accounts_state.items():
                    idx = int(idx)
                    if idx in self._accounts[provider]:
                        acc = self._accounts[provider][idx]
                        acc.status = acc_state.get("status", acc.status)
                        acc.use_count = acc_state.get("use_count", acc.use_count)
                        acc.error_count = acc_state.get("error_count", acc.error_count)
                        acc.success_count = acc_state.get("success_count", acc.success_count)
                        acc.total_tokens = acc_state.get("total_tokens", acc.total_tokens)
                        acc.last_used = acc_state.get("last_used", acc.last_used)
                        acc.cooldown_until = acc_state.get("cooldown_until", acc.cooldown_until)

            self._round_robin_index = state_data.get("round_robin_index", self._round_robin_index)
            logger.info("账号状态加载完成")
        except Exception as e:
            logger.error(f"加载账号状态失败: {e}")

    def _save_state(self) -> None:
        """保存账号状态到文件"""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)

            accounts_data = {}
            for provider, accounts in self._accounts.items():
                accounts_data[provider] = {}
                for idx, acc in accounts.items():
                    accounts_data[provider][str(idx)] = {
                        "status": acc.status,
                        "use_count": acc.use_count,
                        "error_count": acc.error_count,
                        "success_count": acc.success_count,
                        "total_tokens": acc.total_tokens,
                        "last_used": acc.last_used,
                        "cooldown_until": acc.cooldown_until
                    }

            state_data = {
                "accounts": accounts_data,
                "round_robin_index": self._round_robin_index,
                "last_saved": datetime.now().isoformat()
            }

            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存账号状态失败: {e}")

    def set_alert_callback(self, callback: callable) -> None:
        """设置告警回调函数"""
        self._alert_callback = callback

    def _trigger_alert(self, message: str, level: str = "warning") -> None:
        """触发告警"""
        logger.warning(f"账号告警 [{level}]: {message}")
        if self._alert_callback:
            try:
                self._alert_callback(message, level)
            except Exception as e:
                logger.error(f"告警回调执行失败: {e}")

    # ==================== 账号获取策略 ====================

    def round_robin(self, provider: str) -> Optional[Tuple[int, AccountInfo]]:
        """
        简单轮询策略
        :param provider: 提供者名称
        :return: (账号索引, 账号信息) 或 None
        """
        with self._lock:
            if provider not in self._accounts:
                return None

            accounts = self._accounts[provider]
            total = len(accounts)
            if total == 0:
                return None

            # 尝试找到下一个可用账号
            start_idx = self._round_robin_index.get(provider, 0)
            idx = start_idx

            for _ in range(total):
                if self.is_account_available(provider, idx):
                    self._round_robin_index[provider] = (idx + 1) % total
                    return idx, accounts[idx]
                idx = (idx + 1) % total

            # 所有账号都不可用
            return None

    def weighted_round_robin(self, provider: str) -> Optional[Tuple[int, AccountInfo]]:
        """
        加权轮询策略
        :param provider: 提供者名称
        :return: (账号索引, 账号信息) 或 None
        """
        with self._lock:
            if provider not in self._accounts:
                return None

            accounts = self._accounts[provider]
            if not accounts:
                return None

            # 按权重计算有效账号列表
            weighted_list: List[Tuple[int, AccountInfo]] = []
            for idx, acc in accounts.items():
                if self.is_account_available(provider, idx):
                    for _ in range(acc.weight):
                        weighted_list.append((idx, acc))

            if not weighted_list:
                return None

            # 简单轮询选取
            start_idx = self._round_robin_index.get(provider, 0)
            selected_idx = start_idx % len(weighted_list)
            actual_idx, account = weighted_list[selected_idx]

            self._round_robin_index[provider] = (start_idx + 1) % len(weighted_list)
            return actual_idx, account

    def get_next_account(self, provider: str, strategy: str = "round_robin") -> Optional[Tuple[int, str]]:
        """
        获取下一个可用账号
        :param provider: 提供者名称
        :param strategy: 策略类型 round_robin / weighted_round_robin
        :return: (账号索引, api_key) 或 None
        """
        if strategy == "weighted_round_robin":
            result = self.weighted_round_robin(provider)
        else:
            result = self.round_robin(provider)

        if result is None:
            logger.warning(f"提供者 {provider} 没有可用账号")
            self._trigger_alert(f"提供者 {provider} 所有账号都不可用", "critical")
            return None

        idx, account = result
        account.last_used = time.time()
        account.use_count += 1

        return idx, account.api_key

    # ==================== 状态标记 ====================

    def mark_account_success(self, provider: str, account_index: int) -> None:
        """
        标记账号成功
        :param provider: 提供者名称
        :param account_index: 账号索引
        """
        with self._lock:
            if provider not in self._accounts or account_index not in self._accounts[provider]:
                return

            acc = self._accounts[provider][account_index]
            acc.error_count = 0
            acc.success_count += 1
            acc.status = AccountStatus.ACTIVE.value

            logger.debug(f"账号 {provider}[{account_index}] 标记成功")
            self._save_state()

    def mark_account_failed(self, provider: str, account_index: int, error_code: Optional[int] = None) -> bool:
        """
        标记账号失败
        :param provider: 提供者名称
        :param account_index: 账号索引
        :param error_code: 错误码（402配额耗尽/429请求过多）
        :return: 是否需要切换到其他账号
        """
        with self._lock:
            if provider not in self._accounts or account_index not in self._accounts[provider]:
                return False

            acc = self._accounts[provider][account_index]
            acc.error_count += 1

            now = time.time()

            # 识别配额耗尽和限流信号：402长期不可用，429短暂冷却，不要一次失败就永久踢掉。
            if error_code == 402:
                acc.status = AccountStatus.QUOTA_EXHAUSTED.value
                logger.warning(f"账号 {provider}[{account_index}] 配额耗尽 (错误码: {error_code})")
            elif error_code == 429:
                acc.status = AccountStatus.ACTIVE.value
                acc.cooldown_until = now + 300
                logger.warning(f"账号 {provider}[{account_index}] 触发限流，冷却5分钟")
            else:
                if acc.error_count >= self._error_threshold:
                    acc.status = AccountStatus.ERROR.value
                else:
                    acc.status = AccountStatus.ACTIVE.value
                logger.warning(f"账号 {provider}[{account_index}] 错误 (错误码: {error_code}, 连续错误: {acc.error_count})")

            # 检查是否需要禁用
            if acc.error_count >= self._error_threshold:
                self.disable_account(provider, account_index)
                return True

            self._save_state()
            return True

    def disable_account(self, provider: str, account_index: int) -> None:
        """
        禁用账号
        :param provider: 提供者名称
        :param account_index: 账号索引
        """
        with self._lock:
            if provider not in self._accounts or account_index not in self._accounts[provider]:
                return

            acc = self._accounts[provider][account_index]
            acc.enabled = False
            acc.status = AccountStatus.DISABLED.value

            logger.warning(f"账号 {provider}[{account_index}] 已禁用 (连续错误: {acc.error_count})")
            self._trigger_alert(f"账号 {provider}[{acc.name}] 已禁用", "warning")
            self._save_state()

    def enable_account(self, provider: str, account_index: int) -> None:
        """
        启用账号
        :param provider: 提供者名称
        :param account_index: 账号索引
        """
        with self._lock:
            if provider not in self._accounts or account_index not in self._accounts[provider]:
                return

            acc = self._accounts[provider][account_index]
            acc.enabled = True
            acc.error_count = 0
            acc.cooldown_until = None
            acc.status = AccountStatus.ACTIVE.value

            logger.info(f"账号 {provider}[{account_index}] 已启用")
            self._save_state()

    def reset_account_status(self, provider: str) -> int:
        """
        重置提供者下所有账号状态
        :param provider: 提供者名称
        :return: 重置的账号数量
        """
        with self._lock:
            if provider not in self._accounts:
                return 0

            count = 0
            for idx, acc in self._accounts[provider].items():
                if acc.status != AccountStatus.DISABLED.value:
                    acc.status = AccountStatus.ACTIVE.value
                    acc.error_count = 0
                    acc.cooldown_until = None
                    count += 1

            self._round_robin_index[provider] = 0
            logger.info(f"提供者 {provider} 的 {count} 个账号已重置")
            self._save_state()
            return count

    # ==================== 状态查询 ====================

    def is_account_available(self, provider: str, account_index: int) -> bool:
        """
        检查账号是否可用
        :param provider: 提供者名称
        :param account_index: 账号索引
        :return: 是否可用
        """
        with self._lock:
            if provider not in self._accounts:
                return False
            if account_index not in self._accounts[provider]:
                return False

            acc = self._accounts[provider][account_index]
            if acc.cooldown_until and time.time() < acc.cooldown_until:
                return False
            if acc.cooldown_until and time.time() >= acc.cooldown_until:
                acc.cooldown_until = None
                if acc.status != AccountStatus.DISABLED.value:
                    acc.status = AccountStatus.ACTIVE.value
            return acc.enabled and acc.status not in (
                AccountStatus.DISABLED.value,
                AccountStatus.QUOTA_EXHAUSTED.value,
                AccountStatus.ERROR.value
            )

    def get_account_status(self, provider: str, account_index: int) -> Optional[Dict[str, Any]]:
        """
        获取账号详细状态
        :param provider: 提供者名称
        :param account_index: 账号索引
        :return: 账号状态字典
        """
        with self._lock:
            if provider not in self._accounts:
                return None
            if account_index not in self._accounts[provider]:
                return None

            acc = self._accounts[provider][account_index]
            return {
                "name": acc.name,
                "enabled": acc.enabled,
                "status": acc.status,
                "use_count": acc.use_count,
                "success_count": acc.success_count,
                "error_count": acc.error_count,
                "total_tokens": acc.total_tokens,
                "quota_limit": acc.quota_limit,
                "last_used": datetime.fromtimestamp(acc.last_used).isoformat() if acc.last_used else None
            }

    def get_provider_stats(self, provider: str) -> Optional[Dict[str, Any]]:
        """
        获取提供者统计信息
        :param provider: 提供者名称
        :return: 统计信息字典
        """
        with self._lock:
            if provider not in self._accounts:
                return None

            accounts = self._accounts[provider]
            total = len(accounts)
            enabled = sum(1 for acc in accounts.values() if acc.enabled)
            active = sum(1 for acc in accounts.values() if acc.status == AccountStatus.ACTIVE.value)
            quota_exhausted = sum(1 for acc in accounts.values() if acc.status == AccountStatus.QUOTA_EXHAUSTED.value)
            error = sum(1 for acc in accounts.values() if acc.status == AccountStatus.ERROR.value)

            total_usage = sum(acc.use_count for acc in accounts.values())
            total_success = sum(acc.success_count for acc in accounts.values())
            total_tokens = sum(acc.total_tokens for acc in accounts.values())

            return {
                "provider": provider,
                "total_accounts": total,
                "enabled_accounts": enabled,
                "active_accounts": active,
                "quota_exhausted": quota_exhausted,
                "error_accounts": error,
                "total_usage": total_usage,
                "total_success": total_success,
                "total_tokens": total_tokens
            }

    def get_all_providers_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有提供者统计信息"""
        stats = {}
        for provider in self._accounts.keys():
            provider_stats = self.get_provider_stats(provider)
            if provider_stats:
                stats[provider] = provider_stats
        return stats

    # ==================== 配额追踪 ====================

    def track_usage(self, provider: str, account_index: int, tokens: int) -> None:
        """
        追踪账号使用量
        :param provider: 提供者名称
        :param account_index: 账号索引
        :param tokens: 使用的token数量
        """
        with self._lock:
            if provider not in self._accounts or account_index not in self._accounts[provider]:
                return

            acc = self._accounts[provider][account_index]
            acc.total_tokens += tokens

            # 检查配额
            if acc.quota_limit and acc.total_tokens >= acc.quota_limit:
                acc.status = AccountStatus.QUOTA_EXHAUSTED.value
                logger.warning(f"账号 {provider}[{account_index}] 配额已用尽 ({acc.total_tokens}/{acc.quota_limit})")

            self._save_state()

    def check_quota(self, provider: str, account_index: int) -> Tuple[bool, int, Optional[int]]:
        """
        检查账号配额
        :param provider: 提供者名称
        :param account_index: 账号索引
        :return: (是否充足, 当前使用量, 配额上限)
        """
        with self._lock:
            if provider not in self._accounts or account_index not in self._accounts[provider]:
                return False, 0, None

            acc = self._accounts[provider][account_index]
            if acc.quota_limit is None:
                return True, acc.total_tokens, None

            return acc.total_tokens < acc.quota_limit, acc.total_tokens, acc.quota_limit

    # ==================== 故障转移 ====================

    def get_next_available_account(self, provider: str, current_index: int) -> Optional[Tuple[int, str]]:
        """
        获取当前账号失败后的下一个可用账号
        :param provider: 提供者名称
        :param current_index: 当前失败的账号索引
        :return: (新账号索引, api_key) 或 None
        """
        with self._lock:
            if provider not in self._accounts:
                return None

            accounts = self._accounts[provider]
            total = len(accounts)

            # 从当前索引的下一个开始找
            idx = (current_index + 1) % total
            for _ in range(total - 1):
                if self.is_account_available(provider, idx):
                    accounts[idx].last_used = time.time()
                    accounts[idx].use_count += 1
                    return idx, accounts[idx].api_key
                idx = (idx + 1) % total

            # 没有可用账号
            self._trigger_alert(f"提供者 {provider} 所有账号都不可用", "critical")
            return None

    def is_provider_available(self, provider: str) -> bool:
        """检查提供者是否有可用账号"""
        with self._lock:
            if provider not in self._accounts:
                return False
            return any(self.is_account_available(provider, idx) for idx in self._accounts[provider])

    def get_all_unavailable_reasons(self, provider: str) -> List[str]:
        """获取提供者下所有账号不可用的原因"""
        reasons = []
        with self._lock:
            if provider not in self._accounts:
                return ["提供者不存在"]

            for idx, acc in self._accounts[provider].items():
                if not self.is_account_available(provider, idx):
                    reason = f"[{idx}] {acc.name}: {acc.status}"
                    if acc.error_count > 0:
                        reason += f" (连续错误: {acc.error_count})"
                    reasons.append(reason)

        return reasons

    # ==================== 手动管理 ====================

    def add_account(self, provider: str, api_key: str, name: str = "", **kwargs) -> int:
        """
        添加账号
        :param provider: 提供者名称
        :param api_key: API密钥
        :param name: 账号名称
        :param kwargs: 其他参数（weight, quota_limit等）
        :return: 新账号索引
        """
        with self._lock:
            if provider not in self._accounts:
                self._accounts[provider] = {}
                self._round_robin_index[provider] = 0

            idx = len(self._accounts[provider])
            account = AccountInfo(
                api_key=api_key,
                name=name or f"{provider}_account_{idx}",
                **kwargs
            )
            self._accounts[provider][idx] = account

            logger.info(f"添加账号 {provider}[{idx}] {account.name}")
            self._save_state()
            return idx

    def remove_account(self, provider: str, account_index: int) -> bool:
        """
        移除账号
        :param provider: 提供者名称
        :param account_index: 账号索引
        :return: 是否成功
        """
        with self._lock:
            if provider not in self._accounts or account_index not in self._accounts[provider]:
                return False

            acc = self._accounts[provider].pop(account_index)
            logger.info(f"移除账号 {provider}[{account_index}] {acc.name}")
            self._save_state()
            return True

    def update_account(self, provider: str, account_index: int, **kwargs) -> bool:
        """
        更新账号信息
        :param provider: 提供者名称
        :param account_index: 账号索引
        :param kwargs: 要更新的字段
        :return: 是否成功
        """
        with self._lock:
            if provider not in self._accounts or account_index not in self._accounts[provider]:
                return False

            acc = self._accounts[provider][account_index]
            for key, value in kwargs.items():
                if hasattr(acc, key):
                    setattr(acc, key, value)

            logger.info(f"更新账号 {provider}[{account_index}]")
            self._save_state()
            return True

    def get_all_accounts(self, provider: str) -> List[Dict[str, Any]]:
        """获取提供者下所有账号信息"""
        with self._lock:
            if provider not in self._accounts:
                return []
            return [
                {
                    "index": idx,
                    **asdict(acc)
                }
                for idx, acc in self._accounts[provider].items()
            ]


# ==================== 全局单例 ====================

_global_manager: Optional[AccountManager] = None
_manager_lock = threading.Lock()


def get_account_manager(config_manager=None, state_file: Optional[str] = None) -> AccountManager:
    """
    获取账号管理器单例
    :param config_manager: 配置管理器实例（仅首次调用有效）
    :param state_file: 状态文件路径（仅首次调用有效）
    :return: AccountManager实例
    """
    global _global_manager
    with _manager_lock:
        if _global_manager is None:
            _global_manager = AccountManager(config_manager, state_file)
        return _global_manager


def reset_account_manager() -> None:
    """重置全局单例（用于测试）"""
    global _global_manager
    with _manager_lock:
        _global_manager = None
