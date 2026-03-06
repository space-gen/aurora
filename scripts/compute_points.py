"""
compute_points.py
=================
Pipeline Stage 8 — Compute User Points

Compare user annotations (from annotations/) with the ML predictions stored
in the data_processing/ task files.  Award points based on how closely the
user label agrees with the model's prediction weighted by its confidence.

Point-awarding rules:
  • Exact label match + high confidence (>= 0.80) → POINTS_HIGH
  • Exact label match + medium confidence (0.50–0.79) → POINTS_MEDIUM
  • Exact label match + low confidence (< 0.50) → POINTS_LOW
  • No match → 0 points

Results are written back into the task files' ``points`` field.

No external API keys are required for this stage.

Usage:
    python scripts/compute_points.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PROCESSING_DIR = REPO_ROOT / "data_processing"
ANNOTATIONS_DIR = REPO_ROOT / "annotations"

# Point values awarded for a correct user label at each confidence tier.
POINTS_HIGH = 10
POINTS_MEDIUM = 5
POINTS_LOW = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_task_index() -> dict[str, dict[str, Any]]:
    """
    Build a URL → task dict index from all task JSON files in
    data_processing/.  Tasks without an ml_prediction are skipped because
    there is nothing to compare against yet.
    """
    index: dict[str, dict[str, Any]] = {}
    for path in sorted(DATA_PROCESSING_DIR.glob("*.json")):
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping unreadable task file %s: %s", path.name, exc)
            continue
        url = task.get("url")
        if url and task.get("ml_prediction") is not None:
            index[url] = {"task": task, "path": path}
    log.info("Loaded %d task(s) with ML predictions.", len(index))
    return index


def _load_annotations() -> list[dict[str, Any]]:
    """Return all non-empty annotation records from annotations/."""
    records: list[dict[str, Any]] = []
    for path in sorted(ANNOTATIONS_DIR.glob("*.json")):
        raw = path.read_text(encoding="utf-8").strip()
        if not raw or raw == "{}":
            continue
        try:
            ann = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("Skipping malformed annotation file %s: %s", path.name, exc)
            continue
        if ann.get("url") and ann.get("user_label"):
            records.append(ann)
    log.info("Loaded %d annotation record(s).", len(records))
    return records


def _award_points(ml_prediction: str, confidence: float, user_label: str) -> int:
    """
    Return the number of points the user earns for *user_label* against
    *ml_prediction* at *confidence*.
    """
    if user_label.lower() != ml_prediction.lower():
        return 0
    if confidence >= 0.80:
        return POINTS_HIGH
    if confidence >= 0.50:
        return POINTS_MEDIUM
    return POINTS_LOW


def _compute_and_update(
    annotations: list[dict[str, Any]],
    task_index: dict[str, dict[str, Any]],
) -> int:
    """
    Iterate over annotations, compute points, and update task files.
    Returns the total number of task files updated.
    """
    updated = 0
    for ann in annotations:
        url = ann["url"]
        if url not in task_index:
            log.debug("No task found for annotation URL %s — skipping.", url)
            continue

        entry = task_index[url]
        task: dict[str, Any] = entry["task"]
        task_path: Path = entry["path"]

        ml_prediction: str = task.get("ml_prediction", "")
        confidence: float = float(task.get("confidence") or 0.0)
        user_label: str = ann.get("user_label", "")

        points = _award_points(ml_prediction, confidence, user_label)
        # Reset points before setting to avoid double-counting on pipeline re-runs.
        task["points"] = points

        task_path.write_text(json.dumps(task, indent=2), encoding="utf-8")
        updated += 1
        log.info(
            "URL=%s  user_label=%s  ml_prediction=%s  confidence=%.2f  points_awarded=%d",
            url,
            user_label,
            ml_prediction,
            confidence,
            points,
        )

    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    task_index = _load_task_index()
    if not task_index:
        log.info("No tasks with ML predictions available. Skipping point computation.")
        return

    annotations = _load_annotations()
    if not annotations:
        log.info("No annotations found. Skipping point computation.")
        return

    updated = _compute_and_update(annotations, task_index)
    log.info("Stage 8 complete. Points updated in %d task file(s).", updated)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error in compute_points: %s", exc)
        sys.exit(1)
