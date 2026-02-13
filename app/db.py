from __future__ import annotations

from sqlmodel import SQLModel, create_engine

# файл будет рядом с main.py (корень проекта)
engine = create_engine("sqlite:///trading.db", echo=False)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
