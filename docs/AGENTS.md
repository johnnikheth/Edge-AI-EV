# Depot EV agent hierarchy

Eleven agents report to three command (supervisor) agents. Each command reads its agents and reaches one
conclusion — GO, WATCH or ACTION NEEDED. The worst of the three is the **Depot verdict** (Agents tab, hero chip, morning brief).

| Command | Agents | Notes |
|---|---|---|
| Energy Command | Power, Solar & Storage, Tariff, Outage resilience, Demand response | Decide alone; Tariff recommends only; Demand response is simulated (no program rates) and reports grid kWh actually avoided at peak |
| Fleet Command | Fleet planner, Dispatch, Battery health, Charger faults | Planner proposes route swaps — the dispatcher approves; faults open a maintenance ticket and track downtime; Battery health uses per-van history saved in SQLite |
| Business Command | Customer communications, Reporting | Customer drafts wait for approval; drafts escalate near departure; the dispatcher logs customer replies; Reporting queues the owner report. Messages and reports are stored, not sent |

In the app the member agents are rule-based (`depot-engine.js`: `plan`, `fleetPlanner`, `depotAgents`) and the commands are
`supervisors()` in `index.html`. The watsonx Orchestrate versions are `agents/energy_command.yaml`, `fleet_command.yaml`,
`business_command.yaml` (read-only, same rules, using the saved-data tools); `depot_ops_agent.yaml` is the Q&A assistant.

## Orchestrate agent files (7 total)

| File | Kind | Role |
|---|---|---|
| `agents/depot_ops_agent.yaml` | Q&A assistant | Main conversational agent — answers any depot question using all tools |
| `agents/energy_command.yaml` | Supervisor | Energy agents: Power, Solar & Storage, Tariff, Outage resilience, Demand response |
| `agents/fleet_command.yaml` | Supervisor | Fleet agents: Fleet planner, Dispatch, Battery health, Charger faults |
| `agents/business_command.yaml` | Supervisor | Business agents: Customer communications, Reporting |
| `agents/solar_storage.yaml` | Specialist subagent | Solar kWh generated and battery draw-down per night |
| `agents/fleet_planner.yaml` | Specialist subagent | Van readiness — flags any van short of route charge, proposes swaps |
| `agents/tariff.yaml` | Specialist subagent | Tariff lookup (OpenEI) — flags which commercial tariffs apply to the depot |

### Import order

```bash
# 1. Import tools (once)
orchestrate tools import -k openapi -f tools/depot-api.openapi.yaml

# 2. Import specialist subagents first
orchestrate agents import -f agents/solar_storage.yaml
orchestrate agents import -f agents/fleet_planner.yaml
orchestrate agents import -f agents/tariff.yaml

# 3. Import supervisors (reference the subagents)
orchestrate agents import -f agents/energy_command.yaml
orchestrate agents import -f agents/fleet_command.yaml
orchestrate agents import -f agents/business_command.yaml

# 4. Import the top-level Q&A assistant last
orchestrate agents import -f agents/depot_ops_agent.yaml
```
