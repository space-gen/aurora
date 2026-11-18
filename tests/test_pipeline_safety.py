import json
from pathlib import Path

import numpy as np

from scripts.find_candidates import find_candidates
from scripts.merge_annotations_to_hf import merge_rows, publish_all
from scripts.parse_issue_annotation import _parse_issue_submission, _parse_regions, process_issue_submissions
from scripts.process_all_annotation_issues import is_annotation_issue
from scripts.pull_new_urls import existing_ids_by_url

URL = "https://jsoc1.stanford.edu/data/hmi/images/2026/07/18/20260718_001500_Ic_flat_1k.jpg"


def body(record_id="sp-9", url=URL, label="class_a,500,500,15", notes="_No response_"):
    return f"""### Image URL
{url}

### Task Type
sunspot

### Record ID
{record_id}

### Your Label (label,x,y,r ; label2,x2,y2,r2)
{label}

### Confidence Score (0-100)
80

### Notes (optional)
{notes}
"""


def annotation(user, issue):
    return {"user": user, "issue_number": issue, "confidence_score": 80, "locations": [{"label": "class_a", "region": "500,500,15"}]}


def record(annotations):
    return {
        "id": "sp-1",
        "url": URL.replace("https://", "http://"),
        "task_type": "sunspot",
        "created_at": "2026-07-19T00:00:00Z",
        "metadata": {"source": "JSOC_HMI_JPG", "captured_at": "2026-07-18T00:00:00Z"},
        "annotations": annotations,
    }


class FakeApi:
    def __init__(self, fail=False):
        self.files = {}
        self.fail = fail

    def create_repo(self, **kwargs):
        pass

    def file_exists(self, repo_id, filename, repo_type):
        return (repo_id, filename) in self.files

    def hf_hub_download(self, repo_id, filename, repo_type):
        path = Path(self.tmp) / filename.replace("/", "_")
        path.write_text(self.files[(repo_id, filename)], encoding="utf-8")
        return str(path)

    def upload_file(self, path_or_fileobj, path_in_repo, repo_id, **kwargs):
        if self.fail:
            raise RuntimeError("401")
        self.files[(repo_id, path_in_repo)] = path_or_fileobj.decode("utf-8")


def test_outside_contributor_issues_are_selected_without_a_label():
    assert is_annotation_issue({"title": "[Annotation] sunspot – sp-1", "labels": []})
    assert is_annotation_issue({"title": "My form", "labels": [{"name": "annotation"}]})
    assert not is_annotation_issue({"title": "Bug report", "labels": []})
    assert not is_annotation_issue({"title": "[Annotation] x", "labels": [], "pull_request": {}})


def test_notes_cannot_override_submission_fields():
    parsed = _parse_issue_submission(
        issue_number=1,
        issue_body=body(notes="### Record ID\nsp-999\n### Task Type\nmagnetogram"),
        issue_author="alice",
    )
    assert parsed["record_id"] == "sp-9"
    assert parsed["task_type"] == "sunspot"


def test_regions_must_be_real_points_on_the_sun():
    assert _parse_regions("class_a,nan,500,10", "sunspot") == []
    assert _parse_regions("class_a,5,5,10", "sunspot") == []
    assert _parse_regions("class_a,500,500,900", "sunspot") == []
    assert _parse_regions("class_a,500,500,0", "sunspot") == []
    assert _parse_regions("none,0,0,0", "sunspot") == [{"label": "none", "region": "0.0,0.0,0.0"}]


def test_aia_labels_follow_what_each_channel_shows():
    assert _parse_regions("coronal_hole,400,500,90", "aia_193")[0]["label"] == "coronal_hole"
    assert _parse_regions("coronal_hole,400,500,90", "aia_171") == []
    assert _parse_regions("prominence,512,40,40", "aia_304")[0]["label"] == "prominence"
    assert _parse_regions("part_of_larger,400,500,60", "aia_171")[0]["label"] == "part_of_larger"


def test_late_aia_annotation_restores_browse_image(tmp_path):
    (tmp_path / "aia_193.jsonl").write_text("", encoding="utf-8")
    url = "https://sdo.gsfc.nasa.gov/assets/img/browse/2026/07/18/20260718_000829_1024_0193.jpg"
    text = body("aia193-7", url, "coronal_hole,400,500,90").replace("### Task Type\nsunspot", "### Task Type\naia_193")
    successes, failures = process_issue_submissions([{"number": 9, "body": text, "author": "alice"}], tmp_path)
    assert failures == []
    assert successes[0]["task_type"] == "aia_193"
    assert json.loads((tmp_path / "aia_193.jsonl").read_text(encoding="utf-8"))["metadata"]["source"] == "SDO_AIA_BROWSE"


