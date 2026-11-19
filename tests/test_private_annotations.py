import json
from datetime import date

from scripts.private_annotations import prune, seed


def write(path, records):
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_seed_adds_new_tasks_without_touching_stored_annotations(tmp_path):
    public, private = tmp_path / "public", tmp_path / "private"
    public.mkdir(), private.mkdir()
    write(public / "aia_171.jsonl", [{"id": "a", "annotations": []}, {"id": "b", "annotations": []}])
    write(private / "aia_171.jsonl", [{"id": "a", "annotations": [{"user": "ana"}]}])
    seed(public, private)
    assert read(private / "aia_171.jsonl") == [{"id": "a", "annotations": [{"user": "ana"}]}, {"id": "b", "annotations": []}]


def test_prune_keeps_only_the_retention_window(tmp_path):
    write(tmp_path / "aia_171.jsonl", [
        {"id": "old", "metadata": {"captured_at": "2026-09-01T00:00:00Z"}},
        {"id": "new", "metadata": {"captured_at": "2026-11-10T00:00:00Z"}},
    ])
    prune(tmp_path, date(2026, 11, 19))
    assert [record["id"] for record in read(tmp_path / "aia_171.jsonl")] == ["new"]
