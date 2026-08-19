import argparse
import json
from pathlib import Path

from pydantic import BaseModel

from .models import BulletinSummary, SourceEvent, SourceHealth, ThreadEdge
from .render import render_bulletin, update_readme_latest
from .storage import read_jsonl


class PublishResult(BaseModel):
    published: bool
    bulletin_path: Path | None = None


def publish_bulletin(
    root: Path,
    iso_week: str,
    events: list[SourceEvent],
    health: list[SourceHealth],
    edges: list[ThreadEdge],
    summary: BulletinSummary | None = None,
) -> PublishResult:
    if not events:
        return PublishResult(published=False)

    content = render_bulletin(iso_week, events, health, edges, summary)
    bulletin_path = root / f"bulletins/{iso_week}.md"
    bulletin_path.parent.mkdir(parents=True, exist_ok=True)
    if not bulletin_path.exists() or bulletin_path.read_text() != content:
        bulletin_path.write_text(content)

    readme_path = root / "README.md"
    if readme_path.exists():
        updated = update_readme_latest(readme_path.read_text(), content)
        if updated != readme_path.read_text():
            readme_path.write_text(updated)

    return PublishResult(published=True, bulletin_path=bulletin_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--week", required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--health", type=Path, required=True)
    parser.add_argument("--threads", type=Path, required=True)
    parser.add_argument("--graph-state", type=Path, required=True)
    args = parser.parse_args()
    graph_state = json.loads(args.graph_state.read_text())
    summary = BulletinSummary.model_validate(graph_state["bulletin"])
    result = publish_bulletin(
        args.root,
        args.week,
        read_jsonl(args.events, SourceEvent),
        read_jsonl(args.health, SourceHealth),
        read_jsonl(args.threads, ThreadEdge),
        summary,
    )
    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
