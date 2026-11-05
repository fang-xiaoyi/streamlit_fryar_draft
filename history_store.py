"""Read-only helpers for the versioned USDA release store.

The Streamlit app only reads validated snapshots.  The scheduled refresh job
is responsible for downloading files, writing new snapshots, and updating the
manifest/latest pointers.  Keeping writes out of the app prevents a browser
rerun from overwriting history or creating duplicate releases.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from usda_report_pipeline import CASES, ReleaseCase


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
NORMALIZED_DIR = DATA_DIR / "normalized"
MANIFEST_PATH = DATA_DIR / "manifest.json"
LATEST_PATH = DATA_DIR / "latest.json"


# The catalog is intentionally broader than the currently seeded/validated
# release store. This lets the app expose the product roadmap without
# pretending that every commodity already has a parser and historical pair.
COMMODITY_CATALOG: dict[str, dict[str, str]] = {
    "corn": {
        "label": "Corn — WASDE",
        "status": "validated",
        "source_family": "USDA WASDE",
    },
    "cattle": {
        "label": "Cattle — Cattle on Feed",
        "status": "validated",
        "source_family": "USDA Cattle on Feed",
    },
    "soybeans": {
        "label": "Soybeans — WASDE (planned)",
        "status": "planned",
        "source_family": "USDA WASDE",
    },
    "wheat": {
        "label": "Wheat — WASDE (planned)",
        "status": "planned",
        "source_family": "USDA WASDE",
    },
    "cotton": {
        "label": "Cotton — WASDE (planned)",
        "status": "planned",
        "source_family": "USDA WASDE",
    },
    "rice": {
        "label": "Rice — WASDE (planned)",
        "status": "planned",
        "source_family": "USDA WASDE",
    },
    "hogs": {
        "label": "Hogs — Hogs and Pigs (planned)",
        "status": "planned",
        "source_family": "USDA NASS Hogs and Pigs",
    },
    "broilers": {
        "label": "Broilers — poultry outlook (planned)",
        "status": "planned",
        "source_family": "USDA poultry reports",
    },
    "milk": {
        "label": "Milk — Milk Production (planned)",
        "status": "planned",
        "source_family": "USDA NASS Milk Production",
    },
}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def load_manifest() -> dict[str, Any]:
    payload = _read_json(MANIFEST_PATH, {})
    return payload if isinstance(payload, dict) else {}


def load_latest() -> dict[str, Any]:
    payload = _read_json(LATEST_PATH, {})
    return payload if isinstance(payload, dict) else {}


def list_snapshots(
    commodity: str | None = None,
    *,
    include_failed: bool = False,
) -> list[dict[str, Any]]:
    """Return validated snapshots sorted from oldest to newest.

    The normalized JSON file is the source of truth for the app.  The manifest
    is useful metadata, but the page can still show a snapshot if a manifest
    update was interrupted after the normalized file was written.
    """

    directories = [NORMALIZED_DIR / commodity] if commodity else sorted(
        path for path in NORMALIZED_DIR.glob("*") if path.is_dir()
    )
    records: list[dict[str, Any]] = []
    for directory in directories:
        for path in sorted(directory.glob("*.json")):
            payload = _read_json(path, None)
            if not isinstance(payload, dict):
                continue
            if not include_failed and payload.get("validation_status", "passed") != "passed":
                continue
            payload.setdefault("snapshot_id", path.stem)
            payload.setdefault("commodity", directory.name)
            payload["_path"] = str(path)
            records.append(payload)
    return sorted(
        records,
        key=lambda item: (str(item.get("release_date", "")), str(item.get("snapshot_id", ""))),
    )


def _release_period(record: dict[str, Any]) -> str:
    """Return the YYYY-MM vintage period used for release comparisons."""

    release_date = str(record.get("release_date", ""))
    return release_date[:7]


def _monthly_vintages(commodity: str) -> list[dict[str, Any]]:
    """Collapse same-month duplicates/revisions to one reportable vintage.

    Raw revisions remain in ``data/normalized`` and the manifest.  The app,
    however, should compare one monthly release with the prior month rather
    than comparing a release with another copy/revision from the same month.
    The newest snapshot ID within a month is the representative record.
    """

    grouped: dict[str, dict[str, Any]] = {}
    for record in list_snapshots(commodity):
        period = _release_period(record)
        if not period:
            continue
        current = grouped.get(period)
        if current is None or (
            str(record.get("release_date", "")),
            str(record.get("snapshot_id", "")),
        ) > (
            str(current.get("release_date", "")),
            str(current.get("snapshot_id", "")),
        ):
            grouped[period] = record
    return sorted(
        grouped.values(),
        key=lambda item: (str(item.get("release_date", "")), str(item.get("snapshot_id", ""))),
    )


def get_snapshot(commodity: str, snapshot_id: str) -> dict[str, Any]:
    for record in list_snapshots(commodity, include_failed=True):
        if record.get("snapshot_id") == snapshot_id:
            return record
    raise KeyError(f"Unknown USDA snapshot: {commodity}/{snapshot_id}")


def latest_snapshot(commodity: str) -> dict[str, Any] | None:
    """Return the latest pointer when valid, otherwise use the newest file."""

    pointer = load_latest().get("latest", {})
    snapshot_id = pointer.get(commodity) if isinstance(pointer, dict) else None
    if snapshot_id:
        try:
            return get_snapshot(commodity, str(snapshot_id))
        except KeyError:
            pass
    records = _monthly_vintages(commodity)
    return records[-1] if records else None


def previous_snapshot(commodity: str, snapshot_id: str) -> dict[str, Any] | None:
    records = list_snapshots(commodity)
    selected = next(
        (record for record in records if record.get("snapshot_id") == snapshot_id),
        None,
    )
    if selected is None:
        return None
    # A corrected file or a second source record from the same month is not a
    # previous economic vintage. Compare with the latest representative from
    # the strictly older YYYY-MM release period.
    vintages = _monthly_vintages(commodity)
    selected_period = _release_period(selected)
    older = [record for record in vintages if _release_period(record) < selected_period]
    return older[-1] if older else None


def _source_tuple(record: dict[str, Any]) -> tuple[str, str]:
    label = str(record.get("source_label") or record.get("release_label") or "Official USDA release")
    url = str(record.get("source_url") or "")
    return label, url


def build_case(commodity: str, snapshot_id: str) -> ReleaseCase:
    """Build the existing report model from two versioned snapshots."""

    current_record = get_snapshot(commodity, snapshot_id)
    prior_record = previous_snapshot(commodity, snapshot_id)
    if prior_record is None:
        raise ValueError(
            f"The {commodity} snapshot {snapshot_id} has no previous release yet."
        )

    schedule = CASES[commodity]
    current_label = str(current_record.get("release_label", current_record["release_date"]))
    previous_label = str(prior_record.get("release_label", prior_record["release_date"]))
    sources = (_source_tuple(current_record), _source_tuple(prior_record))
    note = str(current_record.get("note") or schedule.note)
    note += (
        f" Snapshot {current_record['snapshot_id']} was validated by parser "
        f"{current_record.get('parser_version', 'unknown')} and is retained as a "
        "release-specific vintage."
    )
    return ReleaseCase(
        key=commodity,
        commodity=schedule.commodity,
        report=schedule.report,
        current_label=current_label,
        previous_label=previous_label,
        current_release_date=str(current_record["release_date"]),
        previous_release_date=str(prior_record["release_date"]),
        current=dict(current_record.get("data", {})),
        previous=dict(prior_record.get("data", {})),
        sources=sources,
        next_release_label=schedule.next_release_label,
        next_release_date=schedule.next_release_date,
        next_release_url=schedule.next_release_url,
        note=note,
    )


def case_records(commodity: str) -> list[dict[str, Any]]:
    """Return snapshots that have a prior vintage and can produce a report."""

    records = _monthly_vintages(commodity)
    if len(records) < 2:
        return []
    return records[1:]


def format_snapshot_option(record: dict[str, Any], latest_id: str | None) -> str:
    label = str(record.get("release_label", record.get("release_date", "Unknown release")))
    release_date = str(record.get("release_date", ""))
    marker = "Latest validated release" if record.get("snapshot_id") == latest_id else "Historical release"
    revision = record.get("revision")
    suffix = f" · revision {revision}" if revision else ""
    return f"{marker} — {label} ({release_date}){suffix}"
