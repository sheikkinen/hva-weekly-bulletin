from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from .models import SourceHealth, SourceItem


def read_jsonl[Model: BaseModel](path: Path, model: type[Model]) -> list[Model]:
    if not path.exists():
        return []
    return [
        model.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line
    ]


def write_jsonl_if_changed(
    path: Path,
    records: list[BaseModel],
    key: Callable[[BaseModel], object],
) -> bool:
    content = "".join(
        f"{record.model_dump_json()}\n" for record in sorted(records, key=key)
    )
    if path.exists() and path.read_text() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content)
    temporary.replace(path)
    return True


def upsert_health(
    existing: list[SourceHealth], incoming: list[SourceHealth]
) -> list[SourceHealth]:
    records = {
        (record.window_date, record.source, record.organization or ""): record
        for record in existing
    }
    for record in incoming:
        records[(record.window_date, record.source, record.organization or "")] = record
    return [records[key] for key in sorted(records)]


def load_item_state(path: Path) -> dict[str, SourceItem]:
    from .delta import state_key

    return {state_key(item): item for item in read_jsonl(path, SourceItem)}
