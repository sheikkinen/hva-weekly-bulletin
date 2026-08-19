import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from hva_bulletin.adapters import (
    ADAPTER_ALLOWLIST,
    _is_hva_buyer,
    failed_families,
    normalize_envelope,
)
from hva_bulletin.collect import persist_collection
from hva_bulletin.config import load_hvas
from hva_bulletin.models import SourceHealth, SourceItem
from hva_bulletin.publish import publish_bulletin
from hva_bulletin.storage import upsert_health
from hva_bulletin.threads import link_events
from hva_bulletin.weekly_window import previous_complete_window

NOW = datetime(2026, 8, 19, 6, tzinfo=UTC)


def item(**changes: object) -> SourceItem:
    values: dict[str, object] = {
        "source": "ktweb",
        "source_id": "ktweb-pohde-2026-08-18-42",
        "title": "Patient system",
        "source_urls": {"ktweb": "https://example.test/governance/42"},
        "organization": "Pohde",
        "effective_date": date(2026, 8, 18),
        "fetched_at": NOW,
        "docket": "PPHVADno-2026-42",
        "previous_handling": (),
        "entities": ("Patient system",),
    }
    values.update(changes)
    return SourceItem.model_validate(values)


def health(status: str = "healthy", **changes: object) -> SourceHealth:
    values: dict[str, object] = {
        "source": "ktweb",
        "organization": "Pohde",
        "window_date": NOW.date(),
        "configured": 1,
        "attempted": 1,
        "succeeded": 1,
        "item_count": 1,
        "status": status,
        "error_codes": [],
    }
    values.update(changes)
    return SourceHealth.model_validate(values)


def test_health_upsert_is_keyed_and_noise_free() -> None:
    original = health(error_codes=[" Timeout ", "timeout"])
    assert original.error_codes == ["timeout"]
    assert upsert_health([original], [original]) == [original]

    replacement = health(
        status="degraded",
        succeeded=0,
        error_codes=["HTTP-500"],
    )
    assert upsert_health([original], [replacement]) == [replacement]


def test_collection_persists_baseline_delta_and_noop(tmp_path: Path) -> None:
    first = persist_collection(tmp_path, [item()], [health()], NOW)
    assert first.baseline is True
    assert first.events_written == 0
    state_before = (tmp_path / "state/source-items.jsonl").read_text()

    changed = item(title="Updated patient system")
    second = persist_collection(tmp_path, [changed], [health()], NOW)
    assert second.baseline is False
    assert second.events_written == 1

    tracked_before = {
        path.relative_to(tmp_path): path.read_text()
        for directory in ("state", "events", "source_health")
        for path in (tmp_path / directory).glob("*")
    }
    observed_later = changed.model_copy(
        update={"fetched_at": datetime(2026, 8, 19, 7, tzinfo=UTC)}
    )
    third = persist_collection(tmp_path, [observed_later], [health()], NOW)
    tracked_after = {
        path.relative_to(tmp_path): path.read_text()
        for directory in ("state", "events", "source_health")
        for path in (tmp_path / directory).glob("*")
    }
    assert third.changed is False
    assert tracked_after == tracked_before
    assert state_before != (tmp_path / "state/source-items.jsonl").read_text()


def test_thread_links_confirmed_evidence_and_keeps_topic_candidate() -> None:
    from hva_bulletin.delta import reconcile_items

    baseline, _ = reconcile_items({}, [item()], NOW)
    variants = [
        item(source_id="docket", source="dynasty"),
        item(
            source_id="reference",
            source="casem",
            docket=None,
            previous_handling=("ktweb-pohde-2026-08-18-42",),
        ),
        item(
            source_id="publication-a",
            source="hilma",
            docket=None,
            publication_id="556915-2026",
        ),
        item(
            source_id="publication-b",
            source="ted",
            docket=None,
            publication_id="556915-2026",
        ),
        item(source_id="topic-only", source="mao", docket=None),
    ]
    _, events = reconcile_items(baseline, variants, NOW)
    result = link_events(events)
    confirmed_bases = {edge.link_basis for edge in result.confirmed}
    assert {"docket", "explicit-reference", "publication-id"} <= confirmed_bases
    assert all(edge.confirmed for edge in result.confirmed)
    assert result.candidates
    assert all(
        not edge.confirmed and edge.link_basis == "topic" for edge in result.candidates
    )


def test_canonical_configuration_has_22_supported_hvas() -> None:
    records = load_hvas()
    assert len(records) == 22
    assert len({record.name for record in records}) == 22
    assert {record.adapter for record in records} <= {"ktweb", "dynasty", "casem"}
    assert all(str(record.url).startswith("https://") for record in records)
    kainuu = next(record for record in records if record.name == "Kainuu")
    assert str(kainuu.url) == "https://kainuunhyvinvointialue.cloudnc.fi/"


