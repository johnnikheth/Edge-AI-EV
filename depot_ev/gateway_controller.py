"""gateway_controller.py — Charging planner, power allocator, simulation step, and cost billing.

Ported from depot-engine.js.  All logic mirrors the JS exactly so that
`python -m depot_ev.run_night` produces the same nightly figures as the
Depot web page for the same configuration.

Key constants (depot-engine.js, lines 3-4):
  VOLTS=240, MAX_A=32, MIN_A=6, CH_KW=MAX_A*VOLTS/1000=7.68 kW
  HVAC_KW=30, CRIT_MIN=90
  START_MIN=13*60, END_MIN=30*60, SLOT=15 min
  ETA_IN=0.95, ETA_OUT=0.95

PG&E BEV-1 (dedicated EV meter, ≤100 kW, secondary voltage, effective March 1 2026):
  peak=$0.35711/kWh  (16:00–21:00)
  off=$0.16510/kWh
  super_off=$0.13844/kWh  (09:00–14:00)
  subscription: $12.41/block of 10 kW peak demand
"""
from __future__ import annotations

import copy
import math
from typing import Optional

from .fleet_simulator import (
    Van, make_fleet,
    START_MIN, DAY_START_MIN, END_MIN, SLOT, TOPUP,
)

# ---------------------------------------------------------------------------
# Hardware constants
# ---------------------------------------------------------------------------
VOLTS = 240
MAX_A = 32
MIN_A = 6
CH_KW = MAX_A * VOLTS / 1000       # 7.68 kW per charger
HVAC_KW = 30                        # kW when HVAC is running
CRIT_MIN = 90                       # minutes of slack below which a van is "critical"

# ---------------------------------------------------------------------------
# Battery efficiency
# ---------------------------------------------------------------------------
ETA_IN = 0.95
ETA_OUT = 0.95

# ---------------------------------------------------------------------------
# Building thermal model
# ---------------------------------------------------------------------------
K = 0.004       # heat-exchange coefficient per minute
HEAT = 0.1      # °C per minute added by HVAC
STD_BAND = 2.5  # standard thermostat hysteresis (°C)
SNAP = -10      # cold-snap delta applied to outdoor temperature
MAX_TIN = 25    # max indoor temperature (°C)

# ---------------------------------------------------------------------------
# PG&E Schedule BEV-1 tariff (depot-engine.js BEV1 object)
# ---------------------------------------------------------------------------
BEV1 = {
    "name": "PG&E BEV-1 (Business EV)",
    "effective": "March 1, 2026",
    "url": "https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_BEV.pdf",
    "peak": 0.35711,
    "off": 0.16510,
    "super_off": 0.13844,
    "block_kw": 10,
    "block_usd": 12.41,
    "overage_usd": 2.48,
}
PRICE = {"peak": BEV1["peak"], "off": BEV1["off"], "super": BEV1["super_off"]}
PERIOD_NAME = {
    "peak": "Peak (4–9 pm)",
    "off": "Off-peak",
    "super": "Super off-peak (9 am–2 pm)",
}


# ---------------------------------------------------------------------------
# Period classifier — mirrors period(m) in depot-engine.js
# ---------------------------------------------------------------------------
def period(minutes: float) -> str:
    """Return 'peak', 'super', or 'off' for a given minute-of-day."""
    h = (((minutes % 1440) + 1440) % 1440) / 60
    if 16 <= h < 21:
        return "peak"
    if 9 <= h < 14:
        return "super"
    return "off"


# ---------------------------------------------------------------------------
# Solar output — mirrors solarPerKwp(m, profile) in depot-engine.js
# ---------------------------------------------------------------------------
def solar_per_kwp(minutes: float, profile: Optional[list] = None) -> float:
    """kW produced per kW of installed panels at the given minute.

    Uses the PVWatts monthly-average profile when provided; otherwise falls
    back to a clear October day in Oakland (rise 07:15, set 18:30).
    """
    h = (((minutes % 1440) + 1440) % 1440) / 60
    if profile and len(profile) == 24:
        i = int(h)
        f = h - i
        return profile[i] * (1 - f) + profile[(i + 1) % 24] * f
    rise, set_ = 7.25, 18.5
    if h <= rise or h >= set_:
        return 0.0
    return 0.68 * math.pow(math.sin(math.pi * (h - rise) / (set_ - rise)), 1.3)


# ---------------------------------------------------------------------------
# Outdoor temperature — mirrors outdoorTemp(m, wx) in depot-engine.js
# ---------------------------------------------------------------------------
def outdoor_temp(minutes: float, wx: Optional[dict] = None) -> float:
    """°C outdoor temperature at the given minute."""
    if wx and wx.get("temps") and len(wx["temps"]) > math.ceil(minutes / 60) + 1:
        h = minutes / 60
        i = int(h)
        f = h - i
        return wx["temps"][i] * (1 - f) + wx["temps"][i + 1] * f
    # typical Oakland October day
    return 15.5 + 5.5 * math.cos(2 * math.pi * ((minutes / 60) % 24 - 15) / 24)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fmt_clock(minutes: float) -> str:
    m = int((minutes % 1440 + 1440) % 1440)
    return f"{m // 60:02d}:{m % 60:02d}"


def _note(st: dict, src: str, text: str) -> None:
    if not st["cfg"].get("quiet"):
        st["events"].append({"t": st["t"], "src": src, "text": text})


def mins_to_fill(c: Van) -> float:
    if c.soc >= c.need:
        return 0.0
    return ((c.need - c.soc) / 100 * c.cap) / c.ch_kw * 60


def want_amps(c: Van) -> float:
    """Amps the van's BMS would accept right now (CC/CV curve approximation).

    Uses c.ch_kw as the charger rate cap so high-power vehicles (e.g. Tesla Semi
    at 50 kW) can draw proportionally more amps than a Level-2 van charger.
    """
    if c.soc >= TOPUP:
        return 0
    max_a_veh = round(c.ch_kw * 1000 / VOLTS)   # charger-rate ceiling for this vehicle
    if c.soc <= 80:
        return max_a_veh
    return max(MIN_A, round(max_a_veh * (1 - (c.soc - 80) / 12)))


# ---------------------------------------------------------------------------
# Battery wear cost — mirrors storageWear() in depot-engine.js
# ---------------------------------------------------------------------------
WEAR_DEFAULTS = {"chem": "NMC", "usd_per_kwh": 200}

try:
    from .reference_data import REFDATA  # type: ignore
except ImportError:
    REFDATA = {}


def _fade_for(chem: str) -> Optional[dict]:
    return (REFDATA.get("battery_fade") or {}).get(chem)


