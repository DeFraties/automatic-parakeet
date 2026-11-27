"""Leaderboards (Section 4.5). Boards never mix modes, difficulties, "Where" or setting choices."""

from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.games import DeviceId, _error
from app.core.config import get_settings
from app.core.countries import COUNTRIES_BY_CODE, REGIONS_BY_KEY, where_flag
from app.core.daily import utc_today
from app.core.db import get_db
from app.core.profanity import nickname_problem
from app.core.security import client_ip, limiter
from app.core.selection import DEFAULT_SETTING_FILTER, encode_settings
from app.models import DailyAttempt, Game, LeaderboardEntry, utcnow

router = APIRouter()

BOARD_MODES = ("classic", "daily")
TOP_N = 100


class SubmitIn(BaseModel):
    game_id: str = Field(max_length=36)
    nickname: str = Field(min_length=1, max_length=32)


def _check_where(where_scope: str, where_value: str | None) -> str | None:
    if where_scope == "world":
        return None
    if where_scope == "region" and where_value in REGIONS_BY_KEY:
        return where_value
    if where_scope == "country" and where_value and where_value.upper() in COUNTRIES_BY_CODE:
        return where_value.upper()
    raise _error(422, "bad_where", "Unknown region or country.")


@router.get("/leaderboards/{mode}")
def board(
    mode: Literal["classic", "daily"],
    difficulty: Literal["normal", "hard"] = "normal",
    where_scope: Literal["world", "region", "country"] = "world",
    where_value: str | None = Query(default=None, max_length=32),
    settings: str = Query(default=DEFAULT_SETTING_FILTER, max_length=32),
    period: Literal["day", "week", "all"] = "all",
    on: date | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
) -> dict:
    q = select(LeaderboardEntry).where(
        LeaderboardEntry.mode == mode, LeaderboardEntry.difficulty == difficulty
    )
    if mode == "daily":
        day = on or utc_today()
        q = q.where(LeaderboardEntry.daily_date == day)
        filters = {"date": day.isoformat()}
    else:
        try:
            setting_filter = encode_settings(settings.split(","))
        except ValueError as e:
            raise _error(422, "bad_settings", str(e)) from e
        wv = _check_where(where_scope, where_value)
        q = q.where(
            LeaderboardEntry.where_scope == where_scope,
            LeaderboardEntry.where_value.is_(None) if wv is None
            else LeaderboardEntry.where_value == wv,
            LeaderboardEntry.setting_filter == setting_filter,
        )  # fmt: skip
        if period != "all":
            now = utcnow()
            since = (
                datetime.combine(utc_today(), datetime.min.time())
                if period == "day"
                else now - timedelta(days=7)
            )
            q = q.where(LeaderboardEntry.created_at >= since)
        filters = {"where_scope": where_scope, "where_value": wv, "settings": setting_filter,
                   "period": period}  # fmt: skip
    rows = db.execute(
        q.order_by(LeaderboardEntry.score.desc(), LeaderboardEntry.created_at.asc()).limit(TOP_N)
    ).scalars()
    entries = [
        {
            "rank": i + 1,
            "nickname": e.nickname,
            "score": e.score,
            "flag": where_flag(e.where_scope, e.where_value),
            "date": (e.daily_date or e.created_at.date()).isoformat(),
        }
        for i, e in enumerate(rows)
    ]
    return {"mode": mode, "difficulty": difficulty, **filters, "entries": entries}


@router.post("/leaderboards", status_code=201)
def submit(
    body: SubmitIn,
    request: Request,
    device_id: DeviceId = None,
    db: Session = Depends(get_db),
) -> dict:
    limiter.check(f"write:{client_ip(request)}", get_settings().rate_limit_writes_per_hour)
    game = db.get(Game, body.game_id)
    if game is None or (game.device_id and game.device_id != device_id):
        raise _error(404, "game_not_found", "Game not found.")
    if game.mode not in BOARD_MODES:
        raise _error(422, "no_board", "This mode has no leaderboard.")
    if game.completed_at is None or game.total_score is None:
        raise _error(409, "not_completed", "Finish the game before submitting.")
    nickname = body.nickname.strip()
    problem = nickname_problem(nickname)
    if problem:
        raise _error(422, "bad_nickname", problem)
    daily_date = None
    if game.mode == "daily":
        daily_date = db.execute(
            select(DailyAttempt.date).where(DailyAttempt.game_id == game.id)
        ).scalar_one_or_none()
    entry = LeaderboardEntry(
        game_id=game.id,
        mode=game.mode,
        where_scope=game.where_scope,
        where_value=game.where_value,
        setting_filter=game.setting_filter,
        difficulty=game.difficulty,
        daily_date=daily_date,
        nickname=nickname,
        score=game.total_score,  # always the server-computed score
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise _error(409, "already_submitted", "This game is already on the leaderboard.") from e
    better = db.execute(
        select(LeaderboardEntry.id).where(
            LeaderboardEntry.mode == entry.mode,
            LeaderboardEntry.difficulty == entry.difficulty,
            LeaderboardEntry.where_scope == entry.where_scope,
            LeaderboardEntry.setting_filter == entry.setting_filter,
            (LeaderboardEntry.daily_date == daily_date) if daily_date
            else LeaderboardEntry.where_value.is_not_distinct_from(entry.where_value),
            LeaderboardEntry.score > entry.score,
        )
    ).all()  # fmt: skip
    return {"rank": len(better) + 1, "nickname": nickname, "score": entry.score}
