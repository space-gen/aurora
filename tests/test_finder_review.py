import json
from pathlib import Path

import numpy as np

from scripts.find_candidates import decode_mask, encode_mask
from scripts.finder_review import review_rows, tally
from scripts.merge_annotations_to_hf import publish_all
from scripts.parse_issue_annotation import _parse_issue_submission, _parse_review, process_issue_submissions

URL = "https://sdo.gsfc.nasa.gov/assets/img/browse/2026/11/17/20261117_115558_1024_0171.jpg"
FINDER = [300, 400, 40]


def ring(action="confirmed", label="coronal_loops", finder=FINDER, **extra):
    return {"action": action, "label": label, "finder": finder, "ring": [300, 400, 40], **extra}


def review(*rings):
    return {"v": 1, "part": 2, "parts": 9, "rings": list(rings)}


def body(payload):
    return f"""### Image URL
{URL}

### Task Type
aia_171

### Record ID
aia171-1

### Your Label (label,x,y,r ; label2,x2,y2,r2)
coronal_loops,300,400,40

### Confidence Score (0-100)
80

### Finder Review
{json.dumps(payload)}

### Notes (optional)
_No response_
"""


def task(candidates=None):
    return {"id": "aia171-1", "url": URL, "task_type": "aia_171", "metadata": {"captured_at": "2026-11-17T00:00:00Z", "candidates": candidates or [{"x": 300, "y": 400, "r": 40}]}, "annotations": []}


def test_review_rejects_bad_shapes_and_keeps_good_ones():
    good = review(ring(), ring("deleted", None), ring("added", "bright_region", None, outline=[[1, 1], [20, 1], [20, 20]]))
    assert len(_parse_review(json.dumps(good), "aia_171")["rings"]) == 3
    for bad in [
        review(ring("hacked")),
        review(ring(label="sunspot")),
        review(ring("added")),
        review(ring("confirmed", finder=None)),
        review(ring("deleted")),
        review(ring(outline=[[1, 1], [2, 2]])),
        review(ring(outline=[[1, 1], [2, 2], [9999, 3]])),
        {**review(ring()), "part": 10},
    ]:
        assert _parse_review(json.dumps(bad), "aia_171") is None
    assert _parse_review("not json", "aia_171") is None


def test_bad_review_does_not_lose_the_annotation():
    parsed = _parse_issue_submission(issue_number=4, issue_body=body(review(ring("hacked"))), issue_author="ana")
    assert parsed["annotation"]["locations"]
    assert "review" not in parsed["annotation"]


def test_only_rings_published_by_the_finder_are_verified(tmp_path):
    (tmp_path / "aia_171.jsonl").write_text(json.dumps(task()) + "\n", encoding="utf-8")
    payload = review(ring(), ring(finder=[1, 2, 3]))
    payload["rings"][1]["finder"] = [500, 500, 30]
    successes, failures = process_issue_submissions([{"number": 4, "body": body(payload), "author": "ana"}], tmp_path)
    assert failures == [] and successes
    saved = json.loads((tmp_path / "aia_171.jsonl").read_text(encoding="utf-8"))
    assert [item["finder_verified"] for item in saved["annotations"][0]["review"]["rings"]] == [True, False]


def test_review_keeps_finder_and_human_shapes_for_comparison(tmp_path):
    ys, xs = np.mgrid[380:420, 280:320]
    mask = encode_mask(xs.ravel(), ys.ravel())
    (tmp_path / "aia_171.jsonl").write_text(json.dumps(task([{"x": 300, "y": 400, "r": 40, "mask": mask}])) + "\n", encoding="utf-8")
    drawn = [[270, 370], [340, 370], [340, 430], [270, 430]]
    payload = review(ring("outlined", outline=drawn, part_of_larger=True), ring("merged", "part_of_larger"), ring())
    successes, failures = process_issue_submissions([{"number": 4, "body": body(payload), "author": "ana"}], tmp_path)
    assert failures == [] and successes
    record = json.loads((tmp_path / "aia_171.jsonl").read_text(encoding="utf-8"))
    rows = review_rows([record], "aia_171", "2026-11-17")
    assert rows[0]["part_of_larger"] is True and rows[0]["finder_mask"] == mask
    assert decode_mask(rows[0]["mask"])[400, 335]
    assert rows[1]["action"] == "merged"
    assert rows[2]["mask"] == mask
    stats = tally(rows)
    assert stats["shapes_redrawn"] == 1
    assert 0 < stats["finder_shape_overlap_median"] < 1


