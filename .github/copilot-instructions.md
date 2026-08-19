# HVA Weekly Bulletin Instructions

- Use Python 3.12+, a `src/` package layout, Pydantic v2, pytest, and Ruff.
- Follow YAMLGraph FR-824 and its judgement as the implementation contract.
- Keep the repository public-data-only. Never add device probes, local `~/Library` access, personal profiles, secret values, or unbounded raw source responses.
- Implement with fixture-backed RED tests before production code.
- Normalize source data at typed Pydantic boundaries before persistence.
- Keep stable IDs, hashing, delta detection, health persistence, materiality ordering, thread linking, and Markdown rendering deterministic and LLM-free.
- Use YAMLGraph only for the bounded weekly summarization judgement.
- Do not infer removals from bounded or top-N source indexes.
- Topic similarity may propose a thread edge but must never confirm one.
- Stage workflow output only from the explicitly authorized state, events, source_health, and bulletins paths.
- Do not add branch protection, PATs, admin credentials, notifications, dashboards, hosted APIs, or sources outside HVA governance, Hilma/TED, and MAO.
