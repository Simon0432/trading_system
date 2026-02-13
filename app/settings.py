from __future__ import annotations
from sqlmodel import Session
from app.models import Settings
from app import repo

def get_settings(session: Session) -> Settings:
    return repo.get_or_create_settings(session)
