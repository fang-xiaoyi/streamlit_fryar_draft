"""Core simulation logic for the Fryar producer decision-support draft.

This module deliberately uses transparent illustrative assumptions. It does not
fetch live market data or provide a trading recommendation.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


COMMODITY_DEFAULTS: dict[str, dict[str, Any]] = {
    "Corn": {
        "kind": "crop",
        "unit": "$/bu",
        "quantity_unit": "bushels",
        "acres": 100.0,
        "yield_per_acre": 180.0,
        "cost_per_acre": 670.0,
        "base_price": 4.60,
        "basis": -0.25,
        "storage": 0.15,
        "annual_vol": 0.22,
        "yield_cv": 0.12,
        "target_price": 4.75,
        "strike": 4.60,
        "premium": 0.18,
    },
    "Soybeans": {
        "kind": "crop",
        "unit": "$/bu",
        "quantity_unit": "bushels",
        "acres": 100.0,
        "yield_per_acre": 55.0,
        "cost_per_acre": 480.0,
        "base_price": 11.20,
        "basis": -0.35,
        "storage": 0.14,
        "annual_vol": 0.20,
        "yield_cv": 0.13,
        "target_price": 11.35,
        "strike": 11.20,
        "premium": 0.42,
    },
    "Rice": {
        "kind": "crop",
        "unit": "$/cwt",
        "quantity_unit": "hundredweight",
        "acres": 100.0,
        "yield_per_acre": 75.0,
        "cost_per_acre": 850.0,
        "base_price": 15.00,
        "basis": -0.35,
        "storage": 0.20,
        "annual_vol": 0.18,
        "yield_cv": 0.10,
        "target_price": 15.25,
        "strike": 15.00,
        "premium": 0.52,
    },
    "Fed Cattle": {
        "kind": "livestock",
        "unit": "$/cwt",
        "quantity_unit": "cwt",
        "head": 150.0,
        "weight_per_head": 1400.0,
        "cost_per_unit": 180.0,
        "base_price": 190.0,
        "basis": 0.0,
        "storage": 0.0,
        "annual_vol": 0.15,
        "yield_cv": 0.04,
        "target_price": 192.0,
        "strike": 190.0,
        "premium": 3.50,
    },
    "Hogs": {
        "kind": "livestock",
        "unit": "$/cwt",
        "quantity_unit": "cwt",
        "head": 500.0,
        "weight_per_head": 280.0,
        "cost_per_unit": 78.0,
        "base_price": 90.0,
        "basis": 0.0,
        "storage": 0.0,
        "annual_vol": 0.17,
        "yield_cv": 0.05,
        "target_price": 92.0,
        "strike": 90.0,
        "premium": 2.20,
    },
    "Poultry (feed cost)": {
        "kind": "poultry",
        "unit": "$/lb",
        "quantity_unit": "lb",
        "base_price": 1.15,
        "basis": 0.0,
        "storage": 0.0,
        "annual_vol": 0.12,
        "yield_cv": 0.04,
        "target_price": 1.15,
        "strike": 1.15,
        "premium": 0.0,
        "head": 10000.0,
        "weight_per_head": 6.0,
        "cost_per_unit": 50.0,
        "birds": 10000.0,
        "sale_weight_lb": 6.0,
        "feed_conversion": 1.65,
        "corn_share": 0.60,
        "soymeal_share": 0.25,
        "other_feed_share": 0.15,
        "corn_price": 4.60,
        "soymeal_price": 320.0,
        "other_feed_price": 0.20,
        "output_price": 1.15,
        "other_cost_per_bird": 3.00,
        "corn_vol": 0.22,
        "soymeal_vol": 0.20,
        "other_feed_vol": 0.10,
        "output_vol": 0.12,
        "feed_cost_budget": 3.45,
        "target_margin": 2.25,
    },
}


def strategy_options(kind: str) -> list[str]:
    """Return strategies that make sense for a producer-facing draft."""

    if kind == "poultry":
        return [
            "Unhedged feed cost",
            "Staged feed purchase (50%)",
            "Corn hedge",
            "Soybean meal hedge",
            "Balanced feed hedge",
        ]

    options = [
        "Cash sale now",
        "Unhedged / wait",
        "Futures hedge",
        "Staged hedge (50% now)",
    ]
    options.append("Put floor" if kind == "crop" else "LRP floor")
    return options


def _poultry_feed_cost(
    corn_price: np.ndarray | float,
    soymeal_price: np.ndarray | float,
    other_feed_price: np.ndarray | float,
    params: dict[str, Any],
) -> np.ndarray:
    """Convert feed-input prices into feed cost per bird."""

    feed_pounds = params["sale_weight_lb"] * params["feed_conversion"]
    corn_bushels = feed_pounds * params["corn_share"] / 56.0
    soybean_meal_tons = feed_pounds * params["soymeal_share"] / 2000.0
    other_feed_pounds = feed_pounds * params["other_feed_share"]

    return (
        corn_bushels * np.asarray(corn_price, dtype=float)
        + soybean_meal_tons * np.asarray(soymeal_price, dtype=float)
        + other_feed_pounds * np.asarray(other_feed_price, dtype=float)
    )


def simulate_poultry_feed_strategies(
    params: dict[str, Any], strategies: list[str], n: int = 12000, seed: int = 2027
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Simulate poultry margin outcomes from corn and soybean-meal exposure."""

    rng = np.random.default_rng(seed)
    horizon_scale = np.sqrt(params["horizon_months"] / 12.0)
    covariance = np.array(
        [
            [1.0, 0.35, 0.10, -0.10],
            [0.35, 1.0, 0.10, -0.05],
            [0.10, 0.10, 1.0, 0.00],
            [-0.10, -0.05, 0.00, 1.0],
        ]
    )
    z = rng.multivariate_normal([0.0, 0.0, 0.0, 0.0], covariance, n)

    volatilities = np.array(
        [
            params["corn_vol"],
            params["soymeal_vol"],
            params["other_feed_vol"],
            params["output_vol"],
        ]
    ) * horizon_scale
    base_prices = np.array(
        [
            params["corn_price"],
            params["soymeal_price"],
            params["other_feed_price"],
            params["output_price"],
        ]
    )
    terminal_prices = base_prices * np.exp(
        -0.5 * volatilities**2 + z * volatilities
    )
    corn_terminal, soymeal_terminal, other_feed_terminal, output_terminal = terminal_prices.T
    hedge_ratio = params["hedge_ratio"]

    records: list[pd.DataFrame] = []
    for strategy in strategies:
        corn_effective = corn_terminal
        soymeal_effective = soymeal_terminal
        other_feed_effective = other_feed_terminal

        if strategy == "Staged feed purchase (50%)":
            corn_effective = 0.50 * params["corn_price"] + 0.50 * corn_terminal
            soymeal_effective = 0.50 * params["soymeal_price"] + 0.50 * soymeal_terminal
            other_feed_effective = 0.50 * params["other_feed_price"] + 0.50 * other_feed_terminal
        elif strategy == "Corn hedge":
            corn_effective = params["corn_price"] + hedge_ratio * (
                params["corn_price"] - corn_terminal
            )
        elif strategy == "Soybean meal hedge":
            soymeal_effective = params["soymeal_price"] + hedge_ratio * (
                params["soymeal_price"] - soymeal_terminal
            )
        elif strategy == "Balanced feed hedge":
            corn_effective = params["corn_price"] + hedge_ratio * (
                params["corn_price"] - corn_terminal
            )
            soymeal_effective = params["soymeal_price"] + hedge_ratio * (
                params["soymeal_price"] - soymeal_terminal
            )

        feed_cost = _poultry_feed_cost(
            corn_effective, soymeal_effective, other_feed_effective, params
        )
        margin = (
            output_terminal * params["sale_weight_lb"]
            - feed_cost
            - params["other_cost_per_bird"]
        )
        records.append(
            pd.DataFrame(
                {
                    "Strategy": strategy,
                    "Output price": output_terminal,
                    "Feed cost / bird": feed_cost,
                    "Margin": margin,
                    "Total margin": margin * params["birds"],
                }
            )
        )

    return pd.concat(records, ignore_index=True), {
        "output_price": float(np.mean(output_terminal)),
        "feed_cost": float(
            np.mean(
                _poultry_feed_cost(
                    corn_terminal,
                    soymeal_terminal,
                    other_feed_terminal,
                    params,
                )
            )
        ),
    }


