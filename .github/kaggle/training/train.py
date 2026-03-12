import os
import json
import logging
import requests
from datasets import load_dataset
from huggingface_hub import HfApi

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
TASK_TYPES = ["sunspot", "solar_flare", "magnetogram", "coronal_hole", "prominence", "active_region", "cme"]
HF_MODEL_REPO_PREFIX = "SpaceGen/solarhub-model-"
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"
GITHUB_REPO = "space-gen/aurora"
BRANCH = "main"

def train_model(task_type, hf_token):
    dataset_repo = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
    model_repo = f"{HF_MODEL_REPO_PREFIX}{task_type.replace('_', '-')}"
    
    logger.info(f"Training for {task_type} using dataset {dataset_repo}")
    
    try:
        # 1. Load annotations from HF
        dataset = load_dataset(dataset_repo, token=hf_token, split="train")
        logger.info(f"Loaded {len(dataset)} annotations for {task_type}")
        
        if len(dataset) == 0:
            logger.warning(f"No annotations found for {task_type}. Skipping training.")
            return

        # 2. Mock Training
        model_path = "model.pt"
        with open(model_path, "w") as f:
            f.write("MOCK_MODEL_WEIGHTS")

        # 3. Push model weights back to HF
        api = HfApi(token=hf_token)
        api.upload_file(
            path_or_fileobj=model_path,
            path_in_repo="model.pt",
            repo_id=model_repo,
            repo_type="model",
            commit_message=f"chore: update model weights for {task_type}"
        )
        logger.info(f"Model for {task_type} pushed to {model_repo}")
        
    except Exception as e:
        logger.error(f"Failed training for {task_type}: {e}")

def trigger_next_workflow(gh_token, workflow_id="06_trigger_kaggle_inference.yml"):
    """Triggers the inference stage in the pipeline."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow_id}/dispatches"
    headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {"ref": BRANCH}
    r = requests.post(url, headers=headers, data=json.dumps(payload))
    if r.status_code == 204:
        logger.info(f"Successfully triggered next workflow: {workflow_id}")
    else:
        logger.error(f"Failed to trigger workflow: {r.status_code} {r.text}")

def main():
    hf_token = os.environ.get("HF_TOKEN")
    gh_token = os.environ.get("GH_TOKEN")
    
    if not hf_token:
        logger.error("HF_TOKEN not found.")
        return
    if not gh_token:
        logger.error("GH_TOKEN not found.")
        return

    for task_type in TASK_TYPES:
        train_model(task_type, hf_token)

    # Trigger next step
    trigger_next_workflow(gh_token)

if __name__ == "__main__":
    main()