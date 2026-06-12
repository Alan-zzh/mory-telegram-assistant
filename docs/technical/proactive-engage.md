# 商业问题主动搭讪 (v5.16.2 [Codex])

> Bot 在群里检测到用户咨询商业问题（订阅/价格/权益等）时，主动搭讪回复并温和引导私聊转化。

## 1. 触发链路

```
用户群内消息 → core/message_dispatcher.do_dispatch()
  ├─ P1-P4: 安全/积分/刷屏（既有）
  ├─ P5-P9: 命令处理（既有）
  │  └─ P7 视奸雷达 → 设 dctx.proactive_eligible=True
  ├─ P7.5 [v5.14.0]: 商业搭讪层
  │  └─ if proactive_eligible and enabled:
  │     └─ ProactiveEngage.should_engage() → True
  │     └─ ProactiveEngage.engage() → 拦截 P10
  └─ P10: AI 回复（仅当 P7.5 未搭讪）
```

## 2. 核心组件

### 2.1 modules/proactive_engage.py (ProactiveEngage 类)

- `should_engage(uid, msg, is_admin) → (bool, str)`
  - [Codex] 检查 enabled、is_admin、convert 关键词、落库冷却、每日上限
  - 返回 (是否应搭讪, 命中关键词)
- `engage(uid, uname, chat_id, msg, matched_keyword, m) → bool`
  - 1. [Codex] 生成话术（AI 失败 fallback 按价格/权益/试看/下单/重复咨询分层）
  - 2. 群内搭讪回复
  - 3. 私聊发送详细引导
  - 4. 视奸雷达通知管理员
  - 5. 入库 proactive_engage_log
  - 6. 写入 conversion_event
  - 7. 设置冷却
  - 8. 给搭讪消息加 👍/👎 反馈按钮
- 异常保护：所有 IO 操作 try/except + logger.warning 静默失败

### 2.2 modules/group_mgr.py (扩展 convert 关键词)

```python
_CONVERT_KEYWORDS_SUBSTR = [
    "多少钱", "价格", "怎么买", "门槛", "开通", "会员",  # 原 6 词
    "订阅", "月付", "年付", "季付", "周付", "包月", "包年", "包季",  # 订阅类
    "续费", "充值", "解锁", "购买", "付费", "升级", "付款", "支付",  # 付费类
    "权益", "权限", "会员群", "VIP群",  # 权益类
    "怎么进", "怎么加", "怎么联系", "怎么私聊",  # 联系类
    "便宜", "划算", "折扣", "优惠",  # 价格比较
    "看看", "想看", "给我", "发一下", "有没有", "能看", "能玩",  # 主动索要看货
    "可以看", "可以用", "能不能", "几号",  # 其他常用
]

_CONVERT_KEYWORDS_WORD = [
    "视频", "观看", "包月", "包年", "包季", "解锁", "续费", "会员群",  # 全词匹配
]

def _is_convert_message(msg: str) -> bool:
    """短词子串匹配 + 长词全词匹配（避免"包月"误匹配"包月嫂"）"""
```

### 2.3 message_dispatcher (P7.5 搭讪层)

```python
# 在 P5-P9 之后、P10 之前调用
if _dispatch_p7_5_proactive_engage(dctx):
    return  # 拦截 P10 AI
```

```python
def _dispatch_p7_5_proactive_engage(dctx: DispatchContext) -> bool:
    """P7.5 商业问题主动搭讪"""
    if not dctx.is_group:
        return False
    if not getattr(dctx, "proactive_eligible", False):
        return False
    if not dctx.ctx.proactive_engage:
        return False

    try:
        # 管理员豁免
        # only_in_group_id 检查
        should, matched_kw = dctx.ctx.proactive_engage.should_engage(...)
        if not should:
            return False
        dctx.ctx.proactive_engage.engage(...)
        return True
    except Exception as e:
        logger.warning(...)
        return False
```

### 2.4 ai_reply_handler (convert 模式显式列举)

```python
# v5.14.0 显式列举（避免未来新增 mode 被误伤）
_non_normal_modes = ("convert", "tarot", "treehole", "dream", "feedback", "contact_mory")
should_reply = (
    is_priv or is_at or is_reply
    or mode in _non_normal_modes  # 跳过 REPLY_CHANCE
    or random.randint(1, 100) <= REPLY_CHANCE
)
```

