import os
import json
import logging
from datasets import load_dataset
from huggingface_hub import hf_hub_download

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
TASK_TYPES = ["sunspot", "solar_flare", "magnetogram", "coronal_hole", "prominence", "active_region", "cme"]
HF_MODEL_REPO_PREFIX = "SpaceGen/solarhub-model-"
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"

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

def main():
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        logger.error("HF_TOKEN not found in environment variables.")
        return

    all_predictions = {}
    for task_type in TASK_TYPES:
        task_preds = run_inference(task_type, hf_token)
        all_predictions.update(task_preds)

    # Save to predictions.json (which script 07 will download)
    with open("predictions.json", "w") as f:
        json.dump(all_predictions, f, indent=2)
    logger.info("predictions.json saved.")

if __name__ == "__main__":
    main()
