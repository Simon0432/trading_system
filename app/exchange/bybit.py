# app/exchange/bybit.py
from __future__ import annotations

import time
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
        last = float(t.get("last") or 0)
        bid = float(t.get("bid") or 0)
        ask = float(t.get("ask") or 0)
        return {
            "symbol": symbol,
            "last": last,
            "bid": bid,
            "ask": ask,
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
            # уже стоит такое плечо — это не ошибка
            if "110043" in msg or "leverage not modified" in msg:
                return {"ok": True, "note": "leverage already set"}
            raise

    # ---------- Orders / Fills ----------

    def create_limit(self, symbol: str, side: str, qty: float, price: float, post_only: bool = False):
        params = {}
        if post_only:
            params["postOnly"] = True
        return self.exchange.create_order(symbol, "limit", side, qty, price, params)

    def create_market(self, symbol: str, side: str, qty: float):
        return self.exchange.create_order(symbol, "market", side, qty)

    def cancel_order(self, order_id: str, symbol: str):
        return self.exchange.cancel_order(order_id, symbol)

    # Оставляем, но НЕ используем в wait_fill (Bybit лимитирует fetch_order по истории)
    def fetch_order(self, order_id: str, symbol: str, params: dict | None = None):
        params = params or {}
        # acknowledged=True убирает warning, но не всегда спасает от "не найдено"
        params.setdefault("acknowledged", True)
        return self.exchange.fetch_order(order_id, symbol, params)

    def set_trading_stop(self, symbol: str, stop_loss: float | None, take_profit: float | None):
        """
        Bybit v5 endpoint: /v5/position/trading-stop
        Работает для swap. Ставим биржевой SL/TP.
        """
        params = {
            "category": "linear",
            "symbol": self._market_id(symbol),
        }
        if stop_loss is not None:
            params["stopLoss"] = str(stop_loss)
        if take_profit is not None:
            params["takeProfit"] = str(take_profit)

        return self.exchange.privatePostV5PositionTradingStop(params)

    def _market_id(self, symbol: str) -> str:
        m = self.exchange.market(symbol)
        return m["id"]

    @staticmethod
    def parse_fill(order: dict) -> dict:
        """
        Нормализуем: avg fill + fee
        """
        avg = order.get("average")
        filled = order.get("filled")
        fee = order.get("fee") or {}
        fee_cost = fee.get("cost")

        return {
            "status": order.get("status"),
            "id": order.get("id"),
            "average": float(avg) if avg is not None else None,
            "filled": float(filled) if filled is not None else None,
            "fee_cost": float(fee_cost) if fee_cost is not None else None,
        }

    # ---------- SAFE order status without fetch_order ----------

    def get_order_status_safe(self, symbol: str, order_id: str) -> dict | None:
        """
        Ищем ордер в open/closed списках, не вызывая fetch_order().
        Возвращаем сам order dict, или None если не найден.
        """
        try:
            opens = self.exchange.fetch_open_orders(symbol)
            for o in opens:
                if o.get("id") == order_id:
                    return o
        except Exception:
            pass

        try:
            closed = self.exchange.fetch_closed_orders(symbol)
            for o in closed:
                if o.get("id") == order_id:
                    return o
        except Exception:
            pass

        return None

    def wait_fill(self, symbol: str, order_id: str, timeout_sec: int):
        """
        Ждём исполнения ордера до timeout_sec.
        SAFE: не использует fetch_order (Bybit лимитирует доступ).
        """
        t0 = time.time()
        last = None

        while time.time() - t0 <= timeout_sec:
            o = self.get_order_status_safe(symbol, order_id)
            if o:
                last = o
                status = (o.get("status") or "").lower()
                if status in ("closed", "filled"):
                    return o

            time.sleep(0.7)

        return last
