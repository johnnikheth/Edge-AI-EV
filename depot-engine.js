// Depot energy engine: cost-aware charging planner, solar + battery dispatch, HVAC power agent, and tariff billing.
// No DOM access, so the Depot page and the sizing explorer run exactly the same logic. Needs common.js (FLEET, needOf, rng...).
const VOLTS = 240, MAX_A = 32, MIN_A = 6, CH_KW = MAX_A*VOLTS/1000, HVAC_KW = 30, CRIT_MIN = 90;
const START_MIN = 13*60, DAY_START_MIN = 6*60, END_MIN = 30*60, SLOT = 15;           // vans return from 13:00, last departure before 06:00
const K = 0.004, HEAT = 0.1, STD_BAND = 2.5, SNAP = -10, MAX_TIN = 25; // building thermal model (per minute)
const ETA_IN = 0.95, ETA_OUT = 0.95;                            // battery charge / discharge efficiency (~90% round trip)

// PG&E Schedule BEV, option BEV-1 (dedicated EV meter, up to 100 kW, secondary voltage). Total bundled rates
// effective March 1, 2026 (Advice 7846-E). Same prices every day of the year, no seasons.
const BEV1 = {name:'PG&E BEV-1 (Business EV)', effective:'March 1, 2026', url:'https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_BEV.pdf',
  peak:0.35711, off:0.16510, superOff:0.13844, blockKw:10, blockUsd:12.41, overageUsd:2.48};
const PRICE = {peak:BEV1.peak, off:BEV1.off, super:BEV1.superOff};
const PERIOD_NAME = {peak:'Peak (4–9 pm)', off:'Off-peak', super:'Super off-peak (9 am–2 pm)'};
function period(m){ const h = (((m%1440)+1440)%1440)/60; return h>=16 && h<21 ? 'peak' : (h>=9 && h<14 ? 'super' : 'off'); }

// kW produced per kW of panels. PVWatts monthly-average profile when available; otherwise a clear October day in Oakland.
function solarPerKwp(m, profile){
  const h = (((m%1440)+1440)%1440)/60;
  if (profile && profile.length===24){ const i = Math.floor(h), f = h-i; return profile[i]*(1-f) + profile[(i+1)%24]*f; }
  const rise = 7.25, set = 18.5;
  return h<=rise || h>=set ? 0 : 0.68*Math.pow(Math.sin(Math.PI*(h-rise)/(set-rise)), 1.3);
}
// Outdoor °C. Open-Meteo hourly forecast (index 0 = today 00:00) when available; otherwise a typical Oakland October day.
function outdoorTemp(m, wx){
  if (wx && wx.temps && wx.temps.length > Math.ceil(m/60)+1){ const h = m/60, i = Math.floor(h), f = h-i; return wx.temps[i]*(1-f) + wx.temps[i+1]*f; }
  return 15.5 + 5.5*Math.cos(2*Math.PI*((m/60)%24 - 15)/24);
}

function note(st, src, text){ if (!st.cfg.quiet) st.events.push({t:st.t, src, text}); }

// ---- battery wear: what one kWh through EV storage costs in lost battery life. Fade rates come from the public
// battery dataset (Actual Data Sets/battery_fade_by_chemistry.json, loaded as REFDATA). Assumes the pack is replaced at 80% health,
// with no resale value, so the wear cost per kWh is the pack price spread over the cycles until then. ----
const WEAR_DEFAULTS = {chem:'NMC', usdPerKwh:200};
const fadeFor = chem => (typeof REFDATA !== 'undefined' && REFDATA.battery_fade && REFDATA.battery_fade[chem]) || null;
const dodBin = d => d < 0.5 ? 'shallow (<50%)' : d <= 0.8 ? 'medium (50-80%)' : 'deep (>80%)';
function storageWear(cfg){
  const chem = cfg.chem || WEAR_DEFAULTS.chem, f = fadeFor(chem);
  if (!f || !cfg.battKwh) return null;
  const usd = cfg.battUsdPerKwh != null ? cfg.battUsdPerKwh : WEAR_DEFAULTS.usdPerKwh, perKwh = usd/f.cycles_to_80pct_soh;
  // buying super off-peak grid power to sell at peak: the energy bought costs more after the round-trip losses, plus the wear
  const gridCost = PRICE.super/(ETA_IN*ETA_OUT), margin = PRICE.peak - gridCost - perKwh;
  return {chem, usdPerKwh:usd, cycles80:f.cycles_to_80pct_soh, wearPerKwh:perKwh, gridCost, gridMargin:margin, gridWorth:margin > 0};
}

