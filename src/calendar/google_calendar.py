from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

from src.calendar.formatting import title_for_game
from src.models import MADRID_TZ, TIMEZONE_NAME, Game
from src.normalize import deterministic_event_id, source_key

LOGGER = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _same_payload(existing: dict[str, Any], desired: dict[str, Any]) -> bool:
    fields = ("summary", "description", "location", "start", "end", "extendedProperties")
    return all(
        existing.get(field, "") == desired.get(field, "")
        if field == "location"
        else existing.get(field) == desired.get(field)
        for field in fields
    )


def _event_times(game: Game) -> tuple[dict[str, str], dict[str, str]] | None:
    if game.start_datetime is not None:
        start = game.start_datetime.astimezone(MADRID_TZ)
        end = start + timedelta(hours=2)
        return (
            {"dateTime": start.isoformat(timespec="seconds"), "timeZone": TIMEZONE_NAME},
            {"dateTime": end.isoformat(timespec="seconds"), "timeZone": TIMEZONE_NAME},
        )
    if game.start_date is not None:
        end_date = game.start_date + timedelta(days=1)
        return (
            {"date": game.start_date.isoformat()},
            {"date": end_date.isoformat()},
        )
    return None


def build_event_payload(
    game: Game,
    description: str,
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    times = _event_times(game)
    if times is None and existing is None:
        return None
    if times is None and existing is not None:
        # Keep the old slot while the official source says only “postponed”.
        times = (existing.get("start", {}), existing.get("end", {}))
    assert times is not None
    private = {
        "penya_source_key": source_key(game),
        "competition": game.competition,
        "season": game.season,
    }
    if game.source_game_id:
        private["source_game_id"] = game.source_game_id
    payload: dict[str, Any] = {
        "id": deterministic_event_id(game),
        "summary": title_for_game(game),
        "description": description,
        "start": times[0],
        "end": times[1],
        "location": game.venue or "",
        "extendedProperties": {"private": private},
    }
    return payload


class GoogleCalendarClient:
    def __init__(self, service: Any, calendar_id: str) -> None:
        self.service = service
        self.calendar_id = calendar_id

    @classmethod
    def from_service_account_json(
        cls, credentials_json: str, calendar_id: str
    ) -> GoogleCalendarClient:
        try:
            info = json.loads(credentials_json)
        except json.JSONDecodeError as exc:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
        credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        return cls(service, calendar_id)

    def find_events(self, game: Game) -> list[dict[str, Any]]:
        response = (
            self.service.events()
            .list(
                calendarId=self.calendar_id,
                privateExtendedProperty=f"penya_source_key={source_key(game)}",
                showDeleted=False,
                maxResults=20,
            )
            .execute()
        )
        if not isinstance(response, dict):
            raise RuntimeError("Google Calendar returned an invalid events response")
        items = response.get("items", [])
        if not isinstance(items, list):
            raise RuntimeError("Google Calendar returned invalid event items")
        return [item for item in items if isinstance(item, dict)]

    def plan_game(self, game: Game, description: str) -> str:
        existing_events = self.find_events(game)
        existing = existing_events[0] if existing_events else None
        payload = build_event_payload(game, description, existing=existing)
        if payload is None:
            return "SKIPPED"
        if existing is None:
            return "CREATE"
        return "UNCHANGED" if _same_payload(existing, payload) else "UPDATE"

    def upsert_game(self, game: Game, description: str) -> str:
        existing_events = self.find_events(game)
        if len(existing_events) > 1:
            LOGGER.warning(
                "Duplicate existing events found for source key; updating the first one",
                extra={"source_key": source_key(game), "count": len(existing_events)},
            )
        existing = existing_events[0] if existing_events else None
        payload = build_event_payload(game, description, existing=existing)
        if payload is None:
            LOGGER.warning(
                "Skipping game without an official date", extra={"source_key": source_key(game)}
            )
            return "SKIPPED"
        if existing is None:
            self.service.events().insert(calendarId=self.calendar_id, body=payload).execute()
            return "CREATE"
        if _same_payload(existing, payload):
            return "UNCHANGED"
        update_body = {key: value for key, value in payload.items() if key != "id"}
        self.service.events().update(
            calendarId=self.calendar_id,
            eventId=existing["id"],
            body=update_body,
        ).execute()
        return "UPDATE"
