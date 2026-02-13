from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.models import Settings, Trade, Event


def get_or_create_settings(session: Session) -> Settings:
    s = session.exec(select(Settings).where(Settings.id == 1)).first()
    if not s:
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
    q = select(Event).order_by(Event.id.desc()).limit(limit)
    return list(reversed(session.exec(q).all()))


def add_trade(session: Session, t: Trade) -> Trade:
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def update_trade(
    session: Session,
    trade_id: int,
    **fields,
) -> Trade:
    t = session.exec(select(Trade).where(Trade.id == trade_id)).first()
    if not t:
        raise ValueError(f"Trade not found: {trade_id}")
    for k, v in fields.items():
        if hasattr(t, k):
            setattr(t, k, v)
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def list_trades(session: Session, limit: int = 50):
    q = select(Trade).order_by(Trade.id.desc()).limit(limit)
    return list(reversed(session.exec(q).all()))


def get_open_trade(session: Session, symbol: str) -> Optional[Trade]:
    q = (
        select(Trade)
        .where(Trade.symbol == symbol)
        .where(Trade.status == "OPEN")
        .order_by(Trade.id.desc())
    )
    return session.exec(q).first()