function createSim(cfg){
  const wear = storageWear(cfg);
  if (wear && !wear.gridWorth && cfg.gridTopUp !== false) cfg = {...cfg, gridTopUp:false};   // the agent skips grid top-ups that wear the pack more than they save
  const r = rng(cfg.seed || 11);
  const t0 = cfg.day ? DAY_START_MIN : START_MIN;   // a full-day run starts at 06:00 (vans are out until they return at 13:00)
  const st = {cfg, wear, t:t0, done:false, events:[], hist:[], snap:false, outage:false, noise:()=>(r()-.5)*3,
    cars: FLEET.map(f=>{
      const a = (cfg.arrivals && cfg.arrivals[f.name]) || {};
      return {name:f.name, cap:f.cap, chKw:f.chKw||CH_KW, daysOut:f.daysOut||1,
        need:needOf(f), dep:f.dep, stops:f.stops, drain:f.drain, ret:f.ret,
        arrive:START_MIN + (a.plug!=null ? a.plug : f.plug),
        soc:a.soc!=null ? a.soc : f.soc, soc0:a.soc!=null ? a.soc : f.soc, status:'Away', kwh:0, amps:0, wantA:0, maxA:0,
        slack:0, critical:false, wasCrit:false, met:null, plan:{}, short:0};
    }),
    tin:21.5, hvac:false, engaged:false, ref:null, suppressed:false, hvacKwh:0, hvacMin:0, cycles:0,
    battCap:cfg.battKwh||0, battKw:cfg.battKw||0, batt:0, battMode:'idle', subTarget:BEV1.blockKw,
    cost:{evUsd:0, bldgUsd:0, prechargeUsd:0, kwh:{peak:0, off:0, super:0}, solarKwh:0, solarToEv:0, exportKwh:0, battIn:0, battOut:0, evKwh:0},
    peakEvImport:0, peakSite:0, trips:0, nextPlan:t0, lastPeriod:null, shedLogged:false};
  if (wear && cfg.managed) note(st, 'solar', `Storage wear: ${wear.chem} at $${wear.usdPerKwh}/kWh lasts about ${wear.cycles80.toLocaleString()} cycles to 80% health, so each kWh through it costs $${wear.wearPerKwh.toFixed(3)}. ` +
    (wear.gridWorth ? `Buying super off-peak power ($${PRICE.super}/kWh, $${wear.gridCost.toFixed(3)} after losses) to use at peak ($${PRICE.peak}/kWh) still nets $${wear.gridMargin.toFixed(3)}/kWh after wear — grid top-up stays on.`
                    : `Grid top-up would net $${wear.gridMargin.toFixed(3)}/kWh after wear — not worth it, so storage fills from rooftop solar only.`));
  // Vans are out 05:00-13:00, so the battery fills from morning solar, topped up from the grid at super off-peak if needed.
  if (st.battCap>0 && cfg.day){
    st.batt = st.battCap*cfg.reserve/100;
    note(st, 'solar', `Day starts with EV storage at ${Math.round(cfg.reserve)}% (the outage reserve). Rooftop solar refills it from sunrise.`);
  } else if (st.battCap>0){
    let soc = st.battCap*cfg.reserve/100, fromSun = 0;
    for (let m=7*60; m<START_MIN; m+=SLOT){
      const add = Math.min(cfg.solarKwp*solarPerKwp(m+SLOT/2, cfg.solarProfile)*SLOT/60*ETA_IN, st.battCap-soc, st.battKw*SLOT/60);
      soc += add; fromSun += add;
    }
    const grid = cfg.gridTopUp===false ? 0 : Math.min(Math.max(0, st.battCap-soc)/ETA_IN, st.battKw*4); // 09:00-13:00
    st.batt = Math.min(st.battCap, soc + grid*ETA_IN);
    st.cost.prechargeUsd = grid*PRICE.super; st.cost.kwh.super += grid;
    st.peakEvImport = grid/4;
    note(st, 'solar', `EV storage starts the afternoon at ${Math.round(st.batt/st.battCap*100)}%: ${fromSun.toFixed(0)} kWh from this morning's rooftop solar` +
      (grid>0.5 ? ` + ${grid.toFixed(0)} kWh from the grid at super off-peak ($${PRICE.super}/kWh)` : '') + '.');
  }
  return st;
}

// ---- charging planner: cheapest energy first — rooftop solar, then stored solar during the peak (if the site has
// EV storage), then super off-peak, then off-peak grid. Peak grid power only if a van would otherwise miss its departure. ----
// ---- GOAL-BASED AGENT: plan() ----
// Agent type: Goal-Based
// Goal state: every van reaches its required charge level (c.need%) before its departure time (c.dep).
// Planning: builds a forward-looking time-slot schedule from now until 06:00, allocating each van into the
// cheapest available slots (solar > storage > super-off-peak > off-peak > peak) without exceeding the site
// breaker limit. If the goal cannot be reached (c.short > 0), the shortfall is flagged to the fleet planner.
function plan(st){
  const cfg = st.cfg, now = Math.floor(st.t/SLOT)*SLOT, slots = [];
  // stored energy above the backup reserve, saved for the 4-9 pm peak (none if the site has no storage).
  // Vans get first claim; the building uses whatever the plan leaves.
  let store = st.battCap>0 && st.t < 21*60 ? Math.max(0, st.batt - st.battCap*cfg.reserve/100)*ETA_OUT : 0;
  for (let m=now; m<END_MIN; m+=SLOT){
    const p = period(m), solar = cfg.solarKwp*solarPerKwp(m+SLOT/2, cfg.solarProfile), storeKw = p==='peak' && store>0 ? st.battKw : 0;
    slots.push({m, p, price:PRICE[p], solar, solarUsed:0, storeKw, storeUsed:0, used:0, cap:Math.max(0, cfg.limit - cfg.base - 2) + solar + storeKw});
  }
  // ---- UTILITY-BASED AGENT: utilityScore() ----
  // Agent type: Utility-Based
  // Utility function: assigns each charging slot a cost score used to rank alternatives.
  //   score = 0      → slot is covered by rooftop solar (free energy, always preferred)
  //   score = 0.001  → slot is covered by stored EV battery energy (near-free, avoids peak buy)
  //   score = price  → grid price for the period (super-off-peak < off-peak < peak in $/kWh)
  // The fill() loop below always picks the slot with the lowest utilityScore first, so the charging
  // plan automatically maximises the use of solar and storage before touching the grid.
  const utilityScore = (s, useStore) =>
    s.solar - s.solarUsed > 0.5  ? 0 :
    (useStore && s.storeKw - s.storeUsed > 0.5 && store > 0.1 ? 0.001 : s.price);
  st.storeForEv = 0; // stored kWh the plan counts on for charging vans during the peak
  for (const c of st.cars.filter(c=>c.status!=='Departed').sort((a,b)=>a.dep-b.dep)){
    c.plan = {};
    // Learning Agent: apply history-derived bump to this van's charge target, capped at 100%.
    // learningNeeds[name] is set by learningAdjust() in index.html from multi-night SQLite history.
    if (cfg.learningNeeds && cfg.learningNeeds[c.name]){
      const bumpedNeed = Math.min(100, c.need + cfg.learningNeeds[c.name]);
      if (bumpedNeed > c.need){
        c.learnBump = cfg.learningNeeds[c.name];  // stored for display in the Agents panel
        c.need = bumpedNeed;
      }
    }
    const win = slots.filter(s=>s.m >= Math.max(c.arrive, now) && s.m+SLOT <= c.dep);
    const fill = (kwh, maxPrice, useStore) => {
      while (kwh > 0.05){
        // among equal prices take the least-loaded slot: keeps the site peak, and the BEV subscription, low
        const s = win.filter(s=>utilityScore(s, useStore) <= maxPrice && (c.plan[s.m]||0) < c.chKw-0.01 && s.used < s.cap - (useStore ? 0 : s.storeKw) - 0.5)
                     .sort((a,b)=>utilityScore(a, useStore)-utilityScore(b, useStore) || a.used-b.used || a.m-b.m)[0];
        if (!s) break;
        const kw = Math.min(c.chKw-(c.plan[s.m]||0), s.cap - (useStore ? 0 : s.storeKw) - s.used, Math.max(MIN_A*VOLTS/1000, kwh*60/SLOT), c.chKw);
        c.plan[s.m] = (c.plan[s.m]||0) + kw; s.used += kw;
        const fromSun = Math.min(kw, Math.max(0, s.solar-s.solarUsed)); s.solarUsed += fromSun;
        const fromStore = useStore ? Math.min(kw-fromSun, Math.max(0, s.storeKw-s.storeUsed), store*60/SLOT) : 0;
        s.storeUsed += fromStore; store -= fromStore*SLOT/60; st.storeForEv += fromStore*SLOT/60; kwh -= kw*SLOT/60;
      }
      return Math.max(0, kwh);
    };
    c.short = fill(Math.max(0, c.need-c.soc)/100*c.cap, Infinity, true);           // must have: route requirement (may use storage)
    if (cfg.topup !== false) fill(Math.max(0, TOPUP-Math.max(c.soc, c.need))/100*c.cap, PRICE.off, false); // nice to have: never at peak, never from storage
    if (c.short > 0.5) note(st, 'agent', `${c.name} can't reach ${c.need}% by ${fmtClock(c.dep)} within the site limit (${c.short.toFixed(0)} kWh short) — it will charge at every opportunity.`);
  }
  const peakNet = Math.max(0, ...slots.map(s=>s.used - s.solar - s.storeUsed));
  st.subTarget = Math.max(BEV1.blockKw, Math.ceil(peakNet/BEV1.blockKw - 1e-9)*BEV1.blockKw);
}
// ---- GOAL-BASED AGENT: fleetPlanner() ----
// Agent type: Goal-Based
// Goal state: every van/semi that is unable to reach its route charge (c.short > 0 or c.fault) is either
// given a lighter route it CAN complete, or is flagged to the dispatcher with no safe swap available.
// Also tracks absent multi-day vehicles (Semis on interstate runs), estimates their ETA and remaining range,
// and pre-reserves a charging window so power is guaranteed on arrival.
const routeKwh = c => (c.stops*c.drain + c.ret)/100*c.cap;
const needPct = (c, kwh) => Math.ceil(kwh/c.cap*100 + FLOOR + RESERVE);

