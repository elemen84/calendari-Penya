from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

TIMEZONE_NAME = "Europe/Madrid"
MADRID_TZ = ZoneInfo(TIMEZONE_NAME)

VALID_STATUSES = frozenset({"scheduled", "finished", "postponed", "cancelled"})


@dataclass(frozen=True, slots=True)
class Game:
    """Source-independent representation of one official men's first-team game."""

    competition: str
    season: str
    round: int | None
    phase: str | None
    home_team: str
    away_team: str
    start_datetime: datetime | None
    timezone: str
    venue: str | None
    status: str
    source_url: str
    source_game_id: str | None
    start_date: date | None = None
    group: str | None = None

    def __post_init__(self) -> None:
        if self.timezone != TIMEZONE_NAME:
            raise ValueError(f"All games must use {TIMEZONE_NAME}")
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Unsupported normalized status: {self.status}")
        if not self.home_team.strip() or not self.away_team.strip():
            raise ValueError("A game must have both teams")
        if not self.source_url.startswith("https://"):
            raise ValueError("source_url must be an HTTPS official URL")
        if self.start_datetime is not None:
            if self.start_datetime.tzinfo is None:
                raise ValueError("start_datetime must be timezone-aware")
            if self.start_datetime.astimezone(MADRID_TZ).tzinfo is None:
                raise ValueError("start_datetime must be convertible to Europe/Madrid")
        if self.start_date is None and self.start_datetime is not None:
            object.__setattr__(self, "start_date", self.start_datetime.astimezone(MADRID_TZ).date())

