"""USDA release cases and report-generation utilities.

The first two cases are deliberately small, auditable demonstrations:

* Corn: October 2026 WASDE versus September 2026 WASDE.
* Cattle: October 2026 Cattle on Feed versus September 2026 Cattle on Feed.

The values are official USDA snapshots.  The fetch functions below are kept
separate from the Streamlit UI so a scheduled job can later download and parse
the latest USDA files, validate them, and persist a new snapshot.
"""

from __future__ import annotations

import base64
import html
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


FRYAR_CARDINAL = "#9E2B44"
FRYAR_BLUE = "#2EA3F2"
FRYAR_INK = "#202124"
FRYAR_SLATE = "#52606D"
FRYAR_PALE = "#F6F7F8"
FRYAR_LINE = "#D9DEE3"
_PROJECT_LOGO = Path(__file__).resolve().with_name("Fryar-Center-logo.png")
_PARENT_LOGO = Path(__file__).resolve().parents[1] / "Fryar-Center-logo.png"
FRYAR_LOGO_PATH = _PROJECT_LOGO if _PROJECT_LOGO.exists() else _PARENT_LOGO


USDA_WASDE_OCT_2026 = "https://www.usda.gov/oce/commodity/wasde/wasde1026.pdf"
USDA_WASDE_SEP_2026 = "https://www.usda.gov/oce/commodity/wasde/wasde0926.pdf"
USDA_WASDE_NOV_2026 = "https://www.usda.gov/oce/commodity/wasde/wasde1126.pdf"
USDA_CATTLE_OCT_2026 = (
    "https://esmis.nal.usda.gov/sites/default/release-files/796119/cofd1026.pdf"
)
USDA_CATTLE_SEP_2026 = (
    "https://www.nass.usda.gov/Publications/Todays_Reports/reports/cofd0926.pdf"
)
USDA_CATTLE_NOV_2026_PAGE = "https://esmis.nal.usda.gov/publication/cattle-feed"


@dataclass(frozen=True)
class ReleaseCase:
    key: str
    commodity: str
    report: str
    current_label: str
    previous_label: str
    current_release_date: str
    previous_release_date: str
    current: dict[str, Any]
    previous: dict[str, Any]
    sources: tuple[tuple[str, str], ...]
    next_release_label: str
    next_release_date: str
    next_release_url: str
    note: str


CASES: dict[str, ReleaseCase] = {
    "corn": ReleaseCase(
        key="corn",
        commodity="Corn",
        report="USDA WASDE",
        current_label="October 2026",
        previous_label="September 2026",
        current_release_date="2026-10-09",
        previous_release_date="2026-09-11",
        current={
            "beginning_stocks": 2095,
            "production": 16034,
            "yield": 181.2,
            "total_use": 16305,
            "ending_stocks": 1849,
            "farm_price": 4.70,
            "exports": 3300,
            "feed_residual": 6000,
            "ethanol": 5650,
        },
        previous={
            "beginning_stocks": 1922,
            "production": 15800,
            "yield": 178.5,
            "total_use": 16180,
            "ending_stocks": 1567,
            "farm_price": 4.80,
            "exports": 3275,
            "feed_residual": 5950,
            "ethanol": 5600,
        },
        sources=(
            ("October 2026 WASDE", USDA_WASDE_OCT_2026),
            ("September 2026 WASDE", USDA_WASDE_SEP_2026),
        ),
        next_release_label="November 2026 WASDE",
        next_release_date="2026-11-10",
        next_release_url=USDA_WASDE_NOV_2026,
        note=(
            "The October-to-September comparison is a vintage comparison for the "
            "same 2026/27 marketing-year forecast. November 2026 WASDE was not "
            "yet released when this case was built."
        ),
    ),
    "cattle": ReleaseCase(
        key="cattle",
        commodity="Cattle",
        report="USDA Cattle on Feed",
        current_label="October 2026 release",
        previous_label="September 2026 release",
        current_release_date="2026-10-23",
        previous_release_date="2026-09-18",
        current={
            "inventory": 11372,
            "placements": 1777,
            "marketings": 1524,
            "other_disappearance": 49,
            "inventory_yoy_percent": 100,
            "placements_yoy_percent": 88,
            "marketings_yoy_percent": 93,
            "other_disappearance_yoy_percent": 96,
        },
        previous={
            "inventory": 11168,
            "placements": 1620,
            "marketings": 1517,
            "other_disappearance": 52,
            "inventory_yoy_percent": 101,
            "placements_yoy_percent": 91,
            "marketings_yoy_percent": 97,
            "other_disappearance_yoy_percent": 102,
        },
        sources=(
            ("October 2026 Cattle on Feed", USDA_CATTLE_OCT_2026),
            ("September 2026 Cattle on Feed", USDA_CATTLE_SEP_2026),
            ("NASS Cattle on Feed survey guide", "https://www.nass.usda.gov/Surveys/Guide_to_NASS_Surveys/Cattle_On_Feed/"),
        ),
        next_release_label="November 2026 Cattle on Feed",
        next_release_date="2026-11-20",
        next_release_url=USDA_CATTLE_NOV_2026_PAGE,
        note=(
            "Cattle on Feed is a monthly flow report rather than a WASDE vintage. "
            "The release-to-release comparison therefore compares the October 1 "
            "inventory and September flows with the September 1 inventory and "
            "August flows; year-over-year percentages remain the primary market read."
        ),
    ),
}