// Semi tracker: for a vehicle that won't return this session, simulate its position along the route.
// Uses the departure time (dep), the total run time (stops × leg duration + return), and the current sim
// clock to estimate which city leg it is on, estimated battery remaining, and ETA back.
// Leg duration assumption: ~500 km at average 85 km/h = ~6 h per outbound leg; return ~4 h.
const LEG_H = 6, RET_H = 4;           // hours per outbound leg and return leg (interstate estimate)
function trackSemi(c, nowMin){
  // Departure was at c.dep (in sim-minutes from midnight, wrapped across days).
  // We model time elapsed since departure to estimate which leg the Semi is on.
  // dep can be > 1440 (e.g. 31*60 = next morning); normalise relative to midnight.
  const depMin = c.dep % 1440;          // departure time in the day (minutes from midnight)
  // elapsed time since last departure — if sim hasn't yet reached dep, use 0
  const elapsedMin = nowMin > depMin ? nowMin - depMin : 0;
  const elapsedH = elapsedMin / 60;

  const legMins = LEG_H * 60, retMins = RET_H * 60;
  const totalOutH = c.stops * LEG_H;   // total outbound time (hours)

  let legIdx, pctAlongLeg, onReturn, etaMin;
  if (elapsedH <= totalOutH){
    // still on outbound legs
    legIdx = Math.min(c.stops - 1, Math.floor(elapsedH / LEG_H));
    pctAlongLeg = (elapsedH % LEG_H) / LEG_H;
    onReturn = false;
    const remainOutH = totalOutH - elapsedH, remRetH = RET_H;
    etaMin = nowMin + (remainOutH + remRetH) * 60;
  } else {
    // on the return leg
    const retElapsedH = elapsedH - totalOutH;
    legIdx = c.stops;
    pctAlongLeg = Math.min(1, retElapsedH / RET_H);
    onReturn = true;
    etaMin = nowMin + Math.max(0, RET_H - retElapsedH) * 60;
  }

  // battery remaining: started at soc0%, drained drain%/leg per outbound leg and ret% on return
  const drainedOutbound = Math.min(c.stops, onReturn ? c.stops : legIdx + pctAlongLeg) * c.drain;
  const drainedReturn   = onReturn ? pctAlongLeg * c.ret : 0;
  const socNow = Math.max(5, c.soc0 - drainedOutbound - drainedReturn);

  // kWh to charge to need% once back — used to pre-reserve a slot window
  const chargeNeeded = Math.max(0, c.need - socNow) / 100 * c.cap;
  const chargeHours  = chargeNeeded / c.chKw;
  // ETA normalised to sim-minute space (may wrap past midnight)
  const etaSimMin = etaMin;

  return {name:c.name, legIdx, onReturn, pctAlongLeg, socNow: Math.round(socNow),
          etaSimMin: Math.round(etaSimMin), chargeNeeded: Math.round(chargeNeeded),
          chargeHours: +chargeHours.toFixed(1), daysOut:c.daysOut};
}

