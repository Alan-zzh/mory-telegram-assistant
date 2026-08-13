# v5.38.43 存量成员广告扫描生产闭环

## 结论

- 生产版本：`v5.38.43`，最终扫描与处置均完成。
- report-only 枚举 6885 / 7100 人，成员覆盖 96.97%；6814 个需检查成员的 Profile、规则评估和真实传输覆盖均为 100%。
- Bot API 个人资料增强覆盖 2.47%，个人频道最近帖子覆盖 0%；均显式记录为 warning，不包装成全能力覆盖。
- 79 个高置信候选中，74 个当次 Profile 强证据复核仍命中并走统一处置链；5 个因个人频道帖子 unknown 跳过。失败 0。
- 处置后独立读回：Telegram 限权 74/74，`blacklist` 74/74、`global_blacklist` 74/74、`mute_records` 74/74；5 个 unknown 跳过者三表均为 0。
- 重复应用同一签名报告：`already_blacklisted=74`、`personal_channel_unknown=5`、新增处置 0。

## 生产证据

- 服务：`mory-assistant`、`mory-dashboard` 均于 2026-08-13 09:05:18 CST 启动，`NRestarts=0`，`/api/health=200`。
- report-only：2026-08-13 09:05:58 CST 启动，耗时 1062 秒；私有报告权限 0600，状态 `success`，SHA-256 内容指纹复算一致。
- apply：2026-08-13 09:25:52 CST 启动，耗时 236 秒；私有回执权限 0600，状态 `success`，来源报告指纹和自身指纹均一致。
- 候选来源：Profile 强规则 77，个人频道组合强锚点 2；无普通姓名格式或弱头像单独候选。

## 关键文件 SHA-256

- `version.py`: `0002985da5ce967886bc7130bb0eabb6a3cfe8c93d7e5dbd4cc5e61e85ac0a42`
- `modules/member_ad_scan.py`: `89a9784e551dd02fd15cc99dab4db6bdb7f20ebd188db03494a6ba35af217566`
- `scripts/scan_group.py`: `022ce4c1446ccefe4889b0cf2a7de2201fafdf3b2d0cf4b3a2f361afda627c34`
- `tasks/maintenance/startup_member_scan_task.py`: `b6842a587b0a0e04f1206d6be0b80d8667e7d235b74943ec01c41c7cdc603b9d`
- `modules/ad_profile_signals.py`: `0d7ced87884ed1176cf94b83e907ce472e8445babfd4e16f8c9bf3a6f1f51acd`

## 边界

- Telegram 不提供“某成员是否看过老板简介/主页”的观察接口；本模块识别的是成员资料中“看我简介/看我主页”等引流文案，不声称知道实际浏览行为。
- 加入频道/强制订阅是独立能力，不作为广告处置授权。
- 本轮未使用外部辅助信号；头像只在已有弱信号时做高置信复核，低置信头像不处罚。
