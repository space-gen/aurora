"""
import_kaggle_predictions.py
============================
Pipeline Stage 7 — Import Kaggle Predictions

Download the predictions.json output from the Kaggle inference kernel and
write the ``ml_prediction`` and ``confidence`` values back into the
corresponding task files in data_processing/.

Architecture note
-----------------
Kaggle is used **only for compute** — no data is stored in Kaggle.

* Training kernel: reads annotation data from the HuggingFace per-task
  annotation datasets (``SpaceGen/solarhub-{task_type}``), trains a model,
  and pushes the model directly to the corresponding HuggingFace model repo
  (``SpaceGen/solarhub-model-{task_type}``) using an ``HF_TOKEN`` Kaggle
  Secret.

* Inference kernel: reads task URLs from the HuggingFace per-task datasets
  (``tasks`` split written by ``prepare_hf_training_data.py``), pulls the
  model from the HuggingFace model repo, runs inference, and writes
  ``predictions.json`` as a kernel output file.

This script then downloads that ``predictions.json`` and applies the
predictions to the local task files.

Environment variables (populated from GitHub Actions secrets):
  KAGGLE_USERNAME — Kaggle account username (required).
  KAGGLE_KEY      — Kaggle API key (required).

Usage:
    python scripts/import_kaggle_predictions.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
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

# Kaggle kernel that produces predictions.json as an output file.
KAGGLE_INFERENCE_KERNEL = "solarhub/solarhub-inference"

# Name of the output file produced by the Kaggle inference kernel.
PREDICTIONS_FILENAME = "predictions.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _configure_kaggle_credentials() -> None:
    """
    Configure Kaggle credentials.
    Supports both KAGGLE_API_TOKEN (preferred for CLI 2.0+) 
    and KAGGLE_USERNAME/KAGGLE_KEY pairs.
    """
    api_token = os.environ.get("KAGGLE_API_TOKEN", "")
    username = os.environ.get("KAGGLE_USERNAME", "")
    key = os.environ.get("KAGGLE_KEY", "")

    if api_token:
        log.info("Kaggle credentials configured via KAGGLE_API_TOKEN.")
        return

    missing = []
    if not username: missing.append("KAGGLE_USERNAME")
    if not key: missing.append("KAGGLE_KEY")
    
    if missing:
        log.error(
            "Missing required environment variable(s): %s. "
            "Set KAGGLE_API_TOKEN or both KAGGLE_USERNAME and KAGGLE_KEY.",
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
    log.info("Kaggle credentials configured from username/key pair.")


def _download_predictions(tmp_dir: str) -> Path:
    """
    Pull the latest predictions.json output file from the Kaggle inference
    kernel into *tmp_dir* and return its path.
    """
    username = os.environ.get("KAGGLE_USERNAME", "")
    if not username:
        log.error("KAGGLE_USERNAME not set.")
        sys.exit(1)
    
    kernel_id = f"{username}/solarhub-inference"

    try:
        from kaggle import KaggleApi  # type: ignore[import]
    except ImportError as exc:
        log.error("kaggle package not installed: %s. Run: pip install kaggle", exc)
        sys.exit(1)

    api = KaggleApi()
    api.authenticate()

    log.info("Downloading kernel output '%s' from %s.", PREDICTIONS_FILENAME, kernel_id)
    api.kernels_output(kernel_id, path=tmp_dir)

    predictions_path = Path(tmp_dir) / PREDICTIONS_FILENAME
    if not predictions_path.exists():
        log.error(
            "Expected output file '%s' not found in kernel output. "
            "Ensure the inference kernel produces this file.",
            PREDICTIONS_FILENAME,
        )
        sys.exit(1)

    log.info("Downloaded predictions to %s.", predictions_path)
    return predictions_path


def _load_predictions(predictions_path: Path) -> dict[str, dict[str, Any]]:
    """
    Parse predictions.json.  Expected format — a JSON object keyed by URL:

    {
      "https://solar-data-source/img.jpg": {
        "ml_prediction": "active_region",
        "confidence": 0.92
      },
      ...
    }
    """
    raw = json.loads(predictions_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        log.error("predictions.json must be a JSON object keyed by URL.")
        sys.exit(1)
    log.info("Loaded predictions for %d URL(s).", len(raw))
    return raw


def _apply_predictions(predictions: dict[str, dict[str, Any]]) -> int:
    """
    For each task file in data_processing/, update ml_prediction and
    confidence from *predictions*.  Returns the number of records updated.
    """
    updated = 0
    for task_path in sorted(DATA_PROCESSING_DIR.glob("*.json")):
        # Skip the model accuracy report itself
        if task_path.name == "model_accuracy.json":
            continue

        try:
            content = json.loads(task_path.read_text(encoding="utf-8"))
            if isinstance(content, list):
                records = content
                is_list = True
            else:
                records = [content]
                is_list = False
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping unreadable task file %s: %s", task_path.name, exc)
            continue

        file_changed = False
        for task in records:
            url = task.get("url")
            if not url or url not in predictions:
                continue

            pred = predictions[url]
            task["ml_prediction"] = pred.get("ml_prediction")
            task["confidence"] = pred.get("confidence")
            updated += 1
            file_changed = True
            log.debug("Updated prediction for %s", url)

        if file_changed:
            output_content = records if is_list else records[0]
            task_path.write_text(json.dumps(output_content, indent=2), encoding="utf-8")

    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _configure_kaggle_credentials()

    with tempfile.TemporaryDirectory() as tmp_dir:
        predictions_path = _download_predictions(tmp_dir)
        predictions = _load_predictions(predictions_path)

    updated = _apply_predictions(predictions)
    log.info("Stage 7 complete. %d task file(s) updated with ML predictions.", updated)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error in import_kaggle_predictions: %s", exc)
        sys.exit(1)
