"""Commodity price forecast page.

This page turns the USDA balance-sheet signal into a transparent low/middle/
high price range.  USDA Agricultural Baseline, FAPRI-MU, and OECD-FAO are
shown as comparison benchmarks with explicit unit and horizon warnings.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import history_store as _history_store

importlib.reload(_history_store)

from history_store import (  # noqa: E402
    COMMODITY_CATALOG,
    build_case,
    case_records,
    format_snapshot_option,
    latest_snapshot,
)
from usda_report_pipeline import metrics_for  # noqa: E402


st.set_page_config(
    page_title="Fryar Commodity Price Forecasts",
    page_icon="🎯",
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


BENCHMARK_PATH = PROJECT_ROOT / "data" / "benchmarks" / "corn_price_benchmarks.csv"
BUSHELS_PER_METRIC_TON = 39.36825


def _number(value: object, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):,.{decimals}f}"


def _price(value: object, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"${float(value):,.{decimals}f}"


def _signed(value: object, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):+,.{decimals}f}"


def _load_benchmarks() -> pd.DataFrame:
    try:
        frame = pd.read_csv(BENCHMARK_PATH)
    except (FileNotFoundError, pd.errors.ParserError):
        return pd.DataFrame(
            columns=[
                "source",
                "benchmark_type",
                "horizon",
                "price_value",
                "unit",
                "comparable_to_us_farm_price",
                "source_url",
                "source_note",
                "data_status",
            ]
        )
    frame["price_value"] = pd.to_numeric(frame["price_value"], errors="coerce")
    frame["price_usd_bu_context"] = frame.apply(
        lambda row: row["price_value"]
        if row["unit"] == "USD/bu"
        else row["price_value"] / BUSHELS_PER_METRIC_TON
        if row["unit"] == "USD/t"
        else np.nan,
        axis=1,
    )
    frame["comparable"] = frame["comparable_to_us_farm_price"].eq("yes")
    return frame


def _format_benchmarks(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if output.empty:
        return output
    output["Original value"] = output.apply(
        lambda row: f"{_price(row['price_value'])}/bu" if row["unit"] == "USD/bu" else f"${row['price_value']:,.0f}/t",
        axis=1,
    )
    output["USD/bu context"] = output["price_usd_bu_context"].map(
        lambda value: "—" if pd.isna(value) else f"${float(value):,.2f}"
    )
    output["Comparable"] = output["comparable"].map({True: "Yes", False: "Context only"})
    return output[
        [
            "source",
            "benchmark_type",
            "horizon",
            "Original value",
            "USD/bu context",
            "Comparable",
            "data_status",
            "source_note",
        ]
    ].rename(
        columns={
            "source": "Source",
            "benchmark_type": "Benchmark type",
            "horizon": "Horizon",
            "data_status": "Data status",
            "source_note": "Note",
        }
    )


def _scenario_frame(
    low: float,
    middle: float,
    high: float,
    anchor: float,
    stu: float,
    reference_stu: float,
    stu_adjustment: float,
    volatility_width: float,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["Low", low, "Middle − volatility width", "Downside / softer-price scenario"],
            ["Middle", middle, "Anchor + stocks-to-use adjustment", "Central scenario, not a guarantee"],
            ["High", high, "Middle + volatility width", "Upside / tighter-price scenario"],
        ],
        columns=["Scenario", "Price ($/bu)", "Formula role", "Interpretation"],
    )


def _interpretation(
    current_stu: float,
    reference_stu: float,
    stu_adjustment: float,
    middle: float,
    width: float,
    benchmarks: pd.DataFrame,
) -> list[str]:
    lines: list[str] = []
    if current_stu < reference_stu:
        lines.append(
            f"Current stocks-to-use is {current_stu:.1f}%, below the {reference_stu:.1f}% reference. In this transparent sensitivity model, that is a relatively tighter balance-sheet signal and raises the middle scenario by {_price(abs(stu_adjustment))}/bu."
        )
    elif current_stu > reference_stu:
        lines.append(
            f"Current stocks-to-use is {current_stu:.1f}%, above the {reference_stu:.1f}% reference. In this transparent sensitivity model, that is a relatively looser balance-sheet signal and lowers the middle scenario by {_price(abs(stu_adjustment))}/bu."
        )
    else:
        lines.append("Current stocks-to-use equals the selected reference level, so the balance-sheet adjustment to the middle scenario is zero.")

    lines.append(
        f"The model middle scenario is {_price(middle)}/bu. The low/high band is approximately {_price(width)}/bu on either side because the options-implied-volatility input determines the width."
    )

    comparable = benchmarks[benchmarks["comparable"] & benchmarks["price_usd_bu_context"].notna()]
    if not comparable.empty:
        differences = comparable.assign(
            difference=lambda frame: frame["price_usd_bu_context"] - middle
        )
        nearest = differences.iloc[(differences["difference"].abs()).argmin()]
        lines.append(
            f"Among the comparable benchmark rows, {nearest['source']} is closest to the model middle at {_price(nearest['price_usd_bu_context'])}/bu. The comparison is a reasonableness check, not a vote on which forecast is correct."
        )
    lines.append(
        "The OECD-FAO row is shown as global maize context. Its USD/tonne reference price is not merged into the U.S. farm-price band because the market level, geography, and price definition differ."
    )
    lines.append(
        "A one-standard-deviation band is not a guaranteed probability of profit. The production version should estimate volatility from option prices for the selected contract and validate coverage using historical backtests."
    )
    return lines


st.markdown(
    """
    <div class="hero">
      <div class="hero-kicker">Fryar Center · USDA analytical layer</div>
      <h1>Commodity Price Forecasts</h1>
      <p>Translate the balance sheet into a low, middle, and high price range, then compare the result with USDA Agricultural Baseline, FAPRI-MU, and OECD-FAO reference scenarios.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="callout"><strong>Big picture:</strong> the middle scenario comes from a USDA price anchor adjusted by the current stocks-to-use signal. The low/high scenarios widen around that middle using volatility. External baselines are displayed as benchmarks with their own horizon, unit, geography, and assumptions; they are not silently averaged into one number.</div>',
    unsafe_allow_html=True,
)


