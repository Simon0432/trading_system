from __future__ import annotations

from sqlmodel import SQLModel, create_engine, Session

DB_URL = "sqlite:///./trading.db"
engine = create_engine(DB_URL, echo=False)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
