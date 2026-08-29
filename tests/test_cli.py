from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.sync_calendar import should_sync

MADRID = ZoneInfo("Europe/Madrid")


def test_sync_gate_waits_until_48_hours() -> None:
    now = datetime(2026, 8, 28, 6, 15, tzinfo=MADRID)
    recent = (now - timedelta(hours=47, minutes=59)).isoformat()
    allowed, next_at = should_sync({"last_successful_sync": recent}, now, force=False)

    assert not allowed
    assert next_at is not None


def test_force_bypasses_sync_gate() -> None:
    now = datetime(2026, 8, 28, 6, 15, tzinfo=MADRID)
    recent = now.isoformat()
    assert should_sync({"last_successful_sync": recent}, now, force=True) == (True, None)
