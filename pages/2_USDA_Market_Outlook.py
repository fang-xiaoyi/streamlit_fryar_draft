"""USDA release monitor and auto-generated extension-style report."""

from __future__ import annotations

from datetime import date

import plotly.graph_objects as go
import streamlit as st

from usda_report_pipeline import (
    CASES,
    TEMPLATE_SHELLS,
    check_source,
    comparison_frame,
    generated_report,
    get_case,
    metrics_for,
    next_release_status,
    yoy_frame,
)


st.set_page_config(
    page_title="Fryar USDA Market Outlook",
    page_icon="📊",
    layout="wide",
)


def signed(value: float, decimals: int = 0) -> str:
    return f"{value:+,.{decimals}f}"


@st.cache_data(ttl=3600, show_spinner=False)
def cached_source_check(url: str) -> dict:
    return check_source(url)


st.title("Fryar USDA Release & Decision Report")
st.caption(
    "Tool 2 · official USDA snapshot → transparent formulas → extension-style report → producer decision cue"
)


with st.sidebar:
    st.header("Choose the real case")
    case_key = st.selectbox(
        "Commodity / release",
        options=list(CASES),
        format_func=lambda key: "Corn — WASDE" if key == "corn" else "Cattle — Cattle on Feed",
    )
    case = get_case(case_key)
    st.divider()
    st.subheader("Pipeline target")
    st.write(f"Current snapshot: **{case.current_label}**")
    st.write(f"Next target: **{case.next_release_label}**")
    st.caption(f"Scheduled date: {case.next_release_date}")


status = next_release_status(case, today=date.today())
if status["released"]:
    st.success(
        f"{status['label']} is now expected to be available. Click the source check below, "
        "then replace the snapshot after the official file is parsed."
    )
else:
    st.info(
        f"Case uses the latest completed releases: {case.current_label} versus {case.previous_label}. "
        f"{status['label']} is scheduled for {status['date']} ({status['days_until']} days from the app date). "
        "The app does not invent a November estimate."
    )


st.subheader("1. Big picture")
big_left, big_right = st.columns([1.45, 1.0])
with big_left:
    st.markdown(f"### {case.commodity}: what changed and why it matters")
    st.write(generated_report(case))
    st.caption(case.note)

with big_right:
    if case.key == "corn":
        metrics = metrics_for(case)
        cards = st.columns(2)
        cards[0].metric("Ending stocks", f"{case.current['ending_stocks']:,} M bu", signed(metrics["ending_change"], 0))
        cards[1].metric("Stocks / use", f"{metrics['current_stu']:.1f}%", f"{metrics['stu_change_pp']:+.1f} pp")
        cards[0].metric("Production", f"{case.current['production']:,} M bu", signed(metrics["production_change"], 0))
        cards[1].metric("USDA farm price", f"${case.current['farm_price']:.2f}/bu", f"{metrics['price_change']:+.2f}")
    else:
        metrics = metrics_for(case)
        cards = st.columns(2)
        cards[0].metric("Oct 1 inventory", f"{case.current['inventory']:,}k head", signed(metrics["inventory_change"], 0))
        cards[1].metric("Sep placements", f"{case.current['placements']:,}k", f"{metrics['placements_yoy_delta']:+.0f} pp y/y")
        cards[0].metric("Sep marketings", f"{case.current['marketings']:,}k", f"{metrics['marketings_yoy_delta']:+.0f} pp y/y")
        cards[1].metric("Other disappearance", f"{case.current['other_disappearance']:,}k", f"{metrics['other_disappearance_yoy_delta']:+.0f} pp y/y")


st.divider()
st.subheader("2. Detailed movement")
comparison = comparison_frame(case)
detail_left, detail_right = st.columns([1.1, 1.0])
with detail_left:
    st.dataframe(comparison, width="stretch", hide_index=True)
with detail_right:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name=case.previous_label,
            x=comparison["Measure"],
            y=comparison[case.previous_label],
            marker_color="#CBD5E1",
        )
    )
    fig.add_trace(
        go.Bar(
            name=case.current_label,
            x=comparison["Measure"],
            y=comparison[case.current_label],
            marker_color="#0F766E",
        )
    )
    fig.update_layout(
        barmode="group",
        height=340,
        margin=dict(l=20, r=20, t=20, b=70),
        yaxis_title="Reported quantity",
        legend=dict(orientation="h", y=1.12),
    )
    st.plotly_chart(fig, width="stretch")

if case.key == "cattle":
    st.markdown("#### Year-over-year read in the October release")
    st.dataframe(yoy_frame(case), width="stretch", hide_index=True)
else:
    st.markdown("#### Balance-sheet formula")
    st.code(
        "stocks_to_use = ending_stocks / total_use\n"
        "ending_stock_change = October_ending_stocks - September_ending_stocks\n"
        "price_signal = read together with production, use, and stocks_to_use",
        language="text",
    )


st.divider()
st.subheader("3. Report template → auto-filled report")
template_col, report_col = st.columns([1.0, 1.2])
with template_col:
    st.markdown("#### Blank template used by the pipeline")
    st.code(TEMPLATE_SHELLS[case.key], language="text")
    st.caption(
        "The blank tokens make the workflow auditable: the sentence structure is stable, "
        "while direction and magnitude are generated from the data rather than hand-written."
    )
with report_col:
    st.markdown("#### Auto-generated extension-style report")
    st.info(generated_report(case))
    report_markdown = (
        f"# {case.commodity} USDA release report\n\n"
        f"**Current release:** {case.current_label}  \n"
        f"**Previous release:** {case.previous_label}\n\n"
        f"{generated_report(case)}\n\n"
        f"## Data note\n{case.note}\n\n"
        "## Official sources\n"
        + "\n".join(f"- [{label}]({url})" for label, url in case.sources)
    )
    st.download_button(
        "Download report (.md)",
        data=report_markdown.encode("utf-8"),
        file_name=f"{case.key}_usda_release_report.md",
        mime="text/markdown",
    )


st.divider()
st.subheader("4. Pipeline readiness and source check")
st.write(
    "The production workflow is: scheduled USDA download → parse into a normalized snapshot → "
    "validate units and release date → calculate formulas → generate report → human review → publish."
)
check_col, source_col = st.columns([1.0, 1.4])
with check_col:
    if st.button("Check official source now", type="secondary"):
        st.session_state["source_check"] = cached_source_check(status["url"])
with source_col:
    result = st.session_state.get("source_check")
    if result:
        if result["ok"]:
            st.success(f"Reachable · HTTP {result['status_code']} · checked {result['checked_at']}")
        else:
            st.warning(result["message"])
    st.markdown(f"Next official source: [{status['url']}]({status['url']})")

st.markdown("#### Data governance gate")
st.warning(
    "Before public deployment, confirm USDA vintage handling, any licensed consensus/market-data access, "
    "the scheduled refresh owner, and a human sign-off for the published interpretation."
)


download_data = comparison.copy()
download_data.insert(0, "commodity", case.commodity)
download_data.insert(1, "report", case.report)
download_data.insert(2, "current_release_date", case.current_release_date)
download_data.insert(3, "previous_release_date", case.previous_release_date)
st.download_button(
    "Download normalized comparison (.csv)",
    data=download_data.to_csv(index=False).encode("utf-8"),
    file_name=f"{case.key}_usda_release_comparison.csv",
    mime="text/csv",
)
