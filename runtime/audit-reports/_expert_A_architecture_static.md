# 专家 A 审计报告 · 架构 + 静态实现真实性

- 项目：mory_assistant
- 审计范围：v5.32.0 → v5.35.0（HEAD=77e849a，工作区 38 modified + 55 untracked）
- 审计时间：2026-07-18
- 审计角色：专家 A（架构 + 静态实现真实性）
- 审计方式：本地只读 + py_compile + import 测试 + grep + 真实文件:行号证据

---

## 1. 执行摘要

### 总体结论

本轮 v5.32.0 → v5.35.0 大改**呈现两极分化**：

- **v5.32.0 广告检测大升级（7 个新模块）** 和 **v5.34.0 6 大业务模块** 状态为 **VERIFIED 或 IMPLEMENTED_CODE_ONLY**，代码完整、可导入、有真实业务调用（v5.32.0）或代码完整但无业务调用（v5.34.0）。
- **v5.35.0 36 个新模块 + anti_raid 改写** 状态为 **BROKEN**，全部因 4 类错误导入在 `import` 阶段失败，**无法被运行时加载**，且**没有任何业务代码引用**。

### 核心数据（实测）

| 指标 | 实测值 | 文档声明值 | 偏差 |
|---|---|---|---|
| v5.32.0+ 新模块总数 | 50 个 | — | — |
| 可正常 import 的模块 | 13 个（26%） | — | — |
| ImportError 的模块 | 37 个（74%） | — | — |
| BaseTask 子类实测数 | 88 | project_snapshot.md `job_count=50` | **-38**（文档严重失真） |
| version.py VERSION | `v5.33.1` | VERSION.md `v5.35.0` | **不一致** |
| VERSION_HISTORY 最新条目 | `v5.33.1` | `v5.35.0` | **未维护** |
| modules/__init__.py `__all__` | 81 个老模块 | — | **不含任何 v5.34.0/v5.35.0 新模块** |
| 单元测试结果 | 305 passed / 7 skipped | — | 无针对新模块的测试 |

### 4 大致命问题（P0）

1. **anti_raid 模块被破坏**：HEAD 版本有模块级 `def check_raid()` 函数，新版被改成 `class AntiRaidModule` + async 方法，且 4 类导入错误。`member_handlers.py:56` 和 `message_dispatcher.py:868` 调用 `from modules.anti_raid import check_raid` 触发 ImportError 被 `except Exception: logger.debug(...)` **静默吞掉**，反突袭功能完全失效且每次新人入群触发一次静默异常。
2. **37 个新模块全部 ImportError**：4 类错误导入模式覆盖 36 个 v5.35.0 新模块 + anti_raid：
   - `from core.settings import config`（`core/settings.py` 无 `config` 全局，只有 `settings` 代理 / `get_config()` 函数）
   - `from core.database import db_manager`（`core/database.py` 只有 `class DB` 和 `_db_lock`，无 `db_manager` 全局）
   - `from core.telebot_compat import TelebotCompat`（`core/telebot_compat.py` 只导出 21 个 compat 函数，无 `TelebotCompat` 类）
   - `from utils.logger import get_logger`（**项目根本不存在 `utils` 模块**，正确路径是 `core.logging_util`）
3. **5+ 新模块查询不存在的表**：表名复数化错误 + 完全不存在的表，10 个模块在运行时全部走 except 静默返回空值。
4. **bottom_button.py 用错 Telegram 库**：`from telegram import InlineKeyboardMarkup` 是 `python-telegram-bot` 库的 API，项目实际用 `telebot` (pyTelegramBotAPI)，即使其他导入修复此模块仍无法工作。

---

## 2. 语法导入审计表

### 2.1 语法层（py_compile）

所有 50 个新模块 .py 文件 py_compile 通过（语法层无问题）。**语法正确 ≠ 运行时可用**。

### 2.2 导入层（import 实测）

实测命令：`python -c "import importlib; importlib.import_module('modules.xxx')"`

| 模块批次 | 模块名 | 状态 | 错误类型 | 错误首行 |
|---|---|---|---|---|
| v5.32.0 | modules.ai_advisor | VERIFIED | — | — |
| v5.32.0 | modules.ad_marketing_patterns | VERIFIED | — | — |
| v5.32.0 | modules.ad_profile_signals | VERIFIED | — | — |
| v5.32.0 | modules.edit_detector | VERIFIED | — | — |
| v5.32.0 | modules.global_blacklist | VERIFIED | — | — |
| v5.32.0 | modules.avatar_detector | VERIFIED | — | — |
| v5.32.0 | modules.ad_enforcement | VERIFIED | — | — |
| v5.34.0 | modules.sales_center | VERIFIED | — | — |
| v5.34.0 | modules.security_center | VERIFIED | — | — |
| v5.34.0 | modules.managed_groups | VERIFIED | — | — |
| v5.34.0 | modules.content_audit | VERIFIED | — | — |
| v5.34.0 | modules.new_member_analytics | VERIFIED | — | — |
| v5.34.0 | modules.membership | VERIFIED | — | — |
| v5.35.0 | modules.bottom_button | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.crypto_detector | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.config_template | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.content_archive | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.message_library | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.random_drop | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.group_props | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.image_manager | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.chat_settings | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.join_settings | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.group_commands | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.bot_settings | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.afool_member | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.super_afool | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.bot_list | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.new_member_probation | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.group_report | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.word_cloud | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.language_whitelist | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.force_channel | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.valid_speak | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.chat_points_cost | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.auto_rules | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.user_marking | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.group_todo | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.invite_link_manager | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.channel_link | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.stats_report | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.entertainment_games | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.punishment_center | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.group_message_push | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.group_safety_center | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.ad_blocker | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.group_members | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.group_migration | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.anti_raid（改写） | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |
| v5.35.0 | modules.group_list | BROKEN | ImportError | cannot import name 'config' from 'core.settings' |

