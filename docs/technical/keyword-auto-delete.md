# 群消息关键词延迟删除

## 目标与边界

`KEYWORD_AUTO_DELETE_CONFIG` 用于清理由群成员发出的、可明确枚举的无意义群消息。命中后只登记延迟删除并停止 Mory 后续的积分、意图和 AI 路由；不会禁言、拉黑、踢人或把该消息标成广告。

私聊、Bot 消息、频道身份消息和未精确命中的普通聊天一律放行。广告与黑名单检查仍先执行，避免关键词清理旁路原有安全治理。

## 配置

```json
{
  "KEYWORD_AUTO_DELETE_CONFIG": {
    "enabled": false,
    "keywords": ["/me@afoolGroupBot"],
    "delay_seconds": 300,
    "match_mode": "exact",
    "case_sensitive": false,
    "max_attempts": 5
  }
}
```

- 新功能默认关闭；生产开启前同时确认 `ENABLE_MESSAGE_DELETION=true`。
- `match_mode` 支持 `exact`、`prefix`、`contains`，默认和推荐值为 `exact`。宽泛的前缀或包含规则必须补正常反例后再启用。
- 延迟限制为 30 秒至 24 小时；关键词最多 50 个，每个最多 100 字符。
- Dashboard → 配置 → 安全治理 → 关键词延迟删，可查看当前状态并编辑 JSON；保存后走现有配置热重载。

## 执行与恢复

1. `core/message_dispatcher.py` 在广告检测之后、积分/意图/AI 之前调用 `modules/keyword_auto_delete.py`。
2. 命中消息写入 `message_snapshots` 的 `auto_delete_*` 状态，并启动进程内定时器准点删除。
3. `KeywordMessageAutoDeleteTask` 每分钟扫描到期待删状态；进程在 5 分钟窗口内重启时由该任务补删。
4. Telegram 返回真实删除成功或消息已不存在时记为 `deleted`；临时错误保留 `pending` 并递增尝试次数，达到上限明确记为 `failed`。

生产验收必须同时核对：配置值、待删状态、Telegram 消息消失、数据库 `status=deleted/deleted=1`，以及重启后恢复任务仍注册。health 200 不能替代这组业务回执。
