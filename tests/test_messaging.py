from __future__ import annotations

from conftest import _register, sample_property


def _body(pid: int, **over) -> dict:
    body = {
        "propertyId": pid,
        "guestName": "Guest Visitor",
        "guestEmail": "guest@example.com",
        "guestPhone": "+2348010000000",
        "message": "Hi, is this still available?",
    }
    body.update(over)
    return body


async def test_create_conversation_guest_success(client, booking_property):
    res = await client.post("/api/conversations", json=_body(booking_property))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["guestToken"]
    assert body["conversation"]["status"] == "OPEN"
    assert body["message"]["body"] == "Hi, is this still available?"
    assert body["message"]["senderRole"] == "guest"


async def test_create_conversation_missing_fields_is_422(client, booking_property):
    res = await client.post(
        "/api/conversations",
        json={"propertyId": booking_property, "message": "hello"},
    )
    assert res.status_code == 422


async def test_create_conversation_unknown_property_is_404(client):
    res = await client.post("/api/conversations", json=_body(999999))
    assert res.status_code == 404


async def test_create_conversation_reuses_open_thread(client, booking_property):
    first = await client.post("/api/conversations", json=_body(booking_property))
    second = await client.post(
        "/api/conversations", json=_body(booking_property, message="follow up question")
    )
    assert first.json()["conversation"]["id"] == second.json()["conversation"]["id"]

    cid = first.json()["conversation"]["id"]
    token = first.json()["guestToken"]
    history = await client.get(f"/api/conversations/{cid}/messages?guestToken={token}")
    assert history.json()["total"] == 2


async def test_guest_can_fetch_and_reply_with_token(client, booking_property):
    created = await client.post("/api/conversations", json=_body(booking_property))
    cid = created.json()["conversation"]["id"]
    token = created.json()["guestToken"]

    reply = await client.post(
        f"/api/conversations/{cid}/messages", json={"body": "thanks!", "guestToken": token}
    )
    assert reply.status_code == 201
    assert reply.json()["senderRole"] == "guest"


async def test_guest_wrong_token_is_403(client, booking_property):
    created = await client.post("/api/conversations", json=_body(booking_property))
    cid = created.json()["conversation"]["id"]

    bad = await client.get(f"/api/conversations/{cid}/messages?guestToken=not-the-real-token")
    assert bad.status_code == 403

    bad_post = await client.post(
        f"/api/conversations/{cid}/messages", json={"body": "hi", "guestToken": "nope"}
    )
    assert bad_post.status_code == 403


async def test_message_moderation_flags_phone_number(client, booking_property):
    created = await client.post(
        "/api/conversations",
        json=_body(booking_property, message="call me on 08012345678 instead"),
    )
    assert created.json()["message"]["flagged"] is True
    assert created.json()["message"]["flagReason"]


async def test_message_without_contact_info_is_not_flagged(client, booking_property):
    created = await client.post("/api/conversations", json=_body(booking_property))
    assert created.json()["message"]["flagged"] is False


async def test_authenticated_user_owns_their_conversation(
    client, booking_property, registered_user, email_sender
):
    token = registered_user["body"]["token"]
    created = await client.post(
        "/api/conversations",
        json={"propertyId": booking_property, "message": "hi there"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 201
    assert created.json()["guestToken"] is None  # authed users don't need one
    cid = created.json()["conversation"]["id"]

    owner_view = await client.get(
        f"/api/conversations/{cid}", headers={"Authorization": f"Bearer {token}"}
    )
    assert owner_view.status_code == 200

    stranger = await _register(client, email_sender, "stranger@example.com", "S", "T")
    stranger_view = await client.get(
        f"/api/conversations/{cid}", headers={"Authorization": f"Bearer {stranger['token']}"}
    )
    assert stranger_view.status_code == 403


async def test_staff_scoping_by_assigned_property(client, admin_auth, agent_auth):
    pid_a = (
        await client.post("/api/properties", json=sample_property(), headers=admin_auth)
    ).json()["id"]
    pid_b = (
        await client.post(
            "/api/properties", json=sample_property(title="Other Place"), headers=admin_auth
        )
    ).json()["id"]

    await client.post(
        f"/api/admin/properties/{pid_a}/agents",
        json={"agentId": agent_auth["id"]},
        headers=admin_auth,
    )

    await client.post("/api/conversations", json=_body(pid_a))
    await client.post("/api/conversations", json=_body(pid_b, guestEmail="other@example.com"))

    agent_view = await client.get("/api/conversations", headers=agent_auth["headers"])
    assert agent_view.json()["total"] == 1
    assert agent_view.json()["conversations"][0]["propertyId"] == pid_a

    admin_view = await client.get("/api/conversations", headers=admin_auth)
    assert admin_view.json()["total"] == 2
