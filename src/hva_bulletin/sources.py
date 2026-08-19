import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ElementTree
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

from .models import SourceItem

HVA_BUYER_TERMS = (
    "hyvinvointialue",
    "välfärdsområde",
    "hus-yhtymä",
    "pohde",
    "pirha",
    "varha",
    "vantaan ja keravan",
    "itä-uudenmaan",
    "länsi-uudenmaan",
    "keski-uudenmaan",
    "keski-suomen",
    "pohjois-savon",
    "etelä-savon",
    "pohjois-karjalan",
    "pohjois-pohjanmaan",
    "kainuun",
    "lapin",
    "kanta-hämeen",
    "päijät-hämeen",
    "kymenlaakson",
    "etelä-karjalan",
    "satakunnan",
    "etelä-pohjanmaan",
    "pohjanmaan",
    "keski-pohjanmaan",
)


def parse_date(value: object) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", str(value))
        return date(int(match[3]), int(match[2]), int(match[1])) if match else None


def parse_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None


def first_text(value: object) -> str:
    if isinstance(value, dict):
        for language in ("fin", "eng"):
            if value.get(language):
                return first_text(value[language])
        return first_text(next(iter(value.values()), ""))
    if isinstance(value, list):
        return first_text(value[0]) if value else ""
    return str(value or "")


def is_hva_buyer(value: object) -> bool:
    buyer = first_text(value).casefold()
    return any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", buyer) for term in HVA_BUYER_TERMS
    )


def first_present(raw: dict[str, Any], *keys: str, default: object = None) -> object:
    for key in keys:
        value = raw.get(key)
        if value:
            return value
    return default


def normalize_record(
    source: str, raw: dict[str, Any], fetched_at: datetime
) -> SourceItem:
    source_id = str(first_present(raw, "source_id", "id", default="")).removeprefix(
        f"{source}-"
    )
    publication_id = first_present(
        raw, "publication_id", "publication_number", "tedPublicationId"
    )
    detail_url = first_present(raw, "detail_url", "url", "source_url")
    if not detail_url:
        raise ValueError("source record has no public URL")
    return SourceItem(
        source=source,
        source_id=source_id,
        title=first_present(raw, "title", "subject", default="Untitled public record"),
        source_urls={source: detail_url},
        organization=first_present(
            raw, "organization", "hva", "buyer", default="Unknown"
        ),
        effective_date=parse_date(
            first_present(
                raw, "effective_date", "meeting_date", "filed", "publication_date"
            )
        ),
        fetched_at=fetched_at,
        docket=raw.get("docket"),
        publication_id=str(publication_id) if publication_id else None,
        deadline=parse_date(raw.get("deadline")),
        value_eur=parse_decimal(raw.get("value_eur")),
        body_excerpt=first_present(raw, "body_excerpt", "body"),
        lifecycle_stage=first_present(
            raw, "lifecycle_stage", "meeting_type", "notice_type"
        ),
        status=raw.get("status"),
        previous_handling=tuple(raw.get("previous_handling") or ()),
        entities=tuple(raw.get("entities") or ()),
    )


def request(url: str, payload: dict[str, Any] | None = None) -> bytes:
    command = [
        "curl",
        "-fsSL",
        "--max-time",
        "30",
        "-A",
        "hva-weekly-bulletin/0.1",
    ]
    if payload is not None:
        command.extend(
            [
                "-X",
                "POST",
                "-H",
                "Content-Type: application/json",
                "-d",
                json.dumps(payload),
            ]
        )
    command.append(url)
    return subprocess.run(command, check=True, capture_output=True).stdout


def item_from_link(
    source: str,
    organization: str,
    title: str,
    url: str,
    now: datetime,
    effective_date: date | None = None,
) -> SourceItem:
    digest = hashlib.sha256(url.encode()).hexdigest()[:20]
    return SourceItem(
        source=source,
        source_id=f"{organization.casefold()}-{digest}",
        title=title,
        source_urls={source: url},
        organization=organization,
        effective_date=effective_date,
        fetched_at=now,
        lifecycle_stage="governance-agenda",
    )


def rss_entries(url: str) -> list[tuple[str, str]]:
    root = ElementTree.fromstring(request(url))
    return [
        (entry.findtext("title", "").strip(), entry.findtext("link", "").strip())
        for entry in root.iter("item")
    ]


def collect_ktweb(organization: str, base_url: str, now: datetime) -> list[SourceItem]:
    feed_url = f"{base_url.rstrip('/')}/ktwebscr/pk_rssfeed.htm"
    records = []
    for _, meeting_url in rss_entries(feed_url)[:5]:
        html = request(meeting_url).decode("utf-8", errors="replace")
        meeting_date = parse_date(html)
        matches = re.findall(
            r"<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>\s*"
            r'<a\s+href="([^"]*)"[^>]*>([^<]+)</a>',
            html,
            re.I | re.S,
        )
        for _, href, raw_title in matches:
            records.append(
                item_from_link(
                    "ktweb",
                    organization,
                    " ".join(raw_title.split()),
                    urljoin(meeting_url, href),
                    now,
                    meeting_date,
                )
            )
    return records


