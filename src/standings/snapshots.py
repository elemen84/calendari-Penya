from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.normalize import standings_display_name


@dataclass(frozen=True, slots=True)
class StandingRow:
    position: int
    team: str
    matches_played: int
    wins: int
    losses: int


@dataclass(frozen=True, slots=True)
class StandingsSnapshot:
    season: str
    round_number: int | None
    captured_at: datetime
    source_url: str
    rows: tuple[StandingRow, ...]


class SnapshotError(RuntimeError):
    pass


def snapshot_from_api(
    payload: dict[str, Any],
    *,
    season: str,
    source_url: str,
    captured_at: datetime,
    round_number: int | None,
) -> StandingsSnapshot | None:
    standings = payload.get("standings")
    teams = payload.get("teams")
    if not isinstance(standings, list) or not isinstance(teams, list):
        raise SnapshotError("ACB standings response has an invalid shape")
    if not standings:
        return None
    team_names = {
        int(team["id"]): str(team["fullName"])
        for team in teams
        if isinstance(team, dict) and "id" in team and "fullName" in team
    }
    rows: list[StandingRow] = []
    for item in standings:
        if not isinstance(item, dict):
            raise SnapshotError("ACB standings contains a non-object row")
        try:
            team_id = int(item["teamId"])
            rows.append(
                StandingRow(
                    position=int(item["position"]),
                    team=team_names[team_id],
                    matches_played=int(item["matchesPlayed"]),
                    wins=int(item["wins"]),
                    losses=int(item["loses"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotError("ACB standings row is incomplete") from exc
    rows.sort(key=lambda row: row.position)
    return StandingsSnapshot(season, round_number, captured_at, source_url, tuple(rows))


class StandingsSnapshotStore:
    def __init__(self, root: Path = Path("data/standings")) -> None:
        self.root = root

    def path_for(self, season: str, round_number: int) -> Path:
        return self.root / season / f"round-{round_number:02d}.json"

    def load(self, season: str, round_number: int) -> StandingsSnapshot | None:
        path = self.path_for(season, round_number)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = tuple(StandingRow(**row) for row in payload["rows"])
            return StandingsSnapshot(
                season=str(payload["season"]),
                round_number=payload.get("round_number"),
                captured_at=datetime.fromisoformat(payload["captured_at"]),
                source_url=str(payload["source_url"]),
                rows=rows,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SnapshotError(f"Invalid standings snapshot: {path}") from exc

    def save_if_absent(self, snapshot: StandingsSnapshot) -> Path | None:
        if snapshot.round_number is None:
            return None
        path = self.path_for(snapshot.season, snapshot.round_number)
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "season": snapshot.season,
            "round_number": snapshot.round_number,
            "captured_at": snapshot.captured_at.isoformat(),
            "source_url": snapshot.source_url,
            "rows": [asdict(row) for row in snapshot.rows],
        }
        fd, temporary_name = tempfile.mkstemp(prefix=".round-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temporary:
                json.dump(document, temporary, ensure_ascii=False, indent=2, sort_keys=True)
                temporary.write("\n")
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return path


TEAM_COLUMN_WIDTH = 22
# FIGURE SPACE (U+2007): digit-width; resists collapse better than U+0020 in many UIs.
FIGURE_SPACE = "\u2007"


def _fit_team_name(name: str, width: int = TEAM_COLUMN_WIDTH) -> str:
    if len(name) <= width:
        return name
    return name[:width].rstrip()


def _pad_left(text: str, width: int, *, pad: str) -> str:
    gap = width - len(text)
    return (pad * gap + text) if gap > 0 else text


def _pad_right(text: str, width: int, *, pad: str) -> str:
    gap = width - len(text)
    return (text + pad * gap) if gap > 0 else text


def format_rows(snapshot: StandingsSnapshot | None, *, pad: str = FIGURE_SPACE) -> str:
    """Render ACB standings as a compact fixed-width plaintext table for ICS DESCRIPTION.

    Default pad is FIGURE SPACE for DESCRIPTION (proportional UIs). Pass pad=' ' for
    HTML <pre> monospace alternative.
    """

    if snapshot is None or not snapshot.rows:
        return "Classificació encara no disponible"

    header = (
        f"{_pad_left('#', 2, pad=pad)}{pad * 2}"
        f"{_pad_right('Equip', TEAM_COLUMN_WIDTH, pad=pad)}{pad}"
        f"{_pad_left('PJ', 2, pad=pad)}{pad}"
        f"{_pad_left('G', 2, pad=pad)}{pad}"
        f"{_pad_left('P', 2, pad=pad)}"
    )
    lines = [header]
    for row in snapshot.rows:
        team = _fit_team_name(standings_display_name(row.team))
        lines.append(
            f"{_pad_left(str(row.position), 2, pad=pad)}{pad * 2}"
            f"{_pad_right(team, TEAM_COLUMN_WIDTH, pad=pad)}{pad}"
            f"{_pad_left(str(row.matches_played), 2, pad=pad)}{pad}"
            f"{_pad_left(str(row.wins), 2, pad=pad)}{pad}"
            f"{_pad_left(str(row.losses), 2, pad=pad)}"
        )
    return "\n".join(lines)
