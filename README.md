# Fryar Producer Decision Lab — Streamlit draft

This is an interview-preparation prototype for the UARK Fryar Center postdoctoral position. It is intentionally producer-first and uses transparent illustrative assumptions, with an optional official USDA RMA quote workflow for the livestock LRP module.

## What it demonstrates

- scenario-based decision support for crop and livestock producers;
- comparison of cash sale, unhedged/wait, futures hedge, staged hedge, Put, and LRP-style floor strategies;
- a dedicated livestock LRP decision tab comparing no LRP versus buying LRP, including coverage share, premium, indemnity, modeled break-even, profit, and residual-risk interpretation;
- a livestock margin-check first step with exposed pounds, gross revenue, detailed cost categories, margin, break-even price, Arkansas/USDA benchmark context, and a covered-head scenario grid;
- an optional live USDA RMA LRP quote workflow that loads the official coverage price, coverage level, endorsement length, end date, and producer premium, then pre-fills the transparent scenario model;
- price, production/quantity, basis, storage, hedge-share, target-price, and protection-cost inputs;
- expected, P10, P50, and P90 net-price outcomes;
- target-price probability, loss probability, positive-margin probability, P10/P50/P90 margin outcomes, CVaR10 downside, expected total margin, and probability of beating the unhedged benchmark;
- an Extension-oriented interpretation layer;
- a Rice case as an additional crop market;
- a planned poultry feed-cost extension that passes corn and soybean-meal price risk through a ration into poultry margins;
- a pathway to connect the product to Fryar's broader tools and monthly USDA/WASDE information.

For livestock, the interface starts with operation economics: exposed pounds,
sale and other revenue, detailed per-head costs, margin, and break-even price.
The producer then chooses covered head, coverage level, endorsement length, and
compares LRP, put-option, cash-sale, futures, and staged-hedge scenarios. Crop
workflows do not show LRP; they show crop-appropriate futures, staged-hedge, and
put-option tools.

The draft now includes seven demonstrable tools in one Streamlit toolbox:

1. **Fryar Producer Decision Lab** — the producer-first hedging and marketing tool in `app.py`.
2. **Fryar USDA Release & Decision Report** — the real-data Corn and Cattle release comparison, formula layer, blank report template, auto-filled report, source check, and download workflow in `pages/2_USDA_Market_Outlook.py`.
3. **Fryar Decision Bridge & Feedback Lab** — the role-specific margin bridge and anonymous workshop feedback page in `pages/3_Decision_Bridge.py`.
4. **Fryar Supply & Demand Analysis** — the transparent USDA balance-sheet calculation layer in `pages/4_Supply_Demand_Analysis.py`.
5. **Fryar Market Price Response** — the USDA event-study layer in `pages/5_Market_Price_Response.py`, with nearby futures movement, deferred-minus-nearby calendar spread, and plain-language interpretation.
6. **Fryar Commodity Price Forecasts** — the low/middle/high scenario layer in `pages/6_Commodity_Price_Forecast.py`, with transparent stocks-to-use sensitivity, volatility band, and USDA Agricultural Baseline/FAPRI-MU/OECD-FAO benchmark comparison.
7. **Fryar Hedging & Marketing Implications** — the producer-facing bridge in `pages/7_Hedging_Marketing_Implications.py`, with editable cost breakdown, Arkansas/regional/USDA/own-history benchmark comparison, break-even interpretation, and validated strategy simulation.
8. **Fryar Monthly USDA Report Studio** — the publication layer in `pages/8_Monthly_Report_Studio.py`, with a fixed monthly content map, branded Fact Sheet and Full Report previews, Markdown editorial draft, review gate, and downloadable report package.

The third page still uses transparent manual inputs. The USDA pages contain two official snapshot cases: October 2026 versus September 2026 Corn WASDE and October 2026 versus September 2026 Cattle on Feed. November 2026 had not yet been released when the case was built, so the app flags the scheduled release rather than inventing data. The intended production architecture is to have one validated release snapshot feed the monthly report, the market-price event study, and the hedging/marketing tool.

### USDA release report case

`usda_report_pipeline.py` keeps the normalized case data and formulas separate from the UI. The current cases include:

- Corn: production, yield, total use, exports, ending stocks, stocks-to-use, and USDA farm-price revision.
- Cattle: inventory, placements, marketings, other disappearance, release-to-release changes, and year-over-year percentages.

The page shows a stable extension-style template with blank tokens, fills the template using the real USDA snapshot, and lets the user download both a Markdown report and a normalized CSV. A future scheduled job can replace the snapshot dictionary with a parser for the official USDA WASDE XLS/XML/TXT and NASS Cattle on Feed files, validate the release date and units, and publish the same report without changing the UI.

