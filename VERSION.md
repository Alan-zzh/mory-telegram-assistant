v5.31.2

2026-07-06 Hotfix：解封入口三次加固。`main.py` 已在兜底分发器之前注册 `/unban` 专用 handler；`/unban 8383136504` 与 `/unban @mmb3695` 线上只读 smoke 均解析到 8383136504；同名显示名“萌萌逼”会返回候选 ID，不盲选。

2026-07-06 Hotfix：修复解封指令私聊不生效。`/unban`、`/解封`、`解封 ...`、`解除封禁...` 已前移到消息分发 P5.6 早路由，私聊和群聊都会优先执行完整解封链；已恢复生产用户 8383136504 的 Telegram 群权限。

2026-07-06 Hotfix：彻底修复“签到”误封。签到/打卡/checkin 等正常业务动作不再进入广告资料层和延迟封禁累计；解封统一清 blacklist/global_blacklist/mute_records/ad_suspicious_users，并支持 /unban ID、/unban @username、回复消息解封、私聊自助解封和按钮解封。

2026-07-06 Hotfix：修复广告资料层误封风险。白名单/群管理员免检前移到 Bio/emoji 状态检测之前；广告处置管理员通知新增“解封”按钮，可一键移除 blacklist/global_blacklist/mute_records 并恢复群内发言权限。

2026-07-05 Hotfix：取消 AI 失败时的拟人化尴尬兜底。普通/未知/特殊模式全失败直接静默，转化/联系模式失败只给 @moryselect 与 @MorychannelBot 固定入口。

2026-07-05 Hotfix：修复 AI 真实失败根因。剔除慢/坏模型，standard 首发 glm-5.1，light/premium 首发 qwen3.7-max-2026-05-17/06-08；生产 AI 调用预算收紧为 30 秒、2 次。
