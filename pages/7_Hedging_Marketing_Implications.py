"""Hedging and marketing implications page.

This page connects forecast scenarios to the producer's cost structure.  It
keeps the cost breakdown editable, compares it with Arkansas/regional, USDA
national, and own-history benchmarks, and reuses the validated Decision Lab
simulation functions for strategy trade-offs.
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

import core as _core
import history_store as _history_store

importlib.reload(_core)
importlib.reload(_history_store)

from core import (  # noqa: E402
    COMMODITY_DEFAULTS,
    simulate_strategies,
    strategy_options,
    summarize,
    livestock_margin_check,
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
    page_title="Fryar Hedging & Marketing Implications",
    page_icon="🧭",
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
    .hero p {font-size: 1.02rem; max-width: 1000px; margin-bottom: 0; color: #edf6f9;}
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


CROP_COST_ROWS = [
    ("Seed", 120.0),
    ("Fertilizer", 190.0),
    ("Chemicals", 70.0),
    ("Machinery / fuel", 100.0),
    ("Labor / management", 35.0),
    ("Land / rent", 100.0),
    ("Insurance / interest", 35.0),
    ("Other", 20.0),
]

LIVESTOCK_COST_ROWS = [
    ("Pasture / forage", 882.0),
    ("Feed", 403.0),
    ("Health / veterinary", 202.0),
    ("Replacements", 303.0),
    ("Machinery / equipment", 202.0),
    ("Labor / management", 151.0),
    ("Land / ownership", 202.0),
    ("Other", 176.0),
]

BENCHMARK_COLUMNS = [
    "Arkansas / regional",
    "USDA national",
    "Own prior year",
]


def _price(value: object, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"${float(value):,.{decimals}f}"


def _signed(value: object, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):+,.{decimals}f}"


def _pct(value: object, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):+.{decimals}f}%"


def _cost_table(kind: str, commodity: str) -> pd.DataFrame:
    rows = CROP_COST_ROWS if kind == "crop" else LIVESTOCK_COST_ROWS
    return pd.DataFrame(
        {
            "Cost item": [row[0] for row in rows],
            "Current operation": [row[1] for row in rows],
            "Arkansas / regional": [np.nan] * len(rows),
            "USDA national": [np.nan] * len(rows),
            "Own prior year": [np.nan] * len(rows),
        }
    )


def _cost_interpretation(current: float, benchmark: float | None, name: str) -> str:
    if benchmark is None or pd.isna(benchmark):
        return f"No {name} benchmark entered; current value remains the operating assumption."
    difference = current - float(benchmark)
    if abs(difference) < 0.01:
        return f"At {name} benchmark."
    relative = difference / abs(float(benchmark)) * 100.0 if float(benchmark) else np.nan
    if difference > 0:
        return f"{_price(difference)} above {name} ({relative:+.1f}%); check whether scale, input timing, or production practice explains the gap."
    return f"{_price(abs(difference))} below {name} ({relative:+.1f}%); verify that the lower assumption does not omit a real cost or risk."


def _cost_breakdown_frame(costs: pd.DataFrame, unit_label: str) -> pd.DataFrame:
    current_total = float(pd.to_numeric(costs["Current operation"], errors="coerce").fillna(0).sum())
    rows: list[dict[str, object]] = []
    for _, row in costs.iterrows():
        current = float(row["Current operation"]) if pd.notna(row["Current operation"]) else 0.0
        rows.append(
            {
                "Cost item": row["Cost item"],
                f"Current ({unit_label})": current,
                "% of current total": current / current_total * 100.0 if current_total else np.nan,
                "vs Arkansas / regional": _cost_interpretation(current, row["Arkansas / regional"], "Arkansas / regional"),
                "vs USDA national": _cost_interpretation(current, row["USDA national"], "USDA national"),
                "vs own prior year": _cost_interpretation(current, row["Own prior year"], "own prior year"),
            }
        )
    rows.append(
        {
            "Cost item": "TOTAL COST",
            f"Current ({unit_label})": current_total,
            "% of current total": 100.0,
            "vs Arkansas / regional": "Total current operation cost; compare the benchmark total below.",
            "vs USDA national": "Total current operation cost; compare the benchmark total below.",
            "vs own prior year": "Total current operation cost; compare the benchmark total below.",
        }
    )
    return pd.DataFrame(rows)


def _benchmark_totals(costs: pd.DataFrame, current_total: float, unit_label: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for name in ["Current operation"] + BENCHMARK_COLUMNS:
        if name == "Current operation":
            total = current_total
        else:
            values = pd.to_numeric(costs[name], errors="coerce")
            total = float(values.sum()) if values.notna().any() else None
        if total is None:
            rows.append(
                {
                    "Benchmark": name,
                    f"Total cost ({unit_label})": np.nan,
                    "Difference vs current": np.nan,
                    "Difference (%)": np.nan,
                    "Interpretation": f"Enter {name.lower()} values in the cost table to locate the operation against this benchmark.",
                }
            )
            continue
        difference = total - current_total
        if name == "Current operation":
            interpretation = "Reference point: all comparisons are measured against the current operation."
        elif abs(difference) < 0.01:
            interpretation = "Total cost is essentially equal to the current operation."
        elif difference > 0:
            interpretation = f"Benchmark is {_price(difference)} higher; current operation is below this cost reference."
        else:
            interpretation = f"Benchmark is {_price(abs(difference))} lower; current operation is above this cost reference."
        rows.append(
            {
                "Benchmark": name,
                f"Total cost ({unit_label})": total,
                "Difference vs current": difference,
                "Difference (%)": difference / current_total * 100.0 if current_total else np.nan,
                "Interpretation": interpretation,
            }
        )
    return pd.DataFrame(rows)


def _net_price_at(terminal_price: float, strategy: str, params: dict[str, object]) -> float:
    price = float(terminal_price)
    basis = float(params["basis"])
    storage = float(params["storage"])
    entry = float(params["base_price"])
    hedge_ratio = float(params["hedge_ratio"])
    other_revenue_per_cwt = 0.0
    if params["kind"] == "livestock":
        sold_cwt_per_head = float(params["weight_per_head"]) * float(params.get("production_rate", 100.0)) / 10000.0
        if sold_cwt_per_head > 0:
            other_revenue_per_cwt = float(params.get("other_revenue_per_head", 0.0)) / sold_cwt_per_head
    if strategy == "Cash sale now":
        return entry + basis - storage + other_revenue_per_cwt
    if strategy == "Unhedged / wait":
        return price + basis - storage + other_revenue_per_cwt
    if strategy == "Futures hedge":
        return price + basis + hedge_ratio * (entry - price) - storage + other_revenue_per_cwt
    if strategy == "Staged hedge (50% now)":
        return price + basis + 0.50 * hedge_ratio * (entry - price) - storage + other_revenue_per_cwt
    if strategy in {"Put option", "LRP"}:
        return price + basis + hedge_ratio * max(float(params["strike"]) - price, 0.0) - hedge_ratio * float(params["premium"]) - storage + other_revenue_per_cwt
    return price + basis - storage + other_revenue_per_cwt


def _scenario_grid(strategies: list[str], prices: dict[str, float], params: dict[str, object], unit_label: str, cost_per_unit: float, crop: bool, yield_or_cwt: float) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for strategy in strategies:
        row: dict[str, object] = {"Strategy": strategy}
        for name, terminal in prices.items():
            net = _net_price_at(terminal, strategy, params)
            margin = net * yield_or_cwt - cost_per_unit if crop else net - cost_per_unit
            row[f"{name} net price ({unit_label})"] = net
            row[f"{name} margin"] = margin
        rows.append(row)
    return pd.DataFrame(rows)


def _strategy_interpretation(row: pd.Series, break_even: float, margin_column: str) -> str:
    expected_margin = row.get("Expected margin")
    loss_probability = row.get("Loss probability")
    if pd.isna(expected_margin):
        return "No simulation result."
    if expected_margin > 0 and loss_probability < 0.10:
        return "Positive expected margin with relatively low modeled loss risk; consider the remaining basis, volume, and execution risk."
    if expected_margin > 0:
        return "Positive expected margin, but downside risk remains material; this is a candidate for partial or staged protection."
    return "Expected margin is negative under the modeled distribution; review costs, timing, and downside protection before expanding exposure."


def _summary_display(summary: pd.DataFrame, unit_label: str, break_even: float) -> pd.DataFrame:
    output = summary.copy()
    output["Interpretation"] = output.apply(lambda row: _strategy_interpretation(row, break_even, "Expected margin"), axis=1)
    for column in [
        "Expected net price",
        "P10 net price",
        "P50 net price",
        "P90 net price",
        "P10 margin",
        "P50 margin",
        "P90 margin",
        "Expected margin",
        "Expected total margin",
    ]:
        if column in output:
            output[column] = output[column].map(lambda value: "—" if pd.isna(value) else f"${float(value):,.2f}")
    for column in ["Target price probability", "Loss probability", "Positive margin probability", "Probability beats unhedged"]:
        if column in output:
            output[column] = output[column].map(lambda value: "—" if pd.isna(value) else f"{float(value):.1%}")
    return output[
        [
            "Strategy",
            "Expected net price",
            "P10 margin",
            "P50 margin",
            "P90 margin",
            "Loss probability",
            "Positive margin probability",
            "Probability beats unhedged",
            "Interpretation",
        ]
    ]


st.markdown(
    """
    <div class="hero">
      <div class="hero-kicker">Fryar Center · producer decision layer</div>
      <h1>Hedging &amp; Marketing Implications</h1>
      <p>Translate the USDA balance sheet and price range into a producer-facing decision: where is break-even, which costs drive it, how does the operation compare with benchmarks, and what changes across marketing strategies?</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="callout"><strong>Decision logic:</strong> forecast range → cost breakdown → break-even price → benchmark position → strategy trade-off. A positive margin does not automatically mean “sell everything”; it identifies a reason to evaluate partial pricing, staged hedging, or protection against a reversal.</div>',
    unsafe_allow_html=True,
)


