"""SQLAlchemy models (Section 9.3)."""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    homepage: Mapped[str | None] = mapped_column(String(500))
    license_note: Mapped[str | None] = mapped_column(Text)
    image_hosts: Mapped[list | None] = mapped_column(JSON)  # hosts photo URLs may come from
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Property(Base):
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("source_id", "source_ref", name="uq_properties_source_ref"),
        Index("ix_properties_play", "is_active", "images_status", "country_code", "setting"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    source_ref: Mapped[str] = mapped_column(String(500))
    listing_url: Mapped[str | None] = mapped_column(String(1000))  # required to be playable
    price_type: Mapped[str] = mapped_column(String(16))  # asking | sale_record
    price_local: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    price_usd: Mapped[float] = mapped_column(Float)
    fx_rate_to_usd: Mapped[float] = mapped_column(Float)  # USD per 1 unit of `currency`
    price_date: Mapped[date] = mapped_column(Date)
    country_code: Mapped[str] = mapped_column(String(2))
    region: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(200))
    # Only coordinates the listing itself provides. Never geocoded.
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    location_precision: Mapped[str | None] = mapped_column(String(16))  # exact | approximate
    setting: Mapped[str] = mapped_column(String(16), default="unknown")  # urban | rural | unknown
    setting_class_raw: Mapped[int | None] = mapped_column(Integer)
    property_type: Mapped[str] = mapped_column(String(16))
    area_m2: Mapped[float | None] = mapped_column(Float)
    bedrooms: Mapped[int | None] = mapped_column(Integer)
    bathrooms: Mapped[int | None] = mapped_column(Integer)
    year_built: Mapped[int | None] = mapped_column(Integer)
    images_status: Mapped[str] = mapped_column(
        String(16), default="unchecked", server_default="unchecked"
    )  # unchecked | ok | broken
    images_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    source: Mapped[Source] = relationship()
    images: Mapped[list["PropertyImage"]] = relationship(
        back_populates="property",
        order_by="PropertyImage.position",
        cascade="all, delete-orphan",
    )


class PropertyImage(Base):
    """A listing photo's URL as published by the source. Never the image file itself."""

    __tablename__ = "property_images"

    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)  # 0 = lead photo
    url: Mapped[str] = mapped_column(String(2000))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str | None] = mapped_column(String(16))  # photo | floorplan | None
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | broken

    property: Mapped[Property] = relationship(back_populates="images")


class PhotoReport(Base):
    __tablename__ = "photo_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"))
    position: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(16))  # price_visible | broken | person | other
    device_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | resolved | dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FxRate(Base):
    __tablename__ = "fx_rates"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate_to_usd: Mapped[float] = mapped_column(Float)


class Game(Base):
    __tablename__ = "games"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    mode: Mapped[str] = mapped_column(String(16))  # classic | daily | hl
    where_scope: Mapped[str] = mapped_column(String(16), default="world")
    where_value: Mapped[str | None] = mapped_column(String(32))
    setting_filter: Mapped[str] = mapped_column(String(32), default="rural,urban")
    difficulty: Mapped[str] = mapped_column(String(8), default="normal")
    device_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    total_score: Mapped[int | None] = mapped_column(Integer)

    rounds: Mapped[list["GameRound"]] = relationship(
        back_populates="game", order_by="GameRound.round_no", cascade="all, delete-orphan"
    )


class GameRound(Base):
    __tablename__ = "game_rounds"

    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), primary_key=True)
    round_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"))
    guess_amount: Mapped[float | None] = mapped_column(Float)
    guess_currency: Mapped[str | None] = mapped_column(String(3))
    guess_local: Mapped[float | None] = mapped_column(Float)
    score: Mapped[int | None] = mapped_column(Integer)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)

    game: Mapped[Game] = relationship(back_populates="rounds")
    property: Mapped[Property] = relationship()


class DailyChallenge(Base):
    __tablename__ = "daily_challenges"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    property_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DailyAttempt(Base):
    __tablename__ = "daily_attempts"
    __table_args__ = (UniqueConstraint("date", "device_id", name="uq_daily_attempt"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date)
    device_id: Mapped[str] = mapped_column(String(64))
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"))


class LeaderboardEntry(Base):
    __tablename__ = "leaderboard_entries"
    __table_args__ = (
        Index(
            "ix_leaderboard_lookup",
            "mode",
            "where_scope",
            "where_value",
            "setting_filter",
            "difficulty",
            "created_at",
        ),
        Index("ix_leaderboard_daily", "mode", "daily_date", "difficulty"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id"), unique=True)
    mode: Mapped[str] = mapped_column(String(16))
    where_scope: Mapped[str] = mapped_column(String(16))
    where_value: Mapped[str | None] = mapped_column(String(32))
    setting_filter: Mapped[str] = mapped_column(
        String(32), default="rural,urban", server_default="rural,urban"
    )
    difficulty: Mapped[str] = mapped_column(String(8))
    daily_date: Mapped[date | None] = mapped_column(Date)  # daily games: the challenge date
    nickname: Mapped[str] = mapped_column(String(16))
    score: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class HlRun(Base):
    __tablename__ = "hl_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    device_id: Mapped[str | None] = mapped_column(String(64))
    difficulty: Mapped[str] = mapped_column(String(8), default="normal")
    streak: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RemovalRequest(Base):
    __tablename__ = "removal_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320))
    reference: Mapped[str] = mapped_column(String(1000))
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Blocklist(Base):
    __tablename__ = "blocklist"

    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    source_ref: Mapped[str] = mapped_column(String(500), primary_key=True)


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_key: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")  # ok|blocked|error|running
    discovered: Mapped[int] = mapped_column(Integer, default=0)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    dropped_country: Mapped[int] = mapped_column(Integer, default=0)
    possible_duplicates: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[dict | None] = mapped_column(JSON)  # e.g. rejection reasons -> counts
    message: Mapped[str | None] = mapped_column(Text)
