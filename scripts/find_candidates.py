"""Find whole solar structures and compact features for contributors to check."""

from __future__ import annotations

import io
from typing import Any

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
# Tuned on 16 days of NOAA regions and coronal holes, keeping nearly everything they found.
MIN_SCORES = {"aia_94": 2, "aia_131": 5, "aia_171": 6, "aia_193": 5, "aia_211": 1, "aia_304": 10, "aia_335": 2, "aia_1600": 3, "aia_1700": 2}
DARK_RATIOS = (0.45, 0.6)
BRIGHT_LEVELS = (6.0, 3.5)
MIN_REGION_AREA = 250
REGIONS_PER_LEVEL = 6
OUTER_RING = 1.6
LIMB_START = 370
LIMB_BAND_RATIO = 3
BRIGHT_SEARCH = 420
SHAPE_MARGIN = 10
MIN_MASK_AREA = 40
MIN_WHOLE_SHARE = 0.8
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


def encode_mask(xs: np.ndarray, ys: np.ndarray) -> str:
    """Stores pixels as COCO compressed RLE, which pycocotools can read directly."""
    index = np.unique(xs.astype(np.int64) * SIZE + ys)
    breaks = np.flatnonzero(np.diff(index) > 1)
    starts = index[np.r_[0, breaks + 1]]
    ends = index[np.r_[breaks, len(index) - 1]] + 1
    counts = np.column_stack((starts - np.r_[0, ends[:-1]], ends - starts)).ravel().tolist()
    if ends[-1] < SIZE * SIZE:
        counts.append(SIZE * SIZE - int(ends[-1]))
    text = []
    for position, count in enumerate(counts):
        value = count - counts[position - 2] if position > 2 else count
        while True:
            chunk = value & 0x1f
            value >>= 5
            more = value != -1 if chunk & 0x10 else value != 0
            text.append(chr(chunk + 48 + (0x20 if more else 0)))
            if not more:
                break
    return "".join(text)


def decode_mask(text: str) -> np.ndarray:
    counts: list[int] = []
    position = 0
    while position < len(text):
        value, shift = 0, 0
        while True:
            chunk = ord(text[position]) - 48
            position += 1
            value |= (chunk & 0x1f) << shift
            shift += 5
            if not chunk & 0x20:
                if chunk & 0x10:
                    value |= -1 << shift
                break
        counts.append(value + counts[-2] if len(counts) > 2 else value)
    flat = np.zeros(SIZE * SIZE, dtype=bool)
    edges = np.cumsum(counts)
    for start, end in zip(edges[::2], edges[1::2]):
        flat[start:end] = True
    return flat.reshape(SIZE, SIZE).T


def _feature_mask(xs: np.ndarray, ys: np.ndarray) -> str | None:
    """Smooths a detected region into one solid shape, keeping its uneven edge."""
    left, top = int(xs.min()) - SHAPE_MARGIN, int(ys.min()) - SHAPE_MARGIN
    grid = np.zeros((int(ys.max()) - top + SHAPE_MARGIN + 1, int(xs.max()) - left + SHAPE_MARGIN + 1), dtype=bool)
    grid[ys - top, xs - left] = True
    grid = ndimage.binary_fill_holes(grid)
    smooth = ndimage.gaussian_filter(grid.astype(float), np.clip(np.sqrt(grid.sum()) * 0.05, 1, 4)) >= 0.5
    labels, count = ndimage.label(smooth)
    if not count:
        return None
    largest = np.argmax(np.bincount(labels.ravel())[1:]) + 1
    rows, columns = np.where(labels == largest)
    rows, columns = rows + top, columns + left
    inside = (rows >= 0) & (rows < SIZE) & (columns >= 0) & (columns < SIZE)
    return encode_mask(columns[inside], rows[inside]) if inside.sum() >= MIN_MASK_AREA else None


