"""Games API (Section 6.1 / 9.4): create a game, then guess each round in order."""

import random
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import update
from sqlalchemy.orm import Session, selectinload

from app.core import fx
from app.core.config import MAX_POINTS, get_settings
from app.core.countries import COUNTRIES_BY_CODE, REGIONS_BY_KEY
from app.core.db import get_db
from app.core.photos import lead_photo_url, photo_credit, round_photos
from app.core.scoring import (
    fx_hint,
    local_to_usd,
    pct_off,
    reveal_label,
    score_guess,
    slider_bounds,
    usd_to_local,
)
from app.core.security import client_ip, limiter
from app.core.selection import (
    DEFAULT_SETTINGS,
    PoolTooSmall,
    decode_settings,
    encode_settings,
    load_candidates,
    pick_rounds,
)
from app.models import Game, GameRound, Property, utcnow

router = APIRouter()

Mode = Literal["classic"]
Difficulty = Literal["normal", "hard"]
WhereScope = Literal["world", "region", "country"]
Setting = Literal["urban", "rural"]


class CreateGameIn(BaseModel):
    mode: Mode = "classic"
    where_scope: WhereScope = "world"
    where_value: str | None = Field(default=None, max_length=32)
    difficulty: Difficulty = "normal"
    settings: list[Setting] = Field(
        default_factory=lambda: list(DEFAULT_SETTINGS), min_length=1, max_length=2
    )

    @model_validator(mode="after")
    def _check_where(self):
        if self.where_scope == "world":
            self.where_value = None
        elif self.where_scope == "region":
            if self.where_value not in REGIONS_BY_KEY:
                raise ValueError("unknown region")
        else:
            code = (self.where_value or "").upper()
            if code not in COUNTRIES_BY_CODE:
                raise ValueError("unknown country")
            self.where_value = code
        return self


class GuessIn(BaseModel):
    amount: Annotated[float, Field(strict=True, gt=0, lt=1e13, allow_inf_nan=False)]
    currency: str = Field(min_length=3, max_length=3)


DeviceId = Annotated[str | None, Header(alias="X-Device-Id", max_length=64)]


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _rate_for(db: Session, p: Property) -> float:
    return fx.latest_rate(db, p.currency) or p.fx_rate_to_usd


def round_payload(db: Session, game: Game, r: GameRound) -> dict:
    p = r.property
    country = COUNTRIES_BY_CODE[p.country_code]
    hard = game.difficulty == "hard"
    guess_currency = p.currency if hard else "USD"
    smin, smax = slider_bounds(guess_currency, _rate_for(db, p) if hard else None)
    place = f"{p.city}, {country.name}"
    return {
        "round_no": r.round_no,
        "rounds_total": len(game.rounds),
        "photos": round_photos(p, place),
        "photo_credit": photo_credit(p),
        "difficulty": game.difficulty,
        "guess_currency": guess_currency,
        "local_currency": p.currency,
        "slider": {"min": smin, "max": smax},
        "clues": {
            "country": country.name,
            "country_code": country.code,
            "flag": country.flag,
            "region": p.region,
            "city": p.city,
            "setting": p.setting,
            "property_type": p.property_type,
            "area_m2": p.area_m2,
            "bedrooms": p.bedrooms,
            "bathrooms": p.bathrooms,
            "year_built": p.year_built,
            "price_year": p.price_date.year,
            "price_type": p.price_type,
        },
        # Only when the listing itself provided coordinates. ~1 km rounding.
        "map": (
            {"lat_approx": round(p.lat, 2), "lng_approx": round(p.lng, 2)}
            if p.lat is not None and p.lng is not None
            else None
        ),
    }


def reveal_payload(r: GameRound) -> dict:
    p = r.property
    guess_usd = local_to_usd(r.guess_local, p.fx_rate_to_usd)
    pct = pct_off(r.guess_local, p.price_local)
    return {
        "round_no": r.round_no,
        "price_local": p.price_local,
        "currency": p.currency,
        "price_usd": round(p.price_usd),
        "guess_local": round(r.guess_local, 2),
        "guess_usd": round(guess_usd, 2),
        "pct_off": round(pct, 1),
        "score": r.score,
        "label": reveal_label(pct),
        "price_per_m2_local": round(p.price_local / p.area_m2) if p.area_m2 else None,
        "area_m2": p.area_m2,
        "price_date": p.price_date.isoformat(),
        "price_type": p.price_type,
        "source_name": p.source.display_name,
        "listing_url": p.listing_url,
        "fx_hint": fx_hint(p.currency, p.fx_rate_to_usd),
        "city": p.city,
        "country_code": p.country_code,
    }


def summary_payload(game: Game) -> dict:
    rows = []
    for r in game.rounds:
        p = r.property
        rows.append(
            {
                "round_no": r.round_no,
                "city": p.city,
                "country_code": p.country_code,
                "flag": COUNTRIES_BY_CODE[p.country_code].flag,
                "lead_photo": lead_photo_url(p),
                "currency": p.currency,
                "price_local": p.price_local,
                "price_usd": round(p.price_usd),
                "guess_local": round(r.guess_local, 2) if r.guess_local is not None else None,
                "guess_usd": round(local_to_usd(r.guess_local, p.fx_rate_to_usd), 2)
                if r.guess_local is not None
                else None,
                "score": r.score,
            }
        )
    return {
        "game_id": game.id,
        "mode": game.mode,
        "where_scope": game.where_scope,
        "where_value": game.where_value,
        "settings": list(decode_settings(game.setting_filter)),
        "difficulty": game.difficulty,
        "total_score": game.total_score,
        "max_score": MAX_POINTS * len(game.rounds),
        "rounds": rows,
    }


