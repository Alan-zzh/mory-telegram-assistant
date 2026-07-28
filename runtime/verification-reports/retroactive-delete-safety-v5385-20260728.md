# v5.38.5 启动追溯防误删验收

日期：2026-07-28  
提交：`8cc8edd`  
生产备份：`/home/ubuntu/mory_assistant/backups/deploy_v5385_20260728_205602`

## 事故结论

生产 `mory-assistant` 在 v5.38.3 部署重启后，于 20:04:23 启动广告追溯扫描；群组受保护导致扫描切到数据库模式。20:04:43 日志明确记录：

```text
[AD] 🗑️ 追溯删除(追踪): msg_id=61890 | 怎么订阅
```

生产数据库只读反查：

```json
{
  "chat_id": -1003004701688,
  "msg_id": 61890,
  "user_id": 8766496147,
  "text": "怎么订阅",
  "is_ad": 0,
  "deleted": 0,
  "blacklist": 0,
  "global_blacklist": 0
}
```

旧路径未更新 `message_snapshots.deleted`，但 Telegram 日志和群内删除提示已经证明原消息实际被删。Telegram Bot API 不支持恢复已删除的原消息。

## 假设排查

1. 回复优化函数直接删除消息：排除。精确日志调用者为广告模块的启动追溯链。
2. 原消息确属广告或用户已在黑名单：排除。单条分数和 `is_ad` 均为 0，两个黑名单均为 0。
3. 数据库模式把“被行为追踪”误当“已确认广告”：确认。旧实现遍历 `ad_suspicious_users.messages` 后无条件计为广告并删除；无追踪记录时还会按消息 ID 范围盲删。

## 修复

- 追踪消息逐条持久化 `is_ad`。
- 数据库追溯只读取当前 30 分钟窗口。
- 只有显式 `is_ad=true` 或单条评分达到阈值的记录可进入删除链。
- 普通追踪记录记录为 `unconfirmed_ad_evidence` 并跳过。
- 无追踪证据时 fail-close，不再执行消息 ID 范围删除。
- forward 中途切换数据库模式时继续传递删除开关配置。
- 启动扫描从 `message_snapshots` 只读获取末条消息 ID，不再向群发送并删除“.”探针。
- 追溯删除成功后同步写审计删除标记。

## 验收证据

- 本地完整回归：`519 passed / 7 skipped`。
- DB 方法门禁：`190` 个委托方法，无缺失、无孤儿。
- 文档门禁：`7/7`。
- 生产发布：暂存与上线文件均 `13/13` 哈希一致。
- 生产服务：双服务 `active + enabled`，health `v5.38.5`，`NRestarts=0`。
- 当前进程：高严重日志 `0`，追溯删除日志 `0`。
- 远端专项回归：`5 passed`。
- 生产代码无 Telegram 写入探针：
  - `怎么订阅 / score=0 / is_ad=false`：`deleted_calls=[]`、`ads_found=0`、`deleted=0`、`skipped=1`。
  - `加我微信日赚千元 / is_ad=true`：删除调用 `1`、`ads_found=1`、`deleted=1`。

结论：误删根因已在真实生产代码和重启运行态闭环；明确广告删除能力保留。不可逆遗留只有原 `msg_id=61890` 无法由 Bot API 恢复。
