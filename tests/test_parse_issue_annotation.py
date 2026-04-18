import json

from scripts.parse_issue_annotation import (
    _parse_issue_body,
    _parse_regions,
    circle_to_rle,
    process_issue_submissions,
)


def test_parse_issue_body_basic():
    body = """
### Task Type
Sunspot

### Record ID
sp-2189

### Your label
class_a,100,100,10

### Confidence score
85%
"""
    fields = _parse_issue_body(body)
    assert fields["task_type"].lower() == "sunspot"
    assert fields["record_id"] == "sp-2189"
    assert "your_label" in fields


def test_parse_regions_circle_to_region():
    regions = _parse_regions("class_a,100,100,10", task_type="sunspot")
    assert len(regions) == 1
    r = regions[0]
    assert r["label"] == "class_a"
    assert "region" in r
    parts = r["region"].split(',')
    assert len(parts) == 3


def test_parse_regions_rle_passthrough_to_region():
    rle_str = "0 10 100 5"
    regions = _parse_regions(f"class_a,{rle_str}", task_type="sunspot")
    assert len(regions) == 1
    assert "region" in regions[0]
    assert regions[0]["region"] == rle_str


def test_circle_to_rle_out_of_bounds():
    # Circle outside the 1024x1024 should return empty string
    rle = circle_to_rle(-100.0, -100.0, 5.0)
    assert rle == ""


def test_bulk_processing_updates_once_per_file(tmp_path):
    annotations_dir = tmp_path / "annotations"
    annotations_dir.mkdir()
    sample = {
        "id": "sp-1",
        "url": "https://example/sp-1.jpg",
        "task_type": "sunspot",
        "created_at": "2026-01-01T00:00:00Z",
        "metadata": {"source": "test", "captured_at": "2026-01-01T00:00:00Z"},
        "annotations": [],
    }
    with open(annotations_dir / "sunspot.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(sample, separators=(",", ":")) + "\n")

    body1 = """
### Task Type
sunspot

### Record ID
sp-1

### Your Label (label,x,y,r ; label2,x2,y2,r2)
class_a,100,100,10

### Confidence Score (0-100)
90
"""
    body2 = """
### Task Type
sunspot

### Record ID
sp-1

### Your Label (label,x,y,r ; label2,x2,y2,r2)
class_b,120,120,8

### Confidence Score (0-100)
85
"""
    successes, failures = process_issue_submissions(
        [
            {"number": 101, "body": body1, "author": "alice"},
            {"number": 102, "body": body2, "author": "bob"},
        ],
        annotations_dir=annotations_dir,
    )

    assert len(successes) == 2
    assert failures == []

    lines = (annotations_dir / "sunspot.jsonl").read_text(encoding="utf-8").strip().splitlines()
    updated = json.loads(lines[0])
    assert len(updated["annotations"]) == 2
    assert {a["user"] for a in updated["annotations"]} == {"alice", "bob"}


def test_duplicate_user_same_record_rejected(tmp_path):
    annotations_dir = tmp_path / "annotations"
    annotations_dir.mkdir()
    sample = {
        "id": "mg-1",
        "url": "https://example/mg-1.jpg",
        "task_type": "magnetogram",
        "created_at": "2026-01-01T00:00:00Z",
        "metadata": {"source": "test", "captured_at": "2026-01-01T00:00:00Z"},
        "annotations": [
            {
                "user": "alice",
                "confidence_score": 90.0,
                "locations": [{"label": "alpha", "region": "10,10,5"}],
                "issue_number": 1,
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        ],
    }
    with open(annotations_dir / "magnetogram.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(sample, separators=(",", ":")) + "\n")

    body = """
### Task Type
magnetogram

### Record ID
mg-1

### Your Label (label,x,y,r ; label2,x2,y2,r2)
beta,20,20,6

### Confidence Score (0-100)
95
"""
    successes, failures = process_issue_submissions(
        [{"number": 2, "body": body, "author": "Alice"}],
        annotations_dir=annotations_dir,
    )

    assert successes == []
    assert len(failures) == 1
    assert "already annotated record mg-1" in failures[0]["error"]
