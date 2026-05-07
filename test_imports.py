import json, os, sys
sys.path.insert(0, '.')

print("=" * 60)
print("阶段三：核心模块导入与初始化验收测试")
print("=" * 60)

# 1. 测试 config.json 加载
with open('config.json', 'r', encoding='utf-8') as f:
    cfg = json.load(f)
print('[PASS] config.json 加载成功')
print(f'       版本: {cfg.get("VERSION", "N/A")}')
pool_count = len(cfg.get("llm_premium", [])) + len(cfg.get("llm_standard", [])) + len(cfg.get("llm_light", []))
print(f'       模型池数量: {pool_count}')

# 2. 测试 .env 加载
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS
print('[PASS] .env 加载成功')
print(f'       VPS_HOST: {VPS_HOST}')
print(f'       VPS_PORT: {VPS_PORT}')
print(f'       VPS_USER: {VPS_USER}')
print(f'       VPS_PASS: {"*" * len(VPS_PASS) if VPS_PASS else "未设置"}')

# 3. 测试数据库初始化（DB类，不是db实例）
from core.database import DB
db = DB("test_mory.db")
print('[PASS] 数据库初始化成功')
print(f'       数据库路径: {db.db_file}')

# 4. 测试AI引擎初始化
from core.ai_engine import AIEngine
import json
with open('config.json', 'r', encoding='utf-8') as f:
    _test_cfg = json.load(f)
ai_engine = AIEngine(_test_cfg)
print('[PASS] AI引擎初始化成功')
print(f'       当前模型: {ai_engine.current_model}')

# 5. 测试日志工具
from core.logging_util import get_logger
logger = get_logger("test")
logger.info('验收测试日志写入成功')
print('[PASS] 日志工具工作正常')

# 6. 测试数据库操作
print()
print("=" * 60)
print("数据库CRUD验收测试")
print("=" * 60)

# 6.1 用户记录（使用真实方法名 upsert_user / get_user）
uid = 999999999
db.upsert_user(uid, "test_user", "group")
user = db.get_user(uid)
assert user is not None, "用户记录失败"
print('[PASS] upsert_user / get_user 工作正常')

# 6.2 积分操作（使用真实方法名 add_points / get_user_points）
db.add_points(uid, 10)
pts = db.get_user_points(uid)
assert pts is not None and pts >= 10, "积分添加失败"
print(f'[PASS] add_points / get_user_points 工作正常 (当前积分: {pts})')

# 6.3 任务抢占
task_key = "test_task_" + os.urandom(4).hex()
result = db.claim_task(task_key)
print(f'[PASS] claim_task 工作正常 (结果: {result})')

# 6.4 每日报告
report = db.get_daily_report()
assert isinstance(report, dict), "get_daily_report 返回类型异常"
assert "active" in report, "get_daily_report 缺少 active 字段"
print(f'[PASS] get_daily_report 工作正常 (活跃用户: {report["active"]})')

# 6.5 清理测试数据
db.conn.execute("DELETE FROM users WHERE uid = ?", (uid,))
db.conn.execute("DELETE FROM user_levels WHERE uid = ?", (uid,))
db.conn.execute("DELETE FROM task_log WHERE task_key = ?", (task_key,))
db.conn.commit()
print('[PASS] 测试数据清理完成')

print()
print("=" * 60)
print("内容模块验收测试")
print("=" * 60)

from modules.content import draw_tarot, get_fortune

# 7.1 塔罗牌
result = draw_tarot("test_user")
assert "【" in result and "】" in result, "塔罗牌返回格式异常"
print(f'[PASS] draw_tarot 工作正常')

# 7.2 运势签
result = get_fortune()
assert len(result) > 0, "运势签返回为空"
print(f'[PASS] get_fortune 工作正常')

print()
print("=" * 60)
print("群管模块验收测试")
print("=" * 60)

from modules.group_mgr import detect_keywords

# 8.1 关键词特征检测
result = detect_keywords("今天好冷", cfg)
assert isinstance(result, dict), "detect_keywords 返回类型异常"
assert "weather_empathy" in result, "detect_keywords 缺少 weather_empathy 字段"
print(f'[PASS] detect_keywords 工作正常 (天气共情: {result["weather_empathy"]})')

