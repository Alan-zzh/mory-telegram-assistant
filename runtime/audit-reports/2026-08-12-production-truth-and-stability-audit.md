# Mory 小助理生产真相与稳定性审计（2026-08-12）

## 审计边界与证据面

- 本地基线：`cf3e2a2`、v5.38.36、工作树初始干净；Python 3.12.10。
- 生产只读核验：systemd、进程/cgroup、`journalctl`、真实 SQLite、Dashboard API、文件 hash/权限、root cron。
- 生产服务在审计时均 active，`/api/health` 为 HTTP 200；健康端点当时不返回版本，因此版本由远端 `version.py` 与关键文件 SHA256 交叉核验为 v5.38.36。
- 本报告区分“审计时生产事实”“本地已修复候选”“部署后证据”；本地测试不冒充生产生效。

## 核心结论

审计不是“整体全绿”。服务存活、数据库完整，但发现可利用的自然语言自助解封路径、root 执行链权限问题、调度与健康面板假绿、生命周期竞态、场景开关假生效、Dashboard 异常路径二次崩溃、AI 头像返回结构不兼容，以及已无入口的新闻/统计幽灵能力。

## 已确认问题与处置

| 级别 | 问题 | 生产/代码证据 | 本地处置 |
|---|---|---|---|
| P0 | 普通用户可借私聊“我被禁言”进入自然反馈自助恢复路径 | 临时禁言不写广告 blacklist，故可绕过前置黑名单拦截；生产自 8/9 未发现实际调用，但路径可达 | 自述只提交管理员审核，不再写四表或恢复权限；管理员 `/unban` 与回调保留 |
| P0 | ubuntu 可写脚本被 root cron 每 2 分钟执行；unit 也是 ubuntu:ubuntu 664 | `/etc/systemd/system/mory-*.service` 与 `scripts/vps_watchdog.py` 权限实测；ubuntu 同时拥有 NOPASSWD ALL | 部署器用 `install root:root 0644` 安装 unit；root cron 改执行 `/usr/local/lib/mory-assistant/` 下 root:root 0755 副本 |
| P0 | `.env`、`config.json` 对其他本机用户可读 | 生产权限均为 644，未读取或暴露任何值 | 部署时收紧为 0600；`mory.db` 同步收紧为 0600 |
| P1 | 自助解封/管理员解封可假报成功 | 原实现只以删除动作未抛异常作为 200，未核验 Telegram 权限及四项持久态 | 四表清理采用事务；完成后读回 blacklist/global/mute/suspicious 与 Bot API 成员权限，全部确认才返回 200/“已解封” |
| P1 | 广告处置多表分次提交，可能出现半黑名单 | mute/global/local 各自 commit | mute/global/local 改为单 SQLite 事务，失败 rollback、告警且返回 `enforcement_incomplete` |
| P1 | 健康与调度面板假绿 | `scheduler_metrics` 119 行是历史而非当前注册；累计失败 30；事务任务 7 日 69 成功/11 失败/1 中止；旧接口仍可显示 100% | 明确区分当前注册表、历史指标、事务任务覆盖；未知项返回 unknown/null，不再用空数据算 100%；root health 缺失/陈旧心跳返回 503 |
| P1 | 禁用任务仍触发 CRITICAL | 生产 00:00 cart recovery、04:00 daily backup 两条 CRITICAL；对应配置明确关闭 | 监控遵循两个功能开关，禁用任务不再误报 |
| P1 | AI 头像视觉复核不兼容 list 响应 | 生产 5 次 `'list' object has no attribute 'get'`；本地 NSFW/OCR 仍工作，但图像广告/QR 证据可能漏判 | 统一抽取字符串与多段 text block；增加 list 响应回归 |
| P1 | 双 ResourceManager 导致锁域分裂 | 后台任务与 BotContext 各建一套资源锁 | 初始化并注入唯一 RM，重复启动复用同一实例 |
| P1 | 关停时 job 未 drain 即关闭 SQLite | `scheduler.shutdown(wait=False)` 后直接 `db.close()` | 所有普通/动态/场景 job 经统一入口计数；停止接收新任务、有界 drain 后才关 DB |
| P1 | 配置重载失败仍删除 reload flag | `finally unlink()` 导致更新永久丢失，watcher 可重复启动 | 仅完整成功后消费 flag；失败保留重试；watcher 单例且可停止 |
| P1 | ColdGroup/NightHint UI 开关假生效 | 启动时禁用不会注册；热重载只刷新 `tasks/` | 场景触发器进入统一刷新，启用 add/replace、禁用 remove，失败触发配置回滚 |
| P1 | Dashboard 异常路径与播报 PUT 二次崩溃 | `extra_fields` 局部变量；多个模块 logger/logging 未定义 | 提取共享常量；统一 logger/import；新增异常分支回归 |
| P1 | 定点播报锁释放可静默失败且跨午夜删错日期 | release 只删“今天”且忽略 False | 按 task key 释放原 claim；False 升级为 CRITICAL 并保留原失败 |
| P2 | 新闻设置、stats report 与 router usage 独立库是幽灵能力 | 无真实运行入口；stats report 启用即吞错返回空；router usage 已长期无写入但监控仍读取 | 删除模块/路由/独立库代码与文档；安全合并时清生产遗留键；监控统一读取真实 `llm_cost_logs` |
| P2 | 文档与代码数量/能力承诺失真 | README 目录数量、CTA 数量、1017 行能力矩阵与代码不符 | 以机械统计重写 README/snapshot/能力矩阵；版本代码只保留 SSOT，历史迁入 CHANGELOG |
| P2 | 全仓异常路径存在未定义 logger | F821 初扫仍有 logging cleanup、VPS config、cleanup script 5 处 | 补真实 logger/明确输出；全仓 F821 归零 |