## 3. 数据库

### 3.1 proactive_engage_log 表

```sql
CREATE TABLE proactive_engage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    uname TEXT NOT NULL DEFAULT '',
    msg TEXT NOT NULL DEFAULT '',
    matched_keyword TEXT NOT NULL DEFAULT '',
    reply_text TEXT NOT NULL DEFAULT '',
    ts INTEGER NOT NULL,
    converted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_proactive_engage_log_uid ON proactive_engage_log(uid);
CREATE INDEX idx_proactive_engage_log_ts ON proactive_engage_log(ts);
```

### 3.2 tracking_repo 3 个新方法

- `log_proactive_engage(uid, chat_id, uname, msg, matched_keyword, reply_text) → int`
- `get_recent_engages(limit=50, uid=0) → list`
- `get_engaged_stats() → {total_count, today_count, converted_count, conversion_rate}`

### 3.3 _REPO_METHOD_MAP 注册

```python
'log_proactive_engage': 'tracking',
'get_recent_engages': 'tracking',
'get_engaged_stats': 'tracking',
```

## 4. Dashboard API

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/engage/stats` | GET | 今日/累计/转化率 |
| `/api/engage/recent?limit=50` | GET | 最近搭讪列表 |
| `/api/engage/config` | GET | 读取配置 |
| `/api/engage/config` | POST | 更新配置（触发 reload_flag） |

## 5. 配置

```json
"PROACTIVE_ENGAGE_CONFIG": {
  "enabled": false,                  // 默认关闭
  "cooldown_minutes": 30,            // 跨群冷却，优先读取 proactive_engage_log
  "max_per_user_per_day": 3,         // 单用户每天上限，优先读取 proactive_engage_log
  "only_in_group_id": true           // 仅 GROUP_ID 群
},
"PROMPT_TEMPLATES": {
  "business_engage": "\n【商业搭讪模式】：用户刚刚在群内咨询了商业相关问题（订阅/价格/权限/内容等），请用轻松自然的方式回复：先简短回应他的问题（30-50字），然后自然引导他私聊了解详情。不要直白营销，不要催促，语气像朋友推荐。绝对不要称呼用户'老板'。末尾可以加一句'想知道更多？私聊我呀～'或'详情私聊我说'，但不要每句都加。"
}
```

## 6. 异常保护（不破坏"绝对不能死"红线）

| 异常 | 处理 |
|------|------|
| AI 引擎失败 | fallback 到内置模板 |
| 重启后冷却丢失 | [Codex] 从 proactive_engage_log 读取最近触达 |
| 用户多次咨询模板感 | [Codex] 按咨询意图和近 24h 次数切换 fallback |
| 群回复失败 | 跳过（搭讪事件可能仍记录） |
| 私聊发送失败 | 静默（用户可能未加 Bot） |
| 管理员通知失败 | 静默（不影响搭讪消息） |
| 入库失败 | logger.warning（不影响消息已发送） |
| 反馈按钮添加失败 | 静默（不影响主流程） |
| should_engage 异常 | 返回 (False, "") |
| engage 异常 | logger.warning + traceback，返回 False |

## 7. 验收清单

详见 `.trae/specs/proactive-business-engage/checklist.md`

## 8. 部署注意

- 部署后 `python -c "import sqlite3; c=sqlite3.connect('mory.db'); c.execute('SELECT * FROM proactive_engage_log LIMIT 1'); print('OK')"` 验证表存在
- 管理员在 Dashboard 开启搭讪，5-8 秒内 Bot 生效
- 真实群内发送商业问题，Bot 5 秒内搭讪回复
- `journalctl -u mory-assistant -n 100 --no-pager` 无 ERROR 日志

## 9. 后续迭代

- 二次触达：搭讪后用户无回应时，24h 后发送催单消息
- A/B 测试：话术模板随机化
- 转化回填：auto_tasks 定时回填 24h 内下单用户到 converted=1
- 关键词自学习：从用户实际问法中挖掘新关键词

## 10. 更新记录

- 2026-06-12 [Codex]：新增落库冷却、每日上限落库读取、咨询意图分层 fallback，避免重启后重复搭讪和固定模板感。
