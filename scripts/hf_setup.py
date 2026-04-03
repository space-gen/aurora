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
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HF_REPO_PREFIX = "SpaceGen/solarhub-"

# Standard AGPL v3 license text for README
AGPL_V3_LICENSE_TEXT = """
This dataset is licensed under the GNU Affero General Public License v3.0.

You can find the full license text here: https://www.gnu.org/licenses/agpl-3.0.en.html

## Terms of Use

By using this dataset, you agree to the terms of the AGPL v3 license.
This license promotes freedom, sharing, and collaboration.
"""

# Standard .gitattributes content for LFS tracking
GITATTRIBUTES_CONTENT = """* text=auto
*.jsonl filter=lfs diff=lfs merge=lfs -text"""

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
            # 1. List existing files
            files = api.list_repo_files(repo_id=repo_id, repo_type="dataset")
            
            # 2. Filter files to delete (everything except metadata)
            # We preserve README.md (tags/license) and .gitattributes (LFS config)
            to_delete = [
                f for f in files 
                if f not in ["README.md", ".gitattributes"] and not f.startswith(".github/")
            ]
            
            if not to_delete:
                log.info(f"No data files found in {repo_id}. Already clean.")
            else:
                log.info(f"Deleting {len(to_delete)} files from {repo_id}...")
                # 3. Perform deletion of data files
                for file_path in to_delete:
                    api.delete_file(
                        path_in_repo=file_path,
                        repo_id=repo_id,
                        repo_type="dataset",
                        commit_message=f"chore: data purge for {task} dataset"
                    )
                log.info(f"Successfully deleted data files from {repo_id}.")

            # 4. Ensure README.md exists with AGPL v3 license
            try:
                readme_content = api.hf_hub_download(repo_id=repo_id, filename="README.md", repo_type="dataset")
                # If README exists, we might not want to overwrite it unless it's plain text
                # For simplicity, let's overwrite it with our standard text
                log.info(f"Updating README.md for {repo_id}")
                api.upload_file(
                    path_or_fileobj=AGPL_V3_LICENSE_TEXT.encode('utf-8'),
                    path_in_repo="README.md",
                    repo_id=repo_id,
                    repo_type="dataset",
                    commit_message=f"chore: set AGPL v3 license in README for {task}"
                )
            except Exception as e: # If README.md doesn't exist
                log.info(f"Creating README.md for {repo_id}")
                api.upload_file(
                    path_or_fileobj=AGPL_V3_LICENSE_TEXT.encode('utf-8'),
                    path_in_repo="README.md",
                    repo_id=repo_id,
                    repo_type="dataset",
                    commit_message=f"chore: add AGPL v3 license README for {task}"
                )
            
            # 5. Ensure .gitattributes exists
            try:
                api.hf_hub_download(repo_id=repo_id, filename=".gitattributes", repo_type="dataset")
                log.info(".gitattributes already exists in %s.", repo_id)
            except Exception as e: # If .gitattributes doesn't exist
                log.info("Creating .gitattributes for %s", repo_id)
                api.upload_file(
                    path_or_fileobj=GITATTRIBUTES_CONTENT.encode('utf-8'),
                    path_in_repo=".gitattributes",
                    repo_id=repo_id,
                    repo_type="dataset",
                    commit_message=f"chore: add .gitattributes for LFS tracking in {task}"
                )
                
        except Exception as e:
            log.error(f"Failed processing {repo_id}: {e}")

    log.info("Cleanup process complete.")

if __name__ == "__main__":
    main()
