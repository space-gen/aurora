import json
from datetime import date

from scripts.private_annotations import answer_counts, prune, seed


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


def test_old_archive_picture_answered_recently_is_kept(tmp_path):
    write(tmp_path / "aia_193.jsonl", [
        {"id": "aia193-20170101000000", "metadata": {"captured_at": "2017-01-01T00:00:00Z"}, "annotations": [{"user": "ana", "timestamp": "2026-11-15T10:00:00+00:00"}]},
        {"id": "aia193-20170102000000", "metadata": {"captured_at": "2017-01-02T00:00:00Z"}, "annotations": [{"user": "bo", "timestamp": "2026-09-01T10:00:00+00:00"}]},
    ])
    prune(tmp_path, date(2026, 11, 19))
    assert [record["id"] for record in read(tmp_path / "aia_193.jsonl")] == ["aia193-20170101000000"]


def test_answer_counts_count_people_and_never_shrink(tmp_path):
    private, published = tmp_path / "private", tmp_path / "published"
    private.mkdir()
    write(private / "aia_193.jsonl", [
        {"id": "a", "annotations": [{"user": "Ana"}, {"user": "ana"}, {"user": "bo"}]},
        {"id": "b", "annotations": []},
    ])
    published.mkdir()
    (published / "aia_193.json").write_text('{"gone": 3}', encoding="utf-8")
    answer_counts(private, published)
    assert json.loads((published / "aia_193.json").read_text(encoding="utf-8")) == {"a": 2, "gone": 3}
    assert json.loads((published / "aia_211.json").read_text(encoding="utf-8")) == {}
