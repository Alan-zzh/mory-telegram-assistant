#!/usr/bin/env python3
"""Test dashboard API endpoints"""
import requests, json

BASE = "http://localhost:5000"
s = requests.Session()

# Login
r = s.post(f"{BASE}/api/login", json={"password": "mory2026"})
print(f"Login: {r.json()}")

# Test stats overview
print("\n=== /api/stats/overview ===")
r = s.get(f"{BASE}/api/stats/overview")
data = r.json()
if data.get("ok"):
    d = data["data"]
    print(f"  Total users: {d.get('total_users')}")
    print(f"  Group msgs: {d.get('total_group_msgs')}")
    print(f"  Private msgs: {d.get('total_private_msgs')}")
    print(f"  Today active: {d.get('today_active')}")
    print(f"  Week active: {d.get('week_active')}")
    print(f"  Funnel: {d.get('conversion_funnel')}")
    print(f"  Level dist: {d.get('level_distribution')}")
    print(f"  Top users: {len(d.get('top_active_users', []))}")
    print(f"  Daily new: {d.get('daily_new_users')}")
else:
    print(f"  ERROR: {data}")

# Test group activity
print("\n=== /api/stats/group-activity ===")
r = s.get(f"{BASE}/api/stats/group-activity")
data = r.json()
if data.get("ok"):
    d = data["data"]
    print(f"  Hourly: {d.get('hourly_distribution')}")
    print(f"  Msg ratio: {d.get('message_ratio')}")
    print(f"  Activity tiers: {d.get('activity_tiers')}")
    print(f"  Conversion: {d.get('conversion_distribution')}")
else:
    print(f"  ERROR: {data}")

# Test users list
print("\n=== /api/stats/users ===")
r = s.get(f"{BASE}/api/stats/users?page=1&per_page=5")
data = r.json()
if data.get("ok"):
    d = data["data"]
    print(f"  Total: {d['pagination']['total']}")
    for u in d.get("users", [])[:3]:
        print(f"  - {u.get('name')} (uid:{u.get('uid')}) grp:{u.get('group_messages')} pri:{u.get('private_messages')}")
else:
    print(f"  ERROR: {data}")

# Test commands
print("\n=== /api/commands ===")
r = s.get(f"{BASE}/api/commands")
data = r.json()
if data.get("ok"):
    for cmd in data["data"][:5]:
        print(f"  - {cmd['label']} ({cmd['key']}): {str(cmd['value'])[:50]}...")
    print(f"  ... total {len(data['data'])} commands")
else:
    print(f"  ERROR: {data}")

print("\n=== ALL TESTS DONE ===")
