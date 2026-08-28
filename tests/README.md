# Mory小助理 测试目录

> **最后整理**：2026-08-24（按真实目录与 CI 分层重写）
> **总原则**：所有测试代码统一放 `tests/`，根目录**禁止**出现 `_*.py` 临时测试文件

---

## 📁 目录结构（实测）

```
tests/
├── README.md        # 本文件
├── unit/            # 默认离线单元测试，pytest tests/unit/ 全量入口
├── alert/           # 告警链路测试（级联抑制等故障注入）
├── persona/         # 离线人设合同；真实模型评测使用 live_llm marker
└── security/        # 安全面测试
```

归因离线回放是审计 CLI，不是 pytest：`python scripts/attribution_offline_replay.py --help`。旧 WriteQueue Locust 脚本随 WriteQueue 退役删除；需要新压测时必须按当前 WAL + busy_timeout 架构重新建基线。

运行方式（与 CI 一致）：

```bash
.venv/Scripts/python -m pytest tests/unit/ tests/security/ tests/alert/ -q  # Windows
python -m pytest tests/unit/ tests/security/ tests/alert/ -q                # Linux / CI
```

## 🧹 历史清理说明

- 旧的一次性 `_*.py` 调试/测试脚本已经不再作为仓库资产保留。
- 这类脚本如果仍有价值，应重写为 `tests/unit/test_xxx.py` 或 `scripts/verify_xxx.py`。
- 不再新增 `tests/_archive/` 这类长期堆放区。

## 🆕 新测试如何写？

| 类型 | 位置 | 命名 |
|------|------|------|
| 单元测试 | `tests/unit/test_xxx.py` | `test_xxx.py` |
| 安全/告警测试 | `tests/security/` 或 `tests/alert/` | `test_xxx.py` |
| 端到端验证 | `scripts/verify_xxx.py` | `verify_*.py` |

共享 fixture 在根目录 [conftest.py](../conftest.py)：
`temp_db` / `mock_bot` / `mock_llm_api` / `temp_config` / `temp_env`。

## ⚠️ 不要再做的事

- ❌ 根目录写 `_test_xxx.py` / `_check_xxx.py` / `_debug_xxx.py`
- ❌ 再建新的历史测试堆放目录
- ❌ 把普通测试放在 `scripts/` 目录（仅 `verify_*` 端到端脚本例外）
