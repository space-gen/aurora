"""scripts/squash_history.py
Monthly run to call huggingface_hub.HfApi.super_squash_history for each HF dataset repo created by the pipeline.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys

import yaml
from huggingface_hub import HfApi

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    token = os.environ.get("HF_TOKEN")
    if not token:
        log.error("HF_TOKEN not set in environment.")
        return 2

    repo_root = Path(__file__).resolve().parent.parent
    config_file = repo_root / "configs" / "system_config.yaml"
    if not config_file.exists():
        log.error("Missing system_config.yaml at %s", config_file)
        return 2

    with open(config_file, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    prefix = cfg.get("huggingface", {}).get("dataset_repo_prefix")
    task_types = cfg.get("data", {}).get("task_types", [])

    if not prefix or not task_types:
        log.error("Invalid config: dataset_repo_prefix or task_types missing")
        return 2

    api = HfApi(token=token)

    for t in task_types:
        repo_id = f"{prefix}{t.replace('_', '-')}"
        try:
            log.info("Squashing history for %s", repo_id)
            # Call super_squash_history on the dataset repo
            # signature may accept repo_id, repo_type and token
            api.super_squash_history(repo_id=repo_id, repo_type="dataset", token=token)
            log.info("Completed squash for %s", repo_id)
        except Exception as exc:
            log.exception("Failed to squash %s: %s", repo_id, exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