**汇总：50 个新模块中，13 个 VERIFIED（26%），37 个 BROKEN（74%）。**

### 2.3 4 类错误导入的真实 API 对照

| 错误导入 | 真实 API | 证据 |
|---|---|---|
| `from core.settings import config` | `from core.settings import settings, get_config, get_config_value` | `core/settings.py:318` `settings = _SettingsProxy()` / `:323` `def get_config()` / `:328` `def get_config_value()` |
| `from core.database import db_manager` | `from core.database import DB, _db_lock` 或通过依赖注入传入 `db` 实例 | `core/database.py:43` `class DB:` / `:40` `_db_lock = RLock()`，**无 `db_manager` 全局** |
| `from core.telebot_compat import TelebotCompat` | `from core.telebot_compat import send_message_compat, restrict_chat_member_compat, ...` | `core/telebot_compat.py` 全部 21 个导出都是函数，**无 `TelebotCompat` 类** |
| `from utils.logger import get_logger` | `from core.logging_util import get_logger` | 项目根本**不存在 `utils/` 模块**，正确路径是 `core/logging_util.py` |

---

## 3. 空壳和伪实现清单

### 3.1 真实空壳（P0/P1）

| 文件:行号 | 模式 | 严重度 | 说明 |
|---|---|---|---|
| `modules/group_props.py:115-124` | 5 个 `effect_type` 中 4 个 `pass` | P1 | `_apply_prop_effect` 只实装 `unmute` 1 种效果，`pin`/`speed`/`protect`/`nickname` 全部 `pass` 空壳。即使导入修复，4/5 道具效果无效 |
| `modules/anti_raid.py:127-128` | `async def process(self, update): return None` | P0 | 占位方法返回 None，无实际逻辑 |
| `modules/bottom_button.py:98-99` | `async def process(self, update): return None` | P0 | 占位方法返回 None，无实际逻辑 |

### 3.2 except 块静默返回默认值（容错降级，但掩盖真实故障）

| 文件:行号 | 模式 | 说明 |
|---|---|---|
| `modules/image_manager.py:43-44, 53-55, 63-66, 73-75, 82-84, 105-108, 119-120` | 7 处 except 块返回 `False`/`[]`/`{}` | 查询 `image_records` 不存在的表，全部走 except 静默返回空，等于功能完全失效但用户无感知 |
| `modules/group_props.py:125-126` | except 块仅 log error | `_apply_prop_effect` 异常被吞 |
| `modules/group_report.py:59, 133` | except 块 `pass` | 静默失败 |
| `modules/group_migration.py:62, 106` | except 块 `pass` | 静默失败 |
| `modules/join_settings.py:82` | except 块 `pass` | 静默失败 |
| `modules/language_whitelist.py:37` | except 块 `pass` | 静默失败 |
| `modules/managed_groups.py:153` | except 块 `pass` 后 fallthrough 到 `feature in features` 兜底 | 容错降级，但表 `managed_group_features` 不存在时永远走兜底 |
| `modules/security_center.py:199` | except 块 `pass` | 静默失败 |
| `modules/auto_tasks.py:1706, 3840` | `pass` 占位 | 老模块历史代码 |
| `modules/group_props.py:116, 120, 122, 124` | `pass` 空效果 | 见 3.1 |

### 3.3 抽象基类（正常 NotImplementedError，非空壳）

| 文件:行号 | 说明 |
|---|---|
| `modules/triggers/base.py:29, 33` | 抽象基类 `BaseTrigger` 的 `evaluate` / `execute` 抛 `NotImplementedError`，正常设计 |

### 3.4 ad_detector.py 中的容错 pass（正常）

| 文件:行号 | 说明 |
|---|---|
| `modules/ad_detector.py:497, 515, 592, 806, 1442` | try-except 默认值场景的 `pass`，属于正常容错，不是空壳 |

---

## 4. 可达性矩阵

### 4.1 v5.32.0 广告检测大升级（7 个模块）— VERIFIED，有真实业务调用

| 模块 | 状态 | 调用入口 | 证据 |
|---|---|---|---|
| ai_advisor | VERIFIED | ad_detector.py:980 / ad_enforcement.py:555 / avatar_detector.py:389 | 4 个真实函数：`review_borderline_ad` / `warn_suspicious_user` / `explain_enforcement_to_chat` / `review_avatar_with_vision` |
| ad_marketing_patterns | VERIFIED | ad_detector.py:34 | 真实 import 4 个正则列表 `MARKETING_TEMPLATE_PATTERNS` 等 |
| ad_profile_signals | VERIFIED | member_handlers.py:125 | `detect_profile_ad_signal` 真实调用 |
| edit_detector | VERIFIED | security_handlers.py / callback_handlers.py | 真实接入主分发链路 |
| global_blacklist | VERIFIED | member_handlers.py:290 | `check_global_blacklist` 真实调用 |
| avatar_detector | VERIFIED | member_handlers.py:203 | `check_user_avatar` / `check_avatar_similarity` 真实调用 |
| ad_enforcement | VERIFIED | member_handlers.py:68,103,132,172,207,224 / security_handlers.py | `enforce_ad_user` 统一广告执法入口，10+ 处真实调用 |