The report preview/download now uses the local `Fryar-Center-logo.png`, the Center's cardinal-red visual accent (`#9E2B44`), Poppins-style typography, a branded header, “At a glance” metric cards, a red conclusion callout, a comparison table, methods/data note, official-source list, and University of Arkansas Division of Agriculture footer. The HTML download is self-contained: the logo is embedded so it does not depend on a local path after download.

### Commodity price forecast case

The price forecast page uses the current validated Corn WASDE farm-price projection as the anchor, adjusts the middle scenario with an explicit stocks-to-use sensitivity, and widens low/high scenarios with a transparent volatility rule. It now displays a historical realized-volatility estimate from a public continuous-futures reference alongside the forward-looking implied-volatility input, shows the IV-minus-historical gap, and lets the audience see whether the band uses the conservative maximum, an average, IV only, or historical volatility only. The current IV input is manual until an entitled options feed is connected; the historical continuous series is a prototype reference and should be replaced by approved contract-level history and a documented roll convention before publication. The current benchmark file in `data/benchmarks/corn_price_benchmarks.csv` shows USDA Agricultural Baseline, FAPRI-MU, and OECD-FAO reference values with their source, horizon, unit, and comparability status. OECD-FAO is kept as global maize context rather than blended into the U.S. farm-price band. The page flags the provisional FAPRI seed and keeps the formulas visible for review.

The hedging/marketing page adds the next JD layer: it breaks total cost into item-level categories, lets the audience enter matching Arkansas/regional, USDA national, and own-prior-year values, calculates current and benchmark break-even prices, and reuses `simulate_strategies`/`summarize` from the Decision Lab for cash sale, wait, futures, staged hedge, put, and livestock LRP comparisons. Each cost and strategy result includes an interpretation rather than only a number.

### Monthly Report Studio

`pages/8_Monthly_Report_Studio.py` is the operator-facing publication layer for the second JD initiative. It reads the same validated monthly release pair as the USDA report page and assembles a repeatable package containing a Fryar-branded Fact Sheet, Full Extension Report, Markdown editorial draft, normalized comparison CSV, and human-review checklist. The browser session does not overwrite history; the scheduled refresh job remains responsible for writing immutable snapshots and archived report bundles under `data/`.

The branded Full Extension Report now embeds the current analytical chain: executive interpretation, supply and demand, the seeded Corn market-price event window, the transparent low/middle/high price forecast, the Decision Lab hedging summary, and sources/methods. The Corn event window uses the same public continuous-futures reference shown on the Market Price Response page and clearly labels the deferred spread as unavailable; a production pipeline should replace it with licensed contract-level data when redistribution is permitted. The forecast and hedging sections retain visible assumptions rather than silently inventing live inputs.

## Live audience interaction for the stakeholder presentation

The prototype now includes a lightweight, anonymous live-poll layer for the
presentation. It uses the first question exactly as designed for Page 2:

> What is the biggest financial decision facing your operation right now?

Four prompt presets are included so the presenter can move from decision
context to profit, cost, and risk-protection questions. The response page is
opened by QR code, and the presenter screen refreshes the response chart every
two seconds. A small SQLite file is shared by the Streamlit sessions; this is
appropriate for a local demonstration or a single-server prototype. A
multi-instance deployment should replace it with Postgres/Supabase.

### Three presentation URLs

After starting Streamlit, use the same app with these query parameters:

```text
http://localhost:8501/?mode=audience&poll=stakeholder-demo
http://localhost:8501/?mode=screen&poll=stakeholder-demo
http://localhost:8501/
```

- `mode=audience`: phone-friendly answer page opened by the QR code.
- `mode=screen`: presenter dashboard with prompt controls, QR code, and live chart.
- no mode: the original producer decision lab; its sidebar also shows the QR code.

For phones on the same Wi-Fi network, start the app so it listens on the
local network and use the computer's LAN address in the QR-code field:

