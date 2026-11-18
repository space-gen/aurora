"""Find a few clear features in an AIA image so contributors can judge them one at a time."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image
from scipy import ndimage

SIZE = 1024
CENTRE = 511.5
DISK_RADIUS = 375
BRIGHT_ONLY = {"aia_94", "aia_131", "aia_171", "aia_335"}
DARK_ONLY = {"aia_193", "aia_211"}
MIN_SEPARATION = 110


def _radius_map() -> np.ndarray:
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    return np.hypot(x - CENTRE, y - CENTRE)


def _scores(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    sample = values[mask]
    median = float(np.median(sample))
    spread = float(np.median(np.abs(sample - median))) * 1.4826 or 1.0
    return (values - median) / spread


def _mark(x: float, y: float, radius: float) -> dict[str, int]:
    return {"x": int(round(x)), "y": int(round(y)), "r": int(np.clip(round(radius), 28, 110))}


def _bright(gray: np.ndarray, mask: np.ndarray, sigma: float, threshold: float, limit: int) -> list[dict[str, int]]:
    smooth = ndimage.gaussian_filter(gray, sigma)
    score = _scores(smooth, mask)
    peaks = (score == ndimage.maximum_filter(score, size=81)) & (score > threshold) & mask
    found = []
    for y, x in sorted(zip(*np.where(peaks)), key=lambda point: -score[point]):
        halfway = score > score[y, x] / 2
        labels, _ = ndimage.label(halfway & mask)
        area = int((labels == labels[y, x]).sum())
        found.append(_mark(x, y, np.sqrt(area / np.pi) * 1.15))
        if len(found) == limit:
            break
    return found


def _dark(gray: np.ndarray, mask: np.ndarray, sigma: float, threshold: float, min_area: int, limit: int) -> list[dict[str, int]]:
    smooth = ndimage.gaussian_filter(gray, sigma)
    labels, count = ndimage.label((_scores(smooth, mask) < threshold) & mask)
    regions = []
    for index in range(1, count + 1):
        region = labels == index
        area = int(region.sum())
        if area >= min_area:
            distance = ndimage.distance_transform_edt(region)
            y, x = np.unravel_index(int(distance.argmax()), distance.shape)
            regions.append((area, _mark(x, y, float(distance[y, x]) * 2.2)))
    return [mark for _, mark in sorted(regions, key=lambda item: -item[0])[:limit]]


def _contrast(gray: np.ndarray, fine: float, broad: float) -> np.ndarray:
    return ndimage.gaussian_filter(gray, fine) - ndimage.gaussian_filter(gray, broad)


def _edge_flames(gray: np.ndarray, radius: np.ndarray) -> list[dict[str, int]]:
    ring = (radius > 408) & (radius < 455)
    return _bright(gray, ring, 5, 5, 1)


def find_candidates(gray: np.ndarray, task_type: str) -> list[dict[str, int]]:
    radius = _radius_map()
    disk = radius < DISK_RADIUS
    if task_type in BRIGHT_ONLY:
        marks = _bright(gray, disk, 14, 3, 3)
    elif task_type in DARK_ONLY:
        marks = _dark(gray, disk, 7, -2.2, 500, 3)
    elif task_type == "aia_304":
        marks = _bright(gray, disk, 14, 2.5, 1) + _dark(gray, disk, 7, -2, 300, 1) + _edge_flames(gray, radius)
    else:
        # These channels are dim with a bright limb, so compare each area with its surroundings.
        marks = _bright(_contrast(gray, 10, 60), disk, 1, 3, 2) + _dark(_contrast(gray, 2, 35), disk, 1, -5, 35, 1)

    kept: list[dict[str, int]] = []
    for mark in marks:
        if all(np.hypot(mark["x"] - other["x"], mark["y"] - other["y"]) >= MIN_SEPARATION for other in kept):
            kept.append(mark)
    return kept


def candidates_from_jpeg(content: bytes, task_type: str) -> list[dict[str, int]]:
    image = Image.open(io.BytesIO(content)).convert("L").resize((SIZE, SIZE))
    return find_candidates(np.asarray(image, dtype=float), task_type)
