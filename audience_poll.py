"""Shared state for the live audience interaction prototype.

The Streamlit app has three presentation surfaces:

* ``?mode=audience`` - a phone-friendly response page;
* ``?mode=screen`` - a presenter dashboard that refreshes automatically;
* the default ``lab`` mode - the existing producer decision tool.

SQLite is intentionally used for this first local/deployed prototype because
it is dependency-light and lets multiple Streamlit sessions share responses.
For a multi-instance production deployment, replace this small module with a
managed Postgres/Supabase backend.
"""

from __future__ import annotations

import io
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


POLL_ID = "stakeholder-demo"

POLL_PRESETS: dict[str, dict[str, Any]] = {
    "decision": {
        "label": "1 · Decision context",
        "question": "What is the biggest financial decision facing your operation right now?",
        "options": [
            "Sell / market cattle now",
            "Hold cattle longer",
            "Retain heifers / expand",
            "Manage cash flow, feed, or forage",
            "Protect the downside",
            "Other / write my own",
        ],
    },
    "profit": {
        "label": "2 · Profit question",
        "question": "Can I still make money at these prices?",
        "options": [
            "Yes, based on my current records",
            "I am not sure yet",
            "Only if production goes as planned",
            "My costs are too high at these prices",
            "Other / write my own",
        ],
    },
    "cost": {
        "label": "3 · Cost question",
        "question": "What does it really cost to carry a cow?",
        "options": [
            "I know my cost fairly well",
            "Feed and forage are the main issue",
            "Land, labor, or equipment are easy to miss",
            "I need a better record system",
            "Other / write my own",
        ],
    },
    "protection": {
        "label": "4 · Risk question",
        "question": "How do I protect the downside without giving up the upside?",
        "options": [
            "LRP / livestock insurance",
            "Put options",
            "Futures or forward contracts",
            "Stage the decision over time",
            "I need more information first",
            "Other / write my own",
        ],
    },
}


def _db_path() -> Path:
    configured = os.getenv("FRYAR_POLL_DB")
    return Path(configured) if configured else Path(__file__).with_name("audience_poll.sqlite3")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path(), timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def init_database() -> None:
    """Create the small shared store and seed the first presentation prompt."""

    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS poll_state (
                poll_id TEXT PRIMARY KEY,
                prompt_id TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS responses (
                poll_id TEXT NOT NULL,
                prompt_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                option TEXT NOT NULL,
                custom_text TEXT DEFAULT '',
                submitted_at TEXT NOT NULL,
                PRIMARY KEY (poll_id, prompt_id, session_id)
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO poll_state (poll_id, prompt_id, updated_at)
            VALUES (?, ?, ?)
            """,
            (POLL_ID, "decision", _now()),
        )


def active_prompt_id() -> str:
    init_database()
    with _connect() as connection:
        row = connection.execute(
            "SELECT prompt_id FROM poll_state WHERE poll_id = ?", (POLL_ID,)
        ).fetchone()
    prompt_id = row["prompt_id"] if row else "decision"
    return prompt_id if prompt_id in POLL_PRESETS else "decision"


def active_prompt() -> dict[str, Any]:
    prompt_id = active_prompt_id()
    return {"id": prompt_id, **POLL_PRESETS[prompt_id]}


def set_active_prompt(prompt_id: str, *, clear_responses: bool = True) -> None:
    if prompt_id not in POLL_PRESETS:
        raise ValueError(f"Unknown prompt: {prompt_id}")
    init_database()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE poll_state SET prompt_id = ?, updated_at = ? WHERE poll_id = ?
            """,
            (prompt_id, _now(), POLL_ID),
        )
        if clear_responses:
            connection.execute(
                "DELETE FROM responses WHERE poll_id = ? AND prompt_id = ?",
                (POLL_ID, prompt_id),
            )


def submit_response(
    session_id: str, option: str, custom_text: str = "", prompt_id: str | None = None
) -> None:
    init_database()
    prompt = prompt_id or active_prompt_id()
    valid_options = POLL_PRESETS[prompt]["options"]
    if option not in valid_options:
        raise ValueError("The selected option is not part of the active prompt.")
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO responses
                (poll_id, prompt_id, session_id, option, custom_text, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (poll_id, prompt_id, session_id)
            DO UPDATE SET option = excluded.option,
                          custom_text = excluded.custom_text,
                          submitted_at = excluded.submitted_at
            """,
            (POLL_ID, prompt, session_id, option, custom_text.strip(), _now()),
        )


def response_counts(prompt_id: str | None = None) -> dict[str, int]:
    init_database()
    prompt = prompt_id or active_prompt_id()
    counts = {option: 0 for option in POLL_PRESETS[prompt]["options"]}
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT option, COUNT(*) AS n
            FROM responses
            WHERE poll_id = ? AND prompt_id = ?
            GROUP BY option
            """,
            (POLL_ID, prompt),
        ).fetchall()
    for row in rows:
        counts[row["option"]] = int(row["n"])
    return counts


def response_total(prompt_id: str | None = None) -> int:
    return sum(response_counts(prompt_id).values())


def recent_custom_responses(prompt_id: str | None = None, limit: int = 10) -> list[str]:
    init_database()
    prompt = prompt_id or active_prompt_id()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT custom_text
            FROM responses
            WHERE poll_id = ? AND prompt_id = ? AND TRIM(custom_text) <> ''
            ORDER BY submitted_at DESC LIMIT ?
            """,
            (POLL_ID, prompt, limit),
        ).fetchall()
    return [str(row["custom_text"]) for row in rows]


def clear_responses(prompt_id: str | None = None) -> None:
    init_database()
    prompt = prompt_id or active_prompt_id()
    with _connect() as connection:
        connection.execute(
            "DELETE FROM responses WHERE poll_id = ? AND prompt_id = ?",
            (POLL_ID, prompt),
        )


def make_qr_bytes(url: str) -> bytes:
    """Return a PNG QR code; imported lazily so the core lab stays lightweight."""

    import qrcode

    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#102a43", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

