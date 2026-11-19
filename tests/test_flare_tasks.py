import json
from datetime import datetime, timezone

import numpy as np

from scripts.flare_tasks import full_noaa, nearest_url, regions_at
from scripts.parse_issue_annotation import _parse_regions, process_issue_submissions
from scripts.science_dataset import CHANNELS, build_catalogue, ephemeris, pixel_from_stonyhurst, solar_coordinates

PEAK = "https://sdo.gsfc.nasa.gov/assets/img/browse/2026/10/05/20261005_224556_1024_0131.jpg"


def flare_task(annotations=None):
    return {
        "id": "flare-0123456789", "url": PEAK, "task_type": "flare_source",
        "metadata": {
            "captured_at": "2026-10-05T22:47:00Z",
            "before_url": PEAK.replace("224556", "222520"),
            "flare": {"catalogue_id": "ivo://x/FL_SWPC_1", "goes_class": "C1.2", "start": "2026-10-05T22:42:00Z", "peak": "2026-10-05T22:47:00Z", "end": "2026-10-05T22:50:00Z"},
            "candidates": [{"x": 405, "y": 485, "r": 40, "noaa": 14549}, {"x": 787, "y": 439, "r": 40, "noaa": 14547}],
            "other_catalogues": [{"catalogue": "SSW Latest Events", "noaa": 14549, "hpc_x": -229.5, "hpc_y": 62.3}],
        },
        "annotations": annotations or [],
    }


def body(label):
    return f"""### Image URL
{PEAK}

### Task Type
flare_source

### Record ID
flare-0123456789

### Your Label (label,x,y,r ; label2,x2,y2,r2)
{label}

### Confidence Score (0-100)
80
"""


def test_sky_and_solar_coordinates_invert_each_other():
    channel, sun = CHANNELS["aia_131"], ephemeris(datetime(2026, 10, 5, 22, tzinfo=timezone.utc))
    x, y = pixel_from_stonyhurst(12.0, -20.0, channel, sun)
    back = solar_coordinates(np.array([x]), np.array([y]), channel, sun)
    assert abs(back["latitude"][0] - 12) < 1e-6 and abs(back["longitude"][0] + 20) < 1e-6
    assert pixel_from_stonyhurst(0, 120, channel, sun) is None


def test_region_positions_rotate_to_the_flare_time():
    seen = {"ar_noaanum": 14549, "hpc_x": -300.0, "hpc_y": 60.0, "event_starttime": "2026-10-05T00:00:00", "event_endtime": "2026-10-05T23:59:59"}
    place = regions_at([seen], datetime(2026, 10, 5, 22, 47, tzinfo=timezone.utc))[0]
    assert place["noaa"] == 14549 and place["x"] > 511.5 - 300 / 2.4


def test_helpers_pick_close_frames_and_full_region_numbers():
    frames = [PEAK, PEAK.replace("224556", "203000")]
    assert nearest_url(frames, datetime(2026, 10, 5, 22, 47, tzinfo=timezone.utc)) == PEAK
    assert nearest_url(frames, datetime(2026, 10, 6, 3, tzinfo=timezone.utc)) is None
    assert full_noaa(4549) == 14549 and full_noaa(14549) == 14549 and full_noaa(0) is None


def test_flare_labels_are_checked():
    assert _parse_regions("noaa_14549,405,485,40", "flare_source")[0]["label"] == "noaa_14549"
    assert _parse_regions("behind_limb,0,0,0", "flare_source")[0]["label"] == "behind_limb"
    assert _parse_regions("noaa_99,405,485,40", "flare_source") == []
    assert _parse_regions("coronal_loops,405,485,40", "flare_source") == []


def test_region_must_be_one_that_was_offered(tmp_path):
    (tmp_path / "flare_source.jsonl").write_text(json.dumps(flare_task()) + "\n", encoding="utf-8")
    good, _ = process_issue_submissions([{"number": 1, "body": body("noaa_14549,405,485,40"), "author": "ana"}], tmp_path)
    _, bad = process_issue_submissions([{"number": 2, "body": body("noaa_14600,405,485,40"), "author": "bo"}], tmp_path)
    assert good and "offered" in bad[0]["error"]


def test_flare_catalogue_gives_a_majority_region_without_names():
    answers = [{"user": user, "locations": [{"label": label, "region": region}]} for user, label, region in (
        ("ana", "noaa_14549", "405.0,485.0,40.0"), ("bo", "noaa_14549", "407.0,480.0,40.0"), ("cy", "noaa_14547", "787.0,439.0,40.0"))]
    _, flares, summary = build_catalogue("flare_source", [flare_task(answers)])
    flare = flares[0]
    assert flare["noaa_number"] == 14549 and flare["n_annotators"] == 3 and flare["attribution_agreement"] == round(2 / 3, 4)
    assert flare["stonyhurst_latitude_deg"] is not None and summary["agreement_with_ssw_latest_events"] == 1
    assert '"ana"' not in json.dumps(flares)
