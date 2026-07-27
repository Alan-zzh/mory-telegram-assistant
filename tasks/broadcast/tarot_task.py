"""
tasks/broadcast/tarot_task.py - 每日塔罗搭讪任务

负责每日 15:00 以 30% 概率向群里活跃用户发起塔罗搭讪。
"""

import html
import random
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import TaskAbort
from tasks.support.message_templates import MessageTemplates

logger = get_logger("tasks.broadcast.tarot")

_CST = timezone(timedelta(hours=8))

_TAROT_DAILY_CACHE: Dict[str, Dict] = {}
_TAROT_CACHE_LAST_DATE: str = ""
_TAROT_CACHE_MAX_SIZE = 500


def _generate_tarot_data(seed_uid: int) -> Dict:
    """根据用户 ID 生成稳定的塔罗数据（牌名预设，其余由 AI 生成）。"""
    rng = random.Random(seed_uid)
    themes = ["整体运势", "爱情运势", "财运", "工作运", "健康运", "桃花运"]
    fortune_theme = rng.choice(themes)
    major = ["愚者", "魔术师", "女祭司", "女皇", "皇帝", "教皇", "恋人", "战车",
             "力量", "隐士", "命运之轮", "正义", "吊人", "死神", "节制", "恶魔",
             "塔", "星星", "月亮", "太阳", "审判", "世界"]
    suits = ["权杖", "圣杯", "宝剑", "金币"]
    card_name = rng.choice(major + [f"{s}{rng.randint(1, 10)}" for s in suits])
    card_position = rng.choice(["正位", "逆位"])
    return {
        "theme": fortune_theme,
        "card": card_name,
        "position": card_position,
        "seed": seed_uid,
    }