def _fit_ring(score: np.ndarray, mask: np.ndarray, x: int, y: int, threshold: float, max_ring: int, limit: int) -> tuple[dict[str, int], np.ndarray, np.ndarray, bool]:
    labels, _ = ndimage.label((score >= max(threshold * 0.65, score[y, x] * 0.38)) & mask)
    ys, xs = np.where(labels == labels[y, x])
    nearby = np.hypot(xs - x, ys - y) <= max_ring
    # A region cut off by the search limit has no real edge there, so its shape is not trustworthy.
    whole = nearby.mean() >= MIN_WHOLE_SHARE
    xs, ys = xs[nearby], ys[nearby]
    centre_x, centre_y = float(xs.mean()), float(ys.mean())
    ring = np.percentile(np.hypot(xs - centre_x, ys - centre_y), 92) * 1.08 + 8
    room = limit - np.hypot(centre_x - CENTRE, centre_y - CENTRE)
    return {
        "x": int(round(centre_x)),
        "y": int(round(centre_y)),
        "r": int(np.clip(round(min(ring, room)), MIN_RING, max_ring)),
    }, xs, ys, whole


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
        mark, xs, ys, whole = _fit_ring(score, mask, int(x), int(y), threshold, max_ring, reach)
        if _can_keep(mark, marks):
            shape = _feature_mask(xs, ys) if whole else None
            marks.append({**mark, "mask": shape} if shape else mark)
            if len(marks) == limit:
                break
    return marks


def _merge(groups: list[list[dict[str, int]]]) -> list[dict[str, int]]:
    kept: list[dict[str, int]] = []
    for group in groups:
        for mark in group:
            if _can_keep(mark, kept):
                kept.append(mark)
    return kept


def _regions(levels: list[np.ndarray], radius: np.ndarray, limit: int) -> list[dict[str, Any]]:
    """Measures whole regions directly, because large or edge features hide from band filters."""
    marks: list[dict[str, Any]] = []
    # The strict level keeps neighbouring regions apart; the loose level catches fainter ones.
    for level in levels:
        labels, count = ndimage.label(level)
        sizes = np.bincount(labels.ravel(), minlength=count + 1)
        sizes[0] = 0
        for label in np.argsort(sizes)[::-1][:REGIONS_PER_LEVEL]:
            if sizes[label] < MIN_REGION_AREA:
                break
            ys, xs = np.where(labels == label)
            # A curved region's average position can fall outside it, so use its nearest pixel.
            nearest = np.argmin(np.hypot(xs - xs.mean(), ys - ys.mean()))
            x, y = int(xs[nearest]), int(ys[nearest])
            ring = np.percentile(np.hypot(xs - x, ys - y), 92) * 1.08 + 8
            room = limit - radius[y, x]
            mark = {"x": x, "y": y, "r": int(np.clip(round(min(ring, room)), MIN_RING, REGION_RING))}
            if _can_keep(mark, marks):
                shape = _feature_mask(xs, ys)
                marks.append({**mark, "mask": shape} if shape else mark)
    return marks


def _dark_regions(gray: np.ndarray, flat: np.ndarray, sun: np.ndarray, radius: np.ndarray) -> list[dict[str, Any]]:
    darkness = _blur(gray, 4, sun) / np.maximum(gray - flat, 1)
    return _regions([(darkness < ratio) & sun & (radius < DISK_SEARCH) for ratio in DARK_RATIOS], radius, IMAGE_LIMIT)


def _bright_regions(gray: np.ndarray, flat: np.ndarray, zone: np.ndarray, radius: np.ndarray, limit: int) -> list[dict[str, Any]]:
    brightness = _blur(gray, 4, zone) / np.maximum(gray - flat, 1)
    typical = float(np.median(brightness[zone]))
    spread = float(np.median(np.abs(brightness[zone] - typical))) * 1.4826 or 0.01
    return _regions([(brightness > typical + level * spread) & zone for level in BRIGHT_LEVELS], radius, limit)


def _hugs_limb(text: str) -> bool:
    """Spots a long thin strip along the solar edge, which is limb glow rather than a feature."""
    ys, xs = np.nonzero(decode_mask(text))
    dx, dy = xs - CENTRE, ys - CENTRE
    distance = np.hypot(dx, dy)
    if np.median(distance) < LIMB_START:
        return False
    offset = (np.arctan2(dy, dx) - np.arctan2(dy.mean(), dx.mean()) + np.pi) % (2 * np.pi) - np.pi
    along = np.subtract(*np.percentile(offset, [95, 5])) * np.median(distance)
    across = np.subtract(*np.percentile(distance, [95, 5])) + 1
    return along > LIMB_BAND_RATIO * across


