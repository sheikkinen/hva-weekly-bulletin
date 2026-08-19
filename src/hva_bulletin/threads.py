import hashlib
from collections import defaultdict
from itertools import combinations

from pydantic import BaseModel

from .models import SourceEvent, ThreadEdge


class ThreadResult(BaseModel):
    confirmed: list[ThreadEdge]
    candidates: list[ThreadEdge]


def _edge(events: list[SourceEvent], basis: str, confirmed: bool) -> ThreadEdge:
    event_ids = sorted(event.event_id for event in events)
    seed = f"{basis}:{':'.join(event_ids)}".encode()
    return ThreadEdge(
        thread_id=hashlib.sha256(seed).hexdigest()[:24],
        event_ids=event_ids,
        link_basis=basis,
        confirmed=confirmed,
    )


def _group(events: list[SourceEvent], attribute: str) -> list[list[SourceEvent]]:
    groups: dict[str, list[SourceEvent]] = defaultdict(list)
    for event in events:
        value = getattr(event.item, attribute)
        if value:
            groups[str(value).casefold()].append(event)
    return list(groups.values())


def link_events(events: list[SourceEvent]) -> ThreadResult:
    confirmed: list[ThreadEdge] = []

    for group in _group(events, "docket"):
        edge = _edge(group, "docket", True)
        confirmed.append(edge)

    by_source_id = {event.source_id: event for event in events}
    for event in events:
        references = [
            by_source_id[reference]
            for reference in event.item.previous_handling
            if reference in by_source_id
        ]
        if event.item.previous_handling:
            edge = _edge([event, *references], "explicit-reference", True)
            confirmed.append(edge)

    for group in _group(events, "publication_id"):
        if len(group) > 1:
            edge = _edge(group, "publication-id", True)
            confirmed.append(edge)

    entity_groups: dict[tuple[str, str], list[SourceEvent]] = defaultdict(list)
    for event in events:
        for entity in event.item.entities:
            entity_groups[
                (event.item.organization.casefold(), entity.casefold())
            ].append(event)
    for group in entity_groups.values():
        if len(group) > 1:
            edge = _edge(group, "entity", True)
            confirmed.append(edge)

    candidates = []
    for left, right in combinations(events, 2):
        if left.item.title.casefold() == right.item.title.casefold():
            candidates.append(_edge([left, right], "topic", False))

    unique_confirmed = {edge.thread_id: edge for edge in confirmed}
    unique_candidates = {edge.thread_id: edge for edge in candidates}
    return ThreadResult(
        confirmed=[unique_confirmed[key] for key in sorted(unique_confirmed)],
        candidates=[unique_candidates[key] for key in sorted(unique_candidates)],
    )
