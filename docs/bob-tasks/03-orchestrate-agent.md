# Bob task 03 — watsonx Orchestrate operations agent (Code)
Owner: AI & Platform lead · Week: Oct 26-Nov 1 · Planned credits: 25

**Context:** `tools/depot-api.openapi.yaml`, `agents/depot_ops_agent.yaml`, `server.py`.

**Prompt:**
> Check agents/depot_ops_agent.yaml and tools/depot-api.openapi.yaml against the current watsonx Orchestrate Agent Development
> Kit format and fix anything that won't import. Write the commands to import the tools and the agent, and five test questions
> with expected answers: "Are all vans ready this morning?", "How much did we save last night?", "How much did we buy at peak?",
> "Which customers were told about delays today?", "Is there any live traffic near the depot?".

**Note:** Orchestrate runs in IBM Cloud, so the API must be reachable from the internet. For testing use a temporary secure
tunnel; for the final demo use the task 05 deployment. Put the URL in the OpenAPI `servers` entry.

**Done when:** the agent answers the five questions correctly from real saved sessions.

**After:** export to `bob_sessions/03-orchestrate-agent`; log credits.
