"""Scheduled jobs: `python -m app.jobs daily` creates today's Daily Challenge (run at 00:05 UTC).
If the job doesn't run, the first Daily request of the day creates it lazily instead."""

import sys

from app.core import daily, quota
from app.core.db import SessionLocal
from app.core.selection import PoolTooSmall


def main(argv: list[str]) -> int:
    if argv[:1] != ["daily"]:
        print("usage: python -m app.jobs daily", file=sys.stderr)
        return 2
    day = quota.utc_today()
    with SessionLocal() as db:
        try:
            row = daily.get_or_create(db, day)
        except PoolTooSmall as e:
            print(f"Cannot create the Daily Challenge for {day}: {e}", file=sys.stderr)
            return 1
    print(f"Daily Challenge {day}: {len(row.property_ids)} properties")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
