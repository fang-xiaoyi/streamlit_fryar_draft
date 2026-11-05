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
    records = list_snapshots(commodity)
    return records[-1] if records else None


def previous_snapshot(commodity: str, snapshot_id: str) -> dict[str, Any] | None:
    records = list_snapshots(commodity)
    selected = next(
        (record for record in records if record.get("snapshot_id") == snapshot_id),
        None,
    )
    if selected is None:
        return None
    # A corrected file for the same release date is a new revision, not the
    # previous economic vintage. Compare it with the latest strictly older
    # release date so revision history does not distort the report.
    older = [
        record
        for record in records
        if str(record.get("release_date", "")) < str(selected.get("release_date", ""))
    ]
    if older:
        return older[-1]
    selected_index = records.index(selected)
    return records[selected_index - 1] if selected_index else None


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

    records = list_snapshots(commodity)
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

