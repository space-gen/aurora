import os
import json
import logging
import requests
import time
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from torchvision import models, transforms
from PIL import Image
from io import BytesIO
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

# Production Training Params
BATCH_SIZE = 16
LEARNING_RATE = 1e-4
EPOCHS = 5
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def get_tokens():
    """Resilient token retrieval with retries and deep fallback."""
    hf_token = os.environ.get("HF_TOKEN")
    gh_token = os.environ.get("GH_TOKEN")
    
    if hf_token and gh_token:
        return hf_token, gh_token

    # Retry secrets client
    for attempt in range(3):
        try:
            from kaggle_secrets import UserSecretsClient
            user_secrets = UserSecretsClient()
            hf_token = hf_token or user_secrets.get_secret("HF_TOKEN")
            gh_token = gh_token or user_secrets.get_secret("GH_TOKEN")
            if hf_token and gh_token:
                return hf_token, gh_token
        except Exception as e:
            logger.warning(f"Attempt {attempt+1}: Kaggle Secrets service error: {e}")
            time.sleep(5)
            
    # Final debug log (masking values)
    logger.error(f"Tokens missing. ENV keys: {list(os.environ.keys())}")
    return hf_token, gh_token

class SolarDataset(Dataset):
    def __init__(self, hf_records, transform=None):
        self.records = [r for r in hf_records if r.get("user_label") is not None]
        self.transform = transform
        self.label_map = {"none": 0, "detected": 1}

    def __len__(self):
        return len(self.records)

    def __getitem__(self, idx):
        record = self.records[idx]
        url = record["url"]
        label_str = record.get("user_label", "none").lower()
        label = self.label_map.get(label_str, 0)

        try:
            response = requests.get(url, timeout=10)
            img = Image.open(BytesIO(response.content)).convert("RGB")
        except Exception as e:
            logger.warning(f"Failed to fetch image {url}: {e}")
            img = Image.new("RGB", (224, 224))

        if self.transform:
            img = self.transform(img)

        return img, torch.tensor(label, dtype=torch.long)

def train_model(task_type, hf_token):
    dataset_repo = f"{HF_DATASET_REPO_PREFIX}{task_type.replace('_', '-')}"
    model_repo = f"{HF_MODEL_REPO_PREFIX}{task_type.replace('_', '-')}"
    
    logger.info(f"--- Production Training for {task_type} ---")
    
    try:
        dataset = load_dataset(dataset_repo, token=hf_token, split="train", trust_remote_code=True)
        
        # If we have real data, train a real model
        if len(dataset) >= 5:
            transform = transforms.Compose([
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
            ])
            train_ds = SolarDataset(dataset, transform=transform)
            if len(train_ds) > 0:
                loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
                model = models.resnet50(weights=models.ResNet50_Weights.DEFAULT)
                model.fc = nn.Linear(model.fc.in_features, 2)
                model = model.to(DEVICE)
                criterion = nn.CrossEntropyLoss()
                optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)
                model.train()
                for epoch in range(EPOCHS):
                    running_loss = 0.0
                    for images, labels in loader:
                        images, labels = images.to(DEVICE), labels.to(DEVICE)
                        optimizer.zero_grad()
                        outputs = model(images)
                        loss = criterion(outputs, labels)
                        loss.backward()
                        optimizer.step()
                        running_loss += loss.item()
                    logger.info(f"Epoch {epoch+1} Loss: {running_loss/len(loader):.4f}")
                
                model_path = "model.pt"
                torch.save(model.state_dict(), model_path)
                
                # Deployment
                api = HfApi(token=hf_token)
                api.upload_file(
                    path_or_fileobj=model_path,
                    path_in_repo="model.pt",
                    repo_id=model_repo,
                    repo_type="model",
                    commit_message=f"feat: production model update for {task_type}"
                )
                return

        # If data is insufficient, we deploy a placeholder model to keep the loop alive
        logger.warning(f"Data for {task_type} is still sparse. Deploying placeholder model.")
        model = models.resnet50(weights=models.ResNet50_Weights.DEFAULT)
        model.fc = nn.Linear(model.fc.in_features, 2)
        model_path = "model.pt"
        torch.save(model.state_dict(), model_path)
        
        api = HfApi(token=hf_token)
        api.upload_file(
            path_or_fileobj=model_path,
            path_in_repo="model.pt",
            repo_id=model_repo,
            repo_type="model",
            commit_message=f"chore: initialise placeholder model for {task_type}"
        )
        
    except Exception as e:
        logger.error(f"Training pipeline failed for {task_type}: {e}")

def trigger_next_workflow(gh_token, workflow_id="06_trigger_kaggle_inference.yml"):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow_id}/dispatches"
    headers = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github.v3+json"}
    r = requests.post(url, headers=headers, json={"ref": BRANCH})
    if r.status_code == 204:
        logger.info(f"Triggered next workflow: {workflow_id}")
    else:
        logger.error(f"Failed to trigger GitHub: {r.status_code} {r.text}")

def main():
    hf_token, gh_token = get_tokens()
    if not hf_token or not gh_token:
        logger.error("Tokens still missing after retries. Check Kaggle Secrets configuration.")
        return

    for task_type in TASK_TYPES:
        train_model(task_type, hf_token)

    trigger_next_workflow(gh_token)

if __name__ == "__main__":
    main()
