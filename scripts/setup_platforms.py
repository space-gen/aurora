"""
setup_platforms.py
==================
One-time Setup — Initialise HuggingFace and Kaggle Resources

Creates one HuggingFace dataset repository **per task type** and one Kaggle
dataset **per task type** if they do not already exist.

HuggingFace repos created (one per task type):
  spacegen/solarhub-sunspot
  spacegen/solarhub-solar-flare
  spacegen/solarhub-magnetogram
  spacegen/solarhub-coronal-hole
  spacegen/solarhub-prominence
  spacegen/solarhub-active-region
  spacegen/solarhub-cme

Kaggle datasets created (one per task type, under the authenticated user):
  solarhub-sunspot
  solarhub-solar-flare
  … etc.

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

# All supported task types — kept in sync with configs/system_config.yaml.
TASK_TYPES: list[str] = [
    "sunspot",
    "solar_flare",
    "magnetogram",
    "coronal_hole",
    "prominence",
    "active_region",
    "cme",
]

# Prefix for HuggingFace dataset repo IDs.
HF_DATASET_REPO_PREFIX = "spacegen/solarhub-"

# Prefix for Kaggle dataset slugs.
KAGGLE_DATASET_SLUG_PREFIX = "solarhub-"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _hf_repo_for_task(task_type: str) -> str:
    """Return the HuggingFace dataset repo ID for *task_type*.

    Underscores in the task type are converted to hyphens to follow
    HuggingFace naming conventions, e.g. ``solar_flare`` → ``spacegen/solarhub-solar-flare``.
    """
    return HF_DATASET_REPO_PREFIX + task_type.replace("_", "-")


def _kaggle_slug_for_task(task_type: str) -> str:
    """Return the Kaggle dataset slug for *task_type*.

    e.g. ``solar_flare`` → ``solarhub-solar-flare``.
    """
    return KAGGLE_DATASET_SLUG_PREFIX + task_type.replace("_", "-")


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


def _setup_hf_dataset_for_task(task_type: str, token: str) -> None:
    """Create the per-task HuggingFace dataset if it does not already exist."""
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

    repo_id = _hf_repo_for_task(task_type)
    api = HfApi(token=token)

    # Check if the dataset already exists.
    try:
        api.dataset_info(repo_id, token=token)
        log.info("HuggingFace dataset '%s' already exists — skipping creation.", repo_id)
        return
    except Exception:  # pylint: disable=broad-except
        pass  # Dataset does not exist yet; proceed to create it.

    log.info("Creating HuggingFace dataset '%s' (task_type=%s).", repo_id, task_type)

    # Push an empty dataset with the correct schema to initialise the repo.
    empty_dataset = Dataset.from_dict({
        "url": [],
        "task_type": [],
        "user_label": [],
        "metadata": [],
    })

    try:
        empty_dataset.push_to_hub(
            repo_id,
            token=token,
            split="train",
            commit_message=f"chore: initialise {repo_id} dataset",
        )
        log.info("HuggingFace dataset '%s' created successfully.", repo_id)
    except Exception as exc:  # pylint: disable=broad-except
        log.error("Failed to create HuggingFace dataset '%s': %s", repo_id, exc)
        sys.exit(1)

    # Add a dataset card (README).
    task_label = task_type.replace("_", " ").title()
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
  - {task_type}
---

# SolarHub — {task_label} Annotations

User annotations for the **{task_label}** task in the
[SolarHub](https://github.com/space-gen/aurora) citizen-science
solar-observation classification project.

## Dataset Fields

| Field | Description |
|-------|-------------|
| `url` | HTTPS URL of the solar observation image |
| `task_type` | Always `{task_type}` for this dataset |
| `user_label` | Human annotation label |
| `metadata` | JSON string with annotator, issue number, and timestamp |

Annotations are collected via GitHub Issues and merged nightly by the Aurora pipeline.
"""
    try:
        DatasetCard(card_content).push_to_hub(repo_id, token=token)
        log.info("Dataset card pushed to '%s'.", repo_id)
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("Could not push dataset card to '%s' (non-fatal): %s", repo_id, exc)


def _setup_all_hf_datasets(token: str) -> None:
    """Create one HuggingFace dataset per task type."""
    log.info("Setting up %d HuggingFace dataset(s) …", len(TASK_TYPES))
    for task_type in TASK_TYPES:
        _setup_hf_dataset_for_task(task_type, token)
    log.info("HuggingFace setup complete.")


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


def _setup_kaggle_dataset_for_task(task_type: str, username: str) -> None:
    """Create the per-task Kaggle dataset if it does not already exist."""
    try:
        from kaggle.api.kaggle_api_extended import KaggleApiExtended  # type: ignore[import]
    except ImportError as exc:
        log.error("kaggle package not installed: %s. Run: pip install kaggle", exc)
        sys.exit(1)

    api = KaggleApiExtended()
    api.authenticate()

    slug = _kaggle_slug_for_task(task_type)
    dataset_id = f"{username}/{slug}"

    # Check if the dataset already exists.
    try:
        api.dataset_status(username, slug)
        log.info("Kaggle dataset '%s' already exists — skipping creation.", dataset_id)
        return
    except Exception:  # pylint: disable=broad-except
        pass  # Dataset does not exist; proceed to create it.

    log.info("Creating Kaggle dataset '%s' (task_type=%s).", dataset_id, task_type)
    task_label = task_type.replace("_", " ").title()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Seed file — an empty JSONL so Kaggle accepts the dataset.
        (tmp_path / "tasks.jsonl").write_text("", encoding="utf-8")

        metadata = {
            "title": slug,
            "id": dataset_id,
            "licenses": [{"name": "CC0-1.0"}],
            "description": (
                f"Solar observation task URLs for the '{task_label}' task in the "
                "SolarHub citizen-science platform. Updated nightly by the Aurora pipeline."
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
            log.error("Failed to create Kaggle dataset '%s': %s", dataset_id, exc)
            sys.exit(1)


def _setup_all_kaggle_datasets(username: str) -> None:
    """Create one Kaggle dataset per task type."""
    log.info("Setting up %d Kaggle dataset(s) …", len(TASK_TYPES))
    for task_type in TASK_TYPES:
        _setup_kaggle_dataset_for_task(task_type, username)
    log.info("Kaggle setup complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=== SolarHub Platform Setup ===")
    log.info("Task types: %s", ", ".join(TASK_TYPES))

    # --- HuggingFace ---
    hf_token = _get_hf_token()
    _setup_all_hf_datasets(hf_token)

    # --- Kaggle ---
    kaggle_username = _configure_kaggle_credentials()
    _setup_all_kaggle_datasets(kaggle_username)

    log.info("Platform setup complete.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error in setup_platforms: %s", exc)
        sys.exit(1)

