"""Fryar USDA release and price-outlook monitor.

This page is intentionally transparent and manual-input first. It demonstrates
the report logic without pretending that Bloomberg, CME, or Barchart data are
available or licensed in the local prototype.
"""

from math import exp, sqrt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(
    page_title="Fryar USDA Market Outlook",
    page_icon="📊",
    layout="wide",
)


def price_range(center: float, annual_iv_pct: float, horizon_days: int) -> tuple[float, float, float]:
    """Return illustrative low/middle/high prices from annualized IV."""

    sigma = max(0.0, annual_iv_pct) / 100.0 * sqrt(max(horizon_days, 1) / 365.0)
    low = center * exp(-1.2816 * sigma)
    high = center * exp(1.2816 * sigma)
    return low, center, high


st.title("Fryar USDA Release & Price Outlook Monitor")
st.caption(
    "Tool 2 of the interview toolbox · transparent release-to-price workflow · "
    "illustrative inputs until Center data access and licensing are confirmed"
)


with st.sidebar:
    st.header("Release snapshot")
    commodity = st.selectbox("Commodity", ["Corn", "Soybeans", "Wheat", "Rice", "Live cattle", "Hogs"])
    report = st.selectbox("USDA report", ["WASDE", "Grain Stocks", "Cattle on Feed"])
    previous_stocks = st.number_input("Previous ending stocks", min_value=0.0, value=1820.0, step=25.0)
    new_stocks = st.number_input("New USDA ending stocks", min_value=0.0, value=1950.0, step=25.0)
    consensus_stocks = st.number_input("Pre-release expectation", min_value=0.0, value=1880.0, step=25.0)
    use = st.number_input("Annual use / denominator", min_value=1.0, value=14500.0, step=100.0)
    futures_price = st.number_input("Current futures price", min_value=0.0, value=4.35, step=0.05)
    implied_vol = st.number_input("Annualized implied volatility (%)", min_value=0.0, value=24.0, step=1.0)
    horizon_days = st.slider("Forecast horizon (days)", min_value=15, max_value=365, value=90, step=15)
    sensitivity = st.slider(
        "Illustrative stocks-surprise price sensitivity",
        min_value=0.0,
        max_value=3.0,
        value=1.0,
        step=0.1,
        help="A transparent teaching parameter, not an estimated structural coefficient.",
    )

    st.divider()
    st.subheader("Event-window check")
    pre_release = st.number_input("Pre-release futures", min_value=0.0, value=float(futures_price), step=0.05)
    post_release = st.number_input("Post-release futures", min_value=0.0, value=float(futures_price), step=0.05)
    pre_spread = st.number_input("Pre-release calendar spread", value=0.00, step=0.01, format="%.2f")
    post_spread = st.number_input("Post-release calendar spread", value=0.00, step=0.01, format="%.2f")


previous_stu = previous_stocks / use * 100.0
new_stu = new_stocks / use * 100.0
surprise = new_stocks - consensus_stocks
surprise_pct_use = surprise / use * 100.0

# Higher ending stocks are treated as a bearish directional adjustment. The
# sensitivity is deliberately visible so a future version can replace it with
# a calibrated/event-study estimate without changing the interface.
directional_adjustment = max(0.25, 1.0 - sensitivity * surprise_pct_use / 100.0)
adjusted_mid = futures_price * directional_adjustment
low, middle, high = price_range(adjusted_mid, implied_vol, horizon_days)

direction = "bearish" if surprise > 0 else "bullish" if surprise < 0 else "neutral"
futures_move_pct = (post_release / pre_release - 1.0) * 100.0 if pre_release else 0.0
spread_move = post_spread - pre_spread

metric_cols = st.columns(5)
metric_cols[0].metric("Stocks-to-use", f"{new_stu:.1f}%", f"{new_stu - previous_stu:+.1f} pp")
metric_cols[1].metric("Surprise vs expectation", f"{surprise:+,.0f}", f"{surprise_pct_use:+.2f}% of use")
metric_cols[2].metric("Directional read", direction.title())
metric_cols[3].metric("Scenario middle", f"{middle:.2f}")
metric_cols[4].metric("Low–high range", f"{low:.2f} – {high:.2f}")


left, right = st.columns([1.2, 1.0])
with left:
    st.subheader("Scenario range")
    scenario_df = pd.DataFrame(
        {
            "Scenario": ["Low", "Middle", "High"],
            "Price": [low, middle, high],
            "Construction": [
                "Adjusted middle × lower IV tail",
                "Futures price × transparent surprise adjustment",
                "Adjusted middle × upper IV tail",
            ],
        }
    )
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=scenario_df["Scenario"],
            y=scenario_df["Price"],
            marker_color=["#B45309", "#0F766E", "#1D4ED8"],
            text=[f"{value:.2f}" for value in scenario_df["Price"]],
            textposition="outside",
        )
    )
    fig.update_layout(height=360, yaxis_title="Price", margin=dict(l=20, r=20, t=20, b=20), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(scenario_df, use_container_width=True, hide_index=True)

with right:
    st.subheader("Release-day market response")
    response_df = pd.DataFrame(
        {
            "Measure": ["Futures move", "Calendar spread move", "Stocks-to-use change"],
            "Value": [f"{futures_move_pct:+.2f}%", f"{spread_move:+.2f}", f"{new_stu - previous_stu:+.2f} pp"],
            "Interpretation": [
                "Observed event-window move from entered prices",
                "Observed change in entered calendar spread",
                "New USDA balance-sheet tightness signal",
            ],
        }
    )
    st.dataframe(response_df, use_container_width=True, hide_index=True)

    st.subheader("One-paragraph interpretation")
    if direction == "bearish":
        read = "The new estimate is above the pre-release expectation, which is a bearish supply/demand surprise under this teaching model."
    elif direction == "bullish":
        read = "The new estimate is below the pre-release expectation, which is a bullish supply/demand surprise under this teaching model."
    else:
        read = "The new estimate matches the pre-release expectation, so the balance-sheet surprise is neutral under this teaching model."
    st.info(
        f"For {commodity} {report}, {read} The implied-volatility range is centered at "
        f"{middle:.2f} and spans {low:.2f}–{high:.2f} over {horizon_days} days. "
        "A production version would replace the transparent sensitivity with a documented, backtested model and would pass this scenario snapshot to the hedging tool."
    )


st.divider()
st.subheader("Data and publication gate")
st.warning(
    "This page is deliberately manual-input first. Before public deployment, the Center should confirm USDA vintage handling, Bloomberg consensus access/display rights, futures/options/IV licensing, and who owns the scheduled refresh and human sign-off."
)

download_df = scenario_df.assign(
    commodity=commodity,
    report=report,
    previous_stocks=previous_stocks,
    new_stocks=new_stocks,
    consensus_stocks=consensus_stocks,
    use=use,
    implied_vol_pct=implied_vol,
    horizon_days=horizon_days,
)
st.download_button(
    "Download scenario snapshot",
    data=download_df.to_csv(index=False).encode("utf-8"),
    file_name="fryar_usda_outlook_snapshot.csv",
    mime="text/csv",
)
