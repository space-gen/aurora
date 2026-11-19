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


def prune(private: Path, today: date, days: int = RETENTION_DAYS) -> None:
    """Drops records older than the retention window. Run only after a successful archive."""
    cutoff = (today - timedelta(days=days)).isoformat()
    for path in sorted(private.glob("*.jsonl")):
        _write(path, [record for record in _records(path) if str((record.get("metadata") or {}).get("captured_at", ""))[:10] >= cutoff])


if __name__ == "__main__":
    command, *paths = sys.argv[1:]
    if command == "seed":
        seed(Path(paths[0]), Path(paths[1]))
    elif command == "prune":
        prune(Path(paths[0]), date.today())
    else:
        sys.exit(f"unknown command: {command}")
