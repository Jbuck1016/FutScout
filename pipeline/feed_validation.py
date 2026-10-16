"""Fail closed before publishing a obviously partial completed-match feed."""
from __future__ import annotations


def validate_completed_feed(payload: dict) -> None:
    events = payload.get("events", []) if isinstance(payload, dict) else []
    minutes = []
    for event in events:
        value = event.get("expandedMinute", event.get("minute"))
        try:
            minutes.append(float(value))
        except (TypeError, ValueError):
            continue
    last = max(minutes, default=0)
    # Same conservative ingestion threshold as the existing repair worker.
    # Abandoned/shortened fixtures require explicit review, never normalization
    # to a full match. This is a minimum guard, not proof of full coverage.
    if not events or last < 80:
        raise ValueError(f"incomplete completed-match feed: {len(events)} events; last minute {last:g}")