TEMPLATE_SHELLS = {
    "corn": (
        "{current_label} {report} changed 2026/27 U.S. corn ending stocks from "
        "[higher/lower] to [higher/lower] at [CURRENT_ENDING_STOCKS] million "
        "bushels ([+/- CHANGE] million; [+/- CHANGE_PCT]%). Production moved "
        "[up/down] to [CURRENT_PRODUCTION], while total use moved [up/down] to "
        "[CURRENT_USE]. The stocks-to-use ratio is [CURRENT_STU]% versus "
        "[PREVIOUS_STU]% in the prior release. Decision cue: [WHAT THIS MEANS "
        "FOR A PRODUCER]."
    ),
    "cattle": (
        "The {current_label} {report} put inventory at [CURRENT_INVENTORY] "
        "thousand head, placements at [CURRENT_PLACEMENTS], marketings at "
        "[CURRENT_MARKETINGS], and other disappearance at [CURRENT_OTHER]. "
        "Compared with the previous release, inventory [rose/fell] [CHANGE_PCT]%. "
        "The year-over-year read was [YOY_READ]. Decision cue: [WHAT THIS MEANS "
        "FOR A CATTLE PRODUCER]."
    ),
}


def get_case(key: str) -> ReleaseCase:
    """Return a case by key and fail loudly for a bad UI selection."""

    try:
        return CASES[key]
    except KeyError as exc:
        raise ValueError(f"Unknown USDA case: {key}") from exc


def _pct_change(current: float, previous: float) -> float:
    return (current / previous - 1.0) * 100.0 if previous else 0.0


def _direction(value: float, positive: str = "higher", negative: str = "lower") -> str:
    if value > 0:
        return positive
    if value < 0:
        return negative
    return "unchanged"


def corn_metrics(case: ReleaseCase) -> dict[str, Any]:
    current = case.current
    previous = case.previous
    current_stu = current["ending_stocks"] / current["total_use"] * 100.0
    previous_stu = previous["ending_stocks"] / previous["total_use"] * 100.0
    ending_change = current["ending_stocks"] - previous["ending_stocks"]
    return {
        "current_stu": current_stu,
        "previous_stu": previous_stu,
        "stu_change_pp": current_stu - previous_stu,
        "ending_change": ending_change,
        "ending_change_pct": _pct_change(current["ending_stocks"], previous["ending_stocks"]),
        "production_change": current["production"] - previous["production"],
        "production_change_pct": _pct_change(current["production"], previous["production"]),
        "yield_change": current["yield"] - previous["yield"],
        "use_change": current["total_use"] - previous["total_use"],
        "price_change": current["farm_price"] - previous["farm_price"],
        "stocks_direction": _direction(ending_change),
        "price_direction": _direction(current["farm_price"] - previous["farm_price"], "higher", "lower"),
    }


