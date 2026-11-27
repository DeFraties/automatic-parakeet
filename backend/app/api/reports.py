"""Player photo reports (Section 4.2 / 9.3). A `price_visible` report takes the home out of play
until the owner reviews it (`ingest reports`)."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.games import DeviceId, _error, shown_round
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import client_ip, limiter
from app.models import PhotoReport

router = APIRouter()


class ReportIn(BaseModel):
    game_id: str = Field(max_length=36)
    round_no: int = Field(ge=1, le=10)
    position: int | None = Field(default=None, ge=0, le=100)
    reason: Literal["price_visible", "broken", "person", "other"]


@router.post("/reports", status_code=201)
def report_photo(
    body: ReportIn, request: Request, device_id: DeviceId = None, db: Session = Depends(get_db)
) -> dict:
    limiter.check(f"write:{client_ip(request)}", get_settings().rate_limit_writes_per_hour)
    r = shown_round(db, body.game_id, body.round_no, device_id)
    if r is None:
        raise _error(404, "round_not_found", "Round not found.")
    rep = PhotoReport(
        property_id=r.property_id,
        position=body.position,
        reason=body.reason,
        device_id=device_id,
    )
    db.add(rep)
    db.commit()
    return {"id": rep.id, "status": rep.status}
