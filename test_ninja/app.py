"""Small localhost-only Ninja sandbox NIN verification app."""

from __future__ import annotations

import html
import json
import os
import re
from typing import Any

import httpx
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse

app = FastAPI(title="Ninja NIN sandbox test", docs_url=None, redoc_url=None)

SANDBOX_URL = "https://api.sandbox.ninja.boucloud.io"
SENSITIVE_RESPONSE_KEYS = {
    "id",
    "idNumber",
    "firstName",
    "lastName",
    "middleName",
    "photo",
    "provided",
}


def _config() -> tuple[str, str]:
    secret = os.environ.get("NINJA_TEST_SECRET_KEY", "").strip()
    api_url = os.environ.get("NINJA_TEST_API_URL", SANDBOX_URL).strip().rstrip("/")
    if not secret:
        raise RuntimeError("Set NINJA_TEST_SECRET_KEY in test_ninja/.env")
    if not secret.startswith("sk_sandbox_"):
        raise RuntimeError("This test harness accepts Ninja sandbox keys only")
    if api_url != SANDBOX_URL:
        raise RuntimeError(f"NINJA_TEST_API_URL must be {SANDBOX_URL}")
    return secret, api_url


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{font:16px system-ui;max-width:680px;margin:48px auto;padding:0 18px;color:#17211b}}
main{{border:1px solid #dce5df;border-radius:16px;padding:26px;box-shadow:0 8px 30px #15251b12}}
label{{display:block;margin:15px 0 6px;font-weight:650}}input{{box-sizing:border-box;width:100%;
padding:11px;border:1px solid #aebbb3;border-radius:8px}}button{{margin-top:20px;padding:12px 18px;
border:0;border-radius:8px;background:#146c43;color:white;font-weight:700;cursor:pointer}}
.tag{{display:inline-block;padding:5px 9px;border-radius:999px;background:#fff2c6;
color:#715700;font-size:13px}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7f5;padding:16px;border-radius:10px}}
.muted{{color:#5d6961;font-size:14px}}a{{color:#146c43}}</style></head><body><main>
<span class="tag">SANDBOX — NO REAL CHARGE</span><h1>{html.escape(title)}</h1>
{body}</main></body></html>"""
    )


def _redact_result(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_result(item)
            for key, item in value.items()
            if key not in SENSITIVE_RESPONSE_KEYS
        }
    if isinstance(value, list):
        return [_redact_result(item) for item in value]
    return value


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    try:
        _config()
        setup = "Sandbox key loaded."
    except RuntimeError as exc:
        setup = html.escape(str(exc))
    return _page(
        "Test Ninja NIN verification",
        f"""<p>{setup}</p><p class="muted">Verify mode returns a match verdict and does not
return the person's registry record. Submitted details are kept only long enough to call Ninja.</p>
<form method="post" action="/verify">
<label for="nin">NIN</label><input id="nin" name="nin" inputmode="numeric" pattern="[0-9]{{11}}"
maxlength="11" required value="77777777777">
<label for="first_name">First name</label>
<input id="first_name" name="first_name" required value="James">
<label for="last_name">Last name</label>
<input id="last_name" name="last_name" required value="Bond">
<label for="date_of_birth">Date of birth (optional)</label>
<input id="date_of_birth" name="date_of_birth" type="date" value="1975-01-01">
<button type="submit">Run sandbox verification</button></form>""",
    )


@app.post("/verify", response_class=HTMLResponse)
async def verify_nin(
    nin: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    date_of_birth: str = Form(""),
) -> HTMLResponse:
    nin = nin.strip()
    first_name = first_name.strip()
    last_name = last_name.strip()
    if not re.fullmatch(r"\d{11}", nin):
        raise HTTPException(422, "NIN must contain exactly 11 digits")
    if not first_name or not last_name:
        raise HTTPException(422, "First and last name are required")

    try:
        secret, api_url = _config()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None

    payload: dict[str, str] = {
        "idType": "nin",
        "mode": "verify",
        "idNumber": nin,
        "firstName": first_name,
        "lastName": last_name,
    }
    if date_of_birth:
        payload["dateOfBirth"] = date_of_birth

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{api_url}/api/identity/identify",
                headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach Ninja: {exc.__class__.__name__}") from None

    try:
        result: Any = response.json()
    except ValueError:
        detail = f"Ninja returned HTTP {response.status_code} with invalid JSON"
        raise HTTPException(502, detail) from None
    if response.is_error:
        message = (
            result.get("message", "Ninja rejected the verification")
            if isinstance(result, dict)
            else str(result)
        )
        raise HTTPException(response.status_code, message)

    # Do not echo the submitted NIN or names back into the response page.
    safe_result = _redact_result(result)
    rendered = html.escape(json.dumps(safe_result, indent=2, default=str))
    return _page(
        "Verification result",
        f"<pre>{rendered}</pre><p><a href='/'>Run another sandbox check</a></p>",
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