### 4.2 v5.34.0 6 大业务模块 — IMPLEMENTED_CODE_ONLY，无业务调用

| 模块 | 状态 | 内部实现 | 业务调用 |
|---|---|---|---|
| sales_center | IMPLEMENTED_CODE_ONLY | SalesCenter 类 + 多个真实方法 | **无任何业务代码引用** |
| security_center | IMPLEMENTED_CODE_ONLY | RiskScorer 类 + log_security_event + get_security_overview | **无任何业务代码引用** |
| managed_groups | IMPLEMENTED_CODE_ONLY | 多群托管 + set_feature_enabled | **无任何业务代码引用** |
| content_audit | IMPLEMENTED_CODE_ONLY | 内容审计逻辑 | **无任何业务代码引用** |
| new_member_analytics | IMPLEMENTED_CODE_ONLY | 新成员数据分析 | **无任何业务代码引用** |
| membership | IMPLEMENTED_CODE_ONLY | 会员订阅逻辑 | **无任何业务代码引用** |

### 4.3 v5.35.0 36 个新模块 — BROKEN，导入失败 + 无业务调用

| 模块 | 状态 | ImportError | 业务调用 |
|---|---|---|---|
| bottom_button | BROKEN | `from core.settings import config` + `from telegram import InlineKeyboardMarkup`（错库） | 无 |
| crypto_detector | BROKEN | `from core.settings import config` | 无 |
| config_template | BROKEN | `from core.settings import config` | 无 |
| content_archive | BROKEN | `from core.settings import config` | 无 |
| message_library | BROKEN | `from core.settings import config` | 无 |
| random_drop | BROKEN | `from core.settings import config` | 无 |
| group_props | BROKEN | `from core.settings import config` | 无 |
| image_manager | BROKEN | `from core.settings import config` + 查 `image_records` 不存在的表 | 无 |
| chat_settings | BROKEN | `from core.settings import config` | 无 |
| join_settings | BROKEN | `from core.settings import config` | 无 |
| group_commands | BROKEN | `from core.settings import config` | 无 |
| bot_settings | BROKEN | `from core.settings import config` | 无 |
| afool_member | BROKEN | `from core.settings import config` | 无 |
| super_afool | BROKEN | `from core.settings import config` + 查 `premium_usage` 不存在的表 | 无 |
| bot_list | BROKEN | `from core.settings import config` + 查 `bot_registry` 不存在的表 | 无 |
| new_member_probation | BROKEN | `from core.settings import config` | 无 |
| group_report | BROKEN | `from core.settings import config` + 查 `group_reports` 表名错误 | 无 |
| word_cloud | BROKEN | `from core.settings import config` + 查 `word_clouds` 表名错误 | 无 |
| language_whitelist | BROKEN | `from core.settings import config` | 无 |
| force_channel | BROKEN | `from core.settings import config` | 无 |
| valid_speak | BROKEN | `from core.settings import config` + 查 `valid_speak_records` 表名错误 | 无 |
| chat_points_cost | BROKEN | `from core.settings import config` | 无 |
| auto_rules | BROKEN | `from core.settings import config` | 无 |
| user_marking | BROKEN | `from core.settings import config` | 无 |
| group_todo | BROKEN | `from core.settings import config` + 查 `group_todos` 表名错误 | 无 |
| invite_link_manager | BROKEN | `from core.settings import config` | 无 |
| channel_link | BROKEN | `from core.settings import config` + 查 `channel_links` 表名错误 | 无 |
| stats_report | BROKEN | `from core.settings import config` | 无 |
| entertainment_games | BROKEN | `from core.settings import config` | 无 |
| punishment_center | BROKEN | `from core.settings import config` | 无 |
| group_message_push | BROKEN | `from core.settings import config` | 无 |
| group_safety_center | BROKEN | `from core.settings import config` | 无 |
| ad_blocker | BROKEN | `from core.settings import config` + 查 `global_ad_blacklist` 不存在的表 | 无 |
| group_members | BROKEN | `from core.settings import config` | 无 |
| group_migration | BROKEN | `from core.settings import config` | 无 |
| anti_raid（改写） | BROKEN | `from core.settings import config` + 模块级函数 `check_raid` 被改成 async 方法 + 调用方 `check_raid(bot, m, config, db)` 签名不匹配 | **2 处调用但全部触发 ImportError 静默吞掉** |
| group_list | BROKEN | `from core.settings import config` + 查 `group_registry` 不存在的表 | 无 |

### 4.4 modules/__init__.py `__all__` 不含新模块

`modules/__init__.py:4-86` 的 `__all__` 列表共 81 个老模块名，**不包含任何 v5.34.0 / v5.35.0 新模块**。这意味着 `from modules import *` 不会导入任何新模块。`anti_raid` 在 `__all__` 中但被改写破坏。

---

## 5. 注册顺序问题

