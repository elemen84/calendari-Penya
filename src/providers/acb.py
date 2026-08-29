from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from src.http_client import OfficialHttpClient
from src.models import TIMEZONE_NAME, Game
from src.normalize import display_team_name, is_penya_team, season_label
from src.standings.snapshots import SnapshotError, StandingsSnapshot, snapshot_from_api

LOGGER = logging.getLogger(__name__)

ACB_API_BASE = "https://api2.acb.com"
ACB_CALENDAR_ENDPOINT = "/api/seasondata/Calendar/season-calendar"
ACB_STANDINGS_ENDPOINT = "/api/seasondata/Competition/standings"
ACB_CALENDAR_URL = "https://www.acb.com/es/liga/calendario"
ACB_STANDINGS_URL = "https://www.acb.com/es/liga/clasificacion"
ACB_COMPETITION_ID = 1
# This is the public browser key used by acb.com, not a private credential.
ACB_PUBLIC_API_KEY = "0dd94928-6f57-4c08-a3bd-b1b2f092976e"
MADRID_TZ = ZoneInfo(TIMEZONE_NAME)


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ACBData:
    games: tuple[Game, ...]
    season: str
    edition_id: int
    round_ids: dict[int, int]
    round_statuses: dict[int, tuple[str, ...]]
    raw_match_count: int