function fleetPlanner(st){
  const live = st.cars.filter(c=>c.status!=='Departed');
  const isShort = c => c.short>0.5 || c.fault;
  // Exclude absent interstate semis (arrive > END_MIN) from the on-site priority order
  const onSite = live.filter(c=>c.arrive < END_MIN);
  const order = [...onSite].sort((a,b)=>a.slack-b.slack).map(c=>c.name);
  const proposals = [];
  for (const a of onSite.filter(isShort)){
    const projA = a.fault ? a.soc : a.need - a.short/a.cap*100;
    const b = onSite.filter(c=>c!==a && !isShort(c) && routeKwh(c)<routeKwh(a) && needPct(a, routeKwh(c))<=projA && needPct(c, routeKwh(a))<=95)
                  .sort((x,y)=>needPct(x, routeKwh(a))-needPct(y, routeKwh(a)))[0];
    const why = a.fault ? `${a.name} has a charger fault` : `${a.name} is ${a.short.toFixed(0)} kWh short for its ${a.stops}-stop route`;
    if (b) proposals.push({from:a.name, to:b.name, id:a.name+'>'+b.name,
      text:`${why}. Proposal: swap routes — ${a.name} takes ${b.name}'s lighter ${b.stops}-stop route and ${b.name} takes the ${a.stops}-stop route (needs ${needPct(b, routeKwh(a))}% by ${fmtClock(b.dep)}). Needs dispatcher approval.`});
  }
  const late = onSite.filter(isShort), nShort = late.length;

  // ---- Semi tracker: compute position + ETA for absent interstate vehicles ----
  const absentSemis = live.filter(c=>c.arrive >= END_MIN && c.daysOut > 1);
  const semiTrack = absentSemis.map(c=>trackSemi(c, st.t));

  // Log a tracking note once per Semi per session (when first computed)
  for (const tr of semiTrack){
    const noteKey = 'semiTrack_' + tr.name;
    if (!st[noteKey]){
      st[noteKey] = true;
      const loc = tr.onReturn ? `returning to depot` : `on outbound leg ${tr.legIdx + 1} of ${st.cars.find(c=>c.name===tr.name).stops}`;
      note(st, 'planner',
        `${tr.name} is currently ${loc} · est. battery ${tr.socNow}% · ETA depot ${fmtClock(tr.etaSimMin)} · ` +
        `will need ~${tr.chargeNeeded} kWh (${tr.chargeHours} h at ${st.cars.find(c=>c.name===tr.name).chKw} kW) — ` +
        `charge slot pre-reserved from ${fmtClock(tr.etaSimMin + 30)} to ${fmtClock(tr.etaSimMin + 30 + tr.chargeHours*60)}.`);
    }
  }

  const key = (order[0]||'') + '|' + nShort + '|' + proposals.map(p=>p.id).join(',');
  st.fleet = {order, proposals, late:late.map(c=>c.name), semiTrack};
  if (key !== st.fleetKey && live.length){
    st.fleetKey = key;
    note(st, 'planner', `Charge priority: ${order.slice(0,3).join(' → ')}${order.length>3?' …':''} (tightest slack first).` + (proposals.length ? '' : nShort ? ` ${nShort} vehicle${nShort===1?'':'s'} short of route charge and no safe route swap found — flagged for the dispatcher.` : ' All on-site vehicles on track.'));
    proposals.forEach(p=>note(st, 'planner', p.text));
  }
  // customer communications agent: drafts a heads-up for vans likely to leave late. Drafts only — rescheduling customers needs approval.
  st.comms = late.map(c => {
    const delay = c.fault ? 60 : Math.max(5, Math.ceil(c.short/c.chKw*60/5)*5);
    return {id:'late-'+c.name, van:c.name, text:`Your delivery may arrive about ${delay} minutes later than planned. We'll confirm your new window this morning.`};
  });
  const ckey = st.comms.map(d=>d.id).join(',');
  if (ckey !== st.commsKey){ st.commsKey = ckey; st.comms.forEach(d=>note(st, 'comms', `Draft for ${d.van}'s customers (held for approval): "${d.text}"`)); }
}
// ---- outage resilience, demand response, charger-fault and battery-health agents (rule-based, observe the sim every step) ----
const urgency = st => st.cars.filter(c=>c.status!=='Away' && c.status!=='Departed').sort((a,b)=>a.slack-b.slack).map(c=>({name:c.name, slack:Math.round(c.slack), soc:Math.round(c.soc), need:c.need}));
function depotAgents(st, x){
  const t = st.t, soc = st.battCap ? st.batt/st.battCap*100 : 0;
  // outage resilience: how long can storage + solar carry the site, and who waits
  if (st.outage){
    const load = x.evKw + x.bldg - x.solar, runH = load>0.5 ? st.batt*ETA_OUT/load : Infinity;
    st.resil = {state:'outage', soc, runtimeH:runH, rank:urgency(st)};
    if (!st.resilOn){ st.resilOn = true; st.resilLow = false;
      note(st, 'resilience', st.battCap ? `Outage: EV storage at ${Math.round(soc)}% plus ${x.solar.toFixed(0)} kW rooftop solar can carry the site about ${isFinite(runH) ? runH.toFixed(1)+' h' : 'indefinitely'} at the current ${Math.max(0,load).toFixed(0)} kW net load. Order of shedding: HVAC, then vans with the most slack, urgent vans last.` : 'Outage with no storage: the site is down until the grid returns.'); }
    if (st.battCap && soc < 25 && !st.resilLow){ st.resilLow = true; note(st, 'resilience', `Storage under 25% — non-urgent vans will wait; only urgent vans keep charging.`); }
  } else {
    st.resil = {state:'grid', soc, runtimeH:null, rank:urgency(st)};
    if (st.resilOn){ st.resilOn = false; note(st, 'resilience', `Grid is back. Storage at ${Math.round(soc)}%; refill handed to the Solar & Storage agent.`); }
  }
  // demand response: how much flexibility could the site offer during the peak (simulated, not enrolled)
  const peak = x.per==='peak';
  if (peak && !st.drOn){
    st.drOn = true;
    const store = st.battCap && st.batt > st.battCap*st.cfg.reserve/100 ? st.battKw : 0;
    const paused = st.cars.reduce((a,c)=>a + Math.max(0, c.maxA - c.amps)*VOLTS/1000, 0), hv = st.hvac ? HVAC_KW : 0;
    st.dr = {offerKw:store + paused + hv, store, paused, hvac:hv};
    note(st, 'demand', `Peak window: the site could offer about ${st.dr.offerKw.toFixed(0)} kW of flexibility to the utility (storage ${store.toFixed(0)} kW + paused chargers ${paused.toFixed(0)} kW + HVAC ${hv} kW). Simulated — no demand-response program rates are used.`);
  }
  if (!peak && st.drOn && t >= 21*60){ st.drOn = false; note(st, 'demand', `Peak over: ${st.cost.kwh.peak.toFixed(1)} kWh of EV charging was bought from the grid at peak price.`); }
  // charger faults: a plugged-in van that cannot draw power
  for (const c of st.cars){
    if (c.fault && c.status!=='Away' && c.status!=='Departed' && !c.ticket){
      st.tickets = (st.tickets||0) + 1; c.ticket = 'MT-' + (1000 + st.tickets);
      note(st, 'fault', `${c.name}: charger fault — 0 kW delivered while plugged in. Maintenance ticket ${c.ticket} opened; the Fleet planner now treats ${c.name} as unable to charge.`);
      st.nextPlan = t;
    }
    if (!c.fault && c.ticket){ note(st, 'fault', `${c.name}: charger back online — ticket ${c.ticket} closed after ${Math.round(c.downMin||0)} min of downtime.`); c.ticket = null; st.nextPlan = t; }
  }
  // battery health: deep-discharge arrivals and peak-price charging, noted once
  if (!st.healthNoted && t >= START_MIN + 120){
    st.healthNoted = true;
    const deep = st.cars.filter(c=>c.soc0 <= 16).map(c=>`${c.name} (${Math.round(c.soc0)}%)`);
    if (deep.length) note(st, 'health', `Deep discharge on arrival: ${deep.join(', ')}. Returning below ~16% ages the battery — consider a shorter route or an earlier return.`);
  }
  if (!st.peakHealth && t >= 21*60){
    st.peakHealth = true;
    const pk = st.cars.filter(c=>(c.peakKwh||0) > 1).map(c=>`${c.name} (${c.peakKwh.toFixed(0)} kWh)`);
    note(st, 'health', pk.length ? `Vans charging during the 4–9 pm window: ${pk.join(', ')}. EV storage and solar covered it where they could; ${st.cost.kwh.peak.toFixed(0)} kWh was bought from the grid at peak price.` : 'No van needed to charge during the peak window tonight.');
  }
}
// ---- GOAL-BASED AGENT: chargeDecision() ----
// Agent type: Goal-Based
// Goal state: the van reaches c.need% before c.dep.
// Planning: evaluates the current price period, solar output, grid headroom and the pre-built slot schedule
// to decide between charging now or waiting for a cheaper/cleaner window — always keeping the goal in view.
function plugIn(st, c){                       // a driver plugs in early (or late): the van is back now
  if (c.status!=='Away') return false;
  c.arrive = st.t;
  if (st.cfg.managed){ c.status = 'Charging'; st.nextPlan = st.t;
    note(st, 'gateway', `${c.name} plugged in at ${fmtClock(st.t)} with ${c.soc.toFixed(0)}% — needs ${c.need}% by ${fmtClock(c.dep)}.`);
    plan(st); fleetPlanner(st); chargeDecision(st, c); }
  return true;
}
function chargeDecision(st, c){
  const cfg = st.cfg, t = st.t, per = period(t), price = PRICE[per];
  const needKwh = Math.max(0, c.need - c.soc)/100*c.cap, sun = cfg.solarKwp*solarPerKwp(t, cfg.solarProfile);
  const office = cfg.base + (st.hvac ? HVAC_KW : 0), headroom = Math.max(0, cfg.limit - office);
  const slack = c.dep - t - minsToFill(c), nowKw = c.plan[Math.floor(t/SLOT)*SLOT] || 0, first = planSummary(c)[0];
  let verdict;
  if (needKwh <= 0.5) verdict = first ? `no charge needed for the route; a cheap top-up is planned from ${fmtClock(first.start)}` : 'no charge needed';
  else if (c.short > 0.5) verdict = `charge now at full available power — it cannot reach ${c.need}% in time (${c.short.toFixed(0)} kWh short)`;
  else if (nowKw > 0.05) verdict = `charge now at ${nowKw.toFixed(1)} kW — ${sun >= nowKw ? 'rooftop solar covers it' : per==='peak' ? 'EV storage carries the peak' : 'this is a cheap window'}`;
  else if (first){
    const sunThen = cfg.solarKwp*solarPerKwp(first.start, cfg.solarProfile), stored = st.battCap>0 && st.batt > st.battCap*cfg.reserve/100 + 5;
    const when = first.p==='peak' ? `peak window, but served by ${sunThen > 1 ? 'rooftop solar' : stored ? 'EV storage' : 'the grid'} instead of buying at $${PRICE.peak.toFixed(3)}/kWh` : `${PERIOD_NAME[first.p].split(' (')[0].toLowerCase()}, $${PRICE[first.p].toFixed(3)}/kWh`;
    verdict = `wait and charge from ${fmtClock(first.start)} (${when}) — ${Math.max(0, Math.round(slack))} min of slack before departure`; }
  else verdict = 'no workable window found — flagged to the dispatcher';
  const text = `${c.name} plugged in at ${fmtClock(t)}: ${c.soc.toFixed(0)}% now, needs ${c.need}% by ${fmtClock(c.dep)} (${needKwh.toFixed(0)} kWh). Price now $${price.toFixed(3)}/kWh, solar ${sun.toFixed(0)} kW, ${headroom.toFixed(0)} kW of grid capacity free after the Corporate Office. Decision: ${verdict}.`;
  (st.decisions = st.decisions || []).unshift({t, van:c.name, verdict, text}); st.decisions.length = Math.min(st.decisions.length, 8);
  note(st, 'agent', text);
}
function planSummary(c){
  const ms = Object.keys(c.plan).map(Number).filter(m=>c.plan[m]>0.05).sort((a,b)=>a-b), out = [];
  for (const m of ms){
    const last = out[out.length-1], p = period(m);
    if (last && last.end===m && last.p===p){ last.end = m+SLOT; last.kwh += c.plan[m]*SLOT/60; }
    else out.push({start:m, end:m+SLOT, p, kwh:c.plan[m]*SLOT/60});
  }
  return out;
}