### 5.1 callback_handlers.py — OK

`core/handlers/callback_handlers.py` 注册顺序：黑名单 → `ad_unban:` → `fb_` → `verify_` → `settings_` → `rp_` → `lot_` → `vk_` → `zc_` → `ghost_` → catch-all `on_any_callback`。

catch-all 在最后注册，符合 pyTelegramBotAPI "首个匹配后停止分发"规则。**注册顺序 OK，无抢占问题。**

### 5.2 message_dispatcher.py 优先级链 — OK

`core/message_dispatcher.py:497-744` 优先级链：P0 member → /unban 早路由 → P1-P3 security → P3.5 ad_detection → P3.6 intent → P2 points → P4 flood → P5-P9 commands → P10 AI。

**优先级链正确，无抢占问题。**

### 5.3 main.py 与 member_handlers 重复注册 new_chat_members — P2 设计问题

| 文件:行号 | 注册内容 | 问题 |
|---|---|---|
| `main.py:165-166` | `@bot.message_handler(func=lambda m: True, content_types=["text", "new_chat_members"])` 兜底 handler | `content_types` 包含 `new_chat_members` 与 member_handlers 重叠 |
| `core/handlers/member_handlers.py:25-26` | `@bot.message_handler(func=lambda m: m.content_type == "new_chat_members", content_types=["new_chat_members"])` 专用 handler | 先注册，先匹配 |

**实际行为**：pyTelegramBotAPI 按 content_type 分桶，`new_chat_members` 事件来时 member_handlers 的专用 handler 先匹配并处理，消息不再传递到 main.py 的 on_any_message。**因此不会真正重复处理，但 main.py 的 `content_types=["text", "new_chat_members"]` 设计冗余且误导**，应改为 `content_types=["text"]`。

### 5.4 auto_tasks.py 死代码 — P3

`modules/auto_tasks.py:4513-4580` `start_background()` 调用 `_start_with_task_scheduler()`（用新 TaskScheduler），`_start_with_apscheduler()` 是死代码，无人调用。但 `report_fault` / `_notify_admin_system_failure` 等工具函数仍被 18+ 核心模块引用，**不能整体删除**。

---

## 6. 重复与冲突清单

### 6.1 anti_raid 新旧版本冲突 — P0

| 版本 | API 形态 | 调用方签名 |
|---|---|---|
| HEAD 版本（已被覆盖） | 模块级 `def check_raid(bot, m, config, db)` 函数 | `check_raid(bot, m, config, db)` |
| 工作区新版（BROKEN） | `class AntiRaidModule` + `async def check_raid(self, chat_id, new_member_count=1)` 方法 | 调用方仍写 `from modules.anti_raid import check_raid; check_raid(bot, m, config, db)` |

**冲突点**：
- 调用方期望模块级函数 `check_raid(bot, m, config, db)`
- 新版改为类方法 `check_raid(self, chat_id, new_member_count=1)`，签名完全不同
- 新版 `from modules.anti_raid import check_raid` 在导入阶段就 ImportError（4 类错误）
- 即使导入修复，调用方仍会拿到类方法对象，调用 `check_raid(bot, m, config, db)` 会因 `self` 不匹配报 TypeError

证据：
- `core/handlers/member_handlers.py:56` `from modules.anti_raid import check_raid`
- `core/handlers/member_handlers.py:57` `check_raid(bot, m, config, db)`（在 try-except 内）
- `core/handlers/member_handlers.py:58-59` `except Exception as e: logger.debug(f"操作异常: {e}")`（**静默吞掉 ImportError**）
- `core/message_dispatcher.py:868-871` 同样的 try-except 静默模式

### 6.2 表名复数化冲突 — P0

`core/database.py:1036-1700` 建表用单数，模块查询用复数，导致运行时全部走 except 静默返回空：

| 模块 | 查询的表名 | 建表的真实表名 | 状态 |
|---|---|---|---|
| channel_link.py | `channel_links` | `channel_link` | BROKEN |
| group_report.py | `group_reports` | `group_report` | BROKEN |
| group_todo.py | `group_todos` | `group_todo` | BROKEN |
| valid_speak.py | `valid_speak_records` | `valid_speak` | BROKEN |
| word_cloud.py | `word_clouds` | `word_cloud` | BROKEN |

### 6.3 完全不存在的表 — P0

| 模块 | 查询的表名 | 是否建表 | 状态 |
|---|---|---|---|
| bot_list.py | `bot_registry` | 否（建表名是 `bot_list`） | BROKEN |
| group_list.py | `group_registry` | 否 | BROKEN |
| super_afool.py | `premium_usage` | 否 | BROKEN |
| image_manager.py | `image_records` | 否 | BROKEN |
| ad_blocker.py | `global_ad_blacklist` | 否 | BROKEN |
| anti_raid.py | `group_join_log` | 否 | BROKEN |

### 6.4 _REPO_METHOD_MAP 漏注册风险 — NOT_APPLICABLE（本次未触发）

`core/database.py:1832-1836` 注册了 `sales_repo` 13 个方法 + `_REPO_ATTR_MAP:1845` 注册 `'sales': 'sales'`。`scripts/verify_db_methods.py` 已通过。**本次新增的 36 个 BROKEN 模块没有定义 Repo 方法，不触发漏注册防御**。但如果修复后新增 Repo 方法，必须同步 `_REPO_METHOD_MAP`。