with st.sidebar:
    st.header("Operation setup")
    commodity_view = st.selectbox("Commodity / enterprise", ["Corn", "Fed Cattle"])
    defaults = COMMODITY_DEFAULTS[commodity_view]
    kind = defaults["kind"]
    if commodity_view == "Corn":
        records = case_records("corn")
        latest = latest_snapshot("corn")
        latest_id = latest.get("snapshot_id") if latest else None
        snapshot_ids = [str(row["snapshot_id"]) for row in records]
        default_id = latest_id if latest_id in snapshot_ids else snapshot_ids[-1]
        selected_id = st.selectbox(
            "USDA release vintage",
            snapshot_ids,
            index=snapshot_ids.index(default_id),
            format_func=lambda sid: format_snapshot_option(next(row for row in records if row["snapshot_id"] == sid), latest_id),
        )
        case = build_case("corn", selected_id)
        anchor_default = float(case.current["farm_price"])
        current_stu_for_forecast = float(case.current["ending_stocks"]) / float(case.current["total_use"]) * 100.0
        st.caption(f"{case.current_label} · {case.current_release_date}")
        acres = st.number_input("Planted acres", 1.0, 100000.0, float(defaults["acres"]), 10.0)
        yield_per_acre = st.number_input("Expected yield (bu/acre)", 1.0, 1000.0, float(defaults["yield_per_acre"]), 1.0)
        current_price = st.number_input("Current futures / entry price ($/bu)", 0.01, 20.0, anchor_default, 0.05)
        basis = st.number_input("Local basis ($/bu)", -5.0, 5.0, float(defaults["basis"]), 0.01)
        storage = st.number_input("Storage / handling cost ($/bu)", 0.0, 5.0, float(defaults["storage"]), 0.01)
        reference_stu = st.number_input("Reference stocks-to-use (%)", 1.0, 40.0, 12.0, 0.1)
        stu_beta = st.number_input("STU price sensitivity ($/bu per 1 pp)", -2.0, 2.0, -0.15, 0.01)
        hedge_share = st.slider("Planned hedge / protection share", 0.0, 1.0, 0.50, 0.05)
        strike = st.number_input("Put strike / protection price ($/bu)", 0.01, 20.0, float(current_price), 0.05)
        premium = st.number_input("Put premium ($/bu)", 0.0, 5.0, float(defaults["premium"]), 0.01)
        annual_vol = st.number_input("Annualized price volatility / IV (%)", 1.0, 100.0, 25.0, 0.5) / 100.0
        horizon_months = st.number_input("Marketing horizon (months)", 1.0, 36.0, 6.0, 1.0)
        band_multiplier = st.selectbox("Forecast band multiplier", [1.0, 1.645, 1.96], index=0, format_func=lambda value: f"{value} × volatility")
        middle_forecast = current_price + float(stu_beta) * (current_stu_for_forecast - float(reference_stu))
        forecast_width = middle_forecast * annual_vol * np.sqrt(horizon_months / 12.0) * float(band_multiplier)
        forecast_prices = {
            "Low": max(0.01, middle_forecast - forecast_width),
            "Middle": middle_forecast,
            "High": middle_forecast + forecast_width,
        }
    else:
        st.caption("The cattle view uses the same margin, put, and LRP strategy functions as the Producer Decision Lab.")
        head = st.number_input("Head", 1.0, 100000.0, float(defaults["head"]), 10.0)
        production_rate = st.number_input("Sale / weaning rate (%)", 1.0, 100.0, float(defaults["production_rate"]), 1.0)
        weight_per_head = st.number_input("Expected sale weight (lb/head)", 50.0, 2500.0, float(defaults["weight_per_head"]), 10.0)
        other_revenue_per_head = st.number_input("Cull / other revenue ($/head)", 0.0, 10000.0, float(defaults["other_revenue_per_head"]), 5.0)
        current_price = st.number_input("Current futures / reference price ($/cwt)", 1.0, 500.0, float(defaults["base_price"]), 1.0)
        basis = st.number_input("Local basis ($/cwt)", -100.0, 100.0, float(defaults["basis"]), 0.5)
        storage = st.number_input("Handling / timing cost ($/cwt)", 0.0, 50.0, float(defaults["storage"]), 0.5)
        hedge_share = st.slider("LRP / put protection share", 0.0, 1.0, 0.50, 0.05)
        strike = st.number_input("LRP coverage / put strike ($/cwt)", 1.0, 500.0, float(current_price), 1.0)
        premium = st.number_input("Premium ($/cwt)", 0.0, 50.0, float(defaults["premium"]), 0.25)
        annual_vol = st.number_input("Annualized price volatility (%)", 1.0, 100.0, float(defaults["annual_vol"] * 100.0), 0.5) / 100.0
        horizon_months = st.number_input("Marketing horizon (months)", 1.0, 36.0, 6.0, 1.0)
        forecast_prices = {
            "Low": max(1.0, current_price * (1.0 - annual_vol * np.sqrt(horizon_months / 12.0))),
            "Middle": current_price,
            "High": current_price * (1.0 + annual_vol * np.sqrt(horizon_months / 12.0)),
        }
    strategies = st.multiselect(
        "Strategies to compare",
        strategy_options(kind),
        default=strategy_options(kind),
    )


