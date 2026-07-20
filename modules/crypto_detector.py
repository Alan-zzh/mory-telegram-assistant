"""加密货币检测模块
参考阿福后台：检测和拦截加密货币广告和诈骗、自动发送BTC/TON/TRX/ETH价格、加密货币资讯实时推送
"""
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import requests

from core.settings import config
from utils.logger import get_logger

logger = get_logger(__name__)

CRYPTO_DETECTOR_CONFIG = config.get('CRYPTO_DETECTOR_CONFIG', {
    'enabled': False,
    'action': 'DELETE',
    'keywords': ['比特币', 'BTC', '以太坊', 'ETH', '加密货币', '虚拟货币',
                 '区块链', 'DeFi', 'NFT', '空投', '挖矿', '钱包地址'],
    'address_patterns': [
        re.compile(r'0x[a-fA-F0-9]{40}'),
        re.compile(r'bc1[a-z0-9]{39,59}'),
        re.compile(r'1[0-9A-Za-z]{26,33}'),
    ],
    'auto_send_btc_price': False,
    'auto_send_ton_price': False,
    'auto_send_trx_price': False,
    'auto_send_eth_price': False,
    'price_message_text': {
        'btc': '💰 BTC价格: {price} USD',
        'ton': '💎 TON价格: {price} USD',
        'trx': '🔥 TRX价格: {price} USD',
        'eth': '🚀 ETH价格: {price} USD',
    },
    'news_push_enabled': False,
    'price_check_interval_hours': 6,
})


class CryptoDetectorModule:
    def __init__(self):
        self._last_price_check: Dict[str, datetime] = {}

    def detect(self, text: str) -> Optional[Dict[str, Any]]:
        if not CRYPTO_DETECTOR_CONFIG.get('enabled', False):
            return None
        matches = []
        for keyword in CRYPTO_DETECTOR_CONFIG.get('keywords', []):
            if keyword.lower() in text.lower():
                matches.append({'type': 'keyword', 'value': keyword})
        for pattern in CRYPTO_DETECTOR_CONFIG.get('address_patterns', []):
            found = pattern.findall(text)
            for addr in found:
                matches.append({'type': 'address', 'value': addr})
        if matches:
            logger.info(f"[加密货币检测] 发现 {len(matches)} 处匹配")
            return {
                'detected': True,
                'matches': matches,
                'action': CRYPTO_DETECTOR_CONFIG.get('action', 'DELETE'),
            }
        return None

    async def get_price(self, symbol: str) -> Optional[str]:
        try:
            url = f'https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd'
            response = requests.get(url, timeout=10)
            data = response.json()
            price = data.get(symbol, {}).get('usd')
            if price:
                return f"${price:,.2f}"
        except Exception as e:
            logger.error(f"[加密货币] 获取价格失败 {symbol}: {e}")
        return None

    async def send_crypto_price(self, chat_id: int, symbol: str, symbol_key: str):
        if not CRYPTO_DETECTOR_CONFIG.get(f'auto_send_{symbol_key}_price', False):
            return
        now = datetime.now()
        last_check = self._last_price_check.get(symbol_key)
        if last_check and (now - last_check) < timedelta(hours=CRYPTO_DETECTOR_CONFIG.get('price_check_interval_hours', 6)):
            return
        price = await self.get_price(symbol)
        if not price:
            return
        message_text = CRYPTO_DETECTOR_CONFIG.get('price_message_text', {}).get(symbol_key, f'{symbol_key.upper()}价格: {price}')
        message_text = message_text.format(price=price)
        try:
            from core.telebot_compat import TelebotCompat
            compat = TelebotCompat.get_instance()
            await compat.send_message(chat_id, message_text)
            self._last_price_check[symbol_key] = now
            logger.info(f"[加密货币] 发送 {symbol_key} 价格到 chat={chat_id}: {message_text}")
        except Exception as e:
            logger.error(f"[加密货币] 发送价格失败 chat={chat_id}: {e}")

    async def send_all_crypto_prices(self, chat_id: int):
        symbols = [
            ('bitcoin', 'btc'),
            ('the-open-network', 'ton'),
            ('tron', 'trx'),
            ('ethereum', 'eth'),
        ]
        for symbol, symbol_key in symbols:
            await self.send_crypto_price(chat_id, symbol, symbol_key)

    async def process(self, update):
        return None


crypto_detector_module = CryptoDetectorModule()