def cattle_metrics(case: ReleaseCase) -> dict[str, Any]:
    current = case.current
    previous = case.previous
    measures = ["inventory", "placements", "marketings", "other_disappearance"]
    metrics: dict[str, Any] = {}
    for measure in measures:
        metrics[f"{measure}_change"] = current[measure] - previous[measure]
        metrics[f"{measure}_change_pct"] = _pct_change(current[measure], previous[measure])
        metrics[f"{measure}_yoy_delta"] = current[f"{measure}_yoy_percent"] - 100.0
    return metrics


def metrics_for(case: ReleaseCase) -> dict[str, Any]:
    return corn_metrics(case) if case.key == "corn" else cattle_metrics(case)


def comparison_frame(case: ReleaseCase) -> pd.DataFrame:
    if case.key == "corn":
        rows = [
            ("Beginning stocks", case.previous["beginning_stocks"], case.current["beginning_stocks"], "million bu", "balance sheet"),
            ("Production", case.previous["production"], case.current["production"], "million bu", "balance sheet"),
            ("Yield", case.previous["yield"], case.current["yield"], "bu/acre", "balance sheet"),
            ("Total use", case.previous["total_use"], case.current["total_use"], "million bu", "balance sheet"),
            ("Exports", case.previous["exports"], case.current["exports"], "million bu", "balance sheet"),
            ("Ending stocks", case.previous["ending_stocks"], case.current["ending_stocks"], "million bu", "balance sheet"),
            ("USDA farm price", case.previous["farm_price"], case.current["farm_price"], "$/bu", "price projection"),
        ]
    else:
        rows = [
            ("On-feed inventory", case.previous["inventory"], case.current["inventory"], "thousand head", "release-to-release"),
            ("Placements", case.previous["placements"], case.current["placements"], "thousand head", "release-to-release"),
            ("Marketings", case.previous["marketings"], case.current["marketings"], "thousand head", "release-to-release"),
            ("Other disappearance", case.previous["other_disappearance"], case.current["other_disappearance"], "thousand head", "release-to-release"),
        ]
    frame = pd.DataFrame(rows, columns=["Measure", case.previous_label, case.current_label, "Units", "Comparison"])
    frame["Change"] = frame[case.current_label] - frame[case.previous_label]
    frame["Change %"] = frame.apply(
        lambda row: _pct_change(row[case.current_label], row[case.previous_label]), axis=1
    )
    return frame


def yoy_frame(case: ReleaseCase) -> pd.DataFrame:
    if case.key == "corn":
        return pd.DataFrame()
    labels = {
        "inventory": "On-feed inventory",
        "placements": "Placements",
        "marketings": "Marketings",
        "other_disappearance": "Other disappearance",
    }
    rows = []
    for key, label in labels.items():
        yoy_percent = case.current[f"{key}_yoy_percent"]
        rows.append((label, yoy_percent, yoy_percent - 100.0))
    return pd.DataFrame(rows, columns=["Measure", "Percent of prior year", "Change vs prior year (pp)"])


def generated_report(case: ReleaseCase) -> str:
    """Generate a short extension-style report from the normalized case."""

    if case.key == "corn":
        m = corn_metrics(case)
        current = case.current
        previous = case.previous
        signal = (
            "more bearish on stocks / more supportive of downside risk"
            if m["ending_change"] > 0
            else "more supportive on stocks / more constructive for price risk"
        )
        return (
            f"{case.current_label} {case.report} increased projected 2026/27 U.S. corn "
            f"ending stocks from {previous['ending_stocks']:,} to {current['ending_stocks']:,} "
            f"million bushels, a {m['ending_change']:+,} million bushel change "
            f"({m['ending_change_pct']:+.1f}%). The revision reflects production rising "
            f"{m['production_change']:+,} million bushels to {current['production']:,} "
            f"million bushels and total use rising {m['use_change']:+,} million bushels to "
            f"{current['total_use']:,} million bushels. Yield moved from "
            f"{previous['yield']:.1f} to {current['yield']:.1f} bushels per acre. "
            f"The stocks-to-use ratio rose from {m['previous_stu']:.1f}% to "
            f"{m['current_stu']:.1f}% ({m['stu_change_pp']:+.1f} percentage points), "
            f"while USDA's season-average farm-price projection moved from "
            f"${previous['farm_price']:.2f} to ${current['farm_price']:.2f} per bushel. "
            f"Producer decision cue: this is {signal}; review unpriced bushels, storage "
            "carry, and a staged hedge rather than treating the USDA number as a price "
            "forecast."
        )

    m = cattle_metrics(case)
    current = case.current
    return (
        f"The {case.current_label} {case.report} reported October 1 on-feed inventory "
        f"of {current['inventory']:,} thousand head, {m['inventory_change']:+,} thousand "
        f"from the prior release's September 1 inventory. September placements were "
        f"{current['placements']:,} thousand head ({current['placements_yoy_percent']:.0f}% "
        "of the prior year), the lowest September placements in the series; September "
        f"marketings were {current['marketings']:,} thousand head "
        f"({current['marketings_yoy_percent']:.0f}% of prior year), and other disappearance "
        f"was {current['other_disappearance']:,} thousand head "
        f"({current['other_disappearance_yoy_percent']:.0f}% of prior year). "
        "Producer decision cue: the near-term inventory signal is not a standalone "
        "price forecast, but the low placement and marketing readings support watching "
        "future fed-cattle availability, basis, and timing of sales."
    )


