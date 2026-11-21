"""fleet_simulator.py — Fleet definition and helper constants.

Ported from common.js: FLEET, FLOOR, RESERVE, TOPUP, needOf.
Depot location: Oakland Corporate Office (simulated), lat 37.7510, lon -122.1990.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Depot location
# ---------------------------------------------------------------------------
DEPOT = {"name": "Oakland Corporate Office (simulated)", "lat": 37.7510, "lon": -122.1990}

# ---------------------------------------------------------------------------
# Charger constants (mirrors gateway_controller.py / depot-engine.js)
# ---------------------------------------------------------------------------
_VOLTS = 240
_MAX_A = 32
CH_KW = _MAX_A * _VOLTS / 1000   # 7.68 kW — default Level-2 charger rate per vehicle

# ---------------------------------------------------------------------------
# Simulation timing constants (all in minutes from midnight)
# ---------------------------------------------------------------------------
START_MIN = 13 * 60      # 13:00 — vans start plugging in
DAY_START_MIN = 6 * 60  # 06:00 — full-day run start
END_MIN = 30 * 60        # 30:00 (06:00 next day) — simulation end
SLOT = 15                # planning slot size (minutes)

# ---------------------------------------------------------------------------
# SOC thresholds
# ---------------------------------------------------------------------------
FLOOR = 10    # minimum battery % the van must keep
RESERVE = 5   # extra buffer above floor
TOPUP = 90    # nice-to-have top-up target %


def need_of(f: "Van") -> int:
    """Battery % a vehicle needs at departure to run its whole route and return
    with FLOOR + RESERVE remaining.  Mirrors needOf() in common.js."""
    return min(100, math.ceil(f.stops * f.drain + f.ret + FLOOR + RESERVE))


# ---------------------------------------------------------------------------
# Van / vehicle dataclass
# ---------------------------------------------------------------------------
@dataclass
class Van:
    name: str
    cap: float          # battery capacity kWh
    soc: float          # state of charge % on return
    plug: int           # minutes after START_MIN (13:00) when it plugs in
    dep: int            # departure time (minutes from midnight; 29*60 = 05:00 next day)
    stops: int          # delivery stops on its route
    pk: float           # peak power draw kW (informational)
    drain: float        # % battery per stop
    ret: float          # % battery to drive back from last stop
    bearing: float      # compass bearing of the route sector (degrees)
    ch_kw: float = CH_KW  # per-vehicle charger rate (kW); default = Level-2 (7.68 kW)
    days_out: int = 1     # how many nights between depot visits (1 = nightly; 2+ = multi-day haul)

    # Runtime fields — reset by gateway_controller for each simulation
    arrive: int = 0         # actual plug-in minute (START_MIN + plug)
    soc0: float = 0.0       # soc at arrival (saved for health notes)
    status: str = "Away"    # Away | Charging | Scheduled | Throttled | Paused | Ready | Departed
    kwh: float = 0.0        # kWh delivered this night
    amps: float = 0.0       # current charging amps
    want_a: float = 0.0     # amps requested this step
    max_a: float = 0.0      # max amps the charger can deliver
    slack: float = 0.0      # minutes of slack before departure
    critical: bool = False
    was_crit: bool = False
    met: Optional[bool] = None   # did it meet its route requirement?
    plan: dict = field(default_factory=dict)   # {slot_minute: kW}
    short: float = 0.0      # kWh still short after planning
    fault: bool = False     # charger fault flag
    ticket: Optional[str] = None
    down_min: float = 0.0
    peak_kwh: float = 0.0
    cost_kwh: float = 0.0
    cost: float = 0.0
    want_kwh: float = 0.0

    @property
    def need(self) -> int:
        return need_of(self)


# ---------------------------------------------------------------------------
# Fleet — seven vehicles matching FLEET in common.js exactly
# ---------------------------------------------------------------------------
# Tesla Semi (interstate long-haul):
#   3 major city drop-offs per run (e.g. Oakland → Fresno → Bakersfield → LA).
#   drain: 40% per leg (~500 km at 1 kWh/km on a 500 kWh pack = 200 kWh = 40%).
#   ret: 35% return leg (~350-400 km empty). soc on return: ~9-10% after a full run.
#   Semis operate on a 2-day cycle: Semi A is back this session (plug=120 min),
#   Semi B is still on the road (plug > END_MIN-START_MIN, so it stays Away all night).
#   dep=31*60 (07:00 next day) gives a full 18-hour charging window for the returned Semi.
_SEMI_ABSENT = END_MIN - START_MIN + 60   # 1020 min after 13:00 → never returns this night

FLEET_DEFS = [
    dict(name="Van 1",   cap=80,  soc=16, plug=0,            dep=29*60,  stops=22, pk=60,  drain=2.8, ret=6,  bearing=20),
    dict(name="Van 2",   cap=80,  soc=18, plug=15,           dep=29*60+45, stops=16, pk=45,  drain=3.0, ret=6,  bearing=70),
    dict(name="Truck 3", cap=100, soc=20, plug=30,           dep=28*60+30, stops=24, pk=110, drain=1.8, ret=5,  bearing=110),
    dict(name="Van 4",   cap=80,  soc=17, plug=60,           dep=29*60+45, stops=14, pk=38,  drain=3.0, ret=6,  bearing=150),
    dict(name="Van 5",   cap=60,  soc=15, plug=90,           dep=29*60+30, stops=18, pk=52,  drain=3.2, ret=6,  bearing=340),
    dict(name="Semi A",  cap=500, soc=9,  plug=120,          dep=31*60,  stops=3,  pk=300, drain=40.0, ret=35, bearing=200, ch_kw=50.0, days_out=2),
    dict(name="Semi B",  cap=500, soc=10, plug=_SEMI_ABSENT, dep=31*60,  stops=3,  pk=300, drain=40.0, ret=35, bearing=280, ch_kw=50.0, days_out=2),
]


def make_fleet(arrivals: dict | None = None) -> list[Van]:
    """Return a fresh list of Van objects, optionally overriding arrival soc/plug.

    arrivals = {"Van 1": {"soc": 22, "plug": 5}, ...}
    """
    arrivals = arrivals or {}
    vans = []
    for d in FLEET_DEFS:
        a = arrivals.get(d["name"], {})
        v = Van(**d)
        v.soc = a.get("soc", v.soc)
        v.soc0 = v.soc
        v.plug = a.get("plug", v.plug)
        v.arrive = START_MIN + v.plug
        vans.append(v)
    return vans
