# 用户问题追踪、自动承接与FAQ蒸馏系统 (v5.42.2)

> 自动记录用户问题 → 蒸馏高频问题 → 人工审核话术 → AI润色自动回复，实现"变相蒸馏运营者"闭环。

## 1. 系统架构

```
用户消息 → 审核预设早路由 / P10 AI回复
  ├─ 审核预设实际送达 → 原子记录问题、回复、answer_source=preset、规则名
  ├─ 明显问句 + FAQ_TRACKING_ENABLED=true → 不受随机回复率限制，主动承接
  ├─ [FAQ_TRACKING_ENABLED=true] → db.log_question() 记录问题
  ├─ [FAQ_AUTO_REPLY_ENABLED=true] → _try_faq_match() 匹配FAQ
  │   ├─ 命中 + ai_polish=true → AI润色模板回复
  │   ├─ 命中 + ai_polish=false → 直接模板回复
  │   └─ 未命中 → 正常AI回复
  ├─ 未命中且AI无可靠答案 → 联系Mory/自助下单同排双按钮
  └─ 最终回复后 → db.update_question_reply() 更新摘要、faq_hit_id、answer_source/ref
      └─ 无可靠答案 → ai_reply_summary加[UNRESOLVED]标记

每日自动蒸馏 → tasks/analytics/faq_distill_task.py
  ├─ 扫描7天内user_questions，排除preset/faq/direct_access/delegated和命令
  ├─ 按(category, mode, intent)分组+文本归一化聚类
  ├─ 频次≥FAQ_MIN_FREQUENCY → 写入faq_candidates(status=pending)
  └─ 通知管理员审核

每日23:50问题汇总 → faq_daily_question_summary
  ├─ 待老板优化：[UNRESOLVED]或没有回复摘要的问题
  ├─ 分别统计FAQ、预设、直接入口、AI和待优化来源
  ├─ AI已答但FAQ/预设未命中：只展示AI或历史未分类的正常回答
  └─ 直接发送给ADMIN_ID，不含用户ID

管理员审核 → Dashboard /api/faq/candidates/:id/approve
  ├─ 编写answer_template话术
  ├─ 设置ai_polish开关
  └─ 写入faq_knowledge(status=approved)
```

## 2. 数据库表

### 2.1 user_questions — 用户问题记录

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| uid | INTEGER | 用户ID |
| chat_id | INTEGER | 聊天ID |
| question_text | TEXT | 问题文本（最长500字） |
| mode | TEXT | detect_keywords模式（convert/tarot/treehole/dream/feedback/contact_mory/normal） |
| intent | TEXT | 意图分类（预留） |
| keyword_tag | TEXT | 命中的关键词标签 |
| question_category | TEXT | 问题分类（pricing/troubleshooting/feedback/content/other） |
| is_convert | INTEGER | 是否转化类（1=是） |
| ai_reply_summary | TEXT | AI回复摘要（前200字）；`[UNRESOLVED]`前缀表示需人工优化 |
| faq_hit_id | INTEGER | 命中的FAQ条目ID（0=未命中） |
| answer_source | TEXT | 回答来源：preset/faq/direct_access/ai/unresolved/fallback/delegated；旧行留空 |
| answer_ref | TEXT | 规则名、FAQ ID、入口目标或稳定路径引用 |
| ts | INTEGER | 时间戳 |

索引：uid, ts, question_category

### 2.2 faq_knowledge — FAQ知识库

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| question_pattern | TEXT | 问题匹配模式（关键词/精确文本） |
| question_category | TEXT | 问题分类 |
| answer_template | TEXT | 话术模板（人工编写） |
| ai_polish | INTEGER | AI润色开关（1=润色，0=原文） |
| match_mode | TEXT | 匹配模式（keyword/exact） |
| priority | INTEGER | 优先级（越大越优先） |
| hit_count | INTEGER | 命中次数 |
| status | TEXT | 状态（approved/disabled） |
| created_by | TEXT | 创建者 |
| created_at | INTEGER | 创建时间 |
| updated_at | INTEGER | 更新时间 |

