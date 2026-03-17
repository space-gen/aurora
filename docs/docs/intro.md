---
sidebar_position: 1
---

> Support Aurora: [GitHub Sponsors](https://github.com/sponsors/soumyadipkarforma) · [Patreon](https://www.patreon.com/SoumyadipKarforma) · [Buy Me a Coffee](https://buymeacoffee.com/soumyadipkarforma)

# SolarHub Aurora Documentation

> Comprehensive documentation for the backend system powering the SolarHub citizen-science platform.

## Support This Project

- GitHub Sponsors: https://github.com/sponsors/soumyadipkarforma
- Patreon: https://www.patreon.com/SoumyadipKarforma
- Buy Me a Coffee: https://buymeacoffee.com/soumyadipkarforma

## What Aurora Is

Aurora is the orchestration backend for SolarHub. It coordinates:

1.  **Data Ingestion**: Daily crawling of NASA/SDO solar image URLs.
2.  **Community Labeling**: Processing user-submitted annotations from GitHub Issues.
3.  **Dataset Synchronization**: Merging local labels into HuggingFace datasets.
4.  **ML Pipelines**: Triggering Kaggle training and inference kernels.

## Production Deployment

Documentation is built from the `docs/` folder and deployed to GitHub Pages via workflow automation.

Open `http://localhost:3000/aurora/` to preview the documentation portal.
