"""Local-only helper routes (mounted only when PROD is false)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.core.config import settings

router = APIRouter(tags=["dev"])

_LANDING = """<!doctype html>
<html><head><meta charset="utf-8"><title>Zent OAuth — dev landing</title>
<style>
  body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:640px;margin:48px auto;padding:0 20px;color:#111}}
  h1{{font-size:20px}} code,pre{{background:#f4f4f5;border-radius:6px}}
  pre{{padding:14px;overflow:auto}} .ok{{color:#0a7d33}} .err{{color:#c1121f}}
  button{{font-size:14px;padding:8px 14px;border-radius:8px;border:1px solid #ccc;background:#fff;cursor:pointer}}
  a.btn{{display:inline-block;margin-top:8px}}
</style></head><body>
<h1>Zent OAuth — dev landing</h1>
<p>This page stands in for the frontend. The backend redirected here after the
provider callback, with a <code>token</code> (or <code>error</code>) in the URL.</p>
<div id="status">Reading URL…</div>
<h3>Access token</h3><pre id="token">—</pre>
<h3>GET /api/auth/me</h3><pre id="me">—</pre>
<p>
  <a class="btn" href="{start_google}">↻ Start Google sign-in again</a>
</p>
<script>
  const q = new URLSearchParams(location.search);
  const token = q.get('token'), error = q.get('error');
  const $ = id => document.getElementById(id);
  if (error) {{
    $('status').innerHTML = '<span class="err">OAuth error: ' + error + '</span>';
  }} else if (token) {{
    $('status').innerHTML = '<span class="ok">Signed in. Token received.</span>';
    $('token').textContent = token;
    fetch('{api}/auth/me', {{ headers: {{ Authorization: 'Bearer ' + token }} }})
      .then(r => r.json()).then(j => $('me').textContent = JSON.stringify(j, null, 2))
      .catch(e => $('me').textContent = String(e));
  }} else {{
    $('status').textContent = 'No token or error in the URL. Click the link below to begin.';
  }}
</script>
</body></html>
"""


@router.get("/dev/oauth-landing", response_class=HTMLResponse)
async def oauth_landing() -> str:
    start_google = (
        f"{settings.API_PREFIX}/auth/google"
        f"?redirect_uri=http://localhost:8000/dev/oauth-landing"
    )
    return _LANDING.format(start_google=start_google, api=settings.API_PREFIX)
