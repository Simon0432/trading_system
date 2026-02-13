from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.models import Settings, Trade, Event


def get_or_create_settings(session: Session) -> Settings:
    s = session.get(Settings, 1)
    if s is None:
        s = Settings(id=1)
        session.add(s)
        session.commit()
        session.refresh(s)
    return s


def update_settings(session: Session, payload: dict) -> Settings:
    s = get_or_create_settings(session)
    for k, v in payload.items():
        if hasattr(s, k):
            setattr(s, k, v)
    s.updated_at = datetime.utcnow()
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def add_event(session: Session, level: str, type_: str, message: str) -> Event:
    e = Event(level=level, type=type_, message=message)
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


def list_events(session: Session, limit: int = 100):
    stmt = select(Event).order_by(Event.id.asc()).limit(limit)
    return list(session.exec(stmt))



def add_trade(session: Session, t: Trade) -> Trade:
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def update_trade(
    session: Session,
    trade_id: int,
    **fields
) -> Trade:
    t = session.get(Trade, trade_id)
    if not t:
        raise ValueError("Trade not found")
    for k, v in fields.items():
        if hasattr(t, k):
            setattr(t, k, v)
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def list_trades(session: Session, limit: int = 50):
    stmt = select(Trade).order_by(Trade.id.desc()).limit(limit)
    return list(session.exec(stmt))


def get_open_trade(session: Session, symbol: str) -> Optional[Trade]:
    stmt = (
        select(Trade)
        .where(Trade.symbol == symbol, Trade.status == "OPEN")
        .order_by(Trade.id.desc())
        .limit(1)
    )
    return session.exec(stmt).first()
