"""Separate USDA supply-and-demand analysis page.

This page deliberately sits apart from the hedging Decision Lab and the report
publisher.  It makes the balance-sheet data, required inputs, and formulas
visible before any market or price-risk interpretation is added.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import importlib
import sys

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
    page_title="Fryar Supply & Demand Analysis",
    page_icon="📐",
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
    [data-testid="stSidebar"] {background: #f5f8fa;}
    </style>
    """,
    unsafe_allow_html=True,
)


def _signed(value: float | None, decimals: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):+,.{decimals}f}"


def _number(value: float | None, decimals: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):,.{decimals}f}"


def _pct(value: float | None, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):+.{decimals}f}%"


def _optional_float(raw: str) -> float | None:
    value = raw.strip().replace(",", "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return float(current) - float(previous)


def _change_pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (float(current) - float(previous)) / abs(float(previous)) * 100.0


def _signal(field: str, surprise: float | None) -> str:
    if surprise is None or pd.isna(surprise):
        return "Consensus not entered"
    if abs(float(surprise)) < 1e-9:
        return "In line with consensus"
    supply_fields = {"beginning_stocks", "production", "yield", "ending_stocks"}
    demand_fields = {"total_use", "exports", "feed_residual", "ethanol"}
    if field in supply_fields:
        return "Bearish pressure" if surprise > 0 else "Bullish pressure"
    if field in demand_fields:
        return "Bullish demand" if surprise > 0 else "Bearish demand"
    return "Interpret with context"


def _corn_fields() -> list[tuple[str, str, str, str]]:
    return [
        ("Beginning stocks", "beginning_stocks", "million bu", "supply"),
        ("Production", "production", "million bu", "supply"),
        ("Yield", "yield", "bu/acre", "supply"),
        ("Total use", "total_use", "million bu", "demand"),
        ("Exports", "exports", "million bu", "demand"),
        ("Feed and residual", "feed_residual", "million bu", "demand"),
        ("Ethanol", "ethanol", "million bu", "demand"),
        ("Ending stocks", "ending_stocks", "million bu", "balance"),
    ]


def _movement_frame(case, consensus: dict[str, float | None]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for label, field, units, category in _corn_fields():
        previous = case.previous.get(field)
        current = case.current.get(field)
        expected = consensus.get(field)
        surprise = _change(current, expected)
        rows.append(
            {
                "Category": category.title(),
                "Measure": label,
                "Previous USDA": previous,
                "Current USDA": current,
                "Change": _change(current, previous),
                "Change %": _change_pct(current, previous),
                "Consensus": expected,
                "USDA − consensus": surprise,
                "Units": units,
                "Read": _signal(field, surprise),
            }
        )
    return pd.DataFrame(rows)


def _format_table(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in [
        "Previous USDA",
        "Current USDA",
        "Change",
        "Consensus",
        "USDA − consensus",
    ]:
        if column in output:
            output[column] = output[column].map(
                lambda value: "—" if pd.isna(value) else f"{float(value):,.2f}"
            )
    if "Change %" in output:
        output["Change %"] = output["Change %"].map(
            lambda value: "—" if pd.isna(value) else f"{float(value):+.1f}%"
        )
    return output


st.markdown(
    """
    <div class="hero">
      <div class="hero-kicker">Fryar Center · USDA analytical layer</div>
      <h1>Supply &amp; Demand Analysis</h1>
      <p>Make the USDA balance sheet explicit: what changed from the previous release, what differs from the pre-release consensus, and how the change flows into ending stocks and stocks-to-use.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="callout"><strong>Scope:</strong> This page is intentionally separate from the hedging Decision Lab and the branded report publisher. It is the transparent supply-and-demand calculation layer that can later feed the price-outlook and marketing pages.</div>',
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
            "This page currently has a complete supply-and-demand case for Corn."
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
    st.caption(
        f"{case.current_label} · prior release: {case.previous_label} · "
        f"snapshot {selected_id}"
    )
    st.divider()
    st.subheader("Pre-release consensus")
    st.caption(
        "Enter a licensed or manually collected consensus estimate. Blank fields are not treated as zero."
    )
    consensus: dict[str, float | None] = {}
    if commodity == "corn":
        for label, field, units, _category in _corn_fields():
            if field == "feed_residual" or field == "ethanol":
                continue
            consensus[field] = _optional_float(
                st.text_input(
                    f"{label} ({units})",
                    value="",
                    key=f"consensus_{field}_{selected_id}",
                )
            )
    else:
        st.info("Consensus input is currently implemented for the Corn case first.")


if commodity != "corn":
    st.warning("The current validated supply-and-demand schema is the Corn WASDE case. Add a commodity-specific parser before interpreting another commodity.")
    st.stop()


current = case.current
previous = case.previous
movement = _movement_frame(case, consensus)
metrics = metrics_for(case)

st.subheader("1. Big picture")
big_cols = st.columns(4)
big_cols[0].metric(
    "Ending stocks",
    f"{_number(current['ending_stocks'])} M bu",
    _signed(metrics["ending_change"]),
)
big_cols[1].metric(
    "Stocks-to-use",
    f"{metrics['current_stu']:.1f}%",
    f"{metrics['stu_change_pp']:+.1f} pp",
)
big_cols[2].metric(
    "Production",
    f"{_number(current['production'])} M bu",
    _signed(metrics["production_change"]),
)
big_cols[3].metric(
    "Total use",
    f"{_number(current['total_use'])} M bu",
    _signed(current["total_use"] - previous["total_use"]),
)

st.caption(
    f"Source: {selected_record.get('source_label', case.current_label)} · "
    f"released {case.current_release_date} · parser {selected_record.get('parser_version', 'unknown')}"
)

st.subheader("2. Supply side")
supply_fields = movement[movement["Category"] == "Supply"].copy()
st.dataframe(_format_table(supply_fields), width="stretch", hide_index=True)
st.caption(
    "Supply-side inputs are beginning stocks, production, and yield. Imports are required to close a complete balance sheet but are not present in the current seeded Corn schema."
)

st.subheader("3. Demand side")
demand_fields = movement[movement["Category"] == "Demand"].copy()
st.dataframe(_format_table(demand_fields), width="stretch", hide_index=True)
implied_other_use = float(current["total_use"] - current["exports"] - current["feed_residual"] - current["ethanol"])
prior_implied_other_use = float(previous["total_use"] - previous["exports"] - previous["feed_residual"] - previous["ethanol"])
demand_cols = st.columns(3)
demand_cols[0].metric("Implied other use", f"{implied_other_use:,.0f} M bu", f"{implied_other_use - prior_implied_other_use:+,.0f}")
demand_cols[1].metric("Exports share of use", f"{current['exports'] / current['total_use']:.1%}")
demand_cols[2].metric("Feed + ethanol share", f"{(current['feed_residual'] + current['ethanol']) / current['total_use']:.1%}")
st.caption("Implied other use is a diagnostic residual: total use minus the currently available exports, feed/residual, and ethanol fields. It is not a separately published USDA line item.")

st.subheader("4. Ending stocks and stocks-to-use")
balance_cols = st.columns(3)
balance_cols[0].metric("Ending stocks", f"{_number(current['ending_stocks'])} M bu")
balance_cols[1].metric("Total use", f"{_number(current['total_use'])} M bu")
balance_cols[2].metric("Stocks-to-use", f"{metrics['current_stu']:.1f}%", f"{metrics['stu_change_pp']:+.1f} pp vs prior")

fig = go.Figure()
fig.add_trace(
    go.Bar(
        x=["Previous release", "Current release"],
        y=[previous["ending_stocks"], current["ending_stocks"]],
        name="Ending stocks",
        marker_color="#4c956c",
    )
)
fig.add_trace(
    go.Bar(
        x=["Previous release", "Current release"],
        y=[previous["total_use"], current["total_use"]],
        name="Total use",
        marker_color="#9fb3c8",
    )
)
fig.update_layout(
    title="Corn balance-sheet scale",
    yaxis_title="Million bushels",
    barmode="group",
    height=360,
    template="plotly_white",
    margin=dict(l=10, r=10, t=55, b=10),
)
st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

st.code(
    """stocks_to_use = ending_stocks / total_use
ending_stock_change = current_ending_stocks - previous_ending_stocks
stocks_to_use_change_pp = current_stocks_to_use - previous_stocks_to_use
complete_balance = beginning_stocks + production + imports - total_use
ending_stocks_surprise = current_ending_stocks - consensus_ending_stocks""",
    language="python",
)
st.warning(
    "Data gap to resolve before production use: the current Corn snapshot does not yet include imports, so the complete supply balance cannot be independently reconciled. Add imports and any other published supply lines to the normalized schema."
)

st.subheader("5. USDA versus pre-release consensus")
surprise_frame = movement[movement["Consensus"].notna()].copy()
if surprise_frame.empty:
    st.info(
        "No consensus values have been entered for this vintage. The page is ready for a Bloomberg or manually collected consensus file, but it does not invent consensus estimates."
    )
else:
    st.dataframe(_format_table(surprise_frame), width="stretch", hide_index=True)
    st.caption(
        "For production, yield, and ending stocks, a positive surprise generally adds supply pressure. For total use and exports, a positive surprise generally adds demand support. The label is a first-pass interpretation and still requires analyst review."
    )

st.subheader("6. Data required for the recurring version")
required_data = pd.DataFrame(
    [
        ["USDA release", "release_date, report_label, source_url, parser_version", "USDA WASDE PDF/table", "Required"],
        ["Previous USDA vintage", "same fields for prior monthly release", "Versioned release store", "Required"],
        ["Supply lines", "beginning_stocks, production, yield, imports", "WASDE balance sheet", "Imports missing in current seed"],
        ["Demand lines", "total_use plus exports/feed/ethanol/other use", "WASDE balance sheet", "Required"],
        ["Consensus", "estimate, high/low range, timestamp, source", "Licensed consensus feed or manual file", "Not connected"],
        ["Units and scope", "marketing year, geography, units, conversion", "USDA metadata", "Required"],
        ["Validation", "balance check, missing fields, revision flag", "Pipeline QA", "Partly implemented"],
    ],
    columns=["Data block", "Fields", "Source", "Current status"],
)
st.dataframe(required_data, width="stretch", hide_index=True)

download_frame = movement.copy()
download_frame.insert(0, "commodity", case.commodity)
download_frame.insert(1, "current_release_date", case.current_release_date)
download_frame.insert(2, "previous_release_date", case.previous_release_date)
st.download_button(
    "Download supply-demand analysis CSV",
    download_frame.to_csv(index=False).encode("utf-8"),
    f"{commodity}_{selected_id}_supply_demand_analysis.csv",
    "text/csv",
)

st.caption(
    "This page separates the USDA balance-sheet analysis from the market-price and hedging decision tools. It is an educational prototype and requires source, units, and interpretation review before public release."
)
