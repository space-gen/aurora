"""
setup_platforms.py
==================
One-time Setup — Initialise HuggingFace Resources

Creates one HuggingFace **annotation dataset** repository and one HuggingFace
**model** repository per task type if they do not already exist.

HuggingFace annotation dataset repos (one per task type):
  SpaceGen/solarhub-sunspot
  SpaceGen/solarhub-solar-flare
  SpaceGen/solarhub-magnetogram
  SpaceGen/solarhub-coronal-hole
  SpaceGen/solarhub-prominence
  SpaceGen/solarhub-active-region
  SpaceGen/solarhub-cme

HuggingFace model repos (one per task type):
  SpaceGen/solarhub-model-sunspot
  SpaceGen/solarhub-model-solar-flare
  SpaceGen/solarhub-model-magnetogram
  SpaceGen/solarhub-model-coronal-hole
  SpaceGen/solarhub-model-prominence
  SpaceGen/solarhub-model-active-region
  SpaceGen/solarhub-model-cme

Kaggle is used only for compute (training & inference kernels).  No datasets
are stored in Kaggle — all data and models live on HuggingFace.  Kaggle
kernels must be configured with an ``HF_TOKEN`` Kaggle Secret so they can push
trained models directly to the HuggingFace model repos above.

Run this script **once** before the nightly pipeline is started for the first
time, or after a full reset.

Environment variables (populated from GitHub Actions secrets):
  HF_TOKEN        — HuggingFace write token (required).
  KAGGLE_USERNAME — Kaggle account username (required to verify Kaggle creds).
  KAGGLE_KEY      — Kaggle API key (required to verify Kaggle creds).

Usage:
    python scripts/setup_platforms.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
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

# Prefix for HuggingFace annotation dataset repo IDs.
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"

# Prefix for HuggingFace model repo IDs.
HF_MODEL_REPO_PREFIX = "SpaceGen/solarhub-model-"


# ---------------------------------------------------------------------------
# Shared naming helpers
# ---------------------------------------------------------------------------

def _hf_repo_for_task(task_type: str) -> str:
    """Return the HuggingFace annotation dataset repo ID for *task_type*.

    e.g. ``solar_flare`` → ``SpaceGen/solarhub-solar-flare``.
    """
    return HF_DATASET_REPO_PREFIX + task_type.replace("_", "-")


def _hf_model_repo_for_task(task_type: str) -> str:
    """Return the HuggingFace model repo ID for *task_type*.

    e.g. ``solar_flare`` → ``SpaceGen/solarhub-model-solar-flare``.
    """
    return HF_MODEL_REPO_PREFIX + task_type.replace("_", "-")


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
    """Create the per-task HuggingFace annotation dataset if it does not already exist."""
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
    model_repo_id = _hf_model_repo_for_task(task_type)
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
The corresponding trained model is published at
[{model_repo_id}](https://huggingface.co/{model_repo_id}).
"""
    try:
        DatasetCard(card_content).push_to_hub(repo_id, token=token)
        log.info("Dataset card pushed to '%s'.", repo_id)
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("Could not push dataset card to '%s' (non-fatal): %s", repo_id, exc)


