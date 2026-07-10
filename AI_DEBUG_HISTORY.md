<!-- 文档守则：本文件仅接受符合 AGENTS.md 文档路由表的内容；禁止追加对话流水账；超过行数上限须先归档再写入。 -->

# AI 调试病历（去重重写）

> 模板：**问题 | 根因 | 解法 | 预防**。完整历史（截至 2026-07-06）已归档至 `docs/archive/AI_DEBUG_HISTORY_archive_20260707.md`。
> 本文件只保留反复出现、有结构风险的暗病；新增条目按模板追加，超 300 行先归档。

## 反复暗病清单

### 1. 解封指令不生效（私聊路由吞掉）
- 问题：`/unban`、解封等指令在私聊场景下不触发完整解封链，用户权限未恢复；同名显示名盲选解封错人。
- 根因：解封入口注册过晚，被兜底分发器/私聊路由吞掉；显示名解析无候选去歧。
- 解法：`main.py` 在兜底分发前注册 `/unban` 专用 handler；解封前移 P5.6 早路由；同名显示名返回候选 ID 不盲选。
- 预防：新增解封类入口必须在 dispatcher 早路由注册，并回归私聊+群聊双场景。

### 2. 签到 / 打卡误封
- 问题：正常业务动作（签到、打卡、checkin）被广告资料层和延迟封禁累计误判为广告。
- 根因：业务动作未从广告检测入口排除。
- 解法：签到/打卡/checkin 不进入广告资料层与延迟封禁累计；解封统一清理 `blacklist`/`global_blacklist`/`mute_records`/`ad_suspicious_users`。
- 预防：新增"正常业务动作"清单需在广告检测前显式排除。

### 3. 广告资料层（Bio / emoji）误封
- 问题：群管理员 / 白名单用户被资料层检测误封。
- 根因：免检前置（白名单/管理员）排在 Bio/emoji 检测之后。
- 解法：白名单/群管理员免检前移到 Bio/emoji 检测之前；广告处置通知加"解封"按钮。
- 预防：任何检测层新增前，确认免检前置已在最前。

### 4. AI 失败兜底尴尬
- 问题：AI 调用失败时返回拟人化尴尬文案，体验差且无意义。
- 根因：兜底文案写死且过度拟人。
- 解法：未知/普通/特殊模式全失败直接静默；转化/联系模式只给固定入口。
- 预防：AI 失败路径默认静默，禁止新增拟人兜底文案。

### 5. 新闻 / 问候消息超时不删
- 问题：定时播报 / 问候消息发出后未清理，长期堆积。
- 根因：发送与清理链未同步接入。
- 解法：播报 / 问候发送须接入统一清理（burn_orphan）链路。
- 预防：新增播报 / 消息能力必须显式接入 dispatcher 与 burn_orphan。

### 6. burn_orphan 漏清 channel_tracking
- 问题：孤儿清理漏清 `channel_tracking` 表，脏数据累积。
- 根因：清理任务未覆盖该表。
- 解法：清理任务补充 `channel_tracking` 清理。
- 预防：新增数据表若会产生孤儿记录，必须同步接入 burn_orphan。

## 结构性风险（推断，附依据）
- 历史误封集中在"检测链与入口/清理链不一致"类问题（见上 1–5）。推断系统存在"新增能力未同步接入统一入口/清理"的结构性风险，新功能易重蹈覆辙。应对：所有新增检测/播报必须显式接入 dispatcher 与 burn_orphan，并加回归测试固化（依据：AI_DEBUG_HISTORY 多次同类 hotfix）。

### 7. Dashboard worker timeout
- 问题：生产 `mory-dashboard` 在 2026-07-07 08:31–08:33 出现连续 Gunicorn `WORKER TIMEOUT` / `SIGKILL`，服务自恢复但后台存在慢请求拖死 worker 的隐患。
- 根因：Dashboard systemd 使用 Gunicorn 默认 30 秒 timeout，后台页面包含数据库、SSH、审计等慢操作，2 worker 配置下容易被长请求占满。
- 解法：`config/mory-dashboard.service` 增加 `--timeout 120 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100`，部署后重启 Dashboard 并复核 health / journal。
- 预防：Dashboard 新增慢接口必须设置应用层 timeout，生产巡检除 10 分钟错误外要抽查最近 1 小时 Dashboard journal。

### 8. 同机浏览器容器拖垮 Mory
- 问题：2026-07-08 生产机出现“各种报错不能用”，`mory-assistant`/`mory-dashboard` 表面 active，但整机 swap 接近打满，内核 OOM 杀过 `headless_shell`，Dashboard 出现 `WORKER TIMEOUT` / `SIGKILL`。
- 根因：同机 `dreamina-bridge` 容器内 Playwright/Chromium 进程占用约 1.8GiB 内存并触发 OOM，拖慢 systemd、调度任务和 Dashboard worker。
- 解法：重启 `dreamina-bridge` 释放内存，并用 `docker update --memory 1536m --memory-swap 1792m dreamina-bridge` 限制容器内存；同时修复 `conversion_events` 重复 `ALTER TABLE ADD COLUMN` 的日志噪声。
- 预防：生产巡检不能只看 Mory 双服务 active，必须同时看 `free -m`、`docker stats`、内核 OOM 日志和最近 1 小时 Dashboard journal。