// ---- gateway allocation: critical vans first, then the rest of the route requirement, then top-ups ----
function wantAmps(c){ if (c.soc >= TOPUP) return 0; if (c.soc <= 80) return MAX_A; return Math.max(MIN_A, Math.round(MAX_A*(1-(c.soc-80)/12))); }
const minsToFill = c => c.soc>=c.need ? 0 : ((c.need-c.soc)/100*c.cap)/CH_KW*60;
function scaleGroup(group, budget){
  if (!group.length) return 0;
  const want = group.reduce((s,c)=>s+c.wantA*VOLTS/1000, 0);
  if (want <= budget){ group.forEach(c=>c.amps=c.wantA); return want; }
  const f = Math.max(0, budget)/want;
  group.forEach(c=>{ const a = Math.floor(c.wantA*f); c.amps = a>=MIN_A ? a : 0; });
  let used = group.reduce((s,c)=>s+c.amps*VOLTS/1000, 0);
  for (const c of [...group].sort((a,b)=>a.slack-b.slack)){
    while (c.amps < c.wantA){ const step = c.amps===0 ? MIN_A : 1; if (used + step*VOLTS/1000 > budget) break; c.amps += step; used += step*VOLTS/1000; }
  }
  return used;
}
function allocate(cars, avail){
  const act = cars.filter(c=>c.wantA>0);
  act.forEach(c=>c.critical = c.soc<c.need && c.slack<CRIT_MIN);
  let used = 0;
  for (const c of act.filter(c=>c.critical).sort((a,b)=>a.slack-b.slack)){
    const a = Math.min(c.wantA, Math.floor(Math.max(0, avail-used)*1000/VOLTS)); c.amps = a>=MIN_A ? a : 0; used += c.amps*VOLTS/1000;
  }
  used += scaleGroup(act.filter(c=>!c.critical && c.soc<c.need), avail-used);
  return used + scaleGroup(act.filter(c=>c.soc>=c.need), avail-used);
}