def collect_dynasty(
    organization: str, base_url: str, now: datetime
) -> list[SourceItem]:
    separator = "&" if "?" in base_url else "?"
    feed_url = f"{base_url}{separator}page=rss/meetingitems&show=100"
    records = []
    for raw_title, detail_url in rss_entries(feed_url):
        title = re.sub(r"^.*?§\s*\d+\s*", "", raw_title).strip() or raw_title
        records.append(
            item_from_link(
                "dynasty", organization, title, detail_url, now, parse_date(raw_title)
            )
        )
    return records


def collect_casem(organization: str, base_url: str, now: datetime) -> list[SourceItem]:
    from playwright.sync_api import sync_playwright

    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(locale="fi-FI")
        organ_url = f"{base_url.rstrip('/')}/fi-FI/Toimielimet/Aluehallitus"
        page.goto(organ_url, wait_until="domcontentloaded", timeout=30_000)
        meeting = page.locator('a[href*="/Kokous_"]').first
        meeting_url = urljoin(base_url, meeting.get_attribute("href") or "")
        page.goto(meeting_url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2_000)
        meeting_date = parse_date(page.locator("h1").first.inner_text())
        for link in page.locator("a").all():
            title = " ".join(link.inner_text().split())
            if re.match(r"^§\s*\d+", title):
                records.append(
                    item_from_link(
                        "casem",
                        organization,
                        title,
                        urljoin(meeting_url, link.get_attribute("href") or ""),
                        now,
                        meeting_date,
                    )
                )
        browser.close()
    return records


def collect_governance(
    adapter: str, organization: str, url: str, now: datetime
) -> list[SourceItem]:
    if adapter == "ktweb":
        return collect_ktweb(organization, url, now)
    if adapter == "dynasty":
        return collect_dynasty(organization, url, now)
    return collect_casem(organization, url, now)


def collect_hilma(now: datetime) -> list[SourceItem]:
    url = "https://www.hankintailmoitukset.fi/search/eformnotices?search=hyvinvointialue&queryType=full&$top=100&$orderby=datePublished+desc"
    payload = json.loads(request(url))
    records = []
    for raw in payload.get("value", []):
        buyer = raw.get("organisationNameFi") or raw.get("organisationNameEn")
        if not is_hva_buyer(buyer):
            continue
        procedure_id = raw.get("procedureId")
        numeric_id = raw.get("noticeId")
        detail = (
            f"https://www.hankintailmoitukset.fi/fi/public/procedure/{procedure_id}/enotice/{numeric_id}/"
            if procedure_id and numeric_id
            else url
        )
        records.append(
            normalize_record(
                "hilma",
                {
                    "id": raw.get("id"),
                    "title": raw.get("titleFi") or raw.get("titleEn"),
                    "hva": buyer,
                    "meeting_date": raw.get("datePublished"),
                    "deadline": raw.get("deadline"),
                    "notice_type": raw.get("type"),
                    "publication_id": raw.get("tedPublicationId"),
                    "detail_url": detail,
                },
                now,
            )
        )
    return records


def collect_ted(now: datetime) -> list[SourceItem]:
    since = date.fromordinal(now.date().toordinal() - 90).strftime("%Y%m%d")
    payload = {
        "query": f"buyer-country = FIN AND publication-date >= {since}",
        "fields": [
            "publication-number",
            "notice-title",
            "buyer-name",
            "publication-date",
            "deadline-receipt-tender-date-lot",
            "notice-type",
        ],
        "limit": 100,
    }
    response = json.loads(
        request("https://api.ted.europa.eu/v3/notices/search", payload)
    )
    records = []
    for notice in response.get("notices", []):
        if not is_hva_buyer(notice.get("buyer-name")):
            continue
        publication = notice.get("publication-number")
        deadlines = notice.get("deadline-receipt-tender-date-lot") or []
        records.append(
            normalize_record(
                "ted",
                {
                    "id": publication,
                    "title": first_text(notice.get("notice-title")) or "TED notice",
                    "buyer": first_text(notice.get("buyer-name")) or "Unknown",
                    "publication_date": notice.get("publication-date"),
                    "deadline": deadlines[0] if deadlines else None,
                    "notice_type": notice.get("notice-type"),
                    "publication_number": publication,
                    "detail_url": f"https://ted.europa.eu/fi/notice/-/detail/{publication}",
                },
                now,
            )
        )
    return records


def collect_mao(now: datetime) -> list[SourceItem]:
    url = "https://www.markkinaoikeus.fi/vireilla-olevat-hankinta-asiat/"
    html = request(url).decode("utf-8", errors="replace")
    cells = [
        " ".join(re.sub(r"<[^>]+>", " ", cell).split())
        for cell in re.findall(r"<td[^>]*>(.*?)</td>", html, re.I | re.S)
    ]
    records = []
    for cell in cells:
        if "hyvinvointialue" not in cell.casefold():
            continue
        filed = re.search(r"VIREILLE:\s*([^A-Z]+)", cell)
        buyer = re.search(r"HANKINTAYKSIKKÖ:\s*(.*?)(?:HANKINTAPÄÄTÖS|$)", cell)
        digest = hashlib.sha256(cell.encode()).hexdigest()[:20]
        records.append(
            SourceItem(
                source="mao",
                source_id=digest,
                title=cell[:160],
                source_urls={"mao": url},
                organization=buyer.group(1).strip() if buyer else "Unknown HVA",
                effective_date=parse_date(filed.group(1) if filed else None),
                fetched_at=now,
                lifecycle_stage="pending-dispute",
                status="pending",
            )
        )
    return records
