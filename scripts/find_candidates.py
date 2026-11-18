"""Find whole solar structures and compact features for contributors to check."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image
from scipy import ndimage

SIZE = 1024
CENTRE = 511.5
SOLAR_RADIUS = 395
FLATTEN_RADIUS = 455
DISK_SEARCH = 388
EDGE_SEARCH = 445
IMAGE_LIMIT = 500
MIN_RING = 24
REGION_RING = 150
COMPACT_RING = 42
MAX_FEATURES = 40
DARK_RATIOS = (0.45, 0.6)
MIN_DARK_AREA = 250
# Best blend against NOAA regions in 31 days of testing; 193 and 211 show dark regions best.
BLEND_BRIGHT = ("131", "211", "193", "1700")
BLEND_DARK = ("193", "211")
BLEND_WAVELENGTHS = BLEND_BRIGHT
HOT_REGION_TYPES = {"aia_94", "aia_131", "aia_171", "aia_335"}
DARK_REGION_TYPES = {"aia_193", "aia_211"}


def _radius_map() -> np.ndarray:
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    return np.hypot(x - CENTRE, y - CENTRE)


def _flatten(gray: np.ndarray, radius: np.ndarray) -> np.ndarray:
    """Compares each pixel with its radius, so edge features compete with disk features."""
    bins = radius.astype(int)
    flat = np.zeros_like(gray, dtype=float)
    for value in range(FLATTEN_RADIUS):
        ring = bins == value
        if ring.any():
            flat[ring] = gray[ring] - np.median(gray[ring])
    return flat


def _blur(values: np.ndarray, sigma: float, inside: np.ndarray | None) -> np.ndarray:
    if inside is None:
        return ndimage.gaussian_filter(values, sigma)
    # Ignore black space, so the solar edge does not look like a feature.
    weight = ndimage.gaussian_filter(inside.astype(float), sigma)
    return ndimage.gaussian_filter(values * inside, sigma) / np.maximum(weight, 1e-3)


def _band(values: np.ndarray, fine: float, broad: float, inside: np.ndarray | None = None) -> np.ndarray:
    return _blur(values, fine, inside) - _blur(values, broad, inside)


def _scores(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    sample = values[mask]
    median = float(np.median(sample))
    spread = float(np.median(np.abs(sample - median))) * 1.4826 or 1.0
    return (values - median) / spread


def _fit_ring(score: np.ndarray, mask: np.ndarray, x: int, y: int, threshold: float, max_ring: int, limit: int) -> dict[str, int]:
    labels, _ = ndimage.label((score >= max(threshold * 0.65, score[y, x] * 0.38)) & mask)
    ys, xs = np.where(labels == labels[y, x])
    nearby = np.hypot(xs - x, ys - y) <= max_ring
    xs, ys = xs[nearby], ys[nearby]
    centre_x, centre_y = float(xs.mean()), float(ys.mean())
    ring = np.percentile(np.hypot(xs - centre_x, ys - centre_y), 92) * 1.08 + 8
    room = limit - np.hypot(centre_x - CENTRE, centre_y - CENTRE)
    return {
        "x": int(round(centre_x)),
        "y": int(round(centre_y)),
        "r": int(np.clip(round(min(ring, room)), MIN_RING, max_ring)),
    }


def _can_keep(mark: dict[str, int], kept: list[dict[str, int]]) -> bool:
    for other in kept:
        distance = np.hypot(mark["x"] - other["x"], mark["y"] - other["y"])
        # Drop a core at the centre of a larger ring, but keep a separate feature beside it.
        if distance < 0.45 * max(other["r"], mark["r"]) + 0.35 * min(other["r"], mark["r"]):
            return False
    return True


def _features(signal: np.ndarray, mask: np.ndarray, threshold: float, limit: int, spacing: int, max_ring: int, reach: int = IMAGE_LIMIT) -> list[dict[str, int]]:
    score = _scores(signal, mask)
    peaks = (score == ndimage.maximum_filter(score, size=spacing | 1)) & (score >= threshold) & mask
    marks: list[dict[str, int]] = []
    for y, x in sorted(zip(*np.where(peaks)), key=lambda point: -score[point]):
        mark = _fit_ring(score, mask, int(x), int(y), threshold, max_ring, reach)
        if _can_keep(mark, marks):
            marks.append(mark)
            if len(marks) == limit:
                break
    return marks


def _merge(groups: list[list[dict[str, int]]]) -> list[dict[str, int]]:
    kept: list[dict[str, int]] = []
    for group in groups:
        for mark in group:
            if len(kept) < MAX_FEATURES and _can_keep(mark, kept):
                kept.append(mark)
    return kept


def _dark_regions(gray: np.ndarray, flat: np.ndarray, sun: np.ndarray, radius: np.ndarray) -> list[dict[str, int]]:
    """Finds large dark areas directly, because holes at the limb hide from band filters."""
    typical = np.maximum(gray - flat, 1)
    darkness = _blur(gray, 4, sun) / typical
    marks: list[dict[str, int]] = []
    # The strict level keeps neighbouring holes apart; the loose level catches fainter ones.
    for ratio in DARK_RATIOS:
        labels, count = ndimage.label((darkness < ratio) & sun & (radius < DISK_SEARCH))
        sizes = np.bincount(labels.ravel(), minlength=count + 1)
        sizes[0] = 0
        for label in np.argsort(sizes)[::-1][:6]:
            if sizes[label] < MIN_DARK_AREA:
                break
            ys, xs = np.where(labels == label)
            # A curved hole's average position can fall outside it, so use its nearest pixel.
            nearest = np.argmin(np.hypot(xs - xs.mean(), ys - ys.mean()))
            x, y = int(xs[nearest]), int(ys[nearest])
            ring = np.percentile(np.hypot(xs - x, ys - y), 92) * 1.08 + 8
            room = IMAGE_LIMIT - np.hypot(x - CENTRE, y - CENTRE)
            mark = {"x": x, "y": y, "r": int(np.clip(round(min(ring, room)), MIN_RING, REGION_RING))}
            if _can_keep(mark, marks):
                marks.append(mark)
    return marks


def blend_context(frames: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Averages matching instruments so features that are faint in one still stand out."""
    radius = _radius_map()
    disk = radius < DISK_SEARCH
    scores = {name: np.clip(_scores(_flatten(gray, radius), disk), -8, 8) for name, gray in frames.items()}
    return {
        "bright": np.mean([scores[name] for name in BLEND_BRIGHT], axis=0).astype(np.float32),
        "dark": (-np.mean([scores[name] for name in BLEND_DARK], axis=0)).astype(np.float32),
    }