if commodity_view == "Corn":
    unit_label = "$/acre"
    cost_table = _cost_table("crop", commodity_view)
    yield_or_cwt = float(yield_per_acre)
    cost_unit_label = "$/acre"
else:
    unit_label = "$/head"
    cost_table = _cost_table("livestock", commodity_view)
    yield_or_cwt = float(weight_per_head) * float(production_rate) / 10000.0
    cost_unit_label = "$/head"

st.subheader("1. Cost breakdown and benchmark inputs")
st.caption(
    "Enter comparable cost values when available. Blank benchmark cells are not treated as zero. The starting current-operation values are editable demonstration assumptions, not a claim about an average Arkansas farm."
)
edited_costs = st.data_editor(
    cost_table,
    width="stretch",
    hide_index=True,
    disabled=["Cost item"],
    column_config={
        "Current operation": st.column_config.NumberColumn(f"Current operation ({cost_unit_label})", min_value=0.0, format="$%.2f"),
        "Arkansas / regional": st.column_config.NumberColumn(f"Arkansas / regional ({cost_unit_label})", min_value=0.0, format="$%.2f"),
        "USDA national": st.column_config.NumberColumn(f"USDA national ({cost_unit_label})", min_value=0.0, format="$%.2f"),
        "Own prior year": st.column_config.NumberColumn(f"Own prior year ({cost_unit_label})", min_value=0.0, format="$%.2f"),
    },
    key=f"cost_breakdown_{commodity_view}",
)
current_total = float(pd.to_numeric(edited_costs["Current operation"], errors="coerce").fillna(0).sum())

