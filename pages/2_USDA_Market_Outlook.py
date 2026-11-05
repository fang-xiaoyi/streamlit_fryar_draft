"""Fryar Center USDA release monitor and report publisher."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import streamlit.components.v1 as components

from history_store import (
    COMMODITY_CATALOG,
    build_case,
    case_records,
    format_snapshot_option,
    latest_snapshot,
)
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
        st.metric("USDA farm price", f"\${case.current['farm_price']:.2f}/bu", f"{metrics['price_change']:+.2f}")
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
st.subheader("3. Report template and auto-filled outputs")
template_col, output_col = st.columns([1, 1.25])
with template_col:
    st.markdown("#### Blank extension-style template")
    st.code(TEMPLATE_SHELLS[case.key], language="text")
    st.caption("Stable sentence structure; direction and magnitude are filled from the selected vintage.")
with output_col:
    fact_html = branded_fact_sheet_html(case)
    full_html = branded_report_html(case)
    fact_tab, report_tab = st.tabs(["Fryar Fact Sheet", "Full Extension Report"])
    with fact_tab:
        components.html(fact_html, height=900, scrolling=True)
        st.download_button("Download Fact Sheet (.html)", fact_html.encode("utf-8"), f"{case.key}_{selected_id}_fact_sheet.html", "text/html")
    with report_tab:
        components.html(full_html, height=1100, scrolling=True)
        st.download_button("Download Full Report (.html)", full_html.encode("utf-8"), f"{case.key}_{selected_id}_full_report.html", "text/html")

st.divider()
st.subheader("4. Refresh, validation, and source check")
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
