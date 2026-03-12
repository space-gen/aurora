# data_processing/

This directory is the **temporary workspace** used during the nightly automation pipeline.

## Pipeline Lifecycle

1. At the **start** of the nightly pipeline (`01_lock_and_prepare.yml`), the `data/` directory is
   renamed to `data_processing/`. This acts as a system lock, preventing the frontend from serving
   stale or partially-updated tasks.

2. All intermediate pipeline stages (URL refresh, annotation sync, ML predictions) operate on
   files in this directory.

3. At the **end** of the nightly pipeline (`09_unlock_frontend.yml`), the directory is renamed
   back to `data/`, making updated task files available to the frontend again.

## Notes

- This directory should be **empty** at all times outside of an active nightly pipeline run.
- Do **not** commit processing artifacts or intermediate files here.
- `data_processing/` and HuggingFace datasets must never mix automatically.
