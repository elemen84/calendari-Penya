from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.calendar.formatting import description_for_game, html_description_for_game
from src.calendar.ics import write_ics
from src.models import Game
from src.normalize import source_key
from src.providers.acb import ACBData, ACBProvider
from src.providers.bcl import BCLData, BCLProvider
from src.standings.snapshots import StandingsSnapshot, StandingsSnapshotStore


@dataclass
class SyncStats:
    acb_games: int = 0
    bcl_games: int = 0
    acb_upcoming: int = 0
    acb_finished: int = 0
    snapshots_frozen: list[int] = field(default_factory=list)
    standings_available: bool = False
    current_round: int | None = None


@dataclass(frozen=True, slots=True)
class PreparedSync:
    games: tuple[Game, ...]
    descriptions: dict[str, str]
    html_descriptions: dict[str, str]
    acb: ACBData
    bcl: BCLData
    stats: SyncStats


def _is_future(game: Game, now: datetime) -> bool:
    if game.start_datetime is not None:
        return game.start_datetime > now
    return game.start_date is not None and game.start_date >= now.date()


def _round_is_complete(statuses: tuple[str, ...]) -> bool:
    return bool(statuses) and all(status in {"finished", "cancelled"} for status in statuses)


def prepare_sync(
    acb_provider: ACBProvider,
    bcl_provider: BCLProvider,
    *,
    snapshot_store: StandingsSnapshotStore,
    now: datetime,
    dry_run: bool = False,
) -> PreparedSync:
    # Fetch and validate every source before writing generated files.
    acb_data = acb_provider.fetch_games()
    bcl_data = bcl_provider.fetch_games()
    current_standings = acb_provider.fetch_standings()
    standings_by_key: dict[str, StandingsSnapshot | None] = {}
    round_cache: dict[int, StandingsSnapshot | None] = {}
    frozen: list[int] = []

    for game in acb_data.games:
        key = source_key(game)
        snapshot: StandingsSnapshot | None = None
        if game.round is not None:
            snapshot = snapshot_store.load(game.season, game.round)
            if snapshot is None and _round_is_complete(acb_data.round_statuses.get(game.round, ())):
                round_id = acb_data.round_ids.get(game.round)
                if round_id is not None:
                    if game.round not in round_cache:
                        round_cache[game.round] = acb_provider.fetch_standings(round_id=round_id)
                    snapshot = round_cache[game.round]
                    if snapshot is not None and not dry_run:
                        snapshot_store.save_if_absent(snapshot)
                    if snapshot is not None:
                        frozen.append(game.round)
            elif snapshot is None and current_standings is not None:
                # A future game or a round in progress gets the latest available context.
                snapshot = current_standings
        standings_by_key[key] = snapshot

    all_games = tuple(acb_data.games) + tuple(bcl_data.games)
    descriptions: dict[str, str] = {}
    html_descriptions: dict[str, str] = {}
    for game in all_games:
        key = source_key(game)
        snapshot = standings_by_key.get(key)
        descriptions[key] = description_for_game(game, snapshot, updated_at=now)
        html_descriptions[key] = html_description_for_game(game, snapshot, updated_at=now)
    stats = SyncStats(
        acb_games=len(acb_data.games),
        bcl_games=len(bcl_data.games),
        acb_upcoming=sum(1 for game in acb_data.games if _is_future(game, now)),
        acb_finished=sum(1 for game in acb_data.games if game.status == "finished"),
        snapshots_frozen=sorted(set(frozen)),
        standings_available=current_standings is not None,
        current_round=current_standings.round_number if current_standings else None,
    )
    return PreparedSync(all_games, descriptions, html_descriptions, acb_data, bcl_data, stats)


def execute_sync(
    prepared: PreparedSync,
    *,
    ics_path: Path,
) -> SyncStats:
    write_ics(
        ics_path,
        prepared.games,
        prepared.descriptions,
        html_descriptions=prepared.html_descriptions,
    )
    return prepared.stats