索引：question_category, status

### 2.3 faq_candidates — FAQ蒸馏候选

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| question_pattern | TEXT | 聚类后的问题模式 |
| question_category | TEXT | 问题分类 |
| sample_questions | TEXT | 样本问题（JSON数组） |
| frequency | INTEGER | 出现频次 |
| mode | TEXT | 主要mode |
| intent | TEXT | 主要intent |
| status | TEXT | 状态（pending/approved/rejected） |
| reviewed_by | TEXT | 审核人 |
| reviewed_at | INTEGER | 审核时间 |
| created_at | INTEGER | 创建时间 |

索引：status, question_category

## 3. question_category 映射规则

P10钩子中根据 mode 自动映射：

| mode | question_category | 说明 |
|------|-------------------|------|
| convert | pricing | 商业咨询（价格/订阅/开通） |
| contact_mory | troubleshooting | 求助（被封/解封/找Mory） |
| feedback | feedback | 反馈 |
| tarot | content | 内容类（塔罗） |
| treehole | content | 内容类（树洞） |
| dream | content | 内容类（解梦） |
| 其他 | other | 其他 |

## 4. FAQ匹配逻辑（search_faq）

```
1. 查询 faq_knowledge WHERE status='approved'
2. 对每条FAQ：
   a. match_mode='keyword': question_pattern中的词全部出现在用户消息中
   b. match_mode='exact': question_pattern与用户消息完全匹配
   c. 额外匹配: question_category == mode 或 question_category == intent
3. 按优先级(priority DESC) + 命中数(hit_count DESC) 排序
4. 返回按优先级排序的匹配项列表；调用方取第一条
```

## 5. FAQ回复流程（_try_faq_match）

```
1. 检查 FAQ_AUTO_REPLY_ENABLED 开关
2. 调用 db.search_faq(msg, mode, intent)，兼容列表和旧版单字典返回
3. 命中时：
   a. db.increment_faq_hit(faq_id) 记录命中
   b. ai_polish=True:
      - 调用 ai.ask("请用Mory的人设风格润色以下回复...：{answer_template}")
      - 润色失败则回退用原文
   c. ai_polish=False:
      - 直接使用 answer_template
4. 返回 (reply_text, faq_id)
5. 任何异常返回 (None, 0)，绝不阻塞正常AI流程
```

## 6. FAQ蒸馏逻辑（distill_candidates）

```
1. 扫描 user_questions 最近 days 天的记录，排除已由 preset/faq/direct_access/delegated 覆盖的记录及 `/` 命令
2. 按 (question_category, mode, intent) 分组
3. 组内按归一化文本聚合：
   - 小写化
   - 去除标点符号
   - 相同归一化文本的问题合并
4. 聚合后频次 >= min_frequency 的生成候选
5. 去重：已存在相同 question_pattern 的候选不重复创建
6. 写入 faq_candidates(status=pending)
7. 返回新候选数量
```

## 7. 配置开关

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| FAQ_TRACKING_ENABLED | true | 问题记录开关；开启后明显问句会主动进入P10 |
| FAQ_AUTO_REPLY_ENABLED | true | FAQ自动回复开关（命中FAQ时优先用审核话术） |
| FAQ_DISTILL_INTERVAL | 86400 | 蒸馏任务间隔（秒，默认每日一次） |
| FAQ_MIN_FREQUENCY | 2 | 蒸馏最低频次（出现次数≥此值才生成候选） |

示例配置已开启追踪和FAQ自动回复；既有环境仍以当前 `config.json` 为准。每日23:50问题汇总复用 `FAQ_TRACKING_ENABLED` 和 `ADMIN_ID`，不新增漂移开关。

## 8. 预置人设化自动回答

