# 群成员全量扫描方案

> **本文件记录全量扫描方案，供AI参考**
> **最后更新**: 2026-05-31

---

## 扫描方案选择

### ✅ 首选方案：Pyrogram + bot_token + 公开API凭证

**使用方法**:
```bash
# VPS上执行
pip3 install --break-system-packages pyrogram tgcrypto
python3 _scan_group.py --ban  # 扫描+封禁
```

**原理**: Pyrogram支持bot_token连接MTProto协议，使用Telegram Desktop开源凭证(api_id=2040)枚举全部群成员

**优点**: 无需用户申请api_id/api_hash，覆盖率~96%

**依赖**: 群组必须有公开用户名

**详见**: `.trae/specs/pyrogram-full-member-scan/spec.md`

---

## 封禁级别说明

| 级别 | 条件 | 动作 | 说明 |
|------|------|------|------|
| TRIPLE | 用户名/显示名命中 + Bio命中 + 头像可疑 | **直接封禁** | 三层组合，极高置信度 |
| DUAL | 用户名/显示名命中 + Bio命中 | **直接封禁** | 两层组合，高置信度 |
| HIGH_NAME | uname_score + display_score >= 4 | **直接封禁** | 高分显示名，无需Bio（v5.8.4新增） |
| UNAME_ONLY | uname_score >= 2 或 display_score >= 2 且 bio_score = 0 | **跳过** | 仅用户名命中，不封禁避免误封 |

### ⚠️ 重要规则：高分显示名直接封禁

**规则**：如果用户名和显示名的广告评分合计 >= 4（即同时命中多个高权重广告词），即使没有Bio也直接永久封禁。

**原因**：如"虚拟货币搬砖日入5K"这类名字本身就是高置信度广告语，即使没有Bio设置也明显是广告号。

**示例**：
- 7634865803 "虚拟货币搬砖日入5K @dsjahuf153512" → uname=2 + display=2 = 4 → HIGH_NAME → 封禁

---

## 历史扫描记录

| 时间 | 版本 | 扫描人数 | 覆盖率 | 可疑 | 封禁 |
|------|------|---------|--------|------|------|
| 2026-05-31 | v5.8.4 | 5811 | 95.7% | 16 | 2 |

### v5.8.4 扫描详情

**封禁(2人)**:
1. UID=5550607049 | 币圈套利日入3千U招团队合作 @dsfuiasawegdbf26 [DUAL] score=18
2. UID=6444578146 | 虚拟货币搬砖日入5K @fsjadhiausak1 [DUAL] score=10

**仅用户名可疑(14人，跳过封禁)**:
1. UID=8679385840 | wer36 [UNAME_ONLY] score=2
2. UID=6937481936 | hyy126 [UNAME_ONLY] score=2
3. UID=7634865803 | 虚拟货币搬砖日入5K @dsjahuf153512 [HIGH_NAME] score=4
4. UID=6006756690 | w1117 [UNAME_ONLY] score=2
5. UID=5226812357 | aygg1356 @aygg1356 [UNAME_ONLY] score=2
6. UID=7029780300 | zhou12 [UNAME_ONLY] score=2
7. UID=5722415467 | rttb2020 [UNAME_ONLY] score=2
8. UID=7359968894 | tiao2025 [UNAME_ONLY] score=2
9. UID=6285688969 | wiki2002 @letme9979 [UNAME_ONLY] score=2
10. UID=6742460696 | liu44 [UNAME_ONLY] score=2
11. UID=8360351680 | xhu999 @xhu999 [UNAME_ONLY] score=2
12. UID=1599882245 | s01 [UNAME_ONLY] score=2
13. UID=8281577365 | xixi01 [UNAME_ONLY] score=2
14. UID=7593587779 | hh6666 [UNAME_ONLY] score=2

---

## 相关文件

- `_scan_group.py` — 扫描脚本（支持Bot API/Pyrogram/Telethon三种模式）
- `_deploy_pyrogram.py` — VPS部署脚本

---

## 注意事项

1. 扫描时需先停Bot: `sudo systemctl stop mory-assistant`
2. 扫描后需重启Bot: `sudo systemctl start mory-assistant`
3. 建议定期全量扫描（每周一次）
