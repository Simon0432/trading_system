from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class Settings(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)

    # trade core
    symbol: str = Field(default="BTC/USDT:USDT", index=True)
    timeframe: str = Field(default="5m")

    leverage: int = Field(default=2)
    risk_pct: float = Field(default=0.5)      # риск на сделку (% от баланса)
    sl_pct: float = Field(default=1.5)        # стоп в % от entry
    tp_pct: float = Field(default=2.5)        # тейк в % от entry

    loop_interval_sec: int = Field(default=30)
    cooldown_minutes: int = Field(default=10)
    max_trades_per_day: int = Field(default=10)
    max_daily_loss_pct: float = Field(default=2.5)
    max_margin_pct: float = Field(default=10.0)

    # execution protection
    entry_order_type: str = Field(default="limit")  # "limit" | "market"
    entry_timeout_sec: int = Field(default=12)

    max_spread_pct: float = Field(default=0.06)     # (ask-bid)/mid * 100
    max_slippage_pct: float = Field(default=0.12)   # |fill-expected|/expected*100
    allow_market_fallback: bool = Field(default=True)

    # limit order behavior
    post_only: bool = Field(default=False)          # если True — лимитка только maker (может не зайти чаще)

    # trailing
    trailing_enabled: bool = Field(default=True)
    trailing_activation_pct: float = Field(default=0.8)  # % прибыли для включения трейла
    trailing_pct: float = Field(default=0.6)             # расстояние трейла (%)

    # SL/TP placement
    use_exchange_sl_tp: bool = Field(default=False)      # true = ставим SL/TP на бирже (надёжнее)
    reduce_only_sl_tp: bool = Field(default=True)        # защита: SL/TP не должен увеличивать позицию

    # ccxt/bybit quirks
    acknowledged_fetch: bool = Field(default=True)       # передавать params={"acknowledged": True} в fetch_order

    # news (позже подключим)
    news_enabled: bool = Field(default=False)
    news_blackout_minutes: int = Field(default=15)

    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Trade(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)

    symbol: str = Field(index=True)
    side: str  # "buy" | "sell"
    qty: float

    entry: float
    sl: float
    tp: float

    # execution details (ENTRY)
    entry_order_id: Optional[str] = None
    entry_avg_fill: Optional[float] = None
    entry_fee_usdt: Optional[float] = None

    # exchange SL/TP state
    exchange_tpsl_set: bool = Field(default=False)        # мы успешно поставили SL/TP на бирже
    tpsl_set_ts: Optional[datetime] = None

    # execution details (EXIT)
    exit_order_id: Optional[str] = None
    exit_avg_fill: Optional[float] = None
    exit_fee_usdt: Optional[float] = None
    exit_reason: Optional[str] = None                     # "TP" | "SL" | "MANUAL" | "RECOVERY" и т.п.

    # optional: for recovery/sync later
    exchange_position_id: Optional[str] = None

    exit_price: Optional[float] = None
    pnl_usdt: Optional[float] = None
    status: str = Field(default="OPEN", index=True)       # OPEN|CLOSED
    note: str = Field(default="")


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)

    level: str
    type: str
    message: str
