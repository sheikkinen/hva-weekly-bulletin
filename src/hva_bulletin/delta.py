import hashlib
import json
from datetime import datetime
from typing import Any

from .models import SourceEvent, SourceItem

NOISE_FIELDS = {"fetched_at"}
REPAIRABLE_TEXT_FIELDS = {"title", "organization", "body_excerpt"}


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


def contains_replacement(item: SourceItem) -> bool:
    return any(
        "\ufffd" in str(getattr(item, field) or "") for field in REPAIRABLE_TEXT_FIELDS
    )


def encoding_repair_keys(
    previous: dict[str, SourceItem], current: list[SourceItem]
) -> set[str]:
    incoming = {state_key(item): item for item in current}
    return {
        key
        for key, old in previous.items()
        if old.source == "ktweb"
        and contains_replacement(old)
        and (new := incoming.get(key)) is not None
        and not contains_replacement(new)
        and old.source_urls.get("ktweb") == new.source_urls.get("ktweb")
    }


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
    repair_keys: set[str] | None = None,
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
            changed_fields = _changed_fields(old, item)
            if key in (repair_keys or set()):
                changed_fields = [
                    field
                    for field in changed_fields
                    if not (
                        field in REPAIRABLE_TEXT_FIELDS
                        and "\ufffd" in str(getattr(old, field) or "")
                        and "\ufffd" not in str(getattr(item, field) or "")
                    )
                ]
            if changed_fields:
                events.append(_event(item, "updated", observed_at, changed_fields))
        else:
            state[key] = old

    return state, events
