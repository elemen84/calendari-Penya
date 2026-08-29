from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.models import Game
from src.providers.acb import ACBData
from src.providers.bcl import BCLData
from src.standings.snapshots import (
    StandingRow,
    StandingsSnapshot,
    StandingsSnapshotStore,
)
from src.sync import prepare_sync

MADRID = ZoneInfo("Europe/Madrid")


def game(
    *,
    competition: str,
    round_number: int,
    start_hour: int = 20,
    status: str = "scheduled",
) -> Game:
    return Game(
        competition=competition,
        season="2026-27",
        round=round_number,
        phase="Liga Regular" if competition == "Liga Endesa" else "Regular Season",
        home_team="Penya",
        away_team="Real Madrid" if competition == "Liga Endesa" else "FC Porto",
        start_datetime=datetime(2026, 12, 10, start_hour, tzinfo=MADRID),
        timezone="Europe/Madrid",
        venue=None,
        status=status,
        source_url="https://www.acb.com/es/liga/calendario"
        if competition == "Liga Endesa"
        else "https://www.championsleague.basketball/en/games",
        source_game_id=f"{competition}-{round_number}",
    )


def snapshot(round_number: int, team: str, captured_hour: int) -> StandingsSnapshot:
    return StandingsSnapshot(
        season="2026-27",
        round_number=round_number,
        captured_at=datetime(2026, 12, 11, captured_hour, tzinfo=MADRID),
        source_url="https://api2.acb.com/api/seasondata/Competition/standings",
        rows=(StandingRow(1, team, 1, 1, 0),),
    )


@dataclass
class StubACB:
    acb_data: ACBData
    current: StandingsSnapshot | None
    round_snapshot: StandingsSnapshot | None

    def fetch_games(self) -> ACBData:
        return self.acb_data

    def fetch_standings(self, round_id=None):
        return self.round_snapshot if round_id is not None else self.current


@dataclass
class StubBCL:
    bcl_data: BCLData

    def fetch_games(self) -> BCLData:
        return self.bcl_data


def data_for(acb_game: Game, statuses: tuple[str, ...]) -> tuple[StubACB, StubBCL]:
    acb_data = ACBData(
        games=(acb_game,),
        season="2026-27",
        edition_id=91,
        round_ids={acb_game.round: 801},
        round_statuses={acb_game.round: statuses},
        raw_match_count=1,
    )
    bcl_game = game(competition="BCL", round_number=1)
    bcl_data = BCLData(games=(bcl_game,), competition_id=209123, raw_game_count=1)
    return (
        StubACB(acb_data, current=snapshot(acb_game.round, "Current Team", 8), round_snapshot=None),
        StubBCL(bcl_data),
    )


def test_future_game_uses_current_standings(tmp_path: Path) -> None:
    acb_game = game(competition="Liga Endesa", round_number=8)
    acb, bcl = data_for(acb_game, ("scheduled",))
    prepared = prepare_sync(
        acb,
        bcl,
        snapshot_store=StandingsSnapshotStore(tmp_path),
        now=datetime(2026, 12, 1, tzinfo=MADRID),
    )

    acb_key = next(key for key in prepared.descriptions if "liga-endesa" in key)
    acb_description = prepared.descriptions[acb_key]
    assert "Current Team 1-0" in acb_description


def test_completed_round_snapshot_is_saved_and_then_frozen(tmp_path: Path) -> None:
    acb_game = game(competition="Liga Endesa", round_number=7, status="finished")
    acb, bcl = data_for(acb_game, ("finished",))
    acb.round_snapshot = snapshot(7, "Historical Team", 9)
    store = StandingsSnapshotStore(tmp_path)
    first = prepare_sync(
        acb,
        bcl,
        snapshot_store=store,
        now=datetime(2026, 12, 12, tzinfo=MADRID),
    )
    assert 7 in first.stats.snapshots_frozen
    assert "Historical Team 1-0" in next(
        value for key, value in first.descriptions.items() if "liga-endesa" in key
    )

    acb.current = snapshot(7, "Later Current Team", 12)
    acb.round_snapshot = snapshot(7, "Should Not Replace", 13)
    second = prepare_sync(
        acb,
        bcl,
        snapshot_store=store,
        now=datetime(2027, 1, 20, tzinfo=MADRID),
    )
    acb_description = next(
        value for key, value in second.descriptions.items() if "liga-endesa" in key
    )
    assert "Historical Team 1-0" in acb_description
    assert "Later Current Team" not in acb_description
    assert "Should Not Replace" not in acb_description
