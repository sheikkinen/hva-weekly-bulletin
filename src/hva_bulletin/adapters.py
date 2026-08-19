import argparse
import json
import subprocess
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from .config import load_hvas
from .models import SourceHealth, SourceItem
from .normalize import merge_hilma_ted
from .sources import (
    collect_governance,
    collect_hilma,
    collect_mao,
    collect_ted,
    is_hva_buyer,
    normalize_record,
)
from .storage import write_jsonl_if_changed

ADAPTER_ALLOWLIST = ("ktweb", "dynasty", "casem", "hilma", "ted", "mao")


def _is_hva_buyer(value: object) -> bool:
    return is_hva_buyer(value)


def normalize_envelope(source: str, envelope: dict[str, object]) -> list[SourceItem]:
    if source not in ADAPTER_ALLOWLIST:
        raise ValueError(f"adapter is not allowlisted: {source}")
    fetched_at = datetime.fromisoformat(
        str(envelope.get("fetched_at") or datetime.now(UTC).isoformat()).replace(
            "Z", "+00:00"
        )
    )
    raw_items = envelope.get("items", [])
    if not isinstance(raw_items, list):
        raise ValueError("source envelope items must be a list")
    return [normalize_record(source, raw, fetched_at) for raw in raw_items]


def failed_families(selected: list[str], health: list[SourceHealth]) -> list[str]:
    return sorted(
        source
        for source in selected
        if not any(
            record.source == source and record.status != "failed" for record in health
        )
    )


def _health(
    source: str,
    organization: str | None,
    now: datetime,
    found: list[SourceItem],
    succeeded: int,
) -> SourceHealth:
    if not succeeded:
        status, errors = "failed", ["fetch-or-schema"]
    elif found:
        status, errors = "healthy", []
    else:
        status, errors = "degraded", ["empty"]
    return SourceHealth(
        source=source,
        organization=organization,
        window_date=now.date(),
        configured=1,
        attempted=1,
        succeeded=succeeded,
        item_count=len(found),
        status=status,
        error_codes=errors,
    )


def _collect_governance_families(
    names: list[str], now: datetime
) -> tuple[list[SourceItem], list[SourceHealth]]:
    items: list[SourceItem] = []
    health: list[SourceHealth] = []
    for record in load_hvas():
        if record.adapter not in names:
            continue
        try:
            found = collect_governance(
                record.adapter, record.name, str(record.url), now
            )
            succeeded = 1
        except Exception:
            found, succeeded = [], 0
        items.extend(found)
        health.append(_health(record.adapter, record.name, now, found, succeeded))
    return items, health


def _collect_single_family(
    name: str, now: datetime
) -> tuple[list[SourceItem], SourceHealth]:
    collectors = {"hilma": collect_hilma, "ted": collect_ted, "mao": collect_mao}
    try:
        found = collectors[name](now)
        succeeded = 1
    except (
        OSError,
        subprocess.CalledProcessError,
        urllib.error.URLError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
    ):
        found, succeeded = [], 0
    return found, _health(name, None, now, found, succeeded)


def collect_allowlisted(
    names: list[str], now: datetime
) -> tuple[list[SourceItem], list[SourceHealth]]:
    unknown = set(names) - set(ADAPTER_ALLOWLIST)
    if unknown:
        raise ValueError(f"adapters are not allowlisted: {sorted(unknown)}")

    governance = [name for name in names if name in {"ktweb", "dynasty", "casem"}]
    items, health = _collect_governance_families(governance, now)
    for name in names:
        if name in governance:
            continue
        found, record = _collect_single_family(name, now)
        items.extend(found)
        health.append(record)
    return merge_hilma_ted(items), health


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allowlist", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    names = [name.strip() for name in args.allowlist.split(",") if name.strip()]
    items, health = collect_allowlisted(names, datetime.now(UTC))
    args.output.mkdir(parents=True, exist_ok=True)
    write_jsonl_if_changed(
        args.output / "items.jsonl",
        items,
        lambda record: (record.source, record.source_id),
    )
    write_jsonl_if_changed(
        args.output / "health.jsonl",
        health,
        lambda record: (record.source, record.organization or ""),
    )
    failures = failed_families(names, health)
    if failures:
        raise RuntimeError(f"total source-family failure: {', '.join(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