// ---- power agent: HVAC ----
function hvacRule(cfg, st){ return {trig:cfg.trig, comfort:cfg.comfort, band:cfg.band, retrig:((st && st.ref!=null) ? st.ref : cfg.trig)*(1-cfg.band/100)}; }
function controlHvac(st){
  const cfg = st.cfg, r = hvacRule(cfg, st), was = st.hvac;
  if (st.outage){ if (st.hvac) note(st, 'resilience', 'Grid outage: HVAC shed to keep the battery for critical loads and chargers.'); st.hvac = false; return; }
  if (cfg.mode==='force') st.hvac = true;
  else if (cfg.mode==='standard'){
    if (!st.hvac && st.tin<=r.trig) st.hvac = true; else if (st.hvac && st.tin>=r.trig+STD_BAND) st.hvac = false;
  } else if (!st.engaged){
    if (st.tin<=r.trig){ st.hvac = true; st.engaged = true; st.ref = st.tin;
      note(st, 'agent', `Building thermostat triggered HVAC at ${st.tin.toFixed(1)} °C. Agent will stop it at ${r.comfort} °C and re-trigger at ${(st.ref*(1-r.band/100)).toFixed(1)} °C (${r.band}% below).`); }
  } else if (st.hvac && st.tin>=r.comfort){
    st.hvac = false; st.suppressed = false; note(st, 'agent', `Indoor ${st.tin.toFixed(1)} °C is comfortable → HVAC off, ${HVAC_KW} kW freed.`);
  } else if (!st.hvac && st.tin<=r.retrig){
    st.hvac = true; st.cycles++; note(st, 'agent', `Indoor fell to ${st.tin.toFixed(1)} °C (${r.band}% below the ${st.ref.toFixed(1)} °C trigger) → HVAC re-triggered.`);
  } else if (!st.hvac && st.tin<=r.trig && !st.suppressed){
    st.suppressed = true; note(st, 'agent', `Thermostat wants HVAC at ${st.tin.toFixed(1)} °C; agent holds it off until ${r.retrig.toFixed(1)} °C.`);
  }
  if (st.hvac!==was && cfg.mode!=='agent') note(st, 'gateway', `HVAC ${st.hvac?'ON (+'+HVAC_KW+' kW)':'OFF'} — ${cfg.mode==='force'?'forced':'standard thermostat'}`);
}

