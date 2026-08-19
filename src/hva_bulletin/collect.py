import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from .delta import reconcile_items, state_key
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


def persist_collection(
    root: Path,
    items: list[SourceItem],
    health: list[SourceHealth],
    observed_at: datetime,
) -> CollectionResult:
    state_path = root / "state/source-items.jsonl"
    previous = load_item_state(state_path)
    baseline = not state_path.exists()
    state, events = reconcile_items(previous, items, observed_at)
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
    if baseline and not metadata_path.exists():
        metadata_path.write_text(
            json.dumps({"baseline_at": observed_at.isoformat()}, sort_keys=True) + "\n"
        )
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