def _load_game(db: Session, game_id: str) -> Game:
    game = (
        db.query(Game)
        .options(
            selectinload(Game.rounds).selectinload(GameRound.property).selectinload(Property.images)
        )
        .filter(Game.id == game_id)
        .one_or_none()
    )
    if game is None:
        raise _error(404, "game_not_found", "Game not found.")
    return game


def game_header(game: Game) -> dict:
    return {
        "game_id": game.id,
        "rounds_total": len(game.rounds),
        "mode": game.mode,
        "where_scope": game.where_scope,
        "where_value": game.where_value,
        "settings": list(decode_settings(game.setting_filter)),
        "difficulty": game.difficulty,
    }


def start_game(
    db: Session,
    *,
    mode: str,
    where_scope: str,
    where_value: str | None,
    setting_filter: str,
    difficulty: str,
    device_id: str | None,
    property_ids: list[str],
) -> dict:
    game = Game(
        mode=mode,
        where_scope=where_scope,
        where_value=where_value,
        setting_filter=setting_filter,
        difficulty=difficulty,
        device_id=device_id,
    )
    game.rounds = [GameRound(round_no=i + 1, property_id=pid) for i, pid in enumerate(property_ids)]
    db.add(game)
    db.commit()
    game = _load_game(db, game.id)
    return {**game_header(game), "round": round_payload(db, game, game.rounds[0])}


def shown_round(
    db: Session, game_id: str, round_no: int, device_id: str | None
) -> GameRound | None:
    """The round if this device has been shown it (answered, or the current one), else None."""
    game = db.get(Game, game_id)
    if game is None or (game.device_id and game.device_id != device_id):
        return None
    r = db.get(GameRound, (game.id, round_no))
    prev = db.get(GameRound, (game.id, round_no - 1)) if round_no > 1 else None
    if r is None or not (r.score is not None or prev is None or prev.score is not None):
        return None
    return r


@router.post("/games", status_code=201)
def create_game(
    body: CreateGameIn,
    request: Request,
    device_id: DeviceId = None,
    db: Session = Depends(get_db),
) -> dict:
    s = get_settings()
    limiter.check(f"games:{client_ip(request)}", s.rate_limit_games_per_hour)
    setting_filter = encode_settings(body.settings)
    cands = load_candidates(
        db,
        today=date.today(),
        max_age_years=s.max_price_age_years,
        setting_filter=setting_filter,
        where_scope=body.where_scope,
        where_value=body.where_value,
    )
    try:
        picks = pick_rounds(
            cands,
            rng=random.Random(),
            where_scope=body.where_scope,
            setting_filter=setting_filter,
            min_pool_per_country=s.min_pool_per_option,
        )
    except PoolTooSmall as e:
        raise _error(422, "pool_too_small", "Not enough properties for these settings yet.") from e
    return start_game(
        db,
        mode=body.mode,
        where_scope=body.where_scope,
        where_value=body.where_value,
        setting_filter=setting_filter,
        difficulty=body.difficulty,
        device_id=device_id,
        property_ids=[c.id for c in picks],
    )


@router.get("/games/{game_id}")
def get_game(game_id: str, device_id: DeviceId = None, db: Session = Depends(get_db)) -> dict:
    """Resume a game (e.g. after a reload): the current round, or the summary when finished."""
    game = _load_game(db, game_id)
    if game.device_id and game.device_id != device_id:
        raise _error(404, "game_not_found", "Game not found.")
    if game.completed_at is not None:
        return {**game_header(game), "summary": summary_payload(game)}
    current = next(r for r in game.rounds if r.score is None)
    score = sum(r.score or 0 for r in game.rounds)
    return {**game_header(game), "score": score, "round": round_payload(db, game, current)}


@router.post("/games/{game_id}/rounds/{round_no}/guess")
def guess(
    game_id: str,
    round_no: int,
    body: GuessIn,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    s = get_settings()
    limiter.check(f"guess:{client_ip(request)}", s.rate_limit_guesses_per_hour)
    game = _load_game(db, game_id)
    if not 1 <= round_no <= len(game.rounds):
        raise _error(404, "round_not_found", "Round not found.")
    r = game.rounds[round_no - 1]
    if r.score is not None:
        raise _error(409, "already_answered", "This round has already been answered.")
    if any(prev.score is None for prev in game.rounds[: round_no - 1]):
        raise _error(409, "out_of_order", "Answer the rounds in order.")

    p = r.property
    expected = p.currency if game.difficulty == "hard" else "USD"
    if body.currency.upper() != expected:
        raise _error(422, "wrong_currency", f"Guesses in this game must be in {expected}.")

    guess_local = (
        body.amount if expected == p.currency else usd_to_local(body.amount, p.fx_rate_to_usd)
    )
    points = score_guess(guess_local, p.price_local)
    now = utcnow()
    # Conditional update makes double-submits race-safe: only one request can fill the round.
    res = db.execute(
        update(GameRound)
        .where(
            GameRound.game_id == game.id,
            GameRound.round_no == round_no,
            GameRound.score.is_(None),
        )
        .values(
            guess_amount=body.amount,
            guess_currency=expected,
            guess_local=guess_local,
            score=points,
            answered_at=now,
        )
    )
    if res.rowcount != 1:
        db.rollback()
        raise _error(409, "already_answered", "This round has already been answered.")
    db.commit()
    db.expire_all()
    game = _load_game(db, game_id)
    r = game.rounds[round_no - 1]

    out: dict = {"reveal": reveal_payload(r)}
    if round_no < len(game.rounds):
        out["next_round"] = round_payload(db, game, game.rounds[round_no])
    else:
        game.total_score = sum(x.score or 0 for x in game.rounds)
        game.completed_at = now
        db.commit()
        out["summary"] = summary_payload(game)
    return out
