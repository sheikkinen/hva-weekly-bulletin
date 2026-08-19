import argparse
import json
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from .materiality import order_events
from .models import SourceEvent, SourceHealth
from .storage import read_jsonl, write_jsonl_if_changed
from .threads import link_events


def previous_complete_window(now: datetime) -> tuple[datetime, datetime]:
    utc_now = now.astimezone(UTC)
    end = datetime.combine(utc_now.date(), time.min, tzinfo=UTC)
    return end - timedelta(days=7), end


def build_window(root: Path, output: Path, now: datetime) -> int:
    start, end = previous_complete_window(now)
    events = [
        event
        for path in sorted((root / "events").glob("*.jsonl"))
        for event in read_jsonl(path, SourceEvent)
        if start <= event.observed_at < end
    ]
    health = [
        record
        for path in sorted((root / "source_health").glob("*.jsonl"))
        for record in read_jsonl(path, SourceHealth)
        if start.date() <= record.window_date < end.date()
    ]
    threads = link_events(events).confirmed
    candidates = order_events(events, threads, health, end.date(), cap=10)
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl_if_changed(
        output / "events.jsonl", events, lambda record: record.event_id
    )
    write_jsonl_if_changed(
        output / "health.jsonl",
        health,
        lambda record: (record.window_date, record.source, record.organization or ""),
    )
    write_jsonl_if_changed(
        output / "threads.jsonl", threads, lambda record: record.thread_id
    )
    iso_year, iso_week, _ = end.date().isocalendar()
    window = {
        "iso_week": f"{iso_year}-W{iso_week:02d}",
        "narrative_candidates": [event.model_dump(mode="json") for event in candidates],
        "events": [event.model_dump(mode="json") for event in events],
        "confirmed_threads": [thread.model_dump(mode="json") for thread in threads],
        "source_health": [record.model_dump(mode="json") for record in health],
    }
    (output / "window.json").write_text(
        json.dumps(window, ensure_ascii=False, sort_keys=True) + "\n"
    )
    return len(events)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    count = build_window(args.root, args.output, datetime.now(UTC))
    print(f"Selected {count} substantive events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
