import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from .delta import (
    contains_replacement,
    encoding_repair_keys,
    reconcile_items,
    state_key,
)
from .models import SourceEvent, SourceHealth, SourceItem
from .storage import (
    load_item_state,
    read_jsonl,
    upsert_health,
    write_jsonl_if_changed,
)


class CollectionResult(BaseModel):
    baseline: bool
    events_written: int
    changed: bool


def _iso_week(moment: datetime) -> str:
    year, week, _ = moment.date().isocalendar()
    return f"{year}-W{week:02d}"


def _load_metadata(path: Path) -> dict[str, object]:
    return json.loads(path.read_text()) if path.exists() else {}


def _record_encoding_repair(
    metadata: dict[str, object],
    previous: dict[str, SourceItem],
    current: list[SourceItem],
    state: dict[str, SourceItem],
    repair_keys: set[str],
    observed_at: datetime,
) -> None:
    corrupt_before = {
        key
        for key, item in previous.items()
        if item.source == "ktweb" and contains_replacement(item)
    }
    if not corrupt_before:
        return
    existing = metadata.get("ktweb_encoding_repair")
    prior = existing if isinstance(existing, dict) else {}
    incoming = {state_key(item): item for item in current}
    unresolved = []
    for key in sorted(corrupt_before - repair_keys):
        old = previous[key]
        new = incoming.get(key)
        if new is None:
            reason = "not present in the bounded collection window"
        elif old.source_urls.get("ktweb") != new.source_urls.get("ktweb"):
            reason = "source URL changed"
        elif contains_replacement(new):
            reason = "incoming record still contains replacement characters"
        else:
            reason = "record did not satisfy the bounded repair contract"
        unresolved.append(
            {
                "source_id": old.source_id,
                "url": str(old.source_urls["ktweb"]),
                "reason": reason,
            }
        )
    record = {
        "started_at": prior.get("started_at", observed_at.isoformat()),
        "status": "complete" if not unresolved else "partial",
        "repaired_count": int(prior.get("repaired_count", 0)) + len(repair_keys),
        "unresolved": unresolved,
    }
    if not unresolved:
        record["completed_at"] = observed_at.isoformat()
    metadata["ktweb_encoding_repair"] = record


def persist_collection(
    root: Path,
    items: list[SourceItem],
    health: list[SourceHealth],
    observed_at: datetime,
) -> CollectionResult:
    state_path = root / "state/source-items.jsonl"
    previous = load_item_state(state_path)
    baseline = not state_path.exists()
    repair_keys = encoding_repair_keys(previous, items)
    state, events = reconcile_items(previous, items, observed_at, repair_keys)
    changed = write_jsonl_if_changed(
        state_path,
        list(state.values()),
        lambda record: state_key(record),
    )

    week = _iso_week(observed_at)
    event_path = root / f"events/{week}.jsonl"
    existing_events = read_jsonl(event_path, SourceEvent)
    event_records = {event.event_id: event for event in existing_events}
    event_records.update({event.event_id: event for event in events})
    if events:
        changed |= write_jsonl_if_changed(
            event_path,
            list(event_records.values()),
            lambda record: record.event_id,
        )

    health_path = root / f"source_health/{week}.jsonl"
    health_records = upsert_health(read_jsonl(health_path, SourceHealth), health)
    if health_records:
        changed |= write_jsonl_if_changed(
            health_path,
            health_records,
            lambda record: (
                record.window_date,
                record.source,
                record.organization or "",
            ),
        )

    metadata_path = root / "state/metadata.json"
    metadata = _load_metadata(metadata_path)
    if baseline and "baseline_at" not in metadata:
        metadata["baseline_at"] = observed_at.isoformat()
    _record_encoding_repair(metadata, previous, items, state, repair_keys, observed_at)
    metadata_content = json.dumps(metadata, sort_keys=True) + "\n"
    if not metadata_path.exists() or metadata_path.read_text() != metadata_content:
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(metadata_content)
        changed = True

    return CollectionResult(
        baseline=baseline,
        events_written=len(events),
        changed=changed,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--health", type=Path, required=True)
    args = parser.parse_args()
    items = read_jsonl(args.items, SourceItem)
    health = read_jsonl(args.health, SourceHealth)
    result = persist_collection(args.root, items, health, datetime.now(UTC))
    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
