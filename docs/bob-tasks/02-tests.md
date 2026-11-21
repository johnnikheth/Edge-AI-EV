# Bob task 02 — automated tests (Code)
Owner: Engine lead · Week: Oct 26-Nov 1 · Planned credits: 25

**Context:** the `depot_ev/` package from task 01 and section 14.2 of `docs/Depot-EV-Solution.pdf`.

**Prompt:**
> Write pytest tests for depot_ev. Each test runs one simulated night (or delivery day) and asserts one rule:
> 1. Normal night: grid power bought for charging between 16:00 and 21:00 is under 2 kWh unless a van is critical.
> 2. Grid import never exceeds the site limit (0 breaker trips) — normal, forced HVAC, cold snap, outage.
> 3. Every van reaches its route requirement by departure in all of those scenarios.
> 4. At peak, EV storage serves the vans' required charge before the building; top-ups never use storage.
> 5. With no EV storage configured, storage is never used.
> 6. HVAC stops at the comfortable temperature and re-triggers only at 95% of the actual trigger temperature.
> 7. Dispatch never reassigns stops or reschedules customers without approval (unless approval is switched off).
> 8. A reroute that would leave the battery below the 10% floor is never chosen.
> 9. BEV-1 prices and 10 kW subscription blocks are applied per period.

**Done when:** `pytest` passes in one command.

**After:** export to `bob_sessions/02-tests`; log credits.