```powershell
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

For a real interview or classroom demonstration, use a deployed HTTPS URL
instead of `localhost`. The URL entered in the presenter screen is the URL
encoded into the QR code.

## Real-data integration and versioned USDA pipeline

The USDA page now uses a versioned release store under `data/`. The initial
Corn and Cattle September/October 2026 records are normalized baselines. The
scheduled `/.github/workflows/refresh-usda.yml` job checks official USDA PDFs,
parses and validates them with `scripts/refresh_usda.py`, writes a new
release-specific snapshot, generates a Fryar fact sheet plus full report, and
commits only new validated files. It is safe to run repeatedly: an unchanged
release/hash is skipped and a changed file becomes a revision rather than
overwriting history.

`data/latest.json` is only a pointer to the newest validated snapshot;
`data/manifest.json` records the source URL, retrieval time, hash, parser
version, revision, and validation status. The Streamlit page reads the
normalized files and provides **Latest validated release** and **Historical
release** selectors. Raw PDFs can remain in GitHub for this prototype and can
later be moved to S3/Azure Blob while preserving the same normalized contract.

API keys should be stored in local Streamlit secrets or a deployment secret
manager, never in the app or repository.

| Source | Access pattern | Intended use |
|---|---|---|
| USDA NASS Quick Stats | API key | Arkansas acreage, yield, production, prices, stocks, and livestock statistics |
| USDA AMS MyMarketNews | API key | Cash bids, cash prices, livestock market reports, and basis inputs where coverage is available |
| USDA FAS PSD / ESR / GATS | API key | World supply-demand balances, export sales, and trade context |
| USDA WAOB / ESMIS WASDE | Public CSV/XLS/XML/report files | Historical report vintages, report revisions, and supply-demand surprises |
| USDA RMA | Public RIRS report, bulk files, and actuarial documents | Live LRP coverage prices/rates plus crop-insurance participation, plan structure, subsidies, and historical policy outcomes |
| CME Group | Licensed REST/WebSocket/DataMine access | Futures, options, settlements, Greeks, and implied volatility |
| Barchart OnDemand | Separate API key and entitlement | Futures quotes, historical prices, futures options, volatility, and Greeks where licensed |
| CFTC COT | Public weekly downloads | Commercial and managed-money positioning as supplementary market context |

The current connectors cover NASS, AMS, FAS PSD, Barchart OnDemand, a public continuous-futures chart fallback, public file downloads, the official RMA RIRS LRP quote report, RMA/CFTC-style bulk files, and entitled CME DataMine downloads. The Market Price Response page uses Barchart historical contract data when `BARCHART_API_KEY` is configured; otherwise it uses a clearly labeled continuous Corn reference for the nearby leg and requires manual or licensed data for the deferred leg. The RMA quote button uses the public **LRP Coverage, Prices, Rates, and Actual Ending Values** report and briefly caches the result so widget reruns do not repeatedly query RMA. It is quote data, not a purchase API; a producer still works with an approved crop-insurance agent to buy a policy. CME or Barchart real-time ingestion should run in a scheduled or persistent backend worker rather than inside a Streamlit browser session.

Official RMA report endpoint used by the connector:
`https://webapp.rma.usda.gov/apps/RIRS/LRPCoveragePricesRatesActualEndingValues.aspx`

The CmdtyView webpage login is not placed in the code. The Barchart adapter expects a separate `BARCHART_API_KEY`, because Barchart's documented OnDemand endpoints authenticate with an API key. Before public deployment, the Center must confirm that the account's license permits programmatic access and public display or redistribution of the resulting data.

## Run locally

From this directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
streamlit run app.py
```

## Important limitations

- The USDA report page uses validated versioned snapshots and a scheduled PDF refresh pipeline; if a new file cannot be parsed or validated, the prior release remains the latest published version and the Action run fails for review. The Market Price Response page can fetch real historical nearby and deferred contract data through an entitled Barchart key; without that key it does not invent a spread from continuous data. RMA LRP quotes are fetched only when the user clicks **Load latest official RMA quote** in the livestock view.
- Price and production draws are illustrative and should not be used for actual marketing, insurance, or trading decisions.
- The Put and LRP calculations are simplified demonstrations; contract sizes, margin, transaction costs, coverage rules, settlement conventions, actual sale weight, basis treatment, and data licensing must be specified before public release.
- The current draft does not optimize a user's timing. It compares explicitly defined strategies and reports tradeoffs.

## Proposed next development steps

1. Confirm the first user and commodity with Fryar faculty and Extension agents.
2. Replace illustrative inputs with approved historical and market-implied data sources; expand the RMA workflow to allow an explicit effective-date selector and agent-facing quote export.
3. Specify contract mechanics, basis treatment, transaction costs, and insurance rules.
4. Backtest the downside labels and target-price probabilities.
5. Review the first scheduled USDA refresh run and confirm the PDF parser against current releases.
6. Add live data credentials only after the Center confirms access, licensing, allowed redistribution, and update ownership.
7. Move raw PDFs to object storage if repository size becomes a constraint; keep normalized snapshots and reports versioned.
8. Add the poultry feed-cost view after the row-crop workflow is validated, using an explicit ration, feed-conversion ratio, procurement horizon, and broiler output-price assumption.
9. Connect the market-price response and commodity-forecast outputs to the Report Studio sections, then move the same package builder into the scheduled USDA refresh workflow for automatic monthly publication after human review.