def _parse_utc(value: Any) -> tuple[datetime | None, Any]:
    if not isinstance(value, str) or not value or value.startswith("0001-"):
        return None, None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderError(f"Invalid ACB date: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    local = parsed.astimezone(MADRID_TZ)
    return local, local.date()


def _normalize_status(value: Any) -> str:
    statuses = {
        "NOT_STARTED": "scheduled",
        "NOT_SCHEDULED": "scheduled",
        "STARTED": "scheduled",
        "FINALIZED": "finished",
        "POSTPONED": "postponed",
        "SUSPENDED": "postponed",
        "CANCELLED": "cancelled",
        "CANCELED": "cancelled",
    }
    try:
        return statuses[str(value).upper()]
    except KeyError as exc:
        raise ProviderError(f"Unknown ACB match status: {value}") from exc


def _season_from_filters(payload: dict[str, Any], requested: int | None) -> tuple[int, int, str]:
    filters = payload.get("availableFilters")
    selected = payload.get("selectedFilters")
    if not isinstance(filters, dict) or not isinstance(selected, dict):
        raise ProviderError("ACB calendar response lacks filter metadata")
    seasons = filters.get("seasons")
    if not isinstance(seasons, list):
        raise ProviderError("ACB calendar response lacks seasons")
    candidates = [s for s in seasons if isinstance(s, dict)]
    selected_id = selected.get("season")
    matching = [
        s for s in candidates if requested is not None and s.get("seasonStartYear") == requested
    ]
    chosen = matching[0] if matching else next(
        (s for s in candidates if s.get("id") == selected_id), None
    )
    if chosen is None and candidates:
        chosen = max(candidates, key=lambda item: int(item.get("seasonStartYear", 0)))
    if not chosen:
        raise ProviderError("ACB did not return a usable season")
    try:
        return int(chosen["id"]), int(chosen["seasonStartYear"]), season_label(
            int(chosen["seasonStartYear"])
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderError("ACB season metadata is incomplete") from exc


def _validate_calendar_shape(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProviderError("ACB calendar response is not an object")
    if not isinstance(payload.get("teams"), list) or not isinstance(payload.get("rounds"), list):
        raise ProviderError("ACB calendar response lacks teams or rounds")
    return payload


class ACBProvider:
    def __init__(
        self,
        http: OfficialHttpClient | Any | None = None,
        *,
        season_start_year: int | None = None,
        api_key: str = ACB_PUBLIC_API_KEY,
    ) -> None:
        self.http = http or OfficialHttpClient()
        self.season_start_year = season_start_year
        self.api_key = api_key
        self._edition_id: int | None = None
        self._season: str | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {"X-APIKEY": self.api_key, "Accept": "application/json"}

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        return self.http.get_json(
            f"{ACB_API_BASE}{endpoint}", headers=self.headers, params=params or {}
        )

    def fetch_games(self) -> ACBData:
        initial = _validate_calendar_shape(self._get(ACB_CALENDAR_ENDPOINT))
        edition_id, _, season = _season_from_filters(initial, self.season_start_year)
        selected = initial.get("selectedFilters", {})
        selected_edition = selected.get("season") if isinstance(selected, dict) else None
        selected_competition = selected.get("competition") if isinstance(selected, dict) else None
        payload = initial
        if selected_edition != edition_id or selected_competition != ACB_COMPETITION_ID:
            payload = _validate_calendar_shape(
                self._get(
                    ACB_CALENDAR_ENDPOINT,
                    {"competitionId": ACB_COMPETITION_ID, "editionId": edition_id},
                )
            )

        teams = payload["teams"]
        team_names: dict[int, str] = {}
        for team in teams:
            if not isinstance(team, dict):
                raise ProviderError("ACB calendar contains an invalid team")
            try:
                team_names[int(team["id"])] = str(team["fullName"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError("ACB calendar team is incomplete") from exc

        games: list[Game] = []
        round_ids: dict[int, int] = {}
        round_statuses: dict[int, tuple[str, ...]] = {}
        raw_match_count = 0
        for round_data in payload["rounds"]:
            if not isinstance(round_data, dict):
                raise ProviderError("ACB calendar contains an invalid round")
            try:
                round_number = int(round_data["roundNumber"])
                round_id = int(round_data["id"])
                matches = round_data["matches"]
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError("ACB round metadata is incomplete") from exc
            if not isinstance(matches, list):
                raise ProviderError("ACB round matches is not a list")
            round_ids[round_number] = round_id
            statuses: list[str] = []
            for match in matches:
                if not isinstance(match, dict):
                    raise ProviderError("ACB calendar contains an invalid match")
                raw_match_count += 1
                try:
                    home = team_names[int(match["homeTeamId"])]
                    away = team_names[int(match["awayTeamId"])]
                    source_id = str(match["id"])
                    status = _normalize_status(match["matchStatus"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ProviderError("ACB match is incomplete") from exc
                statuses.append(status)
                if not (is_penya_team(home) or is_penya_team(away)):
                    continue
                start_datetime, start_date = _parse_utc(match.get("startDateTime"))
                if str(match.get("matchStatus", "")).upper() == "NOT_SCHEDULED":
                    start_datetime = None
                games.append(
                    Game(
                        competition="Liga Endesa",
                        season=season,
                        round=round_number,
                        phase="Liga Regular" if round_number <= 34 else None,
                        home_team=display_team_name(home),
                        away_team=display_team_name(away),
                        start_datetime=start_datetime,
                        timezone=TIMEZONE_NAME,
                        venue=None,
                        status=status,
                        source_url=ACB_CALENDAR_URL,
                        source_game_id=source_id,
                        start_date=start_date,
                    )
                )
            round_statuses[round_number] = tuple(statuses)
        if raw_match_count == 0 or not games:
            raise ProviderError(
                "ACB returned zero usable games; refusing to synchronize or remove existing events"
            )
        self._edition_id = edition_id
        self._season = season
        return ACBData(
            games=tuple(
                sorted(
                    games,
                    key=lambda game: (game.start_date or datetime.max.date(), game.round or 0),
                )
            ),
            season=season,
            edition_id=edition_id,
            round_ids=round_ids,
            round_statuses={key: tuple(value) for key, value in round_statuses.items()},
            raw_match_count=raw_match_count,
        )

    def fetch_standings(self, round_id: int | None = None) -> StandingsSnapshot | None:
        if self._edition_id is None or self._season is None:
            raise ProviderError("fetch_games must run before fetching ACB standings")
        params: dict[str, Any] = {
            "competitionId": ACB_COMPETITION_ID,
            "editionId": self._edition_id,
        }
        if round_id is not None:
            params["roundId"] = round_id
        payload = self._get(ACB_STANDINGS_ENDPOINT, params)
        if not isinstance(payload, dict):
            raise ProviderError("ACB standings response is not an object")
        selected = payload.get("selectedFilters")
        available_rounds = payload.get("availableFilters", {}).get("rounds", [])
        selected_round = selected.get("round") if isinstance(selected, dict) else None
        round_number = None
        for item in available_rounds if isinstance(available_rounds, list) else []:
            if isinstance(item, dict) and item.get("id") == selected_round:
                try:
                    round_number = int(item["roundNumber"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ProviderError("ACB standings round metadata is invalid") from exc
                break
        try:
            snapshot = snapshot_from_api(
                payload,
                season=self._season,
                source_url=f"{ACB_API_BASE}{ACB_STANDINGS_ENDPOINT}?{urlencode(params)}",
                captured_at=datetime.now(MADRID_TZ),
                round_number=round_number,
            )
        except SnapshotError as exc:
            raise ProviderError(str(exc)) from exc
        return snapshot
