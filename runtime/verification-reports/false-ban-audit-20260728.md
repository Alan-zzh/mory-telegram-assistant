# 生产误封与恢复专项审计

日期：2026-07-28
生产版本：v5.38.6

## 验收合同

- `truth_surface`：生产 `mory.db`、Telegram `getChatMember/getChat`、`mory-assistant` journal。
- `success_receipt`：每个对象的消息/资料证据、Telegram 当前权限，以及四类持久记录。
- `persistence_check`：生产写入后关闭并重新连接 SQLite，再查询同一用户四类记录。
- `derived_records`：`AGENTS.md`、`CHANGELOG.md`、`AI_DEBUG_HISTORY.md`、`project_snapshot.md` 与本报告。

## 审计范围与结论

1. 逐个核验 2026-07-28 新增的 8 个全局黑名单对象。
2. 逐个核验当前 v5.38.6 重启后成员扫描处置的 10 个对象。
3. 18 个对象均有可复核的明确证据，包括外链引流、日收益招募、跑分洗钱、彩票交易、色情招揽；Telegram 资料/Bio、消息快照与封禁理由相互印证。
4. 本范围未发现误封，因此没有对任何真实广告账号执行恢复。

## “怎么订阅”用户

- Telegram 当前状态：`left`，不是 `restricted` 或 `kicked`。
- `blacklist=0`
- `global_blacklist=0`
- `mute_records=0`
- 写前仅有一条过期 `ad_suspicious_users` 记录，`score=0`，正文为“怎么订阅”。

该过期正常追踪已精确删除。写入前使用 SQLite online backup 保存：

```text
/home/ubuntu/mory_assistant/backups/false_positive_cleanup_20260728_214140/mory.db
```

关闭并重新连接生产数据库后再次查询：

```json
{
  "blacklist": 0,
  "global_blacklist": 0,
  "mute_records": 0,
  "ad_suspicious_users": 0
}
```

## 防复发边界

- 回复、人设、预览、成交文案修改不得授权删除、禁言或黑名单。
- 行为追踪不等于广告证据；治理动作必须走独立逐条证据门禁。
- 确认误封必须恢复 Telegram 权限，并同时清理四项持久记录，重新查询验证。
- 已删除 Telegram 消息无法恢复时必须如实说明。

## 共享工作区边界

审计期间工作区另有未提交的 v5.38.7 广告变体修改，涉及 `modules/ad_detector.py` 与 `modules/ad_patterns_encoded.py`，且其定向测试当时存在一条全角加号预期失败。本轮未提交、未部署、未覆盖该修改。
