"""Builds science-ready solar feature catalogues from validated volunteer annotations."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from statistics import median
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

try:
    from scripts.find_candidates import SIZE, encode_mask
    from scripts.finder_review import polygon_mask, ring_mask
except ModuleNotFoundError:
    from find_candidates import SIZE, encode_mask
    from finder_review import polygon_mask, ring_mask

SCHEMA_VERSION = "1.0.0"
SOLAR_RADIUS_M = 6.957e8
AU_M = 1.495978707e11
ARCSEC_PER_RADIAN = 206264.806
MIN_MU = 0.1
LIMB_MU = 0.3
SAME_FEATURE_OVERLAP = 0.5
SECTION_GRID = 3
SECTION_START = 96
SECTION_STEP = 208
SECTION_SIZE = 416
SPLITS = {0: "train", 1: "train", 2: "train", 3: "validation", 4: "test"}
TIME_PATTERN = re.compile(r"/(\d{8})_(\d{6})_")
CIRCLE_PATTERN = re.compile(r"^\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*$")
NOT_A_FEATURE = "not_a_feature"
UNCLASSIFIED = "unclassified"
MORPHOLOGY = "SolarHub morphology v1"
AIA = {"instrument": "SDO/AIA", "plate_scale": 2.4, "center": (511.5, 511.5), "scheme": MORPHOLOGY}
# Measured from the solar limb in HMI 1k images across 2026.
HMI = {"instrument": "SDO/HMI", "plate_scale": 2.0175, "center": (511.4, 511.85)}
CHANNELS: dict[str, dict[str, Any]] = {
    "sunspot": {**HMI, "measurement": "continuum intensity (flattened)", "wavelength_angstrom": 6173, "scheme": "Zurich sunspot group class"},
    "magnetogram": {**HMI, "measurement": "line-of-sight magnetic field", "wavelength_angstrom": 6173, "scheme": "Mount Wilson magnetic class"},
    **{
        f"aia_{wavelength}": {**AIA, "measurement": "EUV intensity" if wavelength < 1000 else "UV intensity", "wavelength_angstrom": wavelength}
        for wavelength in (94, 131, 171, 193, 211, 304, 335, 1600, 1700)
    },
}


# Declared types keep files loadable when a nullable column is empty for a whole day.
FEATURE_COLUMNS = {
    "feature_id": "string", "observation_id": "string", "t_obs": "string", "instrument": "string", "wavelength_angstrom": "int64",
    "feature_class": "string", "classification_scheme": "string", "class_votes": "votes", "n_annotators": "int64", "class_agreement": "float64",
    "shape_agreement_iou": "float64", "geometry_source": "string", "centroid_x_pixel": "float64", "centroid_y_pixel": "float64", "bbox_pixel": "ints",
    "mask_rle": "mask", "extent_radius_arcsec": "float64", "helioprojective_x_arcsec": "float64", "helioprojective_y_arcsec": "float64",
    "stonyhurst_latitude_deg": "float64", "stonyhurst_longitude_deg": "float64", "mu": "float64", "disk_pixel_fraction": "float64",
    "area_millionths_hemisphere": "float64", "quality_flags": "strings", "split": "string", "annotators": "strings",
}
OBSERVATION_COLUMNS = {
    "observation_id": "string", "t_obs": "string", "instrument": "string", "wavelength_angstrom": "int64", "measurement": "string", "image_url": "string",
    "image_product": "string", "plate_scale_arcsec_per_pixel": "float64", "disk_center_x_pixel": "float64", "disk_center_y_pixel": "float64",
    "rsun_arcsec": "float64", "rsun_pixel": "float64", "dsun_au": "float64", "solar_b0_deg": "float64", "carrington_longitude_deg": "float64",
    "carrington_rotation": "int64", "n_annotators": "int64", "reviewed_boxes_pixel": "boxes", "reviewed_disk_fraction": "float64", "split": "string", "n_features": "int64",
}
COLUMN_YAML = {
    "votes": "    list:\n    - name: feature_class\n      dtype: string\n    - name: votes\n      dtype: int64\n",
    "mask": "    struct:\n    - name: size\n      sequence: int64\n    - name: counts\n      dtype: string\n",
    "ints": "    sequence: int64\n",
    "strings": "    sequence: string\n",
    "boxes": "    sequence:\n      sequence: int64\n",
}


def _schema_yaml(name: str, columns: dict[str, str]) -> str:
    lines = "".join(f"  - name: {column}\n" + COLUMN_YAML.get(kind, f"    dtype: {kind}\n") for column, kind in columns.items())
    return f"- config_name: {name}\n  features:\n{lines}"


def observation_time(url: str) -> datetime | None:
    match = TIME_PATTERN.search(url)
    return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc) if match else None


def ephemeris(moment: datetime) -> dict[str, float | int]:
    """Earth-view solar geometry from Meeus low-precision formulae and Carrington's elements."""
    jd = moment.timestamp() / 86400 + 2440587.5
    t = (jd - 2451545.0) / 36525
    mean_longitude = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    anomaly = math.radians(357.52911 + 35999.05029 * t - 0.0001537 * t * t)
    eccentricity = 0.016708634 - 0.000042037 * t
    centre = (1.914602 - 0.004817 * t) * math.sin(anomaly) + (0.019993 - 0.000101 * t) * math.sin(2 * anomaly) + 0.000289 * math.sin(3 * anomaly)
    true_anomaly = anomaly + math.radians(centre)
    distance = 1.000001018 * (1 - eccentricity**2) / (1 + eccentricity * math.cos(true_anomaly))
    node = math.radians(125.04 - 1934.136 * t)
    longitude = math.radians(mean_longitude + centre - 0.00569 - 0.00478 * math.sin(node))
    inclination = math.radians(7.25)
    ascending = math.radians(73.6667 + 1.3958333 * (jd - 2396758) / 36525)
    b0 = math.asin(math.sin(longitude - ascending) * math.sin(inclination))
    eta = math.atan2(-math.sin(longitude - ascending) * math.cos(inclination), -math.cos(longitude - ascending))
    carrington = (math.degrees(eta) - (jd - 2398220) * 360 / 25.38) % 360
    estimate = 1690 + (jd - 2444235.34) / 27.2753
    # Carrington longitude falls from 360 to 0 through each numbered rotation.
    rotation = round(estimate - (1 - carrington / 360))
    return {
        "dsun_au": distance,
        "rsun_arcsec": math.asin(SOLAR_RADIUS_M / (distance * AU_M)) * ARCSEC_PER_RADIAN,
        "b0_deg": math.degrees(b0),
        "carrington_longitude_deg": carrington,
        "carrington_rotation": rotation,
    }


