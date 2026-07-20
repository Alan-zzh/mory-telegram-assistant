"""娱乐功能模块
参考阿福后台：13个娱乐游戏（篮球、老虎机、炸金花、足球、飞镖、保龄球、牛牛、骰子快三、赛马、百家乐、21点、单骰、Emoji比赛）
"""
import random
from typing import Dict, Any, Optional

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

ENTERTAINMENT_GAMES_CONFIG = config.get('ENTERTAINMENT_GAMES_CONFIG', {
    'enabled': False,
    'games': {
        'basketball': {'enabled': False, 'bet_min': 1, 'bet_max': 100},
        'slot_machine': {'enabled': False, 'bet_min': 1, 'bet_max': 100},
        'poker': {'enabled': False, 'bet_min': 1, 'bet_max': 100},
        'football': {'enabled': False, 'bet_min': 1, 'bet_max': 100},
        'darts': {'enabled': False, 'bet_min': 1, 'bet_max': 100},
        'bowling': {'enabled': False, 'bet_min': 1, 'bet_max': 100},
        'niuniu': {'enabled': False, 'bet_min': 1, 'bet_max': 100},
        'dice_quick': {'enabled': False, 'bet_min': 1, 'bet_max': 100},
        'horse_racing': {'enabled': False, 'bet_min': 1, 'bet_max': 100},
        'baccarat': {'enabled': False, 'bet_min': 1, 'bet_max': 100},
        'blackjack': {'enabled': False, 'bet_min': 1, 'bet_max': 100},
        'single_dice': {'enabled': False, 'bet_min': 1, 'bet_max': 100},
        'emoji_race': {'enabled': False, 'bet_min': 1, 'bet_max': 100},
    },
})