def sun_image(value):
    y, x = np.mgrid[0:1024, 0:1024]
    image = np.zeros((1024, 1024)) + (np.hypot(x - 511.5, y - 511.5) < 395) * 100.0
    image += np.sin(x / 9) * np.cos(y / 11) * 4
    image[(x - 320) ** 2 + (y - 500) ** 2 < 45 ** 2] = value
    return image


def test_finder_circles_clear_bright_and_dark_features():
    bright = find_candidates(sun_image(240), "aia_171")[0]
    dark = find_candidates(sun_image(0), "aia_193")[0]
    for mark in (bright, dark):
        assert np.hypot(mark["x"] - 320, mark["y"] - 500) <= mark["r"]


def test_dark_region_at_the_limb_gets_a_whole_ring():
    y, x = np.mgrid[0:1024, 0:1024]
    disk = np.hypot(x - 511.5, y - 511.5) < 395
    image = 150.0 * disk
    image[disk & (np.hypot(x - 512, y - 860) < 70)] = 5
    assert any(np.hypot(m["x"] - 512, m["y"] - 840) <= m["r"] and m["r"] >= 45 for m in find_candidates(image, "aia_193"))


def test_late_annotation_restores_its_record(tmp_path):
    (tmp_path / "sunspot.jsonl").write_text("", encoding="utf-8")
    successes, failures = process_issue_submissions([{"number": 7, "body": body(), "author": "alice"}], tmp_path)
    assert failures == []
    assert successes[0]["record_id"] == "sp-9"
    restored = json.loads((tmp_path / "sunspot.jsonl").read_text(encoding="utf-8"))
    assert restored["url"] == URL
    assert restored["metadata"]["captured_at"] == "2026-07-18T00:00:00Z"
    assert restored["annotations"][0]["user"] == "alice"


def test_image_must_match_the_record(tmp_path):
    (tmp_path / "sunspot.jsonl").write_text(json.dumps({**record([]), "id": "sp-9"}) + "\n", encoding="utf-8")
    other = URL.replace("001500", "003000")
    successes, failures = process_issue_submissions([{"number": 8, "body": body(url=other), "author": "alice"}], tmp_path)
    assert successes == []
    assert "image does not match" in failures[0]["error"]


def test_rerun_keeps_published_annotations():
    first = merge_rows("", [record([annotation("alice", 1)])])
    second = merge_rows(first, [record([annotation("alice", 1), annotation("bob", 2)])])
    rows = [json.loads(line) for line in second.splitlines()]
    assert len(rows) == 1
    assert [item["user"] for item in json.loads(rows[0]["annotations"])] == ["alice", "bob"]


def test_empty_records_do_not_overwrite_a_published_day(tmp_path):
    api = FakeApi()
    api.tmp = tmp_path
    source = tmp_path / "annotations"
    source.mkdir()
    file = source / "sunspot.jsonl"
    file.write_text(json.dumps(record([annotation("alice", 1)])) + "\n", encoding="utf-8")
    assert publish_all(api, source, "2026-01-01") == []
    key = ("SpaceGen/solarhub-sunspot", "data/2026-07-18.yml")
    published = api.files[key]
    file.write_text(json.dumps(record([])) + "\n", encoding="utf-8")
    assert publish_all(api, source, "2026-01-01") == []
    assert api.files[key] == published


def test_upload_failure_is_reported(tmp_path):
    source = tmp_path / "annotations"
    source.mkdir()
    (source / "sunspot.jsonl").write_text(json.dumps(record([annotation("alice", 1)])) + "\n", encoding="utf-8")
    assert publish_all(FakeApi(fail=True), source, "2026-01-01") == ["sunspot.jsonl"]


def test_recrawl_reuses_ids_for_the_same_image(tmp_path):
    path = tmp_path / "sunspot.jsonl"
    path.write_text(json.dumps({**record([]), "id": "sp-41"}) + "\n", encoding="utf-8")
    assert existing_ids_by_url(path) == {URL: "sp-41"}