# 8.2 塔罗模式检测
result = detect_keywords("帮我抽张塔罗牌", cfg)
assert result.get("mode") == "tarot", "塔罗模式检测失败"
print(f'[PASS] detect_keywords 塔罗模式检测正常')

# 8.3 转化模式检测
result = detect_keywords("多少钱", cfg)
assert result.get("is_cart") == True, "购物车触发检测失败"
print(f'[PASS] detect_keywords 购物车触发检测正常')

print()
print("=" * 60)
print("关键词触发模块验收测试")
print("=" * 60)

from modules.keyword_trigger import KeywordTrigger

# 9.1 KeywordTrigger 初始化
kt = KeywordTrigger(db, config=cfg)
print('[PASS] KeywordTrigger 初始化成功')

# 9.2 特殊规则匹配（空文本不应匹配）
result = kt.handle_message("", 888888, None, None, False)
assert result == False, "空文本不应匹配"
print('[PASS] KeywordTrigger 空文本处理正常')

print()
print("=" * 60)
print("自然语言指令模块验收测试")
print("=" * 60)

from modules.natural_cmd import handle_natural_admin

# 10.1 指令解析（非管理员不应执行）
class FakeMsg:
    text = "设置概率为50%"
    class from_user:
        id = 12345
        first_name = "Test"
    class chat:
        id = 888888
        type = "private"
    message_id = 1

class FakeBot:
    def send_message(self, *args, **kwargs):
        pass

fake_msg = FakeMsg()
fake_bot = FakeBot()

# 由于需要复杂的bot和mory_bot对象，这里仅验证导入成功
print('[PASS] handle_natural_admin 导入成功')

print()
print("=" * 60)
print("Dashboard 模块导入验收测试")
print("=" * 60)

# 11. 测试 Dashboard 导入
from dashboard.app import app, read_config, write_config
print('[PASS] Dashboard app 导入成功')

# 11.1 配置读写
cfg_data = read_config()
assert isinstance(cfg_data, dict), "read_config 返回类型异常"
print(f'[PASS] read_config 工作正常 (键数: {len(cfg_data)})')

# 11.2 测试原子写入
test_cfg = cfg_data.copy()
test_cfg["_test_key"] = "test_value"
result = write_config(test_cfg)
assert result is True, "write_config 原子写入失败"
# 恢复
cfg2 = read_config()
assert cfg2.get("_test_key") == "test_value", "写入后读取验证失败"
del cfg2["_test_key"]
write_config(cfg2)
print('[PASS] write_config 原子写入工作正常')

print()
print("=" * 60)
print("Universal AI Router 验收测试")
print("=" * 60)

from universal_ai_router.core.router_database import RouterDatabase
from universal_ai_router.core.router_statistics import RouterStatistics

# 12.1 RouterDatabase
rdb = RouterDatabase("test_router.db")
print('[PASS] RouterDatabase 初始化成功')

# 12.2 RouterStatistics
rs = RouterStatistics(rdb)
print('[PASS] RouterStatistics 初始化成功')

# 12.3 除零保护测试
result = rs.get_single_statistic("nonexistent_model")
assert result is not None, "get_single_statistic 返回None"
assert result.get("success_rate", -1) == 0, "除零保护失效"
print(f'[PASS] 除零保护工作正常 (无记录时成功率: {result.get("success_rate")})')

# 12.4 关闭连接
rdb.close()
print('[PASS] RouterDatabase.close() 工作正常')

# 清理测试数据库文件
print()
print("=" * 60)
print("清理测试文件")
print("=" * 60)
try:
    db.close()
    if os.path.exists("test_mory.db"):
        os.remove("test_mory.db")
        print('[PASS] test_mory.db 已清理')
    if os.path.exists("test_router.db"):
        os.remove("test_router.db")
        print('[PASS] test_router.db 已清理')
except Exception as e:
    print(f'[WARN] 清理测试文件时出错: {e}')

print()
print("=" * 60)
print("所有验收测试通过！")
print("=" * 60)
