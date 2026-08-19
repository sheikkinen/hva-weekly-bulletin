# HVA Weekly Bulletin

Public GitHub Actions consumer deployment for YAMLGraph FR-824. The project will collect public Finnish wellbeing-services county governance, Hilma/TED procurement, and Market Court procurement-dispute events daily, then publish a source-linked weekly bulletin.

## Development

Requires Python 3.12 or newer.

```sh
python -m pip install -e '.[dev]'
pytest
ruff check .
```

The package uses a `src/` layout. Feature implementation begins with fixture-backed tests for normalized contracts, baseline/delta behavior, source health, and deterministic materiality.

## Boundaries

Only public OSINT sources belong here. Do not add device probes, local `~/Library` access, Safari, Messages, WhatsApp, Biome, Apple Intelligence, personal profile data, secret values, or unbounded raw source responses.
