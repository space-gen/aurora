# Configuration Reference

The SolarHub system is configured through a centralized YAML file located at `configs/system_config.yaml`. This file defines everything from our task types to our machine learning platforms.

---

## 1. System Metadata

```yaml
system:
  name: SolarHub
  codename: Aurora
  version: 1.0
```

- **`name`**: The primary name of the platform.
- **`codename`**: The project's internal name (Aurora).

---

## 2. Platform Integrations

### Machine Learning

```yaml
ml:
  training_platform: kaggle
  dataset_platform: huggingface
```

- **`training_platform`**: Defines where our ML kernels run. Currently, we use Kaggle for its GPU acceleration and free compute hours.
- **`dataset_platform`**: Where our long-term datasets are stored (HuggingFace).

---

## 3. HuggingFace Settings

```yaml
huggingface:
  dataset_repo_prefix: SpaceGen/solarhub-
  model_repo_prefix: SpaceGen/solarhub-model-
  token_secret: HF_TOKEN
```

- **`dataset_repo_prefix`**: The common prefix for all dataset repositories.
- **`model_repo_prefix`**: The common prefix for all model weight repositories.
- **`token_secret`**: The name of the GitHub Actions secret that contains the HuggingFace write token.

---

## 4. Data Task Types

The `data.task_types` section defines which solar features we currently support.

```yaml
data:
  task_types:
    - sunspot
    - solar_flare
    - magnetogram
    - coronal_hole
    - prominence
    - active_region
    - cme
```

These task types are used by:
1. **`pull_new_urls.py`**: To know which data to crawl.
2. **`parse_issue_annotation.py`**: To validate user-submitted labels.
3. **`merge_annotations_to_hf.py`**: To target the correct HuggingFace repositories.

---

## 5. Source APIs

Defines the official solar observatories we crawl for data.

```yaml
data:
  source_apis:
    - name: NASA SDAC
    - name: SOHO LASCO
    - name: SDO HMI
    ...
```

---

## 6. Annotation Strategy

```yaml
annotations:
  merge_strategy: append
  clear_after_merge: true
```

- **`merge_strategy`**: Currently set to `append`, meaning new user labels are added to our datasets without overwriting historical ones.
- **`clear_after_merge`**: (Boolean) If `true`, the local `annotations/` directory is reset after a successful push to HuggingFace.