def row(action, user="ana", finder=(300, 400, 40), verified=True, label="plage"):
    return {"review_id": f"{user}-{action}", "image_url": URL, "contributor": user, "action": action, "label": label, "finder_x": finder[0], "finder_y": finder[1], "finder_r": finder[2], "finder_verified": verified}


def test_tally_scores_finder_against_people():
    rows = [
        row("confirmed"), row("moved", finder=(1, 1, 9)), row("outlined", finder=(2, 2, 9)),
        row("rejected", finder=(3, 3, 9)), row("deleted", "bo"), row("added", finder=(None, None, None), verified=False),
        row("confirmed", finder=(8, 8, 9), verified=False),
    ]
    stats = tally(rows)
    assert stats["rings_reviewed"] == 5
    assert stats["finder_precision"] == 0.6
    assert stats["rings_corrected_share"] == round(2 / 3, 4)
    assert stats["human_added_share"] == 0.25
    assert stats["reviewer_agreement"] == 0
    assert stats["rows_not_matched_to_finder"] == 1


class Api:
    def __init__(self, tmp, fail=False):
        self.tmp, self.fail, self.files, self.commits = Path(tmp), fail, {}, 0

    def create_repo(self, **kwargs):
        pass

    def repo_exists(self, repo_id, repo_type):
        return any(repo == repo_id for repo, _ in self.files)

    def update_repo_settings(self, repo_id, repo_type, private):
        self.private = {*getattr(self, "private", set()), repo_id}

    def list_repo_files(self, repo_id, repo_type):
        return [path for repo, path in self.files if repo == repo_id]

    def file_exists(self, repo_id, filename, repo_type):
        return (repo_id, filename) in self.files

    def hf_hub_download(self, repo_id, filename, repo_type):
        target = self.tmp / filename.replace("/", "_")
        target.write_text(self.files[(repo_id, filename)], encoding="utf-8")
        return str(target)

    def upload_folder(self, folder_path, repo_id, repo_type, commit_message):
        if self.fail:
            raise RuntimeError("offline")
        self.commits += 1
        for path in Path(folder_path).rglob("*"):
            if path.is_file():
                self.files[(repo_id, path.relative_to(folder_path).as_posix())] = path.read_text(encoding="utf-8")


def published_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "aia_171.jsonl").write_text(json.dumps(task()) + "\n", encoding="utf-8")
    process_issue_submissions([{"number": 4, "body": body(review(ring(), ring("added", "bright_region", None))), "author": "ana"}], source)
    return source


def test_publish_keeps_raw_data_private_and_science_data_clean(tmp_path):
    api, source = Api(tmp_path), published_source(tmp_path)
    assert publish_all(api, source, "2026-01-01") == []
    repo = "SpaceGen/solarhub-aia-171"
    assert ("SpaceGen/solarhub-archive", "annotations/aia_171/2026-11-17.jsonl") in api.files
    public = {path: text for (name, path), text in api.files.items() if name == repo}
    assert "observations/2026-11-17.jsonl" in public and "README.md" in public and "stats/manifest.json" in public
    assert any(path.startswith("features/") for path in public)
    combined = "\n".join(text for path, text in public.items() if path.endswith(".jsonl"))
    for private_word in ('"ana"', '"user"', "issue_number", "confidence_score", "finder", '"ring"', '"part"'):
        assert private_word not in combined
    commits = api.commits
    assert publish_all(api, source, "2026-01-01") == []
    assert api.commits == commits
    assert repo in api.private
