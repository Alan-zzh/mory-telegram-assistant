# B档：巨石文件分批拆分方案（v5.41.0 治理批次后立项）

> 状态：**批次 B1 已完成本地施工并过全部门禁（未部署，随下一版本发布）**；B2-B7 待逐批执行。
> 原则：每批独立可回滚；每批必须过全量 pytest + compileall + 异常卫生 + doc_consistency；
> 行为保持逐字等价（纯搬运不改逻辑），涉视觉的加样张字节比对；部署单独走门禁授权。

## 背景与目标

三个 Python 巨石与一个前端巨石是当前可维护性的最大债（2026-08-23 体检结论）：

| 文件 | 拆前体量 | 问题 |
|---|---|---|
| `core/ai_engine.py` | 3135 行 | 模型路由/人设工厂/后置净化/媒体工具五类混居，ask() 单方法约 500 行 |
| `core/database.py` | 约 2460 行 | DDL 建表 + Repo 注册表 + 连接管理全在一个文件 |
| `core/message_dispatcher.py` | 约 2040 行 | P0-P10 十条分发链内联 |
| `dashboard/templates/index.html` | 274KB | 前端单文件 SPA |

## 批次规划

| 批次 | 内容 | 风险 | 状态 |
|---|---|---|---|
| **B1** | ai_engine 媒体工具（analyze_image/text_to_speech）→ `core/ai_media_tools.py`，ai_engine 再导出兼容 | 低（游离函数零耦合） | ✅ 本地完成 |
| B2 | ai_engine 后置净化链（_sanitize_reply_v2/_strip_stage_directions/_soften_hostile_reply）→ `core/reply_sanitizer.py` | 中（有行为测试护航） | 待做 |
| B3 | ai_engine 人设工厂（~1100 行 prompt 工程/_build_persona）→ `core/persona_factory.py` | 中高（文案敏感，需 persona 一致性测试） | 待做 |
| B4 | ai_engine 模型池管理（黑名单/熔断/慢模型判定）→ `core/model_pool.py`；ask() 主循环瘦身 | 高（主链核心） | 待做 |
| B5 | database.py：DDL 迁入 Alembic migrations（幂等+回滚验证），Repo 注册表拆 `core/db_registry.py` | 高（启动关键路径，需 verify_db_methods 全绿+生产表结构比对） | 待做 |
| B6 | message_dispatcher：P0-P10 阶段函数拆 `core/handlers/dispatch_stages/` 包，dispatcher 只留路由骨架 | 高（消息主链） | 待做 |
| B7 | index.html 按 settings/broadcast/metrics 分片模板 + 静态 JS 抽离 | 中（前端无像素测试，需人工回归清单） | 待做 |

## 批次完成定义（DoD）

1. 纯代码搬运，diff 审查无逻辑改动；
2. 全量 `pytest tests/unit/ -q` 通过（当前基线 1236）；
3. compileall / check_exception_hygiene / doc_consistency / verify_db_methods 全绿；
4. METRICS 计数同步（新文件会改变 core_py 等）；
5. 每批一个独立 commit，message 注明批次号；
6. 部署随下一版统一走 ship-gate，不单独发布。

## 关联决策

- ab_testing 全家桶：**保留休眠**（老板未明确退役指令，默认关闭零运行成本；若连续两个季度不启用再议退役）。
- anomaly_detector 缩编：并入 B4 评估（同为"智能感"模块，看模型池拆分后的监控归属）。