## 生产运行事实（审计时）

- `mory-assistant` 与 `mory-dashboard` 自 2026-08-09 23:01 起 active，NRestarts=0；无重复 main/start.sh/nohup 进程。
- DB：`PRAGMA integrity_check=ok`、`foreign_key_check=[]`、WAL 模式；主库约 4.9 MB，WAL 约 4.0 MB。
- 当前 boot journal 共 24,181 行：INFO 24,156、WARNING 23、CRITICAL 2、ERROR 0。两条 CRITICAL 均为已禁用任务的误报。
- Dashboard 旧 worker 回收时出现 2 次 `greenlet is being finalized`，随后新 worker 正常启动、服务健康，systemd 本身未重启；作为 worker 回收噪声继续观察，不把它误报成全服务事故。
- `fault_alerts.log` 记录 7 月多次 heartbeat timeout 自动重启及 8 月 8 日 greeting lock 残留，证明“当前 NRestarts=0”不能覆盖历史复发风险。
- 351 个 zombie 全部属于独立 Docker 容器内 Chromium 的 root node 父进程，不属于 Mory cgroup；只构成共享主机负载/进程表压力，本次不越权重启或清理。
- 生产配置包含本地运行配置未覆盖的键，但与 `config.json.example` 的能力集合更接近；部署继续采用远端保护字段 + 本地权威字段安全合并，不覆盖数据库和凭据。

## 本地验证与发布门禁

- 初始基线：965 unit 通过。
- 修复定向：广告治理 44 通过；生命周期/健康/触发器 37 通过；Dashboard/部署/AI/播报等定向回归均已通过。
- `verify_db_methods.py`：199 个委托方法通过。
- `check_config_sync.py`：example 与 Dashboard 白名单双向一致。
- `doc_consistency.py`：136 modules、80 core、33 `_job_`、173 tables、163 routes、9 dispatcher、10 router mappings 全一致。
- 全仓 flake8 F821：0。
- 全仓 unit：`1005 passed in 20.33s`；compileall 通过。
- CI flake8 通过；mypy 4 个目标文件通过；interrogate `80.2%`，超过 80% 门槛。
- `check_deploy_ready.py` 5/5 通过，工作树提交时干净；发布提交 `9ad37c0`。

## 不属于本次代码发布可闭环的风险

1. `ubuntu` 仍有 `NOPASSWD: ALL`，这是主机 sudoers 的高风险外部边界；本次已消除 Mory root cron 对 ubuntu 可写脚本的依赖，但不擅自改主机管理员授权。
2. 独立 Docker 容器的 Chromium zombie 与 Mory 无直接所有权证据，需要容器所有者单独治理。
3. Dashboard gunicorn/gevent worker 回收噪声需在发布后观察窗口复核；没有证据时不把健康 worker 的一次回收等同于服务失败。

## 发布状态

当前：**v5.38.37 已部署并独立读回验收**。

- 部署器完成 406/406 个生产文件上传、安全配置合并、死代码删除、权限加固及双服务重启；远端 406 个文件 SHA256 与本地逐一比对，`mismatches=0`。
- `mory-assistant` PID 3822510、`mory-dashboard` PID 3822511 于 2026-08-12 23:02:38 CST 启动，均 `active/running`、`NRestarts=0`；`/api/health` HTTP 200，启动日志明确为 v5.38.37。
- `mory-*.service` 均为 `root:root 0644`；root cron 执行 `/usr/local/lib/mory-assistant/vps_watchdog.py`，该文件为 `root:root 0755`；`.env`、`config.json`、`mory.db` 均为 0600。
- `stats_report.py`、`router_database.py` 在 VPS 已不存在；生产配置遗留 NEWS/空报表键为 0，私有 staging 无残留文件。
- SQLite 保持 WAL，`integrity_check=ok`、`foreign_key_check=[]`；新进程启动后的分钟级任务持续成功，无新 CRITICAL/ERROR/AI 头像解析异常。
- Dashboard 旧 gevent worker 在切换时仍记录一次 `greenlet is being finalized`，发生于旧 PID 3701665；新 master/worker 正常启动且 health 200。该退出噪声不计为业务故障，但保留为上游运行时观察项。
