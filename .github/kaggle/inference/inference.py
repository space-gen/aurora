import os
import json
import logging
import requests
import base64
import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image
from io import BytesIO
from datasets import load_dataset
from huggingface_hub import hf_hub_download

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration (Placeholders for Injection) ---
HF_TOKEN = "__HF_TOKEN_PLACEHOLDER__"
GH_TOKEN = "__GH_TOKEN_PLACEHOLDER__"

TASK_TYPES = ["sunspot", "solar_flare", "magnetogram", "coronal_hole", "prominence", "active_region", "cme"]
HF_MODEL_REPO_PREFIX = "SpaceGen/solarhub-model-"
HF_DATASET_REPO_PREFIX = "SpaceGen/solarhub-"
GITHUB_REPO = "space-gen/aurora"
BRANCH = "main"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def run_inference(task_type, hf_token):
    dataset_repo = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
    model_repo = f"{HF_MODEL_REPO_PREFIX}{task_type.replace('_', '-')}"
    
    predictions = {}
    
    try:
        # 1. Download/Load Model
        logger.info(f"Loading model from {model_repo}")
        try:
            model_path = hf_hub_download(repo_id=model_repo, filename="model.pt", token=hf_token)
            model = models.resnet50()
            model.fc = nn.Linear(model.fc.in_features, 2)
            model.load_state_dict(torch.load(model_path, map_location=DEVICE))
            model = model.to(DEVICE).eval()
        except Exception as e:
            logger.warning(f"No production model found for {task_type}: {e}. using base ResNet.")
            model = models.resnet50(weights=models.ResNet50_Weights.DEFAULT)
            model.fc = nn.Linear(model.fc.in_features, 2)
            model = model.to(DEVICE).eval()

        # 2. Load tasks
        dataset = load_dataset(dataset_repo, token=hf_token, split="tasks", trust_remote_code=True)
        
        transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])

        # 3. Batch Inference (Process a subset to ensure speed in initial runs)
        limit = 100
        count = 0
        for record in dataset:
            if count >= limit: break
            url = record.get("url")
            if not url: continue
            
            try:
                resp = requests.get(url, timeout=10)
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                input_tensor = transform(img).unsqueeze(0).to(DEVICE)
                
                with torch.no_grad():
                    output = model(input_tensor)
                    prob = torch.nn.functional.softmax(output, dim=1)
                    conf, pred_idx = torch.max(prob, 1)
                
                label_map = {0: "none", 1: "detected"}
                predictions[url] = {
                    "ml_prediction": label_map.get(pred_idx.item(), "unknown"),
                    "confidence": round(conf.item(), 4)
                }
                count += 1
            except Exception as e:
                logger.warning(f"Inference failed for {url}: {e}")

        logger.info(f"Generated {len(predictions)} predictions for {task_type}")
        
    except Exception as e:
        logger.error(f"Inference pipeline failed for {task_type}: {e}")
        
    return predictions

def push_to_github(filename, content, gh_token):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    headers = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github.v3+json"}
    
    r = requests.get(url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None
    
    payload = {
        "message": f"chore: update {filename} from Kaggle production inference [skip ci]\n\nCo-authored-by: soumyadipkarforma <soumyadipkarforma@gmail.com>",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": BRANCH
    }
    if sha: payload["sha"] = sha
        
    r = requests.put(url, headers=headers, json=payload)
    if r.status_code in [200, 201]:
        logger.info(f"Pushed {filename} to GitHub.")
    else:
        logger.error(f"GitHub push failed: {r.status_code} {r.text}")

def trigger_workflow(gh_token, workflow_id="07_evaluate_model_accuracy.yml"):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow_id}/dispatches"
    headers = {"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github.v3+json"}
    r = requests.post(url, headers=headers, json={"ref": BRANCH})
    if r.status_code == 204:
        logger.info(f"Triggered evaluation: {workflow_id}")
    else:
        logger.error(f"Failed to trigger evaluation: {r.status_code}")

def main():
    if "__PLACEHOLDER__" in HF_TOKEN or "__PLACEHOLDER__" in GH_TOKEN:
        logger.error("Tokens not injected.")
        return

    all_predictions = {}
    for task_type in TASK_TYPES:
        task_preds = run_inference(task_type, HF_TOKEN)
        all_predictions.update(task_preds)

    pred_content = json.dumps(all_predictions, indent=2)
    push_to_github("predictions.json", pred_content, GH_TOKEN)
    trigger_workflow(GH_TOKEN)

if __name__ == "__main__":
    main()
