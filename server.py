#!/usr/bin/env python3
"""Serve scored NHTSA complaints. Jev judgments are read from the local cache."""

from __future__ import annotations

import json
import os
import time
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from score import CACHE_PATH, clusters, component_root, load_complaints
from memory_repository import load_snapshot, query as snapshot_query

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
COMPLAINTS = Path("/tmp/COMPLAINTS_RECEIVED_2025-2026.txt")
CUTOFF = "20260801"

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

RECORDS: list[dict] = []


def load_records() -> list[dict]:
    cached = {}
    with CACHE_PATH.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cached[row["odi"]] = row
    complaints = load_complaints(COMPLAINTS, CUTOFF)
    records = []
    for odi, score in cached.items():
        rec = complaints.get(odi)
        if rec is None:
            continue
        records.append(
            {
                "odi": odi,
                "make": rec["make"],
                "model": rec["model"],
                "year": rec["year"],
                "ldate": rec["ldate"],
                "crash": rec["crash"],
                "fire": rec["fire"],
                "injured": rec["injured"],
                "deaths": rec["deaths"],
                "desc": rec["desc"],
                "components": rec["components"],
                "failure": score["failure"],
                "failure_confidence": score["failure_confidence"],
                "outside_filed_code": score["outside_filed_code"],
                "severity": score["severity"],
            }
        )
    records.sort(key=lambda row: row["ldate"])
    return records


def _flag(params: dict[str, list[str]], name: str) -> str:
    return (params.get(name) or [""])[0].strip()


def parse_filters(params: dict[str, list[str]]) -> dict:
    severity = _flag(params, "min_severity")
    return {
        "failure": _flag(params, "failure"),
        "make": _flag(params, "make"),
        "model": _flag(params, "model"),
        "year": _flag(params, "year"),
        "component": _flag(params, "component"),
        "q": _flag(params, "q").lower(),
        "min_severity": float(severity) if severity else 0.0,
        "crashes": _flag(params, "crashes") in ("1", "true", "yes"),
        "fires": _flag(params, "fires") in ("1", "true", "yes"),
    }


def matches(rec: dict, filters: dict) -> bool:
    if filters["failure"] and rec["failure"] != filters["failure"]:
        return False
    if filters["make"] and rec["make"] != filters["make"]:
        return False
    if filters["model"] and rec["model"] != filters["model"]:
        return False
    if filters["year"] and rec["year"] != filters["year"]:
        return False
    if filters["min_severity"] and rec["severity"] < filters["min_severity"]:
        return False
    if filters["crashes"] and not rec["crash"]:
        return False
    if filters["fires"] and not rec["fire"]:
        return False
    if filters["q"] and filters["q"] not in rec["desc"].lower() and filters["q"] not in rec["odi"]:
        return False
    if filters["component"]:
        roots = {component_root(name) for name in rec["components"]}
        if filters["component"] not in roots:
            return False
    return True


def filters_active(filters: dict) -> bool:
    return any(
        [
            filters["failure"],
            filters["make"],
            filters["model"],
            filters["year"],
            filters["component"],
            filters["q"],
            filters["min_severity"],
            filters["crashes"],
            filters["fires"],
        ]
    )


def facets(records: list[dict]) -> dict:
    def tally(key: str) -> list[dict]:
        counts: dict[str, int] = {}
        for rec in records:
            value = rec[key]
            counts[value] = counts.get(value, 0) + 1
        rows = [{"id": key_id, "count": count} for key_id, count in counts.items()]
        rows.sort(key=lambda row: (-row["count"], row["id"]))
        return rows

    components: dict[str, int] = {}
    for rec in records:
        for name in {component_root(item) for item in rec["components"]}:
            components[name] = components.get(name, 0) + 1
    component_rows = [{"id": key_id, "count": count} for key_id, count in components.items()]
    component_rows.sort(key=lambda row: (-row["count"], row["id"]))
    failures = tally("failure")
    for row in failures:
        row["label"] = HEADLINES.get(row["id"], row["id"])
    index: dict[tuple[str, str, str], int] = {}
    for rec in records:
        key = (rec["make"], rec["model"], rec["year"])
        index[key] = index.get(key, 0) + 1
    return {
        "failures": failures,
        "makes": tally("make"),
        "models": tally("model"),
        "years": tally("year"),
        "components": component_rows,
        "index": [
            {"make": make, "model": model, "year": year, "count": count}
            for (make, model, year), count in sorted(index.items(), key=lambda item: -item[1])
        ],
    }


