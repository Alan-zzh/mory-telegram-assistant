# v5.38.67 广告化姓名与 Bio 拉新深链生产闭环

## 结论

`verified_with_live_event_boundary`。资料审核过去完全禁止跨字段证据，导致“姓名有招揽语义、Bio 只有规避式 Bot 拉新深链”的账号在两个字段单独评分不足时漏过。v5.38.67 仅增加一条高置信例外：姓名含“老师/同城/同程+免费上榜”，且 Bio 同时给出 `t.me/<bot>?start=invite_*`，进群、延迟复查和每次发言都会进入统一处置。

## 根因与改动

- 唯一资料判定函数原先明确禁止姓名、username、Bio 跨字段组合，即使组合后已具备明确招揽和拉新语义也会放行。
- 新增 `profile_name_bot_invite` 来源；普通姓名、普通 `t.me` 链接、普通群邀请、普通关联频道继续保持字段隔离。
- 现有 `member_handlers._review_member_profile()` 和 `security_handlers.check_ad_detection()` 均调用同一资料判定函数，因此规则同时覆盖进群、30 秒/5 分钟/30 分钟复查和第一次群发言。
- 正文仍使用独立逐条证据；截图“同城PC…平台担保交易…”生产评分 4，不依赖姓名、Bio 或重复次数。

## 验证与发布

- 提交：`57aa41c72627464036c7b9f97e791a99c1608989`。
- 本地：资料/入群目标链 55 项通过；广告相关 359 项通过；全仓 unit 1202 项通过。
- 干净工作树：`doc_consistency.py`、`check_config_sync.py`、`verify_db_methods.py`（208 个委托方法）和 `check_deploy_ready.py` 全部通过。
- 生产：v5.38.67；`modules/ad_profile_signals.py` SHA-256 `bc48ef4e1d54d24592430e4ec6cad4106050561b9aa752cb8b5214da21062a11`，`version.py` SHA-256 `4799b08a3dfe8ecca77311827e3c0ae49ea8ae62496e3d755cf67993db74215a`，均与干净提交一致。
- 运行态：Bot PID `1658275`、Dashboard PID `1658276`，双服务 active/running、NRestarts=0，HTTP 200。启动时出现的两条 Traceback 来自旧 Dashboard worker 在 gevent 终止阶段回收 logging handler；旧 worker 随即正常退出，新 PID 启动窗口未见同类异常。
- 回滚包：`/home/ubuntu/mory_assistant/backups/ad_profile_combo_v53867_20260820_091626.tar.gz`，SHA-256 `3287fc346fa6d5aa1f116b66225b4fa6e0ff2b106b2a357bd4399b0d4945b981`。

## 生产业务探针

- `y同程老师免费上榜{牵.茗.进}y` + `https://t.me/tcsy1bot?start=invite_7982354468`：`is_ad=true`、score=3、source=`profile_name_bot_invite`。
- 同一广告化姓名不带 Bio：0 分，证明不是扩大为姓名裸封；截图原姓名含“同程嫖娼”仍由独立姓名强规则直接处置。
- 截图正文：`is_ad=true`、score=4。
- 反例：广告化姓名+普通个人链接、普通姓名+Bot 深链、“同程旅行老师”+Bot 深链、公益评选+普通官网，均为 0 分。
- 截图账号 UID `6070826211` 刷新 Telegram 状态仍为 `kicked`；独立 SQLite 连接读回 `blacklist=1`、`global_blacklist=1`、`mute_records=1`、`ad_suspicious_users=0`，消息 `68564/68608/68650` 均为 `is_ad=1/deleted=1`。

## 边界

本轮没有为了验收而让新的测试账号真实进群或向生产群发送广告，因此没有新增 live join/update 回执。已验证的是生产解释器中的真实规则结果、两个真实处理入口的集成回归，以及现有截图账号刷新后的 Telegram/数据库持久态；后续真实同类 update 会走已部署的同一入口。
