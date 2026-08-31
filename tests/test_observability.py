from __future__ import annotations

from app.core import observability


async def test_dashboard_page_is_public_html(client):
    res = await client.get("/observability")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Zent · Observability" in res.text
    assert "fetch(\"metrics\"" in res.text  # self-contained, talks to its own endpoints


async def test_metrics_endpoint_records_traffic(client):
    # generate a couple of tracked requests
    await client.get("/api/properties")
    await client.get("/api/properties/does-not-exist-123", params={})
    await client.post("/api/auth/login", json={"email": "x@y.com", "password": "nope123"})

    res = await client.get("/observability/metrics")
    assert res.status_code == 200
    m = res.json()
    assert m["totalRequests"] >= 3
    assert set(m["latencyMs"]) == {"p50", "p90", "p99", "max", "avg"}
    assert "2xx" in m["statusClasses"]
    assert m["process"]["pid"] > 0
    routes = {r["route"] for r in m["topRoutes"]}
    assert "/api/properties" in routes


async def test_logs_endpoint(client):
    await client.get("/api/properties")
    res = await client.get("/observability/logs")
    assert res.status_code == 200
    body = res.json()
    assert body["recentRequests"]
    assert body["recentRequests"][0]["route"] == "/api/properties"
    assert body["recentRequests"][0]["status"] == 200


async def test_request_id_header_present(client):
    res = await client.get("/api/properties")
    assert res.headers.get("x-request-id")
    assert len(res.headers["x-request-id"]) == 16


async def test_observability_not_counted_in_metrics(client):
    await client.get("/observability/metrics")
    await client.get("/observability/metrics")
    res = await client.get("/observability/metrics")
    routes = {r["route"] for r in res.json()["topRoutes"]}
    assert not any(r.startswith("/observability") for r in routes)


async def test_prometheus_format(client):
    await client.get("/api/properties")
    res = await client.get("/observability/prometheus")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    assert "zent_requests_total" in res.text
    assert 'zent_request_latency_ms{quantile="p99"}' in res.text


async def test_token_gate_when_configured(client, monkeypatch):
    monkeypatch.setattr(observability.settings, "OBSERVABILITY_TOKEN", "s3cr3t")

    assert (await client.get("/observability/metrics")).status_code == 401
    assert (await client.get("/observability")).status_code == 401

    ok = await client.get("/observability/metrics", params={"token": "s3cr3t"})
    assert ok.status_code == 200

    ok_h = await client.get(
        "/observability/metrics", headers={"X-Observability-Token": "s3cr3t"}
    )
    assert ok_h.status_code == 200
