from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.calendar.formatting import title_for_game
from src.calendar.revisions import EventRevisionStore, ResolvedRevision, fingerprint_event
from src.models import MADRID_TZ, TIMEZONE_NAME, Game
from src.normalize import source_key


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for character in line:
        candidate = current + character
        if len(candidate.encode("utf-8")) > 75 and current:
            chunks.append(current)
            current = " " + character
        else:
            current = candidate
    if current or not chunks:
        chunks.append(current)
    return chunks


def _utc_datetime_value(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _status_for_game(game: Game) -> str:
    if game.status == "cancelled":
        return "CANCELLED"
    if game.status == "postponed":
        return "TENTATIVE"
    return "CONFIRMED"


def _schedule_values(game: Game) -> tuple[str, str]:
    if game.start_datetime is not None:
        start = game.start_datetime.astimezone(MADRID_TZ)
        end = start + timedelta(hours=2)
        return _utc_datetime_value(start), _utc_datetime_value(end)
    assert game.start_date is not None
    start = game.start_date.strftime("%Y%m%d")
    end = (game.start_date + timedelta(days=1)).strftime("%Y%m%d")
    return start, end


def _default_revision(now: datetime) -> ResolvedRevision:
    now_utc = now.astimezone(UTC)
    return ResolvedRevision(sequence=0, dtstamp=now_utc, last_modified=now_utc)


def render_ics(
    games: list[Game] | tuple[Game, ...],
    descriptions: dict[str, str],
    *,
    revision_store: EventRevisionStore | None = None,
    now: datetime | None = None,
) -> str:
    generated_at = now or datetime.now(UTC)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    if revision_store is not None:
        # One-time SEQUENCE bump for Google URL subscriptions that still hold
        # the pre-revision (implicit SEQUENCE 0) copies of these UIDs.
        revision_store.ensure_google_subscription_compat(now=generated_at)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Penya Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Penya - Joventut Badalona",
        f"X-WR-TIMEZONE:{TIMEZONE_NAME}",
    ]
    unique_games: dict[str, Game] = {}
    for game in games:
        unique_games.setdefault(source_key(game), game)

    active_uids: set[str] = set()
    for game in sorted(
        unique_games.values(),
        key=lambda item: (item.start_date or datetime.max.date(), source_key(item)),
    ):
        if game.start_datetime is None and game.start_date is None:
            continue
        key = source_key(game)
        uid = f"{key}@penya-calendar"
        active_uids.add(uid)
        summary = title_for_game(game)
        description = descriptions.get(key, "")
        status = _status_for_game(game)
        location = game.venue or ""
        dtstart_value, dtend_value = _schedule_values(game)
        fingerprint = fingerprint_event(
            summary=summary,
            description=description,
            status=status,
            location=location,
            dtstart=dtstart_value,
            dtend=dtend_value,
        )
        if revision_store is None:
            revision = _default_revision(generated_at)
        else:
            revision = revision_store.resolve(uid, fingerprint, now=generated_at)

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{_utc_datetime_value(revision.dtstamp)}",
                f"LAST-MODIFIED:{_utc_datetime_value(revision.last_modified)}",
                f"SEQUENCE:{revision.sequence}",
                f"SUMMARY:{_escape(summary)}",
                f"DESCRIPTION:{_escape(description)}",
                f"STATUS:{status}",
            ]
        )
        if location:
            lines.append(f"LOCATION:{_escape(location)}")
        if game.start_datetime is not None:
            lines.append(f"DTSTART:{dtstart_value}")
            lines.append(f"DTEND:{dtend_value}")
        else:
            lines.append(f"DTSTART;VALUE=DATE:{dtstart_value}")
            lines.append(f"DTEND;VALUE=DATE:{dtend_value}")
        lines.append("END:VEVENT")

    if revision_store is not None:
        revision_store.retain_only(active_uids)

    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"


def write_ics(
    path: Path,
    games: list[Game] | tuple[Game, ...],
    descriptions: dict[str, str],
    *,
    revision_store: EventRevisionStore | None = None,
    now: datetime | None = None,
    persist_revisions: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_ics(games, descriptions, revision_store=revision_store, now=now),
        encoding="utf-8",
    )
    if revision_store is not None and persist_revisions:
        revision_store.save()
