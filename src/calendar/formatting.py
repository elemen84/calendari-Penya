from __future__ import annotations

from datetime import datetime

from src.models import Game
from src.normalize import display_team_name, source_key
from src.standings.snapshots import StandingsSnapshot, format_rows


def title_for_game(game: Game) -> str:
    prefix = {
        "postponed": "⚠️ APLAZADO · ",
        "cancelled": "❌ CANCELADO · ",
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


def description_for_game(
    game: Game,
    standings: StandingsSnapshot | None = None,
    *,
    updated_at: datetime | None = None,
) -> str:
    lines: list[str] = []
    if game.competition == "Liga Endesa":
        lines.extend(["🏆 Liga Endesa", f"Jornada {game.round or 'pendiente'}", ""])
        if game.venue:
            lines.extend([f"📍 {game.venue}", ""])
        lines.extend(["📊 CLASIFICACIÓN", format_rows(standings), ""])
        lines.append("Fuente: ACB")
        timestamp: datetime | None
        if standings is not None:
            timestamp = standings.captured_at
        else:
            timestamp = updated_at
        if timestamp is not None:
            lines.append(f"Actualizado: {timestamp.strftime('%d/%m/%Y %H:%M')}")
        lines.append(f"Fuente oficial: {game.source_url}")
        return "\n".join(lines)

    lines.extend(["🏆 Basketball Champions League"])
    if game.phase:
        lines.append(f"Fase: {game.phase}")
    if game.round is not None:
        lines.append(f"Jornada: {game.round}")
    if game.group:
        lines.append(f"Grupo: {game.group}")
    if game.venue:
        lines.extend(["", f"📍 {game.venue}"])
    lines.extend(["", f"Fuente oficial: {game.source_url}"])
    return "\n".join(lines)


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