---

## 7. 代码质量问题

### 7.1 时区边界 — P1（项目铁律违反）

`core/database.py:34` `_CST = timezone(timedelta(hours=8))` 是项目铁律（修复v21.47 统一北京时间）。但 **36 个 v5.35.0 新模块全部使用 `datetime.now()` 不带时区**，违反铁律。

实测 grep 结果（节选，完整 50+ 处见 grep 输出）：

| 文件:行号 | 问题代码 |
|---|---|
| `modules/anti_raid.py:55` | `unlock_time = datetime.now() + timedelta(seconds=defense_duration)` |
| `modules/anti_raid.py:66` | `until_date=datetime.now() + timedelta(seconds=mute_duration)` |
| `modules/ad_blocker.py:45` | `ban_until = datetime.now() + timedelta(days=...)` |
| `modules/afool_member.py:47, 48, 67, 94, 112` | 5 处 `datetime.now().isoformat()` |
| `modules/bottom_button.py:35` | `now = datetime.now()` |
| `modules/chat_settings.py:62` | `current['updated_at'] = datetime.now().isoformat()` |
| `modules/chat_points_cost.py:33, 73, 89, 111` | 4 处 `datetime.now().date().isoformat()` |
| `modules/channel_link.py:35` | `'created_at': datetime.now().isoformat()` |
| `modules/content_archive.py:43, 161` | 2 处 `datetime.now().isoformat()` |
| `modules/group_*.py` | 大量 `datetime.now().isoformat()` |

**影响**：
- 时间戳与 DB 中 `_CST` 时不一致，跨时区部署时数据错乱
- 每日重置类任务（如 `chat_points_cost` 的 `today = datetime.now().date().isoformat()`）可能错时
- 与 `core/database.py` 中所有 `_CST` 时间戳不对齐

### 7.2 无界缓存 — P2

| 文件:行号 | 缓存 | 上限 | 问题 |
|---|---|---|---|
| `modules/antidelete.py:30` | `_msg_cache = {}` | `MAX_CACHE_PER_CHAT=50` 限制每个 chat 的消息数 | **无 chat_id 总数上限**，bot 接入很多群时 `_msg_cache` 的 keys 无界增长 |
| `modules/ad_detector.py:187-188` | `self._cas_cache = {}` / `self._spb_cache = {}` | `self._AD_CACHE_MAX = 2000` | 有上限，正常 |
| `modules/security_center.py:96-97` | `self._cache = {}` | `self._max_cache = 5000` | 有上限，正常 |
| `modules/auto_tasks.py:3191, 3453` | `_tarot_daily_cache = {}` | 无上限 | 函数内局部变量，每日重建，影响有限 |

### 7.3 阻塞调用 — P3

| 文件:行号 | 调用 | 说明 |
|---|---|---|
| `modules/ad_detector.py:1538, 1598` | `time.sleep(1)` | 在重试循环内，正常 |
| `modules/auto_tasks.py:447, 458` | `time.sleep(60)` / `time.sleep(5)` | 后台任务 polling 间隔，正常 |
| `modules/auto_tasks.py:2353, 5016` | `time.sleep(1)` / `time.sleep(60)` | 后台任务，正常 |

**未发现危险的阻塞调用**（如主线程 `time.sleep` 长时间阻塞）。

### 7.4 日志泄露 — 通过

grep 搜索 `logger.(info|debug|error|warning).*(?:token|api_key|password|secret|cookie)` 未发现匹配。`modules/content.py:237` 有注释 "不再将 Token 拼入 URL（防止异常日志泄露 Token）" 表明项目对此有意识。

### 7.5 全局可变状态 — P3

| 文件 | 全局变量 | 说明 |
|---|---|---|
| `modules/security_center.py` | `global` 关键字使用 | 需进一步审查线程安全性 |
| `modules/auto_tasks.py` | `global` 关键字使用 | 老模块，历史代码 |
| `modules/group_mgr.py` | `global` 关键字使用 | 老模块，历史代码 |

### 7.6 v5.34.0 6 大模块代码完整但闲置 — P1

`sales_center` / `security_center` / `managed_groups` / `content_audit` / `new_member_analytics` / `membership` 6 个模块：
- 代码完整（如 `security_center` 有 `RiskScorer` 类 / `log_security_event` / `get_security_overview` 等真实函数）
- 可正常 import
- **但没有任何业务代码调用它们任何函数**
- `modules/__init__.py` 的 `__all__` 也不包含它们
- 状态：**IMPLEMENTED_CODE_ONLY**，需要接入主分发链路或 Dashboard API 才能产生价值

### 7.7 sales_repo 无人调用 — P1

`core/db_repos/sales_repo.py` 的 `SalesRepo` 类实现 13 个真实方法（add_product / update_product / list_products / get_product / create_order / update_order_status / get_user_orders / get_order_stats / track_sales_event / get_funnel_stats / add_commission / get_commission_stats），已正确注册到 `_REPO_METHOD_MAP`。但 **没有任何业务代码通过 `ctx.db.add_product()` 等调用**，等同于死代码。

---

## 8. P0/P1/P2/P3 缺陷表

### P0（致命，必须立即修复）

