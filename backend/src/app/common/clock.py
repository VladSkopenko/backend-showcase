from datetime import UTC, datetime


# Every timestamp the logic compares comes from here, so tests can replace it to move time.
def now() -> datetime:
    return datetime.now(UTC)
