# Bob session report — Task 03 Orchestrate Agent (completion pass)
Date: 2026-11-17
Owner: AI & Platform lead

## Summary
Task 03 files were created on 2026-11-04 (combined session 01-03). This session
completed all remaining work and ran the 5 live test questions successfully in
watsonx Orchestrate.

## What was done in this session

### File changes
| File | Change |
|------|--------|
| `tools/depot-api.openapi.yaml` | Added `security: [BearerAuth: []]` global security declaration and `components.securitySchemes.BearerAuth` (type: http, scheme: bearer). Updated `servers[0].url` from placeholder to live ngrok tunnel. |
| `agents/orchestrate-setup.sh` | Added pre-flight checklist, DEPOT_TOKEN load instructions, BearerAuth credential setup step, shebang line, optional sub-agent imports. Refined 5 Q&A examples. |

### Orchestrate setup (web UI)
| Step | Result |
|------|--------|
| Uploaded `tools/depot-api.openapi.yaml` → Import tool | 5 operations parsed, all showing Bearer Token auth |
| Selected all 5 operations | ✅ |
| Added BearerAuth connection (Team credentials, tunnel URL auto-detected) | ✅ |
| Created "Depot EV Operations Assistant" agent from scratch | ✅ |
| Added name, description, instructions from `depot_ops_agent.yaml` | ✅ |
| All 5 tools auto-added to agent | ✅ |
| Saved agent | ✅ |

## Live test results — 5/5 passed

All 5 test questions answered correctly from real session data via the ngrok tunnel.

| # | Question | Agent answer | Result |
|---|----------|-------------|--------|
| Q1 | "Are all vans ready this morning?" | "All of the vans are ready this morning — every vehicle listed in the latest depot-night session shows ready: true." | ✅ |
| Q2 | "How much did we save last night?" | "Last night we saved $71.49 compared with not using the system (nightly cost $67.37 vs $138.86). The reported monthly savings are $2,145, based on simulating one typical night multiplied over 30 days." | ✅ |
| Q3 | "How much did we buy at peak?" | "The system recorded 0 kWh bought during the 4 pm–9 pm peak period last night." | ✅ |
| Q4 | "Which customers were told about delays today?" | "No delay messages have been sent to customers today." | ✅ |
| Q5 | "Is there any live traffic near the depot?" | "Live traffic data isn't connected right now, so I can't show any incidents near the depot." | ✅ |

## Orchestrate instance details
| Item | Value |
|------|-------|
| Instance name | watsonx-Hackathon Orchestrate |
| Region | eu-de |
| Dashboard | https://eu-de.watson-orchestrate.cloud.ibm.com |
| Agent name | Depot EV Operations Assistant (main Q&A) |
| Also imported | Energy Command, Fleet Command, Business Command |
| Tools imported | 5 (list_sessions, get_session, list_customer_messages, find_building_tariffs, get_live_traffic) |
| Total agents live | 4 (depot_ops_agent + 3 command agents) |
| Auth type | Bearer Token (Team credentials) |
| Server URL used | https://bagginess-satisfied-pregame.ngrok-free.dev (ngrok tunnel) |

## Notes
- The ngrok tunnel (`bagginess-satisfied-pregame.ngrok-free.dev`) is temporary — it runs
  as long as the ngrok process (PID 39424) is active on the local machine.
- After Bob 05 IBM Cloud deploy, update `tools/depot-api.openapi.yaml` `servers[0].url`
  with the Code Engine HTTPS URL and re-import the tools in Orchestrate (Edit tool →
  upload updated YAML). The agent does not need to be re-created.
- IBM Cloud Code Engine project creation was blocked (resource group Viewer-only
  permission on the lab account). Lab admin needs to grant Editor on resource group
  `Default` (ID: aa3f53caec6543baa0fc206747d707fa) to complete Task 05.

## Task 03 — DONE ✅
All deliverables from `docs/bob-tasks/03-orchestrate-agent.md` are complete:
- Agent YAML files fixed and validated ✅
- OpenAPI spec has BearerAuth security scheme ✅
- Import commands documented in `agents/orchestrate-setup.sh` ✅
- Agent imported and answering all 5 test questions correctly ✅

## Credits used
<!-- Fill in after checking the Bob session credit counter -->
Credits planned (original Task 03): 25 | Credits used for this completion pass: 14.88
