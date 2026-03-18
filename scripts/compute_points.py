"""
compute_points.py
=================
Pipeline Stage 8 — Evaluate Model Accuracy

Compare ML predictions stored in data_processing/ task files against the
user annotations in annotations/ to measure how accurately the model labels
solar observations.

Accuracy is computed globally and broken down by task type.  Results are
written to ``data_processing/model_accuracy.json`` so that subsequent stages
(and the frontend) can surface model-quality information.

No external API keys are required for this stage.

Usage:
    python scripts/compute_points.py
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
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
ACCURACY_OUTPUT_FILE = DATA_PROCESSING_DIR / "model_accuracy.json"
PREDICTIONS_FILE = REPO_ROOT / "predictions.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_predictions():
    """Reads predictions.json and updates task files in data_processing/."""
    if not PREDICTIONS_FILE.exists():
        log.warning("predictions.json not found. Skipping prediction application.")
        return

    try:
        predictions = json.loads(PREDICTIONS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("Failed to load predictions.json: %s", e)
        return

    updated = 0
    for task_path in sorted(DATA_PROCESSING_DIR.glob("*.json")):
        if task_path == ACCURACY_OUTPUT_FILE:
            continue
        try:
            content = json.loads(task_path.read_text(encoding="utf-8"))
            records = content if isinstance(content, list) else [content]
            file_changed = False
            for record in records:
                url = record.get("url")
                if url in predictions:
                    pred = predictions[url]
                    record["ml_prediction"] = pred.get("ml_prediction")
                    record["confidence"] = pred.get("confidence")
                    updated += 1
                    file_changed = True
            if file_changed:
                task_path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("Error processing %s: %s", task_path.name, e)
    log.info("Applied %d prediction(s) from predictions.json.", updated)

def _load_task_index() -> dict[str, dict[str, Any]]:
    """
    Build a URL → task dict index from all task JSON files in
    data_processing/.  Tasks without an ml_prediction are skipped because
    there is nothing to compare against yet.
    """
    index: dict[str, dict[str, Any]] = {}
    for path in sorted(DATA_PROCESSING_DIR.glob("*.json")):
        if path == ACCURACY_OUTPUT_FILE:
            continue
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(content, list):
                records = content
            else:
                records = [content]
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping unreadable task file %s: %s", path.name, exc)
            continue
        
        for task in records:
            url = task.get("url")
            if url and task.get("ml_prediction") is not None:
                index[url] = {"task": task, "path": path}
    log.info("Loaded %d task(s) with ML predictions.", len(index))
    return index


def _get_latest_label(ann: dict[str, Any]) -> str | None:
    """Extract the latest user label from the annotations list or legacy field."""
    # 1. Prefer the annotations history
    history = ann.get("annotations")
    if history and isinstance(history, list) and len(history) > 0:
        last_entry = history[-1]
        if isinstance(last_entry, dict) and "user_label" in last_entry:
            return last_entry["user_label"]
            
    # 2. Fallback to legacy top-level field
    return ann.get("user_label")

def _load_annotations() -> list[dict[str, Any]]:
    """Return all non-empty annotation records from annotations/."""
    records: list[dict[str, Any]] = []
    for path in sorted(ANNOTATIONS_DIR.glob("*.json")):
        raw = path.read_text(encoding="utf-8").strip()
        if not raw or raw == "{}":
            continue
        try:
            content = json.loads(raw)
            if isinstance(content, list):
                anns = content
            else:
                anns = [content]
        except json.JSONDecodeError as exc:
            log.warning("Skipping malformed annotation file %s: %s", path.name, exc)
            continue
        
        for ann in anns:
            label = _get_latest_label(ann)
            if ann.get("url") and label:
                records.append(ann)
    log.info("Loaded %d annotation record(s).", len(records))
    return records


def _is_correct_prediction(ml_prediction: str, user_label: str) -> bool:
    """Return True when the model prediction matches the user annotation label."""
    return user_label.lower() == ml_prediction.lower()


def _compute_accuracy(
    annotations: list[dict[str, Any]],
    task_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Compare each annotation against its corresponding ML prediction.
    """
    total = 0
    correct = 0
    per_type: dict[str, dict[str, int]] = {}

    for ann in annotations:
        url = ann["url"]
        if url not in task_index:
            log.debug("No task found for annotation URL %s — skipping.", url)
            continue

        task: dict[str, Any] = task_index[url]["task"]
        ml_prediction: str = task.get("ml_prediction", "")
        
        user_label = _get_latest_label(ann) or ""
        task_type: str = task.get("task_type", "unknown")

        match = _is_correct_prediction(ml_prediction, user_label)
        total += 1
        if match:
            correct += 1

        bucket = per_type.setdefault(task_type, {"total": 0, "correct": 0})
        bucket["total"] += 1
        if match:
            bucket["correct"] += 1

        log.info(
            "URL=%s  task_type=%s  user_label=%s  ml_prediction=%s  correct=%s",
            url,
            task_type,
            user_label,
            ml_prediction,
            match,
        )

    overall_accuracy = correct / total if total > 0 else 0.0
    per_task_type = {
        ttype: {
            "total": counts["total"],
            "correct": counts["correct"],
            "accuracy": counts["correct"] / counts["total"] if counts["total"] > 0 else 0.0,
        }
        for ttype, counts in sorted(per_type.items())
    }

    return {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "total_compared": total,
        "correct": correct,
        "accuracy": overall_accuracy,
        "per_task_type": per_task_type,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # 1. Apply ML results from Kaggle to local task files
    _apply_predictions()

    # 2. Build index for evaluation
    task_index = _load_task_index()
    if not task_index:
        log.info("No tasks with ML predictions available. Skipping accuracy evaluation.")
        return

    annotations = _load_annotations()
    if not annotations:
        log.info("No annotations found. Skipping accuracy evaluation.")
        return

    report = _compute_accuracy(annotations, task_index)

    DATA_PROCESSING_DIR.mkdir(parents=True, exist_ok=True)
    ACCURACY_OUTPUT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")

    log.info(
        "Stage 8 complete. Model accuracy: %.1f%% (%d/%d). "
        "Report written to %s.",
        report["accuracy"] * 100,
        report["correct"],
        report["total_compared"],
        ACCURACY_OUTPUT_FILE.name,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error in compute_points: %s", exc)
        sys.exit(1)
