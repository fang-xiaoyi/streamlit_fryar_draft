"""Fryar Center USDA release monitor and report publisher."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import importlib
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go

# Streamlit Cloud can retain an older imported module during a hot reload.
# Reload the small read-only store before importing its functions so the page
# immediately picks up month-vintage comparison logic and the current catalog.
import history_store as _history_store
importlib.reload(_history_store)

from history_store import (
    build_case,
    case_records,
    format_snapshot_option,
    latest_snapshot,
)

# Keep the page resilient during a Streamlit Cloud hot reload.  A long-lived
# process can temporarily retain an older ``history_store`` module while the
# page file has already been refreshed, so the UI catalog has a local fallback.
try:
    from history_store import COMMODITY_CATALOG
except ImportError:
    COMMODITY_CATALOG = {
        "corn": {
            "label": "Corn — WASDE",
            "status": "validated",
            "source_family": "USDA WASDE",
        },
        "cattle": {
            "label": "Cattle — Cattle on Feed",
            "status": "validated",
            "source_family": "USDA Cattle on Feed",
        },
        "soybeans": {
            "label": "Soybeans — WASDE (planned)",
            "status": "planned",
            "source_family": "USDA WASDE",
        },
        "wheat": {
            "label": "Wheat — WASDE (planned)",
            "status": "planned",
            "source_family": "USDA WASDE",
        },
        "cotton": {
            "label": "Cotton — WASDE (planned)",
            "status": "planned",
            "source_family": "USDA WASDE",
        },
        "rice": {
            "label": "Rice — WASDE (planned)",
            "status": "planned",
            "source_family": "USDA WASDE",
        },
        "hogs": {
            "label": "Hogs — Hogs and Pigs (planned)",
            "status": "planned",
            "source_family": "USDA NASS Hogs and Pigs",
        },
        "broilers": {
            "label": "Broilers — poultry outlook (planned)",
            "status": "planned",
            "source_family": "USDA poultry reports",
        },
        "milk": {
            "label": "Milk — Milk Production (planned)",
            "status": "planned",
            "source_family": "USDA NASS Milk Production",
        },
    }
from usda_report_pipeline import (
    TEMPLATE_SHELLS,
    branded_fact_sheet_html,
    branded_report_html,
    check_source,
    comparison_frame,
    generated_report,
    metrics_for,
    next_release_status,
    yoy_frame,
)
import market_context as _market_context
importlib.reload(_market_context)
from market_context import (  # noqa: E402
    consensus_summary,
    consensus_surprise_frame,
    context_for,
    enhanced_fact_sheet_html,
    enhanced_report_html,
    full_report_markdown,
    market_reaction_frame,
    marketing_implications,
    price_outlook,
    price_outlook_frame,
)

st.set_page_config(page_title="Fryar USDA Market Outlook", page_icon="📊", layout="wide")


def signed(value, decimals=0):
    return f"{value:+,.{decimals}f}"


st.title("Fryar USDA Release & Decision Report")
st.caption("Official USDA snapshot → transparent formulas → extension-style report → producer decision cue")

with st.sidebar:
    st.header("Choose a release vintage")
    commodity_keys = list(COMMODITY_CATALOG)
    commodity = st.selectbox(
        "Commodity",
        commodity_keys,
        format_func=lambda key: COMMODITY_CATALOG[key]["label"],
    )
    commodity_meta = COMMODITY_CATALOG[commodity]
    records = case_records(commodity)
    latest = latest_snapshot(commodity)
    if not records:
        st.info(
            f"{commodity_meta['label']} is in the product catalog, but no validated "
            f"release pair is available yet. The planned source family is "
            f"**{commodity_meta['source_family']}**. Corn and Cattle are the current "
            "working prototypes; this slot is ready for a future parser, normalized "
            "snapshot, and automated report template."
        )
        st.caption(
            "Planned workflow: source check → month-vintage parser → validation → "
            "fact sheet → full report → historical release archive."
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
    selected = next(row for row in records if row["snapshot_id"] == selected_id)
    case = build_case(commodity, selected_id)
    st.caption("Snapshot ID: " + selected_id + " · validated by " + str(selected.get("parser_version", "unknown")))
    st.divider()
    st.subheader("Pipeline status")
    st.write("Latest validated: " + str(latest.get("release_label", latest.get("release_date"))) if latest else "No latest pointer")
    st.write("Current: " + case.current_label)
    st.write("Comparison base: " + case.previous_label)
    st.write("Next target: " + str(case.next_release_date))

status = next_release_status(case, today=date.today())
if status["released"]:
    st.success(status["label"] + " is expected to be available; run the refresh workflow to ingest it.")
else:
    st.info(
        "This report compares " + case.current_label + " with " + case.previous_label
        + ". The pipeline does not invent an unreleased estimate; next scheduled release: "
        + str(status["date"]) + "."
    )

st.subheader("1. Big picture")
left, right = st.columns([1.45, 1])
with left:
    st.markdown("### What changed and why it matters")
    st.write(generated_report(case))
    st.caption(case.note)
with right:
    metrics = metrics_for(case)
    if commodity == "corn":
        st.metric("Ending stocks", str(case.current["ending_stocks"]) + " M bu", signed(metrics["ending_change"]))
        st.metric("Stocks / use", f"{metrics['current_stu']:.1f}%", f"{metrics['stu_change_pp']:+.1f} pp")
        st.metric("Production", str(case.current["production"]) + " M bu", signed(metrics["production_change"]))
        st.metric("USDA farm price", f"${case.current['farm_price']:.2f}/bu", f"{metrics['price_change']:+.2f}")
    else:
        st.metric("Oct 1 inventory", str(case.current["inventory"]) + "k head", signed(metrics["inventory_change"]))
        st.metric("Sep placements", str(case.current["placements"]) + "k", f"{metrics['placements_yoy_delta']:+.0f} pp y/y")
        st.metric("Sep marketings", str(case.current["marketings"]) + "k", f"{metrics['marketings_yoy_delta']:+.0f} pp y/y")
        st.metric("Other disappearance", str(case.current["other_disappearance"]) + "k", f"{metrics['other_disappearance_yoy_delta']:+.0f} pp y/y")

st.divider()
st.subheader("2. Detailed movement")
st.dataframe(comparison_frame(case), width="stretch", hide_index=True)
if commodity == "cattle":
    st.markdown("#### Year-over-year read")
    st.dataframe(yoy_frame(case), width="stretch", hide_index=True)
else:
    st.markdown("#### Balance-sheet formula")
    st.code("stocks_to_use = ending_stocks / total_use\nending_stock_change = current_ending_stocks - previous_ending_stocks\nprice_signal = read with production, use, and stocks_to_use", language="text")

st.divider()
st.subheader("3. Consensus surprise")
st.caption("USDA release → data revision → comparison with the pre-release market expectation.")
context = context_for(case)
if context.get("status") == "illustrative_demo":
    st.warning("Illustrative market context is active for this interview demo. Replace it with an approved, timestamped consensus source before public release.")
consensus = consensus_summary(case)
if consensus["status"] == "loaded":
    cols = st.columns([1, 2])
    cols[0].metric("Consensus read", consensus["label"])
    cols[1].write(consensus["headline"])
    cols[1].caption(f"Source: {consensus['source_label']}")
st.dataframe(consensus_surprise_frame(case), width="stretch", hide_index=True)

st.subheader("4. Market price response")
st.caption("Nearby futures, deferred futures, calendar spread, and volatility around the release.")
reaction = market_reaction_frame(case)
if reaction.empty:
    st.info("No approved futures/options observation set is loaded for this release.")
else:
    left, right = st.columns([1.1, 1])
    with left:
        st.dataframe(reaction, width="stretch", hide_index=True)
    with right:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=reaction["Date"], y=reaction["Nearby futures"], mode="lines+markers", name="Nearby", line=dict(color="#9E2B44", width=3)))
        fig.add_trace(go.Scatter(x=reaction["Date"], y=reaction["Deferred futures"], mode="lines+markers", name="Deferred", line=dict(color="#2EA3F2", width=2)))
        fig.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=35), yaxis_title="$/bushel", legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig, width="stretch")

st.subheader("5. Price outlook")
st.caption("Low / Middle / High are conditional price scenarios, not guaranteed forecasts.")
outlook = price_outlook(case)
if outlook["status"] == "loaded":
    stat_cols = st.columns(4)
    stat_cols[0].metric("Reference", f"${outlook['reference_price']:.2f}/bu")
    stat_cols[1].metric("Annualized volatility", f"{outlook['annualized_iv']:.1%}")
    stat_cols[2].metric("Horizon", f"{outlook['horizon_days']} days")
    stat_cols[3].metric("Scenario σ", f"${outlook['sigma']:.2f}/bu")
    outlook_table = price_outlook_frame(case)
    st.dataframe(outlook_table, width="stretch", hide_index=True)
    fig = go.Figure(go.Bar(x=outlook_table["Scenario"], y=outlook_table["Price midpoint"], error_y=dict(type="data", symmetric=False, array=outlook_table["Price high"] - outlook_table["Price midpoint"], arrayminus=outlook_table["Price midpoint"] - outlook_table["Price low"]), text=[f"{p:.0%}" for p in outlook_table["Probability"]], textposition="auto", marker_color=["#9E2B44", "#52606D", "#2EA3F2"]))
    fig.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=35), yaxis_title="$/bushel", showlegend=False)
    st.plotly_chart(fig, width="stretch")
    st.caption(outlook["method_label"])
else:
    st.info(outlook["method_label"])

st.subheader("6. Hedging and marketing implications")
implications = marketing_implications(case)
if implications["status"] == "loaded":
    st.write(implications["break_even_read"])
    st.write(implications["carry_read"])
    st.dataframe(implications["strategies"], width="stretch", hide_index=True)
    st.info(implications["cue"])
else:
    st.info("No validated market context is loaded for this release.")

st.divider()
st.subheader("7. Report template and auto-filled outputs")
template_col, output_col = st.columns([1, 1.25])
with template_col:
    st.markdown("#### Blank extension-style template")
    st.code(TEMPLATE_SHELLS[case.key], language="text")
    st.caption("Stable sentence structure; direction and magnitude are filled from the selected vintage.")
with output_col:
    fact_html = enhanced_fact_sheet_html(case)
    full_html = enhanced_report_html(case)
    fact_tab, report_tab = st.tabs(["Fryar Fact Sheet", "Full Extension Report"])
    with fact_tab:
        components.html(fact_html, height=900, scrolling=True)
        st.download_button("Download Fact Sheet (.html)", fact_html.encode("utf-8"), f"{case.key}_{selected_id}_fact_sheet.html", "text/html")
    with report_tab:
        components.html(full_html, height=1100, scrolling=True)
        st.download_button("Download Full Report (.html)", full_html.encode("utf-8"), f"{case.key}_{selected_id}_full_report.html", "text/html")
    st.download_button("Download Full Report (.md)", full_report_markdown(case).encode("utf-8"), f"{case.key}_{selected_id}_full_report.md", "text/markdown")

st.divider()
st.subheader("8. Refresh, validation, and source check")
st.write("Scheduled workflow: download official USDA file → parse → validate units/date → store immutable snapshot → generate Fact Sheet and Full Report → commit to GitHub → Streamlit redeploy.")
if st.button("Check selected official source now"):
    result = check_source(case.sources[0][1])
    if result.get("ok"):
        st.success("Reachable · HTTP " + str(result.get("status_code")) + " · checked " + str(result.get("checked_at")))
    else:
        st.warning(result.get("message", "Source check failed"))
st.markdown("Official source: [" + case.sources[0][0] + "](" + case.sources[0][1] + ")")
st.warning("Public release still receives a human review gate for interpretation, vintage handling, and licensed market-data use.")

comparison = comparison_frame(case).copy()
comparison.insert(0, "commodity", case.commodity)
comparison.insert(1, "current_release_date", case.current_release_date)
comparison.insert(2, "previous_release_date", case.previous_release_date)
st.download_button("Download normalized comparison (.csv)", comparison.to_csv(index=False).encode("utf-8"), f"{case.key}_{selected_id}_comparison.csv", "text/csv")
