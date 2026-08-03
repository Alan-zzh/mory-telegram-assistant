# 广告治理执行链热修复验收

日期：2026-08-03

## 根因

- 生产两条原文 `微信代收 一天一W` 已由 Bio 资料层命中，并完成永久禁言与双黑名单。
- Bot 具备删消息权限，但生产 `ENABLE_MESSAGE_DELETION=false`；旧统一治理入口错误复用普通消息删除总闸，实际从未调用 Telegram 删除，回执为 `deleted=0`。

## 修复不变量

- 已确认广告的当前消息删除不受普通自动删除总闸影响。
- 账号证据与逐条消息证据分离；Bio、头像、昵称、黑名单和累计账号评分不得伪造 `message_snapshots.is_ad`。
- 历史清理只读取 `is_ad=1`，不得按账号批删正常历史。
- 头像只作辅助维度，不得单信号封禁。
- `代收/代付` 是歧义业务词，不单独定罪，也不与费率、通道、有量等普通业务词自动组合定罪；截图里的“一天一W”由独立收益强证据封禁。
- Telegram 删除使用 `deleted/already_absent/failed` 三态；禁言或双黑名单未闭合时保留追踪重试。

## 本地门禁

- 精确发布提交 `35422c2` 整仓：`835 passed, 26 skipped`。
- 广告核心与旧关键词回归：`250 passed`。
- DB 委托：`199` 个方法，无缺失、无孤儿。
- 文档数字一致性：通过。
- 独立误封审查经过多轮反例否决后最终 `GO`，P0/P1 均为 0；有风险的代收付扩展已撤回，未进入生产。

## 生产验收

- 发布提交：基础执行链 `7dafbb6`，最终保守规则 `35422c2`；生产继续运行 `v5.38.15`，现有广播升级未被覆盖。
- 文件与数据库备份：
  - `/home/ubuntu/mory_assistant/backups/ad_hotfix_7dafbb6_20260803_114855`
  - `/home/ubuntu/mory_assistant/backups/ad_hotfix_35422c2_20260803_121500`
- 最终服务：`mory-assistant` PID `2597950`、`mory-dashboard` PID `2597951`，均 `active/running/enabled`，`NRestarts=0`。
- Health：`localhost:6616/api/health` 返回 `HTTP 200` 与 `{"status":"ok"}`。
- 最终规则文件 SHA256：`dc4f16afbdb67a295c680de61184a5b05809aa187e820706a656e5aea71f14cb`；其余 11 个执行链文件与首次部署期望哈希一致。
- 生产业务探针：5 条高置信正例全部 `is_ad=true/score=3`，包括截图原文、数字/字母拆写跑分/刷单、拆写日收益和拆写微信；11 条正常/歧义反例全部 `is_ad=false/score=0`。
- 普通删除开关仍为 `false`；隔离假 Bot 探针确认逐条确证广告仍执行删除、广告标记和删除标记，不受该开关阻断。
- 截图账号真实闭环：
  - `guanjing`：UID `8522335888`，消息 `63408` 已不存在；`message_snapshots=(is_ad=1, deleted=1)`。
  - `zangu`：UID `8866062662`，消息 `63409` 已不存在；`message_snapshots=(is_ad=1, deleted=1)`。
  - 两账号均保持 `blacklist=1`、`global_blacklist=1`、永久 `mute_records=1`，可疑追踪残留为 0；Telegram 当前状态为 `kicked`（部署前既有外部状态，本次代码未执行踢人）。
- 当前新进程日志：Bot 无 ERROR/CRITICAL/Traceback，Dashboard 无异常；停旧 Dashboard 时出现两条 gevent `greenlet is being finalized` 解释器退出噪声，随后 systemd 正常 `Deactivated successfully`，不影响新进程和健康检查。