def summarize_poultry(
    simulation: pd.DataFrame, params: dict[str, Any]
) -> pd.DataFrame:
    """Summarize poultry feed-cost and margin outcomes."""

    rows: list[dict[str, Any]] = []
    for strategy, group in simulation.groupby("Strategy", sort=False):
        rows.append(
            {
                "Strategy": strategy,
                "Expected feed cost / bird": group["Feed cost / bird"].mean(),
                "P10 margin / bird": group["Margin"].quantile(0.10),
                "P50 margin / bird": group["Margin"].quantile(0.50),
                "P90 margin / bird": group["Margin"].quantile(0.90),
                "Target margin probability": (
                    group["Margin"] >= params["target_margin"]
                ).mean(),
                "Feed cost over budget": (
                    group["Feed cost / bird"] > params["feed_cost_budget"]
                ).mean(),
                "Expected margin / bird": group["Margin"].mean(),
            }
        )
    return pd.DataFrame(rows)


def _draw_price_and_quantity(
    params: dict[str, Any], n: int, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """Draw terminal price and physical quantity with transparent assumptions."""

    rng = np.random.default_rng(seed)
    correlation = -0.15 if params["kind"] == "crop" else 0.0
    covariance = np.array([[1.0, correlation], [correlation, 1.0]])
    price_z, quantity_z = rng.multivariate_normal([0.0, 0.0], covariance, n).T

    horizon_scale = np.sqrt(params["horizon_months"] / 12.0)
    sigma = params["annual_vol"] * horizon_scale
    base_price = params["base_price"]
    terminal_price = base_price * np.exp(-0.5 * sigma**2 + sigma * price_z)
    terminal_price = np.maximum(terminal_price, 0.01)

    quantity_factor = np.clip(
        1.0 + params["yield_cv"] * quantity_z,
        0.45 if params["kind"] == "crop" else 0.85,
        1.65 if params["kind"] == "crop" else 1.15,
    )

    if params["kind"] == "crop":
        quantity = params["acres"] * params["yield_per_acre"] * quantity_factor
    else:
        quantity = (
            params["head"] * params["weight_per_head"] / 100.0 * quantity_factor
        )

    return terminal_price, quantity


def _net_price(
    terminal_price: np.ndarray | float,
    strategy: str,
    params: dict[str, Any],
) -> np.ndarray:
    """Calculate premium- and basis-adjusted net price for a strategy."""

    price = np.asarray(terminal_price, dtype=float)
    basis = params["basis"]
    storage = params["storage"]
    entry_price = params["base_price"]
    hedge_ratio = params["hedge_ratio"]

    if strategy == "Cash sale now":
        return np.full_like(price, entry_price + basis - storage)

    if strategy == "Unhedged / wait":
        return price + basis - storage

    if strategy == "Futures hedge":
        futures_gain = hedge_ratio * (entry_price - price)
        return price + basis + futures_gain - storage

    if strategy == "Staged hedge (50% now)":
        staged_ratio = 0.50 * hedge_ratio
        futures_gain = staged_ratio * (entry_price - price)
        return price + basis + futures_gain - storage

    if strategy in {"Put floor", "LRP floor"}:
        floor_payoff = np.maximum(params["strike"] - price, 0.0)
        protection_cost = hedge_ratio * params["premium"]
        return price + basis + hedge_ratio * floor_payoff - protection_cost - storage

    raise ValueError(f"Unknown strategy: {strategy}")


def simulate_strategies(
    params: dict[str, Any], strategies: list[str], n: int = 12000, seed: int = 2027
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Simulate net price and margin outcomes for each selected strategy."""

    terminal_price, quantity = _draw_price_and_quantity(params, n=n, seed=seed)
    records: list[pd.DataFrame] = []

    for strategy in strategies:
        net_price = _net_price(terminal_price, strategy, params)

        if params["kind"] == "crop":
            realized_yield = quantity / params["acres"]
            margin = net_price * realized_yield - params["cost_per_acre"]
            total_margin = margin * params["acres"]
        else:
            margin = net_price - params["cost_per_unit"]
            total_margin = margin * quantity

        records.append(
            pd.DataFrame(
                {
                    "Strategy": strategy,
                    "Terminal price": terminal_price,
                    "Net price": net_price,
                    "Margin": margin,
                    "Total margin": total_margin,
                }
            )
        )

    return pd.concat(records, ignore_index=True), {"terminal_price": float(np.mean(terminal_price))}


def summarize(
    simulation: pd.DataFrame, params: dict[str, Any]
) -> pd.DataFrame:
    """Summarize the outcomes in producer-friendly language."""

    target = params["target_price"]
    rows: list[dict[str, Any]] = []
    for strategy, group in simulation.groupby("Strategy", sort=False):
        rows.append(
            {
                "Strategy": strategy,
                "Expected net price": group["Net price"].mean(),
                "P10 net price": group["Net price"].quantile(0.10),
                "P50 net price": group["Net price"].quantile(0.50),
                "P90 net price": group["Net price"].quantile(0.90),
                "Target price probability": (group["Net price"] >= target).mean(),
                "Loss probability": (group["Margin"] < 0).mean(),
                "Expected margin": group["Margin"].mean(),
            }
        )

    return pd.DataFrame(rows)


def payoff_curve(
    strategy: str, params: dict[str, Any], n_points: int = 160
) -> pd.DataFrame:
    """Create a transparent terminal-price payoff curve using expected quantity."""

    low = max(0.01, params["base_price"] * 0.50)
    high = params["base_price"] * 1.50
    terminal = np.linspace(low, high, n_points)
    net_price = _net_price(terminal, strategy, params)

    if params["kind"] == "crop":
        margin = net_price * params["yield_per_acre"] - params["cost_per_acre"]
    else:
        margin = net_price - params["cost_per_unit"]

    return pd.DataFrame(
        {
            "Terminal price": terminal,
            "Net price": net_price,
            "Margin": margin,
        }
    )


def lrp_scenario_values(
    params: dict[str, Any], ending_value: float
) -> dict[str, float]:
    """Return a transparent LRP versus no-LRP scenario for livestock.

    The draft treats ``ending_value`` as the price-risk reference used for the
    LRP settlement calculation.  Local basis and handling are applied to the
    producer's cash revenue, while the LRP indemnity and premium are applied
    only to the covered share of the expected quantity.

    This is a teaching model, not an official RMA quote or policy calculator.
    Contract eligibility, endorsement rules, settlement conventions, actual
    sale weight, and basis treatment must be validated before production use.
    """

    if params["kind"] != "livestock":
        raise ValueError("The LRP module is currently available for livestock only.")

    quantity_cwt = params["head"] * params["weight_per_head"] / 100.0
    coverage_share = params["hedge_ratio"]
    coverage_price = params["strike"]
    premium = params["premium"]
    cash_net_price = ending_value + params["basis"] - params["storage"]
    indemnity_per_covered_cwt = max(coverage_price - ending_value, 0.0)
    indemnity_per_operation_cwt = coverage_share * indemnity_per_covered_cwt
    premium_per_operation_cwt = coverage_share * premium

    no_lrp_net_price = cash_net_price
    lrp_net_price = cash_net_price + indemnity_per_operation_cwt - premium_per_operation_cwt
    no_lrp_profit_per_cwt = no_lrp_net_price - params["cost_per_unit"]
    lrp_profit_per_cwt = lrp_net_price - params["cost_per_unit"]

    return {
        "ending_value": float(ending_value),
        "quantity_cwt": float(quantity_cwt),
        "covered_quantity_cwt": float(quantity_cwt * coverage_share),
        "coverage_share": float(coverage_share),
        "coverage_price": float(coverage_price),
        "premium_per_covered_cwt": float(premium),
        "premium_per_operation_cwt": float(premium_per_operation_cwt),
        "total_premium": float(premium_per_operation_cwt * quantity_cwt),
        "indemnity_per_covered_cwt": float(indemnity_per_covered_cwt),
        "indemnity_per_operation_cwt": float(indemnity_per_operation_cwt),
        "total_indemnity": float(indemnity_per_operation_cwt * quantity_cwt),
        "no_lrp_net_price": float(no_lrp_net_price),
        "lrp_net_price": float(lrp_net_price),
        "no_lrp_profit_per_cwt": float(no_lrp_profit_per_cwt),
        "lrp_profit_per_cwt": float(lrp_profit_per_cwt),
        "no_lrp_total_profit": float(no_lrp_profit_per_cwt * quantity_cwt),
        "lrp_total_profit": float(lrp_profit_per_cwt * quantity_cwt),
    }


def lrp_profit_curve(
    params: dict[str, Any], n_points: int = 180
) -> pd.DataFrame:
    """Build a no-LRP versus LRP profit curve for an operation."""

    if params["kind"] != "livestock":
        raise ValueError("The LRP module is currently available for livestock only.")

    low = max(0.01, min(params["base_price"], params["strike"]) * 0.50)
    high = max(params["base_price"], params["strike"]) * 1.50
    ending_values = np.linspace(low, high, n_points)
    rows = [lrp_scenario_values(params, float(value)) for value in ending_values]
    curve = pd.DataFrame(rows)
    return curve.rename(columns={"ending_value": "Ending value"})


def lrp_break_even_summary(params: dict[str, Any]) -> dict[str, float | None]:
    """Summarize operating and modeled LRP break-even information.

    ``operating_break_even_cash_price`` is the local cash price that covers
    the stated production cost.  The LRP-adjusted value is calculated on a
    grid because the indemnity creates a piecewise payoff, especially when
    only part of the operation is covered.
    """

    if params["kind"] != "livestock":
        raise ValueError("The LRP module is currently available for livestock only.")

    operating_be_cash = params["cost_per_unit"]
    operating_be_ending_value = (
        params["cost_per_unit"] - params["basis"] + params["storage"]
    )
    coverage_price = params["strike"]
    premium = params["premium"]
    coverage_share = params["hedge_ratio"]

    modeled_full_coverage_net_price = (
        coverage_price + params["basis"] - params["storage"] - premium
    )
    modeled_full_coverage_profit = (
        modeled_full_coverage_net_price - params["cost_per_unit"]
    )

    curve = lrp_profit_curve(params, n_points=1200)
    no_lrp_crossings = curve.loc[curve["no_lrp_profit_per_cwt"] >= 0, "Ending value"]
    lrp_crossings = curve.loc[curve["lrp_profit_per_cwt"] >= 0, "Ending value"]

    return {
        "operating_break_even_cash_price": float(operating_be_cash),
        "operating_break_even_ending_value": float(operating_be_ending_value),
        "coverage_price": float(coverage_price),
        "premium_per_covered_cwt": float(premium),
        "coverage_share": float(coverage_share),
        "modeled_full_coverage_net_price": float(modeled_full_coverage_net_price),
        "modeled_full_coverage_profit_per_cwt": float(modeled_full_coverage_profit),
        "no_lrp_break_even_ending_value": (
            float(no_lrp_crossings.iloc[0]) if not no_lrp_crossings.empty else None
        ),
        "lrp_break_even_ending_value": (
            float(lrp_crossings.iloc[0]) if not lrp_crossings.empty else None
        ),
    }