| ID | 标题 | 文件:行号 | 真实影响 | 建议修复 |
|---|---|---|---|---|
| P0-1 | anti_raid 模块被破坏，反突袭功能完全失效且静默吞异常 | `modules/anti_raid.py:8-11`（4 类错误导入）+ `modules/anti_raid.py:34`（签名改为 async 方法）+ `core/handlers/member_handlers.py:56-59`（try-except 静默吞 ImportError）+ `core/message_dispatcher.py:868-871`（同上） | 反突袭功能完全失效；每次新人入群触发一次 ImportError 被静默吞掉；调用方 `check_raid(bot, m, config, db)` 签名与新版 `check_raid(self, chat_id, new_member_count=1)` 不匹配 | 二选一：(A) 回滚 anti_raid.py 到 HEAD 版本的模块级 `def check_raid(bot, m, config, db)` 函数；(B) 保留新版 class 但同步修改 2 处调用方为 `from modules.anti_raid import anti_raid_module; await anti_raid_module.check_raid(chat_id, new_member_count)`，并修复 4 类错误导入 |
| P0-2 | 36 个 v5.35.0 新模块全部 ImportError | 36 个模块的 `from core.settings import config` / `from core.database import db_manager` / `from core.telebot_compat import TelebotCompat` / `from utils.logger import get_logger` | 36 个新模块无法被运行时加载，所有功能完全失效 | 批量替换 4 类错误导入为真实 API；或在 `core/settings.py` / `core/database.py` / `core/telebot_compat.py` 添加兼容性别名（不推荐，掩盖设计问题） |
| P0-3 | 5+ 新模块查询不存在的表 | `modules/channel_link.py`（`channel_links` vs `channel_link`）/ `modules/group_report.py`（`group_reports` vs `group_report`）/ `modules/group_todo.py`（`group_todos` vs `group_todo`）/ `modules/valid_speak.py`（`valid_speak_records` vs `valid_speak`）/ `modules/word_cloud.py`（`word_clouds` vs `word_cloud`）/ `modules/bot_list.py`（`bot_registry` 完全不存在）/ `modules/group_list.py`（`group_registry` 完全不存在）/ `modules/super_afool.py`（`premium_usage` 完全不存在）/ `modules/image_manager.py`（`image_records` 完全不存在）/ `modules/ad_blocker.py`（`global_ad_blacklist` 完全不存在）/ `modules/anti_raid.py`（`group_join_log` 完全不存在） | 即使导入修复，运行时查询全部走 except 静默返回空值，功能完全失效但用户无感知 | 二选一：(A) 修改模块代码使用正确的单数表名；(B) 在 `core/database.py._init_tables()` 添加缺失的表（`bot_registry` / `group_registry` / `premium_usage` / `image_records` / `global_ad_blacklist` / `group_join_log`） |
| P0-4 | bottom_button.py 用错 Telegram 库 | `modules/bottom_button.py:8` `from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove` | 项目用 `telebot` (pyTelegramBotAPI)，不是 `python-telegram-bot`；即使其他导入修复，此模块仍无法工作 | 改用 `from telebot import types` 或 `from core.telebot_compat import send_message_compat` 等 compat 函数 |

### P1（高危，影响功能可用性）

| ID | 标题 | 文件:行号 | 真实影响 | 建议修复 |
|---|---|---|---|---|
| P1-1 | 41 个新模块无任何业务代码引用 | `modules/__init__.py:4-86` `__all__` 不含新模块 + 全项目 grep 无 `from modules.<新模块> import` | 即使导入修复，新模块仍是死代码，不产生业务价值 | 接入主分发链路（`message_dispatcher.py` / `member_handlers.py`）或 Dashboard API；同步更新 `__all__` |
| P1-2 | v5.34.0 6 大模块状态为 IMPLEMENTED_CODE_ONLY | `modules/sales_center.py` / `security_center.py` / `managed_groups.py` / `content_audit.py` / `new_member_analytics.py` / `membership.py` | 代码完整但无业务调用，等同于死代码 | 接入主分发链路或 Dashboard API；至少接入一个真实入口证明可达 |
| P1-3 | 时区铁律违反 | 36 个 v5.35.0 新模块 50+ 处 `datetime.now()` 不带时区 | 时间戳与 DB `_CST` 时不一致；跨时区部署数据错乱；每日重置类任务可能错时 | 批量替换为 `datetime.now(_CST)`，或统一封装 `core/time_util.py` 工具函数 |
| P1-4 | group_props 道具效果 4/5 空壳 | `modules/group_props.py:115-124` `_apply_prop_effect` 中 `pin`/`speed`/`protect`/`nickname` 4 种效果全部 `pass` | 即使导入修复，4/5 道具效果无效 | 实装 4 种效果，或在配置中标注"未实装"避免误导 |
| P1-5 | sales_repo 13 个方法无人调用 | `core/db_repos/sales_repo.py` 全部 13 个方法 | 死代码，不产生业务价值 | 接入 `sales_center.py` 或 Dashboard API |

### P2（中危，影响可维护性）

