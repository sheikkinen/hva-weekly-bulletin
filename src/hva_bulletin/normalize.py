from collections import defaultdict

from .models import SourceItem


def merge_hilma_ted(items: list[SourceItem]) -> list[SourceItem]:
    by_publication: dict[str, list[SourceItem]] = defaultdict(list)
    independent: list[SourceItem] = []

    for item in items:
        if item.source in {"hilma", "ted"} and item.publication_id:
            by_publication[item.publication_id].append(item)
        else:
            independent.append(item)

    merged = list(independent)
    for publication_id in sorted(by_publication):
        group = by_publication[publication_id]
        primary = next((item for item in group if item.source == "hilma"), group[0])
        urls = {name: url for item in group for name, url in item.source_urls.items()}
        merged.append(primary.model_copy(update={"source_urls": urls}))

    return sorted(merged, key=lambda item: (item.source, item.source_id))
