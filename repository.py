"""Fast, filterable reads from the scored complaint database."""

from __future__ import annotations

from datetime import datetime, timedelta
import time

from storage import connect

HEADLINES = {
    "idle_stop_no_restart": "It will not restart",
    "stall_while_moving": "It stalls while moving",
    "wont_start_when_parked": "It will not start",
    "unintended_acceleration": "It accelerates on its own",
    "brake_failure": "The brakes do not hold",
    "stuck_gear_or_rollaway": "It will not take a gear",
    "steering_assist_loss": "The steering goes heavy",
    "pull_shake_or_vibration": "It pulls or shakes",
    "unwanted_driver_assist": "The assist acts alone",
    "restraint_fault": "The restraint fails",
    "fire_smoke_or_burning": "Smoke or fire",
    "leak": "Something is leaking",
    "wheel_or_tire": "A wheel or tire lets go",
    "body_or_latch": "A part leaves the vehicle",
    "lighting_or_visibility": "The driver cannot see",
    "other": "Unsorted",
}

_FACETS_CACHE: dict | None = None


def parse_filters(params: dict[str, list[str]]) -> dict:
    def first(name: str) -> str:
        return (params.get(name) or [""])[0].strip()

    severity = first("min_severity")
    confidence = first("min_confidence")
    window = first("window") or "90"
    return {
        "failure": first("failure"),
        "make": first("make"),
        "model": first("model"),
        "year": first("year"),
        "component": first("component"),
        "q": first("q"),
        "min_severity": float(severity) if severity else 0.0,
        "min_confidence": float(confidence) if confidence else 0.0,
        "crashes": first("crashes") in ("1", "true", "yes"),
        "fires": first("fires") in ("1", "true", "yes"),
        "window": window if window in ("30", "90", "365", "all") else "90",
        "sort": first("sort") if first("sort") in ("momentum", "volume", "severity", "newest") else "momentum",
    }


def _where(filters: dict, maximum_date: str) -> tuple[str, list]:
    conditions = ["1=1"]
    values: list = []
    pairs = [
        ("s.failure", filters["failure"]),
        ("c.make", filters["make"]),
        ("c.model", filters["model"]),
        ("c.year", filters["year"]),
    ]
    for column, value in pairs:
        if value:
            conditions.append(f"{column} = ?")
            values.append(value)
    if filters["min_severity"]:
        conditions.append("s.severity >= ?")
        values.append(filters["min_severity"])
    if filters["min_confidence"]:
        conditions.append("s.failure_confidence >= ?")
        values.append(filters["min_confidence"])
    if filters["crashes"]:
        conditions.append("c.crash = 1")
    if filters["fires"]:
        conditions.append("c.fire = 1")
    if filters["q"]:
        conditions.append("(c.description LIKE ? OR c.odi = ?)")
        values.extend([f"%{filters['q']}%", filters["q"]])
    if filters["component"]:
        conditions.append(
            "EXISTS (SELECT 1 FROM components x "
            "WHERE x.odi = c.odi AND x.component_root = ?)"
        )
        values.append(filters["component"])
    if filters["window"] != "all":
        cutoff = (
            datetime.strptime(maximum_date, "%Y%m%d")
            - timedelta(days=int(filters["window"]) - 1)
        ).strftime("%Y%m%d")
        conditions.append("c.received_date >= ?")
        values.append(cutoff)
    return " AND ".join(conditions), values


def _facets(connection) -> dict:
    global _FACETS_CACHE
    if _FACETS_CACHE is not None:
        return _FACETS_CACHE

    def tally(column: str) -> list[dict]:
        return [
            {"id": row["id"], "count": row["count"]}
            for row in connection.execute(
                f"""
                SELECT {column} AS id, COUNT(*) AS count
                FROM complaints c JOIN scores s ON s.odi = c.odi
                GROUP BY {column}
                ORDER BY count DESC, id
                """
            )
        ]

    failures = tally("s.failure")
    for row in failures:
        row["label"] = HEADLINES.get(row["id"], row["id"])
    components = [
        {"id": row["id"], "count": row["count"]}
        for row in connection.execute(
            """
            SELECT k.component_root AS id, COUNT(DISTINCT k.odi) AS count
            FROM components k JOIN scores s ON s.odi = k.odi
            GROUP BY k.component_root
            ORDER BY count DESC, id
            """
        )
    ]
    _FACETS_CACHE = {
        "failures": failures,
        "makes": tally("c.make"),
        "models": tally("c.model"),
        "years": tally("c.year"),
        "components": components,
    }
    return _FACETS_CACHE


