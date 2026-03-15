"""
merge_annotations_to_local.py
=============================
Updates local task JSON files in data_processing/ with user annotations
(labels and locations) found in the annotations/ folder.
"""

import json
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data_processing"
ANNOTATIONS_DIR = REPO_ROOT / "annotations"

def main():
    # 1. Load all pending annotations
    pending_annotations = {}
    for ann_file in ANNOTATIONS_DIR.glob("annotation_*.json"):
        try:
            data = json.loads(ann_file.read_text())
            if data and "id" in data:
                pending_annotations[data["id"]] = data
        except Exception as e:
            log.warning(f"Failed to read {ann_file.name}: {e}")

    if not pending_annotations:
        log.info("No pending individual annotations to merge locally.")
        return

    # 2. Update local task files
    updated_count = 0
    for task_file in DATA_DIR.glob("*.json"):
        if task_file.name == "model_accuracy.json": continue
        
        try:
            tasks = json.loads(task_file.read_text())
            changed = False
            for task in tasks:
                task_id = task.get("id")
                if task_id in pending_annotations:
                    ann = pending_annotations[task_id]
                    task["user_label"] = ann.get("user_label")
                    task["locations"] = ann.get("locations", [])
                    updated_count += 1
                    changed = True
            
            if changed:
                task_file.write_text(json.dumps(tasks, indent=2))
                log.info(f"Updated {task_file.name} with new annotations.")
        except Exception as e:
            log.error(f"Error processing {task_file.name}: {e}")

    log.info(f"Successfully merged {updated_count} annotations into local task files.")

if __name__ == "__main__":
    main()
