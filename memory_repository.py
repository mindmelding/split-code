"""Low-latency analytical snapshot backed by the SQLite score store."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import time

from repository import HEADLINES, parse_filters
from storage import connect
from vehicle_types import BODY_LABELS, classify

_RECORDS: list[dict] | None = None
_FACETS: dict | None = None
_MAXIMUM_DATE = ""
_COVERAGE_END = ""
_BY_KEY: dict[tuple, list[dict]] = {}
WEEKS = 26


def load_snapshot() -> int:
    global _RECORDS, _FACETS, _MAXIMUM_DATE, _COVERAGE_END, _BY_KEY
    connection = connect(readonly=True)
    try:
        first_pending = connection.execute(
            """
            SELECT MIN(c.received_date)
            FROM complaints c LEFT JOIN scores s ON s.odi = c.odi
            WHERE s.odi IS NULL
            """
        ).fetchone()[0]
        if first_pending:
            _COVERAGE_END = (
                datetime.strptime(first_pending, "%Y%m%d") - timedelta(days=1)
            ).strftime("%Y%m%d")
        else:
            _COVERAGE_END = connection.execute(
                "SELECT MAX(received_date) FROM complaints"
            ).fetchone()[0]
        component_map: dict[str, set[str]] = defaultdict(set)
        for row in connection.execute(
            """
            SELECT k.odi, k.component_root
            FROM components k
            JOIN scores s ON s.odi = k.odi
            JOIN complaints c ON c.odi = k.odi
            WHERE c.received_date <= ?
            """,
            (_COVERAGE_END,),
        ):
            component_map[row["odi"]].add(row["component_root"])
        records = []
        for row in connection.execute(
            """
            SELECT
                c.odi, c.make, c.model, c.year,
                c.received_date AS ldate, c.crash, c.fire,
                c.injured, c.deaths, c.description AS desc,
                s.failure, s.failure_confidence, s.failure_probability,
                s.outside_filed_code, s.severity
            FROM complaints c JOIN scores s ON s.odi = c.odi
            WHERE c.received_date <= ?
            """,
            (_COVERAGE_END,),
        ):
            item = dict(row)
            item["crash"] = bool(item["crash"])
            item["fire"] = bool(item["fire"])
            item["components"] = component_map.get(item["odi"], set())
            item["body"], item["powertrain"] = classify(item["make"], item["model"])
            item["vehicle"] = f"{item['year']} {item['make']} {item['model']}"
            item["vehicle_lower"] = item["vehicle"].lower()
            item["day"] = datetime.strptime(item["ldate"], "%Y%m%d").toordinal()
            records.append(item)
        records.sort(key=lambda item: item["ldate"])
        _RECORDS = records
        by_key: dict[tuple, list[dict]] = defaultdict(list)
        for item in records:
            if item["failure"] != "other" and item["failure_confidence"] >= 0.35:
                by_key[(item["make"], item["model"], item["year"], item["failure"])].append(item)
        _BY_KEY = by_key
        _MAXIMUM_DATE = records[-1]["ldate"] if records else ""
        _FACETS = _build_facets(records)
        return len(records)
    finally:
        connection.close()


def _tally(records: list[dict], key: str) -> list[dict]:
    counts = Counter(record[key] for record in records)
    return [
        {"id": item, "count": count}
        for item, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def _build_facets(records: list[dict]) -> dict:
    components = Counter()
    for record in records:
        components.update(record["components"])
    failures = _tally(records, "failure")
    for row in failures:
        row["label"] = HEADLINES.get(row["id"], row["id"])
    bodies = _tally(records, "body")
    for row in bodies:
        row["label"] = BODY_LABELS.get(row["id"], row["id"])
    vehicles = Counter((r["make"], r["model"]) for r in records)
    return {
        "failures": failures,
        "bodies": bodies,
        "vehicles": [
            f"{make} {model}".title()
            for (make, model), _count in vehicles.most_common(400)
        ],
        "makes": _tally(records, "make"),
        "models": _tally(records, "model"),
        "years": _tally(records, "year"),
        "components": [
            {"id": item, "count": count}
            for item, count in sorted(
                components.items(), key=lambda pair: (-pair[1], pair[0])
            )
        ],
    }


def _weekly(key: tuple) -> list[dict]:
    """Complaints per week for the last WEEKS weeks, oldest first, with filed codes."""
    end = datetime.strptime(_MAXIMUM_DATE, "%Y%m%d")
    end_day = end.toordinal()
    bins = [{"n": 0, "filed": Counter()} for _ in range(WEEKS)]
    for record in _BY_KEY.get(key, []):
        weeks_ago = (end_day - record["day"]) // 7
        if 0 <= weeks_ago < WEEKS:
            bucket = bins[WEEKS - 1 - weeks_ago]
            bucket["n"] += 1
            bucket["filed"].update(record["components"])
    out = []
    for index, bucket in enumerate(bins):
        start = end - timedelta(days=7 * (WEEKS - 1 - index) + 6)
        out.append({"start": start.strftime("%Y%m%d"), "n": bucket["n"], "filed": dict(bucket["filed"])})
    return out


def _matches(record: dict, filters: dict, window_cutoff: str | None) -> bool:
    if filters["failures"] and record["failure"] not in filters["failures"]:
        return False
    if filters["body"] and record["body"] != filters["body"]:
        return False
    if filters["vehicle"] and not all(
        term in record["vehicle_lower"] for term in filters["vehicle"]
    ):
        return False
    for key in ("failure", "make", "model", "year"):
        if filters[key] and record[key] != filters[key]:
            return False
    if filters["component"] and filters["component"] not in record["components"]:
        return False
    if filters["min_severity"] and record["severity"] < filters["min_severity"]:
        return False
    if filters["min_confidence"] and record["failure_confidence"] < filters["min_confidence"]:
        return False
    if filters["crashes"] and not record["crash"]:
        return False
    if filters["fires"] and not record["fire"]:
        return False
    if window_cutoff and record["ldate"] < window_cutoff:
        return False
    if filters["q"]:
        term = filters["q"].lower()
        if term != record["odi"] and term not in record["desc"].lower():
            return False
    return True


def query(params: dict[str, list[str]]) -> dict:
    started = time.perf_counter()
    if _RECORDS is None:
        load_snapshot()
    records = _RECORDS or []
    filters = parse_filters(params)
    filters["body"] = (params.get("body") or [""])[0].strip()
    filters["vehicle"] = (params.get("vehicle") or [""])[0].strip().lower().split()
    filters["failures"] = {
        item for item in (params.get("failures") or [""])[0].split(",") if item.strip()
    }
    latest = datetime.strptime(_MAXIMUM_DATE, "%Y%m%d")
    current_cutoff = (latest - timedelta(days=29)).strftime("%Y%m%d")
    prior_cutoff = (latest - timedelta(days=59)).strftime("%Y%m%d")
    window_cutoff = None
    if filters["window"] != "all":
        window_cutoff = (
            latest - timedelta(days=int(filters["window"]) - 1)
        ).strftime("%Y%m%d")
    matched = [record for record in records if _matches(record, filters, window_cutoff)]

    active = any(
        [
            filters["body"],
            filters["vehicle"],
            filters["failures"],
            filters["failure"],
            filters["make"],
            filters["model"],
            filters["year"],
            filters["component"],
            filters["q"],
            filters["min_severity"],
            filters["min_confidence"],
            filters["crashes"],
            filters["fires"],
        ]
    )
    minimum = 2 if active else 5
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for record in matched:
        if record["failure"] == "other" or record["failure_confidence"] < 0.35:
            continue
        grouped[
            (
                record["make"],
                record["model"],
                record["year"],
                record["failure"],
            )
        ].append(record)

    clusters = []
    for (make, model, year, failure), rows in grouped.items():
        if len(rows) < minimum:
            continue
        component_counts = Counter()
        for row in rows:
            component_counts.update(row["components"])
        if len(component_counts) < 2:
            continue
        current_count = sum(row["ldate"] >= current_cutoff for row in rows)
        prior_count = sum(
            prior_cutoff <= row["ldate"] < current_cutoff for row in rows
        )
        examples = []
        for row in sorted(
            rows,
            key=lambda item: (item["ldate"], item["severity"]),
            reverse=True,
        )[:3]:
            examples.append(
                {
                    "odi": row["odi"],
                    "ldate": row["ldate"],
                    "severity": round(row["severity"], 2),
                    "crash": row["crash"],
                    "fire": row["fire"],
                    "desc": row["desc"],
                    "components": sorted(row["components"]),
                }
            )
        clusters.append(
            {
                "vehicle": f"{year} {make} {model}",
                "make": make,
                "model": model,
                "year": year,
                "body": rows[0]["body"],
                "powertrain": rows[0]["powertrain"],
                "failure": failure,
                "headline": HEADLINES.get(failure, failure),
                "failure_label": HEADLINES.get(failure, failure),
                "count": len(rows),
                "first": rows[0]["ldate"],
                "last": rows[-1]["ldate"],
                "mean_confidence": round(
                    sum(row["failure_confidence"] for row in rows) / len(rows), 2
                ),
                "mean_severity": round(
                    sum(row["severity"] for row in rows) / len(rows), 2
                ),
                "outside_filed_share": round(
                    sum(row["outside_filed_code"] >= 0.6 for row in rows) / len(rows),
                    2,
                ),
                "crashes": sum(row["crash"] for row in rows),
                "fires": sum(row["fire"] for row in rows),
                "current_count": current_count,
                "prior_count": prior_count,
                "momentum": current_count - prior_count,
                "filed_components": [
                    {"name": name, "count": count}
                    for name, count in component_counts.most_common(6)
                ],
                "examples": examples,
            }
        )

    sorters = {
        "momentum": lambda row: (
            row["momentum"],
            row["current_count"],
            row["count"],
        ),
        "volume": lambda row: (row["count"], row["mean_severity"]),
        "severity": lambda row: (row["mean_severity"], row["count"]),
        "newest": lambda row: (row["last"], row["current_count"]),
    }
    clusters.sort(key=sorters[filters["sort"]], reverse=True)
    clusters = clusters[:40]
    for cluster in clusters:
        cluster["weekly"] = _weekly(
            (cluster["make"], cluster["model"], cluster["year"], cluster["failure"])
        )
    stats = {
        "clusters": len(clusters),
        "complaints": len(matched),
        "crashes": sum(row["crash"] for row in matched),
        "fires": sum(row["fire"] for row in matched),
        "mean_severity": round(
            sum(row["severity"] for row in matched) / len(matched), 2
        )
        if matched
        else 0,
    }
    include_facets = (params.get("include_facets") or ["1"])[0] != "0"
    return {
        "meta": {
            "scored": len(records),
            "matched": len(matched),
            "minimum_cluster": minimum,
            "source": (
                "NHTSA ODI complaints received in 2025–2026; "
                f"complete through {_COVERAGE_END}"
            ),
            "model": "jev-1.13.0",
            "maximum_date": _MAXIMUM_DATE,
            "current_cutoff": current_cutoff,
            "prior_cutoff": prior_cutoff,
            "coverage_complete_through": _COVERAGE_END,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        },
        "stats": stats,
        "facets": _FACETS if include_facets else None,
        "clusters": clusters,
    }
