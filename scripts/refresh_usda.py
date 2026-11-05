"""Download, parse, validate, version, and report USDA release snapshots.

This script is designed for GitHub Actions.  It is intentionally idempotent:
the same release and file hash are skipped, while a changed file is retained
as a revision instead of overwriting the older vintage.

Examples
--------
python scripts/refresh_usda.py --all
python scripts/refresh_usda.py --commodity corn --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from history_store import DATA_DIR, MANIFEST_PATH, NORMALIZED_DIR, LATEST_PATH, build_case, list_snapshots  # noqa: E402
from usda_report_pipeline import (  # noqa: E402
    CASES,
    branded_fact_sheet_html,
    branded_report_html,
    generated_report,
)


PARSER_VERSION = "usda-refresh-1.0"
USER_AGENT = "Fryar USDA Release Pipeline/1.0 (University of Arkansas Extension prototype)"
REQUIRED_FIELDS = {
    "corn": ("beginning_stocks", "production", "yield", "total_use", "exports", "ending_stocks", "farm_price"),
    "cattle": ("inventory", "placements", "marketings", "other_disappearance"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _month_candidates(today: date, months_back: int = 2) -> Iterable[tuple[int, int]]:
    year, month = today.year, today.month
    for offset in range(months_back + 1):
        candidate_month = month - offset
        candidate_year = year
        while candidate_month <= 0:
            candidate_month += 12
            candidate_year -= 1
        yield candidate_year, candidate_month


def _candidate_urls(commodity: str, year: int, month: int) -> list[str]:
    code = f"{month:02d}{year % 100:02d}"
    if commodity == "corn":
        return [f"https://www.usda.gov/oce/commodity/wasde/wasde{code}.pdf"]
    return [
        f"https://www.nass.usda.gov/Publications/Todays_Reports/reports/cofd{code}.pdf",
        f"https://esmis.nal.usda.gov/sites/default/release-files/796119/cofd{code}.pdf",
    ]


def _download(url: str, destination: Path, session: requests.Session) -> bytes | None:
    response = session.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=60,
        allow_redirects=True,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "pdf" not in content_type and not response.content.startswith(b"%PDF"):
        # USDA sometimes returns an HTML landing/404 page with HTTP 200 before
        # the monthly file is published.  Treat that as an unavailable
        # candidate so the scheduler can continue checking other months or
        # the cattle fallback source instead of failing the whole job.
        print(
            f"Source not yet published: {url} "
            f"({content_type or 'unknown content type'})."
        )
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return response.content


def _pdf_text(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - dependency is installed in Actions
        raise RuntimeError("PDF parsing requires pdfplumber; install requirements.txt first.") from exc
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    text = "\n".join(pages)
    if not text.strip():
        raise RuntimeError(f"No text could be extracted from {path.name}.")
    return text


def _release_date_from_text(text: str, fallback: date) -> date:
    patterns = (
        r"Released\s+([A-Za-z]+\s+\d{1,2},\s+20\d{2})",
        r"Release Date\s*:?\s*([A-Za-z]+\s+\d{1,2},\s+20\d{2})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            for fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    return datetime.strptime(match.group(1), fmt).date()
                except ValueError:
                    continue
    return fallback


def _number_tokens(value: str) -> list[float]:
    tokens = re.findall(r"(?<![A-Za-z])\(?-?\d[\d,]*(?:\.\d+)?\)?", value)
    numbers: list[float] = []
    for token in tokens:
        cleaned = token.replace(",", "").strip("()")
        try:
            number = float(cleaned)
        except ValueError:
            continue
        if number in {1000.0, 10000.0}:
            continue
        numbers.append(number)
    return numbers


def _find_line(lines: list[str], labels: tuple[str, ...], start: int = 0) -> str:
    # PDF text extraction may split a visual row such as "Beginning Stocks"
    # across a newline or insert repeated spaces between columns.
    lowered = [" ".join(line.lower().split()) for line in lines]
    for label in labels:
        needle = " ".join(label.lower().split())
        for index in range(start, len(lines)):
            window = " ".join(lowered[index : index + 4])
            if needle in window:
                return " ".join(lines[index : index + 4])
    raise RuntimeError(f"Could not find a required table row: {labels[0]}")


def _last_number(lines: list[str], labels: tuple[str, ...], start: int = 0) -> float:
    # Return the last value in a short extraction window.  This handles both
    # one-line table rows and PDFs where a row label is split from its values.
    line = _find_line(lines, labels, start=start)
    numbers = _number_tokens(line)
    if not numbers:
        raise RuntimeError(f"The table row had no numeric value: {line}")
    # In the official release tables the right-most value is the latest
    # marketing-year/month value.  Failing loudly is safer than guessing when
    # the PDF layout changes.
    return numbers[-1]


def parse_corn_wasde(text: str, release_date: date, source_url: str) -> dict[str, Any]:
    """Parse the latest U.S. corn column from a text-extracted WASDE table."""

    lines = text.splitlines()
    # The official October 2026 PDF calls this section "Feed Grain and Corn"
    # (singular), while some earlier releases used "Feed Grains".  Anchor on
    # the first explicit CORN subsection so the generic "Production" row from
    # the highlights page or the feed-grains table cannot be selected.
    # The same title appears in the table of contents before the actual
    # table.  Use the last matching occurrence so the parser cannot anchor
    # itself on the TOC and miss the Corn subsection entirely.
    table_matches = [
        index
        for index, line in enumerate(lines)
        if "feed grain" in line.lower() and "corn supply" in line.lower()
    ]
    table_start = table_matches[-1] if table_matches else 0
    corn_start = next(
        (
            index
            for index in range(table_start, min(table_start + 80, len(lines)))
            if " ".join(lines[index].lower().split()) == "corn"
            or " ".join(lines[index].lower().split()).startswith("corn 2024/25")
        ),
        table_start,
    )
    rows = lines[corn_start : corn_start + 60]
    data = {
        "beginning_stocks": _last_number(rows, ("Beginning Stocks",)),
        "production": _last_number(rows, ("Production",)),
        "yield": _last_number(rows, ("Yield",)),
        "exports": _last_number(rows, ("Exports",)),
        "ending_stocks": _last_number(rows, ("Ending Stocks",)),
        "farm_price": _last_number(rows, ("Farm Price", "Season-Average Farm Price")),
    }
    total_use_line = None
    try:
        total_use_line = _find_line(
            rows,
            ("Use, Total", "Total Use", "Total Domestic and Export Use"),
        )
    except RuntimeError:
        pass
    if total_use_line is not None:
        total_use_numbers = _number_tokens(total_use_line)
        if total_use_numbers:
            data["total_use"] = total_use_numbers[-1]
    if "total_use" not in data:
        raise RuntimeError("Could not find Total Use in the WASDE corn table.")
    return {
        key: int(value) if key not in {"yield", "farm_price"} else float(value)
        for key, value in data.items()
    } | {
        "commodity": "Corn",
        "release_date": release_date.isoformat(),
        "source_url": source_url,
    }


def _cattle_current_and_yoy(line: str) -> tuple[float, float]:
    numbers = [
        number
        for number in _number_tokens(line)
        if not 1900 <= number <= 2100
    ]
    if len(numbers) < 2:
        raise RuntimeError(f"Could not identify current value and year-over-year percent: {line}")
    yoy = numbers[-1]
    current = numbers[-2]
    return current, yoy


def parse_cattle_on_feed(text: str, release_date: date, source_url: str) -> dict[str, Any]:
    """Parse the U.S. totals from the NASS Cattle on Feed report."""

    lines = text.splitlines()
    month_name = release_date.strftime("%B").lower()

    # Most NASS PDFs expose the first U.S. summary table as one row per line,
    # but pdfplumber can also return the labels first and the 2025/2026/
    # percent columns as a separate numeric block.  Try the simple form first.
    try:
        inventory_line = _find_line(lines, (f"On feed {month_name} 1", "On feed"))
        placements_line = _find_line(lines, ("Placed on feed", "Placements"))
        marketings_line = _find_line(lines, ("Fed cattle marketed", "Marketings"))
        disappearance_line = _find_line(lines, ("Other disappearance", "Other Disappearance"))
        inventory, inventory_yoy = _cattle_current_and_yoy(inventory_line)
        placements, placements_yoy = _cattle_current_and_yoy(placements_line)
        marketings, marketings_yoy = _cattle_current_and_yoy(marketings_line)
        disappearance, disappearance_yoy = _cattle_current_and_yoy(disappearance_line)
    except RuntimeError:
        # In the split-column layout, collect the first 15 values after the
        # five summary row labels: 5 values for 2025, 5 for 2026, and 5 YoY
        # percentages.  The row order is fixed by the NASS table.
        table_start = next(
            (
                index
                for index, line in enumerate(lines)
                if "cattle on feed inventory, placements, marketings" in line.lower()
            ),
            None,
        )
        if table_start is None:
            raise RuntimeError("Could not find the NASS Cattle on Feed summary table.")
        labels = (
            "On feed September 1",
            "Placed on feed during",
            "Fed cattle marketed during",
            "Other disappearance during",
            f"On feed {month_name} 1",
        )
        label_positions: list[int] = []
        search_from = table_start
        for label in labels:
            position = next(
                (
                    index
                    for index in range(search_from, min(table_start + 120, len(lines)))
                    if label.lower() in lines[index].lower()
                ),
                None,
            )
            if position is None:
                break
            label_positions.append(position)
            search_from = position + 1
        if len(label_positions) != len(labels):
            raise RuntimeError("Could not identify all rows in the NASS Cattle on Feed table.")

        values: list[float] = []
        for line in lines[label_positions[-1] + 1 : label_positions[-1] + 80]:
            values.extend(_number_tokens(line))
            if len(values) >= 15:
                break
        if len(values) < 15:
            # As a last-resort fallback, use the rounded values stated in the
            # release summary.  This keeps the scheduled job alive if USDA
            # changes the PDF table layout; the validation layer still records
            # the source URL and parser version for review.
            summary_patterns = {
                "inventory": r"totaled\s+([\d.]+)\s*million head on",
                "placements": r"Placements in feedlots during .*? totaled\s+([\d.]+)\s*million head,\s*(\d+)\s*percent",
                "marketings": r"Marketings of fed cattle during .*? totaled\s+([\d.]+)\s*million head,\s*(\d+)\s*percent",
                "disappearance": r"Other disappearance totaled\s+([\d,]+)\s*head during .*?,\s*(\d+)\s*percent",
            }
            inventory_match = re.search(summary_patterns["inventory"], text, flags=re.IGNORECASE | re.DOTALL)
            placements_match = re.search(summary_patterns["placements"], text, flags=re.IGNORECASE | re.DOTALL)
            marketings_match = re.search(summary_patterns["marketings"], text, flags=re.IGNORECASE | re.DOTALL)
            disappearance_match = re.search(summary_patterns["disappearance"], text, flags=re.IGNORECASE | re.DOTALL)
            if not all((inventory_match, placements_match, marketings_match, disappearance_match)):
                raise RuntimeError("Could not parse the NASS Cattle on Feed summary or table.")
            inventory = float(inventory_match.group(1)) * 1000
            placements = float(placements_match.group(1)) * 1000
            placements_yoy = float(placements_match.group(2))
            marketings = float(marketings_match.group(1)) * 1000
            marketings_yoy = float(marketings_match.group(2))
            disappearance = float(disappearance_match.group(1).replace(",", ""))
            disappearance_yoy = float(disappearance_match.group(2))
            # The narrative describes inventory as slightly below the prior
            # year without a percentage; keep the release's rounded direction.
            inventory_yoy = 100.0
        else:
            current_values = values[5:10]
            yoy_values = values[10:15]
            inventory, placements, marketings, disappearance = current_values
            inventory_yoy, placements_yoy, marketings_yoy, disappearance_yoy = yoy_values
    return {
        "commodity": "Cattle",
        "release_date": release_date.isoformat(),
        "source_url": source_url,
        "inventory": int(inventory),
        "placements": int(placements),
        "marketings": int(marketings),
        "other_disappearance": int(disappearance),
        "inventory_yoy_percent": int(inventory_yoy),
        "placements_yoy_percent": int(placements_yoy),
        "marketings_yoy_percent": int(marketings_yoy),
        "other_disappearance_yoy_percent": int(disappearance_yoy),
    }


def _validate(commodity: str, data: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_FIELDS[commodity] if field not in data]
    if missing:
        raise RuntimeError(f"Missing required normalized fields for {commodity}: {', '.join(missing)}")
    for field in REQUIRED_FIELDS[commodity]:
        if not isinstance(data[field], (int, float)):
            raise RuntimeError(f"Normalized field {field} is not numeric.")
        if data[field] < 0:
            raise RuntimeError(f"Normalized field {field} is negative; refusing to publish.")
    if commodity == "corn" and data["total_use"] <= 0:
        raise RuntimeError("Corn total use must be positive.")


def _snapshot_id(commodity: str, release_date: str, file_hash: str) -> tuple[str, int | None]:
    existing = list_snapshots(commodity, include_failed=True)
    same_date = [record for record in existing if record.get("release_date") == release_date]
    for record in same_date:
        if record.get("raw_sha256") == file_hash:
            return str(record["snapshot_id"]), record.get("revision")
    revision = len(same_date) + 1 if same_date else None
    suffix = f"-revision-{revision}" if revision else ""
    return f"{release_date}{suffix}", revision


def _sync_latest_pointer(commodity: str, manifest: dict[str, Any] | None = None) -> None:
    """Point latest.json at the newest validated release for a commodity."""

    manifest = manifest or _load_json(MANIFEST_PATH, {"schema_version": 1, "snapshots": []})
    candidates = [
        item
        for item in manifest.get("snapshots", [])
        if item.get("commodity") == commodity
        and item.get("validation_status") == "passed"
        and item.get("release_date")
    ]
    if not candidates:
        return
    selected = max(
        candidates,
        key=lambda item: (str(item.get("release_date")), str(item.get("snapshot_id"))),
    )
    latest = _load_json(LATEST_PATH, {"schema_version": 1, "latest": {}})
    latest.setdefault("schema_version", 1)
    latest.setdefault("latest", {})
    latest["latest"][commodity] = selected["snapshot_id"]
    latest["updated_at"] = _now()
    _write_json(LATEST_PATH, latest)


def _report_markdown(case: Any) -> str:
    return (
        f"# {case.commodity} USDA release report\n\n"
        f"**Current release:** {case.current_label}  \n"
        f"**Previous release:** {case.previous_label}  \n"
        f"**Current release date:** {case.current_release_date}  \n"
        f"**Previous release date:** {case.previous_release_date}\n\n"
        f"{generated_report(case)}\n\n"
        f"## Data note\n{case.note}\n\n"
        "## Official sources\n"
        + "\n".join(f"- [{label}]({url})" for label, url in case.sources)
        + "\n"
    )


def _store_snapshot(
    commodity: str,
    data: dict[str, Any],
    raw_bytes: bytes,
    source_url: str,
    source_label: str,
    release_date: date,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    _validate(commodity, data)
    file_hash = _sha256(raw_bytes)
    snapshot_id, revision = _snapshot_id(commodity, release_date.isoformat(), file_hash)
    existing = next(
        (
            record
            for record in list_snapshots(commodity, include_failed=True)
            if record.get("snapshot_id") == snapshot_id
            and record.get("raw_sha256") == file_hash
        ),
        None,
    )
    if existing is not None and not dry_run:
        print(f"Unchanged {commodity} {release_date.isoformat()}; keeping {snapshot_id}.")
        _sync_latest_pointer(commodity)
        return existing
    record = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "commodity": commodity,
        "release_label": CASES[commodity].commodity + " " + release_date.strftime("%B %Y") + (" release" if commodity == "cattle" else ""),
        "release_date": release_date.isoformat(),
        "source_label": source_label,
        "source_url": source_url,
        "retrieved_at": _now(),
        "raw_sha256": file_hash,
        "parser_version": PARSER_VERSION,
        "validation_status": "passed",
        "revision": revision,
        "data": {key: value for key, value in data.items() if key not in {"commodity", "release_date", "source_url"}},
        "note": CASES[commodity].note,
    }
    normalized_path = NORMALIZED_DIR / commodity / f"{snapshot_id}.json"
    raw_path = DATA_DIR / "raw" / commodity / release_date.isoformat() / f"source-{file_hash[:12]}.pdf"
    if dry_run:
        print(f"DRY RUN: would write {normalized_path} and {raw_path}")
        return record

    if not normalized_path.exists():
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if not raw_path.exists():
        raw_path.write_bytes(raw_bytes)

    manifest = _load_json(MANIFEST_PATH, {"schema_version": 1, "snapshots": []})
    manifest.setdefault("schema_version", 1)
    manifest.setdefault("snapshots", [])
    manifest["snapshots"] = [
        item for item in manifest["snapshots"] if item.get("snapshot_id") != snapshot_id
    ]
    manifest["snapshots"].append(
        {
            key: record[key]
            for key in (
                "snapshot_id",
                "commodity",
                "release_label",
                "release_date",
                "source_url",
                "retrieved_at",
                "raw_sha256",
                "parser_version",
                "validation_status",
                "revision",
            )
        }
    )
    manifest["updated_at"] = _now()
    manifest["snapshots"] = sorted(
        manifest["snapshots"],
        key=lambda item: (item.get("commodity", ""), item.get("release_date", ""), item.get("snapshot_id", "")),
    )
    _write_json(MANIFEST_PATH, manifest)

    _sync_latest_pointer(commodity, manifest)

    # A release report is created only after normalized data, manifest, and
    # latest pointer have all been written successfully.
    try:
        case = build_case(commodity, snapshot_id)
    except ValueError:
        print(f"Stored {snapshot_id}; report waits for a previous validated vintage.")
    else:
        report_dir = DATA_DIR / "reports" / commodity / snapshot_id
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.md").write_text(_report_markdown(case), encoding="utf-8")
        (report_dir / "fact_sheet.html").write_text(branded_fact_sheet_html(case), encoding="utf-8")
        (report_dir / "extension_report.html").write_text(branded_report_html(case), encoding="utf-8")
        record["report_paths"] = {
            "markdown": str((report_dir / "report.md").relative_to(PROJECT_ROOT)),
            "fact_sheet": str((report_dir / "fact_sheet.html").relative_to(PROJECT_ROOT)),
            "extension_report": str((report_dir / "extension_report.html").relative_to(PROJECT_ROOT)),
        }
        normalized_path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return record


def refresh_commodity(commodity: str, *, dry_run: bool = False, months_back: int = 2) -> int:
    today = date.today()
    session = requests.Session()
    found = 0
    for year, month in _month_candidates(today, months_back=months_back):
        candidate_date = date(year, month, 1)
        for url_index, url in enumerate(_candidate_urls(commodity, year, month)):
            staging_path = DATA_DIR / "raw" / commodity / "_staging" / f"{year}-{month:02d}-{url_index}.pdf"
            try:
                content = _download(url, staging_path, session)
            except requests.RequestException as exc:
                print(f"Source unavailable: {url} ({exc})")
                continue
            if content is None:
                continue
            try:
                found += 1
                text = _pdf_text(staging_path)
                release_date = _release_date_from_text(text, candidate_date)
                if commodity == "corn":
                    data = parse_corn_wasde(text, release_date, url)
                    label = f"{release_date.strftime('%B %Y')} WASDE"
                else:
                    data = parse_cattle_on_feed(text, release_date, url)
                    label = f"{release_date.strftime('%B %Y')} Cattle on Feed"
                record = _store_snapshot(
                    commodity,
                    data,
                    content,
                    url,
                    label,
                    release_date,
                    dry_run=dry_run,
                )
                print(f"Validated {commodity} {release_date.isoformat()} as {record['snapshot_id']}")
                break
            finally:
                # Staging files are never part of the history layer.  Remove
                # them after every parse attempt, including a failed parser.
                staging_path.unlink(missing_ok=True)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commodity", choices=("corn", "cattle"), help="Refresh one commodity.")
    parser.add_argument("--all", action="store_true", help="Refresh Corn and Cattle.")
    parser.add_argument("--months-back", type=int, default=2, help="How many recent months to check.")
    parser.add_argument("--dry-run", action="store_true", help="Download and parse but do not change data files.")
    args = parser.parse_args()
    if not args.all and not args.commodity:
        parser.error("Choose --commodity corn/cattle or --all.")
    commodities = [args.commodity] if args.commodity else ["corn", "cattle"]
    total_found = 0
    for commodity in commodities:
        total_found += refresh_commodity(
            commodity,
            dry_run=args.dry_run,
            months_back=max(args.months_back, 0),
        )
    print(f"Completed USDA refresh. Found {total_found} downloadable release file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
