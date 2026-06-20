# Mory小助理 测试目录

> **最后整理**：2026-06-02（v5.12.1 根目录 47 个 `_*.py` 文件归档至此）
> **总原则**：所有测试代码统一放 `tests/`，根目录**禁止**出现 `_*.py` 临时测试文件
> **详细规范**：[AGENTS.md](../AGENTS.md) F1 铁律

---

## 📁 目录结构

```
tests/
├── README.md           # 本文件
├── integration/        # 集成测试（端到端、多模块协作）
└── unit/               # 单元测试（单函数/单模块）
```

## 🧹 历史清理说明

- 旧的一次性 `_*.py` 调试/测试脚本已经不再作为仓库资产保留。
- 这类脚本如果仍有价值，应重写为：
  - `tests/unit/test_xxx.py`
  - `tests/integration/test_xxx_integration.py`
  - 或 `scripts/verify_xxx.py`
- 以后不再新增 `tests/_archive/` 这种长期堆放区，避免继续沉积失真的旧脚本。

## 🆕 新测试如何写？

| 类型 | 位置 | 命名 |
|------|------|------|
| 单元测试 | `tests/unit/test_xxx.py` | `test_xxx.py` |
| 集成测试 | `tests/integration/test_xxx_integration.py` | `test_xxx_integration.py` |
| 端到端验证 | `tests/integration/verify_xxx.py` | `verify_xxx.py` |

> **注意**：端到端验证脚本也可放在 `scripts/`（如 `scripts/verify_orphan_cleanup.py`），按 F2 铁律。

## ⚠️ 不要再做的事

- ❌ 根目录写 `_test_xxx.py` / `_check_xxx.py` / `_debug_xxx.py`
- ❌ 再建新的历史测试堆放目录
- ❌ 把测试放在 `scripts/` 目录（除非叫 `verify_*` 端到端脚本）

## 🔗 相关

- [AGENTS.md](../AGENTS.md) F1 铁律（测试位置）
- [AGENTS.md](../AGENTS.md) F2 铁律（工具脚本位置）
- [AGENTS.md](../AGENTS.md) F5 铁律（根目录禁临时文件）
- [scripts/verify_orphan_cleanup.py](../scripts/verify_orphan_cleanup.py) — 端到端验证样例
