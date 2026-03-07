"""
pull_new_urls.py
================
Pipeline Stage 2 — Refresh Tasks

Fetch new solar-observation URLs from official source APIs and write them as
task JSON files into the data_processing/ workspace.

Environment variables (populated from GitHub Actions secrets):
  HF_TOKEN   — HuggingFace write token (used to check for duplicate URLs
                already present in the HF dataset).

Usage:
    python scripts/pull_new_urls.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import requests

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

# HuggingFace dataset used for deduplication checks.
HF_DATASET_REPO = "spacegen/solarhub-annotations"

# Supported task types mapped to their source API endpoints.
# Each entry is a dict with at least a "url" key; additional fields are
# merged into the task JSON as-is.
SOURCE_APIS: list[dict[str, Any]] = [
    {
        "task_type": "sunspot",
        "api_url": "https://umbra.nascom.nasa.gov/latest_sunspot_urls.json",
    },
    {
        "task_type": "solar_flare",
        "api_url": "https://lasco-www.nrl.navy.mil/latest_flare_urls.json",
    },
    {
        "task_type": "magnetogram",
        "api_url": "https://jsoc.stanford.edu/latest_magnetogram_urls.json",
    },
    {
        "task_type": "coronal_hole",
        "api_url": "https://jsoc.stanford.edu/latest_coronalhole_urls.json",
    },
    {
        "task_type": "prominence",
        "api_url": "https://www.nso.edu/latest_prominence_urls.json",
    },
    {
        "task_type": "active_region",
        "api_url": "https://www.solarmonitor.org/latest_activeregion_urls.json",
    },
    {
        "task_type": "cme",
        "api_url": "https://cdaw.gsfc.nasa.gov/latest_cme_urls.json",
    },
]

# Empty task template — ml_prediction and confidence are populated later by
# the import_kaggle_predictions stage.
TASK_TEMPLATE: dict[str, Any] = {
    "url": None,
    "task_type": None,
    "ml_prediction": None,
    "confidence": None,
    "user_comments": [],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_hf_token() -> str:
    """Read the HuggingFace API token from the HF_TOKEN environment variable."""
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        log.warning(
            "HF_TOKEN environment variable is not set. "
            "Duplicate-URL checking against the HF dataset will be skipped."
        )
    return token


def _load_hf_urls(token: str) -> set[str]:
    """
    Return the set of URLs already present in the HuggingFace annotation
    dataset so we can skip adding them as new tasks.

    Returns an empty set if the token is absent, the dataset does not yet
    exist, or the ``datasets`` library is not installed.
    """
    if not token:
        return set()
    try:
        from datasets import load_dataset  # type: ignore[import]

        log.info("Loading existing URLs from HuggingFace dataset '%s'.", HF_DATASET_REPO)
        ds = load_dataset(HF_DATASET_REPO, token=token, split="train")
        urls: set[str] = set(ds["url"])
        log.info("Found %d URL(s) already in the HuggingFace dataset.", len(urls))
        return urls
    except ImportError:
        log.warning("'datasets' package not installed — skipping HF deduplication.")
        return set()
    except Exception as exc:  # pylint: disable=broad-except
        log.warning(
            "Could not load HuggingFace dataset for deduplication (it may not exist yet): %s",
            exc,
        )
        return set()


def _fetch_urls_from_api(api_url: str, task_type: str) -> list[str]:
    """
    Call a source API and return a list of observation URLs.

    The API is expected to return a JSON array of strings, e.g.:
        ["https://example.com/img1.jpg", "https://example.com/img2.jpg"]

    Falls back to an empty list on any HTTP or parsing error.
    """
    log.info("Fetching %s URLs from %s", task_type, api_url)
    try:
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        urls = response.json()
        if not isinstance(urls, list):
            log.error("Unexpected response format from %s; expected a JSON array.", api_url)
            return []
        log.info("Retrieved %d URL(s) for task_type=%s", len(urls), task_type)
        return [str(u) for u in urls]
    except requests.RequestException as exc:
        log.error("HTTP error fetching %s: %s", api_url, exc)
        return []
    except (json.JSONDecodeError, ValueError) as exc:
        log.error("Failed to parse response from %s: %s", api_url, exc)
        return []


def _load_existing_urls() -> set[str]:
    """
    Return the set of URLs already present in data_processing/ task files.
    Used to avoid creating duplicate task entries.
    """
    existing: set[str] = set()
    for path in DATA_PROCESSING_DIR.glob("*.json"):
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
            if "url" in task and task["url"]:
                existing.add(task["url"])
        except (json.JSONDecodeError, OSError):
            pass
    return existing


def _write_task_file(url: str, task_type: str, index: int) -> Path:
    """Persist a single task JSON file to data_processing/."""
    task = {**TASK_TEMPLATE, "url": url, "task_type": task_type}
    safe_type = task_type.replace(" ", "_")
    filename = f"task_{safe_type}_{index:06d}.json"
    out_path = DATA_PROCESSING_DIR / filename
    out_path.write_text(json.dumps(task, indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    DATA_PROCESSING_DIR.mkdir(parents=True, exist_ok=True)

    token = _get_hf_token()

    # Combine URLs already in data_processing/ with those already on HuggingFace.
    existing_urls = _load_existing_urls()
    hf_urls = _load_hf_urls(token)
    existing_urls |= hf_urls
    log.info(
        "Deduplication set: %d URL(s) (%d local + %d from HuggingFace).",
        len(existing_urls),
        len(existing_urls) - len(hf_urls),
        len(hf_urls),
    )

    total_written = 0
    for source in SOURCE_APIS:
        task_type = source["task_type"]
        api_url = source["api_url"]
        urls = _fetch_urls_from_api(api_url, task_type)

        for url in urls:
            if url in existing_urls:
                log.debug("Skipping duplicate URL: %s", url)
                continue
            out_path = _write_task_file(url, task_type, total_written)
            existing_urls.add(url)
            total_written += 1
            log.info("Written: %s", out_path.name)

    log.info("Stage 2 complete. %d new task file(s) written.", total_written)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error in pull_new_urls: %s", exc)
        sys.exit(1)