def query(params: dict[str, list[str]]) -> dict:
    started = time.perf_counter()
    connection = connect(readonly=True)
    try:
        maximum_date = connection.execute(
            """
            SELECT MAX(c.received_date)
            FROM complaints c JOIN scores s ON s.odi = c.odi
            """
        ).fetchone()[0]
        filters = parse_filters(params)
        where, values = _where(filters, maximum_date)
        latest = datetime.strptime(maximum_date, "%Y%m%d")
        current_cutoff = (latest - timedelta(days=29)).strftime("%Y%m%d")
        prior_cutoff = (latest - timedelta(days=59)).strftime("%Y%m%d")

        stats = dict(
            connection.execute(
                f"""
                SELECT
                    COUNT(*) AS complaints,
                    SUM(c.crash) AS crashes,
                    SUM(c.fire) AS fires,
                    COALESCE(AVG(s.severity), 0) AS mean_severity
                FROM complaints c JOIN scores s ON s.odi = c.odi
                WHERE {where}
                """,
                values,
            ).fetchone()
        )
        minimum = 5 if not any(
            [
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
        ) else 2
        order = {
            "momentum": "momentum DESC, current_count DESC, count DESC",
            "volume": "count DESC, mean_severity DESC",
            "severity": "mean_severity DESC, count DESC",
            "newest": "last DESC, current_count DESC",
        }[filters["sort"]]
        cluster_rows = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT
                    c.make, c.model, c.year, s.failure,
                    COUNT(*) AS count,
                    MIN(c.received_date) AS first,
                    MAX(c.received_date) AS last,
                    AVG(s.failure_confidence) AS mean_confidence,
                    AVG(s.severity) AS mean_severity,
                    AVG(CASE WHEN s.outside_filed_code >= 0.6 THEN 1.0 ELSE 0.0 END)
                        AS outside_filed_share,
                    SUM(c.crash) AS crashes,
                    SUM(c.fire) AS fires,
                    SUM(CASE WHEN c.received_date >= ? THEN 1 ELSE 0 END)
                        AS current_count,
                    SUM(CASE WHEN c.received_date >= ? AND c.received_date < ? THEN 1 ELSE 0 END)
                        AS prior_count,
                    (
                        SUM(CASE WHEN c.received_date >= ? THEN 1 ELSE 0 END)
                        - SUM(CASE WHEN c.received_date >= ? AND c.received_date < ? THEN 1 ELSE 0 END)
                    ) AS momentum
                FROM complaints c JOIN scores s ON s.odi = c.odi
                WHERE {where}
                    AND s.failure != 'other'
                    AND s.failure_confidence >= 0.35
                GROUP BY c.make, c.model, c.year, s.failure
                HAVING count >= ?
                ORDER BY {order}
                LIMIT 40
                """,
                [
                    current_cutoff,
                    prior_cutoff,
                    current_cutoff,
                    current_cutoff,
                    prior_cutoff,
                    current_cutoff,
                    *values,
                    minimum,
                ],
            )
        ]

        cluster_keys = {
            (row["make"], row["model"], row["year"], row["failure"])
            for row in cluster_rows
        }
        selected_values = [
            value
            for key in cluster_keys
            for value in key
        ]
        if cluster_keys:
            selected_rows = ", ".join(["(?, ?, ?, ?)"] * len(cluster_keys))
        else:
            selected_rows = "(?, ?, ?, ?)"
            selected_values = [None, None, None, None]
        components_by_cluster: dict[tuple, list[dict]] = {}
        for item in connection.execute(
            f"""
            WITH selected(make, model, year, failure) AS (
                VALUES {selected_rows}
            )
            SELECT
                c.make, c.model, c.year, s.failure,
                k.component_root AS name,
                COUNT(DISTINCT c.odi) AS count
            FROM selected z
            JOIN complaints c
                ON c.make = z.make AND c.model = z.model AND c.year = z.year
            JOIN scores s ON s.odi = c.odi
                AND s.failure = z.failure
            JOIN components k ON k.odi = c.odi
            WHERE {where} AND s.failure != 'other'
                AND s.failure_confidence >= 0.35
            GROUP BY c.make, c.model, c.year, s.failure, k.component_root
            ORDER BY count DESC, name
            """,
            [*selected_values, *values],
        ):
            key = (item["make"], item["model"], item["year"], item["failure"])
            if key not in cluster_keys:
                continue
            bucket = components_by_cluster.setdefault(key, [])
            if len(bucket) < 6:
                bucket.append({"name": item["name"], "count": item["count"]})

        examples_by_cluster: dict[tuple, list[dict]] = {}
        for item in connection.execute(
            f"""
            WITH selected(make, model, year, failure) AS (
                VALUES {selected_rows}
            ),
            ranked AS (
                SELECT
                    c.make, c.model, c.year, s.failure,
                    c.odi, c.received_date AS ldate, s.severity,
                    c.crash, c.fire, c.description AS desc,
                    (
                        SELECT GROUP_CONCAT(x.component_root, char(31))
                        FROM components x WHERE x.odi = c.odi
                    ) AS components,
                    ROW_NUMBER() OVER (
                        PARTITION BY c.make, c.model, c.year, s.failure
                        ORDER BY c.received_date DESC, s.severity DESC
                    ) AS row_number
                FROM selected z
                JOIN complaints c
                    ON c.make = z.make AND c.model = z.model AND c.year = z.year
                JOIN scores s ON s.odi = c.odi
                    AND s.failure = z.failure
                WHERE {where} AND s.failure != 'other'
                    AND s.failure_confidence >= 0.35
            )
            SELECT * FROM ranked WHERE row_number <= 3
            """,
            [*selected_values, *values],
        ):
            key = (item["make"], item["model"], item["year"], item["failure"])
            if key not in cluster_keys:
                continue
            example = dict(item)
            example["crash"] = bool(example["crash"])
            example["fire"] = bool(example["fire"])
            example["components"] = (
                example["components"].split(chr(31)) if example["components"] else []
            )
            example.pop("row_number", None)
            example.pop("make", None)
            example.pop("model", None)
            example.pop("year", None)
            example.pop("failure", None)
            examples_by_cluster.setdefault(key, []).append(example)

        clusters = []
        for row in cluster_rows:
            key = (row["make"], row["model"], row["year"], row["failure"])
            components = components_by_cluster.get(key, [])
            if len(components) < 2:
                continue
            examples = examples_by_cluster.get(key, [])
            row["vehicle"] = f"{row['year']} {row['make']} {row['model']}"
            row["headline"] = HEADLINES.get(row["failure"], row["failure"])
            row["failure_label"] = row["headline"]
            row["mean_confidence"] = round(row["mean_confidence"], 2)
            row["mean_severity"] = round(row["mean_severity"], 2)
            row["outside_filed_share"] = round(row["outside_filed_share"], 2)
            row["filed_components"] = components
            row["examples"] = examples
            clusters.append(row)

        stats["clusters"] = len(clusters)
        stats["mean_severity"] = round(stats["mean_severity"], 2)
        stats["crashes"] = stats["crashes"] or 0
        stats["fires"] = stats["fires"] or 0
        scored = connection.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
        result = {
            "meta": {
                "scored": scored,
                "matched": stats["complaints"],
                "minimum_cluster": minimum,
                "source": "NHTSA ODI complaints received in 2025–2026",
                "model": "jev-1.13.0",
                "maximum_date": maximum_date,
                "current_cutoff": current_cutoff,
                "prior_cutoff": prior_cutoff,
            },
            "stats": stats,
            "facets": (
                _facets(connection)
                if (params.get("include_facets") or ["1"])[0] != "0"
                else None
            ),
            "clusters": clusters,
        }
        result["meta"]["elapsed_ms"] = round(
            (time.perf_counter() - started) * 1000, 2
        )
        return result
    finally:
        connection.close()
