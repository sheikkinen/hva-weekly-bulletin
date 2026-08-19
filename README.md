# HVA Weekly Bulletin

This public YAMLGraph consumer publishes a Monday account of changes in Finnish
wellbeing-services county governance, procurement, and procurement disputes.
It is evidence-first: every rendered event retains its stable ID and direct
public source links.

## Coverage and cadence

Daily collection covers a canonical map of 22 organizations through KTweb,
Dynasty, or CaseM, plus Hilma, TED, and pending Market Court procurement cases.
The collector commits compact normalized state, substantive events, and bounded
source-health records. Monday publication reads the previous seven complete UTC
days. A quiet window is a green no-op and does not modify this README.

Hilma and TED records merge only on an explicit publication ID. Governance and
procurement threads are confirmed by docket, explicit prior handling,
publication ID, or normalized entity plus organization. Topic similarity stays
an unconfirmed candidate. Absence from a bounded index never means removal.

## State and materiality

The first successful collection is a baseline and emits no events. Later runs
compare substantive hashes; fetch timestamps, ordering, and whitespace do not
create updates. Event and source-health ledgers are JSON Lines grouped by ISO
week. Raw HTML, PDFs, and API responses are not committed.

Narrative candidates are selected before YAMLGraph: disputes and health gaps,
confirmed transitions, near deadlines, cross-HVA recurrence, known value, then
effective date and stable event ID. Narrative output is capped at ten events;
the deterministic event-ledger appendix remains complete. YAMLGraph performs
one bounded summarization judgement and does not fetch, deduplicate, link,
rank, persist, or serialize source data.

## Source health

Every configured endpoint records attempted/succeeded counts, item count,
status, and normalized error codes. Endpoint failures remain visible and
prevent claims of complete healthy coverage. Empty results are reported as
empty rather than replaced with stale data.

## Development

Requires Python 3.12 or newer.

```sh
python -m pip install -e '.[dev]'
pytest
ruff check .
```

Unit tests are fixture-backed and make no live network calls. To run collection
or publication manually, use the GitHub Actions `workflow_dispatch` controls.
The collector can also consume prepared JSONL locally through `hva-collect`.

## Security boundary

Only public OSINT belongs here. Device probes, local profile paths, browser or
message extraction, personal data, secret values, and unbounded raw responses
are excluded. Actions use only the scoped default `GITHUB_TOKEN` with
`contents: write`; the weekly YAMLGraph step alone receives
`ANTHROPIC_API_KEY`. The unprotected publication repository uses direct bot
commits and no admin or protection-bypassing credential.

## Latest bulletin

<!-- latest-bulletin:start -->
No bulletin has been published yet.
<!-- latest-bulletin:end -->