def solar_coordinates(xs: np.ndarray, ys: np.ndarray, channel: dict[str, Any], sun: dict[str, float | int]) -> dict[str, np.ndarray]:
    """Converts north-up image pixels to helioprojective and Stonyhurst coordinates."""
    scale = channel["plate_scale"]
    tx = (np.asarray(xs, float) - channel["center"][0]) * scale
    ty = (channel["center"][1] - np.asarray(ys, float)) * scale
    distance = float(sun["dsun_au"]) * AU_M
    ax, ay = tx / ARCSEC_PER_RADIAN, ty / ARCSEC_PER_RADIAN
    along = distance * np.cos(ay) * np.cos(ax)
    root = along**2 - distance**2 + SOLAR_RADIUS_M**2
    on_disk = root >= 0
    depth = along - np.sqrt(np.where(on_disk, root, np.nan))
    x = depth * np.cos(ay) * np.sin(ax)
    y = depth * np.sin(ay)
    z = distance - depth * np.cos(ay) * np.cos(ax)
    b0 = math.radians(float(sun["b0_deg"]))
    latitude = np.degrees(np.arcsin(np.clip((y * math.cos(b0) + z * math.sin(b0)) / SOLAR_RADIUS_M, -1, 1)))
    longitude = np.degrees(np.arctan2(x, z * math.cos(b0) - y * math.sin(b0)))
    mu = (z * (distance - z) - x**2 - y**2) / (SOLAR_RADIUS_M * depth)
    return {"tx": tx, "ty": ty, "on_disk": on_disk, "depth": depth, "latitude": latitude, "longitude": longitude, "mu": mu}


def pixel_from_stonyhurst(latitude: float, longitude: float, channel: dict[str, Any], sun: dict[str, float | int]) -> tuple[float, float] | None:
    """Projects a point on the Sun into the image, or returns None when it faces away from Earth."""
    lat, lon, b0 = math.radians(latitude), math.radians(longitude), math.radians(float(sun["b0_deg"]))
    x = SOLAR_RADIUS_M * math.cos(lat) * math.sin(lon)
    y = SOLAR_RADIUS_M * (math.sin(lat) * math.cos(b0) - math.cos(lat) * math.cos(lon) * math.sin(b0))
    z = SOLAR_RADIUS_M * (math.sin(lat) * math.sin(b0) + math.cos(lat) * math.cos(lon) * math.cos(b0))
    if z <= 0:
        return None
    toward = float(sun["dsun_au"]) * AU_M - z
    tx = math.atan2(x, toward) * ARCSEC_PER_RADIAN
    ty = math.asin(y / math.sqrt(x * x + y * y + toward * toward)) * ARCSEC_PER_RADIAN
    return channel["center"][0] + tx / channel["plate_scale"], channel["center"][1] - ty / channel["plate_scale"]


def _as_list(value: Any) -> list[Any]:
    parsed = json.loads(value) if isinstance(value, str) and value else value
    return parsed if isinstance(parsed, list) else []


def _circle_mask(x: float, y: float, r: float) -> np.ndarray:
    image = Image.new("1", (SIZE, SIZE))
    ImageDraw.Draw(image).ellipse([x - r, y - r, x + r, y + r], fill=1)
    return np.asarray(image)


def _scientific_class(task_type: str, label: str) -> str:
    return f"zurich_{label.removeprefix('class_').upper()}" if task_type == "sunspot" and label.startswith("class_") else label


