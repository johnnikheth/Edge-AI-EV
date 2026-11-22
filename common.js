// Shared helpers: API client, nav bar, clock formatting, and the fleet both simulations use.

// Token: read from ?token= URL param (saves it to localStorage), then fall back to localStorage.
(function(){
  const p = new URLSearchParams(window.location.search).get('token');
  if (p) { try { localStorage.setItem('depot_token', p); } catch(e){} }
})();

const API = {
  online: false,
  config: {},
  _tok() { try { return localStorage.getItem('depot_token') || ''; } catch(e){ return ''; } },
  async j(method, url, body) {
    const tok = this._tok();
    const sep = url.includes('?') ? '&' : '?';
    const authUrl = tok ? url + sep + 'token=' + encodeURIComponent(tok) : url;
    const r = await fetch(authUrl, {method, headers: {'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)});
    if (!r.ok) throw new Error(r.status);
    return r.json();
  },
};
const fmtClock = m => { m = ((m % 1440) + 1440) % 1440; return String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(Math.floor(m % 60)).padStart(2, '0'); };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

// Simulated depot near Oakland, CA (inside 511 SF Bay and PG&E coverage).
const DEPOT = {name: 'Oakland Corporate Office (simulated)', lat: 37.7510, lon: -122.1990};

// One fleet for both pages. Depot: cap (kWh), soc when it returns and plugs in, plug (minutes after 13:00), dep (minutes, 24*60+ = next morning).
// Delivery route: stops, packages, drain (% battery per stop), ret (% to drive back), bearing (compass direction of the route from the depot).
// Tesla Semi (interstate long-haul):
//   cap: 500 kWh usable battery.
//   stops: 3 major city drop-offs per run (e.g. Oakland → Fresno → Bakersfield → LA).
//   drain: 40% per leg (~500 km at 1 kWh/km on a 500 kWh pack = 200 kWh = 40%).
//   ret: 35% for the return leg (~350–400 km empty).
//   Semis run every 2-3 days: one is back tonight (plug:120), the other is still on the road (plug beyond END_MIN — absent this session).
//   daysOut: advisory field — how many nights between depot visits (not used by the engine, shown in the Agents panel).
//   chKw: 50 kW Megacharger connection on the dedicated semi bay (site-limited).
// chKw: per-vehicle charger rate. Vans use the default Level-2 charger (7.68 kW).
const FLEET = [
  {name: 'Van 1',         cap: 80,  soc: 16, plug: 0,    dep: 29*60,    stops: 22, pk: 60,  drain: 2.8, ret: 6,  bearing: 20},
  {name: 'Van 2',         cap: 80,  soc: 18, plug: 15,   dep: 29*60+45, stops: 16, pk: 45,  drain: 3.0, ret: 6,  bearing: 70},
  {name: 'Truck 3',       cap: 100, soc: 20, plug: 30,   dep: 28*60+30, stops: 24, pk: 110, drain: 1.8, ret: 5,  bearing: 110},
  {name: 'Van 4',         cap: 80,  soc: 17, plug: 60,   dep: 29*60+45, stops: 14, pk: 38,  drain: 3.0, ret: 6,  bearing: 150},
  {name: 'Van 5',         cap: 60,  soc: 15, plug: 90,   dep: 29*60+30, stops: 18, pk: 52,  drain: 3.2, ret: 6,  bearing: 340},
  {name: 'Semi A',        cap: 500, soc: 9,  plug: 120,  dep: 31*60,    stops: 3,  pk: 300, drain: 40,  ret: 35, bearing: 200, chKw: 50, daysOut: 2},
  {name: 'Semi B',        cap: 500, soc: 10, plug: 1080, dep: 31*60,    stops: 3,  pk: 300, drain: 40,  ret: 35, bearing: 280, chKw: 50, daysOut: 2},
];
const FLOOR = 10, RESERVE = 5, TOPUP = 90;
// Battery a vehicle needs at departure to run its whole route and return with the floor plus a reserve left.
const needOf = f => Math.min(100, Math.ceil(f.stops * f.drain + f.ret + FLOOR + RESERVE));
const VCOLORS = ['#4f6bed', '#e8890c', '#12a150', '#a142f4', '#d92d20', '#0891b2', '#7c3aed'];

// Deterministic stop coordinates: an out-and-back loop in the vehicle's sector, 2.5-9.5 km from the depot.
function rng(seed) { return () => { seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function routePoints(f, idx) {
  const r = rng(idx * 977 + 13), pts = [], kmLon = 111 * Math.cos(DEPOT.lat * Math.PI / 180);
  for (let i = 0; i < f.stops; i++) {
    const a = (f.bearing + 50 * (i / Math.max(1, f.stops - 1) - 0.5) + (r() - .5) * 8) * Math.PI / 180;
    const d = 2.5 + 7 * Math.sin(Math.PI * (i + 0.5) / f.stops) + (r() - .5) * 0.8;
    pts.push([DEPOT.lat + d * Math.cos(a) / 111, DEPOT.lon + d * Math.sin(a) / kmLon]);
  }
  return pts;
}
const kmBetween = (a, b) => { const dy = (a[0] - b[0]) * 111, dx = (a[1] - b[1]) * 111 * Math.cos(a[0] * Math.PI / 180); return Math.hypot(dx, dy); };

// The latest overnight charging result: from the server, else from this browser, else null.
async function latestDepotResult() {
  if (API.online) {
    try {
      const s = (await API.j('GET', '/api/sessions')).find(x => x.kind === 'depot' && x.meta && x.meta.vehicles);
      if (s) return {id: s.id, saved: s.ended_at || s.started_at, vehicles: s.meta.vehicles, source: 'server'};
    } catch (e) {}
  }
  try { const r = JSON.parse(localStorage.getItem('depotResult') || 'null'); if (r) return {...r, source: 'browser'}; } catch (e) {}
  return null;
}

// The latest delivery-day result (battery when each vehicle got back), so the depot can start from it.
async function latestDispatchResult() {
  if (API.online) {
    try {
      const s = (await API.j('GET', '/api/sessions')).find(x => x.kind === 'dispatch' && x.meta && x.meta.vehicles);
      if (s) return {id: s.id, saved: s.ended_at || s.started_at, vehicles: s.meta.vehicles, source: 'server'};
    } catch (e) {}
  }
  try { const r = JSON.parse(localStorage.getItem('dispatchResult') || 'null'); if (r) return {...r, source: 'browser'}; } catch (e) {}
  return null;
}

// Original illustration, drawn here from scratch (no third-party artwork): corporate building with rooftop solar,
// EV storage, chargers and vans, with an animated energy path. Used as the Depot page background and as the page banner elsewhere.
function heroScene(cls) {
  const sky = [[0,250,70],[80,220,60],[150,265,50],[1520,235,80],[1460,270,50],[620,255,40],[900,268,50],[1180,250,45]]
    .map(([x,y,w]) => `<rect x="${x}" y="${y}" width="${w}" height="${360-y}" fill="var(--hero-line)" opacity=".12"/>`).join('');
  let windows = '';
  for (let r = 0; r < 4; r++) for (let c = 0; c < 11; c++) {
    if (r === 3 && c >= 5 && c <= 6) continue;
    windows += `<rect x="${92 + c*48}" y="${192 + r*38}" width="30" height="22" rx="2" fill="var(--hero-sky1)" stroke="var(--hero-line)" stroke-width="1"/>`;
  }
  let panels = '';
  for (let i = 0; i < 10; i++) { const x = 84 + i*54; panels += `<path d="M${x} 168h46l-7-24h-46Z" fill="var(--hero-panel)" stroke="var(--hero-line)" stroke-width="1.2"/><path d="M${x+23} 168l-7-24" stroke="var(--hero-panel-line)"/>`; }
  const vans = [960, 1110, 1260, 1410].map(x => `
    <g transform="translate(${x} 0)">
      <rect x="0" y="298" width="14" height="60" rx="3" fill="var(--hero-charger)"/><rect x="3" y="306" width="8" height="10" rx="1" fill="var(--hero-sky1)"/>
      <path d="M14 332 C 30 332, 30 340, 40 334" stroke="var(--hero-line)" stroke-width="2" fill="none"/>
      <path d="M36 358V322a10 10 0 0 1 10-10h70l22 22v24Z" fill="var(--hero-van)" stroke="var(--hero-line)" stroke-width="2"/>
      <path d="M116 314l18 18h-20v-18Z" fill="var(--hero-sky1)" stroke="var(--hero-line)" stroke-width="1.5"/>
      <rect x="40" y="336" width="96" height="4" fill="var(--hero-stripe)"/>
      <circle cx="58" cy="358" r="9" fill="var(--hero-line)"/><circle cx="116" cy="358" r="9" fill="var(--hero-line)"/>
    </g>`).join('');
  return `<svg class="${cls}" viewBox="0 0 1600 420" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
  <defs><linearGradient id="hsky-${cls}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--hero-sky1)"/><stop offset="1" stop-color="var(--hero-sky2)"/></linearGradient></defs>
  <rect width="1600" height="420" fill="url(#hsky-${cls})"/>
  <circle cx="1450" cy="86" r="62" fill="var(--hero-sun)" opacity=".18"/><circle cx="1450" cy="86" r="34" fill="var(--hero-sun)"/>
  <g fill="#fff" opacity=".55"><ellipse cx="420" cy="70" rx="70" ry="16"/><ellipse cx="470" cy="60" rx="40" ry="14"/><ellipse cx="1100" cy="110" rx="80" ry="15"/></g>
  ${sky}
  <rect y="358" width="1600" height="62" fill="var(--hero-ground)"/>
  <path d="M0 396H1600" stroke="var(--hero-building)" stroke-width="3" stroke-dasharray="26 22" opacity=".7"/>
  <g fill="var(--hero-tree)"><circle cx="30" cy="330" r="24"/><circle cx="660" cy="326" r="20"/><circle cx="1580" cy="320" r="26"/></g>
  <g stroke="var(--hero-line)" stroke-width="4"><path d="M30 352v8M660 344v14M1580 344v14"/></g>
  <rect x="64" y="168" width="580" height="190" fill="var(--hero-building)" stroke="var(--hero-line)" stroke-width="2"/>
  <rect x="58" y="162" width="592" height="10" fill="var(--hero-building)" stroke="var(--hero-line)" stroke-width="2"/>
  ${windows}
  <rect x="332" y="306" width="44" height="52" fill="var(--hero-sky1)" stroke="var(--hero-line)" stroke-width="1.5"/>
  ${panels}
  <text x="354" y="186" text-anchor="middle" font-family="system-ui" font-weight="700" font-size="12" fill="var(--hero-line)" letter-spacing="2">CORPORATE OFFICE · ROOFTOP SOLAR</text>
  <g><rect x="700" y="276" width="170" height="82" rx="6" fill="var(--hero-building)" stroke="var(--hero-line)" stroke-width="2"/>
    <path d="M716 290v54M732 290v54M748 290v54" stroke="var(--hero-line)" stroke-width="1.5" opacity=".5"/>
    <path d="M800 288l-14 24h11l-6 20 17-27h-11l6-17Z" fill="var(--hero-sun)"/>
    <text x="836" y="350" text-anchor="middle" font-family="system-ui" font-weight="700" font-size="11" fill="var(--hero-line)">EV STORAGE</text></g>
  <path class="hero-flow" d="M640 150 C 740 150, 785 210, 785 274" stroke="var(--hero-sun)" stroke-width="4" fill="none"/>
  <path class="hero-flow" d="M870 330 H 958" stroke="var(--hero-sun)" stroke-width="4" fill="none"/>
  ${vans}
</svg>`;
}
const HERO_SVG = heroScene('hero');


async function initNav(active) {
  const links = [['depot', 'index.html', 'Corporate Office'], ['dispatch', 'dispatch.html', 'Dispatch'], ['customers', 'customers.html', 'Customers'],
                 ['history', 'history.html', 'History'], ['arch', 'architecture.html', 'Architecture']];
  const nav = document.createElement('nav');
  nav.innerHTML = links.map(([k, h, t]) => `<a href="${h}" class="${k === active ? 'active' : ''}">${t}</a>`).join('') +
    '<span class="pill" id="srv"><i></i>checking server…</span>';
  document.querySelector('.wrap').prepend(nav);
  // pages with a hero section get the scene as its background; others get it as a banner
  const hb = document.getElementById('heroBg');
  if (hb) hb.outerHTML = heroScene('bg'); else nav.insertAdjacentHTML('afterend', HERO_SVG);
  try {
    API.config = await API.j('GET', '/api/config');
    API.online = true;
    nav.querySelector('#srv').className = 'pill on';
    nav.querySelector('#srv').innerHTML = '<i></i>Server connected — history is saved' + (API.config.granite ? ' · watsonx on' : '');
  } catch (e) {
    nav.querySelector('#srv').className = 'pill off';
    nav.querySelector('#srv').innerHTML = '<i></i>Server offline — run <b>python3 server.py</b> and open http://localhost:8000';
  }
}
