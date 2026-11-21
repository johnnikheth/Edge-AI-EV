// Uses the public-data tables in reference-data.js (built by Actual Data Sets/build_data.py) with the same engine the Depot page runs.
// No DOM access. Needs common.js, depot-engine.js and reference-data.js.

const STRESS = {fromMin:START_MIN, socSpread:0.15};   // vans plug in from 13:00; arrival battery varies +/-15% of the energy the route used (an assumption, not from data)
const pctile = (sorted, q) => { const k = (sorted.length-1)*q, lo = Math.floor(k), hi = Math.min(lo+1, sorted.length-1); return sorted[lo] + (sorted[hi]-sorted[lo])*(k-lo); };

// Palo Alto weekday arrival hours, limited to 13:00-23:59 (when the depot's vans can return) and renormalised.
function arrivalSampler(day){
  const p = REFDATA.arrival_probability[day || 'weekday'], from = STRESS.fromMin/60, w = p.slice(from), sum = w.reduce((a,b)=>a+b, 0);
  return u => { let acc = 0; for (let i = 0; i < w.length; i++){ acc += w[i]/sum; if (u <= acc) return from + i; } return 23; };
}
// One randomised night: when each van plugs in (real arrival pattern) and how much charge it comes back with.
function randomArrivals(r, baseArrivals, hourOf){
  const o = {};
  FLEET.forEach(f => {
    const base = baseArrivals && baseArrivals[f.name] && baseArrivals[f.name].soc != null ? baseArrivals[f.name].soc : f.soc, used = 100 - base;
    o[f.name] = {plug: hourOf(r())*60 + Math.floor(r()*60) - START_MIN, soc: Math.max(5, Math.min(40, 100 - used*(1 - STRESS.socSpread + 2*STRESS.socSpread*r())))};
  });
  return o;
}
// Run n randomised nights, with and without the system, and summarise. Awaits between batches so the page can repaint.
async function runStress(cfg, n, progress){
  const hourOf = arrivalSampler('weekday'), r = rng(2026), nights = [];
  for (let i = 0; i < n; i++){
    const arrivals = randomArrivals(r, cfg.arrivals, hourOf), c = {...cfg, day:false, arrivals, seed:1000 + i};
    const S = runFull(c), B = runFull(baselineCfg(c)), cS = costs(S), cB = costs(B);
    nights.push({save:cB.monthly_usd - cS.monthly_usd, saveNet:cB.monthly_usd - cS.monthly_net_of_wear_usd, nightly:cS.nightly_usd, baseNightly:cB.nightly_usd,
      peakKwh:cS.grid_kwh.peak, basePeakKwh:cB.grid_kwh.peak, ready:S.cars.every(x=>x.met), baseReady:B.cars.every(x=>x.met), trips:S.trips, baseTrips:B.trips,
      late:S.cars.filter(x=>!x.met).map(x=>x.name)});
    if (i % 10 === 9){ if (progress) progress(i+1, n); await new Promise(res => setTimeout(res, 0)); }
  }
  const spread = key => { const v = nights.map(x=>x[key]).sort((a,b)=>a-b); return {p10:pctile(v,.1), p50:pctile(v,.5), p90:pctile(v,.9), min:v[0], max:v[v.length-1]}; };
  const share = key => nights.filter(x=>x[key]).length/n, late = {};
  nights.forEach(x=>x.late.forEach(v=>late[v] = (late[v]||0)+1));
  return {n, nights, save:spread('save'), saveNet:spread('saveNet'), nightly:spread('nightly'), baseNightly:spread('baseNightly'), peakKwh:spread('peakKwh'), basePeakKwh:spread('basePeakKwh'),
    readyShare:share('ready'), baseReadyShare:share('baseReady'), tripShare:nights.filter(x=>x.trips>0).length/n, baseTripShare:nights.filter(x=>x.baseTrips>0).length/n, late};
}

// Years until a van's pack reaches 80% health at tonight's planned cycling (Level 2 charging only, so the low fast-charge multiplier).
function vanLifeYears(chem, c){
  const f = fadeFor(chem); if (!f) return null;
  const m = f.fast_charge['low (<0.2)'], cyc = Math.max(0, c.need - c.soc0)/100;
  return cyc > 0.02 ? f.cycles_to_80pct_soh/(m ? m.multiplier : 1)/(cyc*365) : Infinity;
}
// How long each chemistry lasts at this depot's cycling, what each kWh costs in wear, and whether the grid top-up pays.
// Vans charge on Level 2 only (no DC fast), so they use the low fast-charge multiplier; storage uses the multiplier for its actual depth of discharge.
function batteryLife(cfg, chems){
  return (chems || Object.keys(REFDATA.battery_fade).filter(k=>k[0] !== '_')).map(chem => {
    const f = fadeFor(chem), c = {...cfg, chem, quiet:true}, S = runFull(c), k = costs(S), w = S.wear;
    const lowFast = f.fast_charge['low (<0.2)'], vanMult = lowFast ? lowFast.multiplier : 1;
    const vans = S.cars.map(v => { const cyc = v.kwh/v.cap; return {name:v.name, cycles:cyc, years:cyc > 0.02 ? f.cycles_to_80pct_soh/vanMult/(cyc*365) : Infinity}; });
    let storage = null;
    if (cfg.battKwh){
      const cyc = k.storage_cycles_night, bin = f.depth_of_discharge[dodBin(Math.min(1, cyc))], mult = bin ? bin.multiplier : 1, life = f.cycles_to_80pct_soh/mult;
      storage = {cyclesNight:cyc, cycles80:Math.round(life), years:cyc > 0.02 ? life/(cyc*365) : Infinity, wearPerKwh:w ? w.wearPerKwh : null,
        wearMonth:k.wear_usd_month, replaceUsd:cfg.battKwh*(w ? w.usdPerKwh : WEAR_DEFAULTS.usdPerKwh), gridWorth:w ? w.gridWorth : null, gridMargin:w ? w.gridMargin : null};
    }
    return {chem, fadePer1000:f.fade_pct_per_1000_cycles, cycles80:f.cycles_to_80pct_soh, vans, storage, monthlyNet:k.monthly_net_of_wear_usd, monthly:k.monthly_usd};
  });
}
