# app/bot_engine.py
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from sqlmodel import Session

from app.db import engine
from app.exchange.bybit import BybitClient
from app.strategy import decide_signal
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

        # trailing state (для одной позиции)
        self.best_price: float | None = None  # для buy: max; для sell: min

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

    @staticmethod
    def _spread_pct(bid: float, ask: float) -> float:
        if bid <= 0 or ask <= 0:
            return 999.0
        mid = (bid + ask) / 2.0
        return (ask - bid) / mid * 100.0

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
        if sl_move <= 0:
            return 0.0

        qty_by_risk = risk_usdt / sl_move

        max_margin_usdt = balance * (max_margin_pct / 100.0)
        qty_by_margin = (max_margin_usdt * leverage) / price if price > 0 else 0.0

        qty = min(qty_by_risk, qty_by_margin)
        return float(max(0.0, round(qty, 6)))

    def _run_loop(self):
        while self.running:
            try:
                self._reset_daily_if_needed()

                with Session(engine) as session:
                    st = repo.get_or_create_settings(session)

                # дневной лимит убытка
                bal = self.client.balance_usdt()
                if bal > 0 and self.daily_pnl <= -(bal * (st.max_daily_loss_pct / 100.0)):
                    with Session(engine) as s:
                        repo.add_event(s, "WARN", "DAILY_LOSS_LIMIT", "Daily loss limit reached, bot paused")
                    time.sleep(st.loop_interval_sec)
                    continue

                if self.trades_today >= st.max_trades_per_day:
                    time.sleep(st.loop_interval_sec)
                    continue

                if not self._cooldown_ok(st.cooldown_minutes):
                    time.sleep(st.loop_interval_sec)
                    continue

                # open trade?
                with Session(engine) as session:
                    open_t = repo.get_open_trade(session, st.symbol)

                if open_t:
                    self._manage_open_trade(open_t, st)
                    time.sleep(st.loop_interval_sec)
                    continue

                # сигнал
                ohlcv = self.client.ohlcv(st.symbol, st.timeframe, limit=200)
                closes = [float(c[4]) for c in ohlcv]
                signal = decide_signal(closes)
                if signal == "HOLD":
                    time.sleep(st.loop_interval_sec)
                    continue

                tick = self.client.ticker(st.symbol)
                bid, ask, last = float(tick["bid"]), float(tick["ask"]), float(tick["last"])

                # spread filter
                sp = self._spread_pct(bid, ask)
                if sp > float(st.max_spread_pct):
                    with Session(engine) as s:
                        repo.add_event(s, "INFO", "SPREAD_SKIP", f"Spread {sp:.4f}% > {st.max_spread_pct}%")
                    time.sleep(st.loop_interval_sec)
                    continue

                # leverage (если уже такое — может ругаться, у тебя в client это уже обработано)
                self.client.set_leverage(st.symbol, int(st.leverage))

                balance = self.client.balance_usdt()
                price_expected = last
                qty = self._calc_qty(price_expected, balance, st.risk_pct, st.sl_pct, st.leverage, st.max_margin_pct)
                if qty <= 0:
                    with Session(engine) as s:
                        repo.add_event(s, "WARN", "QTY_ZERO", "Qty=0; check balance/settings")
                    time.sleep(st.loop_interval_sec)
                    continue

                side = "buy" if signal == "BUY" else "sell"
                entry_price_ref = ask if side == "buy" else bid

                # предварительные SL/TP от reference (потом поправим по fill_avg)
                sl = entry_price_ref * (1 - st.sl_pct / 100.0) if side == "buy" else entry_price_ref * (1 + st.sl_pct / 100.0)
                tp = entry_price_ref * (1 + st.tp_pct / 100.0) if side == "buy" else entry_price_ref * (1 - st.tp_pct / 100.0)

                # ---------- ENTRY EXECUTION ----------
                entry_order = None
                waited = None  # важно: чтобы не было UnboundLocalError
                fill_avg = None
                fee_cost = None

                if st.entry_order_type == "market":
                    entry_order = self.client.create_market(st.symbol, side, qty)
                    # market: пытаемся извлечь fill из ответа create_market
                    p0 = self.client.parse_fill(entry_order or {})
                    fill_avg = p0.get("average")
                    fee_cost = p0.get("fee_cost")
                else:
                    # limit entry near best price
                    limit_price = entry_price_ref
                    entry_order = self.client.create_limit(st.symbol, side, qty, limit_price, post_only=False)

                    waited = self.client.wait_fill(st.symbol, entry_order["id"], int(st.entry_timeout_sec))
                    parsed_waited = self.client.parse_fill(waited or {})
                    status = (parsed_waited.get("status") or "").lower()

                    if status not in ("closed", "filled"):
                        # cancel and maybe fallback
                        try:
                            self.client.cancel_order(entry_order["id"], st.symbol)
                        except Exception:
                            pass

                        if st.allow_market_fallback:
                            entry_order = self.client.create_market(st.symbol, side, qty)
                            p0 = self.client.parse_fill(entry_order or {})
                            fill_avg = p0.get("average")
                            fee_cost = p0.get("fee_cost")
                        else:
                            with Session(engine) as s:
                                repo.add_event(s, "INFO", "ENTRY_TIMEOUT", f"Limit entry timeout; canceled. side={side} qty={qty}")
                            time.sleep(st.loop_interval_sec)
                            continue
                    else:
                        # limit filled: берём фактический average/fee из waited
                        fill_avg = parsed_waited.get("average")
                        fee_cost = parsed_waited.get("fee_cost")

                # ---- IMPORTANT FIX: НЕ используем fetch_order() ----
                # fallback если биржа не дала average
                if not fill_avg:
                    fill_avg = entry_price_ref

                # slippage check
                slip = abs(float(fill_avg) - entry_price_ref) / entry_price_ref * 100.0 if entry_price_ref > 0 else 0.0
                if slip > float(st.max_slippage_pct):
                    with Session(engine) as s:
                        repo.add_event(s, "WARN", "SLIPPAGE_HIGH", f"slippage={slip:.4f}% > {st.max_slippage_pct}% (still keeping trade)")

                # adjust SL/TP based on real fill
                sl = float(fill_avg) * (1 - st.sl_pct / 100.0) if side == "buy" else float(fill_avg) * (1 + st.sl_pct / 100.0)
                tp = float(fill_avg) * (1 + st.tp_pct / 100.0) if side == "buy" else float(fill_avg) * (1 - st.tp_pct / 100.0)

                with Session(engine) as session:
                    t = Trade(
                        symbol=st.symbol,
                        side=side,
                        qty=qty,
                        entry=float(fill_avg),
                        sl=float(sl),
                        tp=float(tp),
                        status="OPEN",
                        entry_order_id=str(entry_order["id"]) if entry_order and entry_order.get("id") is not None else None,
                        entry_avg_fill=float(fill_avg) if fill_avg else None,
                        entry_fee_usdt=float(fee_cost) if fee_cost is not None else None,
                    )
                    repo.add_trade(session, t)
                    repo.add_event(session, "INFO", "TRADE_OPENED", f"{side} {st.symbol} qty={qty} entry={fill_avg} sl={sl} tp={tp}")

                # place exchange SL/TP (recommended for real)
                if st.use_exchange_sl_tp:
                    try:
                        self.client.set_trading_stop(st.symbol, stop_loss=sl, take_profit=tp)
                        with Session(engine) as s:
                            repo.add_event(s, "INFO", "EXCHANGE_TPSL_SET", f"Exchange SL/TP set: sl={sl} tp={tp}")
                    except Exception as e:
                        with Session(engine) as s:
                            repo.add_event(s, "WARN", "EXCHANGE_TPSL_FAIL", str(e))

                self.last_trade_time = datetime.utcnow()
                self.trades_today += 1

                # reset trailing state
                self.best_price = None

            except Exception as e:
                with Session(engine) as s:
                    repo.add_event(s, "ERROR", "LOOP_ERROR", str(e))
                time.sleep(3)

    def _manage_open_trade(self, t: Trade, st):
        tick = self.client.ticker(t.symbol)
        price = float(tick["last"])

        # trailing logic (soft)
        if st.trailing_enabled:
            self._apply_trailing(t, st, price)

        hit_tp = price >= t.tp if t.side == "buy" else price <= t.tp
        hit_sl = price <= t.sl if t.side == "buy" else price >= t.sl

        # если use_exchange_sl_tp=True — биржа сама закроет, но мы всё равно закрываем здесь по софту
        if not (hit_tp or hit_sl):
            return

        exit_price = price
        pnl = (exit_price - t.entry) * t.qty
        if t.side == "sell":
            pnl = -pnl

        # close by opposite market
        close_side = "sell" if t.side == "buy" else "buy"
        self.client.create_market(t.symbol, close_side, t.qty)

        with Session(engine) as session:
            repo.update_trade(session, t.id, exit_price=exit_price, pnl_usdt=pnl, status="CLOSED")
            reason = "TP" if hit_tp else "SL"
            repo.add_event(session, "INFO", "TRADE_CLOSED", f"{reason} {t.symbol} exit={exit_price} pnl={pnl:.4f}")

        self.daily_pnl += float(pnl)

    def _apply_trailing(self, t: Trade, st, price: float):
        """
        Soft trailing:
        - activates after profit >= trailing_activation_pct
        - keeps SL trailing_pct behind best price
        """
        if t.side == "buy":
            profit_pct = (price - t.entry) / t.entry * 100.0
            if profit_pct < float(st.trailing_activation_pct):
                return

            # best price = max
            if self.best_price is None or price > self.best_price:
                self.best_price = price

            new_sl = self.best_price * (1 - float(st.trailing_pct) / 100.0)
            if new_sl > t.sl:
                with Session(engine) as session:
                    repo.update_trade(session, t.id, sl=float(new_sl))
                    repo.add_event(session, "INFO", "TRAIL_SL_UPDATED", f"SL -> {new_sl:.2f}")

        else:
            profit_pct = (t.entry - price) / t.entry * 100.0
            if profit_pct < float(st.trailing_activation_pct):
                return

            # best price = min
            if self.best_price is None or price < self.best_price:
                self.best_price = price

            new_sl = self.best_price * (1 + float(st.trailing_pct) / 100.0)
            if new_sl < t.sl:
                with Session(engine) as session:
                    repo.update_trade(session, t.id, sl=float(new_sl))
                    repo.add_event(session, "INFO", "TRAIL_SL_UPDATED", f"SL -> {new_sl:.2f}")


bot = BotEngine()
