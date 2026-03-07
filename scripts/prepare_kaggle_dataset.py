"""
prepare_kaggle_dataset.py
=========================
Pipeline Stage 5 (pre-training) — Prepare Kaggle Datasets

Build one Kaggle dataset **per task type** from the current data_processing/
task files and push each to Kaggle so that training and inference kernels can
access the latest solar-observation URLs grouped by task type.

Kaggle datasets updated (one per task type, under the authenticated user):
  solarhub-sunspot
  solarhub-solar-flare
  solarhub-magnetogram
  solarhub-coronal-hole
  solarhub-prominence
  solarhub-active-region
  solarhub-cme

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

# Prefix for per-task Kaggle dataset slugs.
KAGGLE_DATASET_SLUG_PREFIX = "solarhub-"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kaggle_slug_for_task(task_type: str) -> str:
    """Return the Kaggle dataset slug for *task_type*.

    e.g. ``solar_flare`` → ``solarhub-solar-flare``.
    """
    return KAGGLE_DATASET_SLUG_PREFIX + task_type.replace("_", "-")


def _configure_kaggle_credentials() -> str:
    """
    Write KAGGLE_USERNAME and KAGGLE_KEY from environment variables to
    ~/.kaggle/kaggle.json so the kaggle-api client can authenticate.

    Returns the username.  Raises SystemExit if either variable is absent.
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
    return username


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


def _push_task_dataset_to_kaggle(
    task_type: str,
    records: list[dict[str, Any]],
    username: str,
) -> None:
    """
    Serialize *records* as a JSONL file and push a new version of the
    per-task Kaggle dataset.

    The dataset must already exist (created by setup_platforms.py).
    """
    try:
        import kaggle  # type: ignore[import]  # noqa: F401
        from kaggle.api.kaggle_api_extended import KaggleApiExtended  # type: ignore[import]
    except ImportError as exc:
        log.error(
            "kaggle package not installed: %s. Run: pip install kaggle", exc
        )
        sys.exit(1)

    slug = _kaggle_slug_for_task(task_type)
    dataset_id = f"{username}/{slug}"

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
            "title": slug,
            "id": dataset_id,
            "licenses": [{"name": "CC0-1.0"}],
        }
        (tmp_path / "dataset-metadata.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )

        api = KaggleApiExtended()
        api.authenticate()

        log.info(
            "Pushing dataset '%s' to Kaggle (%d record(s)).",
            dataset_id,
            len(records),
        )
        # Create a new version; the dataset must already exist on Kaggle.
        api.dataset_create_version(
            folder=str(tmp_path),
            version_notes="Nightly pipeline update",
            quiet=False,
        )
        log.info("Kaggle dataset '%s' pushed successfully.", dataset_id)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    username = _configure_kaggle_credentials()

    records_by_type = _collect_task_records_by_type()
    if not records_by_type:
        log.warning("No task records found in data_processing/. Skipping Kaggle upload.")
        return

    for task_type, records in sorted(records_by_type.items()):
        _push_task_dataset_to_kaggle(task_type, records, username)

    total = sum(len(r) for r in records_by_type.values())
    log.info(
        "Stage 5 complete. %d record(s) pushed across %d task type dataset(s).",
        total,
        len(records_by_type),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error in prepare_kaggle_dataset: %s", exc)
        sys.exit(1)

