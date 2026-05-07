import requests, json

TOKEN = '8009972336:AAE9n2Syu6rwAW4Np077_S4X-NwibFbujdY'

# Since private channels can't be resolved via Bot API, let's try to get chat info
# by sending a message to the channel first (if bot is admin)
# Or check if we can get chat info through other means

# Method 1: Check if we can get chat info through the group's linked channels
print("=== Method 1: Check group linked channels ===")
r = requests.get(f'https://api.telegram.org/bot{TOKEN}/getChat?chat_id=-1003004701688', timeout=10)
d = r.json()
if d.get('ok'):
    ch = d['result']
    print(f"Group: {ch['title']}")
    print(f"Linked chat: {ch.get('linked_chat_id', 'None')}")
    print(f"Linked chat type: {ch.get('linked_chat_type', 'None')}")
    # Check for other fields
    for key in ['invite_link', 'permissions', 'slow_mode_delay', 'message_auto_delete_time']:
        if key in ch:
            print(f"{key}: {ch[key]}")
else:
    print(f"FAIL: {d}")

# Method 2: Try to get chat info using the exact format that works for moryselect
print("\n=== Method 2: Check moryselect details ===")
r = requests.get(f'https://api.telegram.org/bot{TOKEN}/getChat?chat_id=@moryselect', timeout=10)
d = r.json()
if d.get('ok'):
    ch = d['result']
    print(f"Channel: {ch['title']} (ID: {ch['id']})")
    print(f"Type: {ch['type']}")
    print(f"Linked chat: {ch.get('linked_chat_id', 'None')}")
    # Check all fields
    for key, val in ch.items():
        if key not in ['photo', 'pinned_message', 'available_reactions', 'accepted_gift_types']:
            print(f"  {key}: {val}")
else:
    print(f"FAIL: {d}")

# Method 3: Try to get chat info through admin status
print("\n=== Method 3: Check bot admin status in known chats ===")
known_chats = [
    -1003004701688,  # Group
    -1003875429116,  # moryselect
]
for cid in known_chats:
    r = requests.get(f'https://api.telegram.org/bot{TOKEN}/getChatAdministrators?chat_id={cid}', timeout=10)
    d = r.json()
    if d.get('ok'):
        admins = d['result']
        bot_admin = any(a.get('user',{}).get('is_bot') for a in admins)
        print(f"Chat {cid}: {len(admins)} admins, bot is admin: {bot_admin}")
        # Print all admin users
        for a in admins:
            u = a.get('user', {})
            if u.get('is_bot'):
                print(f"  Bot admin: {u.get('first_name','?')} (ID: {u['id']})")
    else:
        print(f"Chat {cid}: FAIL - {d.get('description', '?')}")

# Method 4: Try to get chat info using the invite link in a different way
print("\n=== Method 4: Try alternative invite link formats ===")
# Try with just the hash part
hashes = ['10hCfd6BhAAzOTE1', 'iIRwMflvZRU5NDRl', 'jngDULsEwQBjZjVl']
for h in hashes:
    # Try different formats
    formats = [
        f'+{h}',
        f'https://t.me/+{h}',
        f't.me/+{h}',
        h,
    ]
    for fmt in formats:
        r = requests.get(f'https://api.telegram.org/bot{TOKEN}/getChat?chat_id={fmt}', timeout=10)
        d = r.json()
        if d.get('ok'):
            ch = d['result']
            print(f"OK [{h}] [{fmt}]: {ch['title']} -> {ch['id']}")
            break
    else:
        print(f"FAIL [{h}]: All formats failed")

# Method 5: Check if we can get chat info through the bot's own chat list
print("\n=== Method 5: Check bot's chat list through getUpdates ===")
r = requests.get(f'https://api.telegram.org/bot{TOKEN}/getUpdates?limit=100&allowed_updates=["message","channel_post","my_chat_member","chat_member"]', timeout=10)
d = r.json()
if d.get('ok') and d['result']:
    chats_seen = {}
    for u in d['result']:
        # Check message
        msg = u.get('message')
        if msg:
            chat = msg.get('chat', {})
            cid = chat.get('id')
            if cid:
                chats_seen[cid] = chat.get('title', '?')
        # Check channel_post
        cp = u.get('channel_post')
        if cp:
            chat = cp.get('chat', {})
            cid = chat.get('id')
            if cid:
                chats_seen[cid] = chat.get('title', '?')
        # Check chat_member updates
        cm = u.get('chat_member')
        if cm:
            chat = cm.get('chat', {})
            cid = chat.get('id')
            if cid:
                chats_seen[cid] = chat.get('title', '?')
        # Check my_chat_member updates
        mcm = u.get('my_chat_member')
        if mcm:
            chat = mcm.get('chat', {})
            cid = chat.get('id')
            if cid:
                chats_seen[cid] = chat.get('title', '?')
    
    print(f"Chats seen in updates ({len(chats_seen)}):")
    for cid, title in chats_seen.items():
        print(f"  {cid}: {title}")
else:
    print("No recent updates")