def _logo_data_uri() -> str:
    """Return the local Fryar logo as a self-contained image URI."""

    try:
        encoded = base64.b64encode(FRYAR_LOGO_PATH.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return f"data:image/png;base64,{encoded}"


def _html_table(case: ReleaseCase) -> str:
    """Build the branded comparison table without depending on a CSS framework."""

    frame = comparison_frame(case)
    rows = []
    for _, row in frame.iterrows():
        previous = row[case.previous_label]
        current = row[case.current_label]
        change = row["Change"]
        change_pct = row["Change %"]
        if case.key == "corn" and row["Measure"] == "USDA farm price":
            previous_text = f"${previous:.2f}"
            current_text = f"${current:.2f}"
            change_text = f"${change:+.2f}"
        elif row["Measure"] == "Yield":
            previous_text = f"{previous:,.1f}"
            current_text = f"{current:,.1f}"
            change_text = f"{change:+,.1f}"
        else:
            previous_text = f"{previous:,.0f}"
            current_text = f"{current:,.0f}"
            change_text = f"{change:+,.0f}"
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(row['Measure']))}</td>"
            f"<td>{previous_text}</td>"
            f"<td class=\"current\">{current_text}</td>"
            f"<td class=\"change\">{change_text} ({change_pct:+.1f}%)</td>"
            f"<td>{html.escape(str(row['Units']))}</td>"
            "</tr>"
        )
    return (
        "<table class=\"comparison\"><thead><tr>"
        f"<th>Measure</th><th>{html.escape(case.previous_label)}</th>"
        f"<th>{html.escape(case.current_label)}</th><th>Change</th><th>Units</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def branded_report_html(case: ReleaseCase) -> str:
    """Return a standalone Fryar-branded HTML report preview/download."""

    logo = _logo_data_uri()
    report = html.escape(generated_report(case))
    logo_html = (
        f'<img class="logo" src="{logo}" alt="Fryar Price Risk Management Center of Excellence">'
        if logo
        else '<div class="logo-fallback">FRYAR<br><span>PRICE RISK MANAGEMENT</span></div>'
    )
    if case.key == "corn":
        metrics = corn_metrics(case)
        stat_cards = (
            f'<div class="stat"><div class="stat-label">ENDING STOCKS</div><div class="stat-value">{case.current["ending_stocks"]:,} <small>M bu</small></div><div class="stat-delta">{metrics["ending_change"]:+,} vs prior release</div></div>'
            f'<div class="stat"><div class="stat-label">STOCKS / USE</div><div class="stat-value">{metrics["current_stu"]:.1f}<small>%</small></div><div class="stat-delta">{metrics["stu_change_pp"]:+.1f} pp</div></div>'
            f'<div class="stat"><div class="stat-label">PRODUCTION</div><div class="stat-value">{case.current["production"]:,} <small>M bu</small></div><div class="stat-delta">{metrics["production_change"]:+,} vs prior release</div></div>'
            f'<div class="stat"><div class="stat-label">USDA FARM PRICE</div><div class="stat-value">${case.current["farm_price"]:.2f}<small> / bu</small></div><div class="stat-delta">{metrics["price_change"]:+.2f} vs prior release</div></div>'
        )
        watch_text = "Review unpriced bushels, storage carry, and a staged hedge; do not treat the USDA farm-price projection as a guaranteed market forecast."
    else:
        metrics = cattle_metrics(case)
        stat_cards = (
            f'<div class="stat"><div class="stat-label">OCT 1 INVENTORY</div><div class="stat-value">{case.current["inventory"]:,}<small>k head</small></div><div class="stat-delta">{metrics["inventory_change"]:+,} vs prior release</div></div>'
            f'<div class="stat"><div class="stat-label">SEP PLACEMENTS</div><div class="stat-value">{case.current["placements"]:,}<small>k</small></div><div class="stat-delta">{case.current["placements_yoy_percent"]:.0f}% of prior year</div></div>'
            f'<div class="stat"><div class="stat-label">SEP MARKETINGS</div><div class="stat-value">{case.current["marketings"]:,}<small>k</small></div><div class="stat-delta">{case.current["marketings_yoy_percent"]:.0f}% of prior year</div></div>'
            f'<div class="stat"><div class="stat-label">OTHER DISAPPEARANCE</div><div class="stat-value">{case.current["other_disappearance"]:,}<small>k</small></div><div class="stat-delta">{case.current["other_disappearance_yoy_percent"]:.0f}% of prior year</div></div>'
        )
        watch_text = "Watch future fed-cattle availability, basis, and timing of sales; the report is an availability signal, not a standalone price forecast."
    sources = "".join(
        f'<li><a href="{html.escape(url)}">{html.escape(label)}</a></li>'
        for label, url in case.sources
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(case.commodity)} USDA Release Report | Fryar Center</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap');
:root {{ --red:{FRYAR_CARDINAL}; --blue:{FRYAR_BLUE}; --ink:{FRYAR_INK}; --slate:{FRYAR_SLATE}; --pale:{FRYAR_PALE}; --line:{FRYAR_LINE}; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:#eceff1; color:var(--ink); font-family:Poppins,Arial,sans-serif; line-height:1.55; }}
.page {{ max-width:980px; margin:28px auto; background:#fff; box-shadow:0 8px 30px rgba(32,33,36,.12); }}
.header {{ padding:28px 46px 22px; border-top:10px solid var(--red); border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; gap:24px; }}
.logo {{ width:310px; height:auto; max-height:92px; object-fit:contain; object-position:left center; }}
.logo-fallback {{ color:var(--red); font-weight:700; letter-spacing:.12em; line-height:1.05; font-size:27px; }}
.logo-fallback span {{ color:var(--ink); font-size:11px; letter-spacing:.08em; }}
.series {{ text-align:right; color:var(--slate); font-size:12px; }}
.series strong {{ display:block; color:var(--red); font-size:14px; letter-spacing:.08em; text-transform:uppercase; }}
.hero {{ padding:34px 46px 26px; background:linear-gradient(110deg,#fff 0%,#fff 63%,#fbf3f5 100%); }}
.eyebrow {{ color:var(--red); font-size:12px; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }}
h1 {{ margin:8px 0 4px; font-size:34px; line-height:1.15; letter-spacing:-.02em; }}
.subtitle {{ color:var(--slate); margin:0; font-size:15px; }}
.rule {{ height:4px; background:var(--red); width:72px; margin:22px 0 16px; }}
.headline {{ font-size:17px; margin:0; }}
.stats {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; padding:0 46px 28px; background:linear-gradient(110deg,#fff 0%,#fff 63%,#fbf3f5 100%); }}
.stat {{ border:1px solid var(--line); border-top:4px solid var(--red); padding:14px 14px 13px; background:#fff; min-height:112px; }}
.stat-label {{ color:var(--slate); font-size:10px; font-weight:700; letter-spacing:.08em; }}
.stat-value {{ font-size:25px; font-weight:600; line-height:1.2; margin-top:7px; white-space:nowrap; }}
.stat-value small {{ font-size:12px; color:var(--slate); font-weight:500; }}
.stat-delta {{ color:var(--red); font-size:11px; margin-top:7px; }}
.content {{ padding:30px 46px 40px; }}
h2 {{ color:var(--red); font-size:19px; margin:24px 0 8px; padding-bottom:7px; border-bottom:1px solid var(--line); }}
h2:first-child {{ margin-top:0; }}
h3 {{ font-size:15px; margin:16px 0 6px; }}
.callout {{ border-left:5px solid var(--red); background:#fbf3f5; padding:16px 18px; margin:12px 0 20px; }}
.callout strong {{ color:var(--red); }}
.comparison {{ border-collapse:collapse; width:100%; font-size:12px; margin:12px 0 18px; }}
.comparison th {{ background:var(--red); color:#fff; font-weight:600; text-align:left; padding:9px 10px; }}
.comparison td {{ border-bottom:1px solid var(--line); padding:9px 10px; }}
.comparison tr:nth-child(even) td {{ background:#fafbfc; }}
.comparison .current {{ font-weight:600; }}
.comparison .change {{ color:var(--red); font-weight:600; }}
.two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:24px; }}
.method {{ background:var(--pale); border:1px solid var(--line); padding:15px 17px; font-size:12px; color:var(--slate); }}
.method code {{ color:var(--ink); }}
.sources {{ font-size:11px; color:var(--slate); }}
.sources a {{ color:var(--red); }}
.footer {{ background:#27343b; color:#e9eef0; padding:18px 46px; display:flex; justify-content:space-between; gap:24px; font-size:11px; }}
.footer strong {{ color:#fff; }}
.disclaimer {{ color:#cbd5da; max-width:60%; text-align:right; }}
@media(max-width:720px) {{ .header,.hero,.content,.footer {{ padding-left:22px; padding-right:22px; }} .stats {{ padding-left:22px; padding-right:22px; grid-template-columns:repeat(2,1fr); }} .header,.footer {{ display:block; }} .series {{ text-align:left; margin-top:14px; }} .two-col {{ display:block; }} .disclaimer {{ max-width:100%; text-align:left; margin-top:10px; }} h1 {{ font-size:28px; }} .logo {{ width:260px; }} }}
</style>
</head>
<body>
<main class="page">
<header class="header">{logo_html}<div class="series"><strong>Market Situation &amp; Outlook</strong>USDA release analysis<br>{html.escape(case.current_release_date)}</div></header>
<section class="hero"><div class="eyebrow">Fryar Center Extension Brief</div><h1>{html.escape(case.commodity)}: {html.escape(case.report)} update</h1><p class="subtitle">{html.escape(case.previous_label)} → {html.escape(case.current_label)} · Decision-focused interpretation for producers</p><div class="rule"></div><p class="headline"><strong>At a glance.</strong> {report}</p></section>
<section class="stats">{stat_cards}</section>
<section class="content">
<h2>What changed</h2>
{_html_table(case)}
<div class="callout"><strong>Producer decision cue.</strong> {html.escape(watch_text)}</div>
<div class="two-col"><div><h2>How to read this release</h2><p>{html.escape(case.note)}</p></div><div><h2>Method and data</h2><div class="method">This brief compares the two official USDA releases and computes changes directly from the reported quantities. It is an educational Extension product, not a price guarantee, trade recommendation, or individualized marketing advice.</div></div></div>
<h2>Official sources</h2><ul class="sources">{sources}</ul>
</section>
<footer class="footer"><div><strong>Fryar Price Risk Management Center of Excellence</strong><br>University of Arkansas System Division of Agriculture<br>Fayetteville, Arkansas</div><div class="disclaimer">Research-based, stakeholder-informed analysis for better agricultural risk decisions.<br>Prepared {date.today().isoformat()} · Validate data and assumptions before public release.</div></footer>
</main>
</body></html>"""


def branded_fact_sheet_html(case: ReleaseCase) -> str:
    """Return a concise, one-page Fryar-branded fact sheet."""

    logo = _logo_data_uri()
    logo_html = (
        f'<img class="logo" src="{logo}" alt="Fryar Price Risk Management Center of Excellence">'
        if logo
        else '<div class="logo-fallback">FRYAR<br><span>PRICE RISK MANAGEMENT</span></div>'
    )
    if case.key == "corn":
        metrics = corn_metrics(case)
        key_rows = [
            ("Ending stocks", f"{case.current['ending_stocks']:,} million bu", f"{metrics['ending_change']:+,} vs. prior release"),
            ("Stocks-to-use", f"{metrics['current_stu']:.1f}%", f"{metrics['stu_change_pp']:+.1f} percentage points"),
            ("Production", f"{case.current['production']:,} million bu", f"{metrics['production_change']:+,} vs. prior release"),
            ("USDA farm price", f"${case.current['farm_price']:.2f}/bu", f"{metrics['price_change']:+.2f} vs. prior release"),
        ]
        watch = "Review unpriced bushels, storage carry, and a staged hedge. Higher projected stocks are a softer balance-sheet signal, but the marketing decision still depends on basis, storage, cost of production, and the farm's risk tolerance."
        bullets = [
            "Separate the futures-price decision from the basis and storage decision.",
            "Compare the projected margin under unpriced, staged, and protected sales.",
            "Update the decision when the next USDA vintage or local basis changes.",
        ]
    else:
        metrics = cattle_metrics(case)
        key_rows = [
            ("On-feed inventory", f"{case.current['inventory']:,} thousand head", f"{metrics['inventory_change']:+,} vs. prior release"),
            ("September placements", f"{case.current['placements']:,} thousand head", f"{case.current['placements_yoy_percent']:.0f}% of prior year"),
            ("September marketings", f"{case.current['marketings']:,} thousand head", f"{case.current['marketings_yoy_percent']:.0f}% of prior year"),
            ("Other disappearance", f"{case.current['other_disappearance']:,} thousand head", f"{case.current['other_disappearance_yoy_percent']:.0f}% of prior year"),
        ]
        watch = "Use the low placement and marketing readings as an availability signal to monitor future fed-cattle supplies, basis, and sale timing—not as a standalone price forecast."
        bullets = [
            "Track placements and marketings together with basis and cash price discovery.",
            "Compare the expected margin from a sale now versus a staged sale plan.",
            "Use LRP or another protection strategy only after checking coverage, premium, and delivery timing.",
        ]
    rows_html = "".join(
        f'<div class="row"><div class="label">{html.escape(label)}</div><div class="value">{html.escape(value)}</div><div class="delta">{html.escape(delta)}</div></div>'
        for label, value, delta in key_rows
    )
    bullets_html = "".join(f"<li>{html.escape(bullet)}</li>" for bullet in bullets)
    sources = "".join(
        f'<li><a href="{html.escape(url)}">{html.escape(label)}</a></li>'
        for label, url in case.sources
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(case.commodity)} USDA Fact Sheet | Fryar Center</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap');
:root {{ --red:{FRYAR_CARDINAL}; --ink:{FRYAR_INK}; --slate:{FRYAR_SLATE}; --pale:{FRYAR_PALE}; --line:{FRYAR_LINE}; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:#eceff1; color:var(--ink); font-family:Poppins,Arial,sans-serif; line-height:1.5; }}
.page {{ max-width:860px; margin:28px auto; background:#fff; box-shadow:0 8px 30px rgba(32,33,36,.12); }}
.header {{ padding:24px 42px 18px; border-top:9px solid var(--red); border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; gap:18px; }}
.logo {{ width:270px; max-height:82px; object-fit:contain; object-position:left center; }} .logo-fallback {{ color:var(--red); font-weight:700; letter-spacing:.12em; line-height:1.05; font-size:25px; }} .logo-fallback span {{ color:var(--ink); font-size:10px; letter-spacing:.08em; }}
.date {{ text-align:right; color:var(--slate); font-size:11px; }} .date strong {{ display:block; color:var(--red); text-transform:uppercase; letter-spacing:.1em; font-size:13px; }}
.hero {{ padding:27px 42px 23px; background:linear-gradient(110deg,#fff 0%,#fff 65%,#fbf3f5 100%); }} .eyebrow {{ color:var(--red); font-size:11px; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }} h1 {{ margin:7px 0 3px; line-height:1.15; font-size:31px; }} .subtitle {{ margin:0; color:var(--slate); font-size:13px; }} .rule {{ height:4px; background:var(--red); width:64px; margin:17px 0 13px; }}
.content {{ padding:24px 42px 33px; }} h2 {{ margin:19px 0 8px; padding-bottom:6px; border-bottom:1px solid var(--line); color:var(--red); font-size:17px; }} h2:first-child {{ margin-top:0; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:14px 0 18px; }} .row {{ border:1px solid var(--line); border-left:4px solid var(--red); padding:11px 13px; background:#fff; }} .label {{ color:var(--slate); font-size:10px; font-weight:700; letter-spacing:.07em; text-transform:uppercase; }} .value {{ font-size:22px; font-weight:600; line-height:1.2; margin-top:3px; }} .delta {{ color:var(--red); font-size:11px; margin-top:4px; }}
.callout {{ border-left:5px solid var(--red); background:#fbf3f5; padding:14px 16px; font-size:13px; }} .callout strong {{ color:var(--red); }} ul {{ margin-top:7px; padding-left:20px; }} li {{ margin:5px 0; font-size:12px; }} .note {{ background:var(--pale); border:1px solid var(--line); color:var(--slate); padding:12px 14px; font-size:11px; }} .sources {{ font-size:10px; color:var(--slate); }} .sources a {{ color:var(--red); }} .footer {{ background:#27343b; color:#e9eef0; padding:15px 42px; font-size:10px; display:flex; justify-content:space-between; gap:18px; }} .footer strong {{ color:#fff; }} .footer span {{ color:#cbd5da; text-align:right; }}
@media(max-width:680px) {{ .header,.hero,.content,.footer {{ padding-left:20px; padding-right:20px; }} .header,.footer {{ display:block; }} .date {{ text-align:left; margin-top:10px; }} .grid {{ grid-template-columns:1fr; }} h1 {{ font-size:27px; }} .footer span {{ display:block; text-align:left; margin-top:8px; }} }}
</style>
</head>
<body><main class="page">
<header class="header">{logo_html}<div class="date"><strong>Fryar Center Fact Sheet</strong>{html.escape(case.current_label)}<br>Prepared {date.today().isoformat()}</div></header>
<section class="hero"><div class="eyebrow">USDA Release Snapshot</div><h1>{html.escape(case.commodity)}: key numbers for producers</h1><p class="subtitle">{html.escape(case.previous_label)} → {html.escape(case.current_label)}</p><div class="rule"></div><p><strong>Bottom line.</strong> {html.escape(generated_report(case))}</p></section>
<section class="content"><h2>At a glance</h2><div class="grid">{rows_html}</div><h2>What it means for a producer</h2><div class="callout"><strong>Decision cue.</strong> {html.escape(watch)}</div><h2>Three things to do next</h2><ul>{bullets_html}</ul><h2>Data and sources</h2><div class="note">{html.escape(case.note)}</div><ul class="sources">{sources}</ul></section>
<footer class="footer"><div><strong>Fryar Price Risk Management Center of Excellence</strong><br>University of Arkansas System Division of Agriculture</div><span>Research-based, stakeholder-informed analysis.<br>Educational Extension product; validate assumptions before use.</span></footer>
</main></body></html>"""


def next_release_status(case: ReleaseCase, today: date | None = None) -> dict[str, Any]:
    """Return a truthful release status without assuming a future file exists."""

    today = today or date.today()
    release_day = date.fromisoformat(case.next_release_date)
    return {
        "label": case.next_release_label,
        "date": case.next_release_date,
        "url": case.next_release_url,
        "released": today >= release_day,
        "days_until": max((release_day - today).days, 0),
    }


def check_source(url: str, timeout: int = 20) -> dict[str, Any]:
    """Check an official public source for a future scheduled refresh job."""

    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        # Some public USDA endpoints do not implement HEAD correctly.
        if response.status_code >= 400:
            response = requests.get(url, timeout=timeout, stream=True)
        return {
            "ok": response.status_code < 400,
            "status_code": response.status_code,
            "url": response.url,
            "checked_at": checked_at,
            "message": "Official source is reachable." if response.status_code < 400 else response.reason,
        }
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status_code": None,
            "url": url,
            "checked_at": checked_at,
            "message": f"Source check failed: {exc}",
        }
