"""
hf_setup.py
===========
Production Cleanup Tool for HuggingFace Datasets.
Cleans the data within specified HF repositories while preserving repo settings,
licenses, and tags (README.md and .gitattributes).

Usage: python scripts/hf_setup.py task_type1 task_type2 ...
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
    parser = argparse.ArgumentParser(description="Clean data from HuggingFace repositories.")
    parser.add_argument("tasks", nargs="+", help="Task types to clean (e.g. sunspot magnetogram)")
    args = parser.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        log.error("HF_TOKEN missing.")
        sys.exit(1)

    api = HfApi(token=token)
    
    for task in args.tasks:
        repo_id = f"{HF_REPO_PREFIX}{task.replace('_', '-')}"
        log.info(f"Processing repository cleanup for: {repo_id}")
        
        try:
            # 1. List all files in the repository
            files = api.list_repo_files(repo_id=repo_id, repo_type="dataset")
            
            # 2. Filter files to delete (everything except metadata)
            # We preserve README.md (tags/license) and .gitattributes (LFS config)
            to_delete = [
                f for f in files 
                if f not in ["README.md", ".gitattributes"] and not f.startswith(".github/")
            ]
            
            if not to_delete:
                log.info(f"No data files found in {repo_id}. Already clean.")
                continue

            log.info(f"Deleting {len(to_delete)} files from {repo_id}...")
            
            # 3. Perform deletion
            for file_path in to_delete:
                api.delete_file(
                    path_in_repo=file_path,
                    repo_id=repo_id,
                    repo_type="dataset",
                    commit_message=f"chore: production data purge for {task}"
                )
            
            log.info(f"Successfully cleaned data from {repo_id}. Metadata preserved.")
            
        except Exception as e:
            log.error(f"Failed to clean {repo_id}: {e}")

    log.info("Cleanup process complete.")

if __name__ == "__main__":
    main()
