# Bob task 01 — Python repository (Architect, then Code)
Owner: Engine lead · Week: Oct 19-25 · Planned credits: 35

**Goal:** the repository structure the coach asked for, in Python, with the same behaviour as the working prototype.

**Give Bob these files as context:** `depot-engine.js`, `common.js`, `server.py`.

**Prompt (Architect Mode):**
> Read depot-engine.js, common.js and server.py. Design a Python package `depot_ev/` with:
> - `fleet_simulator.py` — the five vans from common.js (FLEET), plugging in from 13:00 and reporting state of charge;
> - `gateway_controller.py` — the charging planner (cheapest energy first: rooftop solar, stored solar at peak, super off-peak,
>   off-peak; peak only for critical vans), load balancing under the site limit, EV storage rules (vans' required charge first,
>   backup reserve, outage) and the HVAC rule (stop when comfortable, re-trigger 5% below the actual trigger temperature);
> - `watsonx_reporter.py` — builds the night summary and calls watsonx Granite (same prompt as depot_prompt in server.py).
> Use the same constants and PG&E BEV-1 prices as depot-engine.js. Plan files and functions before writing code.

**Then (Code Mode):** implement one file per request, in that order.

**Done when:** `python -m depot_ev.run_night` prints a summary whose monthly cost, peak kWh and vans-ready match the Depot page
for the same settings (about $2,000/month with 60 kW solar + 100 kWh storage; $4,212 without the system).

**After:** export the session report to `bob_sessions/01-python-repo`; log credits.
