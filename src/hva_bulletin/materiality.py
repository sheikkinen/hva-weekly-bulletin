from datetime import date
from decimal import Decimal

from .models import SourceEvent, SourceHealth, ThreadEdge


def _cross_hva_count(event: SourceEvent, edges: list[ThreadEdge]) -> int:
    return max(
        (
            len(edge.event_ids)
            for edge in edges
            if edge.confirmed and event.event_id in edge.event_ids
        ),
        default=0,
    )


def _sort_key(
    event: SourceEvent,
    edges: list[ThreadEdge],
    as_of: date,
) -> tuple[object, ...]:
    deadline_days = None
    if event.item.deadline is not None:
        deadline_days = (event.item.deadline - as_of).days

    cross_count = _cross_hva_count(event, edges)
    value = event.item.value_eur or Decimal(0)
    effective_ordinal = (event.effective_date or date.min).toordinal()

    if event.source == "mao":
        tier = 0
    elif event.event_type == "transition":
        tier = 1
    elif deadline_days is not None and 0 <= deadline_days <= 14:
        tier = 2
    elif cross_count > 1:
        tier = 3
    elif value > 0:
        tier = 4
    else:
        tier = 5

    return (
        tier,
        deadline_days if deadline_days is not None else 10**9,
        -cross_count,
        -value,
        -effective_ordinal,
        event.event_id,
    )


def order_events(
    events: list[SourceEvent],
    edges: list[ThreadEdge],
    health: list[SourceHealth],
    as_of: date,
    cap: int = 10,
) -> list[SourceEvent]:
    del health  # Health degradation is always rendered in its dedicated section.
    return sorted(events, key=lambda event: _sort_key(event, edges, as_of))[:cap]
