# 群成员全量广告扫描

> 当前规范入口：`scripts/scan_group.py`。运行态结论必须取生产新回执，历史扫描数字不代表当前覆盖率。

## 安全合同

- Pyrogram + bot token 枚举当前群成员；私有群可直接使用 `GROUP_ID`，不要求公开 username。
- 判定复用 `MemberAdEvaluator`：资料走显示名/username/Bio/Premium/个人频道专用强证据；历史消息逐条只跑内容字段，禁止把普通 username 或 Bio 分数冒充该消息的直接证据；头像仅接受高置信复核。
- 默认只生成报告；报告覆盖率低于 90%、启用 `--max-members`、版本不符、超过 6 小时或指纹不符时禁止应用。
- 单独应用阶段逐个重新确认成员、管理员/白名单/黑名单和最新资料，再重新判定；任何关键状态 unknown 都跳过。
- 处置只走 `modules/ad_enforcement.py:enforce_ad_user()`；弱信号、普通行为追踪和低置信头像不得处罚。
- 输出包含 UID，必须写入权限 0600 的私有路径；审计文档只保存汇总，不保存姓名、Bio 或头像内容。

## 生产命令

```bash
# 第一阶段：全量报告，不处罚
python3 scripts/scan_group.py \
  --output /tmp/mory-member-scan-report.json

# 第二阶段：仅对报告中的高置信候选重新取证并统一处置
python3 scripts/scan_group.py \
  --apply-report /tmp/mory-member-scan-report.json \
  --output /tmp/mory-member-scan-apply.json
```

默认头像策略只复核已有弱信号的候选，避免全群触发视觉调用。`--avatar-all` 会复核每个非豁免成员头像，只应在明确授权、容量评估和生产观察下使用。

## 启动扫描边界

`tasks/maintenance/startup_member_scan_task.py` 只扫描数据库已知 UID，不等于全群枚举。它默认关闭：

- `STARTUP_MEMBER_SCAN_ENABLED=false`
- `STARTUP_MEMBER_SCAN_ENFORCE=false`

即使人工开启，默认也是只报告；零实查、数据库查询失败或 API 错误率过高必须记为失败，不能记录零人成功。

## 验收

报告阶段至少核对：版本、`status=success`、群 ID、平台成员数、枚举数、覆盖率、候选来源分布和指纹。应用阶段核对每名候选的重新取证结果、统一处置回执、Telegram 禁言状态及黑名单/禁言记录；再次应用同一报告应只出现已处置或跳过，不得重复产生副作用。
