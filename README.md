# Fryar Producer Decision Lab — Streamlit draft

This is an interview-preparation prototype for the UARK Fryar Center postdoctoral position. It is intentionally producer-first and uses transparent illustrative assumptions, with an optional official USDA RMA quote workflow for the livestock LRP module.

## What it demonstrates

- scenario-based decision support for crop and livestock producers;
- comparison of cash sale, unhedged/wait, futures hedge, staged hedge, Put, and LRP-style floor strategies;
- a dedicated livestock LRP decision tab comparing no LRP versus buying LRP, including coverage share, premium, indemnity, modeled break-even, profit, and residual-risk interpretation;
- an optional live USDA RMA LRP quote workflow that loads the official coverage price, coverage level, endorsement length, end date, and producer premium, then pre-fills the transparent scenario model;
- price, production/quantity, basis, storage, hedge-share, target-price, and protection-cost inputs;
- expected, P10, P50, and P90 net-price outcomes;
- target-price probability and loss probability;
- an Extension-oriented interpretation layer;
- a Rice case as an additional crop market;
- a planned poultry feed-cost extension that passes corn and soybean-meal price risk through a ration into poultry margins;
- a pathway to connect the product to Fryar's broader tools and monthly USDA/WASDE information.

The draft now includes three demonstrable tools in one Streamlit toolbox:

1. **Fryar Producer Decision Lab** — the producer-first hedging and marketing tool in `app.py`.
2. **Fryar USDA Release & Price Outlook Monitor** — the manual-input-first report/surprise/scenario page in `pages/2_USDA_Market_Outlook.py`.
3. **Fryar Decision Bridge & Feedback Lab** — the role-specific margin bridge and anonymous workshop feedback page in `pages/3_Decision_Bridge.py`.

The second and third pages intentionally use transparent manual inputs until the Center confirms USDA vintage handling, Bloomberg consensus access/display rights, futures/options/IV licensing, and scheduled-refresh ownership. The intended production architecture is to have one validated release snapshot feed both the monthly report and the hedging/marketing tool.

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
http://localhost:8501/?mode=audience&poll=auburn-stakeholder-demo
http://localhost:8501/?mode=screen&poll=auburn-stakeholder-demo
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

## Real-data integration plan

The app is intentionally separated from data acquisition. A scheduled refresh job should call the functions in `data_connectors.py`, normalize the results, save raw and analysis-ready files, and let Streamlit read the latest validated snapshot. API keys should be stored in local Streamlit secrets or a deployment secret manager, never in the app or repository.

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

The current connectors cover NASS, AMS, FAS PSD, Barchart OnDemand, public file downloads, the official RMA RIRS LRP quote report, RMA/CFTC-style bulk files, and entitled CME DataMine downloads. The RMA quote button uses the public **LRP Coverage, Prices, Rates, and Actual Ending Values** report and briefly caches the result so widget reruns do not repeatedly query RMA. It is quote data, not a purchase API; a producer still works with an approved crop-insurance agent to buy a policy. CME or Barchart real-time ingestion should run in a scheduled or persistent backend worker rather than inside a Streamlit browser session.

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

- No live futures, options, basis, or WASDE data are fetched in the current draft. RMA LRP quotes are fetched only when the user clicks **Load latest official RMA quote** in the livestock view.
- Price and production draws are illustrative and should not be used for actual marketing, insurance, or trading decisions.
- The Put and LRP calculations are simplified demonstrations; contract sizes, margin, transaction costs, coverage rules, settlement conventions, actual sale weight, basis treatment, and data licensing must be specified before public release.
- The current draft does not optimize a user's timing. It compares explicitly defined strategies and reports tradeoffs.

## Proposed next development steps

1. Confirm the first user and commodity with Fryar faculty and Extension agents.
2. Replace illustrative inputs with approved historical and market-implied data sources; expand the RMA workflow to allow an explicit effective-date selector and agent-facing quote export.
3. Specify contract mechanics, basis treatment, transaction costs, and insurance rules.
4. Backtest the downside labels and target-price probabilities.
5. Add saved cases, downloadable reports, and a stable monthly update workflow.
6. Add live data credentials only after the Center confirms access, licensing, allowed redistribution, and update ownership.
7. Add the poultry feed-cost view after the row-crop workflow is validated, using an explicit ration, feed-conversion ratio, procurement horizon, and broiler output-price assumption.
