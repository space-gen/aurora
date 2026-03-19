"""
hf_setup.py
===========
Production Setup Tool for HuggingFace Datasets.
Resets (deletes and re-creates) specified datasets on HuggingFace.
Usage: python scripts/hf_setup.py [task_type1] [task_type2] ...
"""

import os
import sys
import logging
import argparse
from huggingface_hub import HfApi

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HF_REPO_PREFIX = "SpaceGen/solarhub-"

def main():
    parser = argparse.ArgumentParser(description="Initialize HuggingFace repositories for SolarHub.")
    parser.add_argument("tasks", nargs="*", help="Task types to initialize (e.g. sunspot magnetogram)")
    args = parser.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        log.error("HF_TOKEN missing.")
        sys.exit(1)

    # Use provided tasks or default set
    tasks = args.tasks if args.tasks else ["sunspot", "magnetogram"]
    
    api = HfApi(token=token)
    
    for task in tasks:
        repo_id = f"{HF_REPO_PREFIX}{task.replace('_', '-')}"
        
        # 1. Delete existing repo to purge old data
        try:
            log.info(f"Purging existing repository: {repo_id}")
            api.delete_repo(repo_id=repo_id, repo_type="dataset")
        except Exception as e:
            log.warning(f"Could not delete {repo_id} (might not exist): {e}")

        # 2. Create fresh empty repo
        try:
            log.info(f"Initializing fresh repository: {repo_id}")
            api.create_repo(repo_id=repo_id, repo_type="dataset", private=False)
            log.info(f"Successfully initialized {repo_id}")
        except Exception as e:
            log.error(f"Failed to initialize {repo_id}: {e}")

    log.info("Setup process complete.")

if __name__ == "__main__":
    main()
