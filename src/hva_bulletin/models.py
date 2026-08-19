from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

SourceName = Literal["ktweb", "dynasty", "casem", "hilma", "ted", "mao"]
EventType = Literal["new", "updated", "transition"]
LinkBasis = Literal["docket", "explicit-reference", "publication-id", "entity", "topic"]


class SourceItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: SourceName
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_urls: dict[str, HttpUrl] = Field(min_length=1)
    organization: str = Field(min_length=1)
    effective_date: date | None
    fetched_at: datetime
    docket: str | None = None
    publication_id: str | None = None
    deadline: date | None = None
    value_eur: Decimal | None = None
    body_excerpt: str | None = None
    lifecycle_stage: str | None = None
    status: str | None = None
    previous_handling: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()

    @field_validator("source_id", "title", "organization")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = " ".join(value.split())
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class SourceEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    event_type: EventType
    source: SourceName
    source_id: str
    observed_at: datetime
    effective_date: date | None
    content_hash: str
    changed_fields: list[str]
    item: SourceItem


class SourceHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    organization: str | None
    window_date: date
    configured: int = Field(ge=0)
    attempted: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    item_count: int = Field(ge=0)
    status: Literal["healthy", "degraded", "failed"]
    error_codes: list[str] = Field(default_factory=list)

    @field_validator("error_codes")
    @classmethod
    def normalize_error_codes(cls, values: list[str]) -> list[str]:
        return sorted(
            {" ".join(value.split()).lower() for value in values if value.strip()}
        )


class ThreadEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    thread_id: str
    event_ids: list[str] = Field(min_length=1)
    link_basis: LinkBasis
    confirmed: bool


class BulletinSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    new_early_signals: list[str]
    threads_that_advanced: list[str]
    awards_and_disputes: list[str]
    cross_hva_patterns: list[str]
    deadlines_next_week: list[str]
    expected_next_transitions: list[str]
    source_health_and_coverage_gaps: list[str]


class Bulletin(BaseModel):
    model_config = ConfigDict(frozen=True)

    iso_week: str = Field(pattern=r"^\d{4}-W\d{2}$")
    summary: BulletinSummary
    events: list[SourceEvent]
    confirmed_threads: list[ThreadEdge]
    source_health: list[SourceHealth]
