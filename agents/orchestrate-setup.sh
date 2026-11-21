#!/usr/bin/env bash
# Bob task 03 — Orchestrate agent: import commands and test Q&A
# ============================================================
# Owner: AI & Platform lead
# Run after server.py is reachable via an HTTPS tunnel (testing) or IBM Cloud (Bob 05 prod).
#
# PRE-FLIGHT CHECKLIST (verify all before importing into Orchestrate):
#   [ ] server.py is running:  python server.py 8000
#   [ ] DEPOT_TOKEN is set in .env and loaded (see Task 04 report)
#   [ ] tools/depot-api.openapi.yaml  servers[0].url  is a real HTTPS URL (not the placeholder)
#   [ ] At least one completed depot-night session is saved (run the app once and let it finish)


# ── 1. Prerequisites ─────────────────────────────────────────────────────────

# Install the ADK CLI (once per machine):
pip install ibm-watson-orchestrate-adk

# Log in to your watsonx Orchestrate instance:
orchestrate login
# You will be prompted for your IBM Cloud API key and region.


# ── 2. Load the DEPOT_TOKEN and start the server ─────────────────────────────

# Load .env variables (PowerShell — run this in a separate PowerShell window):
#   Get-Content .env | ForEach-Object {
#     if ($_ -notmatch '^#' -and $_ -match '=') {
#       $k,$v = $_ -split '=',2
#       [System.Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
#     }
#   }
#   python server.py 8000

# On Linux/macOS:
#   export $(grep -v '^#' .env | xargs)
#   python server.py 8000


# ── 3. Expose server.py over HTTPS for testing ───────────────────────────────

# Option A — localtunnel (no account, no install beyond npx):
npx localtunnel --port 8000
#   Prints a URL like:  https://depot-ev.loca.lt
#   NOTE: localtunnel adds a browser-warning page on first visit; for API calls
#         pass the bypass header:  --local-host localhost  (or use ngrok instead)

# Option B — ngrok (more reliable for API access, free account required):
#   Install: https://ngrok.com/download
#   ngrok http 8000
#   Prints: Forwarding  https://abc123.ngrok-free.app -> http://localhost:8000


# ── 4. Set the tunnel URL in the OpenAPI spec ────────────────────────────────

# Edit tools/depot-api.openapi.yaml, the servers section (around line 15):
#   - url: https://abc123.ngrok-free.app      ← paste your tunnel URL here
#
# Verify the server is reachable through the tunnel:
#   curl -H "Authorization: Bearer $DEPOT_TOKEN" https://abc123.ngrok-free.app/api/sessions
#   Expected: []  (empty array if no sessions saved yet, or a JSON array)


# ── 5. Configure BearerAuth credential in Orchestrate ────────────────────────
#
# The OpenAPI spec now declares  security: [BearerAuth: []]  with scheme: bearer.
# Orchestrate must be told the token value so it can pass it on every tool call.
#
# In the watsonx Orchestrate web UI:
#   1. Go to  Settings → Connections  (or the tool's "Connections" tab after import)
#   2. Click "Add connection" for the Depot EV API tool
#   3. Select type: "API key" or "Bearer token"
#   4. Paste the value of DEPOT_TOKEN from your .env file
#   5. Save — Orchestrate will inject  Authorization: Bearer <token>  automatically
#
# Alternatively via ADK CLI (if supported in your lab environment):
#   orchestrate connections create --name depot-ev-token --type bearer --value "$DEPOT_TOKEN"
#   orchestrate tools update depot_ops_agent --connection depot-ev-token


# ── 6. Import tools (MUST come before the agent) ─────────────────────────────

orchestrate tools import -k openapi -f tools/depot-api.openapi.yaml

# Expected output:
#   Importing tool: list_sessions          ✓
#   Importing tool: get_session            ✓
#   Importing tool: list_customer_messages ✓
#   Importing tool: find_building_tariffs  ✓
#   Importing tool: get_live_traffic       ✓

# Verify:
orchestrate tools list


# ── 7. Import the main operations agent ───────────────────────────────────────

orchestrate agents import -f agents/depot_ops_agent.yaml

# Expected output:
#   Agent 'depot_ops_agent' imported successfully.

# Optionally also import the three command sub-agents:
#   orchestrate agents import -f agents/energy_command.yaml
#   orchestrate agents import -f agents/fleet_command.yaml
#   orchestrate agents import -f agents/business_command.yaml

# Verify:
orchestrate agents list


