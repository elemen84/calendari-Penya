from __future__ import annotations

import hashlib
import re
import unicodedata

from src.models import Game


def normalize_team_name(name: str) -> str:
    """Return a stable comparison form without accents, punctuation or case."""

    decomposed = unicodedata.normalize("NFKD", name)
    ascii_name = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_name.casefold()).strip()


PENYA_ALIASES = frozenset(
    normalize_team_name(alias)
    for alias in (
        "Joventut",
        "Joventut Badalona",
        "Club Joventut Badalona",
        "Club Joventut Badalona SAD",
        "ASISA Joventut",
        "Asisa Joventut",
        "Penya",
    )
)


def is_penya_team(name: str) -> bool:
    return normalize_team_name(name) in PENYA_ALIASES


def display_team_name(name: str) -> str:
    return "Penya" if is_penya_team(name) else name.strip()


def season_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def source_key(game: Game) -> str:
    """Build an identity independent of time, venue and mutable source fields."""

    competition = normalize_team_name(game.competition).replace(" ", "-")
    if game.source_game_id:
        return f"{competition}:{game.season}:{game.source_game_id}"
    round_part = str(game.round) if game.round is not None else "unknown-round"
    home = normalize_team_name(game.home_team).replace(" ", "-")
    away = normalize_team_name(game.away_team).replace(" ", "-")
    return f"{competition}:{game.season}:J{round_part}:{home}:{away}"


def deterministic_event_id(game: Game) -> str:
    return "penya" + hashlib.sha256(source_key(game).encode("utf-8")).hexdigest()[:32]

