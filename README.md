# Depot EV — Electric Fleet Charging & Dispatch Manager

**IBM SkillsBuild AI Experiential Learning Lab · US 2026 Fall Cohort**

An AI-assisted operations system for a small electric delivery fleet. It optimises overnight charging costs using rooftop solar and EV storage, manages dispatch decisions with dispatcher approval, and answers operational questions through a watsonx Orchestrate agent.

---

## Problem

A small electric delivery depot in Oakland, CA operates five delivery vans and two Tesla Semis. Without a managed charging system, charging all vehicles at the standard PG&E BEV-1 rate costs approximately **$4,200/month**. Peak-hour prices ($0.357/kWh, 4–9 pm) make unmanaged overnight charging expensive.

The team also needs to know each morning: are all vans ready? How much did we spend? Were any customers notified of delays?

---

## Solution

Depot EV provides:

- **Smart overnight charging** — prioritises rooftop solar, then stored solar at peak, then super off-peak grid power. Grid peak is used only for critical vans (departing within 90 minutes).
- **EV storage management** — 100 kWh battery serves vans' required charge before the building; top-ups never use storage.
- **HVAC optimisation** — stops at the comfort temperature; re-triggers only at 95% of the actual trigger temperature (agent-mode hysteresis).
- **Dispatch agent** — proposes route swaps for vans with low charge; never reassigns stops without dispatcher approval.
- **Customer notifications** — drafts delay messages; held for approval before sending.
- **Morning brief** — watsonx Granite generates a plain-English summary of the night's results.
- **Operations agent** — watsonx Orchestrate answers five key morning questions from saved session data.

**Result:** approximately **$2,000/month** with the system vs **$4,200/month** without — saving ~$2,200/month.

---

## Architecture

```
Browser (index.html / dispatch.html / customers.html / history.html)
    │
    ├── server.py (Python HTTP server, SQLite, watsonx.ai Granite)
    │       ├── /api/sessions      saved overnight / dispatch sessions
    │       ├── /api/summarize     watsonx Granite morning brief
    │       ├── /api/incidents     511 SF Bay live traffic
    │       ├── /api/solar         NREL PVWatts solar estimate
    │       └── /api/tariffs       OpenEI utility tariffs
    │
    ├── depot_ev/ (Python simulation engine)
    │       ├── fleet_simulator.py   5 vans + 2 Semis, SOC tracking
    │       ├── gateway_controller.py charging planner, BEV-1 tariff, load balancing
    │       ├── watsonx_reporter.py  Granite brief generation
    │       └── run_night.py         CLI entry point
    │
    └── watsonx Orchestrate agent
            └── depot_ops_agent (5 OpenAPI tools → server.py /api/ endpoints)
```

**IBM tools used at runtime:**
- **watsonx Granite** (`ibm/granite-3-8b-instruct`) — generates the morning brief
- **watsonx Orchestrate** — operations agent answering morning questions

**IBM tool used to build:**
- **IBM Bob** — all six tracked build tasks (Python repo, tests, Orchestrate agent, security, deploy, docs)

---

## Quick Start — Run Locally

### Prerequisites
- Python 3.10+
- No pip dependencies — `server.py` uses the standard library only

### 1. Clone and configure
```bash
git clone <repo-url>
cd IBM-Project-main
cp .env.example .env
# Edit .env — set DEPOT_TOKEN to any random string
```

### 2. Load environment and start the server
**PowerShell:**
```powershell
Get-Content .env | ForEach-Object {
  if ($_ -notmatch '^\s*#' -and $_ -match '=') {
    $k,$v = $_ -split '=',2
    [System.Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
  }
}
python server.py 8000
```

**Linux / macOS:**
```bash
export $(grep -v '^#' .env | xargs)
python server.py 8000
```

### 3. Open the app
Navigate to **http://localhost:8000**

### 4. Run the simulation from the CLI
```bash
python -m depot_ev.run_night
```
Expected output: ~$2,046/month with system · ~$4,215/month without.

---

## Run the Tests
```bash
pytest tests/test_depot_ev.py
```
16 tests covering 9 rules: grid usage at peak, site limit, van readiness, storage priority, HVAC hysteresis, dispatch approval, battery floor, BEV-1 tariff, and solar charging. All pass in under 3 seconds.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in values before running.

| Variable | Required | Description |
|----------|----------|-------------|
| `DEPOT_TOKEN` | Recommended | Bearer token for all `/api/` endpoints. Leave blank for localhost-only dev. |
| `WATSONX_API_KEY` | Optional | IBM Cloud IAM key for watsonx.ai Granite brief generation |
| `WATSONX_PROJECT_ID` | Optional | watsonx.ai project GUID |
| `WATSONX_URL` | Optional | Defaults to `https://us-south.ml.cloud.ibm.com` |
| `WATSONX_MODEL` | Optional | Defaults to `ibm/granite-3-8b-instruct` |
| `NREL_API_KEY` | Optional | NREL PVWatts solar estimate (falls back to rate-limited DEMO_KEY) |
| `SF511_API_KEY` | Optional | 511 SF Bay live traffic incidents |
| `OPENEI_API_KEY` | Optional | OpenEI utility tariff lookup (falls back to DEMO_KEY) |
| `DB_PATH` | Container only | Absolute path for `data.db` — set to persistent volume mount in Cloud |