| ID | 标题 | 文件:行号 | 真实影响 | 建议修复 |
|---|---|---|---|---|
| P2-1 | project_snapshot.md METRICS 失真 | `project_snapshot.md:47` `job_count=50` | 实测 BaseTask 子类 88 个，文档严重失真 | 运行 `python scripts/doc_consistency.py` 重新统计；更新 `job_count=88` |
| P2-2 | version.py 与 VERSION.md 不一致 | `version.py:9` `VERSION = "v5.33.1"` vs `VERSION.md:5` `v5.35.0` | 版本号混乱，部署脚本读取 version.py 会得到错误版本 | 同步 `version.py` 到 `v5.35.0`；补全 `VERSION_HISTORY` 中 v5.34.0 / v5.35.0 条目 |
| P2-3 | 无任何针对新模块的测试 | `tests/` 目录 | 50 个新模块无单元测试覆盖；现有 305 passed / 7 skipped 全部针对老模块 | 为每个新模块补充至少 1 个 import 测试 + 1 个核心函数测试 |
| P2-4 | main.py content_types 设计冗余 | `main.py:166` `content_types=["text", "new_chat_members"]` | 与 member_handlers 专用 handler 重叠，虽不实际重复处理但设计误导 | 改为 `content_types=["text"]` |
| P2-5 | antidelete.py `_msg_cache` 无群组总数上限 | `modules/antidelete.py:30` | bot 接入很多群时 `_msg_cache` 的 keys 无界增长 | 添加 `MAX_TOTAL_CHATS` 上限，超限时淘汰最旧 chat_id |

### P3（低危，清理优化）

| ID | 标题 | 文件:行号 | 真实影响 | 建议修复 |
|---|---|---|---|---|
| P3-1 | auto_tasks._start_with_apscheduler 死代码 | `modules/auto_tasks.py:4513-4580` 附近 | 死函数无人调用 | 删除或标注 `[DEPRECATED v5.x]` |
| P3-2 | image_manager.py 7 处 except 静默返回空 | `modules/image_manager.py:43-44, 53-55, 63-66, 73-75, 82-84, 105-108, 119-120` | 表不存在时全部走 except 返回空，用户无感知 | 修复 P0-3 后此问题自动消失；或启动时检查表存在性 |
| P3-3 | 多处 except 块 `pass` 静默失败 | `modules/group_report.py:59, 133` / `modules/group_migration.py:62, 106` / `modules/join_settings.py:82` / `modules/language_whitelist.py:37` / `modules/managed_groups.py:153` / `modules/security_center.py:199` | 隐藏真实故障 | 改为 `logger.warning(f"[模块名] 操作失败: {e}")` |
| P3-4 | 36 个新模块模块底部实例化模式 | `modules/anti_raid.py:131` `anti_raid_module = AntiRaidModule()` 等 | 导入失败时永远到不了这一行；即使导入修复，模块级实例化会阻塞 import | 改为懒加载 `get_anti_raid_module()` 工厂函数 |

---

## 9. 关键发现（最多 10 项）

### 发现 1：v5.35.0 36 个新模块全部 BROKEN，导入阶段就失败

**实测 37/50 个新模块 ImportError（74%）**。4 类错误导入模式（`from core.settings import config` / `from core.database import db_manager` / `from core.telebot_compat import TelebotCompat` / `from utils.logger import get_logger`）覆盖全部 36 个 v5.35.0 新模块 + anti_raid 改写。**这不是个别笔误，而是批量生成代码时未对照真实 API 的系统性问题。**

### 发现 2：anti_raid 改写破坏了 HEAD 版本的可工作代码

HEAD 版本有模块级 `def check_raid(bot, m, config, db)` 函数，被 `member_handlers.py:56` 和 `message_dispatcher.py:868` 真实调用。新版被改成 `class AntiRaidModule` + `async def check_raid(self, chat_id, new_member_count=1)` 方法，签名完全不匹配。**调用方的 try-except 静默吞掉 ImportError，导致反突袭功能完全失效且无任何告警**。每次新人入群都会触发一次静默异常。

### 发现 3：v5.32.0 广告检测大升级是真实可工作的

7 个新模块（ai_advisor / ad_marketing_patterns / ad_profile_signals / edit_detector / global_blacklist / avatar_detector / ad_enforcement）全部 VERIFIED，有真实业务调用链路。`ad_enforcement.enforce_ad_user` 作为统一广告执法入口被 10+ 处调用。**这是本轮大改中唯一真正产生业务价值的批次。**

### 发现 4：v5.34.0 6 大模块代码完整但完全闲置

`sales_center` / `security_center` / `managed_groups` / `content_audit` / `new_member_analytics` / `membership` 6 个模块代码完整、可导入、有真实函数实现，但**没有任何业务代码调用**。`sales_repo` 的 13 个方法也无任何调用方。等同于死代码。需要接入主分发链路或 Dashboard API 才能产生价值。

### 发现 5：表名复数化错误 + 完全不存在的表

10 个模块查询不存在的表：5 个表名复数化错误（`channel_links` vs `channel_link` 等）+ 6 个完全不存在的表（`bot_registry` / `group_registry` / `premium_usage` / `image_records` / `global_ad_blacklist` / `group_join_log`）。即使导入修复，运行时全部走 except 静默返回空值，功能完全失效但用户无感知。

### 发现 6：bottom_button.py 用错 Telegram 库

`from telegram import InlineKeyboardMarkup` 是 `python-telegram-bot` 库的 API，项目实际用 `telebot` (pyTelegramBotAPI)。**这是一个开发者完全不熟悉项目技术栈的明显信号**，需要代码审查流程加固。

