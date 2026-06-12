# 用户问题追踪与FAQ蒸馏系统 (v5.15.0)

> 自动记录用户问题 → 蒸馏高频问题 → 人工审核话术 → AI润色自动回复，实现"变相蒸馏运营者"闭环。

## 1. 系统架构

```
用户消息 → P10 AI回复
  ├─ [FAQ_TRACKING_ENABLED=true] → db.log_question() 记录问题
  ├─ [FAQ_AUTO_REPLY_ENABLED=true] → _try_faq_match() 匹配FAQ
  │   ├─ 命中 + ai_polish=true → AI润色模板回复
  │   ├─ 命中 + ai_polish=false → 直接模板回复
  │   └─ 未命中 → 正常AI回复
  └─ AI回复后 → db.update_question_reply() 更新摘要+faq_hit_id

每日自动蒸馏 → _job_faq_distill()
  ├─ 扫描7天内user_questions
  ├─ 按(category, mode, intent)分组+文本归一化聚类
  ├─ 频次≥FAQ_MIN_FREQUENCY → 写入faq_candidates(status=pending)
  └─ 通知管理员审核

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
| ai_reply_summary | TEXT | AI回复摘要（前200字） |
| faq_hit_id | INTEGER | 命中的FAQ条目ID（0=未命中） |
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
4. 返回最高优先级的匹配项
```

## 5. FAQ回复流程（_try_faq_match）

```
1. 检查 FAQ_AUTO_REPLY_ENABLED 开关
2. 调用 db.search_faq(msg, mode, intent)
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
1. 扫描 user_questions 最近 days 天的记录
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
| FAQ_TRACKING_ENABLED | false | 问题记录开关（开启后P10自动记录用户问题） |
| FAQ_AUTO_REPLY_ENABLED | false | FAQ自动回复开关（开启后匹配FAQ时用话术回复） |
| FAQ_DISTILL_INTERVAL | 86400 | 蒸馏任务间隔（秒，默认每日一次） |
| FAQ_MIN_FREQUENCY | 3 | 蒸馏最低频次（出现次数≥此值才生成候选） |

**重要**：所有开关默认关闭，需手动开启。建议先开 FAQ_TRACKING_ENABLED 积累数据，再开 FAQ_AUTO_REPLY_ENABLED。

## 8. Dashboard API

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/faq/stats | GET | 问题统计（总数/今日/TOP20/分类分布/FAQ命中率） |
| /api/faq/questions | GET | 问题列表（分页+分类+天数筛选） |
| /api/faq/candidates | GET | FAQ候选列表（按状态筛选） |
| /api/faq/candidates/<id>/approve | POST | 审核通过（含answer_template/ai_polish） |
| /api/faq/candidates/<id>/reject | POST | 审核拒绝 |
| /api/faq/knowledge | GET | FAQ知识库列表（分页+分类+状态） |
| /api/faq/knowledge | POST | 新增FAQ条目 |
| /api/faq/knowledge/<id> | PUT | 更新FAQ条目 |
| /api/faq/knowledge/<id> | DELETE | 删除FAQ条目 |
| /api/faq/distill | POST | 手动触发FAQ蒸馏 |

## 9. 代码文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| core/database.py | 修改 | 3张新表 + QuestionRepo实例 + 17个方法注册 |
| core/db_repos/question_repo.py | 新增 | QuestionRepo 17个方法 |
| core/db_repos/__init__.py | 修改 | 导入QuestionRepo |
| core/handlers/ai_handlers.py | 修改 | _try_faq_match() FAQ匹配函数 |
| core/handlers/ai_reply_handler.py | 修改 | P10钩子（记录问题+FAQ匹配+faq_hit_id） |
| modules/auto_tasks.py | 修改 | _job_faq_distill() 蒸馏任务 |
| dashboard/api/faq_api.py | 新增 | 10个API端点 |
| dashboard/app.py | 修改 | 注册faq_bp蓝图 |
| config.json.example | 修改 | 4个新配置键 |

## 10. 运营使用流程

1. **开启记录**：config.json 设置 `"FAQ_TRACKING_ENABLED": true`
2. **积累数据**：让Bot运行几天，自动记录用户问题
3. **查看统计**：Dashboard `/api/faq/stats` 查看高频问题排行
4. **审核候选**：系统自动蒸馏后，在 `/api/faq/candidates` 审核高频问题
5. **编写话术**：为每个候选编写 answer_template，设置 ai_polish 开关
6. **开启回复**：config.json 设置 `"FAQ_AUTO_REPLY_ENABLED": true`
7. **持续优化**：根据 `/api/faq/stats` 的 faq_hit_rate 调整话术
