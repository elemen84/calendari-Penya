import pytest

from src.calendar.formatting import description_for_game
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


def test_bcl_provider_fails_closed_on_zero_matches() -> None:
    with pytest.raises(BCLProviderError, match="zero games"):
        BCLProvider(FakeHTTP(bcl=[]), competition_id=209123).fetch_games()


def test_bcl_description_never_contains_standings() -> None:
    game = BCLProvider(FakeHTTP(bcl=[bcl_game()]), competition_id=209123).fetch_games().games[0]
    description = description_for_game(game)
    assert "🏆 Basketball Champions League" in description
    assert "Fase: Regular Season" in description
    assert "Jornada: 1" in description
    assert "Grup: H" in description
    assert "📍 Palau Olímpic de Badalona" in description
    assert "CLASSIFICACIÓ" not in description
    assert "classificació" not in description.casefold()
    assert "Font oficial: https://www.championsleague.basketball/en/games" in description
