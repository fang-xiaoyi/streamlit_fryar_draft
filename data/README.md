# Versioned USDA release store

This directory is the historical source for the USDA release page.

- `raw/<commodity>/<release-date>/` keeps the original official PDF.
- `normalized/<commodity>/<snapshot-id>.json` keeps the validated values used by the app.
- `reports/<commodity>/<snapshot-id>/` keeps the generated Markdown, fact sheet, and branded HTML report.
- `manifest.json` records source URL, retrieval time, file hash, parser version, and validation status.
- `latest.json` is only a pointer to the newest validated snapshot; it does not delete history.

The September/October 2026 records are the initial validated demonstration baseline. The scheduled refresh job appends later releases and stores revisions under a new snapshot ID.

## Market context

The optional `market/` directory stores release-specific context that is not part of the official USDA snapshot: pre-release consensus, futures and calendar-spread observations, volatility inputs, and transparent price-scenario assumptions. Files are joined by commodity and `snapshot_id`.

The seeded Corn October 2026 file is marked `illustrative_demo`. It exists to demonstrate the complete interview workflow and must be replaced by approved, timestamped, licensed inputs before public publication. Missing market context is displayed as missing; the app does not infer or fabricate a consensus or market reaction.
