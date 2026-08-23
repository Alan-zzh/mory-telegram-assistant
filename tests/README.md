# Mory小助理 测试目录

> **最后整理**：2026-08-23（v5.41.0 重写为真实结构）
> **总原则**：所有测试代码统一放 `tests/`，根目录**禁止**出现 `_*.py` 临时测试文件

---

## 📁 目录结构（实测）

```
tests/
├── README.md        # 本文件
├── unit/            # 单元测试（87 个文件，pytest tests/unit/ 全量入口）
├── alert/           # 告警链路测试（级联抑制等故障注入）
├── attribution/     # 转化归因测试（含离线回放）
├── integration/     # 集成测试（端到端、多模块协作）
├── load/            # Locust 压测（locustfile.py + analyze_results.py）
├── persona/         # 人设一致性测试
├── perf/            # （已并入 load，v5.41.0 删除独立 perf 目录）
└── security/        # 安全面测试
```

运行方式（与 CI 一致）：

```bash
.venv/Scripts/python -m pytest tests/unit/ -q          # Windows
python -m pytest tests/unit/ -q                        # Linux / CI
```

## 🧹 历史清理说明

- 旧的一次性 `_*.py` 调试/测试脚本已经不再作为仓库资产保留。
- 这类脚本如果仍有价值，应重写为 `tests/unit/test_xxx.py` 或 `scripts/verify_xxx.py`。
- 不再新增 `tests/_archive/` 这类长期堆放区。

## 🆕 新测试如何写？

| 类型 | 位置 | 命名 |
|------|------|------|
| 单元测试 | `tests/unit/test_xxx.py` | `test_xxx.py` |
| 集成测试 | `tests/integration/` | `test_xxx_integration.py` |
| 端到端验证 | `scripts/verify_xxx.py` | `verify_*.py` |

共享 fixture 在根目录 [conftest.py](../conftest.py)：
`temp_db` / `mock_bot` / `mock_llm_api` / `temp_config` / `temp_env`。

## ⚠️ 不要再做的事

- ❌ 根目录写 `_test_xxx.py` / `_check_xxx.py` / `_debug_xxx.py`
- ❌ 再建新的历史测试堆放目录
- ❌ 把普通测试放在 `scripts/` 目录（仅 `verify_*` 端到端脚本例外）
