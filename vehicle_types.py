"""Coarse body type and powertrain for a make and model, used to pick a drawing."""

from __future__ import annotations

import re
from functools import lru_cache

PICKUPS = (
    "F-150", "F-250", "F-350", "F-450", "SILVERADO", "SIERRA", "TACOMA", "TUNDRA",
    "COLORADO", "CANYON", "RANGER", "FRONTIER", "TITAN", "GLADIATOR", "RIDGELINE",
    "MAVERICK", "CYBERTRUCK", "R1T", "SANTA CRUZ", "LIGHTNING", "HUMMER EV PICKUP",
)
RAM_PICKUPS = ("1500", "2500", "3500", "1500 CLASSIC")
MINIVANS = (
    "ODYSSEY", "PACIFICA", "SIENNA", "CARNIVAL", "SEDONA", "GRAND CARAVAN",
    "VOYAGER", "QUEST", "ID. BUZZ",
)
BOXY_SUVS = (
    "WRANGLER", "BRONCO", "4RUNNER", "DEFENDER", "G-CLASS", "TAHOE", "SUBURBAN",
    "YUKON", "EXPEDITION", "SEQUOIA", "ESCALADE", "LAND CRUISER", "ARMADA",
    "NAVIGATOR", "GRAND WAGONEER", "WAGONEER", "TELLURIDE", "PALISADE",
)
SEDANS = (
    "ACCORD", "CIVIC", "CAMRY", "COROLLA", "ALTIMA", "SENTRA", "MALIBU", "SONATA",
    "ELANTRA", "FORTE", "K5", "OPTIMA", "JETTA", "PASSAT", "FUSION", "FOCUS",
    "MAZDA3", "MAZDA6", "LEGACY", "IMPREZA", "CHARGER", "300", "AVALON", "MAXIMA",
    "VERSA", "ACCENT", "RIO", "TLX", "ILX", "INTEGRA", "CLA", "C-CLASS", "E-CLASS",
    "A3", "A4", "A6", "3 SERIES", "5 SERIES", "IS", "ES", "CRUZE", "IMPALA",
    "SPARK", "FIT", "YARIS", "MIRAGE", "MUSTANG", "CAMARO", "CHALLENGER", "GENESIS",
    "G70", "G80", "STINGER", "CT4", "CT5", "S60", "WRX",
)
EVS = (
    "MODEL 3", "MODEL Y", "MODEL S", "MODEL X", "MUSTANG MACH-E", "MACH-E",
    "IONIQ", "EV6", "EV9", "ID.4", "BOLT", "LEAF", "ARIYA", "POLESTAR", "R1S",
    "R1T", "LYRIQ", "BLAZER EV", "EQUINOX EV", "SILVERADO EV", "LIGHTNING",
    "CYBERTRUCK", "I4", "IX", "EQS", "EQE", "E-TRON", "BZ4X", "SOLTERRA",
    "PROLOGUE", "NIRO EV", "KONA ELECTRIC", "HUMMER EV",
)
EV_MAKES = ("TESLA", "RIVIAN", "LUCID", "POLESTAR")

BODY_LABELS = {
    "sedan": "Sedan",
    "crossover": "Crossover",
    "suv": "SUV",
    "pickup": "Pickup",
    "minivan": "Minivan",
    "fastback": "EV fastback",
}


def _has(model: str, names: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", model) for name in names)


@lru_cache(maxsize=None)
def classify(make: str, model: str) -> tuple[str, str]:
    """Return (body, powertrain) where powertrain is "ev" or "ice"."""
    make = (make or "").upper()
    model = (model or "").upper()
    ev = make in EV_MAKES or _has(model, EVS)

    if (make == "RAM" and model in RAM_PICKUPS) or _has(model, PICKUPS):
        body = "pickup"
    elif _has(model, MINIVANS):
        body = "minivan"
    elif _has(model, BOXY_SUVS):
        body = "suv"
    elif ev:
        body = "fastback"
    elif _has(model, SEDANS):
        body = "sedan"
    else:
        body = "crossover"
    return body, "ev" if ev else "ice"
