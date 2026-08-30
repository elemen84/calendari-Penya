from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.models import Game
from src.normalize import (
    display_team_name,
    is_penya_team,
    normalize_team_name,
    source_key,
    standings_display_name,
)


@pytest.mark.parametrize(
    "name",
    [
        "Joventut",
        "Joventut Badalona",
        "Club Joventut Badalona",
        "ASISA Joventut",
        "Penya",
        "  asisa joventut  ",
    ],
)
def test_joventut_aliases_are_recognized(name: str) -> None:
    assert is_penya_team(name)
    assert display_team_name(name) == "Penya"
    assert standings_display_name(name) == "Joventut Badalona"


def test_other_categories_are_not_recognized_as_the_first_team() -> None:
    assert normalize_team_name("Joventut Badalona Women") not in {
        normalize_team_name("Joventut Badalona")
    }
    assert not is_penya_team("Joventut Badalona Women")
    assert not is_penya_team("CB Prat")


def test_source_key_is_independent_of_time() -> None:
    game = Game(
        competition="Liga Endesa",
        season="2026-27",
        round=12,
        phase="Liga Regular",
        home_team="Penya",
        away_team="Real Madrid",
        start_datetime=datetime(2026, 12, 14, 20, tzinfo=ZoneInfo("Europe/Madrid")),
        timezone="Europe/Madrid",
        venue=None,
        status="scheduled",
        source_url="https://www.acb.com/es/liga/calendario",
        source_game_id="105378",
    )
    moved = replace(
        game,
        start_datetime=datetime(2026, 12, 15, 21, tzinfo=ZoneInfo("Europe/Madrid")),
    )
    assert source_key(game) == source_key(moved)