def query(params: dict[str, list[str]]) -> dict:
    started = time.perf_counter()
    filters = parse_filters(params)
    matched = [rec for rec in RECORDS if matches(rec, filters)]
    pairs = [
        (
            rec,
            {
                "failure": rec["failure"],
                "failure_confidence": rec["failure_confidence"],
                "outside_filed_code": rec["outside_filed_code"],
                "severity": rec["severity"],
            },
        )
        for rec in matched
    ]
    minimum = 2 if filters_active(filters) else 5
    found = clusters(pairs, minimum)
    by_odi = {rec["odi"]: rec for rec in matched}
    for cluster in found:
        cluster["headline"] = HEADLINES.get(cluster["failure"], cluster["failure_label"])
        cluster["examples"] = []
        for odi in cluster["odi"][:6]:
            rec = by_odi.get(odi)
            if rec is None:
                continue
            cluster["examples"].append(
                {
                    "odi": rec["odi"],
                    "ldate": rec["ldate"],
                    "severity": round(rec["severity"], 2),
                    "crash": rec["crash"],
                    "fire": rec["fire"],
                    "components": sorted(component_root(name) for name in rec["components"]),
                    "desc": rec["desc"][:420],
                }
            )
        cluster["filed_components"] = [
            {"name": name, "count": count} for name, count in cluster["filed_components"][:6]
        ]
        cluster.pop("odi", None)
    crashes = sum(1 for rec in matched if rec["crash"])
    fires = sum(1 for rec in matched if rec["fire"])
    mean_severity = round(sum(rec["severity"] for rec in matched) / len(matched), 2) if matched else 0
    return {
        "meta": {
            "scored": len(RECORDS),
            "matched": len(matched),
            "minimum_cluster": minimum,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "source": "NHTSA ODI complaints received 1 Aug–24 Sep 2026",
            "model": "jev-1.13.0",
        },
        "stats": {
            "clusters": len(found),
            "complaints": len(matched),
            "crashes": crashes,
            "fires": fires,
            "mean_severity": mean_severity,
        },
        "facets": facets(RECORDS),
        "clusters": found,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/query":
            body = json.dumps(snapshot_query(parse_qs(parsed.query))).encode()
            encoding = None
            if "gzip" in self.headers.get("Accept-Encoding", ""):
                body = gzip.compress(body, compresslevel=5)
                encoding = "gzip"
            self._send(
                200,
                "application/json; charset=utf-8",
                body,
                content_encoding=encoding,
            )
            return
        path = parsed.path
        if path in ("", "/"):
            path = "/index.html"
        file_path = (STATIC / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(STATIC.resolve())) or not file_path.is_file():
            self._send(404, "text/plain; charset=utf-8", b"Not found")
            return
        kind = "text/html; charset=utf-8"
        if file_path.suffix == ".css":
            kind = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            kind = "text/javascript; charset=utf-8"
        self._send(200, kind, file_path.read_bytes())

    def _send(
        self,
        status: int,
        content_type: str,
        body: bytes,
        content_encoding: str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if content_encoding:
            self.send_header("Content-Encoding", content_encoding)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        if args and str(args[1]) != "200":
            super().log_message(fmt, *args)


def main() -> None:
    port = int(os.environ.get("PORT", "8787"))
    count = load_snapshot()
    print(f"loaded {count} scored complaints", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
