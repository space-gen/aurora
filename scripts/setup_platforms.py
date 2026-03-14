"""
setup_platforms.py
==================
Initialise HuggingFace annotation dataset repositories.
Sets them to Public and AGPL v3.
"""

import os
import sys
import logging
from huggingface_hub import HfApi

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

TASK_TYPES = ["sunspot", "solar_flare", "magnetogram", "coronal_hole", "prominence", "active_region", "cme"]
HF_REPO_PREFIX = "SpaceGen/solarhub-"

def main():
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("HF_TOKEN missing.")
        sys.exit(1)

    api = HfApi(token=token)
    for task in TASK_TYPES:
        repo_id = f"{HF_REPO_PREFIX}{task.replace('_', '-')}"
        try:
            log.info(f"Setting up {repo_id}")
            api.create_repo(repo_id=repo_id, repo_type="dataset", private=False, exist_ok=True)
            # License/Metadata handled via repo cards or manual setup
        except Exception as e:
            log.error(f"Failed {repo_id}: {e}")

if __name__ == "__main__":
    main()
