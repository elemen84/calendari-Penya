from __future__ import annotations

from datetime import datetime

from src.models import Game
from src.normalize import display_team_name, source_key
from src.standings.snapshots import FIGURE_SPACE, StandingsSnapshot, format_rows


def title_for_game(game: Game) -> str:
    prefix = {
        "postponed": "⚠️ AJORNAT · ",
        "cancelled": "❌ CANCEL·LAT · ",
        "finished": "✅ FINALITZAT · ",
    }.get(game.status, "")
    matchup = f"{display_team_name(game.home_team)} – {display_team_name(game.away_team)}"
    if game.competition == "Liga Endesa":
        round_label = f" J{game.round}" if game.round is not None else ""
        return f"{prefix}🏀 {matchup} · Liga Endesa{round_label}"
    parts = [f"🏀 {matchup}", "BCL"]
    if game.phase:
        parts.append(game.phase)
    if game.round is not None:
        parts.append(f"J{game.round}")
    return prefix + " · ".join(parts)


def _acb_meta(
    game: Game,
    standings: StandingsSnapshot | None,
    *,
    updated_at: datetime | None,
) -> tuple[list[str], list[str]]:
    header = ["🏆 Liga Endesa", f"Jornada {game.round or 'pendent'}"]
    if game.venue:
        header.extend(["", f"📍 {game.venue}"])
    header.extend(["", "📊 CLASSIFICACIÓ"])
    footer = ["Font: ACB"]
    timestamp: datetime | None
    if standings is not None:
        timestamp = standings.captured_at
    else:
        timestamp = updated_at
    if timestamp is not None:
        footer.append(f"Actualitzat: {timestamp.strftime('%d/%m/%Y %H:%M')}")
    footer.append(f"Font oficial: {game.source_url}")
    return header, footer


def description_for_game(
    game: Game,
    standings: StandingsSnapshot | None = None,
    *,
    updated_at: datetime | None = None,
) -> str:
    if game.competition == "Liga Endesa":
        header, footer = _acb_meta(game, standings, updated_at=updated_at)
        # FIGURE SPACE keeps column gaps from collapsing in many proportional UIs.
        body = [format_rows(standings, pad=FIGURE_SPACE), ""]
        return "\n".join([*header, *body, *footer])

    lines: list[str] = ["🏆 Basketball Champions League"]
    if game.phase:
        lines.append(f"Fase: {game.phase}")
    if game.round is not None:
        lines.append(f"Jornada: {game.round}")
    if game.group:
        lines.append(f"Grup: {game.group}")
    if game.venue:
        lines.extend(["", f"📍 {game.venue}"])
    lines.extend(["", f"Font oficial: {game.source_url}"])
    return "\n".join(lines)


def _html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def html_description_for_game(
    game: Game,
    standings: StandingsSnapshot | None = None,
    *,
    updated_at: datetime | None = None,
) -> str:
    """X-ALT-DESC HTML alternative with monospace <pre> standings table.

    Google Calendar ignores X-ALT-DESC; Apple does not use it reliably.
    Emitted for Outlook-class clients that prefer HTML while DESCRIPTION stays plain.
    """
    if game.competition != "Liga Endesa":
        plain = description_for_game(game, updated_at=updated_at)
        body = "<br>".join(_html_escape(line) for line in plain.splitlines())
        return f"<!DOCTYPE html><html><body><div>{body}</div></body></html>"

    header, footer = _acb_meta(game, standings, updated_at=updated_at)
    # ASCII inside <pre>: monospace font aligns; avoid FIGURE SPACE here.
    table = format_rows(standings, pad=" ")
    parts = [
        "<!DOCTYPE html><html><body>",
        "<div>",
        "<br>".join(_html_escape(line) for line in header),
        "</div>",
        '<pre style="font-family:ui-monospace,Menlo,Consolas,monospace;'
        'white-space:pre;margin:0.75em 0;">',
        _html_escape(table),
        "</pre>",
        "<div>",
        "<br>".join(_html_escape(line) for line in footer),
        "</div>",
        "</body></html>",
    ]
    return "".join(parts)


def description_map(
    games: tuple[Game, ...] | list[Game],
    standings_by_key: dict[str, StandingsSnapshot | None],
    *,
    updated_at: datetime,
) -> dict[str, str]:
    return {
        source_key(game): description_for_game(
            game,
            standings_by_key.get(source_key(game)),
            updated_at=updated_at,
        )
        for game in games
    }
