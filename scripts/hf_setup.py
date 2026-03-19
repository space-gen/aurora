"""
hf_setup.py
===========
One-time Production Setup Script.
Resets (deletes and re-creates) sunspot and magnetogram datasets on HuggingFace.
Self-destructs after successful execution.
"""

import os
import sys
import logging
from huggingface_hub import HfApi
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Strictly only for these two task types
TASK_TYPES = ["sunspot", "magnetogram"]
HF_REPO_PREFIX = "SpaceGen/solarhub-"

def main():
    token = os.environ.get("HF_TOKEN")
    if not token:
        log.error("HF_TOKEN missing.")
        sys.exit(1)

    api = HfApi(token=token)
    
    for task in TASK_TYPES:
        repo_id = f"{HF_REPO_PREFIX}{task.replace('_', '-')}"
        
        # 1. Delete existing repo to purge old data
        try:
            log.info(f"Purging existing repository: {repo_id}")
            api.delete_repo(repo_id=repo_id, repo_type="dataset")
        except Exception as e:
            log.warning(f"Could not delete {repo_id} (might not exist): {e}")

        # 2. Create fresh empty repo
        try:
            log.info(f"Initializing fresh production repository: {repo_id}")
            api.create_repo(repo_id=repo_id, repo_type="dataset", private=False)
            log.info(f"Successfully initialized {repo_id}")
        except Exception as e:
            log.error(f"Failed to initialize {repo_id}: {e}")
            sys.exit(1)

    # 3. Self-Destruct
    script_path = Path(__file__).resolve()
    log.info(f"Execution complete. Self-destructing: {script_path.name}")
    try:
        os.remove(script_path)
    except Exception as e:
        log.error(f"Self-destruct failed: {e}")

if __name__ == "__main__":
    main()