breakdown = _cost_breakdown_frame(edited_costs, cost_unit_label)
st.dataframe(breakdown, width="stretch", hide_index=True)
st.caption("The interpretation columns are intentionally repeated at the cost-item level so the user can see what is driving the gap instead of receiving only one total-cost score.")

st.subheader("2. Break-even and pricing opportunity")
if commodity_view == "Corn":
    cost_per_bushel = current_total / yield_per_acre if yield_per_acre else np.nan
    break_even_cash = cost_per_bushel
    break_even_futures = break_even_cash - basis + storage
    current_net_cash = current_price + basis - storage
    cushion = current_net_cash - break_even_cash
    margin_per_acre = cushion * yield_per_acre
    total_margin = margin_per_acre * acres
    margin_unit = "$/acre"
    operation_params = {
        "kind": "crop",
        "acres": float(acres),
        "yield_per_acre": float(yield_per_acre),
        "cost_per_acre": current_total,
        "base_price": float(current_price),
        "basis": float(basis),
        "storage": float(storage),
        "annual_vol": float(annual_vol),
        "yield_cv": float(defaults["yield_cv"]),
        "target_price": float(break_even_cash),
        "strike": float(strike),
        "premium": float(premium),
        "hedge_ratio": float(hedge_share),
        "horizon_months": float(horizon_months),
    }