def _votes(annotation: dict[str, Any], task_type: str) -> list[dict[str, Any]]:
    annotator = str(annotation.get("user", "")).lower()
    votes = []
    review = annotation.get("review")
    if isinstance(review, dict):
        for ring in review.get("rings", []):
            action, label = ring.get("action"), ring.get("label")
            if action == "merged" or (label == "part_of_larger" and not ring.get("outline")):
                continue
            mask, source = ring_mask(ring)
            value = NOT_A_FEATURE if action == "deleted" else UNCLASSIFIED if label in (None, "none", "part_of_larger") else _scientific_class(task_type, label)
            votes.append({"annotator": annotator, "label": value, "mask": mask, "source": source})
        return votes
    for location in annotation.get("locations", []) if isinstance(annotation.get("locations"), list) else []:
        match = CIRCLE_PATTERN.match(str(location.get("region", "")))
        if not match or float(match[3]) <= 0 or location.get("label") == "part_of_larger":
            continue
        label = UNCLASSIFIED if location.get("label") == "none" else _scientific_class(task_type, str(location.get("label")))
        votes.append({"annotator": annotator, "label": label, "mask": _circle_mask(*map(float, match.groups())), "source": "circle"})
    return votes


def _overlap(first: np.ndarray, second: np.ndarray) -> float:
    return float((first & second).sum() / max(min(first.sum(), second.sum()), 1))