// ---- one simulation step of dt minutes ----
function step(st, dt){
  const cfg = st.cfg, t = st.t, per = period(t), price = PRICE[per], h = dt/60;
  const arrivedNow = [];
  for (const c of st.cars){
    if (c.status==='Away' && t>=c.arrive){ c.status = 'Charging'; st.nextPlan = t; arrivedNow.push(c);
      note(st, 'gateway', `${c.name} plugged in at ${fmtClock(t)} with ${c.soc.toFixed(0)}% — needs ${c.need}% by ${fmtClock(c.dep)}.`); }
    if (c.status!=='Away' && c.status!=='Departed' && t>=c.dep){
      c.met = c.soc >= c.need-0.5; c.status = 'Departed'; c.amps = 0;
      note(st, 'gateway', `${c.name} departs at ${c.soc.toFixed(0)}% — ${c.met ? 'route requirement met' : 'MISSED '+c.need+'% requirement'}.`);
    }
  }
  if (per!==st.lastPeriod){
    note(st, 'agent', `${PERIOD_NAME[per]} — $${price.toFixed(3)}/kWh.` + (cfg.managed && per==='peak' ? ' Chargers pause unless a van is critical; the battery carries the site.' : '') +
      (cfg.managed && st.lastPeriod==='peak' ? ' Planned charging resumes.' : ''));
    st.lastPeriod = per;
  }
  if (cfg.managed && t>=st.nextPlan){ plan(st); fleetPlanner(st); st.nextPlan = t+60; arrivedNow.forEach(c=>chargeDecision(st, c)); }
  controlHvac(st);

  const noise = st.noise();
  const bldg = Math.max(0, cfg.base + noise + (st.hvac ? HVAC_KW : 0));
  const solar = cfg.solarKwp*solarPerKwp(t+dt/2, cfg.solarProfile);
  const slot = Math.floor(t/SLOT)*SLOT;
  for (const c of st.cars){
    c.amps = 0; c.critical = false;
    c.maxA = (c.status==='Away' || c.status==='Departed' || c.fault) ? 0 : wantAmps(c);
    c.slack = c.dep - t - minsToFill(c);
    if (!c.maxA){ c.wantA = 0; continue; }
    if (!cfg.managed){ c.wantA = c.maxA; continue; }
    let kw = c.plan[slot] || 0;
    if (c.soc < c.need && c.slack < CRIT_MIN/2) kw = CH_KW;   // fell behind plan: catch up now
    c.wantA = Math.min(c.maxA, Math.round(kw*1000/VOLTS)); if (c.wantA>0 && c.wantA<MIN_A) c.wantA = MIN_A;
  }
  if (cfg.managed){ // free solar beyond the plan tops vans up
    let spare = solar - st.cars.reduce((a,c)=>a+c.wantA*VOLTS/1000, 0);
    for (const c of [...st.cars].sort((a,b)=>a.soc-b.soc)){
      if (spare < MIN_A*VOLTS/1000 || c.maxA<=c.wantA) continue;
      const add = Math.min(c.maxA-c.wantA, Math.floor(spare*1000/VOLTS));
      if (c.wantA+add >= MIN_A){ c.wantA += add; spare -= add*VOLTS/1000; }
    }
  }
  const reserveKwh = st.battCap*cfg.reserve/100;
  // Grid is back after an outage: refill EV storage from solar + grid together, at any hour, until it is full again.
  if (st.wasOutage && !st.outage && st.battCap>0 && st.batt < st.battCap-0.5){ st.recovering = true; note(st, 'solar', 'Grid restored — recharging EV storage from rooftop solar + the grid.'); }
  st.wasOutage = st.outage;
  if (st.recovering && (st.batt >= st.battCap-0.5 || st.outage)) st.recovering = false;
  const battAvail = st.battCap>0 ? Math.min(st.battKw, Math.max(0, st.batt - (st.outage ? 0 : reserveKwh))*ETA_OUT/h) : 0;
  const evCap = !cfg.managed ? (st.outage ? 0 : Infinity)
              : st.outage ? Math.max(0, solar + battAvail - bldg)
              : Math.max(0, cfg.limit - bldg) + solar + battAvail;
  const evKw = allocate(st.cars, evCap), officeOnly = evKw < 0.5;
  st.officeOnly = officeOnly;

  // Rooftop solar serves the chargers first, then fills EV storage; once storage is full (or at its charge limit) the rest goes to the Corporate Office, and only what's left is exported.
  // EV storage (one inverter: charge or discharge, not both) covers chargers and building during the peak and in an outage.
  let toBatt = 0, gridToBatt = 0, fromBatt = 0, battToEv = 0, battToBldg = 0, mode = 'idle';
  const solarToEv = Math.min(solar, evKw);
  let surplus = solar - solarToEv;
  const room = st.battCap>0 ? Math.max(0, st.battCap - st.batt)/ETA_IN/h : 0;
  // In an outage the loads come first (storage is depleting, so solar relieves it); otherwise storage fills first.
  let solarToBatt = 0, solarToBldg = 0;
  if (st.outage){ solarToBldg = cfg.managed ? Math.min(surplus, bldg) : 0; surplus -= solarToBldg; solarToBatt = Math.min(surplus, st.battKw, room); surplus -= solarToBatt; }
  else { solarToBatt = Math.min(surplus, st.battKw, room); surplus -= solarToBatt; solarToBldg = cfg.managed ? Math.min(surplus, bldg) : 0; surplus -= solarToBldg; }
  const deficit = evKw - solarToEv, bldgNeed = bldg - solarToBldg;
  if (st.battCap>0){
    toBatt = solarToBatt; if (toBatt>0.2) mode = 'solar';
    if (st.outage){
      fromBatt = Math.min(deficit + bldgNeed, battAvail); if (fromBatt>0.2) mode = 'backup';
    } else {
      // Stored energy is saved for the 4-9 pm peak. With storageUse 'peak+night', what's left after the peak also
      // replaces off-peak grid power for charging overnight (tomorrow's rooftop solar refills it). Always allowed: keeping the site under its limit.
      const over = Math.max(0, bldgNeed + deficit - cfg.limit);
      // at peak the building only gets stored energy the vans' plan doesn't need
      const spare = Math.max(0, (st.batt - reserveKwh)*ETA_OUT - Math.max(0, (st.storeForEv||0) - deficit*h));
      // peak balance: vans keep their planned storage-fed charge; the Corporate Office draws storage at a steady rate that lasts to 21:00
      // and the grid supplies the rest, so neither runs out early nor does the grid demand spike late in the peak.
      const peakFair = Math.max(0, st.batt - reserveKwh)*ETA_OUT / Math.max(0.25, (21*60 - t)/60);
      const cover = st.recovering ? 0 : per==='peak' ? deficit + Math.min(bldgNeed, spare/h, Math.max(0, peakFair - deficit)) : (cfg.storageUse==='peak+night' && t >= 21*60 ? deficit : 0);
      fromBatt = Math.min(Math.max(over, cover), battAvail);
      if (fromBatt>0.2) mode = over > cover ? 'shave' : per==='peak' ? 'peak' : 'night';
      // fill before the peak (from cheap grid only if allowed); overnight only keep the backup reserve
      // when only the Corporate Office is drawing power (no van charging), use the idle capacity to fill EV storage, balanced under the limit
      const want = st.recovering ? st.battCap : (officeOnly && per!=='peak' && cfg.gridTopUp!==false) ? st.battCap : t < 16*60 && per!=='peak' ? (cfg.gridTopUp===false ? 0 : st.battCap) : (t >= 21*60 ? reserveKwh : 0);
      if (fromBatt<0.2 && st.batt < want-0.5){
        const head = Math.min(cfg.limit - bldgNeed - deficit, st.subTarget - deficit);
        gridToBatt = Math.max(0, Math.min(st.battKw - toBatt, head, room - toBatt, (want - st.batt)/ETA_IN/h));
        if (gridToBatt>0.2) mode = mode==='solar' ? 'solar+grid' : 'grid';
      }
    }
    battToEv = Math.min(fromBatt, deficit); battToBldg = fromBatt - battToEv;
    if (per==='peak') st.storeForEv = Math.max(0, (st.storeForEv||0) - battToEv*h);
    st.batt = Math.min(st.battCap, Math.max(0, st.batt + (toBatt+gridToBatt)*ETA_IN*h - fromBatt/ETA_OUT*h));
  }
  const evImport = st.outage ? 0 : Math.max(0, deficit - battToEv + gridToBatt);
  const bldgImport = st.outage ? 0 : Math.max(0, bldgNeed - battToBldg);
  const site = evImport + bldgImport;
  if (!st.outage && site > cfg.limit + 0.5){ st.trips++; note(st, 'gateway', `BREAKER TRIP — ${site.toFixed(1)} kW over the ${cfg.limit} kW limit.`); }
  st.modeNow = mode;
  // log battery behaviour changes, ignoring idle blips and flips within 30 minutes
  if (cfg.managed && st.battCap>0 && mode!=='idle' && mode!==st.battMode && (t - (st.battLogT||0) >= 30 || mode==='backup')){
    const msg = {solar:'EV storage charging from rooftop solar (free).', grid:`EV storage topping up from the grid at ${PERIOD_NAME[per].toLowerCase()} price, ready for the evening peak.`,
      'solar+grid':'EV storage charging from rooftop solar and cheap grid power.', peak:'EV storage powering the chargers through the peak — no peak-price grid power bought.',
      night:'EV storage supplying chargers with leftover stored solar instead of buying grid power.',
      shave:`EV storage discharging to keep the site under ${cfg.limit} kW.`, backup:'Grid outage — EV storage and rooftop solar are powering the depot.'}[mode];
    note(st, 'solar', `${msg}${officeOnly && (mode==='grid' || mode==='solar+grid' || mode==='solar') ? ' Only the Corporate Office is drawing power, so storage is being refilled, balanced under the site limit.' : ''} (${Math.round(st.batt/st.battCap*100)}%)`); st.battMode = mode; st.battLogT = t;
  }

  const sunShare = evKw>0 ? solarToEv/evKw : 0;
  for (const c of st.cars){
    if (c.status==='Away' || c.status==='Departed') continue;
    if (c.fault) c.downMin = (c.downMin||0) + dt;
    const prev = c.status;
    c.status = c.soc>=c.need ? 'Ready' : c.amps===0 ? (cfg.managed && !c.critical && (c.plan[slot]||0)===0 && !st.outage ? 'Scheduled' : 'Paused')
             : (c.amps < c.wantA-1 ? 'Throttled' : 'Charging');
    if (c.status!==prev && ['Throttled','Paused','Ready'].includes(c.status))
      note(st, 'gateway', `${c.name} → ${c.status}${c.status==='Ready' ? ` (reached ${c.need}%)` : ` at ${c.amps} A`}`);
    if (c.critical && !c.wasCrit) note(st, 'agent', `${c.name} is critical (slack ${Math.round(c.slack)} min to ${fmtClock(c.dep)}) → charged first${per==='peak' ? ', even at peak price' : ''}.`);
    c.wasCrit = c.critical;
    const kwh = c.amps*VOLTS/1000*h; c.kwh += kwh; c.soc = Math.min(100, c.soc + kwh/c.cap*100);
    c.wantKwh = (c.wantKwh||0) + c.wantA*VOLTS/1000*h; c.costKwh = (c.costKwh||0) + kwh; c.cost = (c.cost||0) + kwh*(1-sunShare)*price; if (per==='peak') c.peakKwh = (c.peakKwh||0) + kwh;
  }
  if (cfg.managed) depotAgents(st, {per, evKw, bldg, solar, battAvail});

  // log the peak split once an hour
  if (cfg.managed && st.battCap>0 && per==='peak' && Math.floor(t/60)!==st.peakNoteH){
    st.peakNoteH = Math.floor(t/60);
    const lasts = fromBatt>0.5 ? Math.max(0, st.batt - reserveKwh)*ETA_OUT/fromBatt*60 : null;
    note(st, 'solar', `Peak balance: EV storage ${fromBatt.toFixed(0)} kW + grid ${site.toFixed(0)} kW (site limit ${cfg.limit} kW)` + (lasts!=null ? `; at this rate storage lasts about ${Math.round(Math.min(lasts, 21*60-t))} min of the ${Math.round(21*60-t)} min left in the peak` : '; storage is idle') + '.');
  }
  const k = st.cost;
  k.evUsd += evImport*h*price; k.kwh[per] += evImport*h;
  k.bldgUsd += bldgImport*h*(per==='peak' ? cfg.bldgPrice.max : cfg.bldgPrice.min);
  k.solarKwh += solar*h; k.solarToEv += solarToEv*h; k.solarToBldg = (k.solarToBldg||0) + solarToBldg*h; k.exportKwh += surplus*h; k.battIn += (toBatt+gridToBatt)*h; k.battOut += fromBatt*h; k.evKwh += evKw*h;
  if (st.hvac){ st.hvacKwh += HVAC_KW*h; st.hvacMin += dt; }
  st.peakEvImport = Math.max(st.peakEvImport, evImport); st.peakSite = Math.max(st.peakSite, site);

  const out = outdoorTemp(t, cfg.wx) + (st.snap ? SNAP : 0);
  for (let i=0; i<dt; i++) st.tin = Math.min(MAX_TIN, st.tin - K*(st.tin-out) + (st.hvac ? HEAT : 0));
  st.hist.push({t, bldg, ev:evKw, solar, toBatt:toBatt+gridToBatt, solarToBatt:toBatt, gridToBatt, solarToEv, solarToBldg, exportKw:surplus,
                fromBatt, battToEv, battToBldg, bldgImport,
                grid:site, evImport, batt:st.battCap ? st.batt/st.battCap*100 : null,
                tin:st.tin, tout:out, hvac:st.hvac, per, price});
  st.t += dt;
  if (st.t >= END_MIN) st.done = true;
}

