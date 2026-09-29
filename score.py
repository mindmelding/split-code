#!/usr/bin/env python3
"""Score recent NHTSA complaints with Jev and list failure clusters.

A cluster is one make, model, and year whose descriptions agree on a failure
while the component codes people filed are spread across more than one system.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API_URL = "https://api.typesafe.ai/v1/systemone"
ROOT = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "out" / "scores.jsonl"

# Fixed rubric. Keys are stable ids. Descriptions are what Jev judges against.
FAILURES = {
    "idle_stop_no_restart": (
        "Auto start-stop or idle-stop turns the vehicle off at a light or stop, "
        "and it then fails to restart, re-engage drive, or move when the driver wants to go."
    ),
    "stall_while_moving": (
        "The vehicle loses propulsion, stalls, or drops into limp mode while it is moving."
    ),
    "wont_start_when_parked": (
        "The vehicle will not start or the battery is dead while parked. "
        "This is not an auto start-stop event in traffic."
    ),
    "unintended_acceleration": (
        "The vehicle speeds up on its own, surges, or accelerates without the driver asking."
    ),
    "brake_failure": (
        "Brakes are soft, long, grab, or fail to stop the vehicle. Includes ABS faults that affect stopping."
    ),
    "stuck_gear_or_rollaway": (
        "Transmission will not shift, sticks in park or neutral, or the vehicle rolls when it should hold."
    ),
    "steering_assist_loss": (
        "Power steering assist dies or the wheel locks or goes suddenly heavy, including at low speed."
    ),
    "pull_shake_or_vibration": (
        "The vehicle pulls, shakes, or vibrates in the wheel, seat, or body, without a total loss of steering assist."
    ),
    "unwanted_driver_assist": (
        "Automatic braking, lane keeping, or adaptive cruise acts when it should not, or yanks the vehicle."
    ),
    "restraint_fault": (
        "Airbag or seat belt fails to work, deploys unexpectedly, or shows a restraint warning as the main problem."
    ),
    "fire_smoke_or_burning": (
        "Fire, smoke, melting, or a burning smell from the vehicle itself."
    ),
    "leak": "Fuel, oil, coolant, or another fluid leaks.",
    "wheel_or_tire": (
        "A tire blows out, separates, or a wheel or lug comes loose or falls off."
    ),
    "body_or_latch": (
        "A door, hood, hatch, seat, trim, or body panel opens, detaches, or fails to latch."
    ),
    "lighting_or_visibility": (
        "Lights, wipers, or defrost fail, or the driver cannot see."
    ),
    "other": "The complaint does not describe one of the listed failures.",
}

SEVERITY = [
    "Annoyance only. The vehicle stayed controllable and was not stuck in traffic.",
    "Stuck, stranded, or a repeat no-restart at a stop. Other road users may be affected, but the vehicle was not moving out of control.",
    "Loss of propulsion, braking, or steering while the vehicle was moving, or a near crash.",
    "A crash, fire, injury, or death is described, or control was lost outright.",
]

# High-volume vehicles whose filed codes were already split across systems
# in complaints received on or after the default cutoff. Capped per vehicle.
DEFAULT_VEHICLES = [
    ("HONDA", "ODYSSEY", "2025"),
    ("TESLA", "MODEL Y", "2026"),
    ("JEEP", "WRANGLER", "2024"),
    ("HONDA", "ACCORD", "2018"),
    ("TESLA", "MODEL Y", "2023"),
    ("GMC", "SIERRA 1500", "2023"),
    ("FORD", "F-150", "2021"),
    ("RAM", "1500", "2025"),
]


def load_complaints(path: Path, cutoff: str) -> dict[str, dict]:
    complaints: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) < 46 or row[45] != "V":
                continue
            if row[16] < cutoff or len(row[19].strip()) < 40:
                continue
            if row[3] in ("", "UNKNOWN"):
                continue
            odi = row[1]
            rec = complaints.get(odi)
            if rec is None:
                rec = {
                    "odi": odi,
                    "make": row[3].strip(),
                    "model": row[4].strip(),
                    "year": row[5].strip(),
                    "ldate": row[16],
                    "crash": row[6] == "Y",
                    "fire": row[8] == "Y",
                    "injured": _int(row[9]),
                    "deaths": _int(row[10]),
                    "desc": row[19].strip(),
                    "components": set(),
                }
                complaints[odi] = rec
            rec["components"].add(row[11].strip())
            if row[16] < rec["ldate"]:
                rec["ldate"] = row[16]
    return complaints


def _int(value: str) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def select(complaints: dict[str, dict], per_vehicle: int) -> list[dict]:
    wanted = set(DEFAULT_VEHICLES)
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for rec in complaints.values():
        key = (rec["make"], rec["model"], rec["year"])
        if key in wanted:
            grouped[key].append(rec)
    chosen = []
    for key in DEFAULT_VEHICLES:
        rows = sorted(grouped.get(key, []), key=lambda rec: rec["ldate"], reverse=True)
        chosen.extend(rows[:per_vehicle])
    return chosen


def state_for(rec: dict) -> str:
    filed = "; ".join(sorted(rec["components"])) or "none listed"
    flags = []
    if rec["crash"]:
        flags.append("crash reported")
    if rec["fire"]:
        flags.append("fire reported")
    if rec["injured"]:
        flags.append(f"injuries {rec['injured']}")
    if rec["deaths"]:
        flags.append(f"deaths {rec['deaths']}")
    flag_line = ", ".join(flags) if flags else "none"
    return (
        f"Vehicle: {rec['year']} {rec['make']} {rec['model']}\n"
        f"Filed component categories: {filed}\n"
        f"Structured flags: {flag_line}\n"
        f"Complaint:\n{rec['desc'][:1800]}"
    )


def questions() -> dict:
    return {
        "failure": {
            "type": "choice",
            "instructions": (
                "What failure does the complaint actually describe? "
                "Use the narrative, not the filed component categories. "
                "If auto start-stop shuts the vehicle off and it will not restart or re-engage gear, "
                "choose idle_stop_no_restart even when a battery light or a shift-to-park message is also mentioned."
            ),
            "criteria": FAILURES,
        },
        "outside_filed_code": {
            "type": "noul",
            "instructions": (
                "Does the narrative describe a failure that sits outside the filed component categories? "
                "Yes when those categories are a different system, or so broad that they hide the event. "
                "No when a filed category plainly names the system that failed."
            ),
        },
        "severity": {
            "type": "score",
            "instructions": "How serious is the event in the narrative?",
            "criteria": SEVERITY,
        },
    }


def score_one(rec: dict, api_key: str) -> dict:
    body = json.dumps(
        {
            "model": "jev-latest",
            "state": state_for(rec),
            "questions": questions(),
        }
    ).encode()
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    delay = 1.0
    last_error = None
    for _ in range(5):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode())
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            last_error = f"HTTP {exc.code}: {detail}"
            if exc.code not in (429, 529, 500, 502, 503):
                raise RuntimeError(last_error) from exc
            time.sleep(delay)
            delay = min(delay * 2, 20)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(exc)
            time.sleep(delay)
            delay = min(delay * 2, 20)
    else:
        raise RuntimeError(last_error or "request failed")

    answers = payload["answers"]
    failure = answers["failure"]
    return {
        "odi": rec["odi"],
        "model_used": payload.get("model"),
        "failure": failure["choice"],
        "failure_confidence": failure["confidence"],
        "failure_probability": failure["probabilities"].get(failure["choice"]),
        "outside_filed_code": answers["outside_filed_code"]["noul"],
        "severity": answers["severity"]["score"],
        "usage": payload.get("usage"),
    }


def load_cache() -> dict[str, dict]:
    if not CACHE_PATH.exists():
        return {}
    cached = {}
    with CACHE_PATH.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cached[row["odi"]] = row
    return cached


def component_root(name: str) -> str:
    return name.split(":")[0].strip()


def clusters(scored: list[tuple[dict, dict]], min_count: int) -> list[dict]:
    groups: dict[tuple, list] = defaultdict(list)
    for rec, score in scored:
        if score["failure"] == "other":
            continue
        if score["failure_confidence"] < 0.35:
            continue
        groups[(rec["make"], rec["model"], rec["year"], score["failure"])].append((rec, score))

    found = []
    for (make, model, year, failure), rows in groups.items():
        if len(rows) < min_count:
            continue
        roots = Counter()
        for rec, _score in rows:
            for component in rec["components"]:
                roots[component_root(component)] += 1
        if len(roots) < 2:
            continue
        rows.sort(key=lambda pair: pair[1]["severity"], reverse=True)
        dates = [rec["ldate"] for rec, _score in rows]
        found.append(
            {
                "vehicle": f"{year} {make} {model}",
                "make": make,
                "model": model,
                "year": year,
                "failure": failure,
                "failure_label": FAILURES[failure].split(".")[0],
                "count": len(rows),
                "first": min(dates),
                "last": max(dates),
                "mean_confidence": round(sum(s["failure_confidence"] for _, s in rows) / len(rows), 2),
                "mean_severity": round(sum(s["severity"] for _, s in rows) / len(rows), 2),
                "outside_filed_share": round(
                    sum(1 for _, s in rows if s["outside_filed_code"] >= 0.6) / len(rows), 2
                ),
                "crashes": sum(1 for rec, _ in rows if rec["crash"]),
                "fires": sum(1 for rec, _ in rows if rec["fire"]),
                "filed_components": roots.most_common(),
                "quotes": [rec["desc"][:280] for rec, _ in rows[:3]],
                "odi": [rec["odi"] for rec, _ in rows],
            }
        )
    found.sort(key=lambda row: (row["count"], row["mean_severity"]), reverse=True)
    return found


def write_report(found: list[dict], scored_count: int, usage_tokens: int, path: Path) -> None:
    lines = [
        f"Scored {scored_count} complaints. Input tokens {usage_tokens}.",
        f"Clusters with at least two filed component families: {len(found)}.",
        "",
    ]
    for index, row in enumerate(found, start=1):
        comps = ", ".join(f"{name} {count}" for name, count in row["filed_components"][:5])
        lines.append(
            f"{index}. {row['vehicle']} — {row['failure']} ({row['count']} complaints, "
            f"{row['first']} to {row['last']})"
        )
        lines.append(
            f"   confidence {row['mean_confidence']}, severity {row['mean_severity']}/3, "
            f"outside filed code {row['outside_filed_share']:.0%}, "
            f"crashes {row['crashes']}, fires {row['fires']}"
        )
        lines.append(f"   filed: {comps}")
        for quote in row["quotes"]:
            lines.append(f"   > {quote}")
        lines.append("")
    path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--complaints",
        type=Path,
        default=Path("/tmp/COMPLAINTS_RECEIVED_2025-2026.txt"),
    )
    parser.add_argument("--cutoff", default="20260801")
    parser.add_argument("--per-vehicle", type=int, default=80)
    parser.add_argument("--min-count", type=int, default=5)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        sys.exit("Set TYPESAFE_API_KEY")

    complaints = load_complaints(args.complaints, args.cutoff)
    sample = select(complaints, args.per_vehicle)
    print(f"selected {len(sample)} complaints from {len(DEFAULT_VEHICLES)} vehicles", flush=True)

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cached = load_cache()
    pending = [rec for rec in sample if rec["odi"] not in cached]
    print(f"cached {len(sample) - len(pending)}, to score {len(pending)}", flush=True)

    if pending:
        with CACHE_PATH.open("a") as handle:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {pool.submit(score_one, rec, api_key): rec for rec in pending}
                done = 0
                for future in as_completed(futures):
                    rec = futures[future]
                    result = future.result()
                    handle.write(json.dumps(result) + "\n")
                    handle.flush()
                    done += 1
                    if done % 25 == 0 or done == len(pending):
                        print(f"scored {done}/{len(pending)}", flush=True)

    cached = load_cache()
    paired = []
    tokens = 0
    for rec in sample:
        score = cached.get(rec["odi"])
        if score is None:
            continue
        paired.append((rec, score))
        usage = score.get("usage") or {}
        tokens += int(usage.get("input_tokens") or 0)

    found = clusters(paired, args.min_count)
    out_json = ROOT / "out" / "clusters.json"
    out_txt = ROOT / "out" / "report.txt"
    out_json.write_text(json.dumps(found, indent=2))
    write_report(found, len(paired), tokens, out_txt)
    print(out_txt.read_text())


if __name__ == "__main__":
    main()
