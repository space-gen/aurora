"""
merge_annotations_to_hf.py
===========================
Pipeline Stage 3 — Merge Annotations

Read pending annotation files from annotations/ and append them to the
per-task-type HuggingFace datasets.  Each annotation is routed to the
dataset that matches its ``task_type`` field:

  sunspot       → spacegen/solarhub-sunspot
  solar_flare   → spacegen/solarhub-solar-flare
  magnetogram   → spacegen/solarhub-magnetogram
  coronal_hole  → spacegen/solarhub-coronal-hole
  prominence    → spacegen/solarhub-prominence
  active_region → spacegen/solarhub-active-region
  cme           → spacegen/solarhub-cme

After a successful push the annotation file content is cleared (the file
itself is kept as an empty placeholder).

Environment variables (populated from GitHub Actions secrets):
  HF_TOKEN — HuggingFace write token (required).

Usage:
    python scripts/merge_annotations_to_hf.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections import defaultdict
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
ANNOTATIONS_DIR = REPO_ROOT / "annotations"

# Prefix for per-task HuggingFace dataset repo IDs.
HF_DATASET_REPO_PREFIX = "spacegen/solarhub-"

# Required fields that every annotation file must contain.
REQUIRED_FIELDS = {"url", "task_type", "user_label"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hf_repo_for_task(task_type: str) -> str:
    """Return the HuggingFace dataset repo ID for *task_type*.

    e.g. ``solar_flare`` → ``spacegen/solarhub-solar-flare``.
    """
    return HF_DATASET_REPO_PREFIX + task_type.replace("_", "-")


def _get_hf_token() -> str:
    """Read and validate the HuggingFace API token from the environment."""
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        log.error(
            "HF_TOKEN environment variable is not set. "
            "Cannot push annotations to HuggingFace. "
            "Add HF_TOKEN as a GitHub Actions secret."
        )
        sys.exit(1)
    return token


def _load_annotation_files() -> list[tuple[Path, dict[str, Any]]]:
    """
    Return a list of (path, annotation_dict) for all non-empty annotation
    JSON files in the annotations/ directory.
    """
    results: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(ANNOTATIONS_DIR.glob("*.json")):
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            log.debug("Skipping empty annotation file: %s", path.name)
            continue
        try:
            annotation = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("Skipping malformed annotation file %s: %s", path.name, exc)
            continue
        missing = REQUIRED_FIELDS - annotation.keys()
        if missing:
            log.warning(
                "Skipping annotation %s — missing required fields: %s",
                path.name,
                missing,
            )
            continue
        results.append((path, annotation))
    return results


def _push_annotations_to_hf(
    annotations: list[dict[str, Any]],
    token: str,
    repo_id: str,
) -> bool:
    """
    Append *annotations* to the HuggingFace dataset *repo_id*.

    Returns True on success, False on failure.
    """
    try:
        from datasets import Dataset  # type: ignore[import]
    except ImportError as exc:
        log.error(
            "Required packages not installed: %s. "
            "Run: pip install datasets huggingface_hub",
            exc,
        )
        return False

    log.info(
        "Pushing %d annotation(s) to HuggingFace dataset '%s'.",
        len(annotations),
        repo_id,
    )

    # Normalise annotations to only include dataset-relevant fields.
    records = [
        {
            "url": a["url"],
            "task_type": a["task_type"],
            "user_label": a["user_label"],
            "metadata": json.dumps(a.get("metadata", {})),
        }
        for a in annotations
    ]

    try:
        dataset = Dataset.from_list(records)

        dataset.push_to_hub(
            repo_id,
            token=token,
            split="train",
        )
        log.info("Successfully pushed %d annotation(s) to '%s'.", len(records), repo_id)
        return True
    except Exception as exc:  # pylint: disable=broad-except
        log.error("Failed to push annotations to '%s': %s", repo_id, exc)
        return False


def _clear_annotation_file(path: Path) -> None:
    """Overwrite the annotation file with an empty JSON object placeholder."""
    path.write_text("{}\n", encoding="utf-8")
    log.info("Cleared annotation file: %s", path.name)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    token = _get_hf_token()

    annotation_pairs = _load_annotation_files()
    if not annotation_pairs:
        log.info("No pending annotations found. Stage 3 complete.")
        return

    log.info("Found %d pending annotation file(s).", len(annotation_pairs))

    # Group annotation paths and dicts by task_type.
    by_task: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    for path, ann in annotation_pairs:
        by_task[ann["task_type"]].append((path, ann))

    failed_task_types: list[str] = []
    cleared_paths: list[Path] = []

    for task_type, pairs in sorted(by_task.items()):
        repo_id = _hf_repo_for_task(task_type)
        annotations = [ann for _, ann in pairs]

        success = _push_annotations_to_hf(annotations, token, repo_id)
        if not success:
            log.error(
                "Annotation merge failed for task_type='%s'. "
                "Files will not be cleared.",
                task_type,
            )
            failed_task_types.append(task_type)
            continue

        for path, _ in pairs:
            _clear_annotation_file(path)
            cleared_paths.append(path)

    if failed_task_types:
        log.error(
            "Stage 3 completed with errors. Failed task type(s): %s",
            ", ".join(failed_task_types),
        )
        sys.exit(1)

    log.info(
        "Stage 3 complete. %d annotation(s) merged across %d task type(s).",
        len(cleared_paths),
        len(by_task),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error in merge_annotations_to_hf: %s", exc)
        sys.exit(1)

