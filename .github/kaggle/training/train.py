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

# --- Configuration (Placeholders for Injection) ---
HF_TOKEN = "__HF_TOKEN_PLACEHOLDER__"
GH_TOKEN = "__GH_TOKEN_PLACEHOLDER__"

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
        label_str = str(record.get("user_label", "none")).lower()
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
    
    logger.info(f"--- Processing {task_type} ---")
    
    try:
        # Load dataset, handling missing 'train' split
        try:
            dataset = load_dataset(dataset_repo, token=hf_token, split="train", trust_remote_code=True)
        except Exception as e:
            logger.warning(f"Train split not found for {task_type}: {e}. Creating cold-start model.")
            dataset = []

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
                
                api = HfApi(token=hf_token)
                api.upload_file(
                    path_or_fileobj=model_path,
                    path_in_repo="model.pt",
                    repo_id=model_repo,
                    repo_type="model",
                    commit_message=f"feat: production model update for {task_type}"
                )
                return

        # Cold-start: Deploy a base model
        logger.warning(f"Insufficient data for {task_type}. Deploying base ResNet-50.")
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
            commit_message=f"chore: initialise cold-start model for {task_type}"
        )
        
    except Exception as e:
        logger.error(f"Failed for {task_type}: {e}")

def trigger_next_workflow(gh_token, workflow_id="06_trigger_kaggle_inference.yml"):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow_id}/dispatches"
    headers = {"Authorization": f"Bearer {gh_token}", "Accept": "application/vnd.github.v3+json"}
    r = requests.post(url, headers=headers, json={"ref": BRANCH})
    if r.status_code == 204:
        logger.info(f"Triggered next workflow: {workflow_id}")
    else:
        logger.error(f"Failed to trigger GitHub: {r.status_code} {r.text}")

def main():
    if "__PLACEHOLDER__" in HF_TOKEN:
        logger.error("Tokens not injected.")
        return

    for task_type in TASK_TYPES:
        train_model(task_type, HF_TOKEN)

    trigger_next_workflow(GH_TOKEN)

if __name__ == "__main__":
    main()
