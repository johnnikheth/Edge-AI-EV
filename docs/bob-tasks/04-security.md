# Bob task 04 — security scan and fixes (Code + Semgrep)
Owner: Engine lead · Week: Nov 2-8 · Planned credits: 15

**Prompt:**
> Run a Semgrep scan on server.py, common.js, depot-engine.js and the HTML pages. Fix the findings. Also: validate all /api
> inputs (types, limits), make sure API keys (WATSONX, SF511, NREL, OPENEI) are never returned to the browser or written to
> logs, escape all user-visible text, and add a simple sign-in so only the depot team can use the app and API.

**Done when:** the scan is clean (or remaining findings are documented as accepted) and the app still works.

**After:** export to `bob_sessions/04-security`; log credits.