def storage_wear(cfg: dict) -> Optional[dict]:
    chem = cfg.get("chem", WEAR_DEFAULTS["chem"])
    f = _fade_for(chem)
    if not f or not cfg.get("batt_kwh"):
        return None
    usd = cfg.get("batt_usd_per_kwh", WEAR_DEFAULTS["usd_per_kwh"])
    per_kwh = usd / f["cycles_to_80pct_soh"]
    grid_cost = PRICE["super"] / (ETA_IN * ETA_OUT)
    margin = PRICE["peak"] - grid_cost - per_kwh
    return {
        "chem": chem, "usd_per_kwh": usd, "cycles80": f["cycles_to_80pct_soh"],
        "wear_per_kwh": per_kwh, "grid_cost": grid_cost,
        "grid_margin": margin, "grid_worth": margin > 0,
    }


# ---------------------------------------------------------------------------
# Charging planner — mirrors plan(st) in depot-engine.js
# ---------------------------------------------------------------------------
def plan(st: dict) -> None:
    """Build per-slot charging schedules for all plugged-in vans.

    Priority: cheapest energy first — rooftop solar, then stored solar during
    the peak, then super off-peak grid, then off-peak; peak grid only for
    critical (short) vans.
    """
    cfg = st["cfg"]
    now = (st["t"] // SLOT) * SLOT
    slots = []

    store = 0.0
    if st["batt_cap"] > 0 and st["t"] < 21 * 60:
        store = max(0.0, st["batt"] - st["batt_cap"] * cfg["reserve"] / 100) * ETA_OUT

    for m in range(now, END_MIN, SLOT):
        p = period(m)
        sol = cfg["solar_kwp"] * solar_per_kwp(m + SLOT / 2, cfg.get("solar_profile"))
        store_kw = st["batt_kw"] if (p == "peak" and store > 0) else 0.0
        cap = max(0.0, cfg["limit"] - cfg["base"] - 2) + sol + store_kw
        slots.append({"m": m, "p": p, "price": PRICE[p], "solar": sol,
                      "solar_used": 0.0, "store_kw": store_kw, "store_used": 0.0,
                      "used": 0.0, "cap": cap})

    def eff(s, use_store):
        if s["solar"] - s["solar_used"] > 0.5:
            return 0.0
        if use_store and s["store_kw"] - s["store_used"] > 0.5 and store > 0.1:
            return 0.001
        return s["price"]

    st["store_for_ev"] = 0.0

    plugged = [c for c in st["cars"] if c.status != "Departed"]
    plugged.sort(key=lambda c: c.dep)

    for c in plugged:
        c.plan = {}
        win = [s for s in slots
               if s["m"] >= max(c.arrive, now) and s["m"] + SLOT <= c.dep]

        def fill(kwh, max_price, use_store):
            nonlocal store
            while kwh > 0.05:
                # among equal-cost slots, prefer the least-loaded (keeps peak demand low)
                candidates = [
                    s for s in win
                    if eff(s, use_store) <= max_price
                    and (c.plan.get(s["m"], 0.0)) < c.ch_kw - 0.01
                    and s["used"] < s["cap"] - (0 if use_store else s["store_kw"]) - 0.5
                ]
                candidates.sort(key=lambda s: (eff(s, use_store), s["used"], s["m"]))
                if not candidates:
                    break
                s = candidates[0]
                kw = min(
                    c.ch_kw - c.plan.get(s["m"], 0.0),
                    s["cap"] - (0 if use_store else s["store_kw"]) - s["used"],
                    max(MIN_A * VOLTS / 1000, kwh * 60 / SLOT),
                    c.ch_kw,
                )
                c.plan[s["m"]] = c.plan.get(s["m"], 0.0) + kw
                s["used"] += kw
                from_sun = min(kw, max(0.0, s["solar"] - s["solar_used"]))
                s["solar_used"] += from_sun
                from_store = 0.0
                if use_store:
                    from_store = min(kw - from_sun,
                                     max(0.0, s["store_kw"] - s["store_used"]),
                                     store * 60 / SLOT)
                s["store_used"] += from_store
                store -= from_store * SLOT / 60
                st["store_for_ev"] += from_store * SLOT / 60
                kwh -= kw * SLOT / 60
            return max(0.0, kwh)

        # must-have: route requirement (may use storage)
        c.short = fill(max(0.0, (c.need - c.soc) / 100 * c.cap), math.inf, True)
        # nice-to-have: top-up (never at peak, never from storage)
        if cfg.get("topup", True):
            fill(max(0.0, (TOPUP - max(c.soc, c.need)) / 100 * c.cap), PRICE["off"], False)

        if c.short > 0.5:
            _note(st, "agent",
                  f"{c.name} can't reach {c.need}% by {fmt_clock(c.dep)} within the "
                  f"site limit ({c.short:.0f} kWh short) — it will charge at every opportunity.")

    peak_net = max((s["used"] - s["solar"] - s["store_used"] for s in slots), default=0.0)
    peak_net = max(0.0, peak_net)
    st["sub_target"] = max(BEV1["block_kw"],
                           math.ceil(peak_net / BEV1["block_kw"] - 1e-9) * BEV1["block_kw"])


# ---------------------------------------------------------------------------
# Fleet planner — mirrors fleetPlanner(st) in depot-engine.js
# ---------------------------------------------------------------------------
def _route_kwh(c: Van) -> float:
    return (c.stops * c.drain + c.ret) / 100 * c.cap


def _need_pct(c: Van, kwh: float) -> int:
    from .fleet_simulator import FLOOR, RESERVE
    return math.ceil(kwh / c.cap * 100 + FLOOR + RESERVE)


def fleet_planner(st: dict) -> None:
    live = [c for c in st["cars"] if c.status != "Departed"]

    def is_short(c):
        return c.short > 0.5 or c.fault

    order = sorted(live, key=lambda c: c.slack)
    order_names = [c.name for c in order]

    proposals = []
    for a in [c for c in live if is_short(c)]:
        proj_a = a.soc if a.fault else a.need - a.short / a.cap * 100
        candidates = [
            c for c in live
            if c is not a and not is_short(c)
            and _route_kwh(c) < _route_kwh(a)
            and _need_pct(a, _route_kwh(c)) <= proj_a
            and _need_pct(c, _route_kwh(a)) <= 95
        ]
        candidates.sort(key=lambda c: _need_pct(c, _route_kwh(a)))
        why = (f"{a.name} has a charger fault" if a.fault
               else f"{a.name} is {a.short:.0f} kWh short for its {a.stops}-stop route")
        if candidates:
            b = candidates[0]
            proposals.append({
                "from": a.name, "to": b.name, "id": f"{a.name}>{b.name}",
                "text": (f"{why}. Proposal: swap routes — {a.name} takes {b.name}'s lighter "
                         f"{b.stops}-stop route and {b.name} takes the {a.stops}-stop route "
                         f"(needs {_need_pct(b, _route_kwh(a))}% by {fmt_clock(b.dep)}). "
                         "Needs dispatcher approval."),
            })

    late = [c for c in live if is_short(c)]
    n_short = len(late)
    key = (order_names[0] if order_names else "") + "|" + str(n_short) + "|" + ",".join(p["id"] for p in proposals)
    st["fleet"] = {"order": order_names, "proposals": proposals, "late": [c.name for c in late]}

    if key != st.get("fleet_key") and live:
        st["fleet_key"] = key
        priority_str = " → ".join(order_names[:3]) + (" …" if len(order_names) > 3 else "")
        msg = f"Charge priority: {priority_str} (tightest slack first)."
        if proposals:
            pass
        elif n_short:
            msg += (f" {n_short} van{'s' if n_short != 1 else ''} short of the route charge "
                    "and no safe route swap found — flagged for the dispatcher.")
        else:
            msg += " All vans on track — no route changes needed."
        _note(st, "planner", msg)
        for p in proposals:
            _note(st, "planner", p["text"])

    st["comms"] = []
    for c in late:
        delay = 60 if c.fault else max(5, math.ceil(c.short / CH_KW * 60 / 5) * 5)
        st["comms"].append({
            "id": f"late-{c.name}", "van": c.name,
            "text": (f"Your delivery may arrive about {delay} minutes later than planned. "
                     "We'll confirm your new window this morning."),
        })

    c_key = ",".join(d["id"] for d in st["comms"])
    if c_key != st.get("comms_key"):
        st["comms_key"] = c_key
        for d in st["comms"]:
            _note(st, "comms", f"Draft for {d['van']}'s customers (held for approval): \"{d['text']}\"")


# ---------------------------------------------------------------------------
# Depot agents (outage resilience, demand response, charger faults, battery health)
# mirrors depotAgents(st, x) in depot-engine.js
# ---------------------------------------------------------------------------
def _urgency(st: dict) -> list:
    plugged = [c for c in st["cars"] if c.status not in ("Away", "Departed")]
    return [{"name": c.name, "slack": round(c.slack), "soc": round(c.soc), "need": c.need}
            for c in sorted(plugged, key=lambda c: c.slack)]


def depot_agents(st: dict, x: dict) -> None:
    t = st["t"]
    soc = st["batt"] / st["batt_cap"] * 100 if st["batt_cap"] else 0.0

    # outage resilience
    if st["outage"]:
        load = x["ev_kw"] + x["bldg"] - x["solar"]
        run_h = (st["batt"] * ETA_OUT / load) if load > 0.5 else math.inf
        st["resil"] = {"state": "outage", "soc": soc, "runtime_h": run_h, "rank": _urgency(st)}
        if not st.get("resil_on"):
            st["resil_on"] = True
            st["resil_low"] = False
            if st["batt_cap"]:
                run_str = f"{run_h:.1f} h" if math.isfinite(run_h) else "indefinitely"
                _note(st, "resilience",
                      f"Outage: EV storage at {round(soc)}% plus {x['solar']:.0f} kW rooftop solar "
                      f"can carry the site about {run_str} at the current {max(0, load):.0f} kW net load. "
                      "Order of shedding: HVAC, then vans with the most slack, urgent vans last.")
            else:
                _note(st, "resilience", "Outage with no storage: the site is down until the grid returns.")
        if st["batt_cap"] and soc < 25 and not st.get("resil_low"):
            st["resil_low"] = True
            _note(st, "resilience", "Storage under 25% — non-urgent vans will wait; only urgent vans keep charging.")
    else:
        st["resil"] = {"state": "grid", "soc": soc, "runtime_h": None, "rank": _urgency(st)}
        if st.get("resil_on"):
            st["resil_on"] = False
            _note(st, "resilience", f"Grid is back. Storage at {round(soc)}%; refill handed to the Solar & Storage agent.")

    # demand response
    peak = x["per"] == "peak"
    if peak and not st.get("dr_on"):
        st["dr_on"] = True
        store_kw = st["batt_kw"] if (st["batt_cap"] and st["batt"] > st["batt_cap"] * st["cfg"]["reserve"] / 100) else 0.0
        plugged = [c for c in st["cars"] if c.status not in ("Away", "Departed")]
        paused = sum(max(0.0, c.max_a - c.amps) * VOLTS / 1000 for c in plugged)
        hv = HVAC_KW if st["hvac"] else 0
        st["dr"] = {"offer_kw": store_kw + paused + hv, "store": store_kw, "paused": paused, "hvac": hv}
        _note(st, "demand",
              f"Peak window: the site could offer about {st['dr']['offer_kw']:.0f} kW of flexibility to the utility "
              f"(storage {store_kw:.0f} kW + paused chargers {paused:.0f} kW + HVAC {hv} kW). "
              "Simulated — no demand-response program rates are used.")
    if not peak and st.get("dr_on") and t >= 21 * 60:
        st["dr_on"] = False
        _note(st, "demand",
              f"Peak over: {st['cost']['kwh']['peak']:.1f} kWh of EV charging was bought from the grid at peak price.")

    # charger faults
    for c in st["cars"]:
        if c.fault and c.status not in ("Away", "Departed") and not c.ticket:
            st["tickets"] = st.get("tickets", 0) + 1
            c.ticket = f"MT-{1000 + st['tickets']}"
            _note(st, "fault",
                  f"{c.name}: charger fault — 0 kW delivered while plugged in. "
                  f"Maintenance ticket {c.ticket} opened; the Fleet planner now treats {c.name} as unable to charge.")
            st["next_plan"] = t
        if not c.fault and c.ticket:
            _note(st, "fault",
                  f"{c.name}: charger back online — ticket {c.ticket} closed after {round(c.down_min or 0)} min of downtime.")
            c.ticket = None
            st["next_plan"] = t

    # battery health notes
    if not st.get("health_noted") and t >= START_MIN + 120:
        st["health_noted"] = True
        deep = [f"{c.name} ({round(c.soc0)}%)" for c in st["cars"] if c.soc0 <= 16]
        if deep:
            _note(st, "health",
                  f"Deep discharge on arrival: {', '.join(deep)}. "
                  "Returning below ~16% ages the battery — consider a shorter route or an earlier return.")

    if not st.get("peak_health") and t >= 21 * 60:
        st["peak_health"] = True
        pk = [f"{c.name} ({c.peak_kwh:.0f} kWh)" for c in st["cars"] if (c.peak_kwh or 0) > 1]
        if pk:
            _note(st, "health",
                  f"Vans charging during the 4–9 pm window: {', '.join(pk)}. "
                  f"EV storage and solar covered it where they could; {st['cost']['kwh']['peak']:.0f} kWh "
                  "was bought from the grid at peak price.")
        else:
            _note(st, "health", "No van needed to charge during the peak window tonight.")


# ---------------------------------------------------------------------------
# HVAC control — mirrors controlHvac(st) + hvacRule() in depot-engine.js
# ---------------------------------------------------------------------------
def control_hvac(st: dict) -> None:
    cfg = st["cfg"]
    ref = st.get("ref") if st.get("ref") is not None else cfg["trig"]
    retrig = ref * (1 - cfg["band"] / 100)
    was = st["hvac"]

    if st["outage"]:
        if st["hvac"]:
            _note(st, "resilience", "Grid outage: HVAC shed to keep the battery for critical loads and chargers.")
        st["hvac"] = False
        return

    mode = cfg.get("mode", "agent")
    if mode == "force":
        st["hvac"] = True
    elif mode == "standard":
        if not st["hvac"] and st["tin"] <= cfg["trig"]:
            st["hvac"] = True
        elif st["hvac"] and st["tin"] >= cfg["trig"] + STD_BAND:
            st["hvac"] = False
    else:  # agent mode
        if not st.get("engaged"):
            if st["tin"] <= cfg["trig"]:
                st["hvac"] = True
                st["engaged"] = True
                st["ref"] = st["tin"]
                _note(st, "agent",
                      f"Building thermostat triggered HVAC at {st['tin']:.1f} °C. "
                      f"Agent will stop it at {cfg['comfort']} °C and re-trigger at "
                      f"{st['ref'] * (1 - cfg['band'] / 100):.1f} °C ({cfg['band']}% below).")
        elif st["hvac"] and st["tin"] >= cfg["comfort"]:
            st["hvac"] = False
            st["suppressed"] = False
            _note(st, "agent", f"Indoor {st['tin']:.1f} °C is comfortable → HVAC off, {HVAC_KW} kW freed.")
        elif not st["hvac"] and st["tin"] <= retrig:
            st["hvac"] = True
            st["cycles"] = st.get("cycles", 0) + 1
            _note(st, "agent",
                  f"Indoor fell to {st['tin']:.1f} °C ({cfg['band']}% below the {ref:.1f} °C trigger) → HVAC re-triggered.")
        elif not st["hvac"] and st["tin"] <= cfg["trig"] and not st.get("suppressed"):
            st["suppressed"] = True
            _note(st, "agent",
                  f"Thermostat wants HVAC at {st['tin']:.1f} °C; agent holds it off until {retrig:.1f} °C.")

    if st["hvac"] != was and mode != "agent":
        _note(st, "gateway",
              f"HVAC {'ON (+' + str(HVAC_KW) + ' kW)' if st['hvac'] else 'OFF'} — "
              f"{'forced' if mode == 'force' else 'standard thermostat'}")


# ---------------------------------------------------------------------------
# Gateway allocation — mirrors allocate() + scaleGroup() in depot-engine.js
# ---------------------------------------------------------------------------
def _scale_group(group: list[Van], budget: float) -> float:
    if not group:
        return 0.0
    want = sum(c.want_a * VOLTS / 1000 for c in group)
    if want <= budget:
        for c in group:
            c.amps = c.want_a
        return want
    f = max(0.0, budget) / want
    for c in group:
        a = math.floor(c.want_a * f)
        c.amps = a if a >= MIN_A else 0
    used = sum(c.amps * VOLTS / 1000 for c in group)
    for c in sorted(group, key=lambda c: c.slack):
        while c.amps < c.want_a:
            step = MIN_A if c.amps == 0 else 1
            if used + step * VOLTS / 1000 > budget:
                break
            c.amps += step
            used += step * VOLTS / 1000
    return used


def allocate(cars: list[Van], avail: float) -> float:
    """Allocate available grid+solar kW across plugged-in vans.

    Priority: critical vans (tightest slack) first, then route-need group
    (proportional), then top-up group (proportional).
    """
    act = [c for c in cars if c.want_a > 0]
    for c in act:
        c.critical = c.soc < c.need and c.slack < CRIT_MIN
    used = 0.0
    for c in sorted([c for c in act if c.critical], key=lambda c: c.slack):
        a = min(c.want_a, math.floor(max(0.0, avail - used) * 1000 / VOLTS))
        c.amps = a if a >= MIN_A else 0
        used += c.amps * VOLTS / 1000
    used += _scale_group([c for c in act if not c.critical and c.soc < c.need], avail - used)
    return used + _scale_group([c for c in act if c.soc >= c.need], avail - used)


# ---------------------------------------------------------------------------
# Create simulation state — mirrors createSim(cfg) in depot-engine.js
# ---------------------------------------------------------------------------
def create_sim(cfg: dict) -> dict:
    """Initialise and return a simulation state dict.

    cfg keys (all optional unless noted):
      managed (bool)     — enable smart charging/storage/HVAC control
      limit (float)      — site breaker limit kW  (required)
      base (float)       — baseline building load kW  (required)
      solar_kwp (float)  — rooftop solar capacity kW
      solar_profile (list[float]) — 24-hour PVWatts profile (kW per kWp)
      batt_kwh (float)   — EV storage capacity kWh
      batt_kw (float)    — EV storage max charge/discharge rate kW
      reserve (float)    — backup reserve % of battery (default 20)
      trig (float)       — HVAC trigger temperature °C (default 16)
      comfort (float)    — HVAC stop temperature °C (default 20)
      band (float)       — HVAC re-trigger band % below trigger (default 5)
      mode (str)         — 'agent' | 'standard' | 'force'
      bldg_price (dict)  — {min, max} $/kWh for building electricity
      topup (bool)       — whether to top up vans to 90% (default True)
      grid_top_up (bool) — whether to top up battery from cheap grid (default True)
      storage_use (str)  — 'peak' | 'peak+night'
      arrivals (dict)    — override arrival soc/plug per van name
      seed (int)         — random seed for noise
      quiet (bool)       — suppress event logging
      wx (dict)          — Open-Meteo weather payload
      day (bool)         — start at 06:00 (delivery-day run)
      snap (bool)        — cold-snap flag
    """
    cfg = dict(cfg)
    cfg.setdefault("solar_kwp", 0)
    cfg.setdefault("batt_kwh", 0)
    cfg.setdefault("batt_kw", 0)
    cfg.setdefault("reserve", 20)
    cfg.setdefault("trig", 16)
    cfg.setdefault("comfort", 20)
    cfg.setdefault("band", 5)
    cfg.setdefault("mode", "agent")
    cfg.setdefault("bldg_price", {"min": 0.12, "max": 0.22})
    cfg.setdefault("topup", True)
    cfg.setdefault("grid_top_up", True)
    cfg.setdefault("storage_use", "peak")
    cfg.setdefault("managed", True)

    wear = storage_wear(cfg)
    if wear and not wear["grid_worth"] and cfg.get("grid_top_up", True):
        cfg["grid_top_up"] = False

    # simple LCG noise (seed=11 matches JS default rng(11))
    seed_val = [cfg.get("seed", 11)]

    def noise():
        seed_val[0] = (seed_val[0] + 0x6D2B79F5) & 0xFFFFFFFF
        t = seed_val[0] ^ (seed_val[0] >> 15)
        t = (math.imul_py(t, 1 | seed_val[0]) & 0xFFFFFFFF)
        t = (t + math.imul_py(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF
        t = ((t ^ (t >> 14)) & 0xFFFFFFFF)
        return (t / 4294967296 - 0.5) * 3

    t0 = DAY_START_MIN if cfg.get("day") else START_MIN

    st: dict = {
        "cfg": cfg,
        "wear": wear,
        "t": t0,
        "done": False,
        "events": [],
        "hist": [],
        "snap": cfg.get("snap", False),
        "outage": False,
        "noise": noise,
        "cars": make_fleet(cfg.get("arrivals")),
        "tin": 21.5,
        "hvac": False,
        "engaged": False,
        "ref": None,
        "suppressed": False,
        "hvac_kwh": 0.0,
        "hvac_min": 0.0,
        "cycles": 0,
        "batt_cap": cfg["batt_kwh"],
        "batt_kw": cfg["batt_kw"],
        "batt": 0.0,
        "batt_mode": "idle",
        "sub_target": BEV1["block_kw"],
        "cost": {
            "ev_usd": 0.0, "bldg_usd": 0.0, "precharge_usd": 0.0,
            "kwh": {"peak": 0.0, "off": 0.0, "super": 0.0},
            "solar_kwh": 0.0, "solar_to_ev": 0.0, "export_kwh": 0.0,
            "batt_in": 0.0, "batt_out": 0.0, "ev_kwh": 0.0,
        },
        "peak_ev_import": 0.0,
        "peak_site": 0.0,
        "trips": 0,
        "next_plan": t0,
        "last_period": None,
        "store_for_ev": 0.0,
        "fleet": {},
        "comms": [],
    }

    if wear and cfg.get("managed"):
        if wear["grid_worth"]:
            _note(st, "solar",
                  f"Storage wear: {wear['chem']} at ${wear['usd_per_kwh']}/kWh lasts about "
                  f"{wear['cycles80']:,} cycles to 80% health, so each kWh through it costs "
                  f"${wear['wear_per_kwh']:.3f}. "
                  f"Buying super off-peak power (${PRICE['super']}/kWh, ${wear['grid_cost']:.3f} "
                  f"after losses) to use at peak (${PRICE['peak']}/kWh) still nets "
                  f"${wear['grid_margin']:.3f}/kWh after wear — grid top-up stays on.")
        else:
            _note(st, "solar",
                  f"Grid top-up would net ${wear['grid_margin']:.3f}/kWh after wear — "
                  "not worth it, so storage fills from rooftop solar only.")

    # pre-charge battery (morning solar + optional cheap grid) before vans arrive
    if st["batt_cap"] > 0 and not cfg.get("day"):
        soc = st["batt_cap"] * cfg["reserve"] / 100
        from_sun = 0.0
        for m in range(7 * 60, START_MIN, SLOT):
            add = min(
                cfg["solar_kwp"] * solar_per_kwp(m + SLOT / 2, cfg.get("solar_profile")) * SLOT / 60 * ETA_IN,
                st["batt_cap"] - soc,
                st["batt_kw"] * SLOT / 60,
            )
            soc += add
            from_sun += add
        grid = 0.0
        if cfg.get("grid_top_up", True):
            grid = min(max(0.0, st["batt_cap"] - soc) / ETA_IN, st["batt_kw"] * 4)
        st["batt"] = min(st["batt_cap"], soc + grid * ETA_IN)
        st["cost"]["precharge_usd"] = grid * PRICE["super"]
        st["cost"]["kwh"]["super"] += grid
        st["peak_ev_import"] = grid / 4
        _note(st, "solar",
              f"EV storage starts the afternoon at {round(st['batt'] / st['batt_cap'] * 100)}%: "
              f"{from_sun:.0f} kWh from this morning's rooftop solar"
              + (f" + {grid:.0f} kWh from the grid at super off-peak (${PRICE['super']}/kWh)" if grid > 0.5 else "")
              + ".")
    elif st["batt_cap"] > 0 and cfg.get("day"):
        st["batt"] = st["batt_cap"] * cfg["reserve"] / 100
        _note(st, "solar",
              f"Day starts with EV storage at {round(cfg['reserve'])}% (the outage reserve). "
              "Rooftop solar refills it from sunrise.")

    return st


# tiny helper that matches JS Math.imul (32-bit signed multiply)
def _imul_py(a: int, b: int) -> int:
    return ((a & 0xFFFFFFFF) * (b & 0xFFFFFFFF)) & 0xFFFFFFFF


# patch math module so noise() can use it without import inside lambda
import math as _math_module
_math_module.imul_py = _imul_py  # type: ignore


# ---------------------------------------------------------------------------
# Simulation step — mirrors step(st, dt) in depot-engine.js
# ---------------------------------------------------------------------------
def step(st: dict, dt: float = 5) -> None:
    """Advance the simulation by dt minutes."""
    cfg = st["cfg"]
    t = st["t"]
    per = period(t)
    price = PRICE[per]
    h = dt / 60

    arrived_now: list[Van] = []
    for c in st["cars"]:
        if c.status == "Away" and t >= c.arrive:
            c.status = "Charging"
            st["next_plan"] = t
            arrived_now.append(c)
            _note(st, "gateway",
                  f"{c.name} plugged in at {fmt_clock(t)} with {c.soc:.0f}% — needs {c.need}% by {fmt_clock(c.dep)}.")
        if c.status not in ("Away", "Departed") and t >= c.dep:
            c.met = c.soc >= c.need - 0.5
            c.status = "Departed"
            c.amps = 0
            _note(st, "gateway",
                  f"{c.name} departs at {c.soc:.0f}% — "
                  f"{'route requirement met' if c.met else 'MISSED ' + str(c.need) + '% requirement'}.")

    if per != st["last_period"]:
        msg = f"{PERIOD_NAME[per]} — ${price:.3f}/kWh."
        if cfg.get("managed") and per == "peak":
            msg += " Chargers pause unless a van is critical; the battery carries the site."
        if cfg.get("managed") and st["last_period"] == "peak":
            msg += " Planned charging resumes."
        _note(st, "agent", msg)
        st["last_period"] = per

    if cfg.get("managed") and t >= st["next_plan"]:
        plan(st)
        fleet_planner(st)
        st["next_plan"] = t + 60
        for c in arrived_now:
            _charge_decision(st, c)

    control_hvac(st)

    noise_v = st["noise"]()
    bldg = max(0.0, cfg["base"] + noise_v + (HVAC_KW if st["hvac"] else 0))
    solar = cfg["solar_kwp"] * solar_per_kwp(t + dt / 2, cfg.get("solar_profile"))
    slot = (t // SLOT) * SLOT

    for c in st["cars"]:
        c.amps = 0
        c.critical = False
        if c.status in ("Away", "Departed") or c.fault:
            c.max_a = 0
        else:
            c.max_a = want_amps(c)
        c.slack = c.dep - t - mins_to_fill(c)

        if not c.max_a:
            c.want_a = 0
            continue
        if not cfg.get("managed"):
            c.want_a = c.max_a
            continue

        kw = c.plan.get(slot, 0.0)
        if c.soc < c.need and c.slack < CRIT_MIN / 2:
            kw = c.ch_kw  # fell behind plan: catch up at the vehicle's own charger rate
        c.want_a = min(c.max_a, round(kw * 1000 / VOLTS))
        if 0 < c.want_a < MIN_A:
            c.want_a = MIN_A

    # free solar beyond plan tops vans up
    if cfg.get("managed"):
        spare = solar - sum(c.want_a * VOLTS / 1000 for c in st["cars"])
        for c in sorted(st["cars"], key=lambda c: c.soc):
            if spare < MIN_A * VOLTS / 1000 or c.max_a <= c.want_a:
                continue
            add = min(c.max_a - c.want_a, math.floor(spare * 1000 / VOLTS))
            if c.want_a + add >= MIN_A:
                c.want_a += add
                spare -= add * VOLTS / 1000

    reserve_kwh = st["batt_cap"] * cfg["reserve"] / 100

    # post-outage recovery
    if st.get("was_outage") and not st["outage"] and st["batt_cap"] > 0 and st["batt"] < st["batt_cap"] - 0.5:
        st["recovering"] = True
        _note(st, "solar", "Grid restored — recharging EV storage from rooftop solar + the grid.")
    st["was_outage"] = st["outage"]
    if st.get("recovering") and (st["batt"] >= st["batt_cap"] - 0.5 or st["outage"]):
        st["recovering"] = False

    batt_avail = 0.0
    if st["batt_cap"] > 0:
        batt_avail = min(st["batt_kw"],
                         max(0.0, st["batt"] - (0 if st["outage"] else reserve_kwh)) * ETA_OUT / h)

    if not cfg.get("managed"):
        ev_cap = 0.0 if st["outage"] else math.inf
    elif st["outage"]:
        ev_cap = max(0.0, solar + batt_avail - bldg)
    else:
        ev_cap = max(0.0, cfg["limit"] - bldg) + solar + batt_avail

    ev_kw = allocate(st["cars"], ev_cap)
    office_only = ev_kw < 0.5
    st["office_only"] = office_only

    # ------- battery dispatch -------
    to_batt = grid_to_batt = from_batt = batt_to_ev = batt_to_bldg = 0.0
    mode = "idle"

    solar_to_ev = min(solar, ev_kw)
    surplus = solar - solar_to_ev
    room = max(0.0, st["batt_cap"] - st["batt"]) / ETA_IN / h if st["batt_cap"] > 0 else 0.0

    solar_to_batt = solar_to_bldg = 0.0
    if st["outage"]:
        solar_to_bldg = min(surplus, bldg) if cfg.get("managed") else 0.0
        surplus -= solar_to_bldg
        solar_to_batt = min(surplus, st["batt_kw"], room)
        surplus -= solar_to_batt
    else:
        solar_to_batt = min(surplus, st["batt_kw"], room)
        surplus -= solar_to_batt
        solar_to_bldg = min(surplus, bldg) if cfg.get("managed") else 0.0
        surplus -= solar_to_bldg

    deficit = ev_kw - solar_to_ev
    bldg_need = bldg - solar_to_bldg

    if st["batt_cap"] > 0:
        to_batt = solar_to_batt
        if to_batt > 0.2:
            mode = "solar"

        if st["outage"]:
            from_batt = min(deficit + bldg_need, batt_avail)
            if from_batt > 0.2:
                mode = "backup"
        else:
            over = max(0.0, bldg_need + deficit - cfg["limit"])
            spare_batt = max(0.0,
                             (st["batt"] - reserve_kwh) * ETA_OUT
                             - max(0.0, (st["store_for_ev"] or 0) - deficit * h))
            peak_fair = max(0.0, st["batt"] - reserve_kwh) * ETA_OUT / max(0.25, (21 * 60 - t) / 60)
            if per == "peak":
                cover = deficit + min(bldg_need, spare_batt / h, max(0.0, peak_fair - deficit))
            elif cfg.get("storage_use") == "peak+night" and t >= 21 * 60:
                cover = deficit
            else:
                cover = 0.0
            if st.get("recovering"):
                cover = 0.0
            from_batt = min(max(over, cover), batt_avail)
            if from_batt > 0.2:
                mode = "shave" if over > cover else ("peak" if per == "peak" else "night")

            # fill battery before peak (cheap grid if allowed)
            want = (st["batt_cap"] if st.get("recovering")
                    else st["batt_cap"] if (office_only and per != "peak" and cfg.get("grid_top_up", True))
                    else st["batt_cap"] if (t < 16 * 60 and per != "peak" and cfg.get("grid_top_up", True))
                    else reserve_kwh if t >= 21 * 60
                    else 0.0)
            if from_batt < 0.2 and st["batt"] < want - 0.5:
                head = min(cfg["limit"] - bldg_need - deficit, st["sub_target"] - deficit)
                grid_to_batt = max(0.0, min(st["batt_kw"] - to_batt, head, room - to_batt,
                                            (want - st["batt"]) / ETA_IN / h))
                if grid_to_batt > 0.2:
                    mode = "solar+grid" if mode == "solar" else "grid"

        batt_to_ev = min(from_batt, deficit)
        batt_to_bldg = from_batt - batt_to_ev
        if per == "peak":
            st["store_for_ev"] = max(0.0, (st["store_for_ev"] or 0) - batt_to_ev * h)
        st["batt"] = min(st["batt_cap"],
                         max(0.0, st["batt"] + (to_batt + grid_to_batt) * ETA_IN * h - from_batt / ETA_OUT * h))

    ev_import = 0.0 if st["outage"] else max(0.0, deficit - batt_to_ev + grid_to_batt)
    bldg_import = 0.0 if st["outage"] else max(0.0, bldg_need - batt_to_bldg)
    site = ev_import + bldg_import

    if not st["outage"] and site > cfg["limit"] + 0.5:
        st["trips"] += 1
        _note(st, "gateway", f"BREAKER TRIP — {site:.1f} kW over the {cfg['limit']} kW limit.")

    st["mode_now"] = mode

    # log battery mode changes
    if (cfg.get("managed") and st["batt_cap"] > 0 and mode != "idle"
            and mode != st.get("batt_mode") and (t - st.get("batt_log_t", 0) >= 30 or mode == "backup")):
        msgs = {
            "solar": "EV storage charging from rooftop solar (free).",
            "grid": f"EV storage topping up from the grid at {PERIOD_NAME[per].lower()} price, ready for the evening peak.",
            "solar+grid": "EV storage charging from rooftop solar and cheap grid power.",
            "peak": "EV storage powering the chargers through the peak — no peak-price grid power bought.",
            "night": "EV storage supplying chargers with leftover stored solar instead of buying grid power.",
            "shave": f"EV storage discharging to keep the site under {cfg['limit']} kW.",
            "backup": "Grid outage — EV storage and rooftop solar are powering the depot.",
        }
        msg = msgs.get(mode, "")
        if msg:
            if office_only and mode in ("grid", "solar+grid", "solar"):
                msg += " Only the Corporate Office is drawing power, so storage is being refilled, balanced under the site limit."
            batt_pct = round(st["batt"] / st["batt_cap"] * 100)
            _note(st, "solar", f"{msg} ({batt_pct}%)")
        st["batt_mode"] = mode
        st["batt_log_t"] = t

    # peak balance log (hourly during peak)
    if (cfg.get("managed") and st["batt_cap"] > 0 and per == "peak"
            and math.floor(t / 60) != st.get("peak_note_h")):
        st["peak_note_h"] = math.floor(t / 60)
        lasts = max(0.0, st["batt"] - reserve_kwh) * ETA_OUT / from_batt * 60 if from_batt > 0.5 else None
        msg = (f"Peak balance: EV storage {from_batt:.0f} kW + grid {site:.0f} kW "
               f"(site limit {cfg['limit']} kW)")
        if lasts is not None:
            msg += f"; at this rate storage lasts about {round(min(lasts, 21 * 60 - t))} min of the {round(21 * 60 - t)} min left in the peak"
        else:
            msg += "; storage is idle"
        _note(st, "solar", msg + ".")

    # sun share across all chargers
    sun_share = solar_to_ev / ev_kw if ev_kw > 0 else 0.0

    for c in st["cars"]:
        if c.status in ("Away", "Departed"):
            continue
        if c.fault:
            c.down_min = (c.down_min or 0) + dt
        prev = c.status
        if c.soc >= c.need:
            c.status = "Ready"
        elif c.amps == 0:
            if cfg.get("managed") and not c.critical and c.plan.get(slot, 0) == 0 and not st["outage"]:
                c.status = "Scheduled"
            else:
                c.status = "Paused"
        elif c.amps < c.want_a - 1:
            c.status = "Throttled"
        else:
            c.status = "Charging"

        if c.status != prev and c.status in ("Throttled", "Paused", "Ready"):
            _note(st, "gateway",
                  f"{c.name} → {c.status}"
                  + (f" (reached {c.need}%)" if c.status == "Ready" else f" at {c.amps} A"))

        if c.critical and not c.was_crit:
            _note(st, "agent",
                  f"{c.name} is critical (slack {round(c.slack)} min to {fmt_clock(c.dep)}) → "
                  f"charged first{', even at peak price' if per == 'peak' else ''}.")
        c.was_crit = c.critical

        kwh = c.amps * VOLTS / 1000 * h
        c.kwh += kwh
        c.soc = min(100.0, c.soc + kwh / c.cap * 100)
        c.want_kwh = (c.want_kwh or 0) + c.want_a * VOLTS / 1000 * h
        c.cost_kwh = (c.cost_kwh or 0) + kwh
        c.cost = (c.cost or 0) + kwh * (1 - sun_share) * price
        if per == "peak":
            c.peak_kwh = (c.peak_kwh or 0) + kwh

    if cfg.get("managed"):
        depot_agents(st, {"per": per, "ev_kw": ev_kw, "bldg": bldg, "solar": solar, "batt_avail": batt_avail})

    # accumulate cost
    k = st["cost"]
    k["ev_usd"] += ev_import * h * price
    k["kwh"][per] += ev_import * h
    k["bldg_usd"] += bldg_import * h * (cfg["bldg_price"]["max"] if per == "peak" else cfg["bldg_price"]["min"])
    k["solar_kwh"] += solar * h
    k["solar_to_ev"] += solar_to_ev * h
    k["solar_to_bldg"] = k.get("solar_to_bldg", 0) + solar_to_bldg * h
    k["export_kwh"] += surplus * h
    k["batt_in"] += (to_batt + grid_to_batt) * h
    k["batt_out"] += from_batt * h
    k["ev_kwh"] += ev_kw * h
    if st["hvac"]:
        st["hvac_kwh"] += HVAC_KW * h
        st["hvac_min"] += dt
    st["peak_ev_import"] = max(st["peak_ev_import"], ev_import)
    st["peak_site"] = max(st["peak_site"], site)

    # building thermal model (1-minute resolution within the step)
    out_t = outdoor_temp(t, cfg.get("wx")) + (SNAP if st.get("snap") else 0)
    for _ in range(int(dt)):
        st["tin"] = min(MAX_TIN, st["tin"] - K * (st["tin"] - out_t) + (HEAT if st["hvac"] else 0))

    st["hist"].append({
        "t": t, "bldg": bldg, "ev": ev_kw, "solar": solar,
        "to_batt": to_batt + grid_to_batt, "solar_to_batt": to_batt,
        "grid_to_batt": grid_to_batt, "solar_to_ev": solar_to_ev,
        "solar_to_bldg": solar_to_bldg, "export_kw": surplus,
        "from_batt": from_batt, "batt_to_ev": batt_to_ev,
        "batt_to_bldg": batt_to_bldg, "bldg_import": bldg_import,
        "grid": site, "ev_import": ev_import,
        "batt": st["batt"] / st["batt_cap"] * 100 if st["batt_cap"] else None,
        "tin": st["tin"], "tout": out_t, "hvac": st["hvac"], "per": per, "price": price,
    })

    st["t"] += dt
    if st["t"] >= END_MIN:
        st["done"] = True


# ---------------------------------------------------------------------------
# Charge decision log — mirrors chargeDecision() in depot-engine.js
# ---------------------------------------------------------------------------
def _charge_decision(st: dict, c: Van) -> None:
    cfg = st["cfg"]
    t = st["t"]
    per = period(t)
    price = PRICE[per]
    need_kwh = max(0.0, (c.need - c.soc) / 100 * c.cap)
    sun = cfg["solar_kwp"] * solar_per_kwp(t, cfg.get("solar_profile"))
    headroom = max(0.0, cfg["limit"] - cfg["base"] - (HVAC_KW if st["hvac"] else 0))
    slack = c.dep - t - mins_to_fill(c)

    slot = (t // SLOT) * SLOT
    now_kw = c.plan.get(slot, 0.0)
    first = _plan_summary_first(c)

    if need_kwh <= 0.5:
        verdict = (f"no charge needed for the route; a cheap top-up is planned from {fmt_clock(first['start'])}"
                   if first else "no charge needed")
    elif c.short > 0.5:
        verdict = f"charge now at full available power — it cannot reach {c.need}% in time ({c.short:.0f} kWh short)"
    elif now_kw > 0.05:
        if sun >= now_kw:
            why = "rooftop solar covers it"
        elif per == "peak":
            why = "EV storage carries the peak"
        else:
            why = "this is a cheap window"
        verdict = f"charge now at {now_kw:.1f} kW — {why}"
    elif first:
        sun_then = cfg["solar_kwp"] * solar_per_kwp(first["start"], cfg.get("solar_profile"))
        stored = st["batt_cap"] > 0 and st["batt"] > st["batt_cap"] * cfg["reserve"] / 100 + 5
        if first["p"] == "peak":
            source = "rooftop solar" if sun_then > 1 else ("EV storage" if stored else "the grid")
            when = f"peak window, but served by {source} instead of buying at ${PRICE['peak']:.3f}/kWh"
        else:
            pname = PERIOD_NAME[first["p"]].split(" (")[0].lower()
            when = f"{pname}, ${PRICE[first['p']]:.3f}/kWh"
        verdict = f"wait and charge from {fmt_clock(first['start'])} ({when}) — {round(max(0, slack))} min of slack before departure"
    else:
        verdict = "no workable window found — flagged to the dispatcher"

    text = (f"{c.name} plugged in at {fmt_clock(t)}: {c.soc:.0f}% now, needs {c.need}% by {fmt_clock(c.dep)} "
            f"({need_kwh:.0f} kWh). Price now ${price:.3f}/kWh, solar {sun:.0f} kW, "
            f"{headroom:.0f} kW of grid capacity free after the Corporate Office. Decision: {verdict}.")
    decisions = st.setdefault("decisions", [])
    decisions.insert(0, {"t": t, "van": c.name, "verdict": verdict, "text": text})
    while len(decisions) > 8:
        decisions.pop()
    _note(st, "agent", text)


def _plan_summary_first(c: Van) -> Optional[dict]:
    ms = sorted(m for m, kw in c.plan.items() if kw > 0.05)
    if not ms:
        return None
    m0 = ms[0]
    end = m0 + SLOT
    p = period(m0)
    kwh = c.plan[m0] * SLOT / 60
    for m in ms[1:]:
        if m == end and period(m) == p:
            end = m + SLOT
            kwh += c.plan[m] * SLOT / 60
        else:
            break
    return {"start": m0, "end": end, "p": p, "kwh": kwh}


# ---------------------------------------------------------------------------
# Cost billing — mirrors costs(st) in depot-engine.js
# ---------------------------------------------------------------------------
def costs(st: dict) -> dict:
    k = st["cost"]
    blocks = max(1, math.ceil(st["peak_ev_import"] / BEV1["block_kw"] - 1e-9))
    ev_energy = k["ev_usd"] + k["precharge_usd"]
    nightly = ev_energy + k["bldg_usd"]
    sub = blocks * BEV1["block_usd"]
    wear_night = k["batt_out"] * st["wear"]["wear_per_kwh"] if st.get("wear") else 0.0
    return {
        "wear_usd_night": round(wear_night, 2),
        "wear_usd_month": round(wear_night * 30),
        "monthly_net_of_wear_usd": round(nightly * 30 + sub + wear_night * 30),
        "storage_cycles_night": round(k["batt_out"] / st["batt_cap"], 2) if st["batt_cap"] else 0,
        "ev_energy_usd": round(ev_energy, 2),
        "building_energy_usd": round(k["bldg_usd"], 2),
        "nightly_usd": round(nightly, 2),
        "subscription_blocks": blocks,
        "subscription_usd_month": round(sub, 2),
        "monthly_usd": round(nightly * 30 + sub),
        "grid_kwh": {
            "peak": round(k["kwh"]["peak"], 1),
            "off": round(k["kwh"]["off"], 1),
            "super": round(k["kwh"]["super"], 1),
        },
        "solar_kwh": round(k["solar_kwh"], 1),
        "solar_to_ev_kwh": round(k["solar_to_ev"], 1),
        "solar_to_building_kwh": round(k.get("solar_to_bldg", 0), 1),
        "solar_export_kwh": round(k["export_kwh"], 1),
        "battery_out_kwh": round(k["batt_out"], 1),
        "ev_kwh": round(k["ev_kwh"], 1),
        "peak_ev_import_kw": round(st["peak_ev_import"], 1),
        "peak_site_kw": round(st["peak_site"], 1),
        "hvac_kwh": round(st["hvac_kwh"], 1),
        "trips": st["trips"],
    }


# ---------------------------------------------------------------------------
# High-level runners — mirrors runFull() + baselineCfg() in depot-engine.js
# ---------------------------------------------------------------------------
def run_full(cfg: dict, dt: float = 5) -> dict:
    """Run a complete overnight simulation and return the final state."""
    st = create_sim({**cfg, "quiet": True})
    while not st["done"]:
        step(st, dt)
    return st


def baseline_cfg(cfg: dict) -> dict:
    """Return the 'without this system' config: unmanaged, no solar, no battery."""
    return {
        **cfg,
        "managed": False,
        "solar_kwp": 0,
        "batt_kwh": 0,
        "batt_kw": 0,
        "mode": "force" if cfg.get("mode") == "force" else "standard",
        "quiet": True,
    }
