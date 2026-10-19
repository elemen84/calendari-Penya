from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.calendar.formatting import description_for_game, title_for_game
from src.calendar.ics import render_ics, write_ics
from src.calendar.revisions import EventRevisionStore
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


def _event_block(feed: str, uid: str) -> str:
    unfolded = feed.replace("\r\n ", "").replace("\r\n", "\n")
    for block in unfolded.split("BEGIN:VEVENT")[1:]:
        if f"UID:{uid}" in block:
            return block.split("END:VEVENT")[0]
    raise AssertionError(f"UID not found: {uid}")


def _field(block: str, name: str) -> str:
    prefix = f"{name}:"
    for line in block.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix)
        if line.startswith(f"{name};"):
            return line
    raise AssertionError(f"{name} missing in event")


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
    # 21:00 Europe/Madrid in December (CET, UTC+1) → 20:00 UTC
    assert "DTSTART:20261214T200000Z" in second_ics
    assert "TZID=" not in second_ics


def test_ics_does_not_duplicate_a_source_game() -> None:
    game = make_game()
    duplicate = replace(game, start_datetime=datetime(2026, 12, 15, 20, tzinfo=MADRID))
    feed = render_ics(
        [game, duplicate],
        {source_key(game): "description"},
    )

    assert feed.count(f"UID:{source_key(game)}@penya-calendar") == 1


def test_ics_first_generation_uses_utc_and_initial_revision_metadata(tmp_path: Path) -> None:
    game = make_game(hour=20)
    key = source_key(game)
    uid = f"{key}@penya-calendar"
    store = EventRevisionStore(tmp_path / "ics-revisions.json")
    now = datetime(2026, 10, 19, 10, 0, tzinfo=MADRID)

    feed = render_ics(
        [game],
        {key: "🏆 Liga Endesa"},
        revision_store=store,
        now=now,
    )
    block = _event_block(feed, uid)

    assert _field(block, "UID") == uid
    assert _field(block, "SEQUENCE") == "0"
    assert _field(block, "DTSTAMP") == "20261019T080000Z"
    assert _field(block, "LAST-MODIFIED") == "20261019T080000Z"
    assert _field(block, "DTSTART") == "20261214T190000Z"
    assert _field(block, "DTEND") == "20261214T210000Z"
    assert "TZID=" not in feed


def test_ics_unchanged_sync_keeps_sequence_and_timestamps_stable(tmp_path: Path) -> None:
    game = make_game()
    key = source_key(game)
    uid = f"{key}@penya-calendar"
    store = EventRevisionStore(tmp_path / "ics-revisions.json")
    first_now = datetime(2026, 10, 19, 10, 0, tzinfo=MADRID)
    second_now = datetime(2026, 10, 20, 11, 0, tzinfo=MADRID)
    descriptions = {key: "🏆 Liga Endesa"}

    first = render_ics([game], descriptions, revision_store=store, now=first_now)
    store.save()
    store.load()
    second = render_ics([game], descriptions, revision_store=store, now=second_now)

    first_block = _event_block(first, uid)
    second_block = _event_block(second, uid)
    assert _field(second_block, "SEQUENCE") == "0"
    assert _field(second_block, "DTSTAMP") == _field(first_block, "DTSTAMP")
    assert _field(second_block, "LAST-MODIFIED") == _field(first_block, "LAST-MODIFIED")
    assert _field(second_block, "DTSTART") == _field(first_block, "DTSTART")


def test_ics_date_change_increments_sequence(tmp_path: Path) -> None:
    first_game = make_game(hour=20)
    second_game = make_game(hour=21)
    key = source_key(first_game)
    uid = f"{key}@penya-calendar"
    store = EventRevisionStore(tmp_path / "ics-revisions.json")
    descriptions = {key: "🏆 Liga Endesa"}

    render_ics(
        [first_game],
        descriptions,
        revision_store=store,
        now=datetime(2026, 10, 19, 10, 0, tzinfo=MADRID),
    )
    second = render_ics(
        [second_game],
        descriptions,
        revision_store=store,
        now=datetime(2026, 10, 20, 10, 0, tzinfo=MADRID),
    )
    block = _event_block(second, uid)

    assert _field(block, "SEQUENCE") == "1"
    assert _field(block, "DTSTART") == "20261214T200000Z"
    assert _field(block, "DTSTAMP") == "20261020T080000Z"
    assert _field(block, "LAST-MODIFIED") == "20261020T080000Z"


def test_ics_description_change_increments_sequence(tmp_path: Path) -> None:
    game = make_game()
    key = source_key(game)
    uid = f"{key}@penya-calendar"
    store = EventRevisionStore(tmp_path / "ics-revisions.json")

    render_ics(
        [game],
        {key: "Classificació encara no disponible"},
        revision_store=store,
        now=datetime(2026, 10, 19, 10, 0, tzinfo=MADRID),
    )
    second = render_ics(
        [game],
        {key: "1. Barça\n   1 PJ · 1 G · 0 P"},
        revision_store=store,
        now=datetime(2026, 10, 20, 10, 0, tzinfo=MADRID),
    )

    assert _field(_event_block(second, uid), "SEQUENCE") == "1"


