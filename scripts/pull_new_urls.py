"""
pull_new_urls.py
================
Pipeline Stage 2 — Refresh Tasks

Fetch new solar-observation URLs from official source APIs and write them as
task JSON files into the data_processing/ workspace.

Supports paginated API responses so that millions of URLs can be pulled in a
single run.  APIs may return either a plain JSON array (single page) or a
paginated envelope:

    {"urls": [...], "page": 1, "total_pages": N}

All pages are fetched concurrently via a thread pool.

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlencode, urlunparse, parse_qs

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

# HuggingFace per-task dataset prefix used for deduplication checks.
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"

# All task types — must match configs/system_config.yaml data.task_types.
HF_TASK_TYPES: list[str] = [
    "sunspot",
    "solar_flare",
    "magnetogram",
    "coronal_hole",
    "prominence",
    "active_region",
    "cme",
]

# Maximum number of pagination pages to fetch per source API.
# Set to 0 to disable the limit (fetch all pages).
MAX_PAGES_PER_SOURCE = int(os.environ.get("SOLARHUB_MAX_PAGES", "0"))

# Number of threads used for concurrent page fetching.
FETCH_WORKERS = int(os.environ.get("SOLARHUB_FETCH_WORKERS", "8"))

# Request timeout in seconds.
REQUEST_TIMEOUT = int(os.environ.get("SOLARHUB_REQUEST_TIMEOUT", "30"))

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


def _hf_repo_for_task(task_type: str) -> str:
    """Return the HuggingFace dataset repo ID for *task_type*.

    e.g. ``solar_flare`` → ``SpaceGen/solarhub-solar-flare``.
    """
    return HF_DATASET_REPO_PREFIX + task_type.replace("_", "-")


def _load_hf_urls(token: str) -> set[str]:
    """
    Return the set of URLs already present across all per-task-type
    HuggingFace annotation datasets so we can skip adding duplicates.

    Returns an empty set if the token is absent, no datasets exist yet,
    or the ``datasets`` library is not installed.
    """
    if not token:
        return set()
    try:
        from datasets import load_dataset  # type: ignore[import]
    except ImportError:
        log.warning("'datasets' package not installed — skipping HF deduplication.")
        return set()

    all_urls: set[str] = set()
    for task_type in HF_TASK_TYPES:
        repo_id = _hf_repo_for_task(task_type)
        try:
            log.info("Loading existing URLs from HuggingFace dataset '%s'.", repo_id)
            ds = load_dataset(repo_id, token=token, split="train")
            task_urls: set[str] = set(ds["url"])
            log.info(
                "Found %d URL(s) in '%s'.", len(task_urls), repo_id
            )
            all_urls |= task_urls
        except Exception as exc:  # pylint: disable=broad-except
            log.warning(
                "Could not load HuggingFace dataset '%s' for deduplication "
                "(it may not exist yet): %s",
                repo_id,
                exc,
            )

    log.info(
        "Total of %d unique URL(s) loaded from HuggingFace for deduplication.",
        len(all_urls),
    )
    return all_urls


def _is_valid_url(url: str) -> bool:
    """
    Return True if *url* is a well-formed HTTPS URL with a non-empty host.

    This is a structural check only — no network request is made.
    """
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and bool(parsed.netloc)
    except ValueError:
        return False


def _build_page_url(api_url: str, page: int) -> str:
    """Return *api_url* with ``page=<page>`` added or replaced in the query string."""
    parsed = urlparse(api_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["page"] = [str(page)]
    new_query = urlencode({k: v[0] for k, v in sorted(params.items())})
    return urlunparse(parsed._replace(query=new_query))


def _fetch_page(api_url: str, page: int, task_type: str) -> tuple[list[str], int]:
    """
    Fetch a single page from *api_url* and return ``(urls, total_pages)``.

    The API response may be:
      • A JSON array of URL strings → single-page, total_pages=1
      • A JSON object with ``{"urls": [...], "total_pages": N}``

    Returns an empty list on any HTTP or parsing error.
    """
    page_url = _build_page_url(api_url, page) if page > 1 else api_url
    try:
        response = requests.get(page_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        log.error("HTTP error fetching %s (page %d): %s", api_url, page, exc)
        return [], 1
    except (json.JSONDecodeError, ValueError) as exc:
        log.error("Failed to parse response from %s (page %d): %s", api_url, page, exc)
        return [], 1

    if isinstance(data, list):
        # Simple array response — single page.
        urls = [str(u) for u in data if isinstance(u, str)]
        return urls, 1

    if isinstance(data, dict):
        raw_urls = data.get("urls", [])
        urls = [str(u) for u in raw_urls if isinstance(u, str)]
        total_pages = int(data.get("total_pages", 1))
        return urls, max(total_pages, 1)

    log.error(
        "Unexpected response format from %s (page %d); expected a JSON array or object.",
        api_url,
        page,
    )
    return [], 1


def _fetch_urls_from_api(api_url: str, task_type: str) -> list[str]:
    """
    Fetch all available URLs from *api_url*, following pagination if the API
    supports it.  Pages beyond the first are fetched concurrently.

    Returns a deduplicated list of valid HTTPS URL strings.
    """
    log.info("Fetching %s URLs from %s", task_type, api_url)

    # Fetch page 1 to discover the total number of pages.
    first_page_urls, total_pages = _fetch_page(api_url, 1, task_type)

    if MAX_PAGES_PER_SOURCE > 0:
        total_pages = min(total_pages, MAX_PAGES_PER_SOURCE)

    all_urls: list[str] = list(first_page_urls)

    if total_pages > 1:
        log.info(
            "API '%s' has %d page(s). Fetching pages 2-%d concurrently with %d workers.",
            api_url,
            total_pages,
            total_pages,
            FETCH_WORKERS,
        )
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            futures = {
                pool.submit(_fetch_page, api_url, p, task_type): p
                for p in range(2, total_pages + 1)
            }
            for future in as_completed(futures):
                page_num = futures[future]
                try:
                    page_urls, _ = future.result()
                    all_urls.extend(page_urls)
                    log.debug("Page %d: %d URL(s) retrieved.", page_num, len(page_urls))
                except Exception as exc:  # pylint: disable=broad-except
                    log.warning("Error fetching page %d from %s: %s", page_num, api_url, exc)

    # Validate URL format and deduplicate while preserving order.
    valid_urls: list[str] = []
    seen: set[str] = set()
    invalid_count = 0
    for url in all_urls:
        if url in seen:
            continue
        seen.add(url)
        if _is_valid_url(url):
            valid_urls.append(url)
        else:
            log.debug("Skipping invalid URL from %s: %s", api_url, url)
            invalid_count += 1

    if invalid_count:
        log.warning(
            "%d invalid URL(s) discarded from %s.", invalid_count, api_url
        )

    log.info(
        "Retrieved %d valid URL(s) for task_type=%s (across %d page(s)).",
        len(valid_urls),
        task_type,
        total_pages,
    )
    return valid_urls


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
    sources_failed = 0
    for source in SOURCE_APIS:
        task_type = source["task_type"]
        api_url = source["api_url"]
        try:
            urls = _fetch_urls_from_api(api_url, task_type)
            if not urls:
                # If the API returned success but empty list, we don't count it as a failure
                # but we still log it.
                log.info("API for %s returned 0 URLs.", task_type)
        except Exception as exc:
            log.error("Failed to fetch URLs for %s from %s: %s", task_type, api_url, exc)
            sources_failed += 1
            continue

        for url in urls:
            if url in existing_urls:
                log.debug("Skipping duplicate URL: %s", url)
                continue
            out_path = _write_task_file(url, task_type, total_written)
            existing_urls.add(url)
            total_written += 1
            log.debug("Written: %s", out_path.name)

        log.info(
            "task_type=%s: wrote new task files (running total: %d).",
            task_type,
            total_written,
        )

    log.info("Stage 2 complete. %d new task file(s) written.", total_written)

    if total_written == 0 and sources_failed == len(SOURCE_APIS):
        log.error("All source APIs failed to return data. Exiting with error.")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("Unexpected error in pull_new_urls: %s", exc)
        sys.exit(1)

