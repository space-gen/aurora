import json
from datetime import datetime, timezone

import numpy as np

from scripts.find_candidates import encode_mask
from scripts.science_dataset import CHANNELS, build_catalogue, ephemeris, krippendorff_alpha, observation_time, solar_coordinates

URL = "https://sdo.gsfc.nasa.gov/assets/img/browse/2026/11/17/20261117_115558_1024_0171.jpg"


def outline(x, y, size=40):
    return [[x, y], [x + size, y], [x + size, y + size], [x, y + size]]


def annotation(user, rings):
    return {"user": user, "issue_number": 7, "confidence_score": 80, "review": {"v": 1, "part": 5, "parts": 9, "rings": rings}}


def ring(label, x=500, action="outlined", **extra):
    return {"action": action, "label": label, "finder": [x, 500, 30], "ring": [x + 20, 520, 30], "outline": outline(x, 500), **extra}


def test_time_comes_from_the_image_name():
    assert observation_time(URL) == datetime(2026, 11, 17, 11, 55, 58, tzinfo=timezone.utc)


def test_disk_centre_maps_to_the_sub_observer_point():
    channel = CHANNELS["aia_171"]
    sun = ephemeris(datetime(2026, 3, 20, tzinfo=timezone.utc))
    point = solar_coordinates(np.array([511.5]), np.array([511.5]), channel, sun)
    assert abs(point["latitude"][0] - sun["b0_deg"]) < 1e-6
    assert abs(point["longitude"][0]) < 1e-6
    assert abs(point["mu"][0] - 1) < 1e-6


def test_points_beyond_the_limb_have_no_solar_position():
    channel = CHANNELS["aia_171"]
    point = solar_coordinates(np.array([1000.0]), np.array([511.5]), channel, ephemeris(datetime(2026, 1, 1, tzinfo=timezone.utc)))
    assert not point["on_disk"][0]


def test_majority_feature_has_agreement_and_no_private_fields():
    record = {"url": URL, "annotations": json.dumps([
        annotation("ana", [ring("bright_region")]),
        annotation("bo", [ring("bright_region")]),
        annotation("cy", [ring("coronal_loops")]),
    ])}
    observations, features, summary = build_catalogue("aia_171", [record])
    feature = features[0]
    assert feature["feature_class"] == "bright_region" and feature["n_annotators"] == 3
    assert feature["class_agreement"] == round(2 / 3, 4) and feature["shape_agreement_iou"] == 1
    assert feature["area_millionths_hemisphere"] > 0 and feature["mask_rle"]["size"] == [1024, 1024]
    assert 0 < observations[0]["reviewed_disk_fraction"] < 1
    assert "ana" in feature["annotators"]
    # Usernames are credited only in the annotators column.
    text = json.dumps([observations, [{key: value for key, value in row.items() if key != "annotators"} for row in features], summary])
    assert not any(word in text for word in ('"ana"', "issue_number", "confidence_score", "finder", '"ring"', '"user"'))


def test_rejected_regions_are_not_catalogued():
    deleted = ring("x", action="deleted")
    deleted.update(label=None)
    deleted.pop("outline")
    record = {"url": URL, "annotations": [annotation("ana", [deleted])]}
    _, features, summary = build_catalogue("aia_171", [record])
    assert features == [] and summary["excluded"]["regions_rejected_or_unclassified"] == 1


def test_circles_do_not_claim_a_measured_shape():
    record = {"url": URL, "annotations": [{"user": "ana", "locations": [{"label": "bright_region", "region": "500.0,500.0,30.0"}]}]}
    feature = build_catalogue("aia_171", [record])[1][0]
    assert feature["geometry_source"] == "circle" and feature["mask_rle"] is None
    assert feature["area_millionths_hemisphere"] is None and "approximate_circle" in feature["quality_flags"]


def test_detector_mask_is_used_when_an_annotator_accepts_it():
    ys, xs = np.mgrid[500:530, 500:540]
    item = {"action": "confirmed", "label": "bright_region", "finder": [520, 515, 30], "ring": [520, 515, 30], "finder_mask": encode_mask(xs.ravel(), ys.ravel())}
    feature = build_catalogue("aia_171", [{"url": URL, "annotations": [annotation("ana", [item])]}])[1][0]
    assert feature["geometry_source"] == "detector_mask" and feature["bbox_pixel"] == [500, 500, 40, 30]


def test_alpha_rewards_agreement_beyond_chance():
    assert krippendorff_alpha([["a", "a"], ["b", "b"]]) == 1
    assert krippendorff_alpha([["a", "b"], ["b", "a"]]) < 0
    assert krippendorff_alpha([["a"]]) is None