def _blended_features(context: dict[str, np.ndarray], task_type: str, disk: np.ndarray, sun: np.ndarray, reach: int) -> list[list[dict[str, int]]]:
    groups: list[list[dict[str, int]]] = []
    if task_type not in DARK_REGION_TYPES:
        bright = context["bright"]
        groups += [
            _features(_band(bright, 10, 70, sun), disk, 1.1, 14, 81, REGION_RING, reach),
            _features(_band(bright, 3, 24, sun), disk, 1.8, 16, 45, 60, reach),
        ]
    if task_type in DARK_REGION_TYPES or task_type == "aia_304":
        dark = context["dark"]
        groups += [
            _features(_band(dark, 10, 80, sun), disk, 1.1, 10, 81, 120, reach),
            _features(_band(dark, 3, 24, sun), disk, 1.8, 12, 45, 58, reach),
        ]
    return groups


def find_candidates(gray: np.ndarray, task_type: str, context: dict[str, np.ndarray] | None = None) -> list[dict[str, int]]:
    radius = _radius_map()
    disk = radius < DISK_SEARCH
    with_edge = radius < EDGE_SEARCH
    flat = _flatten(gray, radius)
    sun = radius < SOLAR_RADIUS
    reach = SOLAR_RADIUS + 18
    if task_type in HOT_REGION_TYPES:
        groups = [
            _features(_band(flat, 16, 90), with_edge, 1.2, 12, 101, REGION_RING),
            _features(_band(flat, 5, 34), with_edge, 1.9, 16, 55, 70),
            _features(_band(flat, 2.2, 16), with_edge, 2.4, 16, 35, COMPACT_RING),
        ]
    elif task_type in DARK_REGION_TYPES:
        groups = [
            _dark_regions(gray, flat, sun, radius),
            _features(-_band(flat, 12, 90, sun), disk, 1.2, 12, 101, 120, reach),
            _features(-_band(flat, 3, 24, sun), disk, 2.2, 16, 45, 58, reach),
        ]
    elif task_type == "aia_304":
        edge = (radius > 398) & with_edge
        groups = [
            _features(_band(flat, 3, 22), edge, 2.0, 10, 45, 58),
            _features(_band(flat, 13, 75, sun), disk, 1.2, 12, 81, 125, reach),
            _features(-_band(flat, 3, 24, sun), disk, 2.0, 12, 45, 55, reach),
        ]
    else:
        groups = [
            _features(_band(flat, 12, 70, sun), disk, 1.2, 12, 81, 115, reach),
            _features(_band(flat, 4, 26, sun), disk, 2.0, 16, 45, 55, reach),
            _features(-_band(flat, 2, 20, sun), disk, 3.5, 8, 35, COMPACT_RING, reach),
        ]
    if context is not None:
        groups[1:1] = _blended_features(context, task_type, disk, sun, reach)
    return _merge(groups)


def gray_from_jpeg(content: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(content)).convert("L").resize((SIZE, SIZE)), dtype=float)


def candidates_from_jpeg(content: bytes, task_type: str, context: dict[str, np.ndarray] | None = None) -> list[dict[str, int]]:
    return find_candidates(gray_from_jpeg(content), task_type, context)
