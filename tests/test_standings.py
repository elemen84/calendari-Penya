from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.models import Game
from src.normalize import standings_display_name
from src.providers.acb import ACBData
from src.providers.bcl import BCLData
from src.standings.snapshots import (
    StandingRow,
    StandingsSnapshot,
    StandingsSnapshotStore,
    format_rows,
    snapshot_from_api,
)
from src.sync import execute_sync, prepare_sync

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
        rows=(StandingRow(1, team, 1, 1, 0, 80, 70, 10),),
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
    assert "1. Current Team" in acb_description
    assert "   1 PJ · 1 G · 0 P · PF 80 · PC 70 · +10" in acb_description
    assert "Current Team — 1-0" not in acb_description
    assert "#  Equip" not in acb_description


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
    assert "1. Historical Team" in next(
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
    assert "1. Historical Team" in acb_description
    assert "Later Current Team" not in acb_description
    assert "Should Not Replace" not in acb_description
    loaded = store.load("2026-27", 7)
    assert loaded is not None
    assert loaded.rows[0].team == "Historical Team"
    assert loaded.rows[0].points_for == 80


def test_legacy_snapshot_without_score_fields_still_loads(tmp_path: Path) -> None:
    store = StandingsSnapshotStore(tmp_path)
    path = store.path_for("2026-27", 3)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
{
  "captured_at": "2026-10-20T08:00:00+02:00",
  "round_number": 3,
  "rows": [
    {
      "losses": 1,
      "matches_played": 3,
      "position": 2,
      "team": "Asisa Joventut",
      "wins": 2
    }
  ],
  "season": "2026-27",
  "source_url": "https://api2.acb.com/api/seasondata/Competition/standings"
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    loaded = store.load("2026-27", 3)
    assert loaded is not None
    assert loaded.rows[0].team == "Asisa Joventut"
    assert loaded.rows[0].points_for is None
    assert loaded.rows[0].points_against is None
    assert loaded.rows[0].point_difference is None
    rendered = format_rows(loaded)
    assert "2. Joventut Badalona" in rendered
    assert "   3 PJ · 2 G · 1 P" in rendered
    assert "PF" not in rendered
    assert "PC" not in rendered


def test_format_rows_renders_vertical_blocks_with_pf_pc_and_joventut() -> None:
    snapshot_data = StandingsSnapshot(
        season="2026-27",
        round_number=3,
        captured_at=datetime(2026, 10, 20, 8, tzinfo=MADRID),
        source_url="https://api2.acb.com/api/seasondata/Competition/standings",
        rows=(
            StandingRow(1, "Real Madrid", 3, 3, 0, 252, 221, 31),
            StandingRow(2, "Asisa Joventut", 3, 2, 1, 241, 228, 13),
            StandingRow(3, "Unicaja", 3, 2, 1, 236, 231, 5),
            StandingRow(4, "Recoletas Salud San Pablo Burgos", 3, 1, 2, 220, 240, -20),
        ),
    )

    table = format_rows(snapshot_data)
    assert table == (
        "1. Real Madrid\n"
        "   3 PJ · 3 G · 0 P · PF 252 · PC 221 · +31\n"
        "\n"
        "2. Joventut Badalona\n"
        "   3 PJ · 2 G · 1 P · PF 241 · PC 228 · +13\n"
        "\n"
        "3. Unicaja\n"
        "   3 PJ · 2 G · 1 P · PF 236 · PC 231 · +5\n"
        "\n"
        "4. San Pablo Burgos\n"
        "   3 PJ · 1 G · 2 P · PF 220 · PC 240 · -20"
    )
    assert "#  Equip" not in table
    assert "\u2007" not in table
    assert "Asisa Joventut" not in table
    assert snapshot_data.rows[1].team == "Asisa Joventut"
    assert snapshot_data.rows[3].team == "Recoletas Salud San Pablo Burgos"


def test_snapshot_from_api_maps_official_acb_score_fields() -> None:
    payload = {
        "teams": [
            {"id": 1, "fullName": "Real Madrid"},
            {"id": 2, "fullName": "Asisa Joventut"},
        ],
        "standings": [
            {
                "teamId": 2,
                "position": 2,
                "matchesPlayed": 3,
                "wins": 2,
                "loses": 1,
                "pointsFor": 241,
                "pointsAgainst": 228,
                "plusMinus": 13,
            },
            {
                "teamId": 1,
                "position": 1,
                "matchesPlayed": 3,
                "wins": 3,
                "loses": 0,
                "pointsFor": 252,
                "pointsAgainst": 221,
                "plusMinus": 31,
            },
        ],
    }
    snap = snapshot_from_api(
        payload,
        season="2025-26",
        source_url="https://api2.acb.com/api/seasondata/Competition/standings",
        captured_at=datetime(2026, 5, 30, tzinfo=MADRID),
        round_number=34,
    )
    assert snap is not None
    assert snap.rows[0].team == "Real Madrid"
    assert snap.rows[0].points_for == 252
    assert snap.rows[0].points_against == 221
    assert snap.rows[0].point_difference == 31
    assert snap.rows[1].team == "Asisa Joventut"
    assert snap.rows[1].point_difference == 13


def test_standings_display_name_falls_back_for_unknown_teams() -> None:
    assert standings_display_name("Asisa Joventut") == "Joventut Badalona"
    assert standings_display_name("Club Joventut Badalona SAD") == "Joventut Badalona"
    assert standings_display_name("Unknown Newcomer BC") == "Unknown Newcomer BC"


def _unfold_ics(text: str) -> str:
    return text.replace("\r\n ", "").replace("\n ", "").replace("\r\n", "\n")


def test_production_ics_path_uses_vertical_standings(tmp_path: Path) -> None:
    """Integration: prepare_sync → execute_sync/write_ics vertical standings."""

    acb_game = game(competition="Liga Endesa", round_number=8)
    bcl_game = game(competition="BCL", round_number=1)
    current = StandingsSnapshot(
        season="2026-27",
        round_number=8,
        captured_at=datetime(2026, 12, 11, 8, tzinfo=MADRID),
        source_url="https://api2.acb.com/api/seasondata/Competition/standings",
        rows=(
            StandingRow(1, "Real Madrid", 3, 3, 0, 252, 221, 31),
            StandingRow(2, "Asisa Joventut", 3, 2, 1, 241, 228, 13),
            StandingRow(3, "Recoletas Salud San Pablo Burgos", 3, 1, 2, 220, 240, -20),
        ),
    )
    acb = StubACB(
        ACBData(
            games=(acb_game,),
            season="2026-27",
            edition_id=91,
            round_ids={8: 801},
            round_statuses={8: ("scheduled",)},
            raw_match_count=1,
        ),
        current=current,
        round_snapshot=None,
    )
    bcl = StubBCL(BCLData(games=(bcl_game,), competition_id=209123, raw_game_count=1))
    ics_path = tmp_path / "penya.ics"

    prepared = prepare_sync(
        acb,
        bcl,
        snapshot_store=StandingsSnapshotStore(tmp_path / "standings"),
        now=datetime(2026, 12, 1, tzinfo=MADRID),
    )
    execute_sync(prepared, ics_path=ics_path)

    raw = ics_path.read_text(encoding="utf-8")
    logical = _unfold_ics(raw).replace("\\n", "\n")
    events = logical.split("BEGIN:VEVENT")[1:]
    acb_event = next(event for event in events if "UID:liga-endesa:" in event)
    bcl_event = next(event for event in events if "UID:bcl:" in event)

    assert "CLASSIFICACIÓ" in acb_event
    assert "1. Real Madrid" in acb_event
    assert "2. Joventut Badalona" in acb_event
    assert "3 PJ · 3 G · 0 P · PF 252 · PC 221 · +31" in acb_event
    assert "3 PJ · 2 G · 1 P · PF 241 · PC 228 · +13" in acb_event
    assert "San Pablo Burgos" in acb_event
    assert "Asisa Joventut" not in acb_event
    assert "Recoletas Salud San Pablo Burgos" not in acb_event
    assert "#  Equip" not in acb_event
    assert "\u2007" not in acb_event
    assert "X-ALT-DESC" not in acb_event
    assert "— 3-0" not in acb_event

    assert "CLASSIFICACIÓ" not in bcl_event
    assert "PJ ·" not in bcl_event
    assert "Joventut Badalona" not in bcl_event
    assert current.rows[1].team == "Asisa Joventut"
    assert current.rows[2].team == "Recoletas Salud San Pablo Burgos"
