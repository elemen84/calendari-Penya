from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.http_client import OfficialHttpClient
from src.models import TIMEZONE_NAME, Game
from src.normalize import display_team_name, is_penya_team, season_label

LOGGER = logging.getLogger(__name__)

BCL_GAMES_URL = "https://www.championsleague.basketball/en/games"
BCL_API_BASE = "https://digital-api.fiba.basketball/hapi"
BCL_GAMES_ENDPOINT = "getgdapgamesbycompetitionid"
# This is the public browser key from the official BCL frontend configuration.
BCL_PUBLIC_SUBSCRIPTION_KEY = "898cd5e7389140028ecb42943c47eb74"
MADRID_TZ = ZoneInfo(TIMEZONE_NAME)


@dataclass(frozen=True, slots=True)
class BCLData:
    games: tuple[Game, ...]
    competition_id: int
    raw_game_count: int


class BCLProviderError(RuntimeError):
    pass


def _parse_utc(value: Any) -> tuple[datetime | None, Any]:
    if not isinstance(value, str) or not value or value.startswith("0001-"):
        return None, None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BCLProviderError(f"Invalid BCL date: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    local = parsed.astimezone(MADRID_TZ)
    return local, local.date()


def _normalize_status(game: dict[str, Any]) -> str:
    value = str(game.get("statusCode", "")).upper()
    if value in {"CANCELLED", "CANCELED"}:
        return "cancelled"
    if game.get("isPostponed") is True:
        return "postponed"
    if value in {"FINAL", "FINISHED", "VALID", "COMPLETED"}:
        return "finished"
    if value in {"POSTPONED", "SUSPENDED", "DELAYED"}:
        return "postponed"
    if value in {"INIT", "SCHEDULED", "NOT_STARTED", "STARTED", "LIVE", "RUNNING"}:
        return "scheduled"
    raise BCLProviderError(f"Unknown BCL game status: {game.get('statusCode')}")


def _event_id_from_html(html: str) -> int:
    match = re.search(r'data-event-id=["\'](\d+)["\']', html)
    if not match:
        raise BCLProviderError("BCL games page did not expose its official event id")
    return int(match.group(1))


class BCLProvider:
    def __init__(
        self,
        http: OfficialHttpClient | Any | None = None,
        *,
        subscription_key: str = BCL_PUBLIC_SUBSCRIPTION_KEY,
        competition_id: int | None = None,
    ) -> None:
        self.http = http or OfficialHttpClient()
        self.subscription_key = subscription_key
        self.competition_id_override = competition_id

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Ocp-Apim-Subscription-Key": self.subscription_key,
            "Accept": "application/json",
        }

    def fetch_games(self) -> BCLData:
        if self.competition_id_override is None:
            page = self.http.get_text(BCL_GAMES_URL, headers={"Accept": "text/html"})
            competition_id = _event_id_from_html(page)
        else:
            competition_id = self.competition_id_override
        payload = self.http.get_json(
            f"{BCL_API_BASE}/{BCL_GAMES_ENDPOINT}",
            headers=self.headers,
            params={"gdapCompetitionId": competition_id},
        )
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            payload = payload["data"]
        if not isinstance(payload, list):
            raise BCLProviderError("BCL games response is not a list")
        games: list[Game] = []
        for item in payload:
            if not isinstance(item, dict):
                raise BCLProviderError("BCL games response contains a non-object")
            competition = item.get("competition")
            team_a = item.get("teamA")
            team_b = item.get("teamB")
            if (
                not isinstance(competition, dict)
                or not isinstance(team_a, dict)
                or not isinstance(team_b, dict)
            ):
                # BCL publishes placeholder playoff games before participants are known.
                continue
            if str(competition.get("competitionCode", "")).upper() != "BCL":
                continue
            if str(competition.get("gender", "")).casefold() != "men":
                continue
            if str(competition.get("ageCategory", "")).casefold() != "senior":
                continue
            home = str(team_a.get("shortName") or team_a.get("officialName") or "").strip()
            away = str(team_b.get("shortName") or team_b.get("officialName") or "").strip()
            if not home or not away or not (is_penya_team(home) or is_penya_team(away)):
                continue
            try:
                source_id = str(int(item["gameId"]))
                round_data = item["round"]
                round_number = int(round_data["roundNumber"])
                phase = str(round_data.get("roundName") or "").strip() or None
                group = str(item.get("groupPairingCode") or "").strip() or None
                status = _normalize_status(item)
                competition_start = str(competition.get("start") or "")
                season_start_year = int(competition_start[:4])
                if season_start_year < 2000:
                    raise ValueError("invalid competition season")
            except (KeyError, TypeError, ValueError) as exc:
                raise BCLProviderError("BCL game is incomplete") from exc
            start_datetime, start_date = _parse_utc(item.get("gameDateTimeUTC"))
            games.append(
                Game(
                    competition="BCL",
                    season=season_label(season_start_year),
                    round=round_number,
                    phase=phase,
                    home_team=display_team_name(home),
                    away_team=display_team_name(away),
                    start_datetime=start_datetime,
                    timezone=TIMEZONE_NAME,
                    venue=str(item.get("venueName") or "").strip() or None,
                    status=status,
                    source_url=BCL_GAMES_URL,
                    source_game_id=source_id,
                    start_date=start_date,
                    group=group,
                )
            )
        if not payload:
            raise BCLProviderError(
                "BCL returned zero games; refusing to synchronize or remove existing events"
            )
        if not games:
            raise BCLProviderError(
                "BCL returned no men's Joventut games; refusing to synchronize or remove events"
            )
        return BCLData(
            tuple(sorted(games, key=lambda game: game.start_date or datetime.max.date())),
            competition_id,
            len(payload),
        )
