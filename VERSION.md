v5.31.2

2026-07-06 Hotfix：彻底修复“签到”误封。签到/打卡/checkin 等正常业务动作不再进入广告资料层和延迟封禁累计；解封统一清 blacklist/global_blacklist/mute_records/ad_suspicious_users，并支持 /unban ID、/unban @username、回复消息解封、私聊自助解封和按钮解封。

2026-07-06 Hotfix：修复广告资料层误封风险。白名单/群管理员免检前移到 Bio/emoji 状态检测之前；广告处置管理员通知新增“解封”按钮，可一键移除 blacklist/global_blacklist/mute_records 并恢复群内发言权限。

2026-07-05 Hotfix：取消 AI 失败时的拟人化尴尬兜底。普通/未知/特殊模式全失败直接静默，转化/联系模式失败只给 @moryselect 与 @MorychannelBot 固定入口。

2026-07-05 Hotfix：修复 AI 真实失败根因。剔除慢/坏模型，standard 首发 glm-5.1，light/premium 首发 qwen3.7-max-2026-05-17/06-08；生产 AI 调用预算收紧为 30 秒、2 次。
