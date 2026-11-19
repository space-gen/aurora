import numpy as np

from ml.preannotate import (
    CLASSES, FINDER_LABEL, PREANNOTATOR, answer_row, archive_id, crop_view, decide, filament_candidates,
    flare_annotation, frame_url, location, noon_frame, training_pair,
)
from scripts.parse_issue_annotation import FLARE_REGION, VALID_LABELS, _parse_regions

NAME = "20261117_110805_1024_0193.jpg"


def quiet_sun() -> np.ndarray:
    yy, xx = np.mgrid[:1024, :1024]
    return np.where(np.hypot(xx - 511.5, yy - 511.5) < 395, 120.0, 0.0)


def test_ids_and_urls_match_solarhub_archive_tasks():
    assert archive_id(NAME) == "aia193-20261117110805"
    assert frame_url(NAME) == "https://sdo.gsfc.nasa.gov/assets/img/browse/2026/11/17/20261117_110805_1024_0193.jpg"
    names = ("20261117_000005_1024_0193.jpg", "20261117_115905_1024_0211.jpg", NAME)
    assert noon_frame(names, "0193") == NAME


def test_filament_finder_keeps_thin_dark_threads_and_skips_blobs():
    gray = quiet_sun()
    gray[500:504, 380:540] = 60
    yy, xx = np.mgrid[:1024, :1024]
    gray[np.hypot(xx - 650, yy - 650) < 18] = 60
    marks = filament_candidates(gray)
    assert marks, "the thread should be proposed"
    assert all(abs(mark["y"] - 502) < 10 for mark in marks)
    assert any(abs(mark["x"] - 460) < 15 for mark in marks)
    assert not any(np.hypot(mark["x"] - 650, mark["y"] - 650) < 30 for mark in marks)


def test_decide_needs_agreement_or_a_sure_model():
    mark = {"x": 400, "y": 400, "r": 60, "score": 4.0, "expected": "coronal_hole", "finder": "aurora"}
    kept = decide(mark, {"coronal_hole": 0.7, "filament": 0.1, "none": 0.2}, {"coronal_hole"})
    assert kept["label"] == "coronal_hole" and kept["confidence"] > 60
    assert decide(mark, {"coronal_hole": 0.2, "filament": 0.1, "none": 0.7}, None) is None
    assert decide(mark, {"coronal_hole": 0.1, "filament": 0.6, "none": 0.3}, None) is None
    assert decide(mark, {"coronal_hole": 0.05, "filament": 0.9, "none": 0.05}, None)["label"] == "filament"
    unchecked = decide(mark, {"coronal_hole": 0.7, "filament": 0.1, "none": 0.2}, None)
    assert unchecked["confidence"] < kept["confidence"]


def test_answers_are_valid_volunteer_answers():
    for task in CLASSES:
        mark = {"x": 300, "y": 520, "r": 50, "score": 3.0, "expected": FINDER_LABEL[task], "finder": "aurora"}
        verdict = decide(mark, {label: (0.9 if label == FINDER_LABEL[task] else 0.1 / 3) for label in ("coronal_hole", "filament", "prominence", "bright_region", "none") if label in VALID_LABELS[task]}, None)
        for spots in ([location(mark, verdict)], []):
            row = answer_row(task, NAME.replace("0193", f"{int(task[4:]):04d}"), spots)
            annotation = row["annotations"][0]
            assert annotation["user"] == PREANNOTATOR and annotation["machine"] is True
            text = ";".join(f"{spot['label']},{spot['region']}" for spot in annotation["locations"])
            assert [spot["label"] for spot in _parse_regions(text, task)] == [spot["label"] for spot in annotation["locations"]]


def test_training_masks_use_confident_answers_only():
    spots = [
        {"label": "coronal_hole", "region": "512,512,100", "confidence": 80.0},
        {"label": "filament", "region": "512,512,20", "confidence": 90.0},
        {"label": "filament", "region": "200,512,30", "confidence": 40.0},
    ]
    image, mask = training_pair(quiet_sun(), spots, "aia_193")
    assert image.shape == mask.shape == (512, 512)
    assert mask[256, 256] == CLASSES["aia_193"].index("filament") + 1
    assert mask[256, 300] == CLASSES["aia_193"].index("coronal_hole") + 1
    assert mask[256, 100] == 0


def test_crop_view_is_square_and_marked():
    view = crop_view(quiet_sun(), {"x": 1000, "y": 20, "r": 30})
    assert view.size == (448, 448)
    assert (np.asarray(view)[:, :, 0] == 255).any()


def test_flare_answers_name_the_offered_region():
    record = {"metadata": {"nearest_region_auto": 14549, "flash": {"x": 410, "y": 480, "clarity": 2.4}}}
    spot = flare_annotation(record)["locations"][0]
    assert FLARE_REGION.match(spot["label"]) and spot["region"] == "410,480,40"
    record["metadata"]["nearest_region_auto"] = None
    assert flare_annotation(record)["locations"][0]["label"] == "unnumbered_region"
