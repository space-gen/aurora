# GitHub Actions Workflows

> Support Aurora: [GitHub Sponsors](https://github.com/sponsors/soumyadipkarforma) · [Patreon](https://www.patreon.com/SoumyadipKarforma) · [Buy Me a Coffee](https://buymeacoffee.com/soumyadipkarforma)

SolarHub is an entirely automated platform. All orchestration—from data collection to model evaluation—is handled by GitHub Actions.

---

## 1. Nightly Pipeline (`pipeline.yml`)

This is the primary engine of SolarHub.

- **Trigger**: `00:30 UTC` daily or via manual `workflow_dispatch`.
- **Primary Tasks**:
  - Locks the `data/` directory to prevent frontend inconsistency.
  - Crawls JSOC for the previous day's solar images.
  - Synchronizes local user annotations to HuggingFace datasets.
  - Generates new task templates for the next 24 hours.
  - Unlocks the repository by restoring the `data/` directory.

---

## 2. Parse Annotation Issue (`parse_annotation_issue.yml`)

Handles real-time community contributions.

- **Trigger**: When a GitHub Issue is created or labeled with `annotation`.
- **Workflow**:
  1. Executes `scripts/parse_issue_annotation.py`.
  2. Commits the new annotation JSON directly to the repository.
  3. Comments on the issue to acknowledge the contributor.
  4. Automatically closes the issue as "completed."

---

## 3. Deploy Documentation (`docs_deploy.yml`)

Manages the SolarHub Aurora documentation portal (this site).

- **Trigger**: Any push to the `main` branch that modifies the `docs/` folder.
- **Workflow**:
  1. Builds the Docusaurus site.
  2. Deploys the static assets to **GitHub Pages**.

---

## 4. Setup Platforms (`setup_platforms.yml`)

Used for initial project bootstrapping.

- **Trigger**: Manual `workflow_dispatch` only.
- **Workflow**: Runs `scripts/setup_platforms.py` to initialize HuggingFace and Kaggle integrations.

---

## Workflow Permissions

GitHub Actions requires specific permissions to operate:

- **`contents: write`**: To commit new task URLs and user annotations.
- **`issues: write`**: To comment on and close annotation submissions.
- **`id-token: write`**: For secure authentication with external cloud platforms.

## Error Recovery

If a workflow fails, the system is designed to "fail safe":
- **`pipeline.yml`**: Includes an `unlock-on-failure` stage that renames `data_processing/` back to `data/` to ensure the platform remains accessible to users.
- **Logs**: Detailed logs are preserved in the Actions tab for at least 90 days to assist in debugging data ingestion or synchronization issues.
