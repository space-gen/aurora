# Contributing Annotations

SolarHub relies on citizen scientists to provide the ground-truth data needed to train our machine-learning models. Contributing is easy and handled entirely through GitHub Issues.

## How to Contribute

The **SolarHub UI (Repo A)** facilitates this process by providing a graphical interface for classification. However, if you're comfortable with JSON and GitHub, you can contribute directly.

### 1. Identify a Task
Check the `annotations/` directory for task JSON files (e.g., `sunspot.json`). These files contain blank templates waiting for labels.

### 2. Submit a GitHub Issue
To contribute a label, create a new issue in this repository with the label `annotation`. Use the following format:

#### Issue Body Template

```markdown
### Task Type
sunspot

### Record ID
sp-1234

### Your Label
active_region

### Pixel Coordinates
450,210; 460,215
```

- **Task Type**: Must be one of `sunspot`, `magnetogram`, `solar_flare`, etc.
- **Record ID**: The unique ID found in the task JSON.
- **Your Label**: A valid classification label for that task type.
- **Pixel Coordinates**: (Optional) A semicolon-separated list of `x,y` pairs representing the centers of identified features.

### 3. Automated Processing
Once your issue is submitted and labeled as `annotation`:
1. The **`Parse Annotation Issue`** workflow is triggered.
2. `scripts/parse_issue_annotation.py` validates your input.
3. If valid, your contribution is merged into the local `annotations/` directory.
4. The issue is automatically acknowledged and closed.

## Valid Labels

To ensure high data quality, please use only these predefined labels:

| Task Type | Valid Labels |
|-----------|--------------|
| **Sunspot** | `active_region`, `quiet_sun`, `sunspot_group`, `no_sunspot` |
| **Magnetogram** | `bipolar_active`, `unipolar`, `complex`, `quiet` |
| **Solar Flare** | `a_class`, `b_class`, `c_class`, `m_class`, `x_class`, `no_flare` |

---

## What Happens Next?
Your contribution is stored locally in the `annotations/` directory. During the next **Nightly Pipeline** run (00:30 UTC), it will be merged into the master HuggingFace dataset and used to retrain our solar prediction models.
