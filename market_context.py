"""Release-specific market context for the Fryar USDA product family.

USDA normalized snapshots remain the official source for supply and demand.
This module adds an optional, separately governed layer for consensus,
market reaction, conditional price scenarios, and marketing implications.
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from usda_report_pipeline import (
    branded_fact_sheet_html,
    branded_report_html,
    comparison_frame,
    generated_report,
)


MARKET_DATA_DIR = Path(__file__).resolve().parent / "data" / "market"


def load_market_context(commodity: str, snapshot_id: str) -> dict[str, Any]:
    path = MARKET_DATA_DIR / commodity / f"{snapshot_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def context_for(case) -> dict[str, Any]:
    return load_market_context(case.key, str(case.current_release_date))


def _signal(item: str, surprise: float | None) -> str:
    if surprise is None or pd.isna(surprise) or abs(float(surprise)) < 1e-9:
        return "Neutral"
    demand_item = item in {"Total use", "Exports", "Feed/residual use"}
    bullish = float(surprise) > 0 if demand_item else float(surprise) < 0
    return "Bullish" if bullish else "Bearish"


def consensus_surprise_frame(case) -> pd.DataFrame:
    columns = [
        "Item", "Units", "Previous USDA", "Current USDA", "Change",
        "Market consensus", "Surprise", "Read",
    ]
    if case.key != "corn":
        return pd.DataFrame(columns=columns)
    context = context_for(case)
    consensus = context.get("consensus", {})
    previous = case.previous
    current = case.current
    previous_stu = previous["ending_stocks"] / previous["total_use"] * 100.0
    current_stu = current["ending_stocks"] / current["total_use"] * 100.0
    rows = [
        ("Production", "million bu", previous["production"], current["production"], consensus.get("production")),
        ("Beginning stocks", "million bu", previous["beginning_stocks"], current["beginning_stocks"], consensus.get("beginning_stocks")),
        ("Feed/residual use", "million bu", previous["feed_residual"], current["feed_residual"], consensus.get("feed_residual")),
        ("Exports", "million bu", previous["exports"], current["exports"], consensus.get("exports")),
        ("Total use", "million bu", previous["total_use"], current["total_use"], consensus.get("total_use")),
        ("Ending stocks", "million bu", previous["ending_stocks"], current["ending_stocks"], consensus.get("ending_stocks")),
        ("Stocks-to-use", "%", previous_stu, current_stu, consensus.get("stocks_to_use")),
    ]
    result = []
    for item, units, previous_value, current_value, expected in rows:
        surprise = current_value - expected if expected is not None else None
        result.append({
            "Item": item,
            "Units": units,
            "Previous USDA": previous_value,
            "Current USDA": current_value,
            "Change": current_value - previous_value,
            "Market consensus": expected,
            "Surprise": surprise,
            "Read": _signal(item, surprise),
        })
    return pd.DataFrame(result, columns=columns)


def consensus_summary(case) -> dict[str, Any]:
    frame = consensus_surprise_frame(case)
    context = context_for(case)
    if frame.empty or frame["Surprise"].isna().all():
        return {
            "status": "not_loaded",
            "label": "Not loaded",
            "headline": "Pre-release market consensus is not loaded for this release.",
            "source_label": "No consensus source recorded",
        }
    score = 0.0
    for _, row in frame.dropna(subset=["Surprise"]).iterrows():
        weight = 2.0 if row["Item"] in {"Ending stocks", "Stocks-to-use"} else 1.0
        score += weight if row["Read"] == "Bullish" else -weight if row["Read"] == "Bearish" else 0.0
    label = "Bearish" if score <= -1.5 else "Bullish" if score >= 1.5 else "Neutral / mixed"
    source_label = str(context.get("consensus_source_label", "Recorded pre-release consensus"))
    return {
        "status": "loaded",
        "label": label,
        "score": score,
        "headline": f"The release was {label.lower()} relative to the recorded pre-release consensus.",
        "source_label": source_label,
    }


def market_reaction_frame(case) -> pd.DataFrame:
    columns = [
        "Observation", "Date", "Nearby futures", "Deferred futures",
        "Calendar spread", "Implied volatility",
    ]
    observations = context_for(case).get("market_reaction", {}).get("observations", [])
    rows = []
    for observation in observations:
        nearby = observation.get("nearby")
        deferred = observation.get("deferred")
        spread = observation.get("spread")
        if spread is None and nearby is not None and deferred is not None:
            spread = deferred - nearby
        rows.append({
            "Observation": observation.get("label", "Observation"),
            "Date": observation.get("date", ""),
            "Nearby futures": nearby,
            "Deferred futures": deferred,
            "Calendar spread": spread,
            "Implied volatility": observation.get("iv"),
        })
    return pd.DataFrame(rows, columns=columns)


def price_outlook(case) -> dict[str, Any]:
    context = context_for(case)
    config = context.get("price_outlook", {})
    market = context.get("market_reaction", {})
    reference = config.get("reference_price", market.get("reference_price"))
    annualized_iv = config.get("annualized_iv", market.get("annualized_iv"))
    horizon_days = int(config.get("horizon_days", 30))
    if reference is None or annualized_iv is None:
        return {
            "status": "not_loaded",
            "reference_price": reference,
            "annualized_iv": annualized_iv,
            "horizon_days": horizon_days,
            "scenarios": [],
            "method_label": "No approved futures/options inputs recorded.",
        }
    sigma = float(reference) * float(annualized_iv) * math.sqrt(horizon_days / 365.0)
    scenarios = []
    for spec in config.get("scenarios", []):
        center = float(reference) + float(spec.get("price_shift", 0.0))
        half_width = max(sigma * float(spec.get("width_factor", 1.0)), 0.01)
        scenarios.append({
            "Scenario": spec.get("name", "Scenario"),
            "Probability": float(spec.get("probability", 0.0)),
            "Supply-demand read": spec.get("supply_demand_read", "Conditional scenario"),
            "Price low": max(center - half_width, 0.0),
            "Price midpoint": max(center, 0.0),
            "Price high": max(center + half_width, 0.0),
            "Producer implication": spec.get("producer_implication", "Compare with local costs and basis."),
        })
    return {
        "status": "loaded",
        "reference_price": float(reference),
        "annualized_iv": float(annualized_iv),
        "horizon_days": horizon_days,
        "sigma": sigma,
        "method_label": config.get(
            "method_label",
            "Scenario weights with a transparent volatility-based range; not a guaranteed forecast.",
        ),
        "scenarios": scenarios,
    }


def price_outlook_frame(case) -> pd.DataFrame:
    columns = [
        "Scenario", "Probability", "Supply-demand read", "Price low",
        "Price midpoint", "Price high", "Producer implication",
    ]
    return pd.DataFrame(price_outlook(case).get("scenarios", []), columns=columns)


def marketing_implications(case, assumptions: dict[str, float] | None = None) -> dict[str, Any]:
    assumptions = assumptions or {}
    context = context_for(case)
    market = context.get("market_reaction", {})
    observations = market_reaction_frame(case)
    latest = observations.iloc[-1].to_dict() if not observations.empty else {}
    nearby = float(assumptions.get("nearby_futures", latest.get("Nearby futures") or market.get("reference_price") or 0.0))
    deferred = float(assumptions.get("deferred_futures", latest.get("Deferred futures") or nearby))
    basis = float(assumptions.get("basis", market.get("basis", 0.0)))
    break_even = float(assumptions.get("break_even", market.get("break_even", 0.0)))
    put_strike = float(assumptions.get("put_strike", nearby))
    put_premium = float(assumptions.get("put_premium", market.get("put_premium", 0.0)))
    storage_cost = float(assumptions.get("storage_cost", market.get("storage_cost", 0.0)))
    cash_net = nearby + basis
    deferred_net = deferred + basis - storage_cost
    put_floor = put_strike + basis - put_premium
    outlook = price_outlook(case)
    middle = next((row for row in outlook.get("scenarios", []) if row["Scenario"].lower().startswith("middle")), None)
    middle_price = float(middle["Price midpoint"]) if middle else nearby
    staged_net = 0.5 * cash_net + 0.5 * (middle_price + basis)
    strategies = pd.DataFrame([
        {"Strategy": "Lock now", "Illustrative net price": cash_net, "Protection / cost": "Locks futures plus basis", "Tradeoff": "Reduces downside risk; gives up later upside"},
        {"Strategy": "50% staged hedge", "Illustrative net price": staged_net, "Protection / cost": "Half of exposure protected now", "Tradeoff": "Balances immediate protection and future flexibility"},
        {"Strategy": "Put floor", "Illustrative net price": put_floor, "Protection / cost": f"Strike ${put_strike:.2f} less ${put_premium:.2f} premium", "Tradeoff": "Retains upside; premium lowers the floor"},
        {"Strategy": "Store / defer", "Illustrative net price": deferred_net, "Protection / cost": f"Deferred futures less ${storage_cost:.2f} storage", "Tradeoff": "Needs carry and basis improvement to compensate for waiting"},
    ])
    if break_even <= 0:
        break_even_read = "Enter a farm-specific break-even to compare the current net price with cost of production."
    elif cash_net >= break_even:
        break_even_read = f"The illustrative net price of ${cash_net:.2f}/bu is ${cash_net - break_even:.2f} above the ${break_even:.2f}/bu break-even."
    else:
        break_even_read = f"The illustrative net price of ${cash_net:.2f}/bu is ${break_even - cash_net:.2f} below the ${break_even:.2f}/bu break-even."
    carry_after_cost = deferred - nearby - storage_cost
    carry_read = f"Deferred futures provide ${deferred - nearby:.2f}/bu of carry; after storage, the illustrative net carry is ${carry_after_cost:+.2f}/bu."
    return {
        "status": "loaded" if nearby > 0 else "not_loaded",
        "assumptions": {
            "nearby_futures": nearby, "deferred_futures": deferred, "basis": basis,
            "break_even": break_even, "put_strike": put_strike,
            "put_premium": put_premium, "storage_cost": storage_cost,
        },
        "strategies": strategies,
        "break_even_read": break_even_read,
        "carry_read": carry_read,
        "cue": "Use the comparison to choose a risk-management conversation, not to issue a universal trading recommendation.",
    }


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No observations are loaded."
    headers = [str(column) for column in frame.columns]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for _, row in frame.iterrows():
        values = []
        for value in row.tolist():
            if pd.isna(value):
                values.append("")
            elif isinstance(value, float):
                values.append(f"{value:.4f}".rstrip("0").rstrip("."))
            else:
                values.append(str(value).replace("|", "\\|"))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def full_report_markdown(case) -> str:
    consensus = consensus_surprise_frame(case)
    reaction = market_reaction_frame(case)
    outlook = price_outlook(case)
    implications = marketing_implications(case)
    context = context_for(case)
    source_lines = "\n".join(
        f"- [{label}]({url})" if url else f"- {label}" for label, url in case.sources
    )
    return (
        f"# {case.commodity} USDA Market Outlook\n\n"
        f"**Current release:** {case.current_label}  \n**Previous release:** {case.previous_label}  \n"
        f"**Current release date:** {case.current_release_date}  \n**Previous release date:** {case.previous_release_date}\n\n"
        f"## Bottom line\n\n{generated_report(case)}\n\n"
        "## 1. Release context\n\n"
        f"- Report: {case.report}\n- Commodity: {case.commodity}\n"
        f"- Current release: {case.current_label} ({case.current_release_date})\n"
        f"- Previous release: {case.previous_label} ({case.previous_release_date})\n\n"
        "## 2. Supply and demand revision\n\n"
        f"{_markdown_table(comparison_frame(case))}\n\n"
        "## 3. Consensus surprise\n\n"
        f"{_markdown_table(consensus)}\n\n"
        "## 4. Market price response\n\n"
        f"{_markdown_table(reaction)}\n\n"
        "## 5. Price outlook\n\n"
        f"{outlook.get('method_label', 'No approved price-outlook inputs are loaded.')}\n\n"
        f"{_markdown_table(price_outlook_frame(case))}\n\n"
        "## 6. Hedging and marketing implications\n\n"
        f"{implications.get('break_even_read', '')}\n\n{implications.get('carry_read', '')}\n\n"
        f"{_markdown_table(implications['strategies']) if implications['status'] == 'loaded' else 'No validated market context is loaded.'}\n\n"
        f"> {implications.get('cue', '')}\n\n"
        "## 7. Methods, sources, and limitations\n\n"
        f"USDA snapshot note: {case.note}\n\n"
        f"Market-context status: `{context.get('status', 'not_loaded')}`. {context.get('status_note', 'Market context is not loaded for this release.')}\n\n"
        "This is an educational Extension product. Price scenarios are conditional on the recorded information and assumptions; they are not guaranteed forecasts or individualized marketing advice. Confirm data licensing, contract mechanics, basis treatment, transaction costs, and human review before public release.\n\n"
        f"### Official USDA sources\n\n{source_lines}\n"
    )


def _html_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return '<div class="method">No approved observations are loaded for this section.</div>'
    display = frame.copy()
    for column in display.columns:
        if column == "Probability":
            display[column] = display[column].map(lambda v: "—" if pd.isna(v) else f"{float(v):.0%}")
        elif column in {"Price low", "Price midpoint", "Price high", "Nearby futures", "Deferred futures", "Calendar spread", "Illustrative net price"}:
            display[column] = display[column].map(lambda v: "—" if pd.isna(v) else f"${float(v):.2f}")
        elif column == "Implied volatility":
            display[column] = display[column].map(lambda v: "—" if pd.isna(v) else f"{float(v):.1%}")
        elif column in {"Change", "Surprise"}:
            display[column] = display[column].map(lambda v: "—" if pd.isna(v) else f"{float(v):+,.2f}")
        elif column in {"Previous USDA", "Current USDA", "Market consensus"}:
            display[column] = display[column].map(lambda v: "—" if pd.isna(v) else f"{float(v):,.2f}")
    return display.to_html(index=False, classes="comparison", border=0, escape=True)


def _context_html(case) -> str:
    context = context_for(case)
    if not context:
        return '<h2>Market context and decision bridge</h2><div class="method">Pre-release consensus, futures reaction, price scenarios, and marketing assumptions are not loaded for this release.</div>'
    consensus = consensus_summary(case)
    outlook = price_outlook(case)
    implications = marketing_implications(case)
    status_note = html.escape(str(context.get("status_note", "")))
    status_html = f'<div class="method"><strong>Data status.</strong> {status_note}</div>' if status_note else ""
    return (
        '<h2>Consensus surprise</h2>'
        f'<div class="callout"><strong>{html.escape(consensus["label"])}.</strong> {html.escape(consensus["headline"])}<br><span class="small-note">Source: {html.escape(consensus["source_label"])}</span></div>'
        f'{_html_table(consensus_surprise_frame(case))}'
        '<h2>Market price response</h2>'
        f'{_html_table(market_reaction_frame(case))}'
        '<h2>Price outlook</h2>'
        f'<p class="small-note">{html.escape(outlook.get("method_label", ""))}</p>{_html_table(price_outlook_frame(case))}'
        '<h2>Hedging and marketing implications</h2>'
        f'<p>{html.escape(implications.get("break_even_read", ""))}</p><p>{html.escape(implications.get("carry_read", ""))}</p>'
        f'{_html_table(implications["strategies"])}<div class="method">{html.escape(implications.get("cue", ""))}</div>{status_html}'
    )


def enhanced_report_html(case) -> str:
    """Add the market-context layer to the existing branded report template."""

    base = branded_report_html(case)
    css = ".small-note { color:#52606D; font-size:11px; }"
    base = base.replace("</style>", css + "</style>", 1)
    return base.replace("<h2>Official sources</h2>", _context_html(case) + "<h2>Official sources</h2>", 1)


def enhanced_fact_sheet_html(case) -> str:
    """Add a compact market read to the one-page fact-sheet template."""

    base = branded_fact_sheet_html(case)
    context = context_for(case)
    if not context:
        return base
    consensus = consensus_summary(case)
    reaction = market_reaction_frame(case)
    outlook = price_outlook(case)
    middle = next((row for row in outlook.get("scenarios", []) if row["Scenario"].lower().startswith("middle")), None)
    reaction_text = "Not loaded"
    if not reaction.empty:
        reaction_text = f"{reaction.iloc[-1]['Nearby futures'] - reaction.iloc[0]['Nearby futures']:+.2f}/bu through +1 week"
    outlook_text = f"${middle['Price low']:.2f}–${middle['Price high']:.2f}/bu" if middle else "Not loaded"
    context_html = (
        '<h2>Market read</h2><div class="callout">'
        f'<strong>Consensus:</strong> {html.escape(consensus["label"])} · '
        f'<strong>Futures reaction:</strong> {html.escape(reaction_text)} · '
        f'<strong>Middle range:</strong> {html.escape(outlook_text)}'
        '</div>'
    )
    return base.replace('<h2>What it means for a producer</h2>', context_html + '<h2>What it means for a producer</h2>', 1)
