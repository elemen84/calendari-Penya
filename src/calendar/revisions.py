from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# schema 1: first SEQUENCE-aware publish used SEQUENCE 0 for every UID.
# Google treats a missing SEQUENCE as 0, so those updates were ignored.
# schema 2: one-time +1 bump so existing subscriptions see a higher SEQUENCE.
CURRENT_SCHEMA_VERSION = 2


class RevisionStoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EventRevision:
    sequence: int
    last_modified: datetime
    fingerprint: str


@dataclass(frozen=True, slots=True)
class ResolvedRevision:
    sequence: int
    dtstamp: datetime
    last_modified: datetime


def fingerprint_event(
    *,
    summary: str,
    description: str,
    status: str,
    location: str,
    dtstart: str,
    dtend: str,
) -> str:
    """Hash the ICS fields that must bump SEQUENCE when they change."""

    payload = "\n".join((summary, description, status, location, dtstart, dtend))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise RevisionStoreError("revision timestamps must be timezone-aware")
    return value.astimezone(UTC)


class EventRevisionStore:
    """Persist SEQUENCE / LAST-MODIFIED per UID across sync runs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: dict[str, EventRevision] = {}
        self._schema_version = CURRENT_SCHEMA_VERSION

    @property
    def schema_version(self) -> int:
        return self._schema_version

    def load(self) -> None:
        if not self.path.exists():
            self._entries = {}
            self._schema_version = CURRENT_SCHEMA_VERSION
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RevisionStoreError(f"Invalid ICS revision store: {self.path}") from exc
        if not isinstance(payload, dict):
            raise RevisionStoreError(f"Invalid ICS revision store: {self.path}")
        events = payload.get("events", payload)
        if not isinstance(events, dict):
            raise RevisionStoreError(f"Invalid ICS revision store: {self.path}")
        entries: dict[str, EventRevision] = {}
        for uid, item in events.items():
            if not isinstance(uid, str) or not isinstance(item, dict):
                raise RevisionStoreError(f"Invalid ICS revision entry: {uid}")
            try:
                last_modified = datetime.fromisoformat(str(item["last_modified"]))
                if last_modified.tzinfo is None:
                    last_modified = last_modified.replace(tzinfo=UTC)
                entries[uid] = EventRevision(
                    sequence=int(item["sequence"]),
                    last_modified=_as_utc(last_modified),
                    fingerprint=str(item["fingerprint"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RevisionStoreError(f"Invalid ICS revision entry: {uid}") from exc
        self._entries = entries
        # Missing schema_version means the SEQUENCE:0 publish that Google may ignore.
        if "schema_version" in payload:
            try:
                self._schema_version = int(payload["schema_version"])
            except (TypeError, ValueError) as exc:
                raise RevisionStoreError(
                    f"Invalid ICS revision schema_version: {self.path}"
                ) from exc
        else:
            self._schema_version = 1

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schema_version": self._schema_version,
            "events": {
                uid: {
                    "sequence": revision.sequence,
                    "last_modified": revision.last_modified.astimezone(UTC).isoformat(),
                    "fingerprint": revision.fingerprint,
                }
                for uid, revision in sorted(self._entries.items())
            },
        }
        fd, temporary_name = tempfile.mkstemp(
            prefix=".ics-revisions-",
            suffix=".json",
            dir=self.path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temporary:
                json.dump(document, temporary, ensure_ascii=False, indent=2, sort_keys=True)
                temporary.write("\n")
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def ensure_google_subscription_compat(self, *, now: datetime) -> bool:
        """Raise SEQUENCE once so legacy Google URL subscriptions accept updates.

        Pre-revision feeds omitted SEQUENCE (clients treat that as 0). Publishing
        SEQUENCE:0 with corrected DTSTART/SUMMARY/DESCRIPTION is not enough for
        Google to replace those stored events. A single +1 bump is required.
        """

        if self._schema_version >= CURRENT_SCHEMA_VERSION:
            return False
        now_utc = _as_utc(now)
        self._entries = {
            uid: EventRevision(
                sequence=revision.sequence + 1,
                last_modified=now_utc,
                fingerprint=revision.fingerprint,
            )
            for uid, revision in self._entries.items()
        }
        self._schema_version = CURRENT_SCHEMA_VERSION
        return True

    def resolve(self, uid: str, fingerprint: str, *, now: datetime) -> ResolvedRevision:
        now_utc = _as_utc(now)
        existing = self._entries.get(uid)
        if existing is None:
            revision = EventRevision(sequence=0, last_modified=now_utc, fingerprint=fingerprint)
            self._entries[uid] = revision
            return ResolvedRevision(0, now_utc, now_utc)
        if existing.fingerprint == fingerprint:
            return ResolvedRevision(
                existing.sequence,
                existing.last_modified,
                existing.last_modified,
            )
        sequence = existing.sequence + 1
        revision = EventRevision(sequence=sequence, last_modified=now_utc, fingerprint=fingerprint)
        self._entries[uid] = revision
        return ResolvedRevision(sequence, now_utc, now_utc)

    def retain_only(self, uids: set[str]) -> None:
        self._entries = {uid: revision for uid, revision in self._entries.items() if uid in uids}
