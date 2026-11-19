"""Turns annotator decisions into shapes and detector validation scores."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from statistics import median
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

try:
    from scripts.find_candidates import SIZE, decode_mask, encode_mask
except ModuleNotFoundError:
    from find_candidates import SIZE, decode_mask, encode_mask

ACCEPTED = ("confirmed", "moved", "outlined", "merged")
DISCARDED = ("rejected", "deleted")
def _annotations(record: dict[str, Any]) -> list[Any]:
    value = record.get("annotations") or []
    parsed = json.loads(value) if isinstance(value, str) else value
    return parsed if isinstance(parsed, list) else []


def polygon_mask(outline: list[list[float]]) -> np.ndarray:
    image = Image.new("1", (SIZE, SIZE))
    ImageDraw.Draw(image).polygon([tuple(point) for point in outline], fill=1)
    return np.asarray(image)


def _polygon_rle(outline: list[list[float]]) -> str | None:
    ys, xs = np.where(polygon_mask(outline))
    return encode_mask(xs, ys) if len(xs) else None


def ring_mask(ring: dict[str, Any]) -> tuple[np.ndarray, str]:
    """Returns the best shape for a reviewed feature and where that shape came from."""
    if ring.get("outline"):
        mask = polygon_mask(ring["outline"])
        if mask.any():
            return mask, "annotator_outline"
    if ring.get("finder_mask") and ring.get("action") in ("confirmed", "rejected", "deleted"):
        return decode_mask(ring["finder_mask"]), "detector_mask"
    x, y, r = ring["ring"]
    image = Image.new("1", (SIZE, SIZE))
    ImageDraw.Draw(image).ellipse([x - r, y - r, x + r, y + r], fill=1)
    return np.asarray(image), "circle"


def _mask_overlap(first: str, second: str) -> float:
    a, b = decode_mask(first), decode_mask(second)
    return float((a & b).sum() / max((a | b).sum(), 1))


def review_rows(records: list[dict[str, Any]], task_type: str, date: str) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        for annotation in _annotations(record):
            review = annotation.get("review") if isinstance(annotation, dict) else None
            if not isinstance(review, dict):
                continue
            for index, ring in enumerate(review.get("rings", [])):
                finder = ring.get("finder") or [None, None, None]
                x, y, r = ring["ring"]
                finder_mask = ring.get("finder_mask")
                mask = _polygon_rle(ring["outline"]) if ring.get("outline") else finder_mask if ring["action"] == "confirmed" else None
                rows.append({
                    "review_id": f"{annotation.get('issue_number')}-{index}",
                    "record_id": record.get("id"),
                    "image_url": record.get("url"),
                    "task_type": task_type,
                    "capture_date": date,
                    "contributor": annotation.get("user"),
                    "reviewed_at": annotation.get("timestamp"),
                    "part": review.get("part"),
                    "parts": review.get("parts"),
                    "action": ring["action"],
                    "label": ring.get("label"),
                    "part_of_larger": bool(ring.get("part_of_larger")),
                    "finder_x": finder[0],
                    "finder_y": finder[1],
                    "finder_r": finder[2],
                    "finder_mask": finder_mask,
                    "finder_verified": bool(ring.get("finder_verified")),
                    "x": x,
                    "y": y,
                    "r": r,
                    "mask": mask,
                    "outline": json.dumps(ring["outline"], separators=(",", ":")) if ring.get("outline") else None,
                })
    return rows


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def tally(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Scores the finder only on rings confirmed to be ones it really proposed."""
    trusted = [row for row in rows if row["action"] == "added" or row["finder_verified"]]
    actions = Counter(row["action"] for row in trusted)
    accepted = sum(actions[name] for name in ACCEPTED)
    reviewed = accepted + sum(actions[name] for name in DISCARDED)
    votes: dict[tuple, list[bool]] = defaultdict(list)
    for row in trusted:
        if row["action"] != "added":
            votes[(row["image_url"], row["finder_x"], row["finder_y"], row["finder_r"])].append(row["action"] in ACCEPTED)
    repeated = [items for items in votes.values() if len(items) > 1]
    reshaped = [_mask_overlap(row["finder_mask"], row["mask"]) for row in trusted if row["action"] == "outlined" and row.get("finder_mask") and row.get("mask")]
    return {
        "rings_reviewed": reviewed,
        "actions": {name: actions[name] for name in (*ACCEPTED, *DISCARDED, "added")},
        "labels": dict(sorted(Counter(row["label"] for row in trusted if row["label"]).items())),
        "finder_precision": _share(accepted, reviewed),
        "rings_corrected_share": _share(actions["moved"] + actions["outlined"] + actions["merged"], accepted),
        "human_added_share": _share(actions["added"], accepted + actions["added"]),
        "shapes_redrawn": len(reshaped),
        "finder_shape_overlap_median": round(median(reshaped), 4) if reshaped else None,
        "rings_with_two_or_more_reviews": len(repeated),
        "reviewer_agreement": _share(sum(len(set(items)) == 1 for items in repeated), len(repeated)),
        "contributors": len({row["contributor"] for row in trusted}),
        "images": len({row["image_url"] for row in trusted}),
        "rows_not_matched_to_finder": len(rows) - len(trusted),
    }