def _clusters(votes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Groups votes for one physical feature, allowing one vote per annotator."""
    clusters: list[list[dict[str, Any]]] = []
    for vote in sorted(votes, key=lambda item: -int(item["mask"].sum())):
        options = [(_overlap(vote["mask"], group[0]["mask"]), index) for index, group in enumerate(clusters) if all(item["annotator"] != vote["annotator"] for item in group)]
        best = max(options, default=(0.0, -1))
        if best[0] >= SAME_FEATURE_OVERLAP:
            clusters[best[1]].append(vote)
        else:
            clusters.append([vote])
    return clusters


def _iou(first: np.ndarray, second: np.ndarray) -> float:
    return float((first & second).sum() / max((first | second).sum(), 1))


def _reviewed_boxes(annotations: list[dict[str, Any]]) -> list[list[int]]:
    boxes = set()
    for annotation in annotations:
        review = annotation.get("review")
        if isinstance(review, dict) and review.get("parts") == SECTION_GRID**2:
            column, row = (review["part"] - 1) % SECTION_GRID, (review["part"] - 1) // SECTION_GRID
            boxes.add((SECTION_START + column * SECTION_STEP, SECTION_START + row * SECTION_STEP, SECTION_SIZE, SECTION_SIZE))
        else:
            boxes.add((0, 0, SIZE, SIZE))
    return [list(box) for box in sorted(boxes)]


def _disk_share(boxes: list[list[int]], channel: dict[str, Any], sun: dict[str, float | int]) -> float:
    y, x = np.ogrid[:SIZE, :SIZE]
    radius = float(sun["rsun_arcsec"]) / channel["plate_scale"]
    disk = np.hypot(x - channel["center"][0], y - channel["center"][1]) <= radius
    seen = np.zeros((SIZE, SIZE), dtype=bool)
    for left, top, width, height in boxes:
        seen[top:top + height, left:left + width] = True
    return round(float((seen & disk).sum() / disk.sum()), 4)


def _rounded(value: Any, digits: int) -> float | None:
    number = float(value)
    return round(number, digits) if math.isfinite(number) else None


def _feature_row(group: list[dict[str, Any]], observation: dict[str, Any], channel: dict[str, Any], sun: dict[str, float | int]) -> tuple[dict[str, Any], list[str]] | None:
    labels = [vote["label"] for vote in group]
    counts = Counter(labels)
    named = [(count, label) for label, count in counts.items() if label not in (NOT_A_FEATURE, UNCLASSIFIED)]
    if not named:
        return None
    ordered = sorted(named, reverse=True)
    count, label = ordered[0]
    majority = count * 2 > len(group) and (len(ordered) == 1 or ordered[1][0] < count)
    supporters = [vote for vote in group if vote["label"] == label] if majority else [vote for vote in group if vote["label"] not in (NOT_A_FEATURE, UNCLASSIFIED)]
    for source in ("annotator_outline", "detector_mask", "circle"):
        shaped = [vote for vote in supporters if vote["source"] == source]
        if shaped:
            break
    stack = np.sum([vote["mask"] for vote in shaped], axis=0)
    mask = stack * 2 >= len(shaped)
    if not mask.any():
        mask = max(shaped, key=lambda vote: int(vote["mask"].sum()))["mask"]
    ys, xs = np.nonzero(mask)
    centre = solar_coordinates(np.array([xs.mean()]), np.array([ys.mean()]), channel, sun)
    pixels = solar_coordinates(xs, ys, channel, sun)
    usable = pixels["on_disk"] & (np.nan_to_num(pixels["mu"]) >= MIN_MU)
    scale = channel["plate_scale"] / ARCSEC_PER_RADIAN
    area = float(np.sum(scale**2 * pixels["depth"][usable] ** 2 / pixels["mu"][usable]))
    outlined = source != "circle"
    centre_on_disk = bool(centre["on_disk"][0])
    mu = _rounded(centre["mu"][0], 4) if centre_on_disk else None
    flags = []
    if len({vote["annotator"] for vote in group}) == 1:
        flags.append("single_annotator")
    if not outlined:
        flags.append("approximate_circle")
    if not centre_on_disk:
        flags.append("off_disk")
    elif mu is not None and mu < LIMB_MU:
        flags.append("near_limb")
    if not majority:
        flags.append("no_class_majority")
    pairs = [_iou(a["mask"], b["mask"]) for a, b in combinations(shaped, 2)] if outlined else []
    mask_text = encode_mask(xs, ys)
    return {
        "feature_id": hashlib.sha256(f"{observation['observation_id']}|{mask_text}".encode()).hexdigest()[:16],
        "observation_id": observation["observation_id"],
        "t_obs": observation["t_obs"],
        "instrument": channel["instrument"],
        "wavelength_angstrom": channel["wavelength_angstrom"],
        "feature_class": label if majority else None,
        "classification_scheme": channel["scheme"],
        "class_votes": [{"feature_class": name, "votes": votes} for name, votes in sorted(counts.items())],
        "n_annotators": len(group),
        # GitHub usernames, so contributors can be credited and their record weighed.
        "annotators": sorted({vote["annotator"] for vote in group}),
        "class_agreement": round(count / len(group), 4),
        "shape_agreement_iou": round(median(pairs), 4) if pairs else None,
        "geometry_source": source,
        "centroid_x_pixel": round(float(xs.mean()), 2),
        "centroid_y_pixel": round(float(ys.mean()), 2),
        "bbox_pixel": [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)],
        "mask_rle": {"size": [SIZE, SIZE], "counts": mask_text} if outlined else None,
        "extent_radius_arcsec": round(math.sqrt(xs.size / math.pi) * channel["plate_scale"], 2),
        "helioprojective_x_arcsec": round(float(centre["tx"][0]), 2),
        "helioprojective_y_arcsec": round(float(centre["ty"][0]), 2),
        "stonyhurst_latitude_deg": _rounded(centre["latitude"][0], 3) if centre_on_disk else None,
        "stonyhurst_longitude_deg": _rounded(centre["longitude"][0], 3) if centre_on_disk else None,
        "mu": mu,
        "disk_pixel_fraction": round(float(pixels["on_disk"].mean()), 4),
        "area_millionths_hemisphere": round(area / (2 * math.pi * SOLAR_RADIUS_M**2) * 1e6, 1) if outlined and usable.any() else None,
        "quality_flags": flags,
        "split": observation["split"],
    }, labels


def krippendorff_alpha(units: list[list[str]]) -> float | None:
    """Nominal Krippendorff alpha, which corrects volunteer agreement for chance."""
    pairs: Counter[tuple[str, str]] = Counter()
    for unit in units:
        if len(unit) > 1:
            for first, second in ((a, b) for i, a in enumerate(unit) for j, b in enumerate(unit) if i != j):
                pairs[first, second] += 1 / (len(unit) - 1)
    totals: Counter[str] = Counter()
    for (first, _), weight in pairs.items():
        totals[first] += weight
    n = sum(totals.values())
    expected = sum(totals[a] * totals[b] for a in totals for b in totals if a != b) / (n - 1) if n > 1 else 0
    return round(1 - sum(weight for (a, b), weight in pairs.items() if a != b) / expected, 4) if expected else None


def build_catalogue(task_type: str, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if task_type == "flare_source":
        return build_flare_catalogue(rows)
    channel = CHANNELS[task_type]
    observations, features, units = [], [], []
    excluded = Counter()
    for row in sorted(rows, key=lambda item: str(item.get("url"))):
        url, moment = str(row.get("url")), observation_time(str(row.get("url")))
        annotations = [item for item in _as_list(row.get("annotations")) if isinstance(item, dict)]
        if not annotations:
            continue
        if moment is None:
            excluded["observations_without_timestamp"] += 1
            continue
        sun = ephemeris(moment)
        boxes = _reviewed_boxes(annotations)
        observation = {
            "observation_id": hashlib.sha256(url.encode()).hexdigest()[:16],
            "t_obs": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "instrument": channel["instrument"],
            "wavelength_angstrom": channel["wavelength_angstrom"],
            "measurement": channel["measurement"],
            "image_url": url,
            "image_product": "display JPEG, 1024 x 1024, north up, not radiometrically calibrated",
            "plate_scale_arcsec_per_pixel": channel["plate_scale"],
            "disk_center_x_pixel": channel["center"][0],
            "disk_center_y_pixel": channel["center"][1],
            "rsun_arcsec": round(float(sun["rsun_arcsec"]), 3),
            "rsun_pixel": round(float(sun["rsun_arcsec"]) / channel["plate_scale"], 2),
            "dsun_au": round(float(sun["dsun_au"]), 6),
            "solar_b0_deg": round(float(sun["b0_deg"]), 4),
            "carrington_longitude_deg": round(float(sun["carrington_longitude_deg"]), 4),
            "carrington_rotation": sun["carrington_rotation"],
            "n_annotators": len({str(item.get("user", "")).lower() for item in annotations}),
            "reviewed_boxes_pixel": boxes,
            "reviewed_disk_fraction": _disk_share(boxes, channel, sun),
            "split": SPLITS[int(sun["carrington_rotation"]) % 5],
        }
        votes = [vote for annotation in annotations for vote in _votes(annotation, task_type)]
        found = 0
        for group in _clusters(votes):
            built = _feature_row(group, observation, channel, sun)
            if built is None:
                excluded["regions_rejected_or_unclassified"] += 1
                continue
            features.append(built[0])
            units.append(built[1])
            found += 1
        observations.append({**observation, "n_features": found})
    classes = Counter(item["feature_class"] for item in features if item["feature_class"])
    summary = {
        "schema_version": SCHEMA_VERSION,
        "observations": len(observations),
        "features": len(features),
        "features_with_pixel_masks": sum(item["mask_rle"] is not None for item in features),
        "features_with_two_or_more_annotators": sum(item["n_annotators"] > 1 for item in features),
        "feature_classes": dict(sorted(classes.items())),
        "krippendorff_alpha_class": krippendorff_alpha(units),
        "first_observation": min((item["t_obs"] for item in observations), default=None),
        "last_observation": max((item["t_obs"] for item in observations), default=None),
        "splits": dict(sorted(Counter(item["split"] for item in features).items())),
        "excluded": dict(sorted(excluded.items())),
    }
    return observations, features, summary


def jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, separators=(",", ":"), sort_keys=True, ensure_ascii=False) + "\n" for row in rows)


def manifest(files: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "files": {
            path: {"rows": sum(1 for line in text.splitlines() if line.strip()), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
            for path, text in sorted(files.items())
            if path.endswith(".jsonl")
        },
    }


def dataset_card(task_type: str, summary: dict[str, Any], detector: dict[str, Any], splits: list[str]) -> str:
    if task_type == "flare_source":
        return flare_card(summary, splits)
    channel = CHANNELS[task_type]
    name = f"{channel['instrument']} {channel['wavelength_angstrom']} Å {channel['measurement']}"
    repo = f"SpaceGen/solarhub-{task_type.replace('_', '-')}"
    configs = "".join(f"  - split: {split}\n    path: features/{split}/**/*.jsonl\n" for split in splits) or "  - split: train\n    path: features/**/*.jsonl\n"
    rate = lambda value: "not enough data" if value is None else f"{value:.3f}"
    classes = "\n".join(f"| `{label}` | {count} |" for label, count in summary["feature_classes"].items()) or "| None yet | 0 |"
    return f"""---
license: agpl-3.0
pretty_name: SolarHub feature catalogue, {name}
tags:
- heliophysics
- solar-physics
- sdo
- image-segmentation
- citizen-science
dataset_info:
{_schema_yaml("features", FEATURE_COLUMNS)}{_schema_yaml("observations", OBSERVATION_COLUMNS)}configs:
- config_name: features
  default: true
  data_files:
{configs}- config_name: observations
  data_files: observations/**/*.jsonl
---

# SolarHub feature catalogue: {name}

Solar features identified by volunteers in {channel['instrument']} images. Each row gives the feature class, its agreement measures and its position on the Sun.

| Measure | Value |
| --- | --- |
| Schema version | {SCHEMA_VERSION} |
| Observations | {summary['observations']} |
| Features | {summary['features']} |
| Features with pixel masks | {summary['features_with_pixel_masks']} |
| Features seen by two or more annotators | {summary['features_with_two_or_more_annotators']} |
| Krippendorff's alpha, feature class | {rate(summary['krippendorff_alpha_class'])} |
| Time range (UTC) | {summary['first_observation']} to {summary['last_observation']} |

| Feature class | Count |
| --- | --- |
{classes}

## Suitable uses

The catalogue supports feature detection, segmentation and classification research, and studies of volunteer labelling. Positions and areas are derived from display images. They should be checked against calibrated Level 1 data before use in photometric or magnetic measurements.

## Load the data

```python
from datasets import load_dataset
from pycocotools import mask as coco_mask

features = load_dataset("{repo}", "features")
observations = load_dataset("{repo}", "observations", split="train")

row = next(item for item in features["{splits[0] if splits else 'train'}"] if item["mask_rle"])
pixels = coco_mask.decode(row["mask_rle"])
```

For conservative work, keep rows with `n_annotators >= 2`, a non-null `feature_class`, and no `no_class_majority` flag.

## Coordinates

- Pixel origin is the top-left image corner. `x` increases right and `y` increases down. Pixel centres are integers.
- Images are treated as north up and are on a fixed plate scale. `rsun_pixel` therefore changes through the year with Earth's distance from the Sun.
- Helioprojective coordinates are `Tx = (x - x0) * scale` and `Ty = (y0 - y) * scale`.
- Stonyhurst coordinates use a spherical Sun of radius 695.7 Mm, viewed from Earth. Solar geometry comes from low-precision Meeus formulae and Carrington's rotation elements.
- `mu` is the cosine of the angle between the local solar normal and the line of sight.
- `area_millionths_hemisphere` is corrected for foreshortening. It sums on-disk mask pixels with `mu >= {MIN_MU}` and is null for circular approximations.

## Feature table

| Column | Meaning |
| --- | --- |
| `feature_id`, `observation_id` | Stable identifiers. |
| `t_obs` | Image time in UTC, from the source file name. |
| `instrument`, `wavelength_angstrom` | Source instrument and channel. |
| `feature_class`, `classification_scheme` | Majority class and its vocabulary. Null means no majority. |
| `class_votes` | Vote count per class, including `not_a_feature` and `unclassified`. |
| `n_annotators`, `class_agreement` | Independent annotators and the share choosing the leading class. |
| `annotators` | GitHub usernames of the people whose votes formed this feature. |
| `shape_agreement_iou` | Median pairwise intersection over union of submitted shapes. |
| `geometry_source` | `annotator_outline`, `detector_mask` (accepted by an annotator) or `circle`. |
| `centroid_x_pixel`, `centroid_y_pixel`, `bbox_pixel` | Image position. The box is `[x, y, width, height]`. |
| `mask_rle` | COCO compressed run-length mask. Null for circles. |
| `extent_radius_arcsec` | Radius of a circle with the same projected area. |
| `helioprojective_x_arcsec`, `helioprojective_y_arcsec` | Centroid position on the sky. |
| `stonyhurst_latitude_deg`, `stonyhurst_longitude_deg`, `mu` | Centroid position on the Sun. Null off disk. |
| `disk_pixel_fraction` | Share of the feature inside the solar disk. |
| `area_millionths_hemisphere` | Corrected area. |
| `quality_flags` | `single_annotator`, `approximate_circle`, `near_limb` (`mu < {LIMB_MU}`), `off_disk`, `no_class_majority`. |
| `split` | `train`, `validation` or `test`. |

## Observation table

Each row records image time, source URL, plate scale, disk centre, solar radius, Sun-Earth distance, B0, Carrington longitude and rotation, and the image area that annotators reviewed.

`reviewed_disk_fraction` matters for completeness. Annotators may inspect only part of the disk, so a missing feature outside `reviewed_boxes_pixel` is not evidence of absence.

## Method

Candidate regions come from an image-processing detector and from annotators. Votes from different annotators are grouped when their shapes overlap by at least {SAME_FEATURE_OVERLAP:.0%} of the smaller shape. The published shape is the pixel majority of the best available geometry for the winning class.

Among proposals annotators reviewed, {rate(detector.get('finder_precision'))} were accepted as real features ({detector.get('rings_reviewed', 0)} reviewed). This is not a recall estimate.

## Splits

Splits are assigned by Carrington rotation number modulo 5: 0 to 2 train, 3 validation, 4 test. All images in one rotation stay together, which prevents near-duplicate frames crossing splits. Long-lived regions can survive into a neighbouring rotation.

## Known limitations

- Images are display JPEGs with non-linear scaling, so pixel values are not physical measurements.
- Annotators are volunteers, and many features have one annotator. Check `n_annotators`.
- Class names in {MORPHOLOGY} describe appearance in one channel and are not confirmed physical diagnoses.
- Shapes from the detector follow image contrast and can differ from expert boundaries.
- The catalogue is not complete for any time interval.

## Privacy

The catalogue contains no usernames or other annotator identifiers.

## Credit

Images courtesy of NASA/SDO and the AIA, EVE and HMI science teams. Cite this dataset by repository name and access date, with the SDO instrument papers relevant to your channel.
"""

FLARE_COLUMNS = {
    "flare_id": "string", "catalogue_id": "string", "goes_class": "string", "t_start": "string", "t_peak": "string", "t_end": "string",
    "image_url": "string", "before_image_url": "string", "flash_x_pixel": "int64", "flash_y_pixel": "int64", "flash_clarity": "float64",
    "nearest_region_auto": "int64", "attribution": "string", "noaa_number": "int64", "answer_votes": "answers",
    "n_annotators": "int64", "attribution_agreement": "float64", "candidate_noaa_numbers": "ints", "source_x_pixel": "float64",
    "source_y_pixel": "float64", "helioprojective_x_arcsec": "float64", "helioprojective_y_arcsec": "float64",
    "stonyhurst_latitude_deg": "float64", "stonyhurst_longitude_deg": "float64", "swpc_noaa_number": "int64", "annotators": "strings",
    "other_catalogue_noaa_numbers": "catalogues", "quality_flags": "strings", "split": "string",
}
COLUMN_YAML["answers"] = "    list:\n    - name: answer\n      dtype: string\n    - name: votes\n      dtype: int64\n"
COLUMN_YAML["catalogues"] = "    list:\n    - name: catalogue\n      dtype: string\n    - name: noaa_number\n      dtype: int64\n"
FLARE_CHANNEL = CHANNELS["aia_131"]
BEFORE_MINUTES = 20
MIN_FLASH_CLARITY = 1.5
FLARE_ANSWERS = {"unnumbered_region", "behind_limb", "no_flare_visible"}


def _flare_answer(annotation: dict[str, Any]) -> tuple[str, tuple[float, float] | None] | None:
    for location in annotation.get("locations", []) if isinstance(annotation.get("locations"), list) else []:
        label = str(location.get("label", ""))
        if label.startswith("noaa_") or label in FLARE_ANSWERS:
            match = CIRCLE_PATTERN.match(str(location.get("region", "")))
            point = (float(match[1]), float(match[2])) if match and float(match[3]) > 0 else None
            return label, point
    return None


def build_flare_catalogue(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """One row per flare: which region volunteers saw brighten, and how other catalogues compare."""
    flares, units = [], []
    excluded = Counter()
    for row in sorted(rows, key=lambda item: str(item.get("url"))):
        metadata = row.get("metadata")
        metadata = json.loads(metadata) if isinstance(metadata, str) else metadata or {}
        flare = metadata.get("flare")
        answers = [answer for answer in (_flare_answer(item) for item in _as_list(row.get("annotations")) if isinstance(item, dict)) if answer]
        if not answers:
            continue
        if not flare:
            excluded["answers_without_flare_details"] += 1
            continue
        counts = Counter(label for label, _ in answers)
        ordered = counts.most_common()
        label, count = ordered[0]
        majority = count * 2 > len(answers) and (len(ordered) == 1 or ordered[1][1] < count)
        points = [point for answer, point in answers if answer == label and point] if majority else []
        peak = datetime.strptime(flare["peak"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        sun = ephemeris(peak)
        place = solar_coordinates(np.array([median(p[0] for p in points)]), np.array([median(p[1] for p in points)]), FLARE_CHANNEL, sun) if points else None
        on_disk = bool(place is not None and place["on_disk"][0])
        others = [{"catalogue": item["catalogue"], "noaa_number": item.get("noaa")} for item in metadata.get("other_catalogues", [])]
        flags = ["single_annotator"] if len(answers) == 1 else []
        if not majority:
            flags.append("no_majority")
        units.append([answer for answer, _ in answers])
        flares.append({
            "flare_id": hashlib.sha256(flare["catalogue_id"].encode()).hexdigest()[:16],
            "catalogue_id": flare["catalogue_id"],
            "goes_class": flare["goes_class"],
            "t_start": flare["start"], "t_peak": flare["peak"], "t_end": flare["end"],
            "image_url": row.get("url"),
            "before_image_url": metadata.get("before_url"),
            "flash_x_pixel": (metadata.get("flash") or {}).get("x"),
            "flash_y_pixel": (metadata.get("flash") or {}).get("y"),
            "flash_clarity": (metadata.get("flash") or {}).get("clarity"),
            "nearest_region_auto": metadata.get("nearest_region_auto"),
            "attribution": label if majority else None,
            "noaa_number": int(label[5:]) if majority and label.startswith("noaa_") else None,
            "answer_votes": [{"answer": answer, "votes": votes} for answer, votes in sorted(counts.items())],
            "n_annotators": len(answers),
            "annotators": sorted({str(item.get("user", "")).lower() for item in _as_list(row.get("annotations")) if isinstance(item, dict) and _flare_answer(item) and item.get("user")}),
            "attribution_agreement": round(count / len(answers), 4),
            "candidate_noaa_numbers": [item["noaa"] for item in metadata.get("candidates", [])],
            "source_x_pixel": round(median(p[0] for p in points), 1) if points else None,
            "source_y_pixel": round(median(p[1] for p in points), 1) if points else None,
            "helioprojective_x_arcsec": round(float(place["tx"][0]), 1) if place is not None else None,
            "helioprojective_y_arcsec": round(float(place["ty"][0]), 1) if place is not None else None,
            "stonyhurst_latitude_deg": _rounded(place["latitude"][0], 2) if on_disk else None,
            "stonyhurst_longitude_deg": _rounded(place["longitude"][0], 2) if on_disk else None,
            "swpc_noaa_number": None,
            "other_catalogue_noaa_numbers": others,
            "quality_flags": flags,
            "split": SPLITS[int(sun["carrington_rotation"]) % 5],
        })
    attributed = [item for item in flares if item["noaa_number"]]
    compared = [item for item in attributed if any(other["noaa_number"] for other in item["other_catalogue_noaa_numbers"])]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "flares": len(flares),
        "flares_attributed_to_noaa_region": len(attributed),
        "flares_with_two_or_more_annotators": sum(item["n_annotators"] > 1 for item in flares),
        "attributions": dict(sorted(Counter(item["attribution"] or "no_majority" for item in flares).items())),
        "krippendorff_alpha_attribution": krippendorff_alpha(units),
        "agreement_with_ssw_latest_events": round(sum(any(other["noaa_number"] == item["noaa_number"] for other in item["other_catalogue_noaa_numbers"]) for item in compared) / len(compared), 4) if compared else None,
        "first_flare": min((item["t_peak"] for item in flares), default=None),
        "last_flare": max((item["t_peak"] for item in flares), default=None),
        "splits": dict(sorted(Counter(item["split"] for item in flares).items())),
        "excluded": dict(sorted(excluded.items())),
    }
    return [], flares, summary


def flare_card(summary: dict[str, Any], splits: list[str]) -> str:
    configs = "".join(f"  - split: {split}\n    path: features/{split}/**/*.jsonl\n" for split in splits) or "  - split: train\n    path: features/**/*.jsonl\n"
    rate = lambda value: "not enough data" if value is None else f"{value:.3f}"
    return f"""---
license: agpl-3.0
pretty_name: SolarHub flare source regions
tags:
- heliophysics
- solar-flares
- space-weather
- sdo
- citizen-science
dataset_info:
{_schema_yaml("features", FLARE_COLUMNS)}configs:
- config_name: features
  default: true
  data_files:
{configs}---

# SolarHub flare source regions

GOES flares that the SWPC event list publishes without an active region (`ar_noaanum` of 0 or empty), with the NOAA region volunteers saw brighten in SDO/AIA 131 Å images.

| Measure | Value |
| --- | --- |
| Schema version | {SCHEMA_VERSION} |
| Flares | {summary['flares']} |
| Attributed to a NOAA region | {summary['flares_attributed_to_noaa_region']} |
| Flares with two or more annotators | {summary['flares_with_two_or_more_annotators']} |
| Krippendorff's alpha, attribution | {rate(summary['krippendorff_alpha_attribution'])} |
| Agreement with SSW Latest Events, where it names a region | {rate(summary['agreement_with_ssw_latest_events'])} |
| Peak times (UTC) | {summary['first_flare']} to {summary['last_flare']} |

## Why this exists

Flare forecasting models are trained on flares linked to their source active region. Flares with no region in the SWPC list are often dropped or assigned to the nearest region by guesswork. This catalogue gives an independent, image-based attribution for those flares.

## Method

1. Flares come from the HEK SWPC list: GOES class C or above, with no NOAA region.
2. The flare is located automatically as the area that brightened most between a frame {BEFORE_MINUTES} minutes before flare start and the frame nearest the GOES peak, in AIA 131 and 94 Å together. Flares without one clear brightening (the strongest at least {MIN_FLASH_CLARITY} times the next) are not offered.
2a. Annotators see a zoomed view around that brightening, before and at peak, with the nearby numbered regions.
3. The numbered regions offered are NOAA SWPC regions recorded within one day before to two days after the peak, rotated to the peak time with Snodgrass differential rotation. Regions numbered after the flare are included.
4. Volunteers choose the region that brightened, mark an unnumbered location, or answer `behind_limb` or `no_flare_visible`.
5. Annotators never see what other catalogues report. Those values are stored only for comparison.

## Columns

| Column | Meaning |
| --- | --- |
| `flare_id`, `catalogue_id` | Stable identifier and the HEK event identifier. |
| `goes_class`, `t_start`, `t_peak`, `t_end` | GOES class and times from SWPC (UTC). |
| `image_url`, `before_image_url` | The peak and pre-flare AIA 131 Å images shown. |
| `flash_x_pixel`, `flash_y_pixel`, `flash_clarity` | Automatic brightening location and how much it stood out. |
| `nearest_region_auto` | The NOAA region nearest the brightening, within 60 pixels. A simple baseline to compare with annotators. |
| `attribution`, `noaa_number` | Majority answer, and the NOAA region number when that answer is a region. Null means no majority. |
| `answer_votes`, `n_annotators`, `attribution_agreement` | Vote counts and the share choosing the majority answer. |
| `annotators` | GitHub usernames of the people who answered. |
| `candidate_noaa_numbers` | Regions offered to annotators. |
| `source_x_pixel`, `source_y_pixel` | Median marked position, when the answer has one. |
| `helioprojective_*`, `stonyhurst_*` | That position on the sky and on the Sun. Stonyhurst is null off disk. |
| `swpc_noaa_number` | The SWPC region, always null here by selection. |
| `other_catalogue_noaa_numbers` | Regions given by SSW Latest Events and the Flare Detective trigger module near the same peak. Four-digit numbers are converted to five digits. |
| `quality_flags` | `single_annotator`, `no_majority`. |
| `split` | By Carrington rotation of the peak: modulo 5 values 0 to 2 train, 3 validation, 4 test. |

For conservative work, keep rows with `n_annotators >= 2` and a non-null `noaa_number`.

## Limitations

- Display JPEGs are not calibrated, and a 131 Å frame every few minutes can miss short or faint brightenings.
- Two flares at similar times can be confused. Check `other_catalogue_noaa_numbers` for disagreement.
- A region that is not yet numbered cannot be offered. Those flares appear as `unnumbered_region`.

## Privacy and credit

No usernames or annotator identifiers are included. Flare times come from NOAA SWPC through the Heliophysics Events Knowledgebase. Images courtesy of NASA/SDO and the AIA science team.
"""
