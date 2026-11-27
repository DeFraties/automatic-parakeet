"""Daily Challenge (Section 2.2 / 6.3): same 5 properties for everyone, one attempt per device."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.games import DeviceId, _error, start_game
from app.core import daily
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import client_ip, limiter
from app.core.selection import PoolTooSmall
from app.models import DailyAttempt, Game

router = APIRouter()


class DailyStartIn(BaseModel):
    difficulty: Literal["normal", "hard"] = "normal"


def _status(db: Session, device_id: str | None) -> dict:
    s = get_settings()
    today = daily.utc_today()
    out = {
        "date": today.isoformat(),
        "number": daily.daily_number(today, s.launch_date),
        "played": False,
        "completed": False,
        "game_id": None,
        "score": None,
        "difficulty": None,
    }
    if device_id:
        attempt = db.execute(
            select(DailyAttempt).where(
                DailyAttempt.date == today, DailyAttempt.device_id == device_id
            )
        ).scalar_one_or_none()
        if attempt:
            game = db.get(Game, attempt.game_id)
            out |= {
                "played": True,
                "completed": game.completed_at is not None,
                "game_id": game.id,
                "score": game.total_score,
                "difficulty": game.difficulty,
            }
    return out


@router.get("/daily")
def daily_status(device_id: DeviceId = None, db: Session = Depends(get_db)) -> dict:
    return _status(db, device_id)


@router.post("/daily/start", status_code=201)
def daily_start(
    body: DailyStartIn,
    request: Request,
    device_id: DeviceId = None,
    db: Session = Depends(get_db),
) -> dict:
    s = get_settings()
    limiter.check(f"games:{client_ip(request)}", s.rate_limit_games_per_hour)
    if not device_id:
        raise _error(400, "device_id_required", "Missing device ID.")
    if _status(db, device_id)["played"]:
        raise _error(409, "already_played", "You've already played today's Daily Challenge.")
    today = daily.utc_today()
    try:
        challenge = daily.get_or_create(db, today)
    except PoolTooSmall as e:
        raise _error(422, "pool_too_small", "Not enough properties for a Daily Challenge.") from e

    result = start_game(
        db,
        mode="daily",
        where_scope=daily.DAILY_WHERE_SCOPE,
        where_value=None,
        setting_filter=daily.DAILY_SETTING_FILTER,
        difficulty=body.difficulty,
        device_id=device_id,
        property_ids=list(challenge.property_ids),
    )
    try:
        db.add(DailyAttempt(date=today, device_id=device_id, game_id=result["game_id"]))
        db.commit()
    except IntegrityError as e:  # a parallel request from the same device won the race
        db.rollback()
        raise _error(409, "already_played", "You've already played today's Daily Challenge.") from e
    return {**result, "daily": _status(db, device_id)}