with st.sidebar:
    st.header("Choose USDA vintage")
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
            "The first forecast case is seeded for Corn."
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
    st.caption(f"{case.current_label} · prior release: {case.previous_label} · snapshot {selected_id}")
    st.divider()
    st.header("Forecast assumptions")
    st.caption("These inputs are visible so the audience can see exactly what creates the range.")
    reference_stu = st.number_input(
        "Reference stocks-to-use (%)",
        min_value=1.0,
        max_value=40.0,
        value=12.0,
        step=0.1,
        format="%.1f",
        help="Reference level for the transparent stocks-to-use sensitivity. Replace with an estimated long-run relationship when the historical regression is connected.",
    )
    stu_beta = st.number_input(
        "Price sensitivity ($/bu per 1 pp STU)",
        min_value=-2.0,
        max_value=2.0,
        value=-0.15,
        step=0.01,
        format="%.2f",
        help="Negative means a higher stocks-to-use ratio lowers the modeled price. This is an explicit prototype sensitivity, not a hidden coefficient.",
    )
    annualized_iv = st.number_input(
        "Annualized implied volatility (%)",
        min_value=1.0,
        max_value=100.0,
        value=25.0,
        step=0.5,
        format="%.1f",
        help="Manual placeholder until an entitled options feed is connected. In production, read IV from the selected futures-option contract.",
    )
    forecast_days = st.selectbox(
        "Forecast horizon",
        [90, 180, 365],
        index=1,
        format_func=lambda days: f"{days} days",
    )
    z_value = st.selectbox(
        "Band multiplier",
        [1.0, 1.645, 1.96],
        index=0,
        format_func=lambda value: {
            1.0: "1.0 × volatility (roughly 68% under normality)",
            1.645: "1.645 × volatility (roughly 90% under normality)",
            1.96: "1.96 × volatility (roughly 95% under normality)",
        }[value],
    )


