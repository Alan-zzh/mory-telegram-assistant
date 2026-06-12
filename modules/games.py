"""
群组互动游戏模块

功能：真心话大冒险、猜数字、骰子、随机选择
触发词和命令见各函数说明。
"""

import random
import time
from threading import Lock
from core.logging_util import get_logger

logger = get_logger("games")

# ─────────────────────── 真心话题库 ─────────────────────────────────
TRUTH_QUESTIONS = [
    "你最近一次说谎是什么时候？关于什么？",
    "你手机里最不想让别人看到的是什么？",
    "你暗恋过谁？持续了多久？",
    "你做过最疯狂的事是什么？",
    "你最害怕失去什么？",
    "你最近一次哭是因为什么？",
    "你有没有偷偷翻过别人的手机？",
    "你最想对群里谁说一句心里话？",
    "你觉得自己最大的缺点是什么？",
    "你有没有在背后说过群里某人的坏话？",
    "你最想回到人生的哪个时刻？为什么？",
    "你做过最尴尬的事是什么？",
    "你现在最想见的人是谁？",
    "你有没有假装没看到某人的消息？",
    "你最近一次心动是什么时候？",
    "你最不敢让父母知道的一件事是什么？",
    "你有没有同时喜欢过两个人？",
    "你觉得自己最迷人的地方是什么？",
    "你做过最对不起别人的事是什么？",
    "你有没有偷偷存过谁的合照？",
    "你最想删掉的一段记忆是什么？",
    "你有没有为了某个人改变过自己？",
    "你最近一次心跳加速是因为什么？",
    "你有没有在深夜翻过前任的社交主页？",
    "你最想和群里谁交换人生一天？",
    "你有没有对谁说过违心的话？",
    "你觉得自己最像哪个影视角色？",
    "你有没有因为一个人改变过自己的计划？",
    "你最想对五年前的自己说什么？",
    "你有没有在公共场合做过特别丢脸的事？",
    "你心里藏得最深的秘密是什么？",
]

# ─────────────────────── 大冒险题库 ─────────────────────────────────
DARE_TASKS = [
    "给你右边的人发一条语音说'我想你了'",
    "在群里发一张自拍",
    "用最肉麻的话夸群里一个人",
    "模仿一个动物叫声发语音",
    "说出你最近的一个秘密",
    "给你最近聊天的人发一句'我喜欢你'",
    "在群里发一段10秒的唱歌语音",
    "用最搞笑的表情包回复上一条消息",
    "说出你手机里最近一张照片的内容",
    "在群里发一句土味情话",
    "给你左边的人起一个外号并解释原因",
    "在群里发一段绕口令语音",
    "说出你最近做的一个梦",
    "在群里用三个词形容自己",
    "给你最想聊天的人发一条'在吗？我有话想说'",
    "在群里分享你最近在听的歌",
    "用最夸张的方式在群里说早安",
    "在群里发你最近的一个愿望",
    "给你通讯录第一个人发一个表情包",
    "在群里说出你今天最开心的一件事",
    "模仿一个名人的经典台词发语音",
    "在群里发一段rap语音",
]

# ─────────────────────── 骰子emoji映射 ─────────────────────────────
DICE_EMOJI = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}

# ─────────────────────── 猜数字游戏状态 ─────────────────────────────
_guess_games = {}  # {chat_id: {"target": N, "attempts": 0, "expire": timestamp}}
_guess_lock = Lock()


def handle_truth_or_dare(bot, m, config, db):
    """真心话大冒险 - 触发词：真心话大冒险 / /truthordare / /tod"""
    if random.random() < 0.5:
        question = random.choice(TRUTH_QUESTIONS)
        bot.reply_to(m, f"🎭 真心话\n\n{question}")
    else:
        task = random.choice(DARE_TASKS)
        bot.reply_to(m, f"🎭 大冒险\n\n{task}")


