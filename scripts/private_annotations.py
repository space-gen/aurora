"""Keeps validated annotations in the private repository for a fixed time."""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

RETENTION_DAYS = 30


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def _write(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records), encoding="utf-8")


def seed(templates: Path, private: Path) -> None:
    """Adds today's public task records, keeping every annotation already stored privately."""
    private.mkdir(parents=True, exist_ok=True)
    for template in sorted(templates.glob("*.jsonl")):
        target = private / template.name
        stored = _records(target)
        known = {record.get("id") for record in stored}
        _write(target, stored + [record for record in _records(template) if record.get("id") not in known])


def _recent(record: dict, cutoff: str) -> bool:
    # Archive pictures can be years old, so age is the newest answer, or the capture time for unanswered tasks.
    answered = [str(item.get("timestamp", ""))[:10] for item in record.get("annotations") or [] if isinstance(item, dict)]
    return max(answered or [str((record.get("metadata") or {}).get("captured_at", ""))[:10]]) >= cutoff


def prune(private: Path, today: date, days: int = RETENTION_DAYS) -> None:
    """Drops records with no answer inside the retention window. Run only after a successful archive."""
    cutoff = (today - timedelta(days=days)).isoformat()
    for path in sorted(private.glob("*.jsonl")):
        _write(path, [record for record in _records(path) if _recent(record, cutoff)])


ANSWER_COUNT_TASKS = ("aia_193", "aia_211", "aia_304")
# Machine pre-annotations (ml/preannotate.py) never take one of the three places meant for people.
MACHINE_USERS = {"solarhub-preannotator"}


def answer_counts(private: Path, published: Path) -> None:
    """Publishes how many people answered each archive picture, so browsers can skip full ones.

    Counts only grow: a pruned record keeps the count it was last published with.
    """
    published.mkdir(parents=True, exist_ok=True)
    for task in ANSWER_COUNT_TASKS:
        target = published / f"{task}.json"
        counts = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
        for record in _records(private / f"{task}.jsonl"):
            users = {str(item.get("user", "")).lower() for item in record.get("annotations") or [] if isinstance(item, dict) and item.get("user")} - MACHINE_USERS
            if users and record.get("id"):
                counts[record["id"]] = max(counts.get(record["id"], 0), len(users))
        target.write_text(json.dumps(dict(sorted(counts.items())), separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    command, *paths = sys.argv[1:]
    if command == "seed":
        seed(Path(paths[0]), Path(paths[1]))
    elif command == "prune":
        prune(Path(paths[0]), date.today())
    elif command == "counts":
        answer_counts(Path(paths[0]), Path(paths[1]))
    else:
        sys.exit(f"unknown command: {command}")
