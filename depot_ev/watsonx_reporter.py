"""watsonx_reporter.py — Builds the night-summary prompt and calls watsonx Granite.

Ported from server.py: depot_prompt(), granite(), iam_token().

Environment variables (all optional — without them generate_brief() returns the
template text and does not call the network):
  WATSONX_API_KEY      IBM Cloud IAM API key
  WATSONX_PROJECT_ID   watsonx.ai project GUID
  WATSONX_URL          base URL (default: https://us-south.ml.cloud.ibm.com)
  WATSONX_MODEL        model ID (default: ibm/granite-3-8b-instruct)
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.parse
import urllib.request
from typing import Optional

# ---------------------------------------------------------------------------
# IAM token cache
# ---------------------------------------------------------------------------
_tok: dict = {"v": None, "exp": 0}


def _ssl_ctx() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=os.getenv("SSL_CERT_FILE") or None)


def _iam_token() -> str:
    if _tok["v"] and time.time() < _tok["exp"] - 60:
        return _tok["v"]
    data = urllib.parse.urlencode({
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": os.environ["WATSONX_API_KEY"],
    }).encode()
    req = urllib.request.Request(
        "https://iam.cloud.ibm.com/identity/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20, context=_ssl_ctx()) as r:
        j = json.load(r)
    _tok["v"], _tok["exp"] = j["access_token"], time.time() + int(j.get("expires_in", 3600))
    return _tok["v"]


# ---------------------------------------------------------------------------
# Granite call
# ---------------------------------------------------------------------------
def call_granite(prompt: str, max_tokens: int = 350) -> str:
    """Send *prompt* to watsonx Granite and return the generated text.

    Raises RuntimeError if WATSONX_API_KEY / WATSONX_PROJECT_ID are not set.
    """
    if not (os.getenv("WATSONX_API_KEY") and os.getenv("WATSONX_PROJECT_ID")):
        raise RuntimeError("WATSONX_API_KEY and WATSONX_PROJECT_ID must be set")
    base = os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com").rstrip("/")
    body = {
        "model_id": os.getenv("WATSONX_MODEL", "ibm/granite-3-8b-instruct"),
        "project_id": os.environ["WATSONX_PROJECT_ID"],
        "input": prompt,
        "parameters": {"decoding_method": "greedy", "max_new_tokens": max_tokens},
    }
    req = urllib.request.Request(
        f"{base}/ml/v1/text/generation?version=2023-05-29",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {_iam_token()}",
        },
    )
    with urllib.request.urlopen(req, timeout=60, context=_ssl_ctx()) as r:
        return json.load(r)["results"][0]["generated_text"].strip()


# ---------------------------------------------------------------------------
# Prompt builder — mirrors depot_prompt() in server.py
# ---------------------------------------------------------------------------
def build_prompt(night_result: dict) -> str:
    """Format a night-summary payload into the Granite prompt.

    *night_result* should contain at minimum:
      vehicles: list of {name, soc, need, ready, met}
      costs:    {with_system: {...}, without_system: {...}}
    """
    return (
        "You are an operations assistant for an EV delivery Corporate Office. "
        "Write a short morning readiness brief (under 150 words) for the Corporate Office manager "
        "from this JSON. State how many vehicles met their delivery requirement, the peak demand "
        "versus the site limit, how load balancing helped, and anything needing attention.\n\n"
        + json.dumps(night_result)
    )


# ---------------------------------------------------------------------------
# Template fallback (used when watsonx is not configured)
# ---------------------------------------------------------------------------
def _template_brief(night_result: dict) -> str:
    """Generate a plain-text brief without calling watsonx."""
    vehicles = night_result.get("vehicles", [])
    ready = [v for v in vehicles if v.get("ready") or v.get("met")]
    n_ready = len(ready)
    n_total = len(vehicles)
    costs = night_result.get("costs", {})
    ws = costs.get("with_system", {})
    peak_kw = ws.get("peak_ev_import_kw", "?")
    limit = night_result.get("site_limit_kw", "?")
    monthly = ws.get("monthly_usd", "?")
    savings = costs.get("monthly_savings_usd", "?")

    lines = [
        f"Morning readiness brief (template — watsonx not configured):",
        f"  • {n_ready}/{n_total} vehicles met their route charge requirement.",
        f"  • Peak EV demand: {peak_kw} kW vs site limit {limit} kW.",
        f"  • Estimated monthly cost with the system: ${monthly:,}." if isinstance(monthly, int) else f"  • Estimated monthly cost: {monthly}.",
        f"  • Estimated monthly savings: ${savings:,}." if isinstance(savings, int) else "",
    ]
    not_ready = [v["name"] for v in vehicles if not (v.get("ready") or v.get("met"))]
    if not_ready:
        lines.append(f"  ⚠ Needs attention: {', '.join(not_ready)} did not meet their requirement.")
    return "\n".join(l for l in lines if l)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def generate_brief(night_result: dict) -> dict:
    """Build a morning brief for *night_result*.

    Returns {"text": str, "source": "watsonx-granite" | "template"}.
    """
    prompt = build_prompt(night_result)
    if os.getenv("WATSONX_API_KEY") and os.getenv("WATSONX_PROJECT_ID"):
        try:
            text = call_granite(prompt)
            return {"text": text, "source": "watsonx-granite"}
        except Exception as e:
            return {"text": _template_brief(night_result),
                    "source": "template",
                    "error": str(e)}
    return {"text": _template_brief(night_result), "source": "template"}