# ── 8. Five test questions with expected answers ──────────────────────────────
#
# Run these in the Orchestrate chat UI after saving at least one completed
# depot-night session from the Depot EV web app.
#
# To save a session:
#   1. Open http://localhost:8000 (or the tunnel/Cloud URL)
#   2. Click "Run night" and wait for the simulation to finish
#   3. The app posts the result to /api/sessions automatically
#
# ────────────────────────────────────────────────────────────────────────────
# Q1: "Are all vans ready this morning?"
#
# Expected answer (numbers come from the saved session):
#   "Yes, all 5 vans met their route charge requirement last night.
#    Van 1 departed at 89% (needed 83%), Van 2 at 89% (needed 69%),
#    Truck 3 at 90% (needed 64%), Van 4 at 87% (needed 63%),
#    Van 5 at 89% (needed 79%).
#    These figures are simulated — one typical night."
#
# How the agent answers it:
#   list_sessions → find latest depot session → get_session(id) →
#   read meta.vehicles[].ready and meta.vehicles[].soc
#
# ────────────────────────────────────────────────────────────────────────────
# Q2: "How much did we save last night?"
#
# Expected answer (example):
#   "Last night the system saved $71.49 compared to charging without solar or
#    storage ($67.37 with the system vs $138.86 without).
#    Over a month that's about $2,169 in savings, mainly by avoiding PG&E
#    BEV-1 peak prices ($0.357/kWh, 4–9 pm) using rooftop solar and EV storage.
#    These figures are simulated — one typical night scaled by 30."
#
# How the agent answers it:
#   list_sessions → get_session(id) →
#   read meta.costs.nightly_savings_usd and meta.costs.monthly_savings_usd
#
# ────────────────────────────────────────────────────────────────────────────
# Q3: "How much did we buy at peak?"
#
# Expected answer (example — normal night, no critical vans):
#   "Last night 0.0 kWh was bought from the grid at peak price (4–9 pm).
#    Rooftop solar and EV storage covered all van charging during the peak window."
#
# If storage ran low and some peak grid was needed:
#   "Last night 3.2 kWh was bought at the peak rate ($0.357/kWh) —
#    Van 1 was critical (less than 90 minutes to departure) so it charged through peak."
#
# How the agent answers it:
#   get_session(id) → read meta.costs.with_system.grid_kwh.peak
#
# ────────────────────────────────────────────────────────────────────────────
# Q4: "Which customers were told about delays today?"
#
# Expected answer (no delays):
#   "No customer delay messages were sent today — all vans departed on time."
#
# Expected answer (delays recorded):
#   "Two customers were notified of delays:
#    - Van 2's customer at stop S-07: 'Your delivery may arrive about 30 minutes
#      later than planned. We'll confirm your new window this morning.'
#    - Van 4's customer at stop S-03: same message, 20-minute delay.
#    These messages are stored in the app — a dispatcher must approve before sending."
#
# How the agent answers it:
#   list_customer_messages() → filter by today's date or most recent session_id
#
# ────────────────────────────────────────────────────────────────────────────
# Q5: "Is there any live traffic near the depot?"
#
# Expected answer (SF511 not configured — no key set):
#   "Live traffic is not connected — the server needs an SF511_API_KEY to
#    show real incidents. Set the environment variable and restart server.py."
#
# Expected answer (configured, no incidents):
#   "No active traffic incidents are reported near the depot right now."
#
# Expected answer (configured, incidents present):
#   "Yes — 2 active incidents near Oakland:
#    - I-880 NB at Oak St: ACCIDENT, severity MAJOR (updated 07:14)
#    - SR-61 EB: ROAD_CLOSURE, severity MINOR (updated 06:55)"
#
# How the agent answers it:
#   get_live_traffic() → check configured; if false, report not connected;
#   if true, summarise events[]


# ── 9. Update the servers URL for production (after Bob 05) ──────────────────
#
# After deploying to IBM Cloud Code Engine (Bob task 05), replace the tunnel URL:
#
#   In tools/depot-api.openapi.yaml, servers section:
#     - url: https://depot-ev-<hash>.us-south.codeengine.appdomain.cloud
#
# Then re-import the tools so Orchestrate uses the permanent URL:
#   orchestrate tools import -k openapi -f tools/depot-api.openapi.yaml
#
# The agent YAML does not need re-importing (it references tool names, not URLs).
# The BearerAuth credential in Orchestrate does not need updating either (token is the same).