// Night and monthly cost. Only the parts that differ between scenarios: EV-meter energy + subscription, building energy.
function costs(st){
  const k = st.cost, blocks = Math.max(1, Math.ceil(st.peakEvImport/BEV1.blockKw - 1e-9));
  const evEnergy = k.evUsd + k.prechargeUsd, nightly = evEnergy + k.bldgUsd, sub = blocks*BEV1.blockUsd;
  const wearNight = st.wear ? k.battOut*st.wear.wearPerKwh : 0;   // not part of monthly_usd, so the saving figures stay comparable with the baseline
  return {wear_usd_night:+wearNight.toFixed(2), wear_usd_month:Math.round(wearNight*30), monthly_net_of_wear_usd:Math.round(nightly*30 + sub + wearNight*30),
    storage_cycles_night:st.battCap ? +(k.battOut/st.battCap).toFixed(2) : 0,
    ev_energy_usd:+evEnergy.toFixed(2), building_energy_usd:+k.bldgUsd.toFixed(2), nightly_usd:+nightly.toFixed(2),
    subscription_blocks:blocks, subscription_usd_month:+sub.toFixed(2), monthly_usd:Math.round(nightly*30 + sub),
    grid_kwh:{peak:+k.kwh.peak.toFixed(1), off:+k.kwh.off.toFixed(1), super:+k.kwh.super.toFixed(1)},
    solar_kwh:+k.solarKwh.toFixed(1), solar_to_ev_kwh:+k.solarToEv.toFixed(1), solar_to_building_kwh:+(k.solarToBldg||0).toFixed(1), solar_export_kwh:+k.exportKwh.toFixed(1),
    battery_out_kwh:+k.battOut.toFixed(1), ev_kwh:+k.evKwh.toFixed(1), peak_ev_import_kw:+st.peakEvImport.toFixed(1),
    peak_site_kw:+st.peakSite.toFixed(1), hvac_kwh:+st.hvacKwh.toFixed(1), trips:st.trips};
}
function runFull(cfg, dt=5){ const st = createSim({...cfg, quiet:true}); while (!st.done) step(st, dt); return st; }
// "Without this system": vans charge at full power the moment they plug in, no solar or battery, standard thermostat.
function baselineCfg(cfg){ return {...cfg, managed:false, solarKwp:0, battKwh:0, battKw:0, mode:cfg.mode==='force' ? 'force' : 'standard', quiet:true}; }
