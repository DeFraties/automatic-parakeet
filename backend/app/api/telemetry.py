"""Client telemetry. Only one event: a Street View image failed to load (Section 7.4)."""

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.games import DeviceId, _error
from app.core.config import get_settings
from app.core.db import get_db
from app.core.images import forget_broken
from app.core.security import client_ip, limiter
from app.models import Game, GameRound, Property

router = APIRouter()


class ImageErrorIn(BaseModel):
    game_id: str = Field(max_length=36)
    round_no: int = Field(ge=1, le=10)
    source: Literal["listing", "google", "mapillary"] = "google"


@router.post("/telemetry/image-error", status_code=204)
def image_error(
    body: ImageErrorIn, request: Request, device_id: DeviceId = None, db: Session = Depends(get_db)
) -> Response:
    """Forget the broken image link (see images.forget_broken): the home stays playable with the
    next image source or an illustrated card. Only rounds the caller has been shown count."""
    limiter.check(f"write:{client_ip(request)}", get_settings().rate_limit_writes_per_hour)
    game = db.get(Game, body.game_id)
    if game is None or (game.device_id and game.device_id != device_id):
        raise _error(404, "game_not_found", "Game not found.")
    r = db.get(GameRound, (game.id, body.round_no))
    prev = db.get(GameRound, (game.id, body.round_no - 1)) if body.round_no > 1 else None
    shown = r is not None and (r.score is not None or prev is None or prev.score is not None)
    if not shown:
        raise _error(404, "round_not_found", "Round not found.")
    forget_broken(db.get(Property, r.property_id), body.source)
    db.commit()
    return Response(status_code=204)
