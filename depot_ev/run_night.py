"""run_night.py — Entry point: simulate one overnight charging session and print a summary.

Usage:
    python -m depot_ev.run_night

Runs two scenarios:
  1. With system  — 60 kW solar, 100 kWh / 50 kW EV storage, managed charging
  2. Without system — unmanaged, no solar, no battery (the BEV-1 baseline)

Expected output (approximate, matching the Depot web page):
  With system:    ~$2,000/month
  Without system: ~$4,212/month
"""
from __future__ import annotations

import json

from .gateway_controller import run_full, baseline_cfg, costs, BEV1
from .fleet_simulator import FLEET_DEFS, need_of, Van


# ---------------------------------------------------------------------------
# Reference configuration — matches the Depot page defaults
# ---------------------------------------------------------------------------
BASE_CFG = {
    # site electrical — updated for 7-vehicle fleet with 2 Tesla Semis (50 kW chargers each).
    # Max simultaneous draw: 2×50 + 5×7.68 ≈ 138 kW; limit set to 150 kW.
    "limit": 150,           # kW site breaker limit
    "base": 8,              # kW baseline building load (Corporate Office)
    "bldg_price": {"min": 0.19139, "max": 0.33947},  # $/kWh — DEFAULT_TARIFF in index.html (OpenEI URDB, Oct 2026)

    # solar + storage — matches DEFAULT_SETUP in index.html (solarKw:60, battKwh:100, battKw:50)
    "solar_kwp": 60,        # kW of rooftop solar panels
    "batt_kwh": 100,        # kWh EV storage capacity
    "batt_kw": 50,          # kW EV storage charge/discharge rate
    "reserve": 20,          # % backup reserve

    # HVAC — matches UI defaults in index.html (trig:20, comfort:21, band:5)
    "trig": 20,             # °C trigger temperature
    "comfort": 21,          # °C comfortable temperature (HVAC stops here)
    "band": 5,              # % below trigger for re-trigger

    # charging behaviour
    "managed": True,
    "mode": "agent",
    "topup": True,
    "grid_top_up": True,
    "storage_use": "peak",
}


def _vehicle_summary(st: dict) -> list[dict]:
    return [
        {
            "name": c.name,
            "soc_arrival": round(c.soc0),
            "soc_departure": round(c.soc),
            "need": c.need,
            "ready": c.met is True,
            "met": c.met,
            "kwh_charged": round(c.kwh, 1),
        }
        for c in st["cars"]
    ]


def _print_divider(char="─", width=60):
    print(char * width)


def run_night_summary(cfg: dict | None = None) -> dict:
    """Run both scenarios, print a formatted summary, and return the result dict."""
    cfg = {**BASE_CFG, **(cfg or {})}

    print()
    _print_divider("═")
    print("  Depot EV — overnight charging simulation")
    _print_divider("═")

    # --- with system ---
    st_with = run_full(cfg)
    c_with = costs(st_with)

    # --- without system (baseline) ---
    st_base = run_full(baseline_cfg(cfg))
    c_base = costs(st_base)

    savings_nightly = c_base["nightly_usd"] - c_with["nightly_usd"]
    savings_monthly = c_base["monthly_usd"] - c_with["monthly_usd"]

    vehicles = _vehicle_summary(st_with)
    n_ready = sum(1 for v in vehicles if v["ready"])
    n_total = len(vehicles)

    # build the payload the web app / Orchestrate agent expects
    result = {
        "site_limit_kw": cfg["limit"],
        "solar_kwp": cfg["solar_kwp"],
        "batt_kwh": cfg["batt_kwh"],
        "vehicles": vehicles,
        "costs": {
            "with_system": c_with,
            "without_system": c_base,
            "nightly_savings_usd": round(savings_nightly, 2),
            "monthly_savings_usd": round(savings_monthly),
        },
        "breaker_trips": st_with["trips"],
        "peak_ev_import_kw": c_with["peak_ev_import_kw"],
        "peak_site_kw": c_with["peak_site_kw"],
    }

    # --- formatted output ---
    print(f"\n  Fleet ({n_ready}/{n_total} vans ready for their routes)")
    _print_divider()
    for v in vehicles:
        tick = "✓" if v["ready"] else "✗"
        print(f"  {tick}  {v['name']:<10}  arrival {v['soc_arrival']:>3}%  "
              f"→  departure {v['soc_departure']:>3}%  (need {v['need']}%)  "
              f"  {v['kwh_charged']:.1f} kWh charged")

    print(f"\n  Energy  (with system: {cfg['solar_kwp']} kW solar + {cfg['batt_kwh']} kWh storage)")
    _print_divider()
    g = c_with["grid_kwh"]
    print(f"  Grid bought — super off-peak: {g['super']:.1f} kWh  |  "
          f"off-peak: {g['off']:.1f} kWh  |  peak: {g['peak']:.1f} kWh")
    print(f"  Solar production: {c_with['solar_kwh']:.1f} kWh  "
          f"(to EVs: {c_with['solar_to_ev_kwh']:.1f}  "
          f"to building: {c_with['solar_to_building_kwh']:.1f}  "
          f"exported: {c_with['solar_export_kwh']:.1f})")
    print(f"  Peak site demand: {c_with['peak_site_kw']:.1f} kW  "
          f"(site limit {cfg['limit']} kW)  "
          f"  Breaker trips: {st_with['trips']}")
    print(f"  EV subscription blocks: {c_with['subscription_blocks']} × "
          f"${BEV1['block_usd']:.2f}/10 kW = ${c_with['subscription_usd_month']:.2f}/month")

    print(f"\n  Cost")
    _print_divider()
    print(f"  Nightly  — with system:     ${c_with['nightly_usd']:>7.2f}")
    print(f"  Nightly  — without system:  ${c_base['nightly_usd']:>7.2f}")
    print(f"  Nightly  savings:           ${savings_nightly:>7.2f}")
    print()
    print(f"  Monthly  — with system:     ${c_with['monthly_usd']:>7,}")
    print(f"  Monthly  — without system:  ${c_base['monthly_usd']:>7,}")
    print(f"  Monthly  savings:           ${savings_monthly:>7,}")

    _print_divider("═")
    print()

    return result


if __name__ == "__main__":
    result = run_night_summary()
    # also generate a brief if watsonx is configured
    try:
        from .watsonx_reporter import generate_brief
        brief = generate_brief(result)
        print(f"  Morning brief ({brief['source']}):")
        print("  " + brief["text"].replace("\n", "\n  "))
        print()
    except Exception as e:
        pass  # watsonx not configured — skip silently
