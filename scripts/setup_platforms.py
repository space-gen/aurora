"""
setup_platforms.py
==================
One-time Setup — Initialise HuggingFace and Kaggle Resources

Creates the HuggingFace dataset repository (``spacegen/solarhub-annotations``)
and the Kaggle dataset (``solarhub-dataset``) if they do not already exist.

Run this script **once** before the nightly pipeline is started for the first
time, or after a full reset.

Environment variables (populated from GitHub Actions secrets):
  HF_TOKEN        — HuggingFace write token (required).
  KAGGLE_USERNAME — Kaggle account username (required).
  KAGGLE_KEY      — Kaggle API key (required).

Usage:
    python scripts/setup_platforms.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

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
HF_DATASET_REPO = "spacegen/solarhub-annotations"

KAGGLE_DATASET_SLUG = "solarhub-dataset"

# The initial HuggingFace dataset schema: matches the fields written by
# merge_annotations_to_hf.py.
HF_DATASET_FEATURES = {
    "url": {"dtype": "string", "_type": "Value"},
    "task_type": {"dtype": "string", "_type": "Value"},
    "user_label": {"dtype": "string", "_type": "Value"},
    "metadata": {"dtype": "string", "_type": "Value"},
}


# ---------------------------------------------------------------------------
# HuggingFace setup
# ---------------------------------------------------------------------------

def _get_hf_token() -> str:
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        log.error(
            "HF_TOKEN environment variable is not set. "
            "Add HF_TOKEN as a GitHub Actions secret."
        )
        sys.exit(1)
    return token


def _setup_hf_dataset(token: str) -> None:
    """Create the HuggingFace annotation dataset if it does not already exist."""
    try:
        from datasets import Dataset  # type: ignore[import]
        from huggingface_hub import HfApi, DatasetCard  # type: ignore[import]
    except ImportError as exc:
        log.error(
            "Required packages not installed: %s. "
            "Run: pip install datasets huggingface_hub",
            exc,
        )
        sys.exit(1)

    api = HfApi(token=token)

    # Check if the dataset already exists.
    try:
        api.dataset_info(HF_DATASET_REPO, token=token)
        log.info("HuggingFace dataset '%s' already exists — skipping creation.", HF_DATASET_REPO)
        return
    except Exception:  # pylint: disable=broad-except
        pass  # Dataset does not exist yet; proceed to create it.

    log.info("Creating HuggingFace dataset '%s'.", HF_DATASET_REPO)

    # Push an empty dataset with the correct schema to initialise the repo.
    empty_dataset = Dataset.from_dict({
        "url": [],
        "task_type": [],
        "user_label": [],
        "metadata": [],
    })

    try:
        empty_dataset.push_to_hub(
            HF_DATASET_REPO,
            token=token,
            split="train",
            commit_message="chore: initialise solarhub-annotations dataset",
        )
        log.info("HuggingFace dataset '%s' created successfully.", HF_DATASET_REPO)
    except Exception as exc:  # pylint: disable=broad-except
        log.error("Failed to create HuggingFace dataset: %s", exc)
        sys.exit(1)

    # Add a dataset card (README).
    card_content = f"""\
---
license: cc-by-4.0
task_categories:
  - image-classification
tags:
  - solar
  - astronomy
  - citizen-science
  - solarhub
---

# SolarHub Annotations

User annotations for the [SolarHub](https://github.com/space-gen/aurora)
citizen-science solar-observation classification project.

## Dataset Fields

| Field | Description |
|-------|-------------|
| `url` | HTTPS URL of the solar observation image |
| `task_type` | Solar feature type (sunspot, solar_flare, magnetogram, coronal_hole, prominence, active_region, cme) |
| `user_label` | Human annotation label |
| `metadata` | JSON string with annotator, issue number, and timestamp |

Annotations are collected via GitHub Issues and merged nightly by the Aurora pipeline.
"""
    try:
        DatasetCard(card_content).push_to_hub(HF_DATASET_REPO, token=token)
        log.info("Dataset card pushed to '%s'.", HF_DATASET_REPO)
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("Could not push dataset card (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Kaggle setup
# ---------------------------------------------------------------------------

def _configure_kaggle_credentials() -> str:
    """Write Kaggle credentials from env vars and return the username."""
    username = os.environ.get("KAGGLE_USERNAME", "")
    key = os.environ.get("KAGGLE_KEY", "")
    missing = [n for n, v in (("KAGGLE_USERNAME", username), ("KAGGLE_KEY", key)) if not v]
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
    creds_path.write_text(json.dumps({"username": username, "key": key}), encoding="utf-8")
    creds_path.chmod(0o600)
    log.info("Kaggle credentials configured.")
    return username


def _setup_kaggle_dataset(username: str) -> None:
    """Create the Kaggle dataset if it does not already exist."""
    try:
        from kaggle.api.kaggle_api_extended import KaggleApiExtended  # type: ignore[import]
    except ImportError as exc:
        log.error("kaggle package not installed: %s. Run: pip install kaggle", exc)
        sys.exit(1)

    api = KaggleApiExtended()
    api.authenticate()

    dataset_id = f"{username}/{KAGGLE_DATASET_SLUG}"

    # Check if the dataset already exists.
    try:
        api.dataset_status(username, KAGGLE_DATASET_SLUG)
        log.info("Kaggle dataset '%s' already exists — skipping creation.", dataset_id)
        return
    except Exception:  # pylint: disable=broad-except
        pass  # Dataset does not exist; proceed to create it.

    log.info("Creating Kaggle dataset '%s'.", dataset_id)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Seed file — an empty JSONL so Kaggle accepts the dataset.
        (tmp_path / "tasks.jsonl").write_text("", encoding="utf-8")

        metadata = {
            "title": KAGGLE_DATASET_SLUG,
            "id": dataset_id,
            "licenses": [{"name": "CC0-1.0"}],
            "description": (
                "Solar observation task URLs for the SolarHub citizen-science platform. "
                "Updated nightly by the Aurora pipeline."
            ),
        }
        (tmp_path / "dataset-metadata.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )

        try:
            api.dataset_create_new(
                folder=str(tmp_path),
                public=False,
                quiet=False,
                dir_mode="zip",
            )
            log.info("Kaggle dataset '%s' created successfully.", dataset_id)
        except Exception as exc:  # pylint: disable=broad-except
            log.error("Failed to create Kaggle dataset: %s", exc)
            sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=== SolarHub Platform Setup ===")

    # --- HuggingFace ---
    hf_token = _get_hf_token()
    _setup_hf_dataset(hf_token)

    # --- Kaggle ---
    kaggle_username = _configure_kaggle_credentials()
    _setup_kaggle_dataset(kaggle_username)

    log.info("Platform setup complete.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error in setup_platforms: %s", exc)
        sys.exit(1)
