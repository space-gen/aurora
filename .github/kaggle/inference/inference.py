import os
import json
import logging
import requests
import base64
from datasets import load_dataset
from huggingface_hub import hf_hub_download

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
TASK_TYPES = ["sunspot", "solar_flare", "magnetogram", "coronal_hole", "prominence", "active_region", "cme"]
HF_MODEL_REPO_PREFIX = "SpaceGen/solarhub-model-"
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"
GITHUB_REPO = "space-gen/aurora"
BRANCH = "main"

def run_inference(task_type, hf_token):
    dataset_repo = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
    model_repo = f"{HF_MODEL_REPO_PREFIX}{task_type.replace('_', '-')}"
    
    predictions = {}
    
    try:
        # 1. Download latest model
        logger.info(f"Downloading model from {model_repo}")
        try:
            model_path = hf_hub_download(repo_id=model_repo, filename="model.pt", token=hf_token)
        except Exception as e:
            logger.warning(f"Could not download model for {task_type}: {e}. Skipping.")
            return {}

        # 2. Load tasks (URLs) from HF
        logger.info(f"Loading tasks from {dataset_repo}")
        dataset = load_dataset(dataset_repo, token=hf_token, split="tasks")
        
        # 3. Run Mock Inference
        for record in dataset:
            url = record.get("url")
            if url:
                # Placeholder logic
                predictions[url] = {
                    "ml_prediction": "mock_label",
                    "confidence": 0.85
                }
        
        logger.info(f"Generated {len(predictions)} predictions for {task_type}")
        
    except Exception as e:
        logger.error(f"Failed inference for {task_type}: {e}")
        
    return predictions

def push_to_github(filename, content, gh_token):
    """Commits file directly to GitHub repo using REST API."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    
    # 1. Get existing file sha if it exists
    headers = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github.v3+json"}
    r = requests.get(url, headers=headers)
    sha = None
    if r.status_code == 200:
        sha = r.json().get("sha")
    
    # 2. Create/Update file
    payload = {
        "message": f"chore: upload {filename} from Kaggle [skip ci]",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha
        
    r = requests.put(url, headers=headers, data=json.dumps(payload))
    if r.status_code in [200, 201]:
        logger.info(f"Successfully pushed {filename} to GitHub.")
    else:
        logger.error(f"Failed to push to GitHub: {r.status_code} {r.text}")

def trigger_workflow(gh_token, workflow_id="07_evaluate_model_accuracy.yml"):
    """Triggers the next stage in the pipeline."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow_id}/dispatches"
    headers = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github.v3+json"}
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

    all_predictions = {}
    for task_type in TASK_TYPES:
        task_preds = run_inference(task_type, hf_token)
        all_predictions.update(task_preds)

    # Convert to JSON string
    pred_content = json.dumps(all_predictions, indent=2)
    
    # Push to GitHub
    push_to_github("predictions.json", pred_content, gh_token)
    
    # Trigger Stage 08 (Evaluation)
    trigger_workflow(gh_token)

if __name__ == "__main__":
    main()