def _rank(marks: list[dict[str, Any]], flat: np.ndarray, disk: np.ndarray, sign: int) -> list[dict[str, Any]]:
    """Orders features by how strongly they stand out in the channel people are looking at."""
    spread = float(np.median(np.abs(flat[disk] - np.median(flat[disk])))) * 1.4826 or 1.0
    ranked = []
    for mark in marks:
        if sign >= 0 and "mask" in mark and _hugs_limb(mark["mask"]):
            continue
        reach = int(mark["r"] * OUTER_RING) + 2
        top, left = max(0, mark["y"] - reach), max(0, mark["x"] - reach)
        window = (slice(top, min(SIZE, mark["y"] + reach + 1)), slice(left, min(SIZE, mark["x"] + reach + 1)))
        ys, xs = np.ogrid[window]
        distance = np.hypot(xs - mark["x"], ys - mark["y"])
        inner = decode_mask(mark["mask"])[window] if "mask" in mark else distance <= mark["r"] * 0.7
        outer = (distance <= mark["r"] * OUTER_RING) & ~ndimage.binary_dilation(inner, iterations=6)
        contrast = (flat[window][inner].mean() - flat[window][outer].mean()) / spread if inner.any() and outer.any() else 0.0
        contrast = abs(contrast) if sign == 0 else contrast * sign
        ranked.append({**mark, "score": round(float(contrast * np.sqrt(inner.sum()) / 10), 2)})
    return sorted(ranked, key=lambda item: -item["score"])


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


def score_candidates(gray: np.ndarray, task_type: str, context: dict[str, np.ndarray] | None = None) -> list[dict[str, Any]]:
    radius = _radius_map()
    disk = radius < DISK_SEARCH
    with_edge = radius < EDGE_SEARCH
    flat = _flatten(gray, radius)
    sun = radius < SOLAR_RADIUS
    reach = SOLAR_RADIUS + 18
    sign = 0
    if task_type in HOT_REGION_TYPES:
        sign = 1
        groups = [
            _bright_regions(gray, flat, radius < BRIGHT_SEARCH, radius, IMAGE_LIMIT),
            _features(_band(flat, 16, 90), with_edge, 1.2, 12, 101, REGION_RING),
            _features(_band(flat, 5, 34), with_edge, 1.9, 16, 55, 70),
            _features(_band(flat, 2.2, 16), with_edge, 2.4, 16, 35, COMPACT_RING),
        ]
    elif task_type in DARK_REGION_TYPES:
        sign = -1
        groups = [
            _dark_regions(gray, flat, sun, radius),
            _features(-_band(flat, 12, 90, sun), disk, 1.2, 12, 101, 120, reach),
            _features(-_band(flat, 3, 24, sun), disk, 2.2, 16, 45, 58, reach),
        ]
    elif task_type == "aia_304":
        edge = (radius > 398) & with_edge
        groups = [
            _bright_regions(gray, flat, disk, radius, reach),
            _features(_band(flat, 3, 22), edge, 2.0, 10, 45, 58),
            _features(_band(flat, 13, 75, sun), disk, 1.2, 12, 81, 125, reach),
            _features(-_band(flat, 3, 24, sun), disk, 2.0, 12, 45, 55, reach),
        ]
    else:
        groups = [
            _bright_regions(gray, flat, disk, radius, reach),
            _features(_band(flat, 12, 70, sun), disk, 1.2, 12, 81, 115, reach),
            _features(_band(flat, 4, 26, sun), disk, 2.0, 16, 45, 55, reach),
            _features(-_band(flat, 2, 20, sun), disk, 3.5, 8, 35, COMPACT_RING, reach),
        ]
    if context is not None:
        groups[1:1] = _blended_features(context, task_type, disk, sun, reach)
    return _rank(_merge(groups), flat, disk, sign)


def find_candidates(gray: np.ndarray, task_type: str, context: dict[str, np.ndarray] | None = None) -> list[dict[str, Any]]:
    return [mark for mark in score_candidates(gray, task_type, context) if mark["score"] >= MIN_SCORES.get(task_type, 0)][:MAX_FEATURES]


def gray_from_jpeg(content: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(content)).convert("L").resize((SIZE, SIZE)), dtype=float)


def candidates_from_jpeg(content: bytes, task_type: str, context: dict[str, np.ndarray] | None = None) -> list[dict[str, int]]:
    return find_candidates(gray_from_jpeg(content), task_type, context)
