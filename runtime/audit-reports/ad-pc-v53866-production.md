# v5.38.66 同城 PC 广告漏判生产闭环

## 结论

`verified`。生产在 2026-08-20 00:58、03:33、06:39 收到同一 UID 的三条相同广告，但旧规则正文、显示名和 Bio 均为 0 分；一小时重复窗口也未覆盖 2.5～3 小时的发送间隔。v5.38.66 已补齐显示名和正文两道独立直证并精确发布。

## 四层证据

- `truth_surface`：生产 VPS `/home/ubuntu/mory_assistant`、systemd 双服务、生产 `mory.db` 与 Telegram 群 `-1003004701688`。
- `success_receipt`：正文“同城PC…平台担保交易…”生产评分 4，显示名“同程嫖娼”评分 3；UID `6070826211` 保持 `kicked`，三条消息均由 Telegram 二次删除返回 `message not found`，数据库均为 `is_ad=1/deleted=1`。
- `persistence_check`：处置后以独立 SQLite 连接读回本地黑名单、全局黑名单、禁言记录均为 1；重新查询 Telegram 仍为 `kicked`。部署后重连读回 v5.38.66、双服务和三份文件哈希。
- `derived_records`：`version.py`、`VERSION.md`、`CHANGELOG.md`、`README.md`、`project_snapshot.md`、`AI_DEBUG_HISTORY.md`、`docs/technical/ad-detection.md`。

## 根因与修复

- 旧成人词库没有将 `PC` 与“同城、人工审核/平台担保交易、拒绝被骗/PC无忧”作为同条组合语义，正文得分 0。
- 旧资料名规则没有覆盖“同程/同城+嫖娼”，入群和每次发言资料复审均放行。
- 重复刷屏只清理一小时内三次；本例三次跨约 5 小时 40 分，未触发行为清理。行为本身仍不作为广告定罪依据。
- 新规则要求多锚点同时出现；普通电脑维修、装机、作业审核和反诈讨论 4/4 放行。
- 账号在修复前已被外部管理员手工 `kicked`。统一处置保持该更严格状态，不调用 restrict 改写成员状态，同时补齐持久治理记录。

## 验证与发布

- 提交：`6825e29fd596ac068fc2cdcdf53276c51196fb82`。
- 本地：目标链 `367 passed`；全仓 `1195 passed`；compileall、DB 委托 208/208、配置同步、文档一致性和干净工作树 deploy-ready 门禁通过。
- 生产：`modules/ad_patterns_encoded.py`、`modules/ad_enforcement.py`、`version.py` 哈希与干净提交一致；PID `1613495/1613496`，双 active/running，NRestarts=0，HTTP 200，启动窗口无未解释 ERROR/CRITICAL/Traceback。
- 数据库：`PRAGMA integrity_check=ok`；`blacklist=1`、`global_blacklist=1`、`mute_records=1`、`ad_suspicious_users=0`。
- 回滚包：`/home/ubuntu/mory_assistant/backups/ad_pc_v53866_20260820_084404.tar.gz`，SHA-256 `4b1b9253ef6c82c3cc1dcf9370cabf0afb4712102fe52b00546fa438681c8ae3`。
- 回滚命令：`cd /home/ubuntu/mory_assistant && tar -xzf /home/ubuntu/mory_assistant/backups/ad_pc_v53866_20260820_084404.tar.gz && sudo systemctl restart mory-assistant mory-dashboard`。

## 边界

三条消息在统一处置时 Telegram 已返回不存在，因此不能归因于本次机器人实际删除；本次确认的是它们当前均不可见，并已补齐逐条广告/删除审计状态。后续同类消息会在首条正文评分 4 后进入统一处置。
