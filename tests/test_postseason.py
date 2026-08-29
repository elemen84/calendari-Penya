from copy import deepcopy

from src.normalize import source_key
from src.providers.acb import ACBProvider
from src.providers.bcl import BCLProvider
from tests.test_providers import FakeHTTP, acb_calendar, acb_match, bcl_game


def test_acb_playoff_round_is_discovered_after_regular_season() -> None:
    regular_rounds = [
        {"id": 8000 + number, "roundNumber": number, "matches": [acb_match(str(105000 + number))]}
        for number in range(1, 35)
    ]
    playoff = {
        "id": 8035,
        "roundNumber": 35,
        "matches": [acb_match("106000")],
    }
    payload = acb_calendar([])
    payload["rounds"] = regular_rounds + [playoff]

    data = ACBProvider(FakeHTTP(calendar=payload), season_start_year=2026).fetch_games()

    assert len(data.games) == 35
    assert data.games[-1].source_game_id == "106000"
    assert data.games[-1].round == 35


def test_bcl_new_phase_is_added_without_changing_existing_phase() -> None:
    regular = bcl_game(2001)
    next_phase = bcl_game(2002)
    next_phase["round"] = {"roundNumber": 2, "roundName": "Round of 16"}
    next_phase["groupPairingCode"] = None
    payload = [regular, next_phase]

    data = BCLProvider(FakeHTTP(bcl=payload), competition_id=209123).fetch_games()
    by_id = {item.source_game_id: item for item in data.games}

    assert set(by_id) == {"2001", "2002"}
    assert by_id["2001"].phase == "Regular Season"
    assert by_id["2002"].phase == "Round of 16"


def test_new_phase_can_grow_total_without_expected_count_rules() -> None:
    regular = bcl_game(2001)
    new_phase = deepcopy(regular)
    new_phase["gameId"] = 2002
    new_phase["round"] = {"roundNumber": 2, "roundName": "Quarter-Finals"}
    data = BCLProvider(FakeHTTP(bcl=[regular, new_phase]), competition_id=209123).fetch_games()

    assert len(data.games) == 2
    assert len({source_key(game) for game in data.games}) == 2
