"""Fryar Center monthly USDA report production studio.

This page is intentionally an editorial and publication layer above the
validated release store.  It does not write to the repository from a browser;
it assembles a reproducible in-memory report package for review and download.
The scheduled refresh workflow remains responsible for immutable snapshots,
history, and generated files under ``data/reports``.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path
import html
import importlib
import sys
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


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
from usda_report_pipeline import (  # noqa: E402
    TEMPLATE_SHELLS,
    branded_fact_sheet_html,
    branded_report_html,
    comparison_frame,
    generated_report,
    metrics_for,
)


st.set_page_config(
    page_title="Fryar Monthly Report Studio",
    page_icon="📰",
    layout="wide",
)


def _safe_name(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")


def _markdown_report(case, audience: str, release_status: str) -> str:
    """Build a plain-text editorial draft that travels with the HTML files."""

    frame = comparison_frame(case)
    current_label = case.current_label
    previous_label = case.previous_label
    rows = [
        "| Measure | Prior release | Current release | Change | Units |",
        "|---|---:|---:|---:|---|",
    ]
    for _, row in frame.iterrows():
        prior = row[previous_label]
        current = row[current_label]
        change = row["Change"]
        if case.key == "corn" and row["Measure"] == "USDA farm price":
            prior_text = f"${prior:.2f}"
            current_text = f"${current:.2f}"
            change_text = f"${change:+.2f}"
        elif row["Measure"] == "Yield":
            prior_text = f"{prior:,.1f}"
            current_text = f"{current:,.1f}"
            change_text = f"{change:+,.1f}"
        else:
            prior_text = f"{prior:,.0f}"
            current_text = f"{current:,.0f}"
            change_text = f"{change:+,.0f}"
        rows.append(
            f"| {row['Measure']} | {prior_text} | {current_text} | "
            f"{change_text} ({row['Change %']:+.1f}%) | {row['Units']} |"
        )

    source_lines = "\n".join(f"- [{label}]({url})" for label, url in case.sources)
    metric_lines = "\n".join(
        f"- `{key}`: {value}" for key, value in metrics_for(case).items()
    )
    return f"""# Fryar Center Monthly USDA Market Analysis

**Commodity:** {case.commodity}  
**Current release:** {current_label} ({case.current_release_date})  
**Comparison base:** {previous_label} ({case.previous_release_date})  
**Audience:** {audience}  
**Release status:** {release_status}

## Executive interpretation

{generated_report(case)}

## Supply and demand / market detail

{chr(10).join(rows)}

## Formula and metrics audit trail

The report is generated from the validated release snapshot. The blank
extension-style template is retained below so a reviewer can verify that the
sentence structure does not change from month to month:

```text
{TEMPLATE_SHELLS[case.key]}
```

```text
{metric_lines}
```

## Interpretation and publication note

This product translates the release into a decision cue. It is not a price
guarantee, an individualized marketing recommendation, or a substitute for
reviewing basis, production risk, cost of production, contract terms, and
licensed market data. Human review is required before public release.

## Official sources

{source_lines}