def test_quiet_week_does_not_write_bulletin_or_readme(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# Project\n")
    result = publish_bulletin(tmp_path, "2026-W34", [], [], [])
    assert result.published is False
    assert not (tmp_path / "bulletins/2026-W34.md").exists()
    assert readme.read_text() == "# Project\n"


def test_publish_writes_bulletin_and_embeds_it_in_readme(tmp_path: Path) -> None:
    from hva_bulletin.delta import reconcile_items

    readme = tmp_path / "README.md"
    readme.write_text("# Project\n")
    baseline, _ = reconcile_items({}, [item()], NOW)
    _, events = reconcile_items(baseline, [item(title="Updated patient system")], NOW)
    result = publish_bulletin(tmp_path, "2026-W34", events, [health()], [])
    bulletin = (tmp_path / "bulletins/2026-W34.md").read_text()
    assert result.published is True
    assert bulletin in readme.read_text()


def test_workflows_encode_schedule_permissions_and_scoped_staging() -> None:
    collect = Path(".github/workflows/collect.yml").read_text()
    bulletin = Path(".github/workflows/bulletin.yml").read_text()

    assert "cron: '30 5 * * *'" in collect
    assert "workflow_dispatch:" in collect
    assert "contents: write" in collect
    assert "group: hva-bulletin-state" in collect
    assert "cancel-in-progress: false" in collect
    assert "git add state/ events/ source_health/" in collect
    assert "git pull --rebase" in collect
    assert "ktweb,dynasty,casem,hilma,ted,mao" in collect
    assert "python -m playwright install --with-deps chromium" in collect

    assert "cron: '0 6 * * 1'" in bulletin
    assert "workflow_dispatch:" in bulletin
    assert "group: hva-bulletin-state" in bulletin
    assert "cancel-in-progress: false" in bulletin
    assert "ANTHROPIC_API_KEY" in bulletin
    assert "if: steps.window.outputs.event_count != '0'" in bulletin
    assert "window_json=@tmp/window.json" in bulletin
    assert "--export-state tmp/graph-state.json" in bulletin
    assert "git add bulletins/ README.md" in bulletin
    assert "git pull --rebase" in bulletin


def test_persisted_files_are_json_lines(tmp_path: Path) -> None:
    persist_collection(tmp_path, [item()], [health()], NOW)
    for path in (
        tmp_path / "state/source-items.jsonl",
        tmp_path / "source_health/2026-W34.jsonl",
    ):
        for line in path.read_text().splitlines():
            assert isinstance(json.loads(line), dict)


@pytest.mark.parametrize("source", ADAPTER_ALLOWLIST)
def test_each_allowlisted_adapter_normalizes_a_fixture(source: str) -> None:
    envelope = {
        "fetched_at": NOW.isoformat(),
        "items": [
            {
                "id": f"{source}-stable-1",
                "title": "Public procurement event",
                "hva": "Pohde",
                "meeting_date": "2026-08-18",
                "value_eur": "1 200,50",
                "detail_url": f"https://example.test/{source}/stable-1",
            }
        ],
    }
    normalized = normalize_envelope(source, envelope)
    assert normalized[0].source == source
    assert normalized[0].source_id == "stable-1"
    assert normalized[0].value_eur == Decimal("1200.50")


def test_adapter_allowlist_fails_closed() -> None:
    with pytest.raises(ValueError, match="not allowlisted"):
        normalize_envelope("filesystem", {"items": []})


def test_total_source_family_failure_fails_closed() -> None:
    failed = health(status="failed", succeeded=0, error_codes=["timeout"])
    assert failed_families(["ktweb"], [failed]) == ["ktweb"]
    assert failed_families(["ktweb"], [health(status="degraded")]) == []


def test_ted_buyer_scope_is_limited_to_hvas() -> None:
    assert _is_hva_buyer({"fin": ["Pohjois-Pohjanmaan hyvinvointialue"]})
    assert _is_hva_buyer("Pohjois-Karjalan hankintatoimi")
    assert not _is_hva_buyer({"fin": ["Helsingin yliopisto"]})
    assert not _is_hva_buyer("Sansia Oy")
    assert not _is_hva_buyer("Lappica Oy")
    assert not _is_hva_buyer("Lapinjärven kunta")


def test_weekly_window_is_previous_seven_complete_utc_days() -> None:
    start, end = previous_complete_window(datetime(2026, 8, 24, 6, 15, tzinfo=UTC))
    assert start == datetime(2026, 8, 17, tzinfo=UTC)
    assert end == datetime(2026, 8, 24, tzinfo=UTC)
