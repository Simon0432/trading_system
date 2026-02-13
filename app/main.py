from __future__ import annotations

from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.db import init_db, engine
from app import repo
from app.bot_engine import bot


app = FastAPI()
templates = Jinja2Templates(directory="templates")


def get_session():
    with Session(engine) as session:
        yield session


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def ui(request: Request):
    return templates.TemplateResponse("ui.html", {"request": request})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/settings")
def get_settings(session: Session = Depends(get_session)):
    return repo.get_or_create_settings(session)


@app.post("/settings")
def set_settings(payload: dict, session: Session = Depends(get_session)):
    s = repo.update_settings(session, payload)
    repo.add_event(session, "INFO", "SETTINGS_UPDATED", str(payload))
    return s


@app.get("/trades")
def trades(limit: int = 50, session: Session = Depends(get_session)):
    return repo.list_trades(session, limit=limit)


@app.get("/events")
def events(limit: int = 100, session: Session = Depends(get_session)):
    return repo.list_events(session, limit=limit)


@app.post("/bot/start")
def start_bot():
    bot.start()
    return {"status": "started"}


@app.post("/bot/stop")
def stop_bot():
    bot.stop()
    return {"status": "stopped"}


@app.get("/bot/status")
def bot_status():
    return bot.status()
