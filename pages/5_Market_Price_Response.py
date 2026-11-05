"""Market-price response page for USDA release event studies.

The page is intentionally separate from the balance-sheet analysis.  It links
the USDA release date to observed futures prices, then interprets both the
outright nearby move and the deferred-minus-nearby calendar spread.
"""

from __future__ import annotations

from datetime import date, timedelta
import importlib
import os
from pathlib import Path
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import data_connectors as _data_connectors
import history_store as _history_store

importlib.reload(_data_connectors)
importlib.reload(_history_store)

from data_connectors import (  # noqa: E402
    FetchResult,
    fetch_barchart_history,
    fetch_yahoo_chart_history,
)
from history_store import (  # noqa: E402
    COMMODITY_CATALOG,
    build_case,
    case_records,
    format_snapshot_option,
    latest_snapshot,
)
from usda_report_pipeline import metrics_for  # noqa: E402


st.set_page_config(
    page_title="Fryar Market Price Response",
    page_icon="📈",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {max-width: 1450px; padding-top: 1.2rem; padding-bottom: 3rem;}
    .hero {
        padding: 1.45rem 1.7rem 1.35rem 1.7rem;
        border-radius: 16px;
        background: linear-gradient(115deg, #102a43 0%, #1f4d5f 58%, #4c956c 100%);
        color: white;
        margin-bottom: 1.1rem;
    }
    .hero-kicker {font-size: .76rem; letter-spacing: .12em; text-transform: uppercase; opacity: .78;}
    .hero h1 {font-size: 2.15rem; margin: .3rem 0 .45rem 0; color: white;}
    .hero p {font-size: 1.02rem; max-width: 980px; margin-bottom: 0; color: #edf6f9;}
    .callout {
        border-left: 4px solid #4c956c;
        background: #f1f7f3;
        padding: .8rem 1rem;
        border-radius: 0 10px 10px 0;
        color: #243b53;
        margin: .65rem 0 1rem 0;
    }
    .warning-callout {
        border-left: 4px solid #d97706;
        background: #fff8eb;
        padding: .8rem 1rem;
        border-radius: 0 10px 10px 0;
        color: #6b3f00;
        margin: .65rem 0 1rem 0;
    }
    .interpretation {
        border-left: 4px solid #2f6690;
        background: #eef5fb;
        padding: .85rem 1rem;
        border-radius: 0 10px 10px 0;
        color: #243b53;
        margin: .65rem 0 1rem 0;
    }
    [data-testid="stSidebar"] {background: #f5f8fa;}
    </style>
    """,
    unsafe_allow_html=True,
)


def _secret(name: str) -> str | None:
    """Read a deployment secret without printing or exposing its value."""

    try:
        value = st.secrets.get(name)
    except Exception:
        value = None
    return str(value) if value else os.getenv(name)


def _date(value: object) -> date | None:
    if value is None or pd.isna(value):
        return None
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


def _price_text(value: object, decimals: int = 3) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"${float(value):,.{decimals}f}"


def _signed(value: object, decimals: int = 3) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):+,.{decimals}f}"


def _pct(value: object, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):+.{decimals}f}%"


def _normalise_history(result: FetchResult) -> pd.DataFrame:
    """Normalize Barchart/Yahoo rows into one dated price series.

    Barchart entitlements can return ``tradingDay`` while the public fallback
    returns ``date``.  Price feeds also vary between ``settlement`` and
    ``close``.  The normalized frame keeps the source visible while ensuring
    calculations use one price unit: dollars per bushel for corn.
    """

    frame = result.data.copy() if result.data is not None else pd.DataFrame()
    if frame.empty:
        raise RuntimeError("The market-data source returned no rows.")

    date_column = next(
        (column for column in ["date", "tradingDay", "tradeDate", "timestamp"] if column in frame),
        None,
    )
    price_column = next(
        (
            column
            for column in ["settlement", "settle", "close", "lastPrice", "price"]
            if column in frame
        ),
        None,
    )
    if date_column is None or price_column is None:
        raise RuntimeError(
            "The market-data source did not return a recognizable date and settlement/close field."
        )

    output = pd.DataFrame(
        {
            "Observed date": pd.to_datetime(frame[date_column], errors="coerce", utc=True).dt.date,
            "Price": pd.to_numeric(frame[price_column], errors="coerce"),
        }
    ).dropna()
    output = output.sort_values("Observed date").drop_duplicates("Observed date", keep="last")
    if output.empty:
        raise RuntimeError("The market-data source returned no usable price rows.")

    # Some futures feeds report corn in cents per bushel while others report
    # dollars per bushel.  This transparent conversion is only applied when
    # the series is clearly in cents, not based on a hidden hard-coded scale.
    if output["Price"].abs().median() > 20:
        output["Price"] = output["Price"] / 100.0
    return output.reset_index(drop=True)


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_barchart(symbol: str, start: str, end: str, api_key: str) -> tuple[pd.DataFrame, str, str, str]:
    result = fetch_barchart_history(api_key, symbol, start, end)
    frame = _normalise_history(result)
    return frame, result.source, result.retrieved_at, result.url


@st.cache_data(ttl=900, show_spinner=False)
def _fetch_yahoo(symbol: str, start: str, end: str) -> tuple[pd.DataFrame, str, str, str]:
    result = fetch_yahoo_chart_history(symbol, start, end)
    frame = _normalise_history(result)
    return frame, result.source, result.retrieved_at, result.url


def _series_value(frame: pd.DataFrame, observed_date: date | None) -> float | None:
    if observed_date is None or frame.empty:
        return None
    matches = frame.loc[frame["Observed date"] == observed_date, "Price"]
    if matches.empty:
        return None
    return float(matches.iloc[-1])


def _make_event_table(
    nearby: pd.DataFrame,
    deferred: pd.DataFrame,
    release_date: date,
) -> pd.DataFrame:
    """Select pre-release, release-day, +1 and +5 trading-day observations."""

    available_dates = sorted(
        set(nearby.get("Observed date", pd.Series(dtype=object)).dropna().tolist())
        | set(deferred.get("Observed date", pd.Series(dtype=object)).dropna().tolist())
    )
    if not available_dates:
        return pd.DataFrame(
            columns=[
                "Window",
                "Observed date",
                "Nearby price ($/bu)",
                "Deferred price ($/bu)",
                "Calendar spread ($/bu)",
            ]
        )

    prior_dates = [item for item in available_dates if item < release_date]
    after_dates = [item for item in available_dates if item >= release_date]
    if not prior_dates or not after_dates:
        return pd.DataFrame()

    pre_date = prior_dates[-1]
    release_index = 0
    windows: list[tuple[str, date]] = [("Pre-release", pre_date)]
    for label, offset in [("Release day", 0), ("+1 trading day", 1), ("+5 trading days", 5)]:
        index = release_index + offset
        if index < len(after_dates):
            windows.append((label, after_dates[index]))

    rows: list[dict[str, object]] = []
    for label, observed_date in windows:
        nearby_price = _series_value(nearby, observed_date)
        deferred_price = _series_value(deferred, observed_date)
        spread = None
        if nearby_price is not None and deferred_price is not None:
            spread = deferred_price - nearby_price
        rows.append(
            {
                "Window": label,
                "Observed date": observed_date.isoformat(),
                "Nearby price ($/bu)": nearby_price,
                "Deferred price ($/bu)": deferred_price,
                "Calendar spread ($/bu)": spread,
            }
        )
    return pd.DataFrame(rows)


def _manual_event_table(release_date: date) -> pd.DataFrame:
    dates = [
        release_date - pd.offsets.BDay(1),
        release_date,
        release_date + pd.offsets.BDay(1),
        release_date + pd.offsets.BDay(5),
    ]
    return pd.DataFrame(
        {
            "Window": ["Pre-release", "Release day", "+1 trading day", "+5 trading days"],
            "Observed date": [pd.Timestamp(item).date().isoformat() for item in dates],
            "Nearby price ($/bu)": [None] * 4,
            "Deferred price ($/bu)": [None] * 4,
            "Calendar spread ($/bu)": [None] * 4,
        }
    )


def _response_table(event: pd.DataFrame) -> pd.DataFrame:
    if event.empty:
        return pd.DataFrame()
    output = event.copy()
    if len(output) == 0:
        return output
    pre_nearby = output.iloc[0]["Nearby price ($/bu)"]
    pre_spread = output.iloc[0]["Calendar spread ($/bu)"]
    output["Nearby move ($/bu)"] = output["Nearby price ($/bu)"].map(
        lambda value: None if pd.isna(value) or pd.isna(pre_nearby) else float(value) - float(pre_nearby)
    )
    output["Nearby move (%)"] = output["Nearby move ($/bu)"].map(
        lambda value: None if value is None or pd.isna(pre_nearby) or float(pre_nearby) == 0 else float(value) / float(pre_nearby) * 100
    )
    output["Spread move ($/bu)"] = output["Calendar spread ($/bu)"].map(
        lambda value: None if pd.isna(value) or pd.isna(pre_spread) else float(value) - float(pre_spread)
    )
    return output


def _format_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in [
        "Nearby price ($/bu)",
        "Deferred price ($/bu)",
        "Calendar spread ($/bu)",
        "Nearby move ($/bu)",
        "Spread move ($/bu)",
    ]:
        if column in output:
            output[column] = output[column].map(
                lambda value: "—" if pd.isna(value) else f"{float(value):+,.3f}" if "move" in column.lower() else f"{float(value):,.3f}"
            )
    if "Nearby move (%)" in output:
        output["Nearby move (%)"] = output["Nearby move (%)"].map(
            lambda value: "—" if pd.isna(value) else f"{float(value):+.2f}%"
        )
    return output


def _interpretation(event: pd.DataFrame, case) -> list[str]:
    if event.empty or len(event) < 2:
        return [
            "Enter or load at least the pre-release and release-day prices before interpreting the response."
        ]
    pre = event.iloc[0]
    release = event.iloc[1]
    nearby_change = (
        None
        if pd.isna(pre["Nearby price ($/bu)"]) or pd.isna(release["Nearby price ($/bu)"])
        else float(release["Nearby price ($/bu)"]) - float(pre["Nearby price ($/bu)"])
    )
    spread_change = (
        None
        if pd.isna(pre["Calendar spread ($/bu)"]) or pd.isna(release["Calendar spread ($/bu)"])
        else float(release["Calendar spread ($/bu)"]) - float(pre["Calendar spread ($/bu)"])
    )

    lines: list[str] = []
    if nearby_change is None:
        lines.append(
            "The page has not received both nearby prices, so it cannot describe an outright futures response yet."
        )
    elif abs(nearby_change) < 0.005:
        lines.append("The nearby contract was essentially unchanged at the release-day observation relative to the pre-release price.")
    elif nearby_change < 0:
        lines.append(
            f"The nearby contract fell {_price_text(abs(nearby_change))}/bu on the release-day comparison. This is the immediate market response, not a stand-alone forecast."
        )
    else:
        lines.append(
            f"The nearby contract rose {_price_text(abs(nearby_change))}/bu on the release-day comparison. This is the immediate market response, not a stand-alone forecast."
        )

    try:
        stock_change = float(case.current["ending_stocks"]) - float(case.previous["ending_stocks"])
    except (KeyError, TypeError, ValueError):
        stock_change = None
    if stock_change is not None:
        if stock_change > 0 and nearby_change is not None and nearby_change < 0:
            lines.append(
                f"USDA ending stocks increased by {stock_change:,.0f} million bushels and price also moved lower. Those directions are consistent with a softer balance-sheet signal, although other news and positioning can dominate the reaction."
            )
        elif stock_change < 0 and nearby_change is not None and nearby_change > 0:
            lines.append(
                f"USDA ending stocks declined by {abs(stock_change):,.0f} million bushels and price also moved higher. Those directions are consistent with a tighter balance-sheet signal, although other news and positioning can dominate the reaction."
            )
        else:
            lines.append(
                "The price move did not line up one-for-one with the ending-stocks change. That is a useful signal: the market may have priced in the report, or demand, weather, positioning, and macro news may have mattered more."
            )

    if spread_change is None:
        lines.append(
            "Calendar-spread interpretation is unavailable until both nearby and deferred contract prices are loaded from the same source and timestamp convention."
        )
    elif spread_change > 0.005:
        lines.append(
            f"The deferred-minus-nearby spread widened by {_price_text(spread_change)}/bu. Directionally, deferred prices strengthened relative to nearby prices, which is consistent with more carry or less urgency in nearby supply."
        )
    elif spread_change < -0.005:
        lines.append(
            f"The deferred-minus-nearby spread narrowed by {_price_text(abs(spread_change))}/bu. Directionally, nearby prices strengthened relative to deferred prices, which is consistent with a tighter nearby market or less carry."
        )
    else:
        lines.append("The calendar spread was essentially unchanged at the release-day comparison.")

    if len(event) >= 4 and not pd.isna(event.iloc[3]["Nearby price ($/bu)"]) and nearby_change is not None:
        five_day_move = float(event.iloc[3]["Nearby price ($/bu)"]) - float(pre["Nearby price ($/bu)"])
        if nearby_change == 0 or five_day_move * nearby_change > 0:
            lines.append("The +5-trading-day move remained in the same direction as the initial response, suggesting the first move persisted through the short event window.")
        else:
            lines.append("The +5-trading-day move reversed the initial direction, suggesting the first response was not fully persistent.")

    lines.append("Interpretation rule: use ‘consistent with,’ not ‘caused by.’ A report event is one information shock inside a larger market, and this page is not a trading recommendation or price guarantee.")
    return lines


st.markdown(
    """
    <div class="hero">
      <div class="hero-kicker">Fryar Center · USDA analytical layer</div>
      <h1>Market Price Response</h1>
      <p>Connect the USDA release to the observed futures response: outright price movement first, then the calendar-spread adjustment and a plain-language interpretation.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="callout"><strong>What this page answers:</strong> After a USDA release, did the nearby futures price move, did the deferred-minus-nearby spread change, and what does that pattern mean for the market story? The page keeps the event study separate from the supply-and-demand calculations and from the producer hedging decision tool.</div>',
    unsafe_allow_html=True,
)


with st.sidebar:
    st.header("Choose release event")
    commodity_keys = list(COMMODITY_CATALOG)
    commodity = st.selectbox(
        "Commodity",
        commodity_keys,
        format_func=lambda key: COMMODITY_CATALOG[key]["label"],
    )
    records = case_records(commodity)
    latest = latest_snapshot(commodity)
    if not records:
        st.info(
            f"{COMMODITY_CATALOG[commodity]['label']} has no validated release pair yet. "
            "The first event-study case is seeded for Corn."
        )
        st.stop()
    latest_id = latest.get("snapshot_id") if latest else None
    snapshot_ids = [str(row["snapshot_id"]) for row in records]
    default_id = latest_id if latest_id in snapshot_ids else snapshot_ids[-1]
    selected_id = st.selectbox(
        "Release vintage",
        snapshot_ids,
        index=snapshot_ids.index(default_id),
        format_func=lambda sid: format_snapshot_option(
            next(row for row in records if row["snapshot_id"] == sid), latest_id
        ),
    )
    selected_record = next(row for row in records if row["snapshot_id"] == selected_id)
    case = build_case(commodity, selected_id)
    release_date = _date(case.current_release_date)
    if release_date is None:
        st.error("The selected release does not have a valid release date.")
        st.stop()
    st.caption(f"{case.current_label} · prior release: {case.previous_label} · {release_date.isoformat()}")
    st.divider()
    st.header("Market data")
    data_mode = st.radio(
        "Data mode",
        ["Auto-load real data", "Enter observed settlements"],
        help="Auto mode uses contract-level Barchart history when BARCHART_API_KEY is configured. Otherwise it uses a public continuous-futures reference for the nearby contract only.",
    )
    nearby_symbol = st.text_input(
        "Nearby Barchart symbol",
        value="ZCZ26" if commodity == "corn" else "",
        help="For the seeded October 2026 Corn case, ZCZ26 is the expected nearby contract. Confirm the symbol against your licensed vendor's contract directory.",
    )
    deferred_symbol = st.text_input(
        "Deferred Barchart symbol",
        value="ZCH27" if commodity == "corn" else "",
        help="For the seeded October 2026 Corn case, ZCH27 is a deferred CBOT Corn contract. Confirm the symbol against your licensed vendor's contract directory.",
    )


if commodity != "corn":
    st.warning("The event-study logic is ready for additional commodities, but the first validated release case and contract mapping are Corn. Add the commodity-specific release parser and contract calendar before publishing another market response.")
    st.stop()

if data_mode == "Enter observed settlements":
    event = st.data_editor(
        _manual_event_table(release_date),
        width="stretch",
        hide_index=True,
        disabled=["Window", "Observed date", "Calendar spread ($/bu)"],
        column_config={
            "Nearby price ($/bu)": st.column_config.NumberColumn("Nearby price ($/bu)", format="$%.3f"),
            "Deferred price ($/bu)": st.column_config.NumberColumn("Deferred price ($/bu)", format="$%.3f"),
            "Calendar spread ($/bu)": st.column_config.NumberColumn("Calendar spread ($/bu)", format="$%.3f"),
        },
        key=f"manual_market_response_{selected_id}",
    )
    event["Calendar spread ($/bu)"] = event.apply(
        lambda row: None
        if pd.isna(row["Nearby price ($/bu)"]) or pd.isna(row["Deferred price ($/bu)"])
        else float(row["Deferred price ($/bu)"]) - float(row["Nearby price ($/bu)"]),
        axis=1,
    )
    source_label = "Manual observed settlements"
    retrieved_at = "Entered in page"
    source_url = ""
else:
    start_date = release_date - timedelta(days=12)
    end_date = release_date + timedelta(days=12)
    nearby = pd.DataFrame()
    deferred = pd.DataFrame()
    source_label = ""
    retrieved_at = ""
    source_url = ""
    barchart_key = _secret("BARCHART_API_KEY")
    errors: list[str] = []
    if barchart_key and nearby_symbol and deferred_symbol:
        try:
            nearby, source_label, retrieved_at, source_url = _fetch_barchart(
                nearby_symbol, start_date.isoformat(), end_date.isoformat(), barchart_key
            )
            deferred, deferred_source, deferred_retrieved_at, _deferred_url = _fetch_barchart(
                deferred_symbol, start_date.isoformat(), end_date.isoformat(), barchart_key
            )
            source_label = f"{source_label} · nearby {nearby_symbol} + deferred {deferred_symbol}"
            retrieved_at = f"nearby {retrieved_at}; deferred {deferred_retrieved_at}"
        except Exception as exc:
            errors.append(f"Barchart contract history could not be loaded ({type(exc).__name__}).")
            nearby = pd.DataFrame()
            deferred = pd.DataFrame()
    if nearby.empty:
        try:
            nearby, source_label, retrieved_at, source_url = _fetch_yahoo(
                "ZC=F", start_date.isoformat(), end_date.isoformat()
            )
            source_label = f"{source_label} · nearby reference ZC=F"
        except Exception as exc:
            errors.append(f"Public continuous-futures fallback could not be loaded ({type(exc).__name__}).")
    event = _make_event_table(nearby, deferred, release_date)
    if errors:
        st.warning(" ".join(errors))

if event.empty:
    st.warning("No live event-window rows are available in this deployment. The page remains usable as an input template: configure BARCHART_API_KEY for contract-level history, or switch to Enter observed settlements.")
    event = _manual_event_table(release_date)
    source_label = "No live data loaded — manual template"
    retrieved_at = "Not available"
    source_url = ""

response = _response_table(event)
metrics = metrics_for(case)

st.subheader("1. Big picture: the event window")
big_cols = st.columns(4)
pre = response.iloc[0]
release = response.iloc[1] if len(response) > 1 else response.iloc[0]
big_cols[0].metric(
    "Release-day nearby move",
    _signed(release.get("Nearby move ($/bu)")),
    _pct(release.get("Nearby move (%)")),
)
big_cols[1].metric(
    "Release-day spread move",
    _signed(release.get("Spread move ($/bu)")),
    "deferred − nearby",
)
big_cols[2].metric(
    "USDA ending-stocks change",
    f"{metrics['ending_change']:+,.0f} M bu",
    f"{metrics['stu_change_pp']:+.1f} pp stocks-to-use",
)
big_cols[3].metric(
    "Data source",
    "Contract-level" if event["Deferred price ($/bu)"].notna().any() else ("Manual input" if data_mode == "Enter observed settlements" else "Continuous nearby"),
    "observed event-window prices",
)

st.caption(
    f"Release: {case.current_label} · prior release: {case.previous_label} · source: {source_label or 'manual'} · retrieved: {retrieved_at or 'not applicable'}"
)
if source_url:
    st.caption(f"Source endpoint: {source_url}")

st.subheader("2. Futures price response")
st.dataframe(_format_frame(response[[
    "Window",
    "Observed date",
    "Nearby price ($/bu)",
    "Nearby move ($/bu)",
    "Nearby move (%)",
]]), width="stretch", hide_index=True)

price_fig = go.Figure()
price_fig.add_trace(
    go.Scatter(
        x=event["Observed date"],
        y=event["Nearby price ($/bu)"],
        mode="lines+markers",
        name="Nearby",
        line=dict(color="#1f4d5f", width=3),
    )
)
if event["Deferred price ($/bu)"].notna().any():
    price_fig.add_trace(
        go.Scatter(
            x=event["Observed date"],
            y=event["Deferred price ($/bu)"],
            mode="lines+markers",
            name="Deferred",
            line=dict(color="#4c956c", width=3),
        )
    )
price_fig.update_layout(
    title="Observed futures prices around the USDA release",
    yaxis_title="Dollars per bushel",
    height=360,
    template="plotly_white",
    margin=dict(l=10, r=10, t=55, b=10),
    legend=dict(orientation="h", y=1.08, x=0),
)
st.plotly_chart(price_fig, width="stretch", config={"displayModeBar": False})

st.subheader("3. Calendar-spread adjustment")
if event["Calendar spread ($/bu)"].notna().any():
    st.dataframe(_format_frame(response[[
        "Window",
        "Observed date",
        "Deferred price ($/bu)",
        "Nearby price ($/bu)",
        "Calendar spread ($/bu)",
        "Spread move ($/bu)",
    ]]), width="stretch", hide_index=True)
    spread_fig = go.Figure(
        go.Scatter(
            x=event["Observed date"],
            y=event["Calendar spread ($/bu)"],
            mode="lines+markers",
            name="Deferred − nearby",
            line=dict(color="#d97706", width=3),
        )
    )
    spread_fig.update_layout(
        title="Calendar spread: deferred minus nearby",
        yaxis_title="Dollars per bushel",
        height=330,
        template="plotly_white",
        margin=dict(l=10, r=10, t=55, b=10),
    )
    st.plotly_chart(spread_fig, width="stretch", config={"displayModeBar": False})
else:
    st.info("The nearby continuous series is real observed market data, but it cannot identify a deferred contract. Configure Barchart/CME contract-level data or enter both contracts manually to calculate the calendar spread.")

st.subheader("4. Interpretation for the audience")
interpretation = _interpretation(event, case)
st.markdown(
    '<div class="interpretation"><strong>How to read this:</strong><br>'
    + "<br>".join(f"• {line}" for line in interpretation)
    + "</div>",
    unsafe_allow_html=True,
)

with st.expander("What each number represents"):
    st.markdown(
        """
        **Nearby price move** is the price difference between the release-day observation and the last available price before the release. It answers: *what did the market do immediately?*

        **Calendar spread** is `deferred price − nearby price`. A larger positive spread means deferred strengthened relative to nearby; a smaller or more negative spread means nearby strengthened relative to deferred. It answers: *did the market change its view of immediate availability versus later supply?*

        **+5 trading days** is a short persistence check. If the move remains in the same direction, the first response persisted through this window; if it reverses, the initial reaction was not fully durable.

        None of these is a probability of profit or a guaranteed price forecast. The page is an event-study layer that feeds the report narrative and, later, the producer decision tool.
        """
    )

st.subheader("5. Data and pipeline status")
pipeline_frame = pd.DataFrame(
    [
        ["USDA release event", "release date, report label, prior/current vintage", "Validated snapshot", "Connected"],
        ["Nearby futures price", "contract/date/price or settlement/source/timestamp", "Barchart if key; otherwise public continuous reference", "Connected with fallback"],
        ["Deferred futures price", "same fields, same price convention", "Barchart/CME contract-level entitlement", "Required for automatic spread"],
        ["Calendar spread", "deferred − nearby using same event dates", "Calculated in page", "Connected when both legs exist"],
        ["Audit trail", "source URL, retrieval timestamp, symbol, parser version", "Stored with page output; scheduled job can persist rows", "Prototype"],
    ],
    columns=["Block", "Required fields", "Current source", "Status"],
)
st.dataframe(pipeline_frame, width="stretch", hide_index=True)
st.markdown(
    '<div class="warning-callout"><strong>Licensing boundary:</strong> The public continuous series is a reference fallback. For a published Fryar report, use a data source whose license permits historical futures-price display and redistribution. Barchart/CME credentials belong in Streamlit secrets or a scheduled backend, never in the page code or user-facing inputs.</div>',
    unsafe_allow_html=True,
)

download_frame = response.copy()
download_frame.insert(0, "commodity", commodity)
download_frame.insert(1, "snapshot_id", selected_id)
download_frame.insert(2, "release_date", release_date.isoformat())
download_frame.insert(3, "source", source_label)
st.download_button(
    "Download market-price response CSV",
    download_frame.to_csv(index=False).encode("utf-8"),
    f"{commodity}_{selected_id}_market_price_response.csv",
    "text/csv",
)

st.caption(
    "This page is an educational event-study prototype. Before public publication, validate contract symbols, price timing, data licensing, and the interpretation with the Fryar Center market analyst."
)