Prepared by the Fryar Price Risk Management Center of Excellence,
University of Arkansas System Division of Agriculture. Generated {date.today().isoformat()}.
"""


def _zip_package(files: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


st.title("Fryar Monthly USDA Report Studio")
st.caption(
    "Validated USDA snapshot → fixed analytical sections → human editorial review "
    "→ Fact Sheet + Full Report + archived report package"
)

with st.sidebar:
    st.header("Publication setup")
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
            "The report studio will become available after the parser writes two "
            "monthly snapshots."
        )
        st.stop()

    latest_id = latest.get("snapshot_id") if latest else None
    snapshot_ids = [str(record["snapshot_id"]) for record in records]
    default_id = latest_id if latest_id in snapshot_ids else snapshot_ids[-1]
    selected_id = st.selectbox(
        "Release vintage",
        snapshot_ids,
        index=snapshot_ids.index(default_id),
        format_func=lambda sid: format_snapshot_option(
            next(record for record in records if record["snapshot_id"] == sid),
            latest_id,
        ),
    )
    audience = st.selectbox(
        "Primary audience",
        ["Producers", "Agribusiness and supply chain", "Policy and research audiences"],
    )
    publication_date = st.date_input("Publication date", value=date.today())

selected_record = next(record for record in records if record["snapshot_id"] == selected_id)
case = build_case(commodity, selected_id)

st.info(
    "The studio assembles files in memory for review and download. It never overwrites "
    "the historical release store. The scheduled GitHub Action remains the system of "
    "record for immutable snapshots and generated report bundles."
)

st.subheader("1. Big picture: the monthly publication workflow")
st.markdown(
    "**USDA release** → **validated vintage comparison** → **supply/demand and price interpretation** "
    "→ **producer decision cue** → **Fact Sheet + Full Report** → **review, publish, archive**"
)

status_cols = st.columns(4)
status_cols[0].metric("Selected release", case.current_label)
status_cols[1].metric("Comparison base", case.previous_label)
status_cols[2].metric("Snapshot ID", selected_id)
status_cols[3].metric("Publication state", "Ready for review")

st.divider()
st.subheader("2. Editorial content map")
content_map = pd.DataFrame(
    [
        ["Executive interpretation", "What changed and why it matters", "Producer-facing narrative", "Auto-filled; review tone"],
        ["Supply and demand", "Reported quantities and formula-derived changes", "Balance-sheet table and ratios", "Auto-filled from snapshot"],
        ["Market price response", "Price move and calendar spread context", "Separate market-response section", "Corn seed connected; deferred spread still unavailable"],
        ["Commodity price forecast", "Low / middle / high scenarios", "Range plus uncertainty caveat", "Transparent Corn seed connected"],
        ["Hedging and marketing implications", "Break-even, costs, benchmarks, strategies", "Decision cue and risk trade-off", "Decision Lab formula connected; review assumptions"],
        ["Sources and methods", "Reproducibility and data provenance", "Official links, parser, vintage", "Required before release"],
    ],
    columns=["Report section", "Question answered", "Audience output", "Current status"],
)
st.dataframe(content_map, width="stretch", hide_index=True)

st.divider()
st.subheader("3. Preview the branded publication products")
fact_html = branded_fact_sheet_html(case)
full_html = branded_report_html(case)
fact_tab, report_tab, draft_tab = st.tabs(
    ["Fryar Fact Sheet", "Full Extension Report", "Markdown editorial draft"]
)
with fact_tab:
    components.html(fact_html, height=900, scrolling=True)
with report_tab:
    components.html(full_html, height=1100, scrolling=True)
with draft_tab:
    draft_markdown = _markdown_report(case, audience, "selected validated snapshot")
    st.code(draft_markdown, language="markdown")

st.divider()
st.subheader("4. Human review gate")
st.caption(
    "The checkboxes are a visible editorial gate. They do not change the data; they make "
    "the required review steps explicit before the report is shared publicly."
)
review_cols = st.columns(2)
with review_cols[0]:
    source_review = st.checkbox("Official USDA source and release date checked", value=True)
    vintage_review = st.checkbox("Current month is compared with the prior month", value=True)
    units_review = st.checkbox("Units, signs, and percentage changes checked")
with review_cols[1]:
    interpretation_review = st.checkbox("Interpretation reviewed for producer audience")
    market_data_review = st.checkbox("Market-price / spread inputs reviewed or labeled unavailable")
    disclaimer_review = st.checkbox("Methods, limitations, and disclaimer included", value=True)

review_passed = all(
    [
        source_review,
        vintage_review,
        units_review,
        interpretation_review,
        market_data_review,
        disclaimer_review,
    ]
)
if review_passed:
    st.success("Editorial gate complete: package is ready to download for final approval.")
else:
    st.warning("Editorial gate is not complete. The download remains available as a draft package.")

st.divider()
st.subheader("5. Download the complete monthly report package")
safe_commodity = _safe_name(case.commodity)
safe_release = _safe_name(selected_id)
markdown_bytes = _markdown_report(case, audience, "selected validated snapshot").encode("utf-8")
comparison = comparison_frame(case).copy()
comparison.insert(0, "commodity", case.commodity)
comparison.insert(1, "current_release_date", case.current_release_date)
comparison.insert(2, "previous_release_date", case.previous_release_date)
comparison.insert(3, "publication_date", publication_date.isoformat())

review_text = "\n".join(
    [
        "Fryar Monthly USDA Report Review Gate",
        f"Commodity: {case.commodity}",
        f"Release: {case.current_label} ({case.current_release_date})",
        f"Comparison base: {case.previous_label} ({case.previous_release_date})",
        f"Audience: {audience}",
        f"Publication date: {publication_date.isoformat()}",
        f"Gate complete: {'yes' if review_passed else 'no — draft only'}",
        "",
        "Required review items:",
        f"- Official source/date checked: {'yes' if source_review else 'no'}",
        f"- Monthly vintage comparison checked: {'yes' if vintage_review else 'no'}",
        f"- Units/signs checked: {'yes' if units_review else 'no'}",
        f"- Interpretation checked: {'yes' if interpretation_review else 'no'}",
        f"- Market data labeled/reviewed: {'yes' if market_data_review else 'no'}",
        f"- Disclaimer included: {'yes' if disclaimer_review else 'no'}",
    ]
)

package_files = {
    f"{safe_commodity}_{safe_release}_fact_sheet.html": fact_html.encode("utf-8"),
    f"{safe_commodity}_{safe_release}_full_report.html": full_html.encode("utf-8"),
    f"{safe_commodity}_{safe_release}_editorial_draft.md": markdown_bytes,
    f"{safe_commodity}_{safe_release}_comparison.csv": comparison.to_csv(index=False).encode("utf-8"),
    "review_gate.txt": review_text.encode("utf-8"),
}
package = _zip_package(package_files)
st.write("Package contents:", ", ".join(package_files))
st.download_button(
    "Download monthly report package (.zip)",
    data=package,
    file_name=f"{safe_commodity}_{safe_release}_fryar_report_package.zip",
    mime="application/zip",
    type="primary",
)

st.caption(
    "Next production step: connect the market-price response and forecast outputs to the "
    "full-report sections, then let the scheduled refresh job generate and archive this "
    "same package automatically after each validated USDA release."
)
