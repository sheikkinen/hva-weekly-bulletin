from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from hva_bulletin.delta import content_hash, encoding_repair_keys, reconcile_items
from hva_bulletin.materiality import order_events
from hva_bulletin.models import SourceHealth, SourceItem, ThreadEdge
from hva_bulletin.normalize import merge_hilma_ted
from hva_bulletin.render import render_bulletin, update_readme_latest

NOW = datetime(2026, 8, 19, 6, tzinfo=UTC)


def item(source: str = "hilma", **changes: object) -> SourceItem:
    values: dict[str, object] = {
        "source": source,
        "source_id": f"{source}-1",
        "title": "Patient system procurement",
        "source_urls": {source: f"https://example.test/{source}/1"},
        "organization": "Pohde",
        "effective_date": date(2026, 8, 18),
        "fetched_at": NOW,
        "publication_id": "556915-2026" if source in {"hilma", "ted"} else None,
        "deadline": date(2026, 8, 28),
        "value_eur": Decimal("1200000"),
        "docket": "PPHVADno-2026-42",
        "body_excerpt": "A  patient   system",
        "lifecycle_stage": "tendered",
    }
    values.update(changes)
    return SourceItem.model_validate(values)


@pytest.mark.parametrize("source", ["ktweb", "dynasty", "casem", "hilma", "ted", "mao"])
def test_all_authorized_sources_validate(source: str) -> None:
    assert item(source).source == source


def test_source_item_requires_source_urls() -> None:
    with pytest.raises(ValidationError):
        item("hilma", source_urls={})


def test_content_hash_ignores_observation_noise() -> None:
    original = item()
    noisy = item(
        fetched_at=datetime(2026, 8, 19, 7, tzinfo=UTC),
        source_urls={
            "ted": "https://example.test/ted/1",
            "hilma": "https://example.test/hilma/1",
        },
        body_excerpt="A patient system",
    )
    original_with_ted = item(
        source_urls={
            "hilma": str(original.source_urls["hilma"]),
            "ted": "https://example.test/ted/1",
        }
    )
    assert content_hash(original_with_ted) == content_hash(noisy)


def test_baseline_update_and_retry_are_deterministic() -> None:
    baseline_state, baseline_events = reconcile_items({}, [item()], NOW)
    assert baseline_events == []

    changed = item(deadline=date(2026, 8, 27))
    changed_state, changed_events = reconcile_items(baseline_state, [changed], NOW)
    assert len(changed_events) == 1
    assert changed_events[0].event_type == "updated"
    assert changed_events[0].changed_fields == ["deadline"]

    retry_state, retry_events = reconcile_items(changed_state, [changed], NOW)
    assert retry_events == []
    assert retry_state == changed_state
    assert all(event.event_type != "removed" for event in changed_events)


def test_encoding_repair_suppresses_only_repaired_text_fields() -> None:
    corrupt = item("ktweb", title="P\ufffdytt\ufffdkirja")
    previous = {"ktweb:ktweb-1": corrupt}
    repaired = item("ktweb", title="Pöytäkirja")
    repair_keys = encoding_repair_keys(previous, [repaired])

    repaired_state, repair_events = reconcile_items(
        previous, [repaired], NOW, repair_keys
    )
    assert repair_events == []
    assert repaired_state["ktweb:ktweb-1"].title == "Pöytäkirja"

    changed = repaired.model_copy(update={"deadline": date(2026, 8, 27)})
    _, changed_events = reconcile_items(previous, [changed], NOW, repair_keys)
    assert len(changed_events) == 1
    assert changed_events[0].changed_fields == ["deadline"]

    moved = item(
        "ktweb",
        title="Pöytäkirja",
        source_urls={"ktweb": "https://example.test/ktweb/moved"},
    )
    assert encoding_repair_keys(previous, [moved]) == set()
    _, moved_events = reconcile_items(previous, [moved], NOW)
    assert moved_events[0].changed_fields == ["source_urls", "title"]


def test_hilma_ted_publication_merges_without_fuzzy_matching() -> None:
    hilma = item("hilma")
    ted = item(
        "ted",
        source_urls={"ted": "https://ted.europa.eu/fi/notice/-/detail/556915-2026"},
    )
    merged = merge_hilma_ted([ted, hilma])
    assert len(merged) == 1
    assert merged[0].source_id == "hilma-1"
    assert set(merged[0].source_urls) == {"hilma", "ted"}


def test_materiality_is_deterministic_and_caps_narrative() -> None:
    state, _ = reconcile_items({}, [item()], NOW)
    events = []
    for index in range(12):
        changed = item(
            source_id=f"hilma-{index}",
            title=f"Procurement {index}",
            value_eur=Decimal(index),
        )
        _, emitted = reconcile_items(state, [changed], NOW)
        events.extend(emitted)

    ordered = order_events(events, [], [], NOW.date(), cap=10)
    assert len(ordered) == 10
    assert [event.item.value_eur for event in ordered] == sorted(
        (event.item.value_eur for event in ordered), reverse=True
    )


def test_bulletin_contains_health_edges_and_uncapped_ledger() -> None:
    baseline, _ = reconcile_items({}, [item()], NOW)
    changed = item(deadline=date(2026, 8, 27))
    _, events = reconcile_items(baseline, [changed], NOW)
    edge = ThreadEdge(
        thread_id="thread-1",
        event_ids=[events[0].event_id],
        link_basis="docket",
        confirmed=True,
    )
    health = SourceHealth(
        source="casem",
        organization="Pirha",
        window_date=NOW.date(),
        configured=1,
        attempted=1,
        succeeded=0,
        item_count=0,
        status="failed",
        error_codes=["timeout"],
    )
    bulletin = render_bulletin("2026-W34", events, [health], [edge])
    for heading in (
        "## New early signals",
        "## Threads that advanced",
        "## Awards and disputes",
        "## Cross-HVA patterns",
        "## Deadlines next week",
        "## Expected next transitions",
        "## Source health and coverage gaps",
        "## Event ledger",
    ):
        assert heading in bulletin
    assert events[0].event_id in bulletin
    assert "failed" in bulletin
    assert "docket" in bulletin


def test_latest_bulletin_is_embedded_in_readme_idempotently() -> None:
    readme = "# HVA Weekly Bulletin\n\nProject introduction.\n"
    bulletin = "# HVA Weekly Bulletin 2026-W34\n\n## New early signals\n\n- One event\n"
    updated = update_readme_latest(readme, bulletin)
    assert bulletin in updated
    assert updated.count("<!-- latest-bulletin:start -->") == 1
    assert updated.count("<!-- latest-bulletin:end -->") == 1
    assert update_readme_latest(updated, bulletin) == updated

    next_bulletin = bulletin.replace("One event", "A newer event")
    replaced = update_readme_latest(updated, next_bulletin)
    assert "A newer event" in replaced
    assert "One event" not in replaced
