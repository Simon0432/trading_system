from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class Settings(SQLModel, table=True):
    id: Optional[int] = Field(default=1, primary_key=True)

    loop_interval_sec: int = 30

    risk_pct: float = 1.0
    sl_pct: float = 1.5
    tp_pct: float = 2.5

    max_trades_per_day: int = 10
    cooldown_minutes: int = 10
    news_blackout_minutes: int = 15

    leverage: int = 2
    symbol: str = "BTC/USDT:USDT"
    timeframe: str = "5m"

    max_margin_pct: float = 10.0
    max_daily_loss_pct: float = 2.5

    news_enabled: bool = False

    # ✅ Trailing (софт): TP не трогаем, SL подтягиваем
    trailing_enabled: bool = True
    trailing_activation_pct: float = 0.8  # включить trailing после +0.8% в плюс
    trailing_pct: float = 0.6             # держать SL на 0.6% от цены

    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Trade(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    ts: datetime = Field(default_factory=datetime.utcnow, index=True)

    symbol: str
    side: str  # "buy" / "sell"
    qty: float

    entry: float
    sl: float
    tp: float

    exit_price: Optional[float] = None
    pnl_usdt: Optional[float] = None

    status: str = "OPEN"  # OPEN / CLOSED
    note: str = ""


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)

    level: str  # INFO/WARN/ERROR
    type: str   # e.g. BOT_STARTED, LOOP_ERROR, TRADE_OPENED
    message: str
