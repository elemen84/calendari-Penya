from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.calendar.formatting import description_for_game, title_for_game
from src.calendar.ics import render_ics
from src.models import Game
from src.normalize import source_key
from src.standings.snapshots import StandingRow, StandingsSnapshot

MADRID = ZoneInfo("Europe/Madrid")


def make_game(hour: int = 20, status: str = "scheduled") -> Game:
    return Game(
        competition="Liga Endesa",
        season="2026-27",
        round=12,
        phase="Liga Regular",
        home_team="Penya",
        away_team="Real Madrid",
        start_datetime=datetime(2026, 12, 14, hour, tzinfo=MADRID),
        timezone="Europe/Madrid",
        venue="Palau Olímpic de Badalona",
        status=status,
        source_url="https://www.acb.com/es/liga/calendario",
        source_game_id="105378",
    )


def test_postponed_game_is_marked_and_keeps_identity() -> None:
    game = make_game(status="postponed")
    assert "AJORNAT" in title_for_game(game)
    assert "APLAZADO" not in title_for_game(game)
    assert source_key(game) == source_key(make_game(hour=22))


def test_ics_uid_is_stable_when_time_changes() -> None:
    first = make_game(hour=20)
    second = make_game(hour=21)
    first_ics = render_ics([first], {source_key(first): "description"})
    second_ics = render_ics([second], {source_key(second): "description"})
    uid_line = next(line for line in first_ics.splitlines() if line.startswith("UID:"))
    assert uid_line == next(line for line in second_ics.splitlines() if line.startswith("UID:"))
    assert "DTSTART;TZID=Europe/Madrid:20261214T210000" in second_ics


def test_ics_does_not_duplicate_a_source_game() -> None:
    game = make_game()
    duplicate = replace(game, start_datetime=datetime(2026, 12, 15, 20, tzinfo=MADRID))
    feed = render_ics(
        [game, duplicate],
        {source_key(game): "description"},
    )

    assert feed.count(f"UID:{source_key(game)}@penya-calendar") == 1


def test_acb_event_content_uses_catalan_labels_and_keeps_official_values() -> None:
    game = make_game()
    standings = StandingsSnapshot(
        season="2026-27",
        round_number=12,
        captured_at=datetime(2026, 12, 14, 6, 15, tzinfo=MADRID),
        source_url="https://api2.acb.com/api/seasondata/Competition/standings",
        rows=(
            StandingRow(1, "Real Madrid", 11, 10, 1),
            StandingRow(2, "Valencia Basket", 11, 9, 2),
            StandingRow(3, "Asisa Joventut", 11, 8, 3),
        ),
    )

    description = description_for_game(game, standings)
    content = "\n".join((title_for_game(game), description))

    assert "🏆 Liga Endesa" in content
    assert "#  Equip                  PJ  G  P" in description
    assert "1  Real Madrid            11 10  1" in description
    assert "2  Valencia Basket        11  9  2" in description
    assert "3  Joventut Badalona      11  8  3" in description
    assert "Real Madrid — 10-1" not in description
    assert "Valencia Basket — 9-2" not in description
    assert "Asisa Joventut" not in description
    assert "📍 Palau Olímpic de Badalona" in content
    assert "📊 CLASSIFICACIÓ" in content
    assert "Classificació encara no disponible" not in content
    assert "Font: ACB" in content
    assert "Actualitzat: 14/12/2026 06:15" in content
    assert "Font oficial: https://www.acb.com/es/liga/calendario" in content

    for forbidden in (
        "CLASIFICACIÓN",
        "Clasificación",
        "Fuente",
        "Actualizado",
        "APLAZADO",
        "CANCELADO",
        "FINALIZADO",
        "pendiente",
        "Classification",
        "Source",
        "Updated",
        "Pending",
    ):
        assert forbidden not in content


def test_acb_standings_table_survives_ics_escaping_and_folding() -> None:
    game = make_game()
    standings = StandingsSnapshot(
        season="2026-27",
        round_number=12,
        captured_at=datetime(2026, 12, 14, 6, 15, tzinfo=MADRID),
        source_url="https://api2.acb.com/api/seasondata/Competition/standings",
        rows=(
            StandingRow(1, "Real Madrid", 11, 10, 1),
            StandingRow(2, "Asisa Joventut", 11, 8, 3),
        ),
    )
    description = description_for_game(game, standings)
    feed = render_ics([game], {source_key(game): description})

    assert "DESCRIPTION:" in feed
    assert "\\n" in feed
    assert "\r\n" in feed
    unfolded = feed.replace("\r\n ", "").replace("\r\n", "\n")
    assert "#  Equip                  PJ  G  P" in unfolded
    assert "Joventut Badalona" in unfolded
    assert "1  Real Madrid            11 10  1" in unfolded


def test_acb_event_uses_catalan_unavailable_standings_message() -> None:
    description = description_for_game(make_game())

    assert "Classificació encara no disponible" in description
    assert "Clasificación todavía no disponible" not in description


@pytest.mark.parametrize(
    ("status", "catalan_label", "spanish_label"),
    [
        ("postponed", "AJORNAT", "APLAZADO"),
        ("cancelled", "CANCEL·LAT", "CANCELADO"),
        ("finished", "FINALITZAT", "FINALIZADO"),
    ],
)
def test_event_statuses_are_displayed_in_catalan(
    status: str, catalan_label: str, spanish_label: str
) -> None:
    title = title_for_game(make_game(status=status))

    assert catalan_label in title
    assert spanish_label not in title
