from __future__ import annotations

from datetime import date
import importlib
import os
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Streamlit Cloud may rerun this entry point inside a process that still has an
# older ``core`` module cached. Reload before importing the new livestock
# benchmark and LRP scenario helpers so a hot deployment cannot fail halfway.
import core as _core
importlib.reload(_core)

from audience_poll import (
    POLL_ID,
    POLL_PRESETS,
    active_prompt,
    clear_responses,
    init_database,
    make_qr_bytes,
    recent_custom_responses,
    response_counts,
    response_total,
    set_active_prompt,
    submit_response,
)
from core import (
    COMMODITY_DEFAULTS,
    lrp_coverage_grid,
    lrp_break_even_summary,
    lrp_profit_curve,
    lrp_scenario_values,
    livestock_margin_check,
    livestock_benchmark_options,
    simulate_poultry_feed_strategies,
    simulate_strategies,
    strategy_options,
    summarize,
    summarize_poultry,
)
from data_connectors import (
    RMA_LRP_COMMODITY_CODES,
    RMA_LRP_DEFAULT_TYPE_CODES,
    fetch_rma_lrp_quote,
)


st.set_page_config(
    page_title="Fryar Producer Decision Lab",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
    <style>
    .block-container {max-width: 1450px; padding-top: 1.2rem; padding-bottom: 3rem;}
    .hero {
        padding: 1.6rem 1.8rem 1.5rem 1.8rem;
        border-radius: 18px;
        background: linear-gradient(115deg, #102a43 0%, #1f4d5f 58%, #4c956c 100%);
        color: white;
        margin-bottom: 1.2rem;
        box-shadow: 0 8px 24px rgba(16, 42, 67, .16);
    }
    .hero-kicker {font-size: .78rem; letter-spacing: .12em; text-transform: uppercase; opacity: .78;}
    .hero h1 {font-size: 2.25rem; margin: .3rem 0 .55rem 0; color: white;}
    .hero p {font-size: 1.05rem; max-width: 940px; margin-bottom: 0; color: #edf6f9;}
    .section-label {font-size: .78rem; letter-spacing: .11em; text-transform: uppercase; color: #4c956c; font-weight: 700; margin-top: .7rem;}
    .callout {
        border-left: 4px solid #4c956c;
        background: #f1f7f3;
        padding: .85rem 1rem;
        border-radius: 0 10px 10px 0;
        color: #243b53;
        margin: .7rem 0 1rem 0;
    }
    .warning-callout {
        border-left: 4px solid #d97706;
        background: #fff8eb;
        padding: .85rem 1rem;
        border-radius: 0 10px 10px 0;
        color: #6b3f00;
        margin: .7rem 0 1rem 0;
    }
    .margin-cover {
        padding: 1.15rem 1.35rem;
        border: 1px solid #cfe4dc;
        border-left: 7px solid #4c956c;
        border-radius: 10px;
        background: linear-gradient(135deg, #f1f8f4 0%, #f7f9fb 100%);
        margin: .8rem 0 1.1rem 0;
    }
    .margin-cover .eyebrow {color: #2f855a; font-size: .76rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase;}
    .margin-cover h2 {color: #243b53; margin: .2rem 0 .35rem 0;}
    .margin-cover p {color: #52606d; margin: 0; max-width: 920px;}
    div[data-testid="stMetric"] {background: #f8fafc; border: 1px solid #e6edf2; padding: .8rem; border-radius: 12px;}
    div[data-testid="stMetricLabel"] {font-size: .78rem;}
    [data-testid="stSidebar"] {background: #f5f8fa;}
    </style>
    """,
    unsafe_allow_html=True,
)


def money(value: float, decimals: int = 2) -> str:
    if pd.isna(value):
        return "—"
    return f"${value:,.{decimals}f}"


def pct(value: float) -> str:
    if pd.isna(value):
        return "—"
    return f"{value:.0%}"


LIVESTOCK_COST_LABELS = {
    "pasture": "Pasture / forage cost per head",
    "feed": "Feed cost per head",
    "health": "Health / veterinary cost per head",
    "replacements": "Replacement cost per head",
    "machinery": "Machinery / equipment cost per head",
    "labor": "Labor cost per head",
    "land": "Land / ownership cost per head",
    "other": "Other operating cost per head",
}


def _livestock_cost_defaults(commodity: str, defaults: dict[str, object]) -> dict[str, float]:
    """Create editable per-head defaults while keeping the margin layer auditable."""

    total = float(defaults["cost_per_unit"]) * float(defaults["weight_per_head"]) / 100.0
    shares = (
        [0.35, 0.16, 0.08, 0.12, 0.08, 0.06, 0.08, 0.07]
        if commodity == "Fed Cattle"
        else [0.25, 0.32, 0.08, 0.08, 0.07, 0.06, 0.06, 0.08]
    )
    return {
        key: round(total * share, 2)
        for key, share in zip(LIVESTOCK_COST_LABELS, shares)
    }


def _query_value(name: str, default: str = "") -> str:
    """Read a simple Streamlit query parameter across supported versions."""

    value = st.query_params.get(name, default)
    if isinstance(value, list):
        return str(value[0]) if value else default
    return str(value)


def _audience_url_default() -> str:
    return os.getenv(
        "FRYAR_AUDIENCE_URL",
        "http://localhost:8501/?mode=audience&poll=stakeholder-demo",
    )


@st.cache_data(ttl=900, show_spinner=False)
def _cached_rma_lrp_quote(commodity_code: str, type_code: str) -> tuple[pd.DataFrame, str, str, str]:
    """Cache an official RMA quote briefly so widget reruns do not re-query RMA."""

    result = fetch_rma_lrp_quote(commodity_code, type_code)
    if result.data is None or result.data.empty:
        raise RuntimeError("RMA returned an empty LRP quote table.")
    return result.data, result.retrieved_at, result.url, result.message


def _url_with_mode(url: str, mode: str) -> str:
    """Make a pasted deployment/LAN URL point to a specific presentation surface."""

    parts = urlsplit(url.strip() or _audience_url_default())
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["mode"] = mode
    query.setdefault("poll", POLL_ID)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _render_audience_mode() -> None:
    """Render the phone-friendly page opened from the QR code."""

    prompt = active_prompt()
    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">Stakeholder example · live audience pulse</div>
          <h1>Start with your decision</h1>
          <p>Your anonymous response will appear on the presenter’s screen.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f"### {prompt['question']}")
    st.caption("Choose the answer that best matches your operation today.")

    if "audience_session_id" not in st.session_state:
        st.session_state.audience_session_id = uuid.uuid4().hex

    with st.form("audience_response"):
        selected = st.radio("Your answer", prompt["options"], index=0)
        custom_text = ""
        if selected == "Other / write my own":
            custom_text = st.text_input("Please specify", max_chars=160)
        submitted = st.form_submit_button("Submit anonymous response", width="stretch")

    if submitted:
        submit_response(
            st.session_state.audience_session_id,
            selected,
            custom_text,
            prompt["id"],
        )
        st.success("Thank you — your response has been added to the live results.")

    st.caption("You can submit again if your answer changes. No name or email is collected.")


def _render_live_results() -> None:
    """Render the projection/dashboard surface with two-second refresh."""

    st.markdown(
        """
        <div class="hero">
          <div class="hero-kicker">Stakeholder example · presenter screen</div>
          <h1>Live audience pulse</h1>
          <p>Scan the QR code, answer the question, and watch the response pattern update.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    prompt_ids = list(POLL_PRESETS)
    selected = st.selectbox(
        "Prompt for this discussion",
        prompt_ids,
        index=prompt_ids.index(active_prompt()["id"]),
        format_func=lambda key: POLL_PRESETS[key]["label"],
    )
    control_col, qr_col = st.columns([1.25, 1])
    with control_col:
        if st.button("Start selected prompt", type="primary", width="stretch"):
            set_active_prompt(selected, clear_responses=True)
            st.rerun()
        if st.button("Clear responses for current prompt", width="stretch"):
            clear_responses(active_prompt()["id"])
            st.rerun()
        st.info(
            "Recommended sequence: Decision context → Profit question → Cost question → Risk question."
        )
    with qr_col:
        audience_url_input = st.text_input(
            "Deployment or LAN URL used for the QR code", value=_audience_url_default()
        )
        audience_url = _url_with_mode(audience_url_input, "audience")
        try:
            st.image(make_qr_bytes(audience_url), width=190, caption="Scan to respond anonymously")
        except ModuleNotFoundError:
            st.warning("Install the presentation dependencies to generate the QR code: pip install -r requirements.txt")
        st.caption(audience_url)

    @st.fragment(run_every="2s")
    def refresh_results() -> None:
        current = active_prompt()
        counts = response_counts(current["id"])
        total = sum(counts.values())

        st.markdown(f"### {current['question']}")
        metric_col, note_col = st.columns([1, 3])
        metric_col.metric("Responses", total)
        note_col.caption("Results refresh automatically every two seconds. Responses are anonymous.")

        figure = go.Figure(
            go.Bar(
                x=list(counts.values()),
                y=list(counts.keys()),
                orientation="h",
                marker_color="#4c956c",
                text=list(counts.values()),
                textposition="outside",
            )
        )
        figure.update_layout(
            height=max(380, 65 * len(counts)),
            xaxis_title="Number of responses",
            yaxis_title="",
            xaxis=dict(dtick=1, rangemode="tozero"),
            template="plotly_white",
            margin=dict(l=10, r=45, t=20, b=10),
        )
        st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})

        comments = recent_custom_responses(current["id"])
        if comments:
            st.markdown("**Participant notes**")
            for comment in comments:
                st.markdown(f"- {comment}")

    refresh_results()


init_database()
mode = _query_value("mode", "lab").lower()
if mode == "audience":
    _render_audience_mode()
    st.stop()
if mode == "screen":
    _render_live_results()
    st.stop()


st.markdown(
    """
    <div class="hero">
      <div class="hero-kicker">Fryar Center concept prototype · producer-first</div>
      <h1>Fryar Producer Decision Lab</h1>
      <p>Compare how alternative marketing strategies change the distribution of net prices, margins, and downside risk under uncertain prices and production outcomes.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="callout"><strong>Design principle:</strong> this is a transparent scenario-analysis tool, not a guaranteed price forecast or an automatic buy/sell recommendation. The first version is deliberately producer-focused and can later support Extension teaching, agribusiness, and lender views.</div>',
    unsafe_allow_html=True,
)


with st.sidebar:
    st.markdown("### Live audience pulse")
    audience_url_input = st.text_input(
        "Public audience URL",
        value=_audience_url_default(),
        help="Use the deployed or LAN-accessible URL, not localhost, when participants are using their phones.",
    )
    audience_url = _url_with_mode(audience_url_input, "audience")
    try:
        st.image(make_qr_bytes(audience_url), caption="Scan to answer", width="stretch")
    except ModuleNotFoundError:
        st.caption("QR preview requires: pip install -r requirements.txt")
    screen_url = _url_with_mode(audience_url_input, "screen")
    st.markdown(f"[Open presenter screen]({screen_url})")
    current_prompt = active_prompt()
    st.caption(f"Current prompt: {current_prompt['label']} · {response_total(current_prompt['id'])} responses")
    st.divider()

    st.markdown("### Decision setup")
    view = st.radio(
        "Decision view",
        ["Producer", "Extension demo"],
        help="The current draft prioritizes the producer workflow. Extension demo mode adds teaching-oriented language below.",
    )
    commodity = st.selectbox("Commodity", list(COMMODITY_DEFAULTS.keys()))
    defaults = COMMODITY_DEFAULTS[commodity]
    kind = defaults["kind"]

    st.markdown("#### Farm or operation")
    livestock_costs: dict[str, float] = {}
    livestock_history: dict[str, float] = {}
    grazing_acres = 0.0
    production_rate = 100.0
    other_revenue_per_head = 0.0
    if kind == "crop":
        acres = st.number_input(
            "Planted acres",
            min_value=1.0,
            max_value=100000.0,
            value=float(defaults["acres"]),
            step=10.0,
            key=f"acres_{commodity}",
        )
        yield_per_acre = st.number_input(
            f"Expected yield ({defaults['quantity_unit']}/acre)",
            min_value=1.0,
            max_value=2000.0,
            value=float(defaults["yield_per_acre"]),
            step=1.0,
            key=f"yield_{commodity}",
        )
        cost_per_acre = st.number_input(
            "Production cost ($/acre)",
            min_value=0.0,
            max_value=5000.0,
            value=float(defaults["cost_per_acre"]),
            step=25.0,
            key=f"cost_{commodity}",
        )
    elif kind == "poultry":
        st.markdown("#### Poultry feed exposure")
        poultry_birds = st.number_input(
            "Birds marketed",
            min_value=1.0,
            max_value=10000000.0,
            value=float(defaults["birds"]),
            step=100.0,
            key=f"birds_{commodity}",
        )
        poultry_sale_weight = st.number_input(
            "Sale weight (lb/bird)",
            min_value=0.1,
            max_value=20.0,
            value=float(defaults["sale_weight_lb"]),
            step=0.1,
            key=f"sale_weight_{commodity}",
        )
        poultry_feed_conversion = st.number_input(
            "Feed conversion ratio (lb feed/lb live weight)",
            min_value=0.5,
            max_value=5.0,
            value=float(defaults["feed_conversion"]),
            step=0.01,
            key=f"fcr_{commodity}",
        )
        poultry_corn_share = st.slider(
            "Corn share of ration",
            0.0,
            0.99,
            float(defaults["corn_share"]),
            0.01,
            key=f"corn_share_{commodity}",
        )
        poultry_soymeal_share = st.slider(
            "Soybean-meal share of ration",
            0.0,
            1.0 - poultry_corn_share,
            min(float(defaults["soymeal_share"]), 1.0 - poultry_corn_share),
            0.01,
            key=f"soymeal_share_{commodity}",
        )
        poultry_other_feed_share = 1.0 - poultry_corn_share - poultry_soymeal_share
        st.caption(f"Other feed ingredients: {poultry_other_feed_share:.0%} of ration")
    else:
        st.markdown("#### Livestock margin check")
        head = st.number_input(
            "Livestock units / head",
            min_value=1.0,
            max_value=100000.0,
            value=float(defaults["head"]),
            step=10.0,
            key=f"head_{commodity}",
        )
        grazing_acres = st.number_input(
            "Grazing / production acres",
            min_value=0.0,
            max_value=100000.0,
            value=float(defaults.get("grazing_acres", 0.0)),
            step=10.0,
            key=f"grazing_acres_{commodity}",
        )
        production_rate = st.number_input(
            "Sale / weaning rate (%)",
            min_value=1.0,
            max_value=100.0,
            value=float(defaults.get("production_rate", 100.0)),
            step=1.0,
            key=f"production_rate_{commodity}",
            help="The share of the livestock units expected to produce the modeled sale weight.",
        )
        weight_per_head = st.number_input(
            "Expected sale weight (lb/head)",
            min_value=50.0,
            max_value=2500.0,
            value=float(defaults["weight_per_head"]),
            step=10.0,
            key=f"weight_{commodity}",
        )
        other_revenue_per_head = st.number_input(
            "Cull / other revenue ($/head)",
            min_value=0.0,
            max_value=10000.0,
            value=float(defaults.get("other_revenue_per_head", 0.0)),
            step=5.0,
            key=f"other_revenue_{commodity}",
            help="Other revenue is credited against the sale-price break-even calculation.",
        )
        with st.expander("Annual cost breakdown per head", expanded=True):
            st.caption("These categories drive total cost, margin, and break-even price.")
            cost_defaults = _livestock_cost_defaults(commodity, defaults)
            for cost_key, cost_label in LIVESTOCK_COST_LABELS.items():
                livestock_costs[cost_key] = st.number_input(
                    cost_label,
                    min_value=0.0,
                    max_value=100000.0,
                    value=float(cost_defaults[cost_key]),
                    step=5.0,
                    key=f"livestock_cost_{commodity}_{cost_key}",
                )
            livestock_history = {
                "previous": st.number_input(
                    "Previous year total cost / head (optional)",
                    min_value=0.0,
                    max_value=100000.0,
                    value=0.0,
                    step=10.0,
                    key=f"livestock_history_previous_{commodity}",
                ),
                "three_year": st.number_input(
                    "3-year average total cost / head (optional)",
                    min_value=0.0,
                    max_value=100000.0,
                    value=0.0,
                    step=10.0,
                    key=f"livestock_history_three_year_{commodity}",
                ),
                "five_year": st.number_input(
                    "5-year average total cost / head (optional)",
                    min_value=0.0,
                    max_value=100000.0,
                    value=0.0,
                    step=10.0,
                    key=f"livestock_history_five_year_{commodity}",
                ),
            }
        total_cost_per_head = sum(livestock_costs.values())
        sold_cwt_per_head = weight_per_head * production_rate / 10000.0
        cost_per_unit = total_cost_per_head / sold_cwt_per_head if sold_cwt_per_head else 0.0
        st.caption(
            f"Total cost: ${total_cost_per_head:,.2f}/head · "
            f"${cost_per_unit:,.2f}/cwt of expected sale output"
        )

    st.markdown("#### Market and timing assumptions")
    if kind == "poultry":
        poultry_corn_price = st.number_input(
            "Corn reference price ($/bu)",
            min_value=0.01,
            max_value=30.0,
            value=float(defaults["corn_price"]),
            step=0.05,
            key=f"corn_price_{commodity}",
        )
        poultry_soymeal_price = st.number_input(
            "Soybean-meal reference price ($/ton)",
            min_value=1.0,
            max_value=1000.0,
            value=float(defaults["soymeal_price"]),
            step=5.0,
            key=f"soymeal_price_{commodity}",
        )
        poultry_other_feed_price = st.number_input(
            "Other feed cost ($/lb)",
            min_value=0.0,
            max_value=2.0,
            value=float(defaults["other_feed_price"]),
            step=0.01,
            key=f"other_feed_price_{commodity}",
        )
        poultry_other_cost_per_bird = st.number_input(
            "Non-feed cost ($/bird)",
            min_value=0.0,
            max_value=20.0,
            value=float(defaults["other_cost_per_bird"]),
            step=0.10,
            key=f"other_cost_{commodity}",
        )
        poultry_feed_cost_budget = st.number_input(
            "Feed-cost budget ($/bird)",
            min_value=0.0,
            max_value=20.0,
            value=float(defaults["feed_cost_budget"]),
            step=0.05,
            key=f"feed_budget_{commodity}",
        )
        poultry_target_margin = st.number_input(
            "Target margin ($/bird)",
            min_value=-10.0,
            max_value=20.0,
            value=float(defaults["target_margin"]),
            step=0.05,
            key=f"target_margin_{commodity}",
        )
    if kind == "poultry":
        base_price = st.number_input(
            "Broiler output price ($/lb)",
            min_value=0.01,
            max_value=10.0,
            value=float(defaults["base_price"]),
            step=0.01,
            key=f"price_{commodity}",
        )
        basis = 0.0
        storage = 0.0
    else:
        base_price = st.number_input(
            f"Current / entry price ({defaults['unit']})",
            min_value=0.01,
            max_value=1000.0,
            value=float(defaults["base_price"]),
            step=0.05,
            key=f"price_{commodity}",
        )
        basis = st.number_input(
            f"Local basis ({defaults['unit']})",
            min_value=-50.0,
            max_value=50.0,
            value=float(defaults["basis"]),
            step=0.05,
            key=f"basis_{commodity}",
        )
        storage = st.number_input(
            f"Storage / handling cost ({defaults['unit']})",
            min_value=0.0,
            max_value=50.0,
            value=float(defaults["storage"]),
            step=0.05,
            key=f"storage_{commodity}",
        )
    horizon_months = st.slider(
        "Feed-cost horizon (months)" if kind == "poultry" else "Marketing horizon (months)",
        1,
        18,
        6,
    )
    annual_vol = st.slider(
        "Broiler output-price volatility" if kind == "poultry" else "Illustrative annualized price volatility",
        min_value=0.05,
        max_value=0.60,
        value=float(defaults["annual_vol"]),
        step=0.01,
        help="Placeholder for a future market-implied or historical volatility input.",
    )
    if kind == "poultry":
        yield_cv = 0.0
    else:
        yield_cv = st.slider(
            "Production / quantity risk",
            min_value=0.0,
            max_value=0.30,
            value=float(defaults["yield_cv"]),
            step=0.01,
            help="For crops this approximates yield variation; for livestock it approximates sale-weight variation.",
        )

    rma_quote_df = None
    rma_quote_meta = None
    rma_default_coverage_level = 0.95
    rma_default_endorsement_weeks = 26
    if kind == "livestock":
        st.markdown("#### Official RMA LRP quote")
        rma_commodity_code = RMA_LRP_COMMODITY_CODES.get(commodity, "")
        rma_default_type_code = RMA_LRP_DEFAULT_TYPE_CODES.get(
            rma_commodity_code, ""
        )
        rma_type_code = st.text_input(
            "RMA type code",
            value=rma_default_type_code,
            help=(
                "RMA type code for the selected livestock commodity. The default "
                "matches the current Fed Cattle or Hogs prototype mapping."
            ),
            key=f"rma_type_{commodity}",
        ).strip()
        if st.button(
            "Load latest official RMA quote",
            key=f"load_rma_{commodity}",
            width="stretch",
        ):
            try:
                with st.spinner("Requesting the latest RMA LRP quote..."):
                    quote_df, retrieved_at, quote_url, quote_message = _cached_rma_lrp_quote(
                        rma_commodity_code, rma_type_code
                    )
                st.session_state[f"rma_quote_{commodity}"] = {
                    "records": quote_df.to_dict("records"),
                    "retrieved_at": retrieved_at,
                    "url": quote_url,
                    "message": quote_message,
                    "commodity_code": rma_commodity_code,
                    "type_code": rma_type_code,
                }
                st.session_state.pop(f"rma_error_{commodity}", None)
            except Exception as exc:  # keep the manual fallback usable offline
                st.session_state[f"rma_error_{commodity}"] = str(exc)

        rma_state = st.session_state.get(f"rma_quote_{commodity}")
        if rma_state and rma_state.get("type_code") == rma_type_code:
            rma_quote_df = pd.DataFrame(rma_state["records"])
            rma_quote_meta = rma_state
            if not rma_quote_df.empty:
                def _rma_offer_label(index: int) -> str:
                    row = rma_quote_df.iloc[int(index)]
                    end_date = pd.to_datetime(row.get("End Date"), errors="coerce")
                    end_text = (
                        end_date.strftime("%b %d, %Y")
                        if pd.notna(end_date)
                        else "end date n/a"
                    )
                    return (
                        f"{int(row['Endorsement Length'])} wk · end {end_text} · "
                        f"{float(row['Coverage Level']):.1%} · "
                        f"coverage ${float(row['Coverage Price']):.2f} · "
                        f"premium ${float(row['Producer Premium Per CWT']):.2f}/cwt"
                    )

                default_rma_offer_index = 0
                for candidate_index, candidate_row in rma_quote_df.iterrows():
                    if abs(float(candidate_row["Coverage Level"]) - 0.95) < 1e-9:
                        default_rma_offer_index = int(candidate_index)
                        break
                rma_offer_index = st.selectbox(
                    "Select an RMA offer",
                    options=list(range(len(rma_quote_df))),
                    index=default_rma_offer_index,
                    format_func=_rma_offer_label,
                    key=f"rma_offer_{commodity}",
                    help=(
                        "The table is returned by the official RMA LRP report. "
                        "Select the endorsement length and coverage level that fit "
                        "the marketing decision."
                    ),
                )
                rma_selected = rma_quote_df.iloc[int(rma_offer_index)]
                rma_default_coverage_level = float(rma_selected.get("Coverage Level", 0.95))
                rma_default_endorsement_weeks = int(rma_selected.get("Endorsement Length", 26))
                rma_offer_key = (
                    f"{rma_state['retrieved_at']}|{rma_state['type_code']}|"
                    f"{rma_selected.get('End Date')}|"
                    f"{rma_selected.get('Coverage Level')}"
                )
                st.session_state[f"lrp_level_{commodity}"] = rma_default_coverage_level
                if st.session_state.get(f"rma_applied_{commodity}") != rma_offer_key:
                    st.session_state[f"strike_{commodity}"] = float(
                        rma_selected["Coverage Price"]
                    )
                    st.session_state[f"premium_{commodity}"] = float(
                        rma_selected["Producer Premium Per CWT"]
                    )
                    st.session_state[f"rma_applied_{commodity}"] = rma_offer_key
                st.caption(
                    f"{rma_state['message']} Values below are prefilled from RMA; "
                    "you can still edit them for a what-if scenario."
                )
        elif st.session_state.get(f"rma_error_{commodity}"):
            st.warning(
                "The official RMA quote could not be loaded. The manual inputs "
                "remain available. "
                f"Details: {st.session_state[f'rma_error_{commodity}']}"
            )
        else:
            st.caption(
                "Click the button to load current RMA coverage prices and producer "
                "premiums. Manual assumptions remain available if the public RMA "
                "service is temporarily unavailable."
            )

    st.markdown("#### Strategy assumptions")
    if kind == "livestock":
        st.caption(
            "Choose how many animals to protect, how much price coverage to buy, and "
            "how long the LRP endorsement should run. The strategy selector below also "
            "includes a put-option scenario."
        )
        lrp_covered_head = st.number_input(
            "LRP covered head",
            min_value=0.0,
            max_value=float(head),
            value=float(round(head * 0.50)),
            step=1.0,
            key=f"lrp_head_{commodity}",
            help="The covered head is converted into the covered share used in the LRP scenario.",
        )
        hedge_ratio = lrp_covered_head / head if head else 0.0
        lrp_coverage_level = st.slider(
            "LRP coverage level",
            0.70,
            1.00,
            float(rma_default_coverage_level),
            0.01,
            key=f"lrp_level_{commodity}",
            help="When a live RMA quote is loaded, the selected offer supplies the coverage price and premium.",
        )
        endorsement_options = [13, 17, 21, 26, 30, 34, 39, 43, 47, 52]
        lrp_endorsement_weeks = st.selectbox(
            "LRP endorsement length (weeks)",
            endorsement_options,
            index=(
                endorsement_options.index(rma_default_endorsement_weeks)
                if rma_default_endorsement_weeks in endorsement_options
                else 3
            ),
            key=f"lrp_weeks_{commodity}",
        )
        st.caption(
            f"Scenario coverage: {lrp_covered_head:,.0f} of {head:,.0f} head "
            f"({hedge_ratio:.0%}) · {lrp_coverage_level:.0%} level · "
            f"{lrp_endorsement_weeks} weeks"
        )
    else:
        hedge_ratio = st.slider("Planned hedge share", 0.0, 1.0, 0.50, 0.05)
    if kind == "poultry":
        target_price = defaults["target_price"]
        strike = 0.0
        premium = 0.0
    else:
        target_price = st.number_input(
            f"Target net price ({defaults['unit']})",
            min_value=0.01,
            max_value=1000.0,
            value=float(defaults["target_price"]),
            step=0.05,
            key=f"target_{commodity}",
        )
        protection_label = (
            "LRP coverage price / put strike"
            if kind == "livestock"
            else "Put option strike / protection level"
        )
        default_protection_price = (
            float(base_price * lrp_coverage_level)
            if kind == "livestock" and not rma_quote_meta
            else float(defaults["strike"])
        )
        if kind == "livestock" and not rma_quote_meta:
            previous_level = st.session_state.get(f"lrp_prev_level_{commodity}")
            if previous_level != lrp_coverage_level:
                st.session_state[f"strike_{commodity}"] = default_protection_price
                st.session_state[f"lrp_prev_level_{commodity}"] = lrp_coverage_level
        strike = st.number_input(
            f"{protection_label} ({defaults['unit']})",
            min_value=0.01,
            max_value=1000.0,
            value=default_protection_price,
            step=0.05,
            key=f"strike_{commodity}",
            help=(
                "With no live RMA quote, the starting coverage price is entry price × selected coverage level; edit it for a what-if scenario."
                if kind == "livestock"
                else None
            ),
        )
        premium_label = (
            "LRP premium / put option cost"
            if kind == "livestock"
            else "Put option premium"
        )
        premium = st.number_input(
            f"{premium_label} ({defaults['unit']})",
            min_value=0.0,
            max_value=100.0,
            value=float(defaults["premium"]),
            step=0.05,
            key=f"premium_{commodity}",
            help=(
                "Enter the cost of the selected protection per covered unit. "
                "For LRP, the value is prefilled from the official RMA quote when available; "
                "you can edit it for a scenario."
                if kind == "livestock"
                else None
            ),
        )

    strategy_choices = strategy_options(kind)
    if kind == "poultry":
        default_strategies = [
            "Unhedged feed cost",
            "Staged feed purchase (50%)",
            "Balanced feed hedge",
        ]
    else:
        default_strategies = ["Unhedged / wait", "Futures hedge", "Put option"]
        if kind == "livestock":
            default_strategies.append("LRP")
    strategies = st.multiselect(
        "Strategies to compare",
        strategy_choices,
        default=default_strategies,
    )
    if not strategies:
        strategies = ["Unhedged feed cost" if kind == "poultry" else "Unhedged / wait"]

if kind == "livestock":
    cover_logo_col, cover_text_col = st.columns([1.2, 4.8])
    with cover_logo_col:
        st.image("Fryar-Center-logo.png", width=190)
    with cover_text_col:
        st.markdown(
            """
            <div class="margin-cover">
              <div class="eyebrow">Livestock margin &amp; price-risk decision support</div>
              <h2>Livestock Producer Margin Check</h2>
              <p>Start with exposed pounds, gross revenue, total cost, margin, and break-even price. Then compare the operation with an Arkansas Extension or USDA benchmark and test LRP and put-option protection.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )


if kind == "poultry":
    poultry_params = {
        "kind": kind,
        "birds": poultry_birds,
        "sale_weight_lb": poultry_sale_weight,
        "feed_conversion": poultry_feed_conversion,
        "corn_share": poultry_corn_share,
        "soymeal_share": poultry_soymeal_share,
        "other_feed_share": poultry_other_feed_share,
        "corn_price": poultry_corn_price,
        "soymeal_price": poultry_soymeal_price,
        "other_feed_price": poultry_other_feed_price,
        "output_price": base_price,
        "other_cost_per_bird": poultry_other_cost_per_bird,
        "feed_cost_budget": poultry_feed_cost_budget,
        "target_margin": poultry_target_margin,
        "horizon_months": horizon_months,
        "hedge_ratio": hedge_ratio,
        "corn_vol": defaults["corn_vol"],
        "soymeal_vol": defaults["soymeal_vol"],
        "other_feed_vol": defaults["other_feed_vol"],
        "output_vol": annual_vol,
    }
    poultry_simulation, poultry_meta = simulate_poultry_feed_strategies(
        poultry_params, strategies
    )
    poultry_summary = summarize_poultry(poultry_simulation, poultry_params)
    poultry_display = poultry_summary.copy()
    for column in [
        "Expected feed cost / bird",
        "P10 margin / bird",
        "P50 margin / bird",
        "P90 margin / bird",
        "Expected margin / bird",
    ]:
        poultry_display[column] = poultry_display[column].map(lambda x: money(float(x)))
    for column in ["Target margin probability", "Feed cost over budget"]:
        poultry_display[column] = poultry_display[column].map(lambda x: pct(float(x)))

    st.markdown(
        f'<div class="section-label">{view} view · Poultry feed-cost exposure</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Exposure: {poultry_birds:,.0f} birds × {poultry_sale_weight:.1f} lb/bird · "
        f"Feed conversion: {poultry_feed_conversion:.2f} · Horizon: {horizon_months} months"
    )
    best_poultry = poultry_summary.loc[
        poultry_summary["Expected margin / bird"].idxmax()
    ]
    safest_poultry = poultry_summary.loc[
        poultry_summary["Feed cost over budget"].idxmin()
    ]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "Highest expected margin",
        best_poultry["Strategy"],
        money(float(best_poultry["Expected margin / bird"])),
    )
    col2.metric(
        "Lowest feed-budget risk",
        safest_poultry["Strategy"],
        pct(float(safest_poultry["Feed cost over budget"])),
    )
    col3.metric("Expected unhedged feed cost", money(poultry_meta["feed_cost"]), "per bird")
    col4.metric("Target margin", money(poultry_target_margin), "per bird")

    st.markdown(
        '<div class="callout"><strong>Feed-input logic:</strong> corn and soybean meal are treated as input-price exposures. The model passes their simulated prices through the ration and feed-conversion ratio into feed cost and poultry margin; it does not assume that a direct poultry futures contract exists.</div>',
        unsafe_allow_html=True,
    )
    poultry_tab1, poultry_tab2, poultry_tab3 = st.tabs(
        ["Feed-cost comparison", "Margin distribution", "Assumptions"]
    )
    with poultry_tab1:
        st.dataframe(poultry_display, width="stretch", hide_index=True)
        st.caption(
            "The feed-cost budget and target margin are user-defined thresholds. Hedging can reduce input-price variation while leaving output-price, production, and basis risks.")
    with poultry_tab2:
        fig = go.Figure()
        for strategy in strategies:
            group = poultry_simulation[poultry_simulation["Strategy"] == strategy]
            fig.add_trace(
                go.Histogram(
                    x=group["Margin"],
                    name=strategy,
                    histnorm="probability density",
                    opacity=0.52,
                    nbinsx=42,
                )
            )
        fig.update_layout(
            title="Distribution of poultry margin per bird",
            xaxis_title="Margin per bird ($)",
            yaxis_title="Density",
            barmode="overlay",
            height=470,
            template="plotly_white",
            margin=dict(l=10, r=10, t=55, b=10),
        )
        st.plotly_chart(fig, width="stretch")
    with poultry_tab3:
        st.markdown(
            f"""
            **Ration bridge**

            - Corn share: **{poultry_corn_share:.0%}**
            - Soybean-meal share: **{poultry_soymeal_share:.0%}**
            - Other feed ingredients: **{poultry_other_feed_share:.0%}**
            - Feed consumed: **{poultry_sale_weight * poultry_feed_conversion:.2f} lb/bird**
            - Non-feed cost: **{money(poultry_other_cost_per_bird)} per bird**

            This is an illustrative extension view. A production version should use an approved poultry ration, feed mill or procurement data, and a documented broiler output-price source.
            """
        )
    st.stop()


params = {
    "kind": kind,
    "acres": locals().get("acres"),
    "yield_per_acre": locals().get("yield_per_acre"),
    "cost_per_acre": locals().get("cost_per_acre"),
    "head": locals().get("head"),
    "grazing_acres": locals().get("grazing_acres", 0.0),
    "production_rate": locals().get("production_rate", 100.0),
    "weight_per_head": locals().get("weight_per_head"),
    "cost_per_unit": locals().get("cost_per_unit"),
    "livestock_costs": livestock_costs if kind == "livestock" else {},
    "livestock_history": livestock_history if kind == "livestock" else {},
    "other_revenue_per_head": other_revenue_per_head if kind == "livestock" else 0.0,
    "base_price": base_price,
    "basis": basis,
    "storage": storage,
    "horizon_months": horizon_months,
    "annual_vol": annual_vol,
    "yield_cv": yield_cv,
    "hedge_ratio": hedge_ratio,
    "target_price": target_price,
    "strike": strike,
    "premium": premium,
    "lrp_coverage_share": hedge_ratio if kind == "livestock" else 0.0,
    "lrp_coverage_price": strike if kind == "livestock" else 0.0,
    "lrp_premium": premium if kind == "livestock" else 0.0,
    "lrp_covered_head": lrp_covered_head if kind == "livestock" else 0.0,
    "lrp_coverage_level": lrp_coverage_level if kind == "livestock" else 0.0,
    "lrp_endorsement_weeks": lrp_endorsement_weeks if kind == "livestock" else 0,
}


simulation, simulation_meta = simulate_strategies(params, strategies)
summary = summarize(simulation, params)
summary_display = summary.copy()
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
    "Expected loss when loss",
    "CVaR10 margin",
]:
    # Keep the UI compatible with a previously cached/older core.py during
    # deployment.  The current core returns every metric below, but a partial
    # upload should not turn a missing optional column into a KeyError.
    if column in summary_display.columns:
        summary_display[column] = summary_display[column].map(lambda x: money(float(x)))
for column in [
    "Target price probability",
    "Loss probability",
    "Positive margin probability",
    "Probability beats unhedged",
]:
    if column in summary_display.columns:
        summary_display[column] = summary_display[column].map(lambda x: pct(float(x)))


quantity_text = (
    f"{acres:,.0f} acres × {yield_per_acre:,.0f} {defaults['quantity_unit']}/acre"
    if kind == "crop"
    else f"{head:,.0f} head × {weight_per_head:,.0f} lb/head"
)
st.markdown(f'<div class="section-label">{view} view · {commodity}</div>', unsafe_allow_html=True)
st.caption(
    f"Exposure: {quantity_text} · Horizon: {horizon_months} months · Target net price: {money(target_price)} {defaults['unit'].replace('$/', '')}"
)

best_row = summary.loc[summary["Expected margin"].idxmax()]
lowest_downside = summary.loc[summary["P10 margin"].idxmax()]
lowest_loss = summary.loc[summary["Loss probability"].idxmin()]
col1, col2, col3, col4 = st.columns(4)
col1.metric("Highest expected margin", best_row["Strategy"], money(float(best_row["Expected margin"])))
col2.metric("Strongest P10 margin", lowest_downside["Strategy"], money(float(lowest_downside["P10 margin"])))
col3.metric("Lowest loss probability", lowest_loss["Strategy"], pct(float(lowest_loss["Loss probability"])))
col4.metric("Scenario count", f"{len(simulation):,}", "illustrative draws")

st.info(
    "Risk reading: P10/P50/P90 margin show the lower-tail, typical, and upper-tail "
    "profit outcomes. Target price probability measures how often the simulated net "
    "price reaches the user-defined target; loss probability measures how often margin "
    "is negative. CVaR10 is the average margin in the worst 10% of simulations. "
    "These are model-implied results, not guarantees."
)

if view == "Extension demo":
    st.markdown(
        '<div class="callout"><strong>Extension conversation prompt:</strong> Which risk matters most for this operation—low prices, low yields, basis, storage cost, or cash-flow pressure? The table and charts below are designed to support that conversation rather than replace producer judgment.</div>',
        unsafe_allow_html=True,
    )


if kind == "livestock":
    tab_labels = [
        "Margin check",
        "LRP & put options",
        "Strategy comparison",
        "Assumptions",
        "Sources and roadmap",
    ]
    tabs = st.tabs(tab_labels)
    margin_tab, lrp_tab, tab1, tab3, tab4 = tabs
else:
    tab_labels = [
        "Strategy comparison",
        "Assumptions",
        "Sources and roadmap",
    ]
    tabs = st.tabs(tab_labels)
    tab1, tab3, tab4 = tabs


if kind == "livestock":
    with margin_tab:
        st.markdown("### Operation margin check")
        st.caption(
            "The first step is an operation-level check: expected pounds sold, gross revenue, "
            "total cost, margin, and the sale price needed to cover cost. The calculation uses "
            "the same cost-per-head logic throughout the benchmark and protection screens."
        )
        margin = livestock_margin_check(params)
        margin_cols = st.columns(4)
        margin_cols[0].metric(
            "Pounds sold / exposed head",
            f"{margin['pounds_per_head']:,.0f} lb",
        )
        margin_cols[1].metric(
            "Gross revenue / head",
            money(margin["gross_revenue_per_head"]),
        )
        margin_cols[2].metric(
            "Total cost / head",
            money(margin["total_cost_per_head"]),
        )
        margin_cols[3].metric(
            "Margin / head",
            money(margin["margin_per_head"]),
            "positive margin" if margin["margin_per_head"] >= 0 else "below zero",
            delta_color="normal" if margin["margin_per_head"] >= 0 else "inverse",
        )

        margin_cols2 = st.columns(4)
        margin_cols2[0].metric(
            "Break-even sale price",
            f"{money(margin['break_even_price_per_cwt'])}/cwt",
        )
        margin_cols2[1].metric(
            "Break-even sale price",
            f"{money(margin['break_even_price_per_lb'])}/lb",
        )
        margin_cols2[2].metric(
            "Estimated annual margin",
            money(margin["annual_margin"]),
        )
        margin_cols2[3].metric(
            "Acres / head",
            f"{margin['acres_per_head']:.1f}" if margin["acres_per_head"] is not None else "—",
        )

        st.markdown("#### Revenue and cost bridge")
        bridge = pd.DataFrame(
            {
                "Measure": [
                    "Sale revenue / head",
                    "Cull / other revenue / head",
                    "Gross revenue / head",
                    "Total cost / head",
                    "Margin / head",
                ],
                "Value": [
                    money(margin["sale_revenue_per_head"]),
                    money(margin["other_revenue_per_head"]),
                    money(margin["gross_revenue_per_head"]),
                    money(margin["total_cost_per_head"]),
                    money(margin["margin_per_head"]),
                ],
            }
        )
        st.dataframe(bridge, width="stretch", hide_index=True)

        st.markdown("#### Benchmark comparison")
        benchmark_options = livestock_benchmark_options(commodity)
        benchmark_names = [item["name"] for item in benchmark_options]
        benchmark_key = f"livestock_benchmark_{commodity}"
        selected_benchmark_name = st.selectbox(
            "Benchmark reference",
            benchmark_names,
            key=benchmark_key,
            help="Use an Arkansas Extension, USDA, or approved representative-farm benchmark with matching enterprise and units.",
        )
        selected_benchmark = next(
            item for item in benchmark_options if item["name"] == selected_benchmark_name
        )
        benchmark_default = selected_benchmark.get("break_even_price")
        benchmark_be_price = st.number_input(
            "Benchmark break-even sale price ($/cwt)",
            min_value=0.01,
            max_value=1000.0,
            value=float(benchmark_default or margin["break_even_price_per_cwt"]),
            step=0.25,
            key=f"benchmark_be_{commodity}_{selected_benchmark['key']}",
            help="Editable so an approved Arkansas or USDA source-year value can be inserted without changing the formula layer.",
        )
        benchmark_gap = margin["break_even_price_per_cwt"] - benchmark_be_price
        benchmark_cols = st.columns(3)
        benchmark_cols[0].metric(
            "Your break-even",
            f"{money(margin['break_even_price_per_cwt'])}/cwt",
        )
        benchmark_cols[1].metric(
            "Selected benchmark",
            f"{money(benchmark_be_price)}/cwt",
        )
        benchmark_cols[2].metric(
            "Gap vs benchmark",
            f"{money(benchmark_gap)}/cwt",
            "higher cost" if benchmark_gap > 0 else "lower cost",
            delta_color="inverse" if benchmark_gap > 0 else "normal",
        )
        st.caption(
            f"{selected_benchmark['scope']}. {selected_benchmark['note']}"
            + (
                f" [Source]({selected_benchmark['source']})"
                if selected_benchmark.get("source")
                else ""
            )
        )

        cost_rows = [
            [label, money(params["livestock_costs"].get(key, 0.0))]
            for key, label in LIVESTOCK_COST_LABELS.items()
        ]
        st.markdown("#### Cost breakdown")
        st.dataframe(
            pd.DataFrame(cost_rows, columns=["Cost category", "Your operation / head"]),
            width="stretch",
            hide_index=True,
        )
        history_rows = []
        for label, key in [
            ("Previous year", "previous"),
            ("3-year average", "three_year"),
            ("5-year average", "five_year"),
        ]:
            if params["livestock_history"].get(key, 0.0) > 0:
                history_value = params["livestock_history"][key]
                history_rows.append(
                    [label, money(history_value), money(margin["total_cost_per_head"] - history_value)]
                )
        if history_rows:
            st.markdown("#### Your history")
            st.dataframe(
                pd.DataFrame(
                    history_rows,
                    columns=["Reference", "Historical cost / head", "Current minus reference"],
                ),
                width="stretch",
                hide_index=True,
            )

if kind == "livestock":
    with lrp_tab:
        st.markdown("### LRP and put-option decision")
        st.caption(
            "Compare the modeled operation with no protection, an LRP policy, and a put option. "
            "LRP indemnity is applied only to the covered share and is based on the modeled ending value; "
            "the strategy comparison also shows the put-option scenario."
        )
        if rma_quote_meta:
            st.markdown(
                f"**Quote source:** [USDA RMA official LRP report]({rma_quote_meta['url']}) "
                f" · {rma_quote_meta['message']}"
            )
        else:
            st.caption(
                "No live RMA quote is loaded for this session; the protection price "
                "and premium are manual scenario inputs."
            )

        lrp_summary = lrp_break_even_summary(params)
        benchmark_gap = lrp_summary["operating_break_even_ending_value"] - benchmark_be_price
        benchmark_cols = st.columns(3)
        benchmark_cols[0].metric(
            "Your operating BE",
            f"{money(lrp_summary['operating_break_even_ending_value'])}/cwt",
            "market value before LRP",
        )
        benchmark_cols[1].metric("Selected benchmark BE", f"{money(benchmark_be_price)}/cwt")
        benchmark_cols[2].metric(
            "BE gap vs benchmark",
            f"{money(benchmark_gap)}/cwt",
            "higher cost" if benchmark_gap > 0 else "lower cost",
            delta_color="inverse" if benchmark_gap > 0 else "normal",
        )

        reference_value = st.slider(
            "Check a possible LRP ending value ($/cwt)",
            min_value=max(0.01, min(base_price, strike) * 0.50),
            max_value=max(base_price, strike) * 1.50,
            value=float(base_price),
            step=0.25,
            key=f"lrp_reference_value_{commodity}",
        )
        scenario = lrp_scenario_values(params, reference_value)

        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
        metric_col1.metric(
            "LRP coverage price",
            f"{money(lrp_summary['coverage_price'])}/cwt",
            f"{lrp_summary['coverage_share']:.0%} covered",
        )
        metric_col2.metric(
            "LRP-adjusted BE",
            (
                "Protected below floor"
                if lrp_summary["lrp_adjusted_break_even_ending_value"] is None
                else f"{money(lrp_summary['lrp_adjusted_break_even_ending_value'])}/cwt"
            ),
            f"{lrp_endorsement_weeks} weeks",
        )
        metric_col3.metric(
            "LRP covered head",
            f"{lrp_summary['covered_head']:,.0f}",
            f"{lrp_summary['coverage_level']:.0%} level",
        )
        metric_col4.metric(
            "LRP premium",
            money(scenario["total_premium"]),
            f"{money(scenario['premium_per_operation_cwt'])}/cwt",
        )
        st.metric("Modeled LRP profit at selected ending value", money(scenario["lrp_total_profit"]))

        st.markdown("#### Choose how much to cover")
        coverage_grid = lrp_coverage_grid(params, reference_value).copy()
        for column in [
            "Producer premium",
            "Indemnity at selected value",
            "Net price at selected value",
            "Profit / cwt",
        ]:
            coverage_grid[column] = coverage_grid[column].map(lambda value: money(float(value)))
        coverage_grid["Covered head"] = coverage_grid["Covered head"].map(
            lambda value: f"{value:,.0f}"
        )
        st.dataframe(coverage_grid, width="stretch", hide_index=True)
        st.caption(
            "This table holds the selected coverage price, premium, ending value, and endorsement length constant, "
            "then shows how the number of insured head changes the premium, indemnity, and modeled profit."
        )

        compare_col, explanation_col = st.columns([1.65, 1])
        with compare_col:
            curve = lrp_profit_curve(params)
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=curve["Ending value"],
                    y=curve["no_lrp_profit_per_cwt"],
                    mode="lines",
                    name="No LRP",
                    line=dict(color="#52606d", width=3),
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=curve["Ending value"],
                    y=curve["lrp_profit_per_cwt"],
                    mode="lines",
                    name="With LRP",
                    line=dict(color="#1f7a5c", width=4),
                )
            )
            fig.add_vline(
                x=strike,
                line_dash="dash",
                line_color="#d97706",
                annotation_text="LRP coverage price",
            )
            fig.add_vline(
                x=lrp_summary["operating_break_even_ending_value"],
                line_dash="dot",
                line_color="#d64545",
                annotation_text="Operating BE",
            )
            fig.add_hline(y=0, line_color="#d64545", line_width=1)
            fig.add_vline(
                x=reference_value,
                line_dash="dot",
                line_color="#1f4d5f",
                annotation_text="Selected scenario",
            )
            fig.update_layout(
                title="Modeled profit with and without LRP",
                xaxis_title="LRP ending value / market price ($/cwt)",
                yaxis_title="Profit per cwt ($/cwt)",
                height=510,
                template="plotly_white",
                hovermode="x unified",
                margin=dict(l=10, r=10, t=55, b=10),
            )
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

        with explanation_col:
            st.markdown("#### Selected scenario")
            st.metric("No-LRP profit", money(scenario["no_lrp_total_profit"]))
            st.metric("LRP indemnity", money(scenario["total_indemnity"]))
            st.metric("LRP profit", money(scenario["lrp_total_profit"]))
            st.metric(
                "LRP profit difference",
                money(scenario["lrp_total_profit"] - scenario["no_lrp_total_profit"]),
                "relative to no LRP",
            )

        st.markdown("#### What the LRP module is showing")
        st.dataframe(
            pd.DataFrame(
                {
                    "Measure": [
                        "Operating break-even cash price",
                        "Break-even market ending value before LRP",
                        "Selected benchmark break-even",
                        "LRP-adjusted break-even market value",
                        "LRP coverage price",
                        "Covered share",
                        "Covered head",
                        "Coverage level",
                        "Endorsement length",
                        "Producer premium per covered cwt",
                        "Modeled full-coverage net price after premium",
                        "Modeled full-coverage profit per cwt",
                    ],
                    "Value": [
                        f"{money(lrp_summary['operating_break_even_cash_price'])}/cwt",
                        f"{money(lrp_summary['operating_break_even_ending_value'])}/cwt",
                        f"{money(benchmark_be_price)}/cwt",
                        (
                            "Protected below coverage price"
                            if lrp_summary["lrp_adjusted_break_even_ending_value"] is None
                            else f"{money(lrp_summary['lrp_adjusted_break_even_ending_value'])}/cwt"
                        ),
                        f"{money(lrp_summary['coverage_price'])}/cwt",
                        f"{lrp_summary['coverage_share']:.0%}",
                        f"{lrp_summary['covered_head']:,.0f} head",
                        f"{lrp_summary['coverage_level']:.0%}",
                        f"{lrp_endorsement_weeks} weeks",
                        f"{money(lrp_summary['premium_per_covered_cwt'])}/cwt",
                        f"{money(lrp_summary['modeled_full_coverage_net_price'])}/cwt",
                        f"{money(lrp_summary['modeled_full_coverage_profit_per_cwt'])}/cwt",
                    ],
                }
            ),
            width="stretch",
            hide_index=True,
        )
        st.markdown(
            '<div class="warning-callout"><strong>Interpretation:</strong> this is a transparent teaching model. LRP protects the modeled price-risk channel only. It does not guarantee total profit and does not remove production, weight, basis, forage, feed-cost, or cash-flow risk.</div>',
            unsafe_allow_html=True,
        )

with tab1:
    st.markdown("### What changes across strategies?")
    st.dataframe(
        summary_display,
        width="stretch",
        hide_index=True,
        column_config={
            "Target price probability": st.column_config.TextColumn("Target probability"),
            "Loss probability": st.column_config.TextColumn("Loss probability"),
        },
    )
    st.caption(
        "P10 is a lower-tail outcome: approximately one simulated outcome out of ten is below this value. It is not a guaranteed floor."
    )

    chart_col, table_col = st.columns([1.7, 1])
    with chart_col:
        fig = go.Figure()
        for strategy in strategies:
            group = simulation[simulation["Strategy"] == strategy]
            fig.add_trace(
                go.Histogram(
                    x=group["Margin"],
                    name=strategy,
                    histnorm="probability density",
                    opacity=0.52,
                    nbinsx=42,
                )
            )
        fig.update_layout(
            title="Distribution of margin outcomes",
            xaxis_title="Margin per acre" if kind == "crop" else "Margin per cwt",
            yaxis_title="Density",
            barmode="overlay",
            height=470,
            legend_title="Strategy",
            template="plotly_white",
            margin=dict(l=10, r=10, t=55, b=10),
        )
        st.plotly_chart(fig, width="stretch")
    with table_col:
        st.markdown("#### Decision reading")
        st.write(
            f"The current inputs imply a simulated average terminal price of {money(simulation_meta['terminal_price'])} {defaults['unit'].replace('$/', '')}. The tool compares how each strategy changes the distribution around that market outcome."
        )
        st.write(
            f"The target net price is user-defined at {money(target_price)}. A higher target probability may come with a lower expected margin because protection has a cost."
        )
        st.markdown(
            '<div class="warning-callout"><strong>Interpretation:</strong> A strategy with the highest expected margin is not automatically the best choice. Producers may rationally accept a lower mean outcome to reduce the probability of a severe downside result.</div>',
            unsafe_allow_html=True,
        )

with tab3:
    st.markdown("### What the current draft assumes")
    premium_source = (
        "Official USDA RMA LRP quote; editable for a what-if scenario."
        if kind == "livestock" and rma_quote_meta
        else "Manual assumption; click Load latest official RMA quote for current RMA values."
        if kind == "livestock"
        else "Illustrative premium; not used for crop live-market execution."
    )
    protection_source = (
        "Official USDA RMA coverage price from the selected offer; editable for a what-if scenario."
        if kind == "livestock" and rma_quote_meta
        else "Manual protection level or coverage price."
    )
    assumption_rows = [
        ["Market price", f"{money(base_price)} {defaults['unit'].replace('$/', '')}", "Illustrative entry or reference price; replace with an approved live data source."],
        ["Local basis", f"{money(basis)} {defaults['unit'].replace('$/', '')}", "User-entered local basis for the delivery or sale window."],
        ["Storage / handling", f"{money(storage)} {defaults['unit'].replace('$/', '')}", "Deducted from the net price in every strategy."],
        ["Price uncertainty", f"{annual_vol:.0%} annualized volatility", "Placeholder for historical or market-implied volatility after validation."],
        ["Production uncertainty", f"{yield_cv:.0%}", "Yield variation for crops or sale-weight variation for livestock."],
        ["Protection level", f"{money(strike)} {defaults['unit'].replace('$/', '')}", protection_source],
        ["Premium", f"{money(premium)} {defaults['unit'].replace('$/', '')}", premium_source],
    ]
    st.table({"Input": [row[0] for row in assumption_rows], "Current value": [row[1] for row in assumption_rows], "Interpretation": [row[2] for row in assumption_rows]})
    st.markdown(
        """
        **Planned model upgrades:**

        - replace illustrative volatility with documented historical and market-implied inputs;
        - add contract size, margin, transaction cost, and basis-risk treatment;
        - compare crop insurance or LRP with comparable private-market protection;
        - backtest target probabilities and downside labels;
        - add saved scenarios and an Extension teaching mode.
        """
    )

with tab4:
    st.markdown("### Relationship to the Fryar tool ecosystem")
    st.write(
        "This prototype is designed as a marketing-risk layer that could complement, rather than duplicate, existing Fryar and Arkansas decision-support products. The public ecosystem includes strategy and farm-management tools such as Basis Trader, HogGraph, and the Potash Rate Calculators. The newer Arkansas Crop Decision Support Tool integrates crop insurance, farm-program choices, production costs, storage, and grain marketing, and presents downside outcomes in plain-language 1-in-5, 1-in-10, and 1-in-20-year scenarios."
    )
    st.markdown(
        """
        **Where this draft adds a distinct emphasis:**

        1. compare an unhedged position, futures hedge, staged hedge, put, or LRP-style floor in one view;
        2. make contract horizon, hedge share, target net price, and protection cost explicit;
        3. show the tradeoff between expected margin, downside outcomes, and upside retained;
        4. provide a reusable engine that can later connect to monthly USDA/WASDE updates;
        5. make the same scenario engine usable by an Extension educator in a producer conversation.
        """
    )
    st.markdown("#### Public references")
    st.markdown(
        "- [USDA RMA LRP Coverage, Prices, Rates, and Actual Ending Values](https://webapp.rma.usda.gov/apps/RIRS/LRPCoveragePricesRatesActualEndingValues.aspx)\n"
        "- [Fryar Risk Center tools](https://fryar-risk-center.uada.edu/tools/)\n"
        "- [Arkansas Crop Decision Support Tool announcement](https://www.uaex.uada.edu/media-resources/news/2026/april/04-29-2026-ark-farm-decision-tool.aspx)\n"
        "- [Fryar Risk Center podcast and resources](https://fryar-risk-center.uada.edu/podcast/)"
    )
    st.markdown(
        '<div class="warning-callout"><strong>Prototype status:</strong> this is an interview and design draft, not an official Fryar Center product. Values are illustrative and should not be used for actual marketing, insurance, or trading decisions.</div>',
        unsafe_allow_html=True,
    )


st.divider()
st.caption(
    f"Draft generated for interview preparation · {date.today().isoformat()} · Next step: replace illustrative assumptions with approved data sources and validate the economic specification with Fryar faculty and Extension users."
)
