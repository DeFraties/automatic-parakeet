"""Client telemetry: listing photos that failed to load in the player's browser (Section 7.4)."""

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.games import DeviceId, _error, shown_round
from app.core.config import get_settings
from app.core.db import get_db
from app.core.photos import mark_broken
from app.core.security import client_ip, limiter

router = APIRouter()


class ImageErrorIn(BaseModel):
    game_id: str = Field(max_length=36)
    round_no: int = Field(ge=1, le=10)
    positions: list[int] = Field(min_length=1, max_length=20)


@router.post("/telemetry/image-error", status_code=204)
def image_error(
    body: ImageErrorIn, request: Request, device_id: DeviceId = None, db: Session = Depends(get_db)
) -> Response:
    """Mark those photos broken. With fewer than 2 working photos left, the home leaves the pool
    until `ingest images-check` / `refresh` finds its photos working again."""
    limiter.check(f"write:{client_ip(request)}", get_settings().rate_limit_writes_per_hour)
    r = shown_round(db, body.game_id, body.round_no, device_id)
    if r is None:
        raise _error(404, "round_not_found", "Round not found.")
    mark_broken(r.property, body.positions)
    db.commit()
    return Response(status_code=204)
