# Generated USDA reports

The refresh job writes one report bundle per validated snapshot: `report.md`,
`fact_sheet.html`, and `extension_report.html`. The branded full report includes
the USDA comparison plus the report-level market-price response, transparent
price forecast, and Decision Lab hedging interpretation when a validated case
has those inputs. Missing licensed contract data is labeled as unavailable;
existing bundles are never overwritten when a new release arrives.
