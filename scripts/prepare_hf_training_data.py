"""
prepare_hf_training_data.py
============================
Pipeline Stage 5 (pre-training) — Push Task Records to HuggingFace

Write the current data_processing/ task records to HuggingFace so that
Kaggle training and inference kernels can pull task data directly from HF
instead of from Kaggle datasets.

One HuggingFace dataset split is updated per task type:
  • Split ``train``  — user annotations (managed by merge_annotations_to_hf.py)
  • Split ``tasks``  — task records from data_processing/, written by THIS script

Kaggle kernels read from HF:
  • Training kernel: reads the ``train`` split (annotations) to train models,
    then pushes trained model weights to SpaceGen/solarhub-model-{task_type}.
  • Inference kernel: reads the ``tasks`` split (task URLs + existing predictions)
    to produce a new predictions.json.

HuggingFace repos updated (one per task type with new task records):
  SpaceGen/solarhub-sunspot       (split: tasks)
  SpaceGen/solarhub-solar-flare   (split: tasks)
  SpaceGen/solarhub-magnetogram   (split: tasks)
  SpaceGen/solarhub-coronal-hole  (split: tasks)
  SpaceGen/solarhub-prominence    (split: tasks)
  SpaceGen/solarhub-active-region (split: tasks)
  SpaceGen/solarhub-cme           (split: tasks)

Environment variables (populated from GitHub Actions secrets):
  HF_TOKEN        — HuggingFace write token (required).
  KAGGLE_USERNAME — Kaggle account username (required to trigger training kernel).
  KAGGLE_KEY      — Kaggle API key (required to trigger training kernel).

Usage:
    python scripts/prepare_hf_training_data.py
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
DATA_PROCESSING_DIR = REPO_ROOT / "data_processing"

# Prefix for per-task HuggingFace annotation dataset repo IDs.
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"

# HuggingFace split name used for task records (separate from annotation "train" split).
HF_TASKS_SPLIT = "tasks"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hf_repo_for_task(task_type: str) -> str:
    """Return the HuggingFace dataset repo ID for *task_type*.

    e.g. ``solar_flare`` → ``SpaceGen/solarhub-solar-flare``.
    """
    return HF_DATASET_REPO_PREFIX + task_type.replace("_", "-")


def _get_hf_token() -> str:
    """Read and validate the HuggingFace API token from the environment."""
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        log.error(
            "HF_TOKEN environment variable is not set. "
            "Cannot push task data to HuggingFace. "
            "Add HF_TOKEN as a GitHub Actions secret."
        )
        sys.exit(1)
    return token


def _configure_kaggle_credentials() -> None:
    """
    Write KAGGLE_USERNAME and KAGGLE_KEY from environment variables to
    ~/.kaggle/kaggle.json so the kaggle CLI can trigger kernels.

    Raises SystemExit if either variable is absent.
    """
    username = os.environ.get("KAGGLE_USERNAME", "")
    key = os.environ.get("KAGGLE_KEY", "")
    missing = [name for name, val in (("KAGGLE_USERNAME", username), ("KAGGLE_KEY", key)) if not val]
    if missing:
        log.error(
            "Missing required environment variable(s): %s. "
            "Add them as GitHub Actions secrets.",
            ", ".join(missing),
        )
        sys.exit(1)

    kaggle_dir = Path.home() / ".kaggle"
    kaggle_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    creds_path = kaggle_dir / "kaggle.json"
    creds_path.write_text(
        json.dumps({"username": username, "key": key}),
        encoding="utf-8",
    )
    creds_path.chmod(0o600)
    log.info("Kaggle credentials configured from environment secrets.")


def _collect_task_records_by_type() -> dict[str, list[dict[str, Any]]]:
    """
    Read all task JSON files from data_processing/ and group them by
    ``task_type``.  Files without a ``task_type`` are skipped.
    """
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(DATA_PROCESSING_DIR.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping unreadable task file %s: %s", path.name, exc)
            continue
        task_type = record.get("task_type")
        if not task_type:
            log.warning("Skipping task file %s: missing task_type.", path.name)
            continue
        by_type[task_type].append(record)

    for task_type, records in sorted(by_type.items()):
        log.info(
            "Collected %d record(s) for task_type='%s'.", len(records), task_type
        )
    return dict(by_type)


def _push_task_records_to_hf(
    task_type: str,
    records: list[dict[str, Any]],
    token: str,
) -> None:
    """
    Push *records* as the ``tasks`` split of the per-task HuggingFace dataset.

    This overwrites the previous ``tasks`` split so that Kaggle training and
    inference kernels always see the latest set of task URLs and any existing
    ML predictions.
    """
    try:
        from datasets import Dataset  # type: ignore[import]
    except ImportError as exc:
        log.error(
            "Required packages not installed: %s. "
            "Run: pip install datasets huggingface_hub",
            exc,
        )
        sys.exit(1)

    repo_id = _hf_repo_for_task(task_type)
    log.info(
        "Pushing %d task record(s) to HuggingFace '%s' (split='%s').",
        len(records),
        repo_id,
        HF_TASKS_SPLIT,
    )

    try:
        dataset = Dataset.from_list(records)
        dataset.push_to_hub(
            repo_id,
            token=token,
            split=HF_TASKS_SPLIT,
        )
        log.info(
            "Successfully pushed %d task record(s) to '%s' split='%s'.",
            len(records),
            repo_id,
            HF_TASKS_SPLIT,
        )
    except Exception as exc:  # pylint: disable=broad-except
        log.error(
            "Failed to push task records to '%s' (split='%s'): %s",
            repo_id,
            HF_TASKS_SPLIT,
            exc,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    hf_token = _get_hf_token()
    _configure_kaggle_credentials()

    records_by_type = _collect_task_records_by_type()
    if not records_by_type:
        log.warning("No task records found in data_processing/. Skipping HuggingFace upload.")
        return

    for task_type, records in sorted(records_by_type.items()):
        _push_task_records_to_hf(task_type, records, hf_token)

    total = sum(len(r) for r in records_by_type.values())
    log.info(
        "Stage 5 complete. %d task record(s) pushed to HuggingFace across %d task type(s).",
        total,
        len(records_by_type),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error in prepare_hf_training_data: %s", exc)
        sys.exit(1)