def test_ics_preserves_madrid_wall_clock_across_dst(tmp_path: Path) -> None:
    winter = replace(
        make_game(),
        start_datetime=datetime(2026, 1, 15, 20, 30, tzinfo=MADRID),
    )
    summer = replace(
        make_game(),
        start_datetime=datetime(2026, 7, 15, 20, 30, tzinfo=MADRID),
        source_game_id="105379",
    )
    store = EventRevisionStore(tmp_path / "ics-revisions.json")
    feed = render_ics(
        [winter, summer],
        {
            source_key(winter): "winter",
            source_key(summer): "summer",
        },
        revision_store=store,
        now=datetime(2026, 10, 19, 12, 0, tzinfo=UTC),
    )

    winter_block = _event_block(feed, f"{source_key(winter)}@penya-calendar")
    summer_block = _event_block(feed, f"{source_key(summer)}@penya-calendar")
    # CET (UTC+1) in January, CEST (UTC+2) in July — same Madrid tip-off.
    assert _field(winter_block, "DTSTART") == "20260115T193000Z"
    assert _field(winter_block, "DTEND") == "20260115T213000Z"
    assert _field(summer_block, "DTSTART") == "20260715T183000Z"
    assert _field(summer_block, "DTEND") == "20260715T203000Z"


def test_ics_sequence_persists_between_process_runs(tmp_path: Path) -> None:
    game = make_game(hour=20)
    key = source_key(game)
    uid = f"{key}@penya-calendar"
    path = tmp_path / "ics-revisions.json"
    descriptions = {key: "🏆 Liga Endesa"}

    first_store = EventRevisionStore(path)
    write_ics(
        tmp_path / "a.ics",
        [game],
        descriptions,
        revision_store=first_store,
        now=datetime(2026, 10, 19, 10, 0, tzinfo=MADRID),
    )

    second_store = EventRevisionStore(path)
    second_store.load()
    changed = make_game(hour=21)
    write_ics(
        tmp_path / "b.ics",
        [changed],
        descriptions,
        revision_store=second_store,
        now=datetime(2026, 10, 20, 10, 0, tzinfo=MADRID),
    )

    third_store = EventRevisionStore(path)
    third_store.load()
    third = render_ics(
        [changed],
        descriptions,
        revision_store=third_store,
        now=datetime(2026, 10, 21, 10, 0, tzinfo=MADRID),
    )

    assert path.exists()
    changed_feed = (tmp_path / "b.ics").read_text(encoding="utf-8")
    assert _field(_event_block(changed_feed, uid), "SEQUENCE") == "1"
    assert _field(_event_block(third, uid), "SEQUENCE") == "1"


def test_ics_rfc5545_timed_event_shape(tmp_path: Path) -> None:
    game = make_game()
    key = source_key(game)
    store = EventRevisionStore(tmp_path / "ics-revisions.json")
    feed = render_ics(
        [game],
        {key: "line one\nline two"},
        revision_store=store,
        now=datetime(2026, 10, 19, 10, 0, tzinfo=MADRID),
    )

    assert feed.endswith("\r\n")
    assert "\r\n" in feed
    assert "BEGIN:VCALENDAR\r\n" in feed
    assert "VERSION:2.0\r\n" in feed
    assert "METHOD:PUBLISH\r\n" in feed
    block = _event_block(feed, f"{key}@penya-calendar")
    assert _field(block, "DTSTART").endswith("Z")
    assert _field(block, "DTEND").endswith("Z")
    assert _field(block, "DTSTAMP").endswith("Z")
    assert _field(block, "LAST-MODIFIED").endswith("Z")
    assert _field(block, "SEQUENCE").isdigit()
    assert "DTSTART;TZID=" not in feed
    assert "DTEND;TZID=" not in feed
    assert "\\n" in feed


