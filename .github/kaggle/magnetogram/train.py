import os
import json
import logging
import requests
import numpy as np
import tensorflow as tf
from PIL import Image
from io import BytesIO
from datasets import load_dataset
from huggingface_hub import HfApi

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration (Placeholders for Injection) ---
HF_TOKEN = "__HF_TOKEN_PLACEHOLDER__"
GH_TOKEN = "__GH_TOKEN_PLACEHOLDER__"

TASK_TYPE = "magnetogram"
HF_DATASET_REPO = f"SpaceGen/solarhub-{TASK_TYPE}"
HF_MODEL_REPO = f"SpaceGen/solarhub-model-{TASK_TYPE}"
IMG_SIZE = (224, 224)
BATCH_SIZE = 32

def download_image(url):
    try:
        response = requests.get(url, timeout=10)
        img = Image.open(BytesIO(response.content)).convert('RGB')
        img = img.resize(IMG_SIZE)
        return np.array(img) / 255.0
    except Exception as e:
        logger.warning(f"Failed to download {url}: {e}")
        return None

def train_and_export():
    logger.info(f"--- Starting Production Training for {TASK_TYPE} ---")
    
    try:
        # 1. Load Data from HF
        ds = load_dataset(HF_DATASET_REPO, token=HF_TOKEN, split="train", trust_remote_code=True)
        if len(ds) < 10:
            logger.warning("Insufficient data for training. Using cold-start logic.")
            model = tf.keras.applications.MobileNetV2(input_shape=(224, 224, 3), include_top=True, weights='imagenet')
        else:
            # Real training logic
            images = []
            labels = []
            label_map = {"none": 0, "detected": 1}
            
            for record in ds:
                img = download_image(record['url'])
                if img is not None:
                    images.append(img)
                    labels.append(label_map.get(record.get('user_label', 'none'), 0))
            
            X = np.array(images)
            y = np.array(labels)
            
            base_model = tf.keras.applications.MobileNetV2(input_shape=(224, 224, 3), include_top=False, weights='imagenet')
            base_model.trainable = False
            
            model = tf.keras.Sequential([
                base_model,
                tf.keras.layers.GlobalAveragePooling2D(),
                tf.keras.layers.Dense(1, activation='sigmoid')
            ])
            
            model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
            model.fit(X, y, epochs=5, batch_size=BATCH_SIZE)

        # 2. Export to multiple formats
        model.save("model.keras")
        converter = tf.lite.TFLiteConverter.from_keras_model(model)
        tflite_model = converter.convert()
        with open("model.tflite", "wb") as f:
            f.write(tflite_model)

        # 3. Push to HuggingFace
        api = HfApi(token=HF_TOKEN)
        for fmt in ["model.keras", "model.tflite"]:
            api.upload_file(
                path_or_fileobj=fmt,
                path_in_repo=fmt,
                repo_id=HF_MODEL_REPO,
                repo_type="model",
                commit_message=f"feat: update production {TASK_TYPE} model"
            )
        logger.info("Models successfully synced to HF.")

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")

if __name__ == "__main__":
    train_and_export()
