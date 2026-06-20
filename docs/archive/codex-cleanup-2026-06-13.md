# Codex 整理收口记录（2026-06-13）

这份文档只记这次“清旧、收口、让配置和实际行为一致”的结果，给后面任何 AI 或人工接手时快速对齐。

## 1. 已清理

- 已移除历史测试堆放目录与缓存：
  - `tests/archive`
  - `tests/_archive`
  - `.pytest_cache`
  - 各层 `__pycache__/`
- `scripts/README.md` 和 `project_snapshot.md` 已改成只描述当前仍在用的脚本，不再把旧调试脚本当现役资产。
- `tests/README.md` 已改口径：以后不再长期保留“历史测试垃圾堆”，有价值的验证要么进 `tests/unit|integration`，要么进 `scripts/verify_*`。

## 2. 播报链路收口

- 问候播报统一读 `GREETING_CONFIG`：
  - `morning_enabled` / `morning_time`
  - `afternoon_enabled` / `afternoon_time`
  - `evening_enabled` / `evening_time`
- 新闻播报统一读 `NEWS_BROADCAST_CONFIG`：
  - `enabled`
  - `preferred_source`
  - `morning_time`
  - `afternoon_time`
  - `evening_time`
- 旧键 `AUTO_GREETING` / `AUTO_GOODNIGHT` / `AUTO_NEWS` / `GREETING_HOUR` / `GOODNIGHT_HOUR` / `NEWS_HOUR_*` 仍兼容，但现在属于过渡层，不应再继续扩写新逻辑。

## 3. 新闻策略调整

- 新闻播报默认改成 `real_first`：
  - 先走 `fetch_real_news()`
  - 不够用时再降级到 `TrendRadar`
- 文案要求已经改成：
  - 每条先把事件讲清楚
  - 再补一句进展/影响/后续方向
  - 不要主持腔
  - 不要瞎分析
  - 只给轻量观察，不替用户下裁判

## 4. 后台面板收口

- Telegram 按钮面板 `modules/settings_panel.py` 已改成展示真实配置：
  - 早安/午安/晚安问候
  - 新闻来源优先级
  - 私聊中继
- Dashboard 设置与配置页已同步：
  - 提示文案改成“5到8秒内自动生效”
  - 配置分组改成按当前真实运行项展示
  - 不再优先突出那批已经失真的旧广播时间键
- `dashboard/api/settings_api.py` 的历史双份接口已收口：
  - `/settings/cleanservice` 与 `/settings/clean-service`
  - `/settings/visual-dashboard` 与 `/settings/dashboard`
  - `/settings/blindbox` 与 `/settings/blind-box`
  - `/settings/luckywheel` 与 `/settings/lucky-wheel`
  - `/settings/dailyquest` 与 `/settings/daily-quest`
  - `/settings/achievement` 与 `/settings/achievements`
  - 现状是“旧地址继续兼容，但后端只保留一份真实实现”，避免同一功能两套逻辑越改越偏。
- Dashboard 设置前端这批“假字段”已清理：
  - 问候配置不再展示未接线的自定义文案，只保留真实开关和 `HH:MM` 时间。
  - 新闻配置不再展示未接线的“自定义新闻源列表”，只保留开关、真实源优先策略、三段时间。
  - 广告检测不再假装支持后台自定义关键词，词库仍由专门规则文件维护，面板只保留真实开关和灵敏度。
  - CAS 面板不再展示未落地的“自动封禁/处理方式”，改成真实可用的 `CAS` / `SpamWatch` 开关与 Token。
  - 反刷屏面板改成一次保存 `SPAM_LIMIT` 和 `ANTIFLOOD_CONFIG`，避免两套配置继续分裂。
  - 首页统计卡片 `消息总量` 已改成 `消息总量（群+私聊）`，避免把群消息与私聊合计误读成单一群数据。
- Dashboard 设置接口已补“空配置不崩”兜底：
  - `TIP_CONFIG`
  - `DAILY_QUEST_CONFIG`
  - `ACHIEVEMENT_CONFIG`
  - `POINTS_DECAY`
  - 即使这些键当前是 `null`，面板保存也会自动补成合法字典，不再一点击就报错。
- 新增 `core/config_compat.py`：
  - Dashboard 读写配置时先做一次规范化
  - Bot 内联按钮面板读写配置时也走同一层规范化
  - 自动对齐 `enable/enabled`、`window/window_seconds`、问候/新闻旧兼容键
  - 自动清理“说明文字伪装成配置键”的历史脏数据
  - 自动同步 `BLIND_BOX_CONFIG.cost -> BLIND_BOX_COST`
  - 自动同步 `LUCKY_WHEEL_CONFIG.cost -> LUCKY_WHEEL_COST`
- 修正 `core/deploy_utils.safe_merge_config()`：
  - 仍然保护密钥、管理员、群组等敏感字段
  - 其他业务配置默认以本地整理后的配置为准
  - 避免部署时线上旧值把 `RELAY_MODE_ENABLED`、播报配置、价格配置又覆盖回去