else:
    sold_cwt_per_head = float(weight_per_head) * float(production_rate) / 10000.0
    cost_per_cwt = current_total / sold_cwt_per_head if sold_cwt_per_head else np.nan
    other_revenue_per_cwt = other_revenue_per_head / sold_cwt_per_head if sold_cwt_per_head else 0.0
    break_even_cash = cost_per_cwt - other_revenue_per_cwt
    break_even_futures = break_even_cash - basis + storage
    current_net_cash = current_price + basis - storage + other_revenue_per_cwt
    cushion = current_net_cash - cost_per_cwt
    margin_per_acre = cushion
    total_margin = cushion * sold_cwt_per_head * head
    margin_unit = "$/cwt"
    operation_params = {
        "kind": "livestock",
        "head": float(head),
        "weight_per_head": float(weight_per_head),
        "production_rate": float(production_rate),
        "other_revenue_per_head": float(other_revenue_per_head),
        "cost_per_unit": float(cost_per_cwt),
        "base_price": float(current_price),
        "basis": float(basis),
        "storage": float(storage),
        "annual_vol": float(annual_vol),
        "yield_cv": float(defaults["yield_cv"]),
        "target_price": float(break_even_cash),
        "strike": float(strike),
        "premium": float(premium),
        "hedge_ratio": float(hedge_share),
        "horizon_months": float(horizon_months),
        "livestock_costs": {str(row["Cost item"]): float(row["Current operation"]) for _, row in edited_costs.iterrows()},
    }

if commodity_view == "Fed Cattle":
    margin_check = livestock_margin_check(operation_params)
    break_even_cash = float(margin_check["break_even_price_per_cwt"])
    break_even_futures = break_even_cash - basis + storage

status = "favorable" if cushion > 0.25 else "near break-even" if cushion >= -0.25 else "unfavorable"
status_text = {
    "favorable": f"Current net cash price is {_price(cushion)} above break-even. This is a pricing opportunity to evaluate, not an instruction to price 100%.",
    "near break-even": f"Current net cash price is {_price(abs(cushion))} from break-even. Small basis, yield, or cost changes can change the result; staged protection is worth comparing.",
    "unfavorable": f"Current net cash price is {_price(abs(cushion))} below break-even. Review cost assumptions and downside protection before increasing unpriced exposure.",
}[status]

metric_cols = st.columns(5)
metric_cols[0].metric("Current futures / reference", _price(current_price))
metric_cols[1].metric("Current net cash", _price(current_net_cash), f"basis {basis:+.2f}; storage {storage:.2f}")
metric_cols[2].metric("Break-even cash", _price(break_even_cash))
metric_cols[3].metric("Break-even futures", _price(break_even_futures))
metric_cols[4].metric("Margin cushion", _price(cushion), status)
st.markdown(f'<div class="interpretation"><strong>Interpretation:</strong> {status_text}<br>At the entered assumptions, the modeled current margin is {_price(margin_per_acre)} {margin_unit}; total operation margin is approximately {_price(total_margin)}. The main check is whether the price cushion is large enough to absorb basis, yield, cost, and execution uncertainty.</div>', unsafe_allow_html=True)

st.subheader("3. Benchmark position: where is this operation?")
totals = _benchmark_totals(edited_costs, current_total, cost_unit_label)
if commodity_view == "Corn":
    totals["Cost per bushel"] = totals[f"Total cost ({cost_unit_label})"] / float(yield_per_acre)
    totals["Break-even cash price"] = totals["Cost per bushel"]
else:
    totals["Cost per cwt"] = totals[f"Total cost ({cost_unit_label})"] / float(sold_cwt_per_head)
    totals["Break-even cash price"] = totals["Cost per cwt"] - other_revenue_per_cwt
