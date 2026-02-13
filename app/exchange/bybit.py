from __future__ import annotations

import ccxt
from app.config import BYBIT_KEY, BYBIT_SECRET, TESTNET


class BybitClient:
    def __init__(self):
        self.exchange = ccxt.bybit({
            "apiKey": BYBIT_KEY,
            "secret": BYBIT_SECRET,
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",  # USDT Perp
            },
        })

        if TESTNET:
            self.exchange.set_sandbox_mode(True)

        self.exchange.load_markets()

    def ticker(self, symbol: str):
        t = self.exchange.fetch_ticker(symbol)
        return {
            "symbol": symbol,
            "last": float(t.get("last") or 0),
            "bid": float(t.get("bid") or 0),
            "ask": float(t.get("ask") or 0),
            "timestamp": t.get("timestamp"),
        }

    def ohlcv(self, symbol: str, timeframe: str, limit: int = 200):
        return self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def balance_usdt(self) -> float:
        b = self.exchange.fetch_balance()
        total = b.get("total", {}).get("USDT")
        if total is None:
            total = b.get("free", {}).get("USDT", 0)
        return float(total or 0)

    def set_leverage(self, symbol: str, leverage: int):
        try:
            return self.exchange.set_leverage(leverage, symbol)
        except Exception as e:
            msg = str(e)
            # Bybit: 110043 leverage not modified -> это НЕ ошибка, просто уже стоит такое плечо
            if "110043" in msg or "leverage not modified" in msg:
                return {"ok": True, "note": "leverage already set"}
            raise

    def market_order(self, symbol: str, side: str, qty: float):
        side = side.lower()
        if side == "buy":
            return self.exchange.create_market_buy_order(symbol, qty)
        else:
            return self.exchange.create_market_sell_order(symbol, qty)

    def close_position_market(self, symbol: str, side: str, qty: float):
        # закрытие противоположной сделкой
        side = side.lower()
        if side == "buy":
            return self.exchange.create_market_sell_order(symbol, qty)
        else:
            return self.exchange.create_market_buy_order(symbol, qty)
