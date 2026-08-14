# v5.38.56 频道内容相关评论修复

## 结论

生产 v5.38.55 的取消置顶链正常，但自动评论硬依赖频道侧 `channel_post` 先登记 pending；生产只收到群内自有频道自动转发，因此只取消置顶、不发评论。v5.38.56 改为直接以群转发为评论真相源，并按原帖文案选择 `contact` 或 `subscribe` 单入口，可附一张项目内已审核营销图片卡。

## 生产只读证据

- 2026-08-14 19:13:21、19:17:23、19:20:26、19:20:27：`linked_channel_sync` 均记录取消关联频道置顶。
- 同日 journal 无 `频道帖子捕获`、`关联频道评论已发` 或评论发送异常。
- 生产 `channel_posts` 最近记录为空；允许更新列表包含 `channel_post`，联动开关和自动评论开关均为 true。
- 生产服务仍为 v5.38.55，active/running，NRestarts=0；以上只证明当前进程存活与故障链路，不证明新行为已生效。

## 本地改动

- 群内可信自有频道转发没有 pending 时，直接回复该转发，不再静默跳过。
- 文案含定制、需求、原味、私聊等语义时只给联系 Mory；完整版、解锁、订阅、下单等语义及普通预览帖只给自助订阅。
- 评论正文先给内容相关彩虹屁，再给与按钮一致的自然承接；每条只保留一个入口，不回引预览群。
- `comment_media_enabled=true` 时随机复用 `photo_pool_01..07.png`；原味文案使用 `original_taste_menu.png`。图片失败降级同文案文本卡。
- 群转发先到时记录原帖为 consumed；后到 `channel_post` 不会重新打开，避免重复评论。

## 验证

- `python -m compileall modules/linked_channel_sync.py -q`
- `python -m pytest tests/unit/test_linked_channel_sync.py tests/unit/test_ad_channel_forward_exempt.py -q`：33 passed。
- `python scripts/check_config_sync.py`：配置三处同步一致。
- 真实频道业务探针：未执行；当前请求未授权部署或发送测试帖子。

## 边界

本地已完成，生产未部署。生产要闭环仍需部署后从频道发一条已知帖子，确认群转发取消置顶、唯一图片评论回执、按钮目标、刷新后仍存在，并核对未出现重复评论。
