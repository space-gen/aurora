"""
prepare_kaggle_dataset.py
=========================
Pipeline Stage 5 (pre-training) — Prepare Kaggle Dataset

Build a Kaggle dataset from the current data_processing/ task files and push
it to Kaggle so that training and inference kernels can access the latest
solar-observation URLs.

Environment variables (populated from GitHub Actions secrets):
  KAGGLE_USERNAME — Kaggle account username (required).
  KAGGLE_KEY      — Kaggle API key (required).

Usage:
    python scripts/prepare_kaggle_dataset.py
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

KAGGLE_DATASET_TITLE = "solarhub-helios-dataset"
KAGGLE_DATASET_SLUG = "solarhub-helios-dataset"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _configure_kaggle_credentials() -> None:
    """
    Write KAGGLE_USERNAME and KAGGLE_KEY from environment variables to
    ~/.kaggle/kaggle.json so the kaggle-api client can authenticate.

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


def _collect_task_records() -> list[dict[str, Any]]:
    """Read all task JSON files from data_processing/ and return them as a list."""
    records: list[dict[str, Any]] = []
    for path in sorted(DATA_PROCESSING_DIR.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            records.append(record)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping unreadable task file %s: %s", path.name, exc)
    log.info("Collected %d task record(s) from data_processing/.", len(records))
    return records


def _push_dataset_to_kaggle(records: list[dict[str, Any]]) -> None:
    """
    Serialize *records* as a JSONL file and push it as a new Kaggle dataset
    version using the kaggle-api client.
    """
    try:
        import kaggle  # type: ignore[import]  # noqa: F401
        from kaggle.api.kaggle_api_extended import KaggleApiExtended  # type: ignore[import]
    except ImportError as exc:
        log.error(
            "kaggle package not installed: %s. Run: pip install kaggle", exc
        )
        sys.exit(1)

    username = os.environ["KAGGLE_USERNAME"]

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Write records as newline-delimited JSON.
        data_file = tmp_path / "tasks.jsonl"
        data_file.write_text(
            "\n".join(json.dumps(r) for r in records),
            encoding="utf-8",
        )

        # Write dataset-metadata.json required by the Kaggle API.
        metadata = {
            "title": KAGGLE_DATASET_TITLE,
            "id": f"{username}/{KAGGLE_DATASET_SLUG}",
            "licenses": [{"name": "CC0-1.0"}],
        }
        (tmp_path / "dataset-metadata.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )

        api = KaggleApiExtended()
        api.authenticate()

        log.info(
            "Pushing dataset '%s/%s' to Kaggle (%d record(s)).",
            username,
            KAGGLE_DATASET_SLUG,
            len(records),
        )
        # Create a new version; the dataset must already exist on Kaggle.
        api.dataset_create_version(
            folder=str(tmp_path),
            version_notes="Nightly pipeline update",
            quiet=False,
        )
        log.info("Kaggle dataset pushed successfully.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _configure_kaggle_credentials()
    records = _collect_task_records()
    if not records:
        log.warning("No task records found in data_processing/. Skipping Kaggle upload.")
        return
    _push_dataset_to_kaggle(records)
    log.info("Stage 5 (prepare_kaggle_dataset) complete.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error in prepare_kaggle_dataset: %s", exc)
        sys.exit(1)
