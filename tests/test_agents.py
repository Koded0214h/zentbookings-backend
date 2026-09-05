from __future__ import annotations

from conftest import next_open_slot, sample_property


async def _make_property(client, admin_auth) -> int:
    res = await client.post("/api/properties", json=sample_property(), headers=admin_auth)
    return res.json()["id"]


async def test_assign_and_scope(client, admin_auth, agent_auth):
    pid = await _make_property(client, admin_auth)
    h = agent_auth["headers"]

    assign = await client.post(
        f"/api/admin/properties/{pid}/agents",
        json={"agentId": agent_auth["id"]},
        headers=admin_auth,
    )
    assert assign.status_code == 201
    assert agent_auth["id"] in assign.json()["agentIds"]

    listed = await client.get(f"/api/admin/properties/{pid}/agents", headers=admin_auth)
    assert listed.json()["agentIds"] == [agent_auth["id"]]

    mine = await client.get("/api/agent/properties", headers=h)
    assert [p["id"] for p in mine.json()] == [pid]

    # a tour on that property shows in the agent's scoped view
    d, t = next_open_slot()
    await client.post(
        "/api/tours",
        json={
            "propertyId": pid, "visitorName": "G", "visitorEmail": "g@example.com",
            "visitorPhone": "+2348000000000", "scheduledDate": d, "scheduledTime": t,
        },
    )
    at = await client.get("/api/agent/tours", headers=h)
    assert at.json()["total"] == 1
    assert at.json()["tours"][0]["leadStatus"] == "NEW"

    unassign = await client.delete(
        f"/api/admin/properties/{pid}/agents/{agent_auth['id']}", headers=admin_auth
    )
    assert unassign.status_code == 204
    assert (await client.get("/api/agent/properties", headers=h)).json() == []


async def test_assign_rejects_non_staff(client, admin_auth, registered_user):
    pid = await _make_property(client, admin_auth)
    res = await client.post(
        f"/api/admin/properties/{pid}/agents",
        json={"agentId": registered_user["body"]["user"]["id"]},
        headers=admin_auth,
    )
    assert res.status_code == 422


async def test_agent_profile_and_public_listing(client, admin_auth, agent_auth):
    h = agent_auth["headers"]

    empty = await client.get("/api/staff/me/profile", headers=h)
    assert empty.status_code == 200
    assert empty.json()["published"] is False

    # not listed publicly while unpublished
    assert (await client.get("/api/agents")).json()["agents"] == []
    assert (await client.get(f"/api/agents/{agent_auth['id']}")).status_code == 404

    upd = await client.put(
        "/api/staff/me/profile",
        json={
            "title": "Senior Advisor",
            "bio": "15 years across Ikoyi and VI.",
            "linkedinUrl": "https://linkedin.com/in/ada",
            "published": True,
        },
        headers=h,
    )
    assert upd.status_code == 200
    assert upd.json()["title"] == "Senior Advisor"

    pub = await client.get("/api/agents")
    assert [a["id"] for a in pub.json()["agents"]] == [agent_auth["id"]]
    assert pub.json()["agents"][0]["fullName"] == "Ada Agent"

    one = await client.get(f"/api/agents/{agent_auth['id']}")
    assert one.status_code == 200
    assert one.json()["title"] == "Senior Advisor"


async def test_patch_tour_lead_status_and_reschedule(
    client, admin_auth, agent_auth, email_sender
):
    pid = await _make_property(client, admin_auth)
    d, t = next_open_slot(days_ahead=4)
    made = await client.post(
        "/api/tours",
        json={
            "propertyId": pid, "visitorName": "G", "visitorEmail": "g@example.com",
            "visitorPhone": "+2348000000000", "scheduledDate": d, "scheduledTime": t,
        },
    )
    tid = made.json()["id"]
    h = agent_auth["headers"]

    lead = await client.patch(
        f"/api/tours/{tid}", json={"leadStatus": "NEGOTIATING"}, headers=h
    )
    assert lead.status_code == 200
    assert lead.json()["leadStatus"] == "NEGOTIATING"

    # reschedule to a different slot same day -> dedicated "rescheduled" email
    other = "14:00" if t != "14:00" else "15:00"
    resc = await client.patch(
        f"/api/tours/{tid}",
        json={"scheduledDate": d, "scheduledTime": other},
        headers=h,
    )
    assert resc.status_code == 200
    assert "rescheduled" in email_sender.sent[-1]["subject"].lower()

    # one field of a reschedule pair -> 422
    bad = await client.patch(f"/api/tours/{tid}", json={"scheduledTime": "16:00"}, headers=h)
    assert bad.status_code == 422


async def test_admin_can_edit_another_agents_profile(client, admin_auth, agent_auth):
    res = await client.put(
        f"/api/admin/users/{agent_auth['id']}/profile",
        json={"title": "Lead Advisor", "published": True},
        headers=admin_auth,
    )
    assert res.status_code == 200
    assert res.json()["title"] == "Lead Advisor"

    got = await client.get(
        f"/api/admin/users/{agent_auth['id']}/profile", headers=admin_auth
    )
    assert got.json()["title"] == "Lead Advisor"

    # and it shows on the public directory
    pub = await client.get("/api/agents")
    assert agent_auth["id"] in {a["id"] for a in pub.json()["agents"]}


async def test_non_staff_cannot_patch_tour(client, admin_auth, registered_user):
    pid = await _make_property(client, admin_auth)
    d, t = next_open_slot()
    made = await client.post(
        "/api/tours",
        json={
            "propertyId": pid, "visitorName": "G", "visitorEmail": "g@example.com",
            "visitorPhone": "+2348000000000", "scheduledDate": d, "scheduledTime": t,
        },
    )
    auth = {"Authorization": f"Bearer {registered_user['body']['token']}"}
    res = await client.patch(
        f"/api/tours/{made.json()['id']}", json={"leadStatus": "LOST"}, headers=auth
    )
    assert res.status_code == 403