display_totals = totals.copy()
for column in [f"Total cost ({cost_unit_label})", "Difference vs current", "Cost per bushel", "Cost per cwt", "Break-even cash price"]:
    if column in display_totals:
        display_totals[column] = display_totals[column].map(lambda value: "—" if pd.isna(value) else f"${float(value):,.2f}")
if "Difference (%)" in display_totals:
    display_totals["Difference (%)"] = display_totals["Difference (%)"].map(lambda value: "—" if pd.isna(value) else f"{float(value):+.1f}%")
st.dataframe(display_totals, width="stretch", hide_index=True)
st.markdown(
    '<div class="callout"><strong>Benchmark interpretation:</strong> the page separates “where my total cost is” from “why it is there.” The row-level table above identifies whether seed, fertilizer, feed, land, labor, or another category is driving the difference. Add the matching source year, enterprise definition, and units before treating a benchmark gap as a management problem.</div>',
    unsafe_allow_html=True,
)

st.subheader("4. Scenario margins across pricing strategies")
if not strategies:
    st.info("Select at least one pricing strategy in the sidebar.")
else:
    simulation, _ = simulate_strategies(operation_params, strategies, n=8000, seed=2027)
    summary = summarize(simulation, operation_params)
    st.dataframe(_summary_display(summary, "$/bu" if commodity_view == "Corn" else "$/cwt", break_even_cash), width="stretch", hide_index=True)

    grid_cost = current_total if commodity_view == "Corn" else cost_per_cwt
    grid = _scenario_grid(
        strategies,
        forecast_prices,
        operation_params,
        "$ / bu" if commodity_view == "Corn" else "$ / cwt",
        grid_cost,
        commodity_view == "Corn",
        yield_or_cwt,
    )
    grid_display = grid.copy()
    for column in grid_display.columns:
        if column != "Strategy":
            grid_display[column] = grid_display[column].map(lambda value: "—" if pd.isna(value) else f"${float(value):,.2f}")
    st.caption("Scenario grid: low/middle/high are terminal price paths; the simulation table above adds price and quantity uncertainty and reports modeled probabilities.")
    st.dataframe(grid_display, width="stretch", hide_index=True)

    chart = go.Figure()
    for strategy in strategies:
        row = grid.loc[grid["Strategy"] == strategy].iloc[0]
        margin_values = [row[f"{label} margin"] for label in ["Low", "Middle", "High"]]
        chart.add_trace(go.Scatter(x=["Low", "Middle", "High"], y=margin_values, mode="lines+markers", name=strategy))
    chart.add_hline(y=0, line_dash="dash", line_color="#9E2B44")
    chart.update_layout(
        title="Margin response by terminal-price scenario",
        yaxis_title=f"Margin ({margin_unit})",
        height=430,
        template="plotly_white",
        margin=dict(l=10, r=10, t=55, b=10),
        legend=dict(orientation="h", y=-0.25, x=0),
    )
    st.plotly_chart(chart, width="stretch", config={"displayModeBar": False})

st.subheader("5. Formula and interpretation layer")
st.code(
    """net_cash_price = futures_price + basis - storage
break_even_cash_price = total_cost / expected_quantity
break_even_futures_price = break_even_cash_price - basis + storage
margin = (net_cash_price - break_even_cash_price) * expected_quantity
strategy_result = cash_price + basis + hedge_or_option_payoff - protection_cost - storage
""",
    language="python",
)
st.markdown(
    '<div class="warning-callout"><strong>Use in the report:</strong> this page turns the price forecast into a decision cue, but it does not choose the producer’s position. The final recommendation still depends on basis confidence, yield risk, cash-flow needs, contract mechanics, insurance rules, and risk tolerance. The LRP/put formulas reuse the Decision Lab teaching model and require policy/contract validation before public production use.</div>',
    unsafe_allow_html=True,
)

download = breakdown.copy()
download.insert(0, "commodity_or_enterprise", commodity_view)
download.insert(1, "current_price", current_price)
download.insert(2, "current_net_cash", current_net_cash)
download.insert(3, "break_even_cash", break_even_cash)
download.insert(4, "break_even_futures", break_even_futures)
download.insert(5, "margin_cushion", cushion)
st.download_button(
    "Download cost and marketing implications CSV",
    download.to_csv(index=False).encode("utf-8"),
    f"{commodity_view.lower().replace(' ', '_')}_hedging_marketing_implications.csv",
    "text/csv",
)

st.caption(
    "This page is an educational producer-decision prototype. Benchmark values should be matched by enterprise, geography, source year, unit, and production system before publication."
)
