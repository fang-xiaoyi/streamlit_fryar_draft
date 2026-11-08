"""Fryar decision bridge: connect a market snapshot to an operation."""

import pandas as pd
import plotly.express as px
import streamlit as st


st.set_page_config(
    page_title="Fryar Decision Bridge",
    page_icon="🌉",
    layout="wide",
)


st.title("Fryar Decision Bridge & Feedback Lab")
st.caption(
    "Tool 3 of the interview toolbox · translate a USDA/market scenario into "
    "role-specific margins, then collect lightweight anonymous feedback"
)

linked_forecast = st.session_state.get("fryar_price_scenario_snapshot")
has_linked_forecast = (
    isinstance(linked_forecast, dict)
    and all(key in linked_forecast for key in ("low", "middle", "high"))
)

with st.sidebar:
    st.header("User pathway")
    role = st.selectbox(
        "I am viewing this as a…",
        ["Producer", "Elevator / merchandiser", "Feed buyer / poultry user", "Extension educator"],
    )
    quantity = st.number_input("Quantity to price", min_value=1.0, value=10000.0, step=500.0)
    unit_label = st.text_input("Quantity unit", value="bushels")
    cost_per_unit = st.number_input(
        "Production or procurement cost per unit", min_value=0.0, value=3.85, step=0.05
    )
    basis = st.number_input("Local basis / location adjustment", value=-0.15, step=0.01, format="%.2f")
    current_futures = st.number_input("Hedge futures price", min_value=0.0, value=4.35, step=0.05)
    hedge_share = st.slider("Futures hedge share (%)", min_value=0, max_value=100, value=50, step=10) / 100.0
    put_strike = st.number_input("Illustrative put/floor strike", min_value=0.0, value=4.25, step=0.05)
    put_premium = st.number_input("Illustrative put premium", min_value=0.0, value=0.18, step=0.01)

    st.divider()
    st.subheader("Tool 2 forecast scenarios")
    use_linked_forecast = False
    if has_linked_forecast:
        use_linked_forecast = st.checkbox(
            "Use linked forecast scenarios",
            value=True,
            key="decision_bridge_use_linked_forecast",
            help="Use the commodity, release, and low/middle/high values from Commodity Price Forecast.",
        )

    if use_linked_forecast:
        low = float(linked_forecast["low"])
        middle = float(linked_forecast["middle"])
        high = float(linked_forecast["high"])
        st.caption(
            f"Linked: {linked_forecast.get('commodity_label', 'Commodity')} · "
            f"{linked_forecast.get('release_label', 'selected release')} · "
            f"snapshot {linked_forecast.get('snapshot_id', '—')}"
        )
        st.write(f"Low ${low:.2f} · Middle ${middle:.2f} · High ${high:.2f}")
    else:
        st.caption("Manual fallback. Open Commodity Price Forecast first to link its validated range.")
        low = st.number_input(
            "Low scenario price", min_value=0.0, value=3.65, step=0.05, key="decision_bridge_manual_low"
        )
        middle = st.number_input(
            "Middle scenario price", min_value=0.0, value=4.15, step=0.05, key="decision_bridge_manual_middle"
        )
        high = st.number_input(
            "High scenario price", min_value=0.0, value=4.75, step=0.05, key="decision_bridge_manual_high"
        )


scenario_prices = {"Low": low, "Middle": middle, "High": high}


def effective_price(spot_scenario: float, strategy: str) -> float:
    """Calculate a simplified seller-side effective price."""

    cash_price = spot_scenario + basis
    if strategy == "Cash sale now":
        # Cash-sale baseline: lock the current futures reference plus basis.
        # This page intentionally keeps the simplified Decision Bridge model
        # without a separate storage-cost input.
        return current_futures + basis
    if strategy == "Unhedged / wait":
        return cash_price
    if strategy == "Futures hedge":
        return hedge_share * (current_futures + basis) + (1.0 - hedge_share) * cash_price
    if strategy == "Put / floor":
        floor_payoff = max(put_strike - spot_scenario, 0.0) - put_premium
        protected = spot_scenario + basis + floor_payoff
        return hedge_share * protected + (1.0 - hedge_share) * cash_price
    if strategy == "Staged 50/50":
        staged_share = 0.5
        return staged_share * (current_futures + basis) + (1.0 - staged_share) * cash_price
    raise ValueError(f"Unknown strategy: {strategy}")


strategies = ["Cash sale now", "Unhedged / wait", "Futures hedge", "Put / floor", "Staged 50/50"]
rows: list[dict[str, object]] = []
for strategy in strategies:
    for scenario, price in scenario_prices.items():
        effective = effective_price(price, strategy)
        rows.append(
            {
                "Strategy": strategy,
                "Scenario": scenario,
                "Market price": price,
                "Effective price": effective,
                "Margin / unit": effective - cost_per_unit,
                "Total margin": (effective - cost_per_unit) * quantity,
            }
        )

