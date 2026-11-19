# SolarHub — Aurora

> **Backend orchestration system for the SolarHub citizen-science platform.**
>
> I’m [Soumyadip Karforma](https://github.com/soumyadipkarforma), founder of SpaceGen, the mother organisation of SolarHub. Aurora is the backend engine I designed to run our contributor-powered solar science pipeline.

[![Nightly Pipeline](https://github.com/space-gen/aurora/actions/workflows/pipeline.yml/badge.svg)](https://github.com/space-gen/aurora/actions)
[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor-GitHub-ff69b4)](https://github.com/sponsors/soumyadipkarforma)
[![Patreon](https://img.shields.io/badge/Support-Patreon-FF424D)](https://www.patreon.com/SoumyadipKarforma)
[![Buy Me a Coffee](https://img.shields.io/badge/Support-Buy%20Me%20a%20Coffee-orange)](https://buymeacoffee.com/soumyadipkarforma)

## Overview

This repository is **Repo B** of the SolarHub platform. It manages task data,
user annotations, solar observation data pipelines, and synchronisation between GitHub
and HuggingFace.

Repo A (the user-facing UI : [solarhub](https://github.com/space-gen/solarhub) ) is maintained separately and reads task files from this repository. Daily pipeline writes and annotation commits now run against the dedicated orphan `data` branch, and that branch is recreated regularly to keep history minimal.

## Tech Stack

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![GitHub Actions](https://img.shields.io/badge/github%20actions-%232671E5.svg?style=for-the-badge&logo=githubactions&logoColor=white)
![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Datasets-yellow?style=for-the-badge)
![Docusaurus](https://img.shields.io/badge/Docusaurus-3EE6AF?style=for-the-badge&logo=docusaurus&logoColor=white)
![JSON](https://img.shields.io/badge/json-5E5E5E?style=for-the-badge&logo=json&logoColor=white)

## Repository Structure

```
aurora/
├── data/                    # Active task JSON files (URLs only, no raw data)
├── data_processing/         # Temporary nightly pipeline workspace
├── annotations/             # User annotations pending HuggingFace merge
├── scripts/                 # Python pipeline scripts
│   ├── pull_new_urls.py          # Daily solar data crawler
│   ├── merge_annotations_to_hf.py # Push annotations to HuggingFace (Schema reconciled)
│   ├── parse_issue_annotation.py  # Parse GitHub issue bodies into annotation JSON
│   └── process_all_annotation_issues.py # Process open annotation issues
├── configs/                 # System configuration (YAML)
├── docs/                    # Docusaurus documentation source
├── .github/ISSUE_TEMPLATE/  # GitHub issue forms for annotation submission
└── .github/workflows/       # GitHub Actions (Pipeline, Parser, Docs Deploy)
```

## Data Schema

The data is stored in a compressed JSON Lines (JSONL) format. Each line is a minified JSON object representing a solar observation record.

**Field Order:** `id`, `url`, `task_type`, `created_at`, `metadata`, `annotations`.

### Task Record Example:
```jsonl
{"id":"mg-1428","url":"http://jsoc1.stanford.edu/data/hmi/images/2026/04/01/20260401_000000_M_1k.jpg","task_type":"magnetogram","created_at":"2026-04-02T00:02:08.160034+00:00","metadata":{"source":"JSOC_HMI_JPG","captured_at":"2026-04-01T00:00:00Z"},"annotations":[]}
```

## Submitting Annotations

Users annotate solar observations by **opening a GitHub Issue** using the *Submit Solar Observation Annotation* template. The scheduled `Parse Annotation` workflow reads open issues that have the `annotation` label or a title starting with `[Annotation]`, validates them and writes the annotation to `annotations/`. It is merged into HuggingFace during the next nightly pipeline run.

**When submitting annotations:**
*   Use the `your_label` field to submit one or more annotations in the format `label,region`. Multiple annotations are separated by a semicolon (`;`). Example: `class_a,10 1 5 2 3 ; class_h,2 7 1 4`.
*   Labels must be valid for the selected Task Type (see table above). Circles use 1024-pixel image coordinates and must fall on the solar disk for sunspot and magnetogram tasks.
*   A single GitHub username can annotate a given record ID only once. Repeat submissions for the same `id` by the same user are rejected by the parser.

## Finder Reviews

SolarHub works out the 193, 211 and 304 pictures itself from NASA's SDO browse archive. A fair coin toss on each contributor's GitHub username decides their direction: half walk back from 20 November 2026 and half walk forward from 1 October 2016, so the two groups meet in between. They move one day at a time, taking every frame (about 100 to 140 a day), so features can be tracked as they evolve. Each person's last finished picture is saved in their `solarhub-data` repository, so they carry on from there. Aurora publishes only flare tasks now.

The browser runs a copy of `scripts/find_candidates.py` (`solarhub/src/utils/finder.ts`) to propose whole dark regions in 193 and 211 and edge flames in 304. Each proposal has a circle and a `mask` in COCO compressed run-length encoding. Contributors confirm, reshape, reject or delete each proposal and draw what was missed, and SolarHub sends those decisions in the optional `Finder Review` issue field.

The browser is not trusted. For an archive picture the parser checks that the address matches NASA's pattern, that the record ID matches the image time, that the date is inside the archive range, and that the image downloads. It then reruns the Python finder on the image and counts a ring as the finder's only if Aurora's own finder found it there; the stored finder shape is always Aurora's. Anything that does not fit is rejected. An invalid review is dropped and the labels are kept.

## Science Datasets

Validated annotations are committed to the private `space-gen/aurora-annotations` repository, and each annotation issue is deleted once its data is stored. Records stay there for 30 days after they reach the Hugging Face archive.

Hugging Face datasets are private and contain science catalogues only. Raw submissions, including usernames and review details, go to the private `SpaceGen/solarhub-archive` dataset before the catalogues are rebuilt.

| Path | Contents |
| --- | --- |
| `features/<split>/<year>/<month>.jsonl` | One row per solar feature, with class, agreement, mask and solar coordinates |
| `observations/<year>/<month>.jsonl` | Image time, solar geometry and reviewed disk area |
| `stats/summary.json` | Catalogue counts, Krippendorff's alpha and detector validation |
| `stats/manifest.json` | Row counts and SHA-256 hashes |
| `README.md` | Dataset card with schema, method and limitations |

Splits are assigned by Carrington rotation. A publish stops if a merge would remove an archived image.

## Documentation

Comprehensive documentation is available at [Aurora Docs](https://space-gen.github.io/aurora/):

- [Architecture](https://space-gen.github.io/aurora/architecture)
- [Pipeline Details](https://space-gen.github.io/aurora/pipeline)
- [ML Flow](https://space-gen.github.io/aurora/ml_flow)
- [Data Schema](https://space-gen.github.io/aurora/data_schema)


## Supported Task Types

SolarHub supports rigorous scientific standards for ML training:

| Task Type | Scientific Standard |
|-----------|---------------------|
| `sunspot` | **McIntosh** |
| `magnetogram` | **Mount Wilson** |
| `aia_94`, `aia_131`, `aia_171`, `aia_335` | Bright regions and coronal loops |
| `aia_193`, `aia_211` | Coronal holes and filaments |
| `aia_304` | Filaments, prominences and bright regions |
| `aia_1600`, `aia_1700` | Plage, flare ribbons and sunspots |

## Funding

[![Sponsor on GitHub](https://img.shields.io/badge/Sponsor-GitHub-ff69b4?style=for-the-badge&logo=github-sponsors)](https://github.com/sponsors/soumyadipkarforma)
[![Patreon](https://img.shields.io/badge/Support-Patreon-FF424D?style=for-the-badge&logo=patreon)](https://www.patreon.com/SoumyadipKarforma)
[![Buy Me a Coffee](https://img.shields.io/badge/Support-Buy%20Me%20a%20Coffee-orange?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/soumyadipkarforma)

## License

See [LICENSE](LICENSE).