`modules/keyword_trigger.py` 在数据库关键词规则之前合并项目内置规则，当前覆盖：

- “助理出来/助理在吗”：按当前人设响应，并自然保留 `@MorychannelBot` 自助下单入口。
- 私聊“可以约吗/怎么进群/包年可以/预览”等对象明确短句：使用审核底稿；群聊必须带会员、VIP、至臻等业务对象。
- 生产 `SPECIAL_AUTO_REPLIES` 中老板明确配置的“积分咨询/签到奖励咨询”是白名单，完整句命中后使用配置原文并记录 `preset` 来源；代码不再自行扩写相似问法。
- 未命中白名单的签到/积分操作话题不进入 Mory AI，也不猜另一个机器人的账号；只记录为 `answer_source=delegated`，供原始对话审计，且从 Mory 日报、FAQ蒸馏、覆盖率和高频榜排除。

`SPECIAL_AUTO_REPLIES` 中的同名配置优先，可通过 `enabled=false` 关闭规则。历史硬编码的签到积分福利、积分兑换、签到九十天兑换和兑换未进群问答不再自动启用，只有老板以后在生产配置中明确新增才可恢复。

## 9. Dashboard API

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/faq/stats | GET | Mory职责内问题统计；分子分母均排除 delegated；数据库不可读时返回 503，不以零指标假成功 |
| /api/faq/questions | GET | 问题列表（真实总数分页+分类+天数+回答来源） |
| /api/faq/candidates | GET | FAQ候选列表（按状态筛选） |
| /api/faq/candidates/<id>/approve | POST | 审核通过（含answer_template/ai_polish） |
| /api/faq/candidates/<id>/reject | POST | 审核拒绝 |
| /api/faq/knowledge | GET | FAQ知识库列表（分页+分类+状态） |
| /api/faq/knowledge | POST | 新增FAQ条目 |
| /api/faq/knowledge/<id> | PUT | 更新FAQ条目 |
| /api/faq/knowledge/<id> | DELETE | 删除FAQ条目 |
| /api/faq/distill | POST | 手动触发FAQ蒸馏 |

## 10. 代码文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| core/database.py | 修改 | 3张新表 + QuestionRepo实例 + 17个方法注册 |
| core/db_repos/question_repo.py | 新增 | QuestionRepo 17个方法 |
| core/db_repos/__init__.py | 修改 | 导入QuestionRepo |
| core/handlers/ai_handlers.py | 修改 | _try_faq_match() FAQ匹配函数 |
| core/handlers/ai_reply_handler.py | 修改 | P10钩子（记录问题+FAQ匹配+faq_hit_id） |
| modules/keyword_trigger.py | 修改 | 内置人设化问题回答与配置同名覆盖 |
| modules/checkin.py | 修改 | 无效签到写法识别与正确格式提示 |
| tasks/analytics/faq_distill_task.py | 修改 | FAQ蒸馏 + 每日问题汇总 |
| dashboard/api/faq_api.py | 新增 | 10个API端点 |
| dashboard/app.py | 修改 | 注册faq_bp蓝图 |
| config.json.example | 修改 | 4个新配置键 |

## 11. 运营使用流程

1. **开启记录**：config.json 设置 `"FAQ_TRACKING_ENABLED": true`
2. **积累数据**：让Bot运行几天，自动记录用户问题
3. **查看统计**：Dashboard `/api/faq/stats` 查看高频问题排行
4. **审核候选**：系统自动蒸馏后，在 `/api/faq/candidates` 审核高频问题
5. **编写话术**：为每个候选编写 answer_template，设置 ai_polish 开关
6. **开启回复**：config.json 设置 `"FAQ_AUTO_REPLY_ENABLED": true`
7. **查看日报**：每天23:50读取管理员消息中的待优化问题和未命中样本
8. **持续优化**：根据日报与 `/api/faq/stats` 的 faq_hit_rate 调整话术