def test_legacy_sequence_zero_store_bumps_once_for_google_subscribers(
    tmp_path: Path,
) -> None:
    """Simulate the SEQUENCE:0 publish that Google may still hold for these UIDs."""

    import json

    game = make_game(hour=20)
    key = source_key(game)
    uid = f"{key}@penya-calendar"
    path = tmp_path / "ics-revisions.json"
    descriptions = {key: "🏆 Liga Endesa\nClassificació encara no disponible"}

    # First write creates a current-schema store. Downgrade it to schema 1 / SEQUENCE 0
    # to mirror production right after the first Google-compat deploy.
    bootstrap = EventRevisionStore(path)
    write_ics(
        tmp_path / "bootstrap.ics",
        [game],
        descriptions,
        revision_store=bootstrap,
        now=datetime(2026, 10, 19, 10, 0, tzinfo=MADRID),
    )
    legacy = json.loads(path.read_text(encoding="utf-8"))
    legacy.pop("schema_version", None)
    for entry in legacy["events"].values():
        entry["sequence"] = 0
        entry["last_modified"] = "2026-10-19T08:00:00+00:00"
    path.write_text(json.dumps(legacy, indent=2) + "\n", encoding="utf-8")

    store = EventRevisionStore(path)
    store.load()
    assert store.schema_version == 1

    bumped = render_ics(
        [game],
        descriptions,
        revision_store=store,
        now=datetime(2026, 10, 19, 12, 0, tzinfo=MADRID),
    )
    store.save()
    block = _event_block(bumped, uid)
    assert _field(block, "UID") == uid
    assert _field(block, "SEQUENCE") == "1"
    assert _field(block, "DTSTAMP") == "20261019T100000Z"
    assert _field(block, "LAST-MODIFIED") == "20261019T100000Z"
    assert _field(block, "DTSTART") == "20261214T190000Z"

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2
    assert saved["events"][uid]["sequence"] == 1

    # Later sync with identical content must not bump again.
    store2 = EventRevisionStore(path)
    store2.load()
    stable = render_ics(
        [game],
        descriptions,
        revision_store=store2,
        now=datetime(2026, 10, 20, 9, 0, tzinfo=MADRID),
    )
    stable_block = _event_block(stable, uid)
    assert _field(stable_block, "SEQUENCE") == "1"
    assert _field(stable_block, "DTSTAMP") == "20261019T100000Z"
    assert _field(stable_block, "LAST-MODIFIED") == "20261019T100000Z"

    # A real description/date change after the compat bump must go 1 → 2.
    store3 = EventRevisionStore(path)
    store3.load()
    updated = render_ics(
        [make_game(hour=21)],
        {key: "🏆 Liga Endesa\n1. Barça\n   1 PJ · 1 G · 0 P"},
        revision_store=store3,
        now=datetime(2026, 10, 21, 9, 0, tzinfo=MADRID),
    )
    updated_block = _event_block(updated, uid)
    assert _field(updated_block, "UID") == uid
    assert _field(updated_block, "SEQUENCE") == "2"
    assert _field(updated_block, "DTSTART") == "20261214T200000Z"
    assert "1. Barça" in updated_block


def test_acb_event_content_uses_catalan_labels_and_keeps_official_values() -> None:
    game = make_game()
    standings = StandingsSnapshot(
        season="2026-27",
        round_number=12,
        captured_at=datetime(2026, 12, 14, 6, 15, tzinfo=MADRID),
        source_url="https://api2.acb.com/api/seasondata/Competition/standings",
        rows=(
            StandingRow(1, "Real Madrid", 11, 10, 1, 900, 850, 50),
            StandingRow(2, "Valencia Basket", 11, 9, 2, 880, 860, 20),
            StandingRow(3, "Asisa Joventut", 11, 8, 3, 870, 865, 5),
        ),
    )

    description = description_for_game(game, standings)
    content = "\n".join((title_for_game(game), description))

    assert "🏆 Liga Endesa" in content
    assert "1. Real Madrid" in description
    assert "   11 PJ · 10 G · 1 P · PF 900 · PC 850 · +50" in description
    assert "2. Valencia Basket" in description
    assert "3. Joventut Badalona" in description
    assert "   11 PJ · 8 G · 3 P · PF 870 · PC 865 · +5" in description
    assert "#  Equip" not in description
    assert "\u2007" not in description
    assert "Real Madrid — 10-1" not in description
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


def test_acb_standings_vertical_survives_ics_escaping_and_folding() -> None:
    game = make_game()
    standings = StandingsSnapshot(
        season="2026-27",
        round_number=12,
        captured_at=datetime(2026, 12, 14, 6, 15, tzinfo=MADRID),
        source_url="https://api2.acb.com/api/seasondata/Competition/standings",
        rows=(
            StandingRow(1, "Real Madrid", 11, 10, 1, 900, 850, 50),
            StandingRow(2, "Asisa Joventut", 11, 8, 3, 870, 865, 5),
        ),
    )
    description = description_for_game(game, standings)
    feed = render_ics([game], {source_key(game): description})

    assert "DESCRIPTION:" in feed
    assert "X-ALT-DESC" not in feed
    assert "\\n" in feed
    assert "\r\n" in feed
    unfolded = feed.replace("\r\n ", "").replace("\r\n", "\n")
    assert "1. Real Madrid" in unfolded
    assert "Joventut Badalona" in unfolded
    assert "PF 900" in unfolded
    assert "PC 850" in unfolded
    assert "+50" in unfolded
    assert "#  Equip" not in unfolded
    assert "\u2007" not in unfolded


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
