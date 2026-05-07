import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

BASE = os.path.dirname(os.path.abspath(__file__))
PY = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"

print("=" * 60)
print("Phase 3: Core Module Import & Init Verification")
print("=" * 60)

passed = 0
failed = 0

def check(name, func):
    global passed, failed
    try:
        func()
        print(f"[PASS] {name}")
        passed += 1
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
        failed += 1

def t1():
    from core.database import DB
    db = DB(os.path.join(BASE, "test_mory.db"))
    db.upsert_user(999999999, "test_user", "group")
    user = db.get_user(999999999)
    assert user is not None
    db.add_points(999999999, 10)
    pts = db.get_user_points(999999999)
    assert pts is not None and pts >= 10
    task_key = "test_task_abc123"
    result = db.claim_task(task_key)
    report = db.get_daily_report()
    assert isinstance(report, dict) and "active" in report
    db.conn.execute("DELETE FROM users WHERE uid = 999999999")
    db.conn.execute("DELETE FROM user_levels WHERE uid = 999999999")
    db.conn.execute("DELETE FROM task_log WHERE task_key = ?", (task_key,))
    db.conn.commit()
    db.close()
check("DB: upsert_user/get_user/add_points/get_user_points/claim_task/get_daily_report", t1)

def t2():
    from core.token_statistics import TokenStatistics
    ts = TokenStatistics(os.path.join(BASE, "test_router.db"))
    daily = ts.get_daily_statistic()
    assert isinstance(daily, dict)
    ts.close()
check("TokenStatistics: init + get_daily_statistic + close", t2)

def t3():
    from universal_ai_router.core.router_database import RouterDatabase
    from universal_ai_router.core.router_statistics import RouterStatistics
    rdb = RouterDatabase(os.path.join(BASE, "test_router2.db"))
    rs = RouterStatistics(rdb)
    result = rs.get_single_statistic(99999)
    rdb.close()
check("RouterDatabase + RouterStatistics: init + get_single_statistic + close", t3)

def t4():
    from modules.content import draw_tarot, get_fortune
    result = draw_tarot("test_user")
    assert "\u3010" in result and "\u3011" in result
    result = get_fortune()
    assert len(result) > 0
check("Content: draw_tarot + get_fortune", t4)

def t5():
    from modules.group_mgr import detect_keywords
    with open(os.path.join(BASE, "config.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)
    result = detect_keywords("\u4eca\u5929\u597d\u51b7", cfg)
    assert isinstance(result, dict) and "weather_empathy" in result
    result2 = detect_keywords("\u5e2e\u6211\u62bd\u5f20\u5854\u7f57\u724c", cfg)
    assert result2.get("mode") == "tarot"
check("GroupMgr: detect_keywords (weather + tarot)", t5)

def t6():
    from core.database import DB
    from modules.keyword_trigger import KeywordTrigger
    db = DB(os.path.join(BASE, "test_mory.db"))
    with open(os.path.join(BASE, "config.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)
    kt = KeywordTrigger(db, config=cfg)
    result = kt.handle_message("", 888888, None, None, False)
    assert result == False
    db.close()
check("KeywordTrigger: init + handle_message(empty)", t6)

def t7():
    from modules.natural_cmd import handle_natural_admin
check("NaturalCmd: handle_natural_admin import", t7)

def t8():
    from dashboard.app import app, read_config, write_config
    cfg_data = read_config()
    assert isinstance(cfg_data, dict)
    test_cfg = cfg_data.copy()
    test_cfg["_test_key"] = "test_value"
    result = write_config(test_cfg)
    assert result is True
    cfg2 = read_config()
    assert cfg2.get("_test_key") == "test_value"
    del cfg2["_test_key"]
    write_config(cfg2)
check("Dashboard: app + read_config + write_config (atomic)", t8)

def t9():
    from core.logging_util import get_logger
    logger = get_logger("test")
    logger.info("verification test log")
check("LoggingUtil: get_logger", t9)

def t10():
    from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS
    assert isinstance(VPS_HOST, str)
check("VPSConfig: VPS_HOST/VPS_PORT/VPS_USER/VPS_PASS", t10)

def t11():
    from core.ai_engine import AIEngine
    assert AIEngine is not None
check("AIEngine: import only (no init - requires API key)", t11)

for f in ["test_mory.db", "test_router.db", "test_router2.db"]:
    p = os.path.join(BASE, f)
    if os.path.exists(p):
        os.remove(p)

print()
print("=" * 60)
if failed == 0:
    print(f"ALL {passed} TESTS PASSED!")
else:
    print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 60)