class EntertainmentGamesModule:
    def __init__(self):
        self._compat = None

    async def play_basketball(self, chat_id: int, user_id: int, bet: int = 1) -> Dict[str, Any]:
        if not self._is_game_enabled('basketball'):
            return {'result': 'disabled', 'message': '🏀 篮球游戏未开启'}
        points = random.randint(0, 100)
        win = points >= 60
        multiplier = 2 if win else 0
        return self._format_game_result('basketball', chat_id, user_id, bet, win, multiplier,
                                       f'🏀 投篮得分: {points}! {"🎉 命中！" if win else "😅 未命中"}')

    async def play_slot_machine(self, chat_id: int, user_id: int, bet: int = 1) -> Dict[str, Any]:
        if not self._is_game_enabled('slot_machine'):
            return {'result': 'disabled', 'message': '🎰 老虎机未开启'}
        symbols = ['🍎', '🍊', '🍋', '🍇', '🍉', '⭐']
        reel1, reel2, reel3 = random.choices(symbols, k=3)
        if reel1 == reel2 == reel3:
            win = True
            multiplier = 10
        elif reel1 == reel2 or reel1 == reel3 or reel2 == reel3:
            win = True
            multiplier = 3
        else:
            win = False
            multiplier = 0
        return self._format_game_result('slot_machine', chat_id, user_id, bet, win, multiplier,
                                       f'🎰 [{reel1}][{reel2}][{reel3}]')

    async def play_poker(self, chat_id: int, user_id: int, bet: int = 1) -> Dict[str, Any]:
        if not self._is_game_enabled('poker'):
            return {'result': 'disabled', 'message': '🃏 炸金花未开启'}
        cards = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        suits = ['♠', '♥', '♣', '♦']
        hand = [(random.choice(cards), random.choice(suits)) for _ in range(3)]
        hand_str = ' '.join(f'{c}{s}' for c, s in hand)
        score = self._evaluate_poker_hand(hand)
        win = score >= 2
        multiplier = score * 2 if win else 0
        return self._format_game_result('poker', chat_id, user_id, bet, win, multiplier,
                                       f'🃏 你的牌: {hand_str}')

    async def play_football(self, chat_id: int, user_id: int, bet: int = 1) -> Dict[str, Any]:
        if not self._is_game_enabled('football'):
            return {'result': 'disabled', 'message': '⚽ 足球游戏未开启'}
        goals = random.randint(0, 5)
        win = goals >= 3
        multiplier = goals if win else 0
        return self._format_game_result('football', chat_id, user_id, bet, win, multiplier,
                                       f'⚽ 进球数: {goals}个!')

    async def play_darts(self, chat_id: int, user_id: int, bet: int = 1) -> Dict[str, Any]:
        if not self._is_game_enabled('darts'):
            return {'result': 'disabled', 'message': '🎯 飞镖游戏未开启'}
        score = random.randint(1, 180)
        win = score >= 100
        multiplier = 2 if win else 0
        return self._format_game_result('darts', chat_id, user_id, bet, win, multiplier,
                                       f'🎯 得分: {score}分!')

    async def play_bowling(self, chat_id: int, user_id: int, bet: int = 1) -> Dict[str, Any]:
        if not self._is_game_enabled('bowling'):
            return {'result': 'disabled', 'message': '🎳 保龄球未开启'}
        pins = random.randint(0, 10)
        win = pins == 10
        multiplier = 5 if win else (1 if pins >= 7 else 0)
        return self._format_game_result('bowling', chat_id, user_id, bet, win, multiplier,
                                       f'🎳 击倒: {pins}个瓶子! {"🎯 全中！" if win else ""}')

    async def play_niuniu(self, chat_id: int, user_id: int, bet: int = 1) -> Dict[str, Any]:
        if not self._is_game_enabled('niuniu'):
            return {'result': 'disabled', 'message': '🐮 牛牛游戏未开启'}
        cards = [random.randint(1, 13) for _ in range(5)]
        total = sum(cards) % 10
        is_niuniu = total == 0
        win = is_niuniu or total >= 7
        multiplier = 5 if is_niuniu else (2 if total >= 7 else 0)
        return self._format_game_result('niuniu', chat_id, user_id, bet, win, multiplier,
                                       f'🐮 点数: {"牛牛！" if is_niuniu else total}')

    async def play_dice_quick(self, chat_id: int, user_id: int, bet: int = 1) -> Dict[str, Any]:
        if not self._is_game_enabled('dice_quick'):
            return {'result': 'disabled', 'message': '🎲 骰子快三未开启'}
        dice1, dice2, dice3 = random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)
        total = dice1 + dice2 + dice3
        win = total >= 11
        multiplier = 2 if win else 0
        return self._format_game_result('dice_quick', chat_id, user_id, bet, win, multiplier,
                                       f'🎲 [{dice1}][{dice2}][{dice3}] = {total}')

    async def play_horse_racing(self, chat_id: int, user_id: int, bet: int = 1) -> Dict[str, Any]:
        if not self._is_game_enabled('horse_racing'):
            return {'result': 'disabled', 'message': '🐎 赛马未开启'}
        horses = ['🐴1号', '🐴2号', '🐴3号', '🐴4号', '🐴5号']
        winner = random.choice(horses)
        win = random.random() > 0.6
        multiplier = 3 if win else 0
        return self._format_game_result('horse_racing', chat_id, user_id, bet, win, multiplier,
                                       f'🐎 获胜者: {winner}!')

    async def play_baccarat(self, chat_id: int, user_id: int, bet: int = 1) -> Dict[str, Any]:
        if not self._is_game_enabled('baccarat'):
            return {'result': 'disabled', 'message': '🎲 百家乐未开启'}
        player = random.randint(0, 9)
        banker = random.randint(0, 9)
        win = player > banker
        multiplier = 2 if win else 0
        return self._format_game_result('baccarat', chat_id, user_id, bet, win, multiplier,
                                       f'🎲 玩家: {player} - 庄家: {banker}')

    async def play_blackjack(self, chat_id: int, user_id: int, bet: int = 1) -> Dict[str, Any]:
        if not self._is_game_enabled('blackjack'):
            return {'result': 'disabled', 'message': '🃏 21点未开启'}
        player_score = random.randint(12, 22)
        dealer_score = random.randint(12, 22)
        win = (player_score <= 21 and dealer_score > 21) or (player_score <= 21 and player_score > dealer_score)
        multiplier = 2 if win else 0
        return self._format_game_result('blackjack', chat_id, user_id, bet, win, multiplier,
                                       f'🃏 你的: {player_score} - 庄家: {dealer_score}')

    async def play_single_dice(self, chat_id: int, user_id: int, bet: int = 1) -> Dict[str, Any]:
        if not self._is_game_enabled('single_dice'):
            return {'result': 'disabled', 'message': '🎲 单骰未开启'}
        result = random.randint(1, 6)
        win = result >= 4
        multiplier = 2 if win else 0
        return self._format_game_result('single_dice', chat_id, user_id, bet, win, multiplier,
                                       f'🎲 点数: {result}')

    async def play_emoji_race(self, chat_id: int, user_id: int, bet: int = 1) -> Dict[str, Any]:
        if not self._is_game_enabled('emoji_race'):
            return {'result': 'disabled', 'message': '🏁 Emoji比赛未开启'}
        racers = ['🐢', '🐇', '🐘', '🦘', '🦋']
        winner = random.choice(racers)
        win = random.random() > 0.5
        multiplier = 2 if win else 0
        return self._format_game_result('emoji_race', chat_id, user_id, bet, win, multiplier,
                                       f'🏁 冠军: {winner}!')

    def _is_game_enabled(self, game_name: str) -> bool:
        return ENTERTAINMENT_GAMES_CONFIG.get('enabled', False) and \
               ENTERTAINMENT_GAMES_CONFIG.get('games', {}).get(game_name, {}).get('enabled', False)

    def _format_game_result(self, game_name: str, chat_id: int, user_id: int,
                            bet: int, win: bool, multiplier: int, message: str) -> Dict[str, Any]:
        amount = bet * multiplier
        return {
            'result': 'win' if win else 'lose',
            'game': game_name,
            'bet': bet,
            'amount': amount,
            'message': f'{message} {"💰 赢了 " + str(amount) + " 金币！" if win else "😢 输了 " + str(bet) + " 金币"}',
        }

    def _evaluate_poker_hand(self, hand) -> int:
        values = [c[0] for c in hand]
        suits = [c[1] for c in hand]
        value_counts = {v: values.count(v) for v in set(values)}
        suit_counts = {s: suits.count(s) for s in set(suits)}
        if max(suit_counts.values()) == 3 and max(value_counts.values()) == 3:
            return 5
        if max(value_counts.values()) == 3:
            return 4
        if len(value_counts) == 2 and max(value_counts.values()) == 2:
            return 3
        if len(value_counts) == 3 and max(value_counts.values()) == 2:
            return 2
        if max(suit_counts.values()) == 3:
            return 1
        return 0

    async def process(self, update):
        return None


entertainment_games_module = EntertainmentGamesModule()