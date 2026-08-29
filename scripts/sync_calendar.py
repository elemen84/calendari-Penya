#!/usr/bin/env python3
# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calendar.google_calendar import GoogleCalendarClient
from src.http_client import OfficialHttpClient
from src.providers.acb import ACB_PUBLIC_API_KEY, ACBProvider, ProviderError
from src.providers.bcl import BCL_PUBLIC_SUBSCRIPTION_KEY, BCLProvider, BCLProviderError
from src.standings.snapshots import SnapshotError, StandingsSnapshotStore
from src.sync import execute_sync, prepare_sync

LOGGER = logging.getLogger("penya-calendar")
TZ = ZoneInfo("Europe/Madrid")
STATE_PATH = ROOT / "data/sync-state.json"
ICS_PATH = ROOT / "public/penya.ics"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronize Penya games to Google Calendar")
    parser.add_argument("--dry-run", action="store_true", help="Read sources and plan changes only")
    parser.add_argument("--force", action="store_true", help="Ignore the 48-hour sync gate")
    return parser.parse_args()


def load_state() -> dict[str, object]:
    if not STATE_PATH.exists():
        return {"last_successful_sync": None}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid sync state: {STATE_PATH}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Invalid sync state: {STATE_PATH}")
    return value


def should_sync(state: dict[str, object], now: datetime, force: bool) -> tuple[bool, str | None]:
    if force:
        return True, None
    last = state.get("last_successful_sync")
    if not last:
        return True, None
    try:
        parsed = datetime.fromisoformat(str(last))
    except ValueError as exc:
        raise RuntimeError("last_successful_sync is not a valid ISO datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    elapsed = now - parsed.astimezone(TZ)
    if elapsed < timedelta(hours=48):
        next_at = parsed.astimezone(TZ) + timedelta(hours=48)
        return False, next_at.strftime("%d/%m/%Y %H:%M %Z")
    return True, None


def save_state(state: dict[str, object]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def configured_google_client(*, dry_run: bool) -> GoogleCalendarClient | None:
    credentials = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")
    if not credentials or not calendar_id:
        if dry_run:
            LOGGER.info(
                "Google credentials not configured; dry-run will report source results only"
            )
            return None
        raise RuntimeError(
            "Set GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_CALENDAR_ID before a real sync"
        )
    return GoogleCalendarClient.from_service_account_json(credentials, calendar_id)


def print_report(stats, *, dry_run: bool, google_configured: bool) -> None:
    print("\nPENYA CALENDAR SYNC\n")
    print("ACB")
    print(f"Games found: {stats.acb_games}")
    print(f"Upcoming: {stats.acb_upcoming}")
    print(f"Finished: {stats.acb_finished}\n")
    print("BCL")
    print(f"Games found: {stats.bcl_games}\n")
    print("Standings:")
    print(f"ACB current standings: {'OK' if stats.standings_available else 'NOT AVAILABLE'}")
    print(f"Current round: {stats.current_round if stats.current_round is not None else 'N/A'}")
    frozen = ", ".join(str(item) for item in stats.snapshots_frozen) or "none"
    print(f"Snapshot rounds frozen: {frozen}\n")
    print("Google Calendar:")
    if google_configured:
        for action in ("CREATE", "UPDATE", "UNCHANGED", "SKIPPED"):
            print(f"{action}: {stats.actions.get(action, 0)}")
        print("DELETE: 0")
    else:
        print("CREATE: N/A (Google credentials not configured)")
        print("UPDATE: N/A (Google credentials not configured)")
        print("UNCHANGED: N/A (Google credentials not configured)")
        print("DELETE: 0")
    print(f"\nMode: {'DRY-RUN' if dry_run else 'SYNC'}")
    print("Result: PASS")


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(TZ)
    try:
        state = load_state()
        allowed, next_at = should_sync(state, now, args.force)
        if not allowed:
            print(f"PENYA CALENDAR SYNC\n\nNo sync needed; next eligible sync is after {next_at}.")
            return 0
        google_client = configured_google_client(dry_run=args.dry_run)
        http = OfficialHttpClient()
        season_value = os.environ.get("PENYA_SEASON_START_YEAR")
        season_start_year = int(season_value) if season_value else None
        acb_api_key = os.environ.get("ACB_API_KEY", "").strip() or ACB_PUBLIC_API_KEY
        bcl_subscription_key = (
            os.environ.get("BCL_APIM_SUBSCRIPTION_KEY", "").strip()
            or BCL_PUBLIC_SUBSCRIPTION_KEY
        )
        acb = ACBProvider(
            http,
            season_start_year=season_start_year,
            api_key=acb_api_key,
        )
        bcl = BCLProvider(
            http,
            subscription_key=bcl_subscription_key,
        )
        prepared = prepare_sync(
            acb,
            bcl,
            snapshot_store=StandingsSnapshotStore(ROOT / "data/standings"),
            now=now,
            dry_run=args.dry_run,
        )
        stats = execute_sync(
            prepared,
            google_calendar=google_client,
            ics_path=ICS_PATH,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            state["last_successful_sync"] = now.isoformat()
            save_state(state)
        print_report(
            stats,
            dry_run=args.dry_run,
            google_configured=google_client is not None,
        )
        return 0
    except (ProviderError, BCLProviderError, SnapshotError, RuntimeError, ValueError) as exc:
        LOGGER.error("Synchronization failed safely: %s", exc)
        print("\nPENYA CALENDAR SYNC\n\nResult: FAIL", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
