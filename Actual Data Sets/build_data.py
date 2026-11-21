"""Build the derived datasets for the Depot EV agents from the raw files in ../Raw Data Sets.

Reads (never modifies):
  Raw Data Sets/archive (4)/ev_battery_health.csv   synthetic battery degradation (CC0)
  Raw Data Sets/EVChargingStationUsage.csv      City of Palo Alto charging sessions 2011-2020 (real)

Writes into this folder:
  battery_fade_by_chemistry.csv / .json         Battery health agent
  arrival_profile_by_hour.csv                   Power agent stress test
  dwell_energy_quantiles.csv                    Power / Fleet planner stress test
  palo_alto_session_sample.csv                  seeded sample of anonymised sessions
  build_report.json                             row counts and filters, for the docs
  ../reference-data.js                          the same tables as a script the app loads (REFDATA)

Run:  python3 -I "Actual Data Sets/build_data.py"     (stdlib only)
"""
import csv, json, os, random, statistics as st, datetime as dt
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "Raw Data Sets")
BATTERY = os.path.join(RAW, "archive (4)", "ev_battery_health.csv")
PALO = os.path.join(RAW, "EVChargingStationUsage.csv")
PALO_YEARS = range(2016, 2020)   # full years after the ramp-up and before 2020 disruption
SEED = 42
report = {}


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def write_csv(name, header, rows):
    with open(os.path.join(HERE, name), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def pct(sorted_vals, q):
    """Linear-interpolated percentile (q in 0-100) of a sorted list."""
    k = (len(sorted_vals) - 1) * q / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


# ---------------------------------------------------------------- battery
def fade_rate(points):
    """Least-squares fade per cycle through the origin: fade% = k * cycles."""
    sxx = sum(c * c for c, _ in points)
    return sum(c * f for c, f in points) / sxx if sxx else None


def build_battery():
    rows = list(csv.DictReader(open(BATTERY)))
    pts = []
    for x in rows:
        c, s, fast, dod = num(x["cycle_count"]), num(x["state_of_health_pct"]), num(x["fast_charge_ratio"]), num(x["avg_depth_of_discharge_pct"])
        if c is None or s is None or not x["chemistry"] or not (0 <= s <= 100):
            continue
        pts.append((x["chemistry"], c, 100 - s, fast, dod))
    report["battery"] = {"rows_raw": len(rows), "rows_used": len(pts), "batteries": len({x["battery_id"] for x in rows})}

    def bin_fast(v):
        return None if v is None else "low (<0.2)" if v < 0.2 else "mid (0.2-0.5)" if v <= 0.5 else "high (>0.5)"

    def bin_dod(v):
        return None if v is None else "shallow (<50%)" if v < 50 else "medium (50-80%)" if v <= 80 else "deep (>80%)"

    out, js = [], {}
    for chem in sorted({p[0] for p in pts}):
        base = fade_rate([(c, f) for ch, c, f, _, _ in pts if ch == chem])
        js[chem] = {"fade_pct_per_1000_cycles": round(base * 1000, 3), "cycles_to_80pct_soh": round(20 / base),
                    "n": sum(1 for p in pts if p[0] == chem), "fast_charge": {}, "depth_of_discharge": {}}
        out.append([chem, "all", "all", len([p for p in pts if p[0] == chem]), round(base * 1000, 3), 1.0, round(20 / base)])
        for label, binner, idx, key in (("fast_charge_ratio", bin_fast, 3, "fast_charge"), ("depth_of_discharge", bin_dod, 4, "depth_of_discharge")):
            groups = defaultdict(list)
            for p in pts:
                if p[0] == chem and binner(p[idx]):
                    groups[binner(p[idx])].append((p[1], p[2]))
            for b in sorted(groups):
                if len(groups[b]) < 200:
                    continue   # too few readings to trust
                k = fade_rate(groups[b])
                js[chem][key][b] = {"fade_pct_per_1000_cycles": round(k * 1000, 3), "multiplier": round(k / base, 3), "n": len(groups[b])}
                out.append([chem, label, b, len(groups[b]), round(k * 1000, 3), round(k / base, 3), round(20 / k)])
    write_csv("battery_fade_by_chemistry.csv",
              ["chemistry", "factor", "bin", "readings", "fade_pct_per_1000_cycles", "multiplier_vs_chemistry", "cycles_to_80pct_soh"], out)
    js["_meta"] = {"source": "ev_battery_health.csv (synthetic, CC0)", "model": "fade% = rate x cycles, fitted through the origin",
                   "note": "Simulated degradation model. Do not use for real warranty or safety decisions."}
    json.dump(js, open(os.path.join(HERE, "battery_fade_by_chemistry.json"), "w"), indent=2)


# ------------------------------------------------------------- palo alto
def hours(s):
    try:
        h, m, sec = s.split(":")
        return int(h) + int(m) / 60 + int(sec) / 3600
    except ValueError:
        return None


def build_palo_alto():
    raw = list(csv.DictReader(open(PALO, encoding="utf-8-sig")))
    sessions = []
    for x in raw:
        try:
            start = dt.datetime.strptime(x["Start Date"], "%m/%d/%Y %H:%M")
        except ValueError:
            continue
        dwell, kwh = hours(x["Total Duration (hh:mm:ss)"]), num(x["Energy (kWh)"])
        if start.year in PALO_YEARS and dwell and 0 < dwell <= 24 and kwh and kwh > 0:
            sessions.append((start, dwell, kwh))
    report["palo_alto"] = {"rows_raw": len(raw), "rows_used": len(sessions), "years": [min(PALO_YEARS), max(PALO_YEARS)],
                           "filters": "start year 2016-2019, 0 < dwell <= 24 h, energy > 0 kWh"}

    # arrivals by hour, weekday vs weekend, as a probability and with median dwell / energy
    rows = []
    for label, test in (("weekday", lambda d: d.weekday() < 5), ("weekend", lambda d: d.weekday() >= 5)):
        sub = [s for s in sessions if test(s[0])]
        for h in range(24):
            hs = [s for s in sub if s[0].hour == h]
            rows.append([label, h, len(hs), round(len(hs) / len(sub), 5),
                         round(st.median(s[1] for s in hs), 2) if hs else "", round(st.median(s[2] for s in hs), 2) if hs else ""])
    write_csv("arrival_profile_by_hour.csv", ["day_type", "hour", "sessions", "arrival_probability", "median_dwell_h", "median_energy_kwh"], rows)

    # quantiles overall and for the depot-like group (arrive 16:00-20:59, stay > 6 h)
    groups = {"all_sessions": sessions, "evening_arrival_long_dwell": [s for s in sessions if 16 <= s[0].hour <= 20 and s[1] > 6]}
    qs = [5, 10, 25, 50, 75, 90, 95]
    qrows = []
    for g, ss in groups.items():
        for metric, i in (("dwell_h", 1), ("energy_kwh", 2)):
            v = sorted(s[i] for s in ss)
            qrows.append([g, metric, len(v)] + [round(pct(v, q), 2) for q in qs])
    write_csv("dwell_energy_quantiles.csv", ["group", "metric", "sessions"] + [f"p{q}" for q in qs], qrows)
    report["palo_alto"]["evening_arrival_long_dwell_sessions"] = len(groups["evening_arrival_long_dwell"])

    # seeded anonymised sample (no user, station or location columns)
    random.seed(SEED)
    sample = random.sample(sessions, 2000)
    write_csv("palo_alto_session_sample.csv", ["day_type", "arrival_hour", "dwell_h", "energy_kwh"],
              [["weekday" if s[0].weekday() < 5 else "weekend", s[0].hour, round(s[1], 2), round(s[2], 2)] for s in sample])


def build_app_bundle():
    """One script the app loads with <script src="reference-data.js"> (works offline; no fetch, no URL-encoded folder name)."""
    def rows(name):
        return list(csv.DictReader(open(os.path.join(HERE, name))))
    arrivals = {"weekday": [0.0] * 24, "weekend": [0.0] * 24}
    for x in rows("arrival_profile_by_hour.csv"):
        arrivals[x["day_type"]][int(x["hour"])] = float(x["arrival_probability"])
    q = {}
    for x in rows("dwell_energy_quantiles.csv"):
        q.setdefault(x["group"], {})[x["metric"]] = {k: float(v) for k, v in x.items() if k.startswith("p")}
    bundle = {
        "battery_fade": json.load(open(os.path.join(HERE, "battery_fade_by_chemistry.json"))),
        "arrival_probability": arrivals,
        "quantiles": q,
        "sources": [
            {"name": "ev_battery_health.csv", "kind": "synthetic", "licence": "CC0", "rows": report["battery"]["rows_raw"],
             "used": report["battery"]["rows_used"], "agent": "Battery health, Solar & Storage (wear cost)",
             "note": "Physics-informed synthetic fleet telemetry; not for real warranty or safety decisions."},
            {"name": "EVChargingStationUsage.csv", "kind": "real", "licence": "City of Palo Alto open data", "rows": report["palo_alto"]["rows_raw"],
             "used": report["palo_alto"]["rows_used"], "agent": "Power (night stress test)",
             "note": "Commuter and public cars, 2016-2019 sessions; only the weekday arrival-time pattern is used. It says nothing about van energy needs."},
        ],
        "built": report["built"],
    }
    with open(os.path.join(HERE, "..", "reference-data.js"), "w") as f:
        f.write("// Generated by Actual Data Sets/build_data.py. Do not edit.\nconst REFDATA = " + json.dumps(bundle, separators=(",", ":")) + ";\n")


if __name__ == "__main__":
    build_battery()
    build_palo_alto()
    report["built"] = dt.date.today().isoformat()
    json.dump(report, open(os.path.join(HERE, "build_report.json"), "w"), indent=2)
    build_app_bundle()
    print(json.dumps(report, indent=2))
