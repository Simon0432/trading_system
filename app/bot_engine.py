from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from sqlmodel import Session

from app.exchange.bybit import BybitClient
from app.strategy import decide_signal
from app.db import engine
from app import repo
from app.models import Trade


class BotEngine:
    def __init__(self):
        self.running = False
        self.thread: threading.Thread | None = None
        self.client = BybitClient()

        self.last_trade_time: datetime | None = None
        self.trades_today = 0
        self.day_start = datetime.utcnow().date()
        self.daily_pnl = 0.0

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        with Session(engine) as s:
            repo.add_event(s, "INFO", "BOT_STARTED", "Bot started")

    def stop(self):
        self.running = False
        with Session(engine) as s:
            repo.add_event(s, "INFO", "BOT_STOPPED", "Bot stopped")

    def status(self):
        return {
            "running": self.running,
            "trades_today": self.trades_today,
            "daily_pnl_usdt": self.daily_pnl,
            "last_trade_time": self.last_trade_time.isoformat() if self.last_trade_time else None,
        }

    def _reset_daily_if_needed(self):
        now = datetime.utcnow().date()
        if now != self.day_start:
            self.day_start = now
            self.trades_today = 0
            self.daily_pnl = 0.0

    def _cooldown_ok(self, cooldown_minutes: int) -> bool:
        if not self.last_trade_time:
            return True
        return datetime.utcnow() - self.last_trade_time >= timedelta(minutes=cooldown_minutes)

    def _calc_qty(
        self,
        price: float,
        balance: float,
        risk_pct: float,
        sl_pct: float,
        leverage: int,
        max_margin_pct: float,
    ) -> float:
        """
        qty в базовой монете (BTC), грубая оценка:
        - риск = balance * risk_pct%
        - стоп = sl_pct% => риск на 1 BTC = price * sl_pct%
        qty = risk / (price * sl_pct%)
        ограничение по марже: margin = (qty*price)/leverage <= balance*max_margin_pct%
        """
        risk_usdt = balance * (risk_pct / 100.0)
        sl_move = price * (sl_pct / 100.0)
        if sl_move <= 0 or price <= 0:
            return 0.0

        qty_by_risk = risk_usdt / sl_move

        max_margin_usdt = balance * (max_margin_pct / 100.0)
        qty_by_margin = (max_margin_usdt * leverage) / price

        qty = min(qty_by_risk, qty_by_margin)
        return float(max(0.0, round(qty, 6)))

    def _apply_soft_trailing(self, t: Trade, st) -> None:
        """
        ✅ Софт trailing:
        - TP не трогаем
        - SL подтягиваем только когда цена уже в плюсе на trailing_activation_pct
        """
        tick = self.client.ticker(t.symbol)
        price = float(tick["last"])

        activation = float(st.trailing_activation_pct) / 100.0
        trail = float(st.trailing_pct) / 100.0

        if t.side == "buy":
            if price < t.entry * (1.0 + activation):
                return
            new_sl = price * (1.0 - trail)
            if new_sl > t.sl:
                with Session(engine) as session:
                    repo.update_trade(session, t.id, sl=new_sl)
                    repo.add_event(session, "INFO", "TRAIL_SL_UPDATED", f"SL -> {new_sl:.2f}")
        else:  # sell
            if price > t.entry * (1.0 - activation):
                return
            new_sl = price * (1.0 + trail)
            if new_sl < t.sl:
                with Session(engine) as session:
                    repo.update_trade(session, t.id, sl=new_sl)
                    repo.add_event(session, "INFO", "TRAIL_SL_UPDATED", f"SL -> {new_sl:.2f}")

    def _run_loop(self):
        while self.running:
            try:
                self._reset_daily_if_needed()

                with Session(engine) as session:
                    st = repo.get_or_create_settings(session)

                # лимит дневного убытка
                bal_now = self.client.balance_usdt()
                if bal_now > 0:
                    if self.daily_pnl <= -(bal_now * (st.max_daily_loss_pct / 100.0)):
                        with Session(engine) as s:
                            repo.add_event(s, "WARN", "DAILY_LOSS_LIMIT", "Daily loss limit reached, bot paused")
                        time.sleep(st.loop_interval_sec)
                        continue

                # лимит сделок
                if self.trades_today >= st.max_trades_per_day:
                    time.sleep(st.loop_interval_sec)
                    continue

                # cooldown
                if not self._cooldown_ok(st.cooldown_minutes):
                    time.sleep(st.loop_interval_sec)
                    continue

                # есть открытая сделка — сопровождаем
                with Session(engine) as session:
                    open_t = repo.get_open_trade(session, st.symbol)

                if open_t:
                    if getattr(st, "trailing_enabled", False):
                        self._apply_soft_trailing(open_t, st)
                    self._manage_open_trade(open_t)
                    time.sleep(st.loop_interval_sec)
                    continue

                # иначе — ищем сигнал
                ohlcv = self.client.ohlcv(st.symbol, st.timeframe, limit=200)
                closes = [float(c[4]) for c in ohlcv]
                signal = decide_signal(closes)

                if signal == "HOLD":
                    time.sleep(st.loop_interval_sec)
                    continue

                tick = self.client.ticker(st.symbol)
                price = float(tick["last"])
                balance = float(self.client.balance_usdt())

                if price <= 0 or balance <= 0:
                    with Session(engine) as s:
                        repo.add_event(s, "WARN", "NO_BALANCE_OR_PRICE", f"balance={balance} price={price}")
                    time.sleep(st.loop_interval_sec)
                    continue

                # плечо (если уже стоит — ок)
                self.client.set_leverage(st.symbol, int(st.leverage))

                qty = self._calc_qty(price, balance, st.risk_pct, st.sl_pct, st.leverage, st.max_margin_pct)
                if qty <= 0:
                    with Session(engine) as s:
                        repo.add_event(s, "WARN", "QTY_ZERO", "Qty calculated as zero; check settings/balance")
                    time.sleep(st.loop_interval_sec)
                    continue

                side = "buy" if signal == "BUY" else "sell"
                sl = price * (1 - st.sl_pct / 100.0) if side == "buy" else price * (1 + st.sl_pct / 100.0)
                tp = price * (1 + st.tp_pct / 100.0) if side == "buy" else price * (1 - st.tp_pct / 100.0)

                # ордер
                self.client.market_order(st.symbol, side, qty)

                with Session(engine) as session:
                    t = Trade(symbol=st.symbol, side=side, qty=qty, entry=price, sl=sl, tp=tp, status="OPEN")
                    repo.add_trade(session, t)
                    repo.add_event(
                        session,
                        "INFO",
                        "TRADE_OPENED",
                        f"{side} {st.symbol} qty={qty} entry={price} sl={sl} tp={tp}",
                    )

                self.last_trade_time = datetime.utcnow()
                self.trades_today += 1

            except Exception as e:
                with Session(engine) as s:
                    repo.add_event(s, "ERROR", "LOOP_ERROR", str(e))
                time.sleep(3)

    def _manage_open_trade(self, t: Trade):
        """
        Закрываем по SL/TP по текущей цене.
        """
        tick = self.client.ticker(t.symbol)
        price = float(tick["last"])

        hit_tp = price >= t.tp if t.side == "buy" else price <= t.tp
        hit_sl = price <= t.sl if t.side == "buy" else price >= t.sl

        if not (hit_tp or hit_sl):
            return

        exit_price = price

        pnl = (exit_price - t.entry) * t.qty
        if t.side == "sell":
            pnl = -pnl

        # закрываем рыночной
        self.client.close_position_market(t.symbol, t.side, t.qty)

        with Session(engine) as session:
            repo.update_trade(session, t.id, exit_price=exit_price, pnl_usdt=pnl, status="CLOSED")
            reason = "TP" if hit_tp else "SL"
            repo.add_event(session, "INFO", "TRADE_CLOSED", f"{reason} {t.symbol} exit={exit_price} pnl={pnl:.4f}")

        self.daily_pnl += float(pnl)


bot = BotEngine()
