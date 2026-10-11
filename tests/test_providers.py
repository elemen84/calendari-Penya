from copy import deepcopy
from pathlib import Path

import pytest

from src.calendar.formatting import description_for_game, title_for_game
from src.calendar.ics import write_ics
from src.normalize import source_key
from src.providers.acb import (
    ACB_CALENDAR_ENDPOINT,
    ACB_STANDINGS_ENDPOINT,
    ACBProvider,
    ProviderError,
)
from src.providers.bcl import BCLProvider, BCLProviderError


class FakeHTTP:
    def __init__(
        self,
        *,
        calendar=None,
        standings=None,
        bcl=None,
        page="<div data-event-id='209123'>",
    ):
        self.calendar = calendar
        self.standings = standings
        self.bcl = bcl
        self.page = page

    def get_json(self, url, *, headers=None, params=None):
        if url.endswith(ACB_CALENDAR_ENDPOINT):
            return self.calendar
        if url.endswith(ACB_STANDINGS_ENDPOINT):
            return self.standings
        if "getgdapgamesbycompetitionid" in url:
            return self.bcl
        raise AssertionError(f"Unexpected URL: {url}")

    def get_text(self, url, *, headers=None):
        return self.page


def acb_calendar(matches):
    return {
        "availableFilters": {
            "seasons": [{"id": 91, "seasonStartYear": 2026, "seasonEndYear": 2027}],
        },
        "selectedFilters": {"competition": 1, "season": 91},
        "teams": [
            {"id": 4473, "fullName": "Asisa Joventut"},
            {"id": 1, "fullName": "Real Madrid"},
            {"id": 2, "fullName": "Valencia Basket"},
        ],
        "rounds": [{"id": 801, "roundNumber": 12, "matches": matches}],
    }


def acb_match(match_id="105378", home=4473, away=1, status="NOT_STARTED"):
    return {
        "id": match_id,
        "homeTeamId": home,
        "awayTeamId": away,
        "startDateTime": "2026-12-14T19:30:00Z",
        "matchStatus": status,
    }


def test_acb_provider_detects_liga_endesa_and_filters_other_games() -> None:
    http = FakeHTTP(calendar=acb_calendar([acb_match(), acb_match("other", 2, 1)]))
    data = ACBProvider(http, season_start_year=2026).fetch_games()

    assert len(data.games) == 1
    assert data.games[0].competition == "Liga Endesa"
    assert data.games[0].home_team == "Penya"
    assert data.games[0].round == 12
    assert data.raw_match_count == 2


def test_acb_provider_fails_closed_on_zero_matches() -> None:
    with pytest.raises(ProviderError, match="zero usable games"):
        ACBProvider(FakeHTTP(calendar=acb_calendar([])), season_start_year=2026).fetch_games()


def bcl_game(game_id=2001, competition_code="BCL", gender="men", team_a="Asisa Joventut"):
    return {
        "gameId": game_id,
        "statusCode": "INIT",
        "isPostponed": False,
        "teamA": {"shortName": team_a},
        "teamB": {"shortName": "FC Porto"},
        "gameDateTimeUTC": "2026-10-06T18:00:00Z",
        "venueName": "Palau Olímpic de Badalona",
        "groupPairingCode": "H",
        "round": {"roundNumber": 1, "roundName": "Regular Season"},
        "competition": {
            "competitionCode": competition_code,
            "gender": gender,
            "ageCategory": "senior",
            "start": "2026-09-01T00:00:00Z",
        },
    }


def test_bcl_provider_detects_mens_bcl() -> None:
    http = FakeHTTP(bcl=[bcl_game(), bcl_game(2002, competition_code="OTHER")])
    data = BCLProvider(http, competition_id=209123).fetch_games()

    assert len(data.games) == 1
    assert data.games[0].competition == "BCL"
    assert data.games[0].home_team == "Penya"
    assert data.games[0].venue == "Palau Olímpic de Badalona"
    assert data.games[0].round is None
    assert data.games[0].phase == "Regular Season"
    assert data.games[0].group == "H"


