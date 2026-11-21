# Bob session report — Task 05 Deploy
Date: 2026-11-17
Owner: AI & Platform lead

## Summary
All deployment artefacts created. The image is ready to build and push to IBM Cloud
Container Registry. The AI & Platform lead must run `ibmcloud-deploy.sh` from a machine
with Docker and the IBM Cloud CLI installed to complete the live deployment.

## Files created / modified
| File | Change |
|------|--------|
| `Dockerfile` | New — slim Python 3.12 image, non-root user, PORT env var, DB_PATH for volume |
| `.dockerignore` | New — excludes .env, data.db, tests/, agents/, node_modules/, git, etc. |
| `ibmcloud-deploy.sh` | New — full deploy script: login, build, push, secrets, CE app create/update, URL print |
| `server.py` line 42 | `DB` path now reads `DB_PATH` env var (falls back to repo root for local dev) |
| `.env.example` | Added `DB_PATH=` entry with documentation |

## Design decisions
| Decision | Reason |
|----------|--------|
| `python:3.12-slim` base image | Smallest stable image; server.py has zero pip dependencies |
| `--min-scale 1` on Code Engine | Avoids cold-start delays; acceptable for a demo with 1 user |
| Secrets via `ibmcloud ce secret` | API keys never baked into the image or the script |
| `DB_PATH=/data/data.db` | Decouples storage from code; persistent volume or COS mount replaces it in production |
| Ephemeral storage for lab | Code Engine ephemeral is sufficient for the demo; noted in the script for production upgrade |

## What the AI & Platform lead must do to complete Task 05

### Prerequisites (install once)
```bash
# IBM Cloud CLI
curl -fsSL https://clis.cloud.ibm.com/install/linux | sh   # or Windows installer
ibmcloud plugin install container-registry
ibmcloud plugin install code-engine

# Docker Desktop (Windows): https://docs.docker.com/desktop/install/windows-install/
```

### One-time IBM Cloud setup
1. Create a **Code Engine project** in the IBM Cloud console:
   https://cloud.ibm.com/codeengine/projects → "Create project" → name it `depot-ev-project`
2. Create a **Container Registry namespace**:
   ```bash
   ibmcloud cr namespace-add depot-ev --resource-group default
   ```
3. Add your IBM Cloud API key to `.env` as `IBMCLOUD_API_KEY=<key>` (optional — the
   script falls back to interactive login if not set)

### Fill in ibmcloud-deploy.sh
Edit the CONFIGURATION section at the top of `ibmcloud-deploy.sh`:
- `REGION` — your IBM Cloud region (default `us-south`)
- `RESOURCE_GROUP` — your resource group (default `default`)
- `CE_PROJECT` — the project name you created above
- `REGISTRY_NS` — the namespace you created above

### Run
```bash
chmod +x ibmcloud-deploy.sh
./ibmcloud-deploy.sh
```

The script prints the HTTPS URL on success, e.g.:
```
Depot EV deployed at: https://depot-ev-abc123.us-south.codeengine.appdomain.cloud
```

### After deployment — update Orchestrate
1. Copy the printed URL
2. Edit `tools/depot-api.openapi.yaml` line 10:
   ```yaml
   - url: https://depot-ev-abc123.us-south.codeengine.appdomain.cloud
   ```
3. Re-import the tools (agent YAML does not need re-importing):
   ```bash
   orchestrate tools import -k openapi -f tools/depot-api.openapi.yaml
   ```

## Validation
- Local build test: `docker build -t depot-ev . && docker run -p 8080:8080 --env-file .env depot-ev`
- Verify: `curl http://localhost:8080` → HTTP 200
- Authenticated: `curl -H "Authorization: Bearer $DEPOT_TOKEN" http://localhost:8080/api/sessions` → `[]` or session list

## Credits used
<!-- Fill in after checking the Bob session credit counter -->
Credits planned: 25 | Credits used: 14.88