result_df = pd.DataFrame(rows)
expected_weights = {"Low": 0.2, "Middle": 0.6, "High": 0.2}
summary_rows: list[dict[str, object]] = []
for strategy in strategies:
    subset = result_df[result_df["Strategy"] == strategy].copy()
    expected_price = sum(
        float(subset.loc[subset["Scenario"] == scenario, "Effective price"].iloc[0]) * weight
        for scenario, weight in expected_weights.items()
    )
    loss_probability = sum(
        weight
        for scenario, weight in expected_weights.items()
        if float(subset.loc[subset["Scenario"] == scenario, "Margin / unit"].iloc[0]) < 0
    )
    summary_rows.append(
        {
            "Strategy": strategy,
            "Expected effective price": expected_price,
            "Expected margin / unit": expected_price - cost_per_unit,
            "Expected total margin": (expected_price - cost_per_unit) * quantity,
            "Scenario-weighted loss probability": loss_probability,
        }
    )

summary_df = pd.DataFrame(summary_rows)

st.caption(
    "Illustrative scenario weights for this teaching view: Low 20%, Middle 60%, High 20%. "
    "These weights are not market-implied probabilities."
)

st.subheader(f"{role}: what does the market snapshot mean for the operation?")
st.info(
    "This page is the bridge between the USDA outlook and a local decision. "
    "When linked, the page uses the same commodity, release vintage, and low/middle/high range as Commodity Price Forecast. "
    "The hedge entry price and farm assumptions remain operation-specific."
)

metric_cols = st.columns(4)
best_row = summary_df.loc[summary_df["Expected margin / unit"].idxmax()]
metric_cols[0].metric("Best expected margin", f"{best_row['Expected margin / unit']:.2f}", str(best_row["Strategy"]))
metric_cols[1].metric("Best expected total", f"{best_row['Expected total margin']:,.0f}", unit_label)
metric_cols[2].metric("Cost / unit", f"{cost_per_unit:.2f}")
metric_cols[3].metric("Hedge share", f"{hedge_share:.0%}")

left, right = st.columns([1.15, 1.0])
with left:
    chart_df = result_df.copy()
    fig = px.bar(
        chart_df,
        x="Scenario",
        y="Margin / unit",
        color="Strategy",
        barmode="group",
        text_auto=".2f",
        title="Margin by market scenario",
    )
    fig.add_hline(y=0, line_dash="dash", line_color="#B91C1C")
    fig.update_layout(height=420, yaxis_title="Margin per unit", legend_title="Strategy")
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Decision summary")
    display_summary = summary_df.copy()
    display_summary["Expected effective price"] = display_summary["Expected effective price"].map(lambda x: f"{x:.2f}")
    display_summary["Expected margin / unit"] = display_summary["Expected margin / unit"].map(lambda x: f"{x:.2f}")
    display_summary["Expected total margin"] = display_summary["Expected total margin"].map(lambda x: f"{x:,.0f}")
    display_summary["Scenario-weighted loss probability"] = display_summary["Scenario-weighted loss probability"].map(lambda x: f"{x:.0%}")
    st.dataframe(display_summary, use_container_width=True, hide_index=True)

st.subheader("Scenario mechanics")
st.dataframe(
    result_df.style.format(
        {
            "Market price": "{:.2f}",
            "Effective price": "{:.2f}",
            "Margin / unit": "{:.2f}",
            "Total margin": "{:,.0f}",
        }
    ),
    use_container_width=True,
    hide_index=True,
)

st.divider()
st.subheader("Anonymous pre/post-release feedback")
st.write(
    "For a workshop or release-day pilot, ask one question before the report and one after the report. "
    "This prototype keeps the response in the current session; a deployment would use a documented, privacy-reviewed store."
)
with st.form("feedback_form"):
    expected_direction = st.radio(
        "Before seeing the scenarios, what direction did you expect?",
        ["Higher", "About unchanged", "Lower"],
        horizontal=True,
    )
    intended_action = st.selectbox(
        "What would you most likely do next?",
        [
            "Review the decision with an adviser",
            "Price/hedge part of the exposure",
            "Wait and monitor",
            "Change procurement or storage plan",
            "Use this as a teaching case",
        ],
    )
    confidence = st.slider("How confident are you in your interpretation?", min_value=1, max_value=5, value=3)
    submitted = st.form_submit_button("Record anonymous response")

if submitted:
    st.success(
        f"Recorded for this prototype session: expected {expected_direction.lower()}, "
        f"next step '{intended_action}', confidence {confidence}/5."
    )

st.download_button(
    "Download bridge case",
    data=result_df.to_csv(index=False).encode("utf-8"),
    file_name="fryar_decision_bridge_case.csv",
    mime="text/csv",
)

st.caption(
    "Illustrative decision-support only. The calculations simplify contract mechanics, basis, transaction costs, insurance rules, and probability calibration; they are not personalized trading advice."
)
