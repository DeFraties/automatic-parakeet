"""Public removal requests (Section 4.6 / Compliance rule 6). Reviewed with `ingest removals`."""

import re

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import client_ip, limiter
from app.models import RemovalRequest

router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


class RemovalIn(BaseModel):
    email: str = Field(max_length=320)
    reference: str = Field(min_length=3, max_length=1000)  # listing URL or property ID
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if not EMAIL_RE.match(v):
            raise ValueError("enter a valid email address")
        return v


@router.post("/removals", status_code=201)
def request_removal(body: RemovalIn, request: Request, db: Session = Depends(get_db)) -> dict:
    limiter.check(f"write:{client_ip(request)}", get_settings().rate_limit_writes_per_hour)
    req = RemovalRequest(email=body.email, reference=body.reference.strip(), message=body.message)
    db.add(req)
    db.commit()
    return {"id": req.id, "status": req.status}
