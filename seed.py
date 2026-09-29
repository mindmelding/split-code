#!/usr/bin/env python3
"""Import NHTSA complaints and resumably score every unscored row with Jev."""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from score import CACHE_PATH, score_one
from storage import PROMPT_VERSION, connect, import_nhtsa, migrate_jsonl

DEFAULT_COMPLAINTS = Path("/tmp/COMPLAINTS_RECEIVED_2025-2026.txt")
PRICE_PER_TOKEN = 0.042 / 1_000_000
EXIT_BUDGET = 0
EXIT_BILLING = 3


class BillingError(RuntimeError):
    pass


def pending_rows(limit: int | None = None) -> list[dict]:
    connection = connect(readonly=True)
    sql = """
        SELECT
            c.odi, c.make, c.model, c.year, c.received_date AS ldate,
            c.crash, c.fire, c.injured, c.deaths, c.description AS desc,
            GROUP_CONCAT(k.component, char(31)) AS component_list
        FROM complaints c
        LEFT JOIN scores s ON s.odi = c.odi
        LEFT JOIN components k ON k.odi = c.odi
        WHERE s.odi IS NULL
        GROUP BY c.odi
        ORDER BY c.received_date, c.odi
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    try:
        rows = []
        for row in connection.execute(sql):
            item = dict(row)
            item["crash"] = bool(item["crash"])
            item["fire"] = bool(item["fire"])
            item["components"] = set((item.pop("component_list") or "").split(chr(31)))
            item["components"].discard("")
            rows.append(item)
        return rows
    finally:
        connection.close()


def save_score(connection, result: dict) -> None:
    usage = result.get("usage") or {}
    connection.execute(
        """
        INSERT INTO scores (
            odi, prompt_version, model_used, failure, failure_confidence,
            failure_probability, outside_filed_code, severity,
            input_tokens, output_tokens
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(odi) DO UPDATE SET
            prompt_version=excluded.prompt_version,
            model_used=excluded.model_used,
            failure=excluded.failure,
            failure_confidence=excluded.failure_confidence,
            failure_probability=excluded.failure_probability,
            outside_filed_code=excluded.outside_filed_code,
            severity=excluded.severity,
            input_tokens=excluded.input_tokens,
            output_tokens=excluded.output_tokens,
            scored_at=CURRENT_TIMESTAMP
        """,
        (
            result["odi"],
            PROMPT_VERSION,
            result.get("model_used"),
            result["failure"],
            result["failure_confidence"],
            result.get("failure_probability"),
            result["outside_filed_code"],
            result["severity"],
            int(usage.get("input_tokens") or 0),
            int(usage.get("output_tokens") or 0),
        ),
    )


def score_pending(
    api_key: str, workers: int, limit: int | None, max_cost: float | None
) -> dict:
    records = pending_rows(limit)
    total = len(records)
    if not total:
        print("nothing to score", flush=True)
        return {"scored": 0, "failures": 0, "cost": 0.0, "stopped": None}

    connection = connect()
    started = time.monotonic()
    completed = 0
    failures = 0
    token_total = 0
    stopped = None
    iterator = iter(records)
    inflight = {}

    def submit_next(pool) -> bool:
        if stopped:
            return False
        try:
            record = next(iterator)
        except StopIteration:
            return False
        future = pool.submit(score_one, record, api_key)
        inflight[future] = record
        return True

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for _ in range(min(workers * 2, total)):
                submit_next(pool)
            while inflight:
                done, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for future in done:
                    record = inflight.pop(future)
                    try:
                        result = future.result()
                        save_score(connection, result)
                        usage = result.get("usage") or {}
                        token_total += int(usage.get("input_tokens") or 0)
                    except Exception as exc:
                        failures += 1
                        message = str(exc)
                        if "HTTP 402" in message or "billing_error" in message:
                            if not stopped:
                                print(f"stopping: Jev billing error: {message}", file=sys.stderr, flush=True)
                            stopped = "billing"
                        else:
                            print(f"error {record['odi']}: {message}", file=sys.stderr, flush=True)
                    completed += 1
                    if max_cost is not None and token_total * PRICE_PER_TOKEN >= max_cost and not stopped:
                        print(f"stopping: reached the ${max_cost:.2f} budget", flush=True)
                        stopped = "budget"
                    submit_next(pool)

                    if completed % 500 == 0 or completed == total:
                        connection.commit()
                        elapsed = time.monotonic() - started
                        rate = completed / elapsed
                        remaining = (total - completed) / rate if rate else 0
                        cost = token_total * PRICE_PER_TOKEN
                        print(
                            f"scored {completed}/{total} | {rate:.1f}/s | "
                            f"ETA {remaining / 60:.1f}m | ${cost:.2f} | "
                            f"errors {failures}",
                            flush=True,
                        )
        connection.commit()
    finally:
        connection.close()
    return {
        "scored": completed - failures,
        "failures": failures,
        "cost": round(token_total * PRICE_PER_TOKEN, 4),
        "stopped": stopped,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--complaints", type=Path, default=DEFAULT_COMPLAINTS)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--import-only", action="store_true")
    parser.add_argument("--max-cost", type=float, help="Stop scoring after this many dollars of Jev usage")
    args = parser.parse_args()

    count = import_nhtsa(args.complaints)
    migrated = migrate_jsonl(CACHE_PATH)
    print(f"database has {count} eligible complaints; inspected {migrated} MVP scores", flush=True)
    if args.import_only:
        return

    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Set TYPESAFE_API_KEY")
    result = score_pending(api_key, args.workers, args.limit, args.max_cost)
    print(
        f"run: scored {result['scored']}, errors {result['failures']}, "
        f"${result['cost']:.2f}, stopped={result['stopped']}",
        flush=True,
    )
    if result["stopped"] == "billing":
        sys.exit(EXIT_BILLING)
    sys.exit(EXIT_BUDGET)


if __name__ == "__main__":
    main()
