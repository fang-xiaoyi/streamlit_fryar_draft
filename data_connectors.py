"""Optional live-data connectors for the Fryar Streamlit draft.

The app should call these connectors from a scheduled data-refresh job and read
the normalized result from local storage or a database. They are kept separate
from the Streamlit UI so that API credentials are never exposed to end users.

Credentials should be supplied through Streamlit secrets or environment
variables. No credential belongs in this file or in the repository.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


@dataclass
class FetchResult:
    source: str
    url: str
    retrieved_at: str
    data: pd.DataFrame | None = None
    raw_bytes: bytes | None = None
    message: str = ""


RMA_LRP_PAGE = "LRPCoveragePricesRatesActualEndingValues"
RMA_LRP_SERVICE = (
    "https://webapp.rma.usda.gov/apps/RIRS/WebServices/"
    "LRPCoveragePricesRatesActualEndingValues.asmx"
)
RMA_LRP_API = (
    "https://webapp.rma.usda.gov/apps/RIRS/api/"
    "LRPCoveragePricesRatesActualEndingValues"
)
RMA_LRP_COMMODITY_CODES = {
    "Fed Cattle": "0802",
    "Hogs": "0815",
    "Feeder Cattle": "0801",
}
RMA_LRP_DEFAULT_TYPE_CODES = {
    "0801": "809",  # feeder cattle: first type in the RMA criteria table
    "0802": "820",  # fed cattle: steers and heifers
    "0815": "997",  # swine: current RMA swine type
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(value: str | None, name: str) -> str:
    if not value:
        raise RuntimeError(f"Missing credential: {name}")
    return value


def _rma_json_value(response: requests.Response) -> Any:
    """Decode the ASP.NET web-service envelope used by the RMA RIRS site."""

    response.raise_for_status()
    payload = response.json()
    value = payload.get("d", payload)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _rma_post(
    method: str,
    payload: dict[str, Any],
    *,
    session: requests.Session,
    timeout: int,
) -> Any:
    response = session.post(
        f"{RMA_LRP_SERVICE}/{method}",
        json=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=timeout,
    )
    return _rma_json_value(response)


def _rma_criteria_frame(
    *,
    commodity: str | None,
    type_code: str | None,
    session: requests.Session,
    timeout: int,
) -> pd.DataFrame:
    criteria = _rma_post(
        "GetReportCriteria",
        {"PageName": RMA_LRP_PAGE, "Database": "R"},
        session=session,
        timeout=timeout,
    )
    frame = pd.DataFrame(criteria)
    if frame.empty:
        raise RuntimeError("RMA returned no LRP criteria records.")
    if commodity:
        frame = frame.loc[frame["Commodity"].astype(str) == str(commodity)]
    if type_code:
        frame = frame.loc[frame["TypeCode"].astype(str) == str(type_code)]
    if frame.empty:
        raise ValueError(
            "RMA has no LRP quote criteria for "
            f"commodity={commodity!r}, type_code={type_code!r}."
        )
    frame["SalesEffectiveDateParsed"] = pd.to_datetime(
        frame["SalesEffectiveDate"], errors="coerce"
    ).dt.date
    return frame


def fetch_rma_lrp_quote(
    commodity: str,
    type_code: str,
    effective_date: str | date | None = None,
    commodity_year: str | int | None = None,
    timeout: int = 120,
    session: requests.Session | None = None,
) -> FetchResult:
    """Fetch live LRP coverage prices and producer premiums from USDA RMA.

    This uses the public RMA RIRS report service behind the official
    ``LRP Coverage, Prices, Rates, and Actual Ending Values`` report.  It is
    intentionally quote-data only: purchasing a policy still requires an
    approved crop-insurance agent.

    ``commodity`` and ``type_code`` are RMA codes (for example, ``0802`` and
    ``820`` for fed cattle / steers and heifers).  When no effective date is
    supplied, the most recent available date in the RMA criteria table is used.
    """

    own_session = session is None
    http = session or requests.Session()
    try:
        criteria = _rma_criteria_frame(
            commodity=str(commodity),
            type_code=str(type_code),
            session=http,
            timeout=timeout,
        )

        if effective_date is None:
            today = date.today()
            eligible = criteria.loc[criteria["SalesEffectiveDateParsed"] <= today]
            if eligible.empty:
                eligible = criteria
            selected_date = eligible["SalesEffectiveDateParsed"].max()
        else:
            selected_date = pd.to_datetime(effective_date).date()

        criteria = criteria.loc[
            criteria["SalesEffectiveDateParsed"] == selected_date
        ]
        if commodity_year is not None:
            criteria = criteria.loc[
                criteria["CommodityYear"].astype(str) == str(commodity_year)
            ]
        if criteria.empty:
            raise ValueError(
                "RMA has no matching LRP quote for the requested effective date "
                f"({selected_date})."
            )

        # If several commodity years are present for a date, use the latest
        # year.  The criteria row is only used to identify a valid report
        # selection; the returned report contains all endorsement lengths and
        # coverage levels for that selection.
        chosen = criteria.sort_values("CommodityYear").iloc[-1]
        payload: dict[str, Any] = {
            "PageName": RMA_LRP_PAGE,
            "DataSource": "R",
            "CommodityYear": str(chosen["CommodityYear"]),
            "SalesEffectiveDate": str(chosen["SalesEffectiveDate"]),
            "Commodity": str(chosen["Commodity"]),
            "TypeCode": str(chosen["TypeCode"]),
            "InsuranceOfferFields": (
                "CommodityYear,CommodityCode,CommodityName,InsurancePlanCode,"
                "InsurancePlanName,InsurancePlanAbbreviation,SalesEffectiveDate"
            ),
            "TypePracticeFields": "TypeCode,TypeName,PracticeCode,PracticeName",
            "CoveragePriceRateFields": (
                "EndorsementLength,ExpectedEndValue,CoveragePrice,CoverageLevel,"
                "LivestockRate,CostPerCwt,ProducerPremiumPerCWT,EndDate,"
                "ActualEndValue,PriceAdjustmentFactor"
            ),
            "OutputFormat": "CSV",
            # The web form sends an empty value when Preview is unchecked.
            "preview": "",
        }
        report_id = _rma_post(
            "GetReport", payload, session=http, timeout=timeout
        )
        if not report_id:
            raise RuntimeError("RMA did not return a report identifier.")

        report_url = f"{RMA_LRP_API}/{report_id}"
        response = http.get(report_url, timeout=timeout)
        response.raise_for_status()
        frame = pd.read_csv(io.BytesIO(response.content), skipinitialspace=True)
        frame.columns = [str(column).strip() for column in frame.columns]
        for column in frame.select_dtypes(include="object").columns:
            frame[column] = frame[column].map(
                lambda value: value.strip() if isinstance(value, str) else value
            )
        numeric_columns = [
            "Endorsement Length",
            "Expected End Value",
            "Coverage Price",
            "Coverage Level",
            "Livestock Rate",
            "Cost Per CWT",
            "Producer Premium Per CWT",
            "Actual End Value",
            "Price Adjustment Factor",
        ]
        for column in numeric_columns:
            if column in frame:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")

        return FetchResult(
            source="USDA RMA RIRS: LRP coverage prices and rates",
            url=report_url,
            retrieved_at=_timestamp(),
            data=frame,
            message=(
                "Official RMA LRP coverage prices, rates, and producer premiums; "
                f"sales effective date {selected_date.isoformat()}."
            ),
        )
    finally:
        if own_session:
            http.close()


def fetch_nass_quickstats(
    api_key: str,
    query: dict[str, Any],
    timeout: int = 30,
) -> FetchResult:
    """Fetch NASS Quick Stats records using the official API."""

    url = "https://quickstats.nass.usda.gov/api/api_GET/"
    params = {"key": _require(api_key, "NASS_API_KEY"), "format": "JSON", **query}
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", payload if isinstance(payload, list) else [])
    return FetchResult(
        source="USDA NASS Quick Stats",
        url=response.url,
        retrieved_at=_timestamp(),
        data=pd.DataFrame(rows),
        message="Official NASS estimates retrieved through Quick Stats API.",
    )


def fetch_ams_reports(
    api_key: str,
    report_id: str | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = 30,
) -> FetchResult:
    """Fetch USDA AMS MyMarketNews report metadata or a selected report."""

    base = "https://marsapi.ams.usda.gov/services/v1.2/reports"
    url = f"{base}/{report_id}" if report_id else base
    response = requests.get(
        url,
        params=params or {},
        auth=(_require(api_key, "AMS_API_KEY"), ""),
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("results", payload if isinstance(payload, list) else [])
    return FetchResult(
        source="USDA AMS MyMarketNews",
        url=response.url,
        retrieved_at=_timestamp(),
        data=pd.DataFrame(rows),
        message="Official AMS Market News data retrieved through MyMarketNews API.",
    )


def fetch_fas_psd(
    api_key: str,
    commodity_code: str,
    country_code: str,
    market_year: int,
    base_url: str = "https://api.fas.usda.gov",
    timeout: int = 30,
) -> FetchResult:
    """Fetch USDA FAS PSD data.

    The FAS Open Data portal has migrated its API base URL over time. The base
    URL is configurable so the Center can use the endpoint documented by its
    current API subscription. The current portal uses an API-key header.
    """

    endpoint = (
        f"{base_url.rstrip('/')}/api/psd/commodity/{commodity_code}"
        f"/country/{country_code}/year/{market_year}"
    )
    response = requests.get(
        endpoint,
        headers={"API_KEY": _require(api_key, "FAS_API_KEY")},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", payload if isinstance(payload, list) else [])
    return FetchResult(
        source="USDA FAS Production, Supply and Distribution",
        url=response.url,
        retrieved_at=_timestamp(),
        data=pd.DataFrame(rows),
        message="Official FAS PSD forecast data retrieved through the configured API.",
    )


def fetch_barchart_quote(
    api_key: str,
    symbols: str,
    fields: str | None = None,
    timeout: int = 30,
) -> FetchResult:
    """Fetch Barchart OnDemand quote data for futures or other instruments.

    This requires a Barchart OnDemand API key. A CmdtyView webpage username and
    password are not substituted for that key and should never be stored here.
    """

    url = "https://ondemand.websol.barchart.com/getQuote.json"
    params: dict[str, Any] = {
        "apikey": _require(api_key, "BARCHART_API_KEY"),
        "symbols": symbols,
    }
    if fields:
        params["fields"] = fields
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("results", [])
    return FetchResult(
        source="Barchart OnDemand quote",
        url=response.url,
        retrieved_at=_timestamp(),
        data=pd.DataFrame(rows),
        message="Barchart quote data retrieved through the configured OnDemand API entitlement.",
    )


def fetch_barchart_history(
    api_key: str,
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    interval: str = "daily",
    timeout: int = 30,
) -> FetchResult:
    """Fetch historical futures prices from an entitled Barchart feed.

    The page uses this connector for contract-level event studies, where a
    continuous futures series is not sufficient to calculate a calendar
    spread.  Credentials stay in Streamlit secrets/environment variables and
    are never returned in the result or shown in the UI.
    """

    url = "https://ondemand.websol.barchart.com/getHistory.json"
    params: dict[str, Any] = {
        "apikey": _require(api_key, "BARCHART_API_KEY"),
        "symbol": symbol,
        "type": interval,
        "startDate": pd.Timestamp(start_date).date().isoformat(),
        "endDate": pd.Timestamp(end_date).date().isoformat(),
    }
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("results", [])
    return FetchResult(
        source="Barchart OnDemand historical futures",
        url=response.url,
        retrieved_at=_timestamp(),
        data=pd.DataFrame(rows),
        message=(
            "Barchart historical futures data retrieved through the configured "
            "OnDemand API entitlement."
        ),
    )


def fetch_yahoo_chart_history(
    symbol: str,
    start_date: date | str,
    end_date: date | str,
    interval: str = "1d",
    timeout: int = 30,
) -> FetchResult:
    """Fetch a public daily continuous-futures history for fallback context.

    This is intentionally labeled as a continuous reference series.  It is
    useful for the nearby-price response when no licensed contract-level feed
    is configured, but it must not be used to manufacture a deferred contract
    or a calendar spread.
    """

    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")
    end = end + pd.Timedelta(days=1)

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "period1": int(start.timestamp()),
        "period2": int(end.timestamp()),
        "interval": interval,
        "events": "history",
        "includeAdjustedClose": "true",
    }
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": "Fryar-Center-Market-Response/1.0"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(str(chart["error"]))
    results = chart.get("result") or []
    if not results:
        raise RuntimeError(f"No Yahoo Finance history returned for {symbol}.")
    result = results[0]
    timestamps = result.get("timestamp", [])
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    rows: list[dict[str, Any]] = []
    for idx, stamp in enumerate(timestamps):
        rows.append(
            {
                "date": pd.to_datetime(stamp, unit="s", utc=True).date().isoformat(),
                "open": (quote.get("open") or [None] * len(timestamps))[idx],
                "high": (quote.get("high") or [None] * len(timestamps))[idx],
                "low": (quote.get("low") or [None] * len(timestamps))[idx],
                "close": (quote.get("close") or [None] * len(timestamps))[idx],
                "volume": (quote.get("volume") or [None] * len(timestamps))[idx],
            }
        )
    return FetchResult(
        source="Yahoo Finance chart feed (continuous futures reference)",
        url=response.url,
        retrieved_at=_timestamp(),
        data=pd.DataFrame(rows),
        message=(
            "Public continuous-futures reference data retrieved. It is not a "
            "substitute for licensed contract-level settlement data."
        ),
    )


def fetch_barchart_futures_options(
    api_key: str,
    root: str,
    contract: str | None = None,
    option_type: str | None = None,
    fields: str = "premium,openInterest",
    end_of_day: bool = False,
    timeout: int = 30,
) -> FetchResult:
    """Fetch Barchart futures-option chains, including volatility and Greeks when entitled."""

    endpoint = "getFuturesOptionsEOD" if end_of_day else "getFuturesOptions"
    url = f"https://ondemand.websol.barchart.com/{endpoint}.json"
    params: dict[str, Any] = {
        "apikey": _require(api_key, "BARCHART_API_KEY"),
        "root": root,
        "fields": fields,
    }
    if contract:
        params["contract"] = contract
    if option_type:
        params["type"] = option_type
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("results", [])
    return FetchResult(
        source="Barchart OnDemand futures options",
        url=response.url,
        retrieved_at=_timestamp(),
        data=pd.DataFrame(rows),
        message="Barchart futures-options data retrieved through the configured OnDemand API entitlement.",
    )


def download_table(
    url: str,
    file_type: str = "csv",
    timeout: int = 60,
) -> FetchResult:
    """Download a public CSV, Excel, XML, or text data file.

    This generic connector is used for WASDE files, RMA bulk files, CFTC
    downloads, and USDA historical tables whose official access is a file rather
    than a REST API.
    """

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    content = response.content
    normalized = file_type.lower().lstrip(".")

    if normalized in {"csv", "txt"}:
        data = pd.read_csv(io.BytesIO(content))
    elif normalized in {"xlsx", "xls"}:
        data = pd.read_excel(io.BytesIO(content))
    elif normalized == "zip":
        data = None
    else:
        data = pd.DataFrame({"content": [content.decode("utf-8", errors="replace")]})

    return FetchResult(
        source="Public USDA/CFTC file",
        url=response.url,
        retrieved_at=_timestamp(),
        data=data,
        raw_bytes=content,
        message=f"Downloaded public {normalized.upper()} file.",
    )


def save_result(result: FetchResult, output_dir: str | Path, filename: str) -> Path:
    """Save a normalized table or raw response to a controlled cache directory."""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    if result.data is not None:
        result.data.to_parquet(target, index=False)
    elif result.raw_bytes is not None:
        target.write_bytes(result.raw_bytes)
    else:
        raise ValueError("FetchResult contains neither tabular data nor raw bytes")
    return target


def credential_status() -> dict[str, bool]:
    """Return whether environment credentials are available without revealing them."""

    names = [
        "NASS_API_KEY",
        "AMS_API_KEY",
        "FAS_API_KEY",
        "BARCHART_API_KEY",
        "CME_API_ID",
        "CME_API_PASSWORD",
    ]
    return {name: bool(os.getenv(name)) for name in names}


def cme_datamine_access_token(
    api_id: str,
    api_password: str,
    timeout: int = 30,
) -> str:
    """Obtain an OAuth token for an entitled CME DataMine account."""

    response = requests.post(
        "https://auth.cmegroup.com/as/token.oauth2",
        data={"grant_type": "client_credentials"},
        auth=(
            _require(api_id, "CME_API_ID"),
            _require(api_password, "CME_API_PASSWORD"),
        ),
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def download_cme_datamine_file(
    api_id: str,
    api_password: str,
    file_id: str,
    timeout: int = 60,
) -> FetchResult:
    """Download an entitled historical CME DataMine file."""

    token = cme_datamine_access_token(api_id, api_password, timeout=timeout)
    url = "https://datamine.new.cmegroup.com/cme/api/v2/download"
    response = requests.get(
        url,
        params={"fid": file_id},
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return FetchResult(
        source="CME DataMine",
        url=response.url,
        retrieved_at=_timestamp(),
        raw_bytes=response.content,
        message="Entitled CME historical file downloaded; parse according to its file metadata.",
    )
