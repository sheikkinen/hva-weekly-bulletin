from collections.abc import Iterable

from .models import BulletinSummary, SourceEvent, SourceHealth, ThreadEdge

START_MARKER = "<!-- latest-bulletin:start -->"
END_MARKER = "<!-- latest-bulletin:end -->"
SECTIONS = (
    "New early signals",
    "Threads that advanced",
    "Awards and disputes",
    "Cross-HVA patterns",
    "Deadlines next week",
    "Expected next transitions",
    "Source health and coverage gaps",
    "Event ledger",
)


def _links(event: SourceEvent) -> str:
    return ", ".join(
        f"[{name}]({url})" for name, url in sorted(event.item.source_urls.items())
    )


def _event_line(event: SourceEvent, link_basis: str = "unlinked") -> str:
    date_text = (
        event.effective_date.isoformat() if event.effective_date else "date unknown"
    )
    return (
        f"- **{event.item.organization}: {event.item.title}** "
        f"({date_text}; `{event.event_id}`; link basis: `{link_basis}`) "
        f"- {_links(event)}"
    )


def _lines_or_none(lines: Iterable[str]) -> list[str]:
    materialized = list(lines)
    return materialized or ["- No substantive events."]


def _event_lines(events: Iterable[SourceEvent], bases: dict[str, str]) -> list[str]:
    return _lines_or_none(
        _event_line(event, bases.get(event.event_id, "unlinked")) for event in events
    )


def _cross_events(
    events: list[SourceEvent], edges: list[ThreadEdge]
) -> list[SourceEvent]:
    linked_ids = {
        event_id
        for edge in edges
        if edge.confirmed and len(edge.event_ids) > 1
        for event_id in edge.event_ids
    }
    return [event for event in events if event.event_id in linked_ids]


def _default_blocks(
    events: list[SourceEvent],
    health: list[SourceHealth],
    edges: list[ThreadEdge],
    bases: dict[str, str],
) -> dict[str, list[str]]:
    new_events = [
        event for event in events if event.event_type == "new" and event.source != "mao"
    ]
    advanced = [
        event for event in events if event.event_type in {"updated", "transition"}
    ]
    return {
        "New early signals": _event_lines(new_events, bases),
        "Threads that advanced": _event_lines(advanced, bases),
        "Awards and disputes": _event_lines(
            (event for event in events if event.source == "mao"), bases
        ),
        "Cross-HVA patterns": _event_lines(_cross_events(events, edges), bases),
        "Deadlines next week": _event_lines(
            (event for event in events if event.item.deadline is not None), bases
        ),
        "Expected next transitions": _lines_or_none(
            f"- `{event.event_id}`: observe the next public lifecycle stage "
            f"after `{event.item.lifecycle_stage or event.event_type}`."
            for event in events
        ),
        "Source health and coverage gaps": _lines_or_none(
            f"- **{record.source}/{record.organization or 'all'}:** `{record.status}` "
            f"({record.succeeded}/{record.attempted} succeeded; errors: "
            f"{', '.join(record.error_codes) or 'none'})."
            for record in health
        ),
        "Event ledger": _event_lines(events, bases),
    }


def _summary_blocks(summary: BulletinSummary) -> dict[str, list[str]]:
    return {
        "New early signals": _lines_or_none(summary.new_early_signals),
        "Threads that advanced": _lines_or_none(summary.threads_that_advanced),
        "Awards and disputes": _lines_or_none(summary.awards_and_disputes),
        "Cross-HVA patterns": _lines_or_none(summary.cross_hva_patterns),
        "Deadlines next week": _lines_or_none(summary.deadlines_next_week),
        "Expected next transitions": _lines_or_none(summary.expected_next_transitions),
        "Source health and coverage gaps": _lines_or_none(
            summary.source_health_and_coverage_gaps
        ),
    }


def render_bulletin(
    iso_week: str,
    events: list[SourceEvent],
    health: list[SourceHealth],
    edges: list[ThreadEdge],
    summary: BulletinSummary | None = None,
) -> str:
    bases = {
        event_id: edge.link_basis
        for edge in edges
        if edge.confirmed
        for event_id in edge.event_ids
    }
    blocks = _default_blocks(events, health, edges, bases)
    if summary is not None:
        blocks.update(_summary_blocks(summary))

    parts = [f"# HVA Weekly Bulletin {iso_week}"]
    for section in SECTIONS:
        parts.extend(["", f"## {section}", "", *blocks[section]])
    return "\n".join(parts).rstrip() + "\n"


def update_readme_latest(readme: str, bulletin: str) -> str:
    block = f"{START_MARKER}\n{bulletin.rstrip()}\n{END_MARKER}"
    if START_MARKER in readme and END_MARKER in readme:
        prefix, remainder = readme.split(START_MARKER, 1)
        _, suffix = remainder.split(END_MARKER, 1)
        return f"{prefix}{block}{suffix}"
    return f"{readme.rstrip()}\n\n## Latest bulletin\n\n{block}\n"