- 修正 `core.bot_initializer.save_config()`：
  - 如果磁盘上的 `config.json` 比当前进程加载时更新，则跳过保存
  - 避免部署/热更新期间旧进程停机时把新配置重新写回旧值

## 5. 私聊中继现状

- `RELAY_MODE_ENABLED=true` 时：
  - 用户私聊文本会立刻转到管理员
  - 用户私聊图片会立刻转到管理员
  - 用户私聊语音会立刻转到管理员
  - 管理员直接回复那条转发消息，Bot 会把回复回送给原用户
- 这条链路依赖 `relay_sessions` 表做消息映射。

## 6. 这次顺手关掉的旧功能

- `PUZZLE_ENABLED = false`
- `SIGNUP_ENABLED = false`
- `ANTI_REVOKE = false`
- `BURN_AFTER = false`
- `RECOVER_ENABLED = false`

原因：
- 这几项都是旧口径残留开关，和当前主配置结构不是一套，继续开着只会制造“后台看到一套、代码又跑另一套”的假象。

## 6.1 日报口径调整

- 每日群报、频道报已经改成：
  - 先列 `数据来源`
  - 再列 `原始数据`
  - 最后才给 `数据分析`
- 不再使用“综合健康度 80/100”这类主观打分口径，避免系统替人下裁判。
- 群日报的“消息总量”已改成真实群发言数据：
  - 不再误读 `channel_tracking` 里的频道发帖数
  - 现在直接统计 `speech_daily` 的群内发言量
- 群日报的分析项已改成更可复核的口径：
  - `活跃覆盖`
  - `沉默比例`
  - `人均发言`
  - `离群/入群比`
- 频道日报移除了“内容节奏”这类带判断色彩的话术，改成 `单帖均阅` 这类纯数据指标。
- 群周报 / 群月报已同步收口为同一风格：
  - 增加 `数据来源`
  - 原始数据直接展示成员变化和群内发言总量
  - 分析项只保留 `活跃覆盖`、`人均发言`、`离群/入群比`
- 频道周报 / 频道月报已同步去掉空泛判断，补成：
  - `数据来源`
  - 各频道成员变化
  - 发帖 / 浏览 / 转发原始数据
  - `周总发帖/月总发帖` 与 `单帖均阅`

## 7. 剩余扫尾建议

- 如果后面要继续瘦身，优先审查 FAQ/FAQ 自动回复这一整组功能是否要继续保留在主配置里。
- 如果要再收一轮体验层，可以直接在本地打开 Dashboard 做一次可视化点点验证，确认所有提示文案和默认值都符合当前口径。
- 如果后续新增播报或资料面板，继续沿用“数据来源 → 原始数据 → 数据分析”的顺序，避免又回到主持腔或打分口径。

## 8. 本次线上验收结果

- 已完成真实部署与线上核验：
  - `mory-assistant` 服务 `active`
  - `mory-dashboard` 服务 `active`
  - `http://localhost:6616/api/health` 返回 `200`
- 已确认 VPS 运行配置关键项生效：
  - `RELAY_MODE_ENABLED = true`
  - `NEWS_BROADCAST_CONFIG.preferred_source = real_first`
  - `BLIND_BOX_COST = 35`
  - `BLIND_BOX_CONFIG.cost = 35`
- 已确认历史假键不再残留到线上运行配置：
  - “设置面板完全体 新增配置项（v5.0.0）” 不再存在
- 本地验证已补充：
  - `python -m py_compile dashboard/api/settings_api.py tests/unit/test_settings_api_aliases.py`
  - `python -m pytest tests/unit/test_settings_api_aliases.py tests/unit/test_config_compat.py tests/unit/test_deploy_utils.py tests/unit/test_relay_handler.py tests/unit/test_auto_tasks_greeting_config.py -q`
  - `python -m pytest tests/unit/test_settings_api_smoke.py tests/unit/test_settings_api_aliases.py tests/unit/test_auto_tasks_greeting_config.py tests/unit/test_config_compat.py tests/unit/test_deploy_utils.py tests/unit/test_relay_handler.py -q`
  - 本轮继续补充后测试为 `26 passed`
  - `test_settings_api_smoke.py` 已覆盖 `64` 个后台设置 GET 接口，确认设置页不会打开即报错。
- 线上 Dashboard 已做登录后页面级核验：
  - `LOGIN_OK=True`
  - 页面包含 `真实源优先`
  - 页面包含 `私聊中继`
  - 页面包含 `问候配置`
  - 页面包含 `新闻配置`
  - 页面包含 `SpamWatch Token`
  - 页面包含 `消息总量（群+私聊）`
- 本轮代码更新后已再次真实部署，线上校验继续通过：
  - `mory-assistant` = `active`
  - `mory-dashboard` = `active`
  - `curl http://localhost:6616/api/health` = `200`