### 发现 7：modules/__init__.py `__all__` 不含任何新模块

`__all__` 列表共 81 个老模块名，**不包含任何 v5.34.0 / v5.35.0 新模块**。`from modules import *` 不会导入任何新模块。这进一步证明新模块从未被真正集成。

### 发现 8：时区铁律被 36 个新模块系统性违反

`core/database.py:34` `_CST = timezone(timedelta(hours=8))` 是项目铁律（修复v21.47 统一北京时间）。但 36 个 v5.35.0 新模块 50+ 处使用 `datetime.now()` 不带时区，与 DB 时间戳不对齐，跨时区部署会数据错乱。

### 发现 9：文档严重失真

- `project_snapshot.md:47` `job_count=50`，实测 BaseTask 子类 88 个，偏差 -38
- `version.py:9` `VERSION = "v5.33.1"`，`VERSION.md:5` `v5.35.0`，不一致
- `VERSION_HISTORY` 最新条目是 v5.33.1，未维护 v5.34.0 / v5.35.0
- `modules/__init__.py` `__all__` 81 个老模块，不含 50 个新模块

### 发现 10：测试覆盖严重不足

50 个新模块**无任何单元测试覆盖**。现有 305 passed / 7 skipped 全部针对老模块。**没有任何测试会在 36 个新模块 ImportError 时失败**，证明测试覆盖与代码变更脱节。建议至少补充每个新模块的 import 测试（`def test_import_<module>(): import modules.<module>`），这样 ImportError 会立即在 CI 中暴露。

---

## 10. 审计方法与证据

### 10.1 实测命令

```bash
# 1. 50 个新模块 import 测试
python -c "import importlib; modules = [...]; for m in modules: importlib.import_module(m)"
# 结果：13 OK + 37 FAIL

# 2. BaseTask 子类实测
python -c "import tasks; from tasks.base_task import BaseTask; ..."
# 结果：88 个

# 3. 全项目 grep 验证
# - from modules.<新模块> import 调用方搜索
# - 4 类错误导入模式覆盖范围
# - datetime.now() 时区问题
# - 无界缓存 / 阻塞调用 / 日志泄露

# 4. 真实文件:行号证据
# - core/settings.py:318,323,328（真实 API）
# - core/database.py:43,40（真实 API）
# - core/telebot_compat.py 全部 21 个函数导出
# - core/database.py:1036-1700 建表 SQL
# - core/handlers/member_handlers.py:56-59 调用方
# - core/message_dispatcher.py:868-871 调用方
# - modules/__init__.py:4-86 __all__ 列表
```

### 10.2 状态枚举说明

| 状态 | 含义 |
|---|---|
| VERIFIED | 代码完整 + 可导入 + 有真实业务调用 |
| IMPLEMENTED_CODE_ONLY | 代码完整 + 可导入 + 无业务调用（死代码） |
| PARTIAL | 部分实装，部分空壳 |
| MISSING | 完全缺失 |
| BROKEN | 导入失败或运行时崩溃 |
| BLOCKED | 因依赖 BROKEN 而阻塞 |
| OBSOLETE | 已废弃 |
| NOT_APPLICABLE | 不适用 |

### 10.3 未覆盖范围

- **运行时行为**：本次审计仅静态分析 + import 测试，未在真实 Telegram 群中验证新模块的运行时行为
- **Dashboard API**：未审查 Dashboard 是否有 API 端点调用新模块（实测 grep 未发现）
- **配置开关**：未审查 `config.json.example` 是否包含所有新模块的配置项（实测部分模块的 `XXX_CONFIG = config.get('XXX_CONFIG', {...})` 在导入失败时永远到不了）
- **Alembic 迁移**：未审查是否有 Alembic migration 对应新表（`core/database.py._init_tables()` 用 `CREATE TABLE IF NOT EXISTS`，无 migration）

---

## 11. 建议的修复优先级

### 立即修复（P0，阻断生产）

1. **回滚或重写 anti_raid.py**：恢复模块级 `def check_raid(bot, m, config, db)` 函数，或同步修改 2 处调用方
2. **批量修复 36 个新模块的 4 类错误导入**：替换为真实 API
3. **修复 10 个模块的表名错误**：统一为 `core/database.py` 建表的单数名，或补建缺失的表
4. **修复 bottom_button.py 的 Telegram 库错误**：改用 `telebot` API

### 短期修复（P1，恢复可用性）

5. **接入 v5.34.0 6 大模块到主分发链路或 Dashboard API**
6. **批量替换 `datetime.now()` 为 `datetime.now(_CST)`**
7. **实装 group_props 4 种空壳道具效果**
8. **接入 sales_repo 13 个方法到 sales_center 或 Dashboard**

### 中期修复（P2，提升可维护性）

9. **同步 version.py 到 v5.35.0**，补全 VERSION_HISTORY
10. **运行 `python scripts/doc_consistency.py` 重新统计 METRICS**
11. **为 50 个新模块补充至少 import 测试**
12. **修复 main.py content_types 冗余设计**

### 长期清理（P3）

13. **清理 auto_tasks 死代码**
14. **改善 except 块静默失败为日志告警**
15. **模块底部实例化改为懒加载工厂函数**

---

**审计完成。本报告所有判断均有文件:行号证据支撑，未使用"看起来没问题""应该能用"等模糊结论。**