---

## IBM Cloud Deploy (Code Engine)

### Prerequisites
- IBM Cloud CLI with `container-registry` and `code-engine` plugins
- Docker Desktop
- IBM Cloud account with Editor access on the resource group

### One-time setup
```bash
# Create Container Registry namespace
ibmcloud cr namespace-add depot-ev -g Default

# Create Code Engine project (via console if CLI is blocked)
# https://cloud.ibm.com/codeengine/projects → Create project → depot-ev-project
```

### Deploy
```bash
# Fill in REGION, RESOURCE_GROUP, CE_PROJECT, REGISTRY_NS in ibmcloud-deploy.sh
chmod +x ibmcloud-deploy.sh
./ibmcloud-deploy.sh
```
The script builds the image, pushes to IBM Container Registry, creates Code Engine secrets from `.env`, deploys the app, and prints the HTTPS URL.

### After deploy — update Orchestrate
```bash
# In tools/depot-api.openapi.yaml, update servers[0].url with the Code Engine URL
# Then re-import the tools in Orchestrate (Edit tool → upload updated YAML)
```

---

## watsonx Orchestrate Agent

The **Depot EV Operations Assistant** answers five morning questions using the `/api/` endpoints.

### Setup
1. Open your Orchestrate instance
2. **Active inventory → Tools → Create tool → OpenAPI** → upload `tools/depot-api.openapi.yaml`
3. Select all 5 operations → Next → Add BearerAuth connection (Team credentials, paste `DEPOT_TOKEN`)
4. **Active inventory → Agents → Create agent** → fill in name/description/instructions from `agents/depot_ops_agent.yaml`
5. Tools are added automatically

See `agents/orchestrate-setup.sh` for full import commands and expected answers.

### Five test questions
| Question | What the agent reads |
|----------|---------------------|
| "Are all vans ready this morning?" | `meta.vehicles[].ready` |
| "How much did we save last night?" | `meta.costs.nightly_savings_usd` |
| "How much did we buy at peak?" | `meta.costs.with_system.grid_kwh.peak` |
| "Which customers were told about delays today?" | `/api/notifications` |
| "Is there any live traffic near the depot?" | `/api/incidents` → `configured` flag |

---

## Project Structure

```
IBM-Project-main/
├── server.py                    # HTTP server + SQLite API
├── index.html                   # Depot overnight charging UI
├── dispatch.html                # Dispatch & delivery day UI
├── customers.html               # Customer notifications UI
├── history.html                 # Session history UI
├── architecture.html            # Architecture diagram
├── common.js / common.css       # Shared frontend utilities
├── depot-engine.js              # JavaScript simulation (original prototype)
├── data-tools.js                # Data visualisation helpers
├── reference-data.js            # PG&E BEV-1 tariff constants
├── Dockerfile                   # Container image for IBM Cloud Code Engine
├── ibmcloud-deploy.sh           # One-command deploy script
├── .env.example                 # Environment variable template
├── depot_ev/                    # Python simulation engine (Bob 01)
│   ├── __init__.py
│   ├── fleet_simulator.py       # Fleet state, SOC tracking
│   ├── gateway_controller.py    # Charging planner, load balancer, BEV-1 tariff
│   ├── watsonx_reporter.py      # Granite brief generation
│   └── run_night.py             # CLI entry point
├── tests/
│   └── test_depot_ev.py         # 16 pytest tests, 9 rules (Bob 02)
├── tools/
│   └── depot-api.openapi.yaml   # OpenAPI spec for Orchestrate tools (Bob 03)
├── agents/
│   ├── depot_ops_agent.yaml     # Main operations agent (Bob 03)
│   ├── energy_command.yaml      # Energy sub-agent
│   ├── fleet_command.yaml       # Fleet sub-agent
│   ├── business_command.yaml    # Business sub-agent
│   └── orchestrate-setup.sh    # Import commands + test Q&A
├── docs/
│   ├── Depot-EV-Solution.pdf    # Full solution write-up
│   ├── TEAM_PLAN.md             # Team roles and roadmap
│   └── bob-tasks/               # Bob session task specs + credit log
├── bob_sessions/                # Bob session reports (one per task)
└── Actual Data Sets/            # Reference datasets
```

---

## IBM Tools Used

| Tool | Role |
|------|------|
| **IBM Bob** | Built all six tracked tasks: Python repo, automated tests, Orchestrate agent, security hardening, Cloud deploy artefacts, documentation |
| **watsonx Granite** (`ibm/granite-3-8b-instruct`) | Generates the overnight morning brief summarising costs, van readiness and anything needing attention |
| **watsonx Orchestrate** | Operations agent — answers the five morning questions from saved session data via OpenAPI tools |

---

## API Reference

Generated from `tools/depot-api.openapi.yaml`:
```bash
npx @redocly/cli build-docs tools/depot-api.openapi.yaml -o docs/api.html
```
See `docs/api.html` after running the command above.

---

## Security

All `/api/` endpoints require `Authorization: Bearer <DEPOT_TOKEN>`. See `bob_sessions/04-security/report.md` for the full security audit findings and accepted items.

---

*IBM SkillsBuild AI Experiential Learning Lab · US 2026 Fall Cohort · Built with IBM Bob*
