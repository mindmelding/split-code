"""SQLite storage for NHTSA complaints and Jev scores."""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("SPLIT_CODE_DB") or ROOT / "out" / "signals.db")
PROMPT_VERSION = "failure-v1"


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS complaints (
    odi TEXT PRIMARY KEY,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    year TEXT NOT NULL,
    received_date TEXT NOT NULL,
    crash INTEGER NOT NULL,
    fire INTEGER NOT NULL,
    injured INTEGER NOT NULL,
    deaths INTEGER NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS components (
    odi TEXT NOT NULL REFERENCES complaints(odi) ON DELETE CASCADE,
    component TEXT NOT NULL,
    component_root TEXT NOT NULL,
    PRIMARY KEY (odi, component)
);

CREATE TABLE IF NOT EXISTS scores (
    odi TEXT PRIMARY KEY REFERENCES complaints(odi) ON DELETE CASCADE,
    prompt_version TEXT NOT NULL,
    model_used TEXT,
    failure TEXT NOT NULL,
    failure_confidence REAL NOT NULL,
    failure_probability REAL,
    outside_filed_code REAL NOT NULL,
    severity REAL NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    scored_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_complaints_vehicle
    ON complaints(make, model, year);
CREATE INDEX IF NOT EXISTS idx_complaints_received
    ON complaints(received_date);
CREATE INDEX IF NOT EXISTS idx_complaints_crash
    ON complaints(crash);
CREATE INDEX IF NOT EXISTS idx_complaints_fire
    ON complaints(fire);
CREATE INDEX IF NOT EXISTS idx_components_root
    ON components(component_root, odi);
CREATE INDEX IF NOT EXISTS idx_scores_failure
    ON scores(failure, failure_confidence, severity);
"""


def connect(readonly: bool = False) -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    if not readonly:
        connection.executescript(SCHEMA)
    return connection


def component_root(name: str) -> str:
    return name.split(":")[0].strip()


def _integer(value: str) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def import_nhtsa(path: Path) -> int:
    """Import eligible vehicle complaints. Safe to run repeatedly."""
    complaints: dict[str, tuple] = {}
    components: set[tuple[str, str, str]] = set()
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) < 46 or row[45] != "V":
                continue
            if row[3] in ("", "UNKNOWN") or len(row[19].strip()) < 40:
                continue
            odi = row[1]
            complaints.setdefault(
                odi,
                (
                    odi,
                    row[3].strip(),
                    row[4].strip(),
                    row[5].strip(),
                    row[16],
                    int(row[6] == "Y"),
                    int(row[8] == "Y"),
                    _integer(row[9]),
                    _integer(row[10]),
                    row[19].strip(),
                ),
            )
            component = row[11].strip()
            if component:
                components.add((odi, component, component_root(component)))

    connection = connect()
    try:
        connection.executemany(
            """
            INSERT INTO complaints (
                odi, make, model, year, received_date, crash, fire,
                injured, deaths, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(odi) DO UPDATE SET
                make=excluded.make,
                model=excluded.model,
                year=excluded.year,
                received_date=excluded.received_date,
                crash=excluded.crash,
                fire=excluded.fire,
                injured=excluded.injured,
                deaths=excluded.deaths,
                description=excluded.description
            """,
            complaints.values(),
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO components (odi, component, component_root)
            VALUES (?, ?, ?)
            """,
            components,
        )
        connection.commit()
    finally:
        connection.close()
    return len(complaints)


def migrate_jsonl(path: Path) -> int:
    """Bring the original MVP scores into SQLite."""
    if not path.exists():
        return 0
    rows = []
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            score = json.loads(line)
            usage = score.get("usage") or {}
            rows.append(
                (
                    score["odi"],
                    PROMPT_VERSION,
                    score.get("model_used"),
                    score["failure"],
                    score["failure_confidence"],
                    score.get("failure_probability"),
                    score["outside_filed_code"],
                    score["severity"],
                    int(usage.get("input_tokens") or 0),
                    int(usage.get("output_tokens") or 0),
                )
            )
    connection = connect()
    try:
        connection.executemany(
            """
            INSERT INTO scores (
                odi, prompt_version, model_used, failure, failure_confidence,
                failure_probability, outside_filed_code, severity,
                input_tokens, output_tokens
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(odi) DO NOTHING
            """,
            rows,
        )
        connection.commit()
    finally:
        connection.close()
    return len(rows)
