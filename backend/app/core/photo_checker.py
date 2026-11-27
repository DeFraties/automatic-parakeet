"""Background Mapillary check: finds photos for unchecked homes while the API runs, so the pool
of playable homes fills up on its own (only homes with photos are played by default).

One thread per server. With several Uvicorn workers, a file lock in the cache directory makes
sure only one of them runs the checker.
"""

import fcntl
import logging
import threading
import time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import mapillary
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import Property

log = logging.getLogger(__name__)

PRECISE = ("exact", "street")
BATCH = 25
IDLE_S = 60  # nothing to check: look again in a minute (new imports)
ERROR_BACKOFF_S = 300


def _pending_query():
    return select(Property).where(
        Property.mly_status == "unchecked",
        Property.is_active.is_(True),
        Property.location_precision.in_(PRECISE),
    )


def pending_count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(_pending_query().subquery())).scalar_one()


def check_batch(db: Session, token: str, *, limit: int = BATCH, pause_s: float = 0.0) -> int:
    """Check up to `limit` unchecked homes. Returns how many were checked.
    Raises MapillaryError on API problems (nothing is marked for that home)."""
    props = db.execute(_pending_query().order_by(Property.created_at).limit(limit)).scalars()
    n = 0
    for p in props:
        if n and pause_s:
            time.sleep(pause_s)
        image_id = mapillary.resolver.find(p.lat, p.lng, token)
        p.mly_image_id, p.mly_status = image_id, ("ok" if image_id else "none")
        db.commit()
        n += 1
    return n


class BackgroundPhotoChecker(threading.Thread):
    def __init__(self):
        super().__init__(name="photo-checker", daemon=True)
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        s = get_settings()
        pause = 1 / max(0.1, s.background_photo_check_per_second)
        log.info("background photo check started")
        while not self._stop.is_set():
            wait = IDLE_S
            try:
                with SessionLocal() as db:
                    n = check_batch(db, s.mapillary_token, pause_s=pause)
                    if n:
                        log.info("photo check: %d homes checked, %d left", n, pending_count(db))
                        wait = pause
            except mapillary.MapillaryError as e:
                log.warning("photo check paused for 5 minutes: %s", e)
                wait = ERROR_BACKOFF_S
            except Exception:  # never let the thread die silently
                log.exception("photo check failed; retrying in 5 minutes")
                wait = ERROR_BACKOFF_S
            self._stop.wait(wait)


_lock_handle = None


def start_background_checker() -> BackgroundPhotoChecker | None:
    """Start the checker if configured and no other worker already runs one."""
    global _lock_handle
    s = get_settings()
    if not (s.background_photo_check and s.mapillary_token):
        return None
    lock_path = Path(s.ingest_cache_dir) / "photo_checker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "w")  # noqa: SIM115  (kept open for the process lifetime)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None  # another worker has it
    _lock_handle = handle
    t = BackgroundPhotoChecker()
    t.start()
    return t
