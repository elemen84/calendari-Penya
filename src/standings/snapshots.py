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
    # Official ACB fields when present (optional for older snapshots).
    points_for: int | None = None
    points_against: int | None = None
    point_difference: int | None = None


@dataclass(frozen=True, slots=True)
class StandingsSnapshot:
    season: str
    round_number: int | None
    captured_at: datetime
    source_url: str
    rows: tuple[StandingRow, ...]


class SnapshotError(RuntimeError):
    pass


def _optional_int(item: dict[str, Any], key: str) -> int | None:
    if key not in item or item[key] is None:
        return None
    return int(item[key])


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
            points_for = _optional_int(item, "pointsFor")
            points_against = _optional_int(item, "pointsAgainst")
            # Official differential from ACB when present.
            point_difference = _optional_int(item, "plusMinus")
            if (
                point_difference is None
                and points_for is not None
                and points_against is not None
            ):
                point_difference = points_for - points_against
            rows.append(
                StandingRow(
                    position=int(item["position"]),
                    team=team_names[team_id],
                    matches_played=int(item["matchesPlayed"]),
                    wins=int(item["wins"]),
                    losses=int(item["loses"]),
                    points_for=points_for,
                    points_against=points_against,
                    point_difference=point_difference,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotError("ACB standings row is incomplete") from exc
    rows.sort(key=lambda row: row.position)
    return StandingsSnapshot(season, round_number, captured_at, source_url, tuple(rows))


def _row_from_payload(row: dict[str, Any]) -> StandingRow:
    """Load a StandingRow; unknown/missing optional score fields stay None."""

    return StandingRow(
        position=int(row["position"]),
        team=str(row["team"]),
        matches_played=int(row["matches_played"]),
        wins=int(row["wins"]),
        losses=int(row["losses"]),
        points_for=_optional_int(row, "points_for"),
        points_against=_optional_int(row, "points_against"),
        point_difference=_optional_int(row, "point_difference"),
    )


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
            rows = tuple(_row_from_payload(row) for row in payload["rows"])
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


def _stats_line(row: StandingRow) -> str:
    parts = [
        f"{row.matches_played} PJ",
        f"{row.wins} G",
        f"{row.losses} P",
    ]
    if row.points_for is not None and row.points_against is not None:
        parts.append(f"PF {row.points_for}")
        parts.append(f"PC {row.points_against}")
        difference = row.point_difference
        if difference is None:
            difference = row.points_for - row.points_against
        parts.append(f"{difference:+d}")
    elif row.point_difference is not None:
        parts.append(f"Dif {row.point_difference:+d}")
    return "   " + " · ".join(parts)


def format_rows(snapshot: StandingsSnapshot | None) -> str:
    """Render ACB standings as a compact vertical plaintext block for ICS DESCRIPTION."""

    if snapshot is None or not snapshot.rows:
        return "Classificació encara no disponible"

    blocks: list[str] = []
    for row in snapshot.rows:
        team = standings_display_name(row.team)
        blocks.append(f"{row.position}. {team}\n{_stats_line(row)}")
    return "\n\n".join(blocks)
