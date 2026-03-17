---
sidebar_position: 1
---

# SolarHub Aurora Documentation

> Comprehensive documentation for the backend system powering the SolarHub citizen-science platform.

## Support This Project

- GitHub Sponsors: https://github.com/sponsors/soumyadipkarforma
- Buy Me a Coffee: https://buymeacoffee.com/soumyadipkarforma

## What Aurora Is

Aurora is the orchestration backend for SolarHub. It coordinates:

- task URL ingestion from trusted solar data sources
- community annotation intake via GitHub Issues
- annotation sync to HuggingFace datasets
- training/inference execution on Kaggle
- prediction import + confidence scoring back into task files

## Core Documents

- [Architecture](./architecture.md)
- [Pipeline](./pipeline.md)
- [ML Flow](./ml_flow.md)

## Quick Start for Contributors

1. Open the repository README for operational context and secrets setup.
2. Use the annotation issue form in GitHub to submit structured labels.
3. Monitor Actions to track nightly pipeline stages and status.
4. Review `data/` updates after unlock stage completion.

## Local Docs Development

```bash
cd docs
npm ci
npm run start
```

Open `http://localhost:3000/aurora/` to preview the documentation portal.

## Production Deployment

Documentation is built from the `docs/` folder and deployed to GitHub Pages via workflow automation.

Only changes under the `docs/` folder trigger docs deployment.
