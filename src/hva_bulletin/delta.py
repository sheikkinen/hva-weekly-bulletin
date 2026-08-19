import hashlib
import json
from datetime import datetime
from typing import Any

from .models import SourceEvent, SourceItem

NOISE_FIELDS = {"fetched_at"}


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, dict):
        return {key: _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, list | tuple):
        return [_normalize(item) for item in value]
    return value


def substantive_payload(item: SourceItem) -> dict[str, Any]:
    payload = item.model_dump(mode="json", exclude=NOISE_FIELDS)
    return _normalize(payload)


def content_hash(item: SourceItem) -> str:
    encoded = json.dumps(
        substantive_payload(item),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def state_key(item: SourceItem) -> str:
    return f"{item.source}:{item.source_id}"


def _changed_fields(previous: SourceItem, current: SourceItem) -> list[str]:
    before = substantive_payload(previous)
    after = substantive_payload(current)
    return sorted(
        key for key in set(before) | set(after) if before.get(key) != after.get(key)
    )


def _event(
    item: SourceItem, event_type: str, observed_at: datetime, changed_fields: list[str]
) -> SourceEvent:
    digest = content_hash(item)
    event_seed = f"{item.source}:{item.source_id}:{event_type}:{digest}".encode()
    return SourceEvent(
        event_id=hashlib.sha256(event_seed).hexdigest(),
        event_type=event_type,
        source=item.source,
        source_id=item.source_id,
        observed_at=observed_at,
        effective_date=item.effective_date,
        content_hash=digest,
        changed_fields=changed_fields,
        item=item,
    )


def reconcile_items(
    previous: dict[str, SourceItem],
    current: list[SourceItem],
    observed_at: datetime,
) -> tuple[dict[str, SourceItem], list[SourceEvent]]:
    state = dict(previous)
    events: list[SourceEvent] = []
    baseline = not previous

    for item in sorted(current, key=state_key):
        key = state_key(item)
        old = previous.get(key)
        if baseline:
            state[key] = item
            continue
        if old is None:
            state[key] = item
            events.append(_event(item, "new", observed_at, []))
            continue
        if content_hash(old) != content_hash(item):
            state[key] = item
            events.append(
                _event(item, "updated", observed_at, _changed_fields(old, item))
            )
        else:
            state[key] = old

    return state, events