if commodity != "corn":
    st.warning("The forecast framework is designed to extend to additional commodities, but the first validated case and benchmark file are Corn. Add a commodity-specific price unit and benchmark series before interpreting another commodity.")
    st.stop()

current = case.current
previous = case.previous
metrics = metrics_for(case)
current_stu = float(current["ending_stocks"]) / float(current["total_use"]) * 100.0
anchor_price = float(current["farm_price"])
stu_adjustment = float(stu_beta) * (current_stu - float(reference_stu))
middle_price = anchor_price + stu_adjustment
volatility_width = middle_price * (float(annualized_iv) / 100.0) * np.sqrt(float(forecast_days) / 365.0) * float(z_value)
low_price = max(0.0, middle_price - volatility_width)
high_price = middle_price + volatility_width

benchmarks = _load_benchmarks()

st.subheader("1. Big picture: the price range")
big_cols = st.columns(5)
big_cols[0].metric("Current USDA anchor", _price(anchor_price), "WASDE farm-price projection")
big_cols[1].metric("Current stocks-to-use", f"{current_stu:.1f}%", f"{metrics['stu_change_pp']:+.1f} pp vs prior")
big_cols[2].metric("Low scenario", _price(low_price), f"{_price(-volatility_width)} from middle")
big_cols[3].metric("Middle scenario", _price(middle_price), f"STU adjustment {_signed(stu_adjustment)}")
big_cols[4].metric("High scenario", _price(high_price), f"{_price(volatility_width)} from middle")

st.caption(
    f"Current case: {case.current_label} · USDA release date: {case.current_release_date} · "
    f"forecast horizon: {forecast_days} days · band multiplier: {z_value}"
)

st.subheader("2. Forecast scenarios")
scenario_frame = _scenario_frame(
    low_price,
    middle_price,
    high_price,
    anchor_price,
    current_stu,
    reference_stu,
    stu_adjustment,
    volatility_width,
)
scenario_display = scenario_frame.copy()
scenario_display["Price ($/bu)"] = scenario_display["Price ($/bu)"].map(lambda value: f"${value:,.2f}")
st.dataframe(scenario_display, width="stretch", hide_index=True)

band_fig = go.Figure()
band_fig.add_trace(
    go.Scatter(
        x=[low_price, high_price],
        y=["Fryar model band", "Fryar model band"],
        mode="lines",
        line=dict(color="#4c956c", width=12),
        name="Low–high range",
        hovertemplate="$%{x:.2f}/bu<extra></extra>",
    )
)
band_fig.add_trace(
    go.Scatter(
        x=[middle_price],
        y=["Fryar model band"],
        mode="markers",
        marker=dict(color="#102a43", size=16),
        name="Middle",
        hovertemplate="Middle: $%{x:.2f}/bu<extra></extra>",
    )
)
for _, row in benchmarks[benchmarks["comparable"] & benchmarks["price_usd_bu_context"].notna()].iterrows():
    band_fig.add_trace(
        go.Scatter(
            x=[float(row["price_usd_bu_context"])],
            y=[str(row["source"])],
            mode="markers",
            marker=dict(size=12),
            name=str(row["source"]),
            hovertemplate=f"{row['source']}: $%{{x:.2f}}/bu<extra></extra>",
        )
    )
band_fig.update_layout(
    title="Fryar scenario band compared with U.S. benchmark prices",
    xaxis_title="Dollars per bushel",
    height=400,
    template="plotly_white",
    margin=dict(l=10, r=10, t=55, b=10),
    legend=dict(orientation="h", y=-0.25, x=0),
)
st.plotly_chart(band_fig, width="stretch", config={"displayModeBar": False})