def _setup_hf_model_repo_for_task(task_type: str, token: str) -> None:
    """Create the per-task HuggingFace model repository if it does not already exist.

    The model repo is where Kaggle training kernels push trained model weights
    after each nightly training run.
    """
    try:
        from huggingface_hub import HfApi, ModelCard  # type: ignore[import]
    except ImportError as exc:
        log.error(
            "Required packages not installed: %s. "
            "Run: pip install huggingface_hub",
            exc,
        )
        sys.exit(1)

    repo_id = _hf_model_repo_for_task(task_type)
    api = HfApi(token=token)

    # Check if the model repo already exists.
    try:
        api.model_info(repo_id, token=token)
        log.info("HuggingFace model repo '%s' already exists — skipping creation.", repo_id)
        return
    except Exception:  # pylint: disable=broad-except
        pass  # Model repo does not exist yet; proceed to create it.

    log.info("Creating HuggingFace model repo '%s' (task_type=%s).", repo_id, task_type)

    try:
        api.create_repo(repo_id, repo_type="model", token=token, exist_ok=True)
        log.info("HuggingFace model repo '%s' created successfully.", repo_id)
    except Exception as exc:  # pylint: disable=broad-except
        log.error("Failed to create HuggingFace model repo '%s': %s", repo_id, exc)
        sys.exit(1)

    # Add a model card (README).
    task_label = task_type.replace("_", " ").title()
    dataset_repo = _hf_repo_for_task(task_type)
    card_content = f"""\
---
license: cc-by-4.0
tags:
  - solar
  - astronomy
  - image-classification
  - solarhub
  - {task_type}
datasets:
  - {dataset_repo}
---

# SolarHub — {task_label} Model

Image classification model for the **{task_label}** task in the
[SolarHub](https://github.com/space-gen/aurora) citizen-science
solar-observation classification project.

This model is trained nightly by a Kaggle kernel on annotations collected
from [{dataset_repo}](https://huggingface.co/datasets/{dataset_repo}) and pushed
directly to this repository from the Kaggle training environment.

## Usage

```python
from huggingface_hub import hf_hub_download

model_path = hf_hub_download(repo_id="{repo_id}", filename="model.pt")
```
"""
    try:
        ModelCard(card_content).push_to_hub(repo_id, token=token)
        log.info("Model card pushed to '%s'.", repo_id)
    except Exception as exc:  # pylint: disable=broad-except
        log.warning("Could not push model card to '%s' (non-fatal): %s", repo_id, exc)


def _setup_all_hf_datasets(token: str) -> None:
    """Create one HuggingFace annotation dataset per task type."""
    log.info("Setting up %d HuggingFace annotation dataset(s) …", len(TASK_TYPES))
    for task_type in TASK_TYPES:
        _setup_hf_dataset_for_task(task_type, token)
    log.info("HuggingFace annotation dataset setup complete.")


def _setup_all_hf_model_repos(token: str) -> None:
    """Create one HuggingFace model repository per task type."""
    log.info("Setting up %d HuggingFace model repo(s) …", len(TASK_TYPES))
    for task_type in TASK_TYPES:
        _setup_hf_model_repo_for_task(task_type, token)
    log.info("HuggingFace model repo setup complete.")


# ---------------------------------------------------------------------------
# Kaggle credentials verification
# ---------------------------------------------------------------------------

def _verify_kaggle_credentials() -> None:
    """Verify that the Kaggle credentials env vars are present.

    Kaggle is used only for compute (training & inference kernels).
    No datasets are stored in Kaggle — all data and models live on HuggingFace.

    The Kaggle training kernel must be configured with an ``HF_TOKEN`` Kaggle
    Secret so it can push trained model weights directly to the per-task
    HuggingFace model repos.
    """
    username = os.environ.get("KAGGLE_USERNAME", "")
    key = os.environ.get("KAGGLE_KEY", "")
    missing = [n for n, v in (("KAGGLE_USERNAME", username), ("KAGGLE_KEY", key)) if not v]
    if missing:
        log.error(
            "Missing required Kaggle environment variable(s): %s. "
            "Add them as GitHub Actions secrets.",
            ", ".join(missing),
        )
        sys.exit(1)

    # Write credentials so the kaggle CLI can authenticate when kernels are triggered.
    kaggle_dir = Path.home() / ".kaggle"
    kaggle_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    creds_path = kaggle_dir / "kaggle.json"
    creds_path.write_text(json.dumps({"username": username, "key": key}), encoding="utf-8")
    creds_path.chmod(0o600)
    log.info("Kaggle credentials verified and configured (used for kernel triggers only).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=== SolarHub Platform Setup ===")
    log.info("Task types: %s", ", ".join(TASK_TYPES))

    # --- HuggingFace annotation datasets (one per task type) ---
    hf_token = _get_hf_token()
    _setup_all_hf_datasets(hf_token)

    # --- HuggingFace model repos (one per task type) ---
    _setup_all_hf_model_repos(hf_token)

    # --- Kaggle credentials (for kernel triggers only — no datasets in Kaggle) ---
    _verify_kaggle_credentials()

    log.info("Platform setup complete.")
    log.info(
        "IMPORTANT: Configure the Kaggle training kernel with an 'HF_TOKEN' Kaggle Secret "
        "so it can push trained models to HuggingFace after each training run."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error in setup_platforms: %s", exc)
        sys.exit(1)

