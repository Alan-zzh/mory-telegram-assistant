# v5.38.4 订阅回复变体生产验收

## 结论

`verified`：明确订阅成交回复已从单条模板改为简短人设变体池。生产连续五次近义问法得到五条不同回复，语气保持清醒、温柔、略带小傲娇；随机只改变措辞，不改变成交目标和按钮合同。

## 四层证据

- **truth_surface**：VPS `/home/ubuntu/mory_assistant`，服务实际解释器 `/usr/bin/python3`，systemd `mory-assistant` / `mory-dashboard`，群聊近期助手历史含 `@moryselect` 预览。
- **success_receipt**：生产依次输入“怎么订阅、订阅怎么弄、咋开通、会员怎么开、付费入口在哪”，均返回 `subscribe / explicit_purchase`，生成 5/5 不同短句且每句不超过 55 字；群聊按钮恰好一个并指向 `https://t.me/MorychannelBot`，私聊 markup 为空。Telegram 管理员真实验收卡 `message_id=3017`。
- **persistence_check**：部署后重新连接 VPS，4/4 运行文件哈希一致，双服务 active+enabled、health `v5.38.4`、NRestarts 均为 0、当前进程 priority error 为空，发布锁已释放。
- **derived_records**：`CHANGELOG.md`、`project_snapshot.md`、`VERSION.md`、`README.md`、`AI_DEBUG_HISTORY.md`、`AGENTS.md` 与 `docs/technical/persona-engine.md`。

## 业务矩阵

- 有近期预览的群聊示例：`懂了，不只看看是吧。下面可以直接订。@MorychannelBot`
- 同一会话后续变体：`嗯，看来你是认真想订了。入口给你，自己慢慢选。@MorychannelBot`
- 其他连续变体：`好，那就往下一步走。入口在下面，按提示来就行。@MorychannelBot`
- 误判反例：`咖啡怎么买`、`鞋子怎么购买`、`淘宝付款入口在哪` 均为 `none`

## 发布证据

- 可信提交：`4443ab1`
- 生产备份：`/home/ubuntu/mory_assistant/backups/deploy_v5384_20260728_203335`
- 发布文件：10/10 SHA-256 一致
- 本地门禁：定向 70 passed；完整 514 passed / 7 skipped；DB 190/190；文档 7/7；`py_compile`、JSON 解析与 `git diff --check` 通过
- 安全边界：未覆盖 `.env`、`config.json`、`mory.db`，未向真实群成员补发测试消息