def test_bcl_provider_fails_closed_on_zero_matches() -> None:
    with pytest.raises(BCLProviderError, match="zero games"):
        BCLProvider(FakeHTTP(bcl=[]), competition_id=209123).fetch_games()


def test_bcl_description_never_contains_standings() -> None:
    game = BCLProvider(FakeHTTP(bcl=[bcl_game()]), competition_id=209123).fetch_games().games[0]
    description = description_for_game(game)
    title = title_for_game(game)
    assert "🏆 Basketball Champions League" in description
    assert "Fase: Regular Season" in description
    assert "Jornada:" not in description
    assert "J1" not in title
    assert " · J" not in title
    assert "Grup: H" in description
    assert "📍 Palau Olímpic de Badalona" in description
    assert "CLASSIFICACIÓ" not in description
    assert "classificació" not in description.casefold()
    assert "Font oficial: https://www.championsleague.basketball/en/games" in description


def test_bcl_regular_season_does_not_publish_phase_index_as_jornada() -> None:
    first = bcl_game(2001)
    second = deepcopy(first)
    second["gameId"] = 2002
    second["gameDateTimeUTC"] = "2026-10-21T18:00:00Z"
    second["teamB"] = {"shortName": "Telekom Baskets Bonn"}
    second["round"] = {"roundNumber": 1, "roundName": "Regular Season"}

    data = BCLProvider(FakeHTTP(bcl=[first, second]), competition_id=209123).fetch_games()

    assert len(data.games) == 2
    assert {game.round for game in data.games} == {None}
    assert {game.phase for game in data.games} == {"Regular Season"}
    for game in data.games:
        assert game.round is None
        assert "J1" not in title_for_game(game)
        assert "Jornada:" not in description_for_game(game)


def test_bcl_play_ins_keeps_phase_without_fake_jornada() -> None:
    play_ins = bcl_game(3001)
    play_ins["round"] = {"roundNumber": 2, "roundName": "Play-ins"}
    play_ins["groupPairingCode"] = None

    game = BCLProvider(FakeHTTP(bcl=[play_ins]), competition_id=209123).fetch_games().games[0]

    assert game.phase == "Play-ins"
    assert game.round is None
    assert game.group is None
    assert "Play-ins" in title_for_game(game)
    assert "J2" not in title_for_game(game)
    assert "Jornada:" not in description_for_game(game)


def test_acb_jornada_label_is_unchanged() -> None:
    http = FakeHTTP(calendar=acb_calendar([acb_match()]))
    game = ACBProvider(http, season_start_year=2026).fetch_games().games[0]

    assert game.round == 12
    assert "Liga Endesa J12" in title_for_game(game)
    assert "Jornada 12" in description_for_game(game)


def test_bcl_uids_stay_stable_when_round_is_omitted(tmp_path: Path) -> None:
    first = bcl_game(2001)
    second = deepcopy(first)
    second["gameId"] = 2002
    second["round"] = {"roundNumber": 2, "roundName": "Play-ins"}
    second["groupPairingCode"] = None
    data = BCLProvider(FakeHTTP(bcl=[first, second]), competition_id=209123).fetch_games()

    keys = [source_key(game) for game in data.games]
    assert keys == ["bcl:2026-27:2001", "bcl:2026-27:2002"]
    assert len(set(keys)) == 2

    feed_path = tmp_path / "penya.ics"
    write_ics(
        feed_path,
        data.games,
        {source_key(game): description_for_game(game) for game in data.games},
    )
    feed = feed_path.read_text(encoding="utf-8")
    uids = [line for line in feed.splitlines() if line.startswith("UID:")]
    assert uids == [
        "UID:bcl:2026-27:2001@penya-calendar",
        "UID:bcl:2026-27:2002@penya-calendar",
    ]
    assert "J1" not in feed
    assert "Jornada:" not in feed
    assert "Fase: Regular Season" in feed
    assert "Fase: Play-ins" in feed