st.subheader("3. Benchmark comparison")
st.dataframe(_format_benchmarks(benchmarks), width="stretch", hide_index=True)
st.caption(
    "Comparable rows are U.S. farm-price style values for the same marketing-year horizon. OECD-FAO is a global maize reference in USD/tonne and is shown for context only; it is not part of the U.S. band."
)
for _, row in benchmarks.iterrows():
    if pd.notna(row.get("source_url")):
        st.markdown(f"- [{row['source']}]({row['source_url']}) — {row['source_note']}")

st.subheader("4. Interpretation for the audience")
interpretation = _interpretation(
    current_stu,
    float(reference_stu),
    stu_adjustment,
    middle_price,
    volatility_width,
    benchmarks,
)
st.markdown(
    '<div class="interpretation"><strong>How to explain this chart:</strong><br>'
    + "<br>".join(f"• {line}" for line in interpretation)
    + "</div>",
    unsafe_allow_html=True,
)

with st.expander("Formula layer"):
    st.code(
        """current_stocks_to_use = ending_stocks / total_use
stu_adjustment = beta * (current_stocks_to_use - reference_stocks_to_use)
middle_price = USDA_price_anchor + stu_adjustment
volatility_width = middle_price * implied_volatility * sqrt(horizon_days / 365) * z
low_price = middle_price - volatility_width
high_price = middle_price + volatility_width""",
        language="python",
    )
    st.caption(
        "The live version should replace beta and implied volatility with estimated historical parameters and the selected contract's option-implied volatility. The formulas remain visible so an Extension audience can audit the result."
    )

st.subheader("5. Data and production status")
status_frame = pd.DataFrame(
    [
        ["USDA WASDE anchor", "farm-price projection, release date, vintage", "Validated October 2026 Corn case", "Connected"],
        ["Stocks-to-use signal", "ending stocks / total use", "Validated USDA fields", "Connected"],
        ["USDA Agricultural Baseline", "10-year U.S. projection and vintage", "Versioned benchmark CSV with source link", "Seeded; refresh annually"],
        ["FAPRI-MU", "10-year U.S. baseline and workbook vintage", "Versioned benchmark CSV; provisional value flagged", "Needs workbook refresh"],
        ["OECD-FAO", "global maize reference, USD/tonne, horizon", "Versioned benchmark CSV with source link", "Context only"],
        ["Options-implied volatility", "contract, strike, expiry, IV timestamp", "Manual input in this draft", "Not live yet"],
        ["Historical validation", "forecast error, coverage, calibration", "Future backtest table", "Next model step"],
    ],
    columns=["Data block", "Required fields", "Current implementation", "Status"],
)
st.dataframe(status_frame, width="stretch", hide_index=True)
st.markdown(
    '<div class="warning-callout"><strong>Benchmark discipline:</strong> baseline projections are reference scenarios under stated assumptions, not promises about the next USDA release. The forecast band should not be used as a trading recommendation or a guaranteed probability of profit.</div>',
    unsafe_allow_html=True,
)

download_frame = scenario_frame.copy()
download_frame.insert(0, "commodity", commodity)
download_frame.insert(1, "snapshot_id", selected_id)
download_frame.insert(2, "release_date", case.current_release_date)
download_frame.insert(3, "current_stocks_to_use_pct", current_stu)
download_frame.insert(4, "reference_stocks_to_use_pct", float(reference_stu))
download_frame.insert(5, "annualized_iv_pct", float(annualized_iv))
download_frame.insert(6, "forecast_days", forecast_days)
download_frame.insert(7, "band_multiplier", float(z_value))
download_frame.insert(8, "source", "USDA WASDE anchor + transparent STU sensitivity + manual IV")
st.download_button(
    "Download price forecast CSV",
    download_frame.to_csv(index=False).encode("utf-8"),
    f"{commodity}_{selected_id}_commodity_price_forecast.csv",
    "text/csv",
)

st.caption(
    "This page is an educational prototype for the Fryar Center's recurring USDA report. Before publication, refresh benchmark files, connect option-implied volatility, estimate the historical stocks-to-use relationship, and backtest scenario coverage."
)
