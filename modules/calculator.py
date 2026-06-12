"""
计算器 - 安全的数学表达式计算

命令：
  /calc 表达式 → handle_calc
"""
import ast
import operator
from core.logging_util import get_logger

logger = get_logger("calculator")

# 安全的运算符映射
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# 安全的函数
_SAFE_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "int": int,
    "float": float,
}


class _SafeEval(ast.NodeVisitor):
    """安全的表达式求值器，只允许数学运算"""

    def visit(self, node):
        if isinstance(node, ast.Expression):
            return self.visit(node.body)
        elif isinstance(node, ast.BinOp):
            left = self.visit(node.left)
            right = self.visit(node.right)
            op_type = type(node.op)
            if op_type in _SAFE_OPERATORS:
                return _SAFE_OPERATORS[op_type](left, right)
            raise ValueError(f"不支持的运算符: {op_type.__name__}")
        elif isinstance(node, ast.UnaryOp):
            operand = self.visit(node.operand)
            op_type = type(node.op)
            if op_type in _SAFE_OPERATORS:
                return _SAFE_OPERATORS[op_type](operand)
            raise ValueError(f"不支持的运算符: {op_type.__name__}")
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("只支持数字常量")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _SAFE_FUNCTIONS:
                args = [self.visit(arg) for arg in node.args]
                return _SAFE_FUNCTIONS[node.func.id](*args)
            raise ValueError(f"不支持的函数: {node.func.id if isinstance(node.func, ast.Name) else 'unknown'}")
        else:
            raise ValueError(f"不支持的表达式类型: {type(node).__name__}")


def handle_calc(bot, m, config, db):
    """计算数学表达式"""
    text = (m.text or "").strip()
    parts = text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(m, "❌ 用法：/calc 数学表达式\n💡 示例：/calc 2+3*4")
        return

    expr = parts[1].strip()
    # 限制表达式长度
    if len(expr) > 200:
        bot.reply_to(m, "❌ 表达式过长")
        return

    try:
        tree = ast.parse(expr, mode="eval")
        result = _SafeEval().visit(tree)
        # 格式化结果
        if isinstance(result, float) and result == int(result):
            result = int(result)
        bot.reply_to(m, f"🧮 {expr} = {result}")
    except ValueError as e:
        bot.reply_to(m, f"❌ 表达式错误：{e}")
    except ZeroDivisionError:
        bot.reply_to(m, "❌ 除数不能为零")
    except Exception as e:
        bot.reply_to(m, f"❌ 计算失败：{e}")