def handle_guess_number(bot, m, config, db):
    """猜数字游戏 - 触发词：猜数字 / /guess"""
    chat_id = m.chat.id
    name = m.from_user.first_name or "玩家"

    # 清理过期游戏
    now = time.time()
    with _guess_lock:
        expired = [cid for cid, g in _guess_games.items() if now > g["expire"]]
        for cid in expired:
            del _guess_games[cid]

    # 开启新游戏
    target = random.randint(1, 100)
    with _guess_lock:
        _guess_games[chat_id] = {
            "target": target,
            "attempts": 0,
            "expire": now + 300,  # 5分钟后过期
        }

    bot.reply_to(m,
        f"🎲 {name} 开启了猜数字游戏！\n\n"
        f"我心里想了一个 1~100 的数字，来猜猜看吧～\n"
        f"直接发数字就行，5分钟内有效哦！")


def handle_guess_reply(bot, m, config, db):
    """
    猜数字的回复处理 - 当用户在猜数字游戏中发送数字时调用。
    返回 True 表示已处理（消费消息），False 表示不是猜数字消息。
    """
    if not m.text:
        return False

    chat_id = m.chat.id

    # 检查是否有进行中的游戏
    with _guess_lock:
        game = _guess_games.get(chat_id)
        if not game:
            return False

        now = time.time()
        if now > game["expire"]:
            del _guess_games[chat_id]
            return False

    # 尝试解析数字
    text = m.text.strip()
    try:
        guess = int(text)
    except ValueError:
        return False

    if guess < 1 or guess > 100:
        return False

    with _guess_lock:
        game = _guess_games.get(chat_id)
        if not game or now > game["expire"]:
            return False
        game["attempts"] += 1
        target = game["target"]
        attempts = game["attempts"]

    if guess == target:
        with _guess_lock:
            _guess_games.pop(chat_id, None)
        bot.reply_to(m,
            f"🎉 恭喜猜对了！答案就是 {target}！\n"
            f"你一共猜了 {attempts} 次～")
    elif guess > target:
        bot.reply_to(m, f"⬇️ 大了！再小一点～（第{attempts}次）")
    else:
        bot.reply_to(m, f"⬆️ 小了！再大一点～（第{attempts}次）")

    return True


def handle_dice(bot, m, config, db):
    """掷骰子 - 触发词：骰子 / /dice / 掷骰子"""
    result = random.randint(1, 6)
    emoji = DICE_EMOJI[result]
    bot.reply_to(m, f"🎲 掷骰子结果：{emoji} {result}")


def handle_choose(bot, m, config, db):
    """
    随机选择 - 触发词：选择 A还是B / /choose A,B,C
    支持用"还是"或","分隔选项
    """
    msg = m.text or ""

    # 提取选项部分
    if msg.startswith("/choose"):
        # /choose A,B,C 格式
        options_str = msg[len("/choose"):].strip()
        if "," in options_str:
            options = [o.strip() for o in options_str.split(",") if o.strip()]
        else:
            options = [o.strip() for o in options_str.split() if o.strip()]
    else:
        # "选择 A还是B还是C" 格式
        # 去掉开头的"选择"
        options_str = msg
        for prefix in ("选择",):
            if options_str.startswith(prefix):
                options_str = options_str[len(prefix):].strip()
                break

        if "还是" in options_str:
            options = [o.strip() for o in options_str.split("还是") if o.strip()]
        elif "," in options_str:
            options = [o.strip() for o in options_str.split(",") if o.strip()]
        else:
            options = [o.strip() for o in options_str.split() if o.strip()]

    # 过滤无效选项
    options = [o for o in options if o]

    if len(options) < 2:
        bot.reply_to(m, "⚠️ 至少需要2个选项哦！\n用法：选择 A还是B  或  /choose A,B,C")
        return

    chosen = random.choice(options)
    bot.reply_to(m, f"🎯 命运之轮转动中...\n\n选择了：**{chosen}**")
