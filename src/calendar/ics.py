from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from src.calendar.formatting import title_for_game
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


def _datetime_value(value: datetime) -> str:
    return value.astimezone(MADRID_TZ).strftime("%Y%m%dT%H%M%S")


def render_ics(games: list[Game] | tuple[Game, ...], descriptions: dict[str, str]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Penya Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Penya - Joventut Badalona",
        f"X-WR-TIMEZONE:{TIMEZONE_NAME}",
    ]
    for game in sorted(
        games,
        key=lambda item: (item.start_date or datetime.max.date(), source_key(item)),
    ):
        if game.start_datetime is None and game.start_date is None:
            continue
        key = source_key(game)
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{key}@penya-calendar",
                "DTSTAMP:20000101T000000Z",
                f"SUMMARY:{_escape(title_for_game(game))}",
                f"DESCRIPTION:{_escape(descriptions.get(key, ''))}",
                "STATUS:"
                + (
                    "CANCELLED"
                    if game.status == "cancelled"
                    else "TENTATIVE"
                    if game.status == "postponed"
                    else "CONFIRMED"
                ),
            ]
        )
        if game.venue:
            lines.append(f"LOCATION:{_escape(game.venue)}")
        if game.start_datetime is not None:
            start = game.start_datetime.astimezone(MADRID_TZ)
            end = start + timedelta(hours=2)
            lines.append(f"DTSTART;TZID={TIMEZONE_NAME}:{_datetime_value(start)}")
            lines.append(f"DTEND;TZID={TIMEZONE_NAME}:{_datetime_value(end)}")
        else:
            assert game.start_date is not None
            lines.append(f"DTSTART;VALUE=DATE:{game.start_date.strftime('%Y%m%d')}")
            lines.append(
                f"DTEND;VALUE=DATE:{(game.start_date + timedelta(days=1)).strftime('%Y%m%d')}"
            )
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"


def write_ics(
    path: Path,
    games: list[Game] | tuple[Game, ...],
    descriptions: dict[str, str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_ics(games, descriptions), encoding="utf-8")