def _get_tarot_cache(uid: int, dt: datetime) -> Dict:
    """获取/生成某用户当日的塔罗运势（北京时间）。"""
    global _TAROT_DAILY_CACHE, _TAROT_CACHE_LAST_DATE
    cst_now = dt.astimezone(_CST)
    date_key = cst_now.strftime("%Y-%m-%d")

    if date_key != _TAROT_CACHE_LAST_DATE:
        _TAROT_DAILY_CACHE = {}
        _TAROT_CACHE_LAST_DATE = date_key

    if len(_TAROT_DAILY_CACHE) >= _TAROT_CACHE_MAX_SIZE:
        keys = list(_TAROT_DAILY_CACHE.keys())
        for k in random.sample(keys, len(keys) // 5):
            del _TAROT_DAILY_CACHE[k]
        logger.debug(f"🎴 塔罗缓存触发LRU淘汰，当前大小={len(_TAROT_DAILY_CACHE)}")

    cache_key = f"{uid}_{date_key}"
    if cache_key not in _TAROT_DAILY_CACHE:
        _TAROT_DAILY_CACHE[cache_key] = _generate_tarot_data(uid)
    return _TAROT_DAILY_CACHE[cache_key]


def _parse_tarot_ai_response(ai_response: str, tarot: Dict) -> Dict:
    """解析 AI 返回的塔罗内容。"""
    lines = ai_response.strip().split('\n')
    full_text = ai_response.strip()

    result = {
        "theme": tarot['theme'],
        "card": tarot['card'],
        "position": tarot['position'],
        "mood": "✨ 今日牌面呈现吉祥之象",
        "meaning": "今日运势平稳，保持积极心态...",
        "advice": "保持好心情，顺势而为",
        "result": "会有好事发生",
        "color": None,
        "dir": None,
        "nums": None,
        "star": None,
        "time": None,
    }

    mood_match = re.search(r'(?:牌面描述?|[:：].*?)[:：]\s*(.+?)(?:\n|$)', full_text)
    if mood_match:
        result["mood"] = mood_match.group(1).strip()
    else:
        for line in lines:
            if ('🌟' in line or '✨' in line) and len(line) > 15:
                result["mood"] = line.strip()
                break

    meaning_match = re.search(r'(?:今日)?(?:解读?|💫|📖)[:：]\s*(.+?)(?:\n|$)', full_text)
    if meaning_match:
        result["meaning"] = meaning_match.group(1).strip()
    else:
        candidates = [l.strip() for l in lines if 30 < len(l.strip()) < 100]
        if candidates:
            result["meaning"] = candidates[0]

    advice_match = re.search(r'(?:今日)?(?:建议?|💡|🌱)[:：]\s*(.+?)(?:\n|$)', full_text)
    if advice_match:
        result["advice"] = advice_match.group(1).strip()
    else:
        for line in lines:
            if len(line.strip()) < 30 and ('💡' in line or '🌱' in line):
                result["advice"] = line.strip()
                break

    color_match = re.search(r'(?:幸运)?(?:色|🌈|🎨)[:：]\s*(\S{1,4})', full_text)
    if not color_match:
        colors = ["白色", "黑色", "红色", "蓝色", "绿色", "紫色", "粉色", "金色", "橙色", "黄色", "青色", "棕色"]
        for c in colors:
            if c in full_text:
                result["color"] = c
                break
    if color_match:
        result["color"] = color_match.group(1).strip()
    if not result["color"]:
        result["color"] = "蓝色"

    dir_match = re.search(r'(?:幸运)?(?:方位?|方向?|📍|🧭)[:：]\s*(\S{1,4})', full_text)
    if not dir_match:
        dirs = ["东方", "西方", "南方", "北方", "东南", "东北", "西南", "西北", "东", "南", "西", "北"]
        for d in dirs:
            if d in full_text:
                result["dir"] = d
                break
    if dir_match:
        result["dir"] = dir_match.group(1).strip()
    if not result["dir"]:
        result["dir"] = "东方"

    nums = re.findall(r'\b(\d{1,3})\b', full_text)
    nums = [n for n in nums if 1 <= int(n) <= 99][:3]
    if len(nums) >= 3:
        result["nums"] = f"{nums[0]}, {nums[1]}, {nums[2]}"
    else:
        result["nums"] = "7, 23, 45"

    star_match = re.search(r'(?:贵人)?(?:星座?|⭐|🌟)[:：]\s*(\S{2,4}座?)', full_text)
    if not star_match:
        stars = ["白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座",
                 "天秤座", "天蝎座", "射手座", "摩羯座", "水瓶座", "双鱼座",
                 "白羊", "金牛", "双子", "巨蟹", "狮子", "处女",
                 "天秤", "天蝎", "射手", "摩羯", "水瓶", "双鱼"]
        for s in stars:
            if s in full_text:
                result["star"] = s if "座" in s else s + "座"
                break
    if star_match:
        result["star"] = star_match.group(1).strip()
    if not result["star"]:
        result["star"] = "天秤座"

    time_match = re.search(r'(?:幸运)?(?:时段?|时间?|⏰|🕐)[:：]\s*(.+?)(?:\n|$)', full_text)
    if time_match:
        result["time"] = time_match.group(1).strip()
    else:
        for line in lines:
            if any(x in line for x in ['点', '时', '早', '午', '晚', '上', '下']):
                if len(line.strip()) < 15:
                    result["time"] = line.strip()
                    break
    if not result["time"]:
        result["time"] = "上午9-11点"

    return result


def _get_fallback_tarot_content(tarot: Dict) -> Dict:
    """备用塔罗内容（AI 失败时使用）。"""
    rng = random.Random(tarot.get('seed', 42))
    meanings = {
        "正位": ["内心充满希望，适合开展新计划", "感情上可能有惊喜",
                "财运上升，适合投资", "人际关系和谐"],
        "逆位": ["有些迷茫，需要冷静思考", "感情上可能有误会",
                "财务上要谨慎", "工作上可能遇小阻碍"]
    }
    colors = ["白色", "黑色", "红色", "蓝色", "绿色", "紫色", "粉色", "金色"]
    dirs = ["东方", "西方", "南方", "北方", "东南", "东北"]
    stars = ["白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座", "天秤座", "天蝎座"]
    return {
        "theme": tarot['theme'],
        "card": tarot['card'],
        "position": tarot['position'],
        "mood": "✨ 牌面呈现吉祥之象",
        "meaning": rng.choice(meanings[tarot['position']]),
        "advice": rng.choice(["大胆尝试新事物", "多倾听少说话", "主动出击别犹豫"]),
        "result": rng.choice(["会有意外收获", "会有贵人相助", "会有好运降临"]),
        "color": rng.choice(colors),
        "dir": rng.choice(dirs),
        "nums": f"{rng.randint(1, 99)}, {rng.randint(1, 99)}, {rng.randint(1, 99)}",
        "star": rng.choice(stars),
        "time": rng.choice(["早上9-11点", "下午15-17点", "晚上19-21点"]),
    }


def _generate_tarot_ai_content(tarot: Dict, seed: int, rm) -> Dict:
    """调用 AI 生成完整的塔罗运势内容。"""
    seed_for_ai = seed or random.randint(100000, 999999)
    prompt = f"""你是Mory，一个撩人的塔罗师，像闺蜜一样亲切。

根据以下信息生成塔罗运势，全部要浓缩在一屏能看完的长度：

【运势类型】：{tarot['theme']}
【塔罗牌】：{tarot['card']} {tarot['position']}

请按以下格式生成：

1. 牌面描述（一句话，15-25字，有画面感，带一个emoji）
2. 今日解读（1-2句话，30-40字，有故事感，带emoji）
3. 今日建议（一句话，15字以内，带emoji）
4. 幸运色（只写颜色，2-4字）

其他信息（幸运方位、幸运数字、贵人星座、幸运时段）可以自由发挥，用自然的方式融入解读中，不需要单独列出。

seed={seed_for_ai}
要求：
- 语气温柔亲切，像闺蜜聊天
- 禁止空话套话，用画面感语言
- 解读要有故事感，别超过40字
- 每次seed不同，内容必须不同"""

    try:
        with rm.locked('ai'):
            ai_response = rm.ai.ask(prompt, mode="tarot_interpret", seed=seed_for_ai)
        if not ai_response or len(ai_response) < 50:
            raise ValueError("AI返回内容太短")
        return _parse_tarot_ai_response(ai_response, tarot)
    except Exception as e:
        logger.warning(f"AI生成塔罗内容失败，使用备用方案: {e}")
        return _get_fallback_tarot_content(tarot)


def _get_fallback_hook(theme: str, uname: str) -> str:
    """AI 失败时的转化钩子。"""
    return MessageTemplates.get_tarot_hook()


class TarotTask(BaseTask):
    """旧版定向塔罗搭讪；默认关闭，避免与新栏目重复或点名打扰。"""

    @property
    def task_id(self) -> str:
        return "tarot_flirt"

    def schedule(self) -> List[Dict[str, Any]]:
        cfg = self.rm.config.get("MYSTIC_BROADCAST_CONFIG", {}) if isinstance(self.rm.config, dict) else {}
        if not bool(cfg.get("legacy_targeted_tarot_enabled", False)):
            return []
        return [{
            "job_id": "tarot_flirt",
            "trigger": "cron",
            "hour": 15,
            "minute": 0,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 60,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            with TaskTransactionManager("tarot_flirt", self.rm.db, resources=['ai', 'bot'], min_interval_sec=7200) as tx:
                if not tx.claimed:
                    return
                if random.random() > 0.30:
                    raise TaskAbort("30%概率跳过", expected=True)

                gid = self.rm.config.get("GROUP_ID", 0)
                admin_id = self.rm.config.get("ADMIN_ID", 0)
                if not gid or not admin_id:
                    raise TaskAbort("群ID或管理员ID为0", expected=True)

                logger.info("🎴 触发每日塔罗搭讪任务")

                try:
                    members = self.rm.bot.get_chat_member_count(gid)
                    if members < 5:
                        raise TaskAbort("群成员太少", expected=True)
                except TaskAbort:
                    raise
                except Exception as e:
                    logger.debug(f"获取群成员数失败: {e}")

                recent_users = {}
                try:
                    ts_1h_ago = int(time.time()) - 3600
                    active_users = self.rm.db.get_active_users(ts_1h_ago)
                    for uid, uname, keywords in active_users[:20]:
                        if uid != admin_id:
                            recent_users[uid] = (uname or "哥哥", keywords or "")
                except Exception as e:
                    logger.debug(f"获取活跃用户失败：{e}")
                    raise TaskAbort("获取活跃用户失败")

                if not recent_users:
                    raise TaskAbort("无活跃用户", expected=True)

                uid, (uname, user_msg) = random.choice(list(recent_users.items()))
                logger.info(f"🎴 塔罗搭讪目标: {uname} 说: {user_msg[:30]}")

                tarot_base = _get_tarot_cache(uid, datetime.now(_CST))
                tarot = _generate_tarot_ai_content(tarot_base, uid, self.rm)

                opener_text = random.choice(['哥哥～', '嘿～', '在吗～', '哎～', '诶～'])
                opener_action = random.choice(['看到你说的', '刷到你这句', '你刚才说'])

                convert_seed = random.randint(10000, 99999)
                convert_prompt = f"""你是Mory，刚给「{uname}」测了「{tarot['theme']}」。
写一句自然的后续引导，让对方想继续聊。
要求：20-30字，像闺蜜私聊，勾起好奇心，不提商业词。
seed={convert_seed}"""

                try:
                    convert_hint = self.rm.ai.ask(convert_prompt, mode="convert_hook", seed=convert_seed)
                    if not convert_hint or len(convert_hint) < 10:
                        convert_hint = _get_fallback_hook(tarot['theme'], uname)
                except Exception:
                    convert_hint = _get_fallback_hook(tarot['theme'], uname)

                short_mode = random.random() < 0.4

                safe_uname = html.escape(str(uname))
                safe_opener = html.escape(str(opener_text))
                safe_action = html.escape(str(opener_action))
                safe_user_msg = html.escape(str(user_msg[:10]))
                safe_card = html.escape(str(tarot['card']))
                safe_position = html.escape(str(tarot['position']))
                safe_theme = html.escape(str(tarot['theme']))
                safe_meaning = html.escape(str(tarot['meaning']))
                safe_advice = html.escape(str(tarot['advice']))
                safe_color = html.escape(str(tarot['color']))
                safe_dir = html.escape(str(tarot['dir']))
                safe_nums = html.escape(str(tarot['nums']))
                safe_star = html.escape(str(tarot['star']))
                safe_time = html.escape(str(tarot['time']))
                safe_convert = html.escape(str(convert_hint))

                if short_mode:
                    html_reply = f"""🎴 <b>{safe_card} {safe_position}</b>

@{safe_uname} {safe_opener} {safe_action}「{safe_user_msg}」~

📖 {safe_meaning}

🌈 {safe_color} · 📍 {safe_dir}

{safe_convert}"""
                else:
                    html_reply = f"""🎴 <b>{safe_theme}</b> · {safe_card} {safe_position}

@{safe_uname} {safe_opener} {safe_action}「{safe_user_msg}」~

📖 {safe_meaning}

💡 {safe_advice}

🌈 {safe_color} · 📍 {safe_dir} · 🔢 {safe_nums} · ⭐ {safe_star} · ⏰ {safe_time}

{safe_convert}"""

                try:
                    self.rm.bot.send_message(gid, html_reply, parse_mode="HTML")
                    logger.info(f"🎴 塔罗搭讪成功: @{uname}")
                except Exception as e:
                    logger.error(f"塔罗搭讪发送失败：{e}")
                    raise
        except TaskAbort:
            pass
        except Exception as e:
            logger.error(f"塔罗搭讪任务失败：{e}")
