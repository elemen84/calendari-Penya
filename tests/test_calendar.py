from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from src.calendar.formatting import title_for_game
from src.calendar.google_calendar import GoogleCalendarClient, build_event_payload
from src.calendar.ics import render_ics
from src.models import Game
from src.normalize import source_key

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


class Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeEvents:
    def __init__(self):
        self.items = []
        self.inserted = 0
        self.updated = 0

    def list(self, **kwargs):
        wanted = kwargs["privateExtendedProperty"].split("=", 1)[1]
        matching = [
            item
            for item in self.items
            if item.get("extendedProperties", {}).get("private", {}).get("penya_source_key")
            == wanted
        ]
        return Request({"items": matching})

    def insert(self, *, calendarId, body):
        self.items.append(dict(body))
        self.inserted += 1
        return Request(body)

    def update(self, *, calendarId, eventId, body):
        for item in self.items:
            if item["id"] == eventId:
                item.update(body)
                break
        else:
            raise AssertionError("update target not found")
        self.updated += 1
        return Request(body)


class FakeService:
    def __init__(self):
        self.resource = FakeEvents()

    def events(self):
        return self.resource


def test_google_calendar_create_update_and_no_duplicate() -> None:
    service = FakeService()
    client = GoogleCalendarClient(service, "calendar@example")
    game = make_game()

    assert client.upsert_game(game, "first") == "CREATE"
    moved = make_game(hour=21)
    assert client.upsert_game(moved, "moved") == "UPDATE"
    moved_date = replace(moved, start_datetime=datetime(2026, 12, 15, 21, tzinfo=MADRID))
    assert client.upsert_game(moved_date, "moved date") == "UPDATE"
    assert client.upsert_game(moved_date, "moved date") == "UNCHANGED"
    assert service.resource.inserted == 1
    assert service.resource.updated == 2
    assert len(service.resource.items) == 1


def test_postponed_game_is_marked_and_keeps_identity() -> None:
    game = make_game(status="postponed")
    assert "APLazADO" not in title_for_game(game)
    assert "APLAZADO" in title_for_game(game)
    assert source_key(game) == source_key(make_game(hour=22))


def test_postponed_without_new_date_preserves_existing_slot() -> None:
    original = make_game()
    existing = build_event_payload(original, "old description")
    postponed = replace(original, start_datetime=None, start_date=None, status="postponed")
    updated = build_event_payload(postponed, "postponed description", existing=existing)

    assert updated is not None
    assert updated["start"] == existing["start"]
    assert updated["end"] == existing["end"]
    assert "APLAZADO" in updated["summary"]


def test_ics_uid_is_stable_when_time_changes() -> None:
    first = make_game(hour=20)
    second = make_game(hour=21)
    first_ics = render_ics([first], {source_key(first): "description"})
    second_ics = render_ics([second], {source_key(second): "description"})
    uid_line = next(line for line in first_ics.splitlines() if line.startswith("UID:"))
    assert uid_line == next(line for line in second_ics.splitlines() if line.startswith("UID:"))
    assert "DTSTART;TZID=Europe/Madrid:20261214T210000" in second_ics
