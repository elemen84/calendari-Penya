from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.sync_calendar import should_sync
from src.models import Game
from src.normalize import source_key
from src.providers.acb import ACBData
from src.providers.bcl import BCLData
from src.sync import PreparedSync, SyncStats, execute_sync

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


def test_sync_generates_ics_without_google_configuration(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_CALENDAR_ID", raising=False)
    game = Game(
        competition="Liga Endesa",
        season="2026-27",
        round=12,
        phase="Liga Regular",
        home_team="Penya",
        away_team="Real Madrid",
        start_datetime=datetime(2026, 12, 14, 20, tzinfo=MADRID),
        timezone="Europe/Madrid",
        venue=None,
        status="scheduled",
        source_url="https://www.acb.com/es/liga/calendario",
        source_game_id="105378",
    )
    acb = ACBData(
        games=(game,),
        season="2026-27",
        edition_id=91,
        round_ids={12: 801},
        round_statuses={12: ("scheduled",)},
        raw_match_count=1,
    )
    bcl = BCLData(games=(), competition_id=209123, raw_game_count=0)
    key = source_key(game)
    prepared = PreparedSync(
        games=(game,),
        descriptions={key: "🏆 Liga Endesa"},
        html_descriptions={},
        acb=acb,
        bcl=bcl,
        stats=SyncStats(acb_games=1),
    )

    ics_path = tmp_path / "penya.ics"
    stats = execute_sync(prepared, ics_path=ics_path)

    assert stats is prepared.stats
    assert ics_path.exists()
    assert f"UID:{key}@penya-calendar" in ics_path.read_text(encoding="utf-8")
