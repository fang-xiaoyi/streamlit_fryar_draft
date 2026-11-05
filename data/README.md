# Versioned USDA release store

This directory is the historical source for the USDA release page.

- `raw/<commodity>/<release-date>/` keeps the original official PDF.
- `normalized/<commodity>/<snapshot-id>.json` keeps the validated values used by the app.
- `reports/<commodity>/<snapshot-id>/` keeps the generated Markdown, fact sheet, and branded HTML report.
- `manifest.json` records source URL, retrieval time, file hash, parser version, and validation status.
- `latest.json` is only a pointer to the newest validated snapshot; it does not delete history.

The September/October 2026 records are the initial validated demonstration baseline. The scheduled refresh job appends later releases and stores revisions under a new snapshot ID.
