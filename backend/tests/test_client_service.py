"""End-to-end client MVP tests against isolated migrated PostgreSQL."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import ClientInvitation, ClientProjectLink
from app.db.session import get_sessionmaker

P = "/api/v1/client-service"


def actor(client, email, mode="client"):
    c = TestClient(client.app)
    r = c.post(
        "/api/v1/auth/register",
        json=dict(
            name=email.split("@")[0],
            email=email,
            password="password123",
            job_type="design",
            agree_terms=True,
            preferred_mode=mode,
        ),
    )
    assert r.status_code == 201, r.text
    return c, r.json()["id"]


def post(c, path, data):
    r = c.post(P + path, json=data)
    assert r.status_code in (200, 201), r.text
    return r.json()


def workspace(c, name="Company"):
    return post(c, "/workspaces", {"name": name})["id"]


def team(c, w, target, email, role="member"):
    i = post(c, f"/workspaces/{w}/invitations", dict(email=email, role=role))
    post(target, "/invitations/accept", dict(token=i["token"]))
    return i


def project(c):
    r = c.post(
        "/api/v1/projects",
        json=dict(
            name="Design",
            new_client_name="Customer",
            job_type="design",
            contract_amount="3300000",
            included_revisions=2,
        ),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def connected(client):
    f, fid = actor(client, "freelancer@example.com", "freelancer")
    a, aid = actor(client, "approver@example.com")
    w = workspace(a)
    p = project(f)
    i = post(f, f"/projects/{p}/connection-invitations", dict(email="approver@example.com"))
    post(a, "/invitations/accept", dict(token=i["token"], workspace_id=w))
    return f, fid, a, aid, w, p


def attachment(c, p, kind="deliverable", file=False):
    if file:
        r = c.post(
            f"/api/v1/projects/{p}/attachments/file",
            data={"kind": kind},
            files={"file": ("sample.txt", b"private design contents", "text/plain")},
        )
    else:
        r = c.post(
            f"/api/v1/projects/{p}/attachments/link",
            json={"kind": kind, "title": "Artwork", "url": "https://example.com/art"},
        )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def delivery(c, p, aid, previous=None):
    return post(
        c, f"/projects/{p}/deliveries", dict(title="Artwork", attachment_ids=[aid], delivery_id=previous)
    )


PROFILE = dict(
    headline="Goods designer",
    job_type="design",
    services=["굿즈"],
    scope="3 graphics",
    price="3300000",
    price_type="fixed",
    revisions=2,
    days=20,
    portfolio=[
        dict(
            title="External work",
            description="Brand goods",
            contribution="Graphics only",
            url="https://example.com/work",
            assets_consent=True,
        )
    ],
)


def test_roles_are_preference_not_authority(client):
    f, _, a, _, w, p = connected(client)
    outsider, _ = actor(client, "outsider@example.com")
    assert outsider.get(P + f"/projects/{p}").status_code == 404
    assert outsider.get(P + f"/workspaces/{w}/projects").status_code == 404
    assert a.get(f"/api/v1/projects/{p}").status_code == 404
    assert f.get(f"/api/v1/projects/{p}").status_code == 200
    assert a.get(P + f"/projects/{p}").json()["owner"] is False


def test_admin_and_owner_still_need_project_grant(client):
    f, _, a, _, w, p = connected(client)
    b, bid = actor(client, "admin@example.com")
    team(a, w, b, "admin@example.com", "admin")
    assert b.get(P + f"/workspaces/{w}/projects").json() == []
    assert b.get(P + f"/projects/{p}").status_code == 404
    assert b.get(P + f"/projects/{p}/members").status_code == 404
    post(a, f"/projects/{p}/members", dict(user_id=bid))
    r = b.get(P + f"/projects/{p}").json()
    assert r["contract_amount"] is None and r["can_finance"] is False
    assert r["can_manage"] is True
    assert len(b.get(P + f"/workspaces/{w}/projects").json()) == 1


def test_invites_wrong_recipient_expired_reused_revoked(client):
    a, _ = actor(client, "a@example.com")
    b, _ = actor(client, "b@example.com")
    x, _ = actor(client, "x@example.com")
    w = workspace(a)
    i = post(a, f"/workspaces/{w}/invitations", dict(email="b@example.com"))
    assert x.post(P + "/invitations/accept", json=dict(token=i["token"])).status_code == 404
    post(b, "/invitations/accept", dict(token=i["token"]))
    assert b.post(P + "/invitations/accept", json=dict(token=i["token"])).status_code == 404
    i = post(a, f"/workspaces/{w}/invitations", dict(email="b@example.com"))
    with get_sessionmaker()() as db:
        inv = db.get(ClientInvitation, UUID(i["id"]))
        inv.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert b.post(P + "/invitations/accept", json=dict(token=i["token"])).status_code == 404
    i = post(a, f"/workspaces/{w}/invitations", dict(email="b@example.com"))
    assert a.delete(P + f"/invitations/{i['id']}").status_code == 200
    assert b.post(P + "/invitations/accept", json=dict(token=i["token"])).status_code == 404
    assert "token" not in a.get(P + f"/workspaces/{w}/invitations").json()[0]
    assert (
        a.post(
            P + f"/workspaces/{w}/invitations", json=dict(email="x@example.com", send_email=True)
        ).status_code
        == 409
    )


def test_last_owner_and_role_escalation_blocked(client):
    a, aid = actor(client, "a@example.com")
    b, bid = actor(client, "b@example.com")
    w = workspace(a)
    team(a, w, b, "b@example.com", "admin")
    assert a.delete(P + f"/workspaces/{w}/members/{aid}").status_code == 409
    assert b.patch(P + f"/workspaces/{w}/members/{bid}", json=dict(role="owner")).status_code == 404
    assert b.patch(P + f"/workspaces/{w}/members/{aid}", json=dict(role="member")).status_code == 404
    assert a.patch(P + f"/workspaces/{w}/members/{bid}", json=dict(role="owner")).status_code == 200
    assert a.delete(P + f"/workspaces/{w}/members/{aid}").status_code == 200


def test_files_require_project_grant_and_explicit_submission(client):
    f, _, a, aid, w, p = connected(client)
    hidden = attachment(f, p, file=True)
    evidence = attachment(f, p, kind="evidence", file=True)
    path = P + f"/projects/{p}/attachments/{hidden}/file"
    assert a.get(path).status_code == 404
    assert (
        f.post(P + f"/projects/{p}/deliveries", json=dict(title="Bad", attachment_ids=[evidence])).status_code
        == 404
    )
    delivery(f, p, hidden)
    assert a.get(path).content == b"private design contents"
    assert a.get(P + f"/projects/{p}/attachments/{evidence}/file").status_code == 404
    assert f.delete(f"/api/v1/attachments/{hidden}").status_code == 409
    assert a.delete(P + f"/projects/{p}/members/{aid}").status_code == 200
    assert a.get(path).status_code == 404


def test_workspace_removal_revokes_existing_download(client):
    f, _, a, _, w, p = connected(client)
    b, bid = actor(client, "b@example.com")
    team(a, w, b, "b@example.com")
    post(a, f"/projects/{p}/members", dict(user_id=bid))
    att = attachment(f, p, file=True)
    delivery(f, p, att)
    path = P + f"/projects/{p}/attachments/{att}/file"
    assert b.get(path).status_code == 200
    assert a.delete(P + f"/workspaces/{w}/members/{bid}").status_code == 200
    assert b.get(path).status_code == 404


def test_versioned_review_comments_and_idempotent_decision(client):
    f, _, a, _, w, p = connected(client)
    b, bid = actor(client, "viewer@example.com")
    team(a, w, b, "viewer@example.com", "viewer")
    post(a, f"/projects/{p}/members", dict(user_id=bid))
    att = attachment(f, p)
    v1 = delivery(f, p, att)
    url = P + f"/versions/{v1['id']}/reviews"
    assert b.post(url, json=dict(kind="approved")).status_code == 404
    assert f.post(url, json=dict(kind="approved")).status_code == 403
    post(a, f"/versions/{v1['id']}/reviews", dict(kind="comment", body="Maybe green"))
    assert a.get(P + f"/projects/{p}").json()["revisions"]["used"] == 0
    post(a, f"/versions/{v1['id']}/reviews", dict(kind="changes", body="Consolidated green"))
    post(a, f"/versions/{v1['id']}/reviews", dict(kind="changes", body="Consolidated green"))
    assert a.get(P + f"/projects/{p}").json()["revisions"]["used"] == 1
    v2 = delivery(f, p, att, v1["delivery_id"])
    assert a.post(url, json=dict(kind="approved")).status_code == 409
    data = a.get(P + f"/projects/{p}").json()["deliveries"]
    assert data[0]["state"] == "changes" and data[1]["state"] == "pending"
    post(a, f"/versions/{v2['id']}/reviews", dict(kind="approved"))
    assert (
        a.post(P + f"/versions/{v2['id']}/reviews", json=dict(kind="changes", body="late")).status_code == 409
    )
    assert a.get(P + f"/projects/{p}").json()["revisions"]["used"] == 1


def test_tasks_are_private_until_published(client):
    f, _, a, _, _, p = connected(client)
    t = f.post(f"/api/v1/projects/{p}/tasks", json=dict(title="Internal note", hourly_rate="70000")).json()
    assert a.get(P + f"/projects/{p}").json()["tasks"] == []
    assert f.put(P + f"/projects/{p}/published-tasks", json=dict(task_ids=[t["id"]])).status_code == 200
    task = a.get(P + f"/projects/{p}").json()["tasks"][0]
    assert task["title"] == "Internal note" and "hourly_rate" not in task


def test_marketplace_opt_in_and_separate_publication_consents(client):
    f, _ = actor(client, "f@example.com", "freelancer")
    a, _ = actor(client, "a@example.com")
    assert f.put(P + "/profile", json={**PROFILE, "published": False}).status_code == 200
    assert a.get(P + "/experts").json() == []
    assert f.put(P + "/profile", json={**PROFILE, "published": True}).status_code == 200
    assert len(a.get(P + "/experts?q=굿즈&job=design&budget=3300000").json()) == 1
    assert a.get(P + "/experts?budget=3000000").json() == []
    invalid = {**PROFILE, "portfolio": [{**PROFILE["portfolio"][0], "client_name": "Secret"}]}
    assert f.put(P + "/profile", json=invalid).status_code == 422


def test_inquiry_quote_versions_contract_and_tenant_isolation(client):
    f, fid = actor(client, "f@example.com", "freelancer")
    a, aid = actor(client, "a@example.com")
    x, _ = actor(client, "x@example.com")
    w = workspace(a)
    assert f.put(P + "/profile", json={**PROFILE, "published": True}).status_code == 200
    i = post(
        a,
        f"/workspaces/{w}/inquiries",
        dict(
            freelancer_id=fid,
            title="Goods",
            purpose="Brand",
            scope="Graphics",
            deliverables="3 files",
            budget="3300000",
        ),
    )
    assert f.get(P + "/inquiries").json() == []
    post(a, f"/inquiries/{i['id']}/send", {})
    assert f.get(P + "/inquiries").json()[0]["status"] == "sent"
    assert x.post(P + f"/inquiries/{i['id']}/messages", json=dict(body="attack")).status_code == 404
    post(f, f"/inquiries/{i['id']}/messages", dict(body="Confirm scope"))
    quote = dict(
        amount="3300000",
        vat="excluded",
        scope="Graphics",
        deliverables="3 files",
        exclusions="Print excluded",
        revisions=2,
        due_date="2026-12-18",
        client_due_date="2026-11-30",
        payment="40/30/30",
        rights="Commercial",
        originals="AI included",
    )
    post(f, f"/inquiries/{i['id']}/quotes", quote)
    second = post(f, f"/inquiries/{i['id']}/quotes", {**quote, "amount": "3400000"})
    assert a.post(P + f"/quotes/{second['quotes'][0]['id']}/accept", json={}).status_code == 409
    qid = second["quotes"][1]["id"]
    accepted = post(a, f"/quotes/{qid}/accept", {})
    again = post(a, f"/quotes/{qid}/accept", {})
    assert accepted["project_id"] == again["project_id"]
    p = a.get(P + f"/projects/{accepted['project_id']}").json()
    assert p["contract_amount"] == "3400000"
    assert p["agreement"]["payload"]["amount"] == "3400000"
    assert len(p["tasks"]) == 2
    with get_sessionmaker()() as db:
        assert len(list(db.scalars(select(ClientProjectLink)))) == 1


def test_approval_is_linked_to_invoice_and_latest_version_checked(client):
    from uuid import uuid4

    f, _, a, _, _, p = connected(client)
    att = attachment(f, p)
    v = delivery(f, p, att)
    body = dict(
        project_id=p,
        title="Final invoice",
        due_date="2026-12-31",
        items=[
            dict(
                kind="extra",
                description="Approved delivery",
                unit_price="10000",
                basis_confirmed=True,
                approval_version_id=v["id"],
            )
        ],
    )
    assert f.post("/api/v1/invoices", json=body).status_code == 422
    post(a, f"/versions/{v['id']}/reviews", dict(kind="approved"))
    draft = f.post("/api/v1/invoices", json=body)
    assert draft.status_code == 201, draft.text
    assert draft.json()["items"][0]["approval_version_id"] == v["id"]
    issued = f.post(
        f"/api/v1/invoices/{draft.json()['id']}/issue", json={}, headers={"Idempotency-Key": uuid4().hex}
    )
    assert issued.status_code == 200, issued.text
    evidence = issued.json()["snapshot"]["items"][0]["approval_evidence"]
    assert evidence["version_id"] == v["id"] and evidence["actor"] == "approver"
    next_draft = f.post("/api/v1/invoices", json=body)
    assert next_draft.status_code == 201
    delivery(f, p, att, v["delivery_id"])
    blocked = f.post(
        f"/api/v1/invoices/{next_draft.json()['id']}/issue", json={}, headers={"Idempotency-Key": uuid4().hex}
    )
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "approval_outdated"
    # Issued evidence remains a historical snapshot, despite new deliveries.
    historical = f.get(f"/api/v1/invoices/{draft.json()['id']}").json()
    assert historical["snapshot"]["items"][0]["approval_evidence"] == evidence


def test_concurrent_approval_and_changes_have_one_winner(client):
    from concurrent.futures import ThreadPoolExecutor

    f, _, a, _, _, p = connected(client)
    v = delivery(f, p, attachment(f, p))

    def decide(kind):
        c = TestClient(client.app)
        c.cookies.update(a.cookies)
        return c.post(P + f"/versions/{v['id']}/reviews", json=dict(kind=kind, body="decision")).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(decide, ["approved", "changes"]))
    assert sorted(results) == [200, 409]
    data = a.get(P + f"/projects/{p}").json()
    events = data["deliveries"][0]["events"]
    assert len([e for e in events if e["kind"] in ("approved", "changes")]) == 1
    assert data["revisions"]["used"] <= 1


def test_chat_requires_opposite_acceptance_and_requests_remain_separate(client):
    f, _, a, _, w, p = connected(client)
    request = post(a, f"/projects/{p}/messages", dict(body="Please provide the brand files"))
    assert request["messages"][0]["session_id"] is None
    pending = post(a, f"/projects/{p}/chat-sessions", dict(body="Discuss colours"))
    cid = str(pending["current"]["id"])
    assert pending["current"]["state"] == "pending"
    assert a.post(P + f"/projects/{p}/chat-sessions/{cid}", json=dict(action="accept")).status_code == 409
    assert f.post(P + f"/projects/{p}/messages", json=dict(body="Early", session_id=cid)).status_code == 409
    active = post(f, f"/projects/{p}/chat-sessions/{cid}", dict(action="accept"))
    assert active["current"]["state"] == "active"
    post(f, f"/projects/{p}/messages", dict(body="Hello", session_id=cid))
    both = post(a, f"/projects/{p}/messages", dict(body="Hello designer", session_id=cid))
    assert len(both["messages"]) == 3
    assert len([m for m in both["messages"] if m["session_id"] is None]) == 1
    closed = post(a, f"/projects/{p}/chat-sessions/{cid}", dict(action="close"))
    assert closed["current"] is None
    assert f.post(P + f"/projects/{p}/messages", json=dict(body="Late", session_id=cid)).status_code == 409
    post(f, f"/projects/{p}/messages", dict(body="Follow-up request"))
    assert a.get(P + f"/projects/{p}").json()["revisions"]["used"] == 0
    viewer, vid = actor(client, "chat-viewer@example.com")
    team(a, w, viewer, "chat-viewer@example.com", "viewer")
    post(a, f"/projects/{p}/members", dict(user_id=vid))
    assert viewer.get(P + f"/projects/{p}/conversation").status_code == 200
    assert viewer.post(P + f"/projects/{p}/messages", json=dict(body="Not allowed")).status_code == 404


def test_sse_stops_when_existing_session_or_project_grant_is_revoked(client):
    from app.api.routes.conversations import events

    f, _, a, aid, _, p = connected(client)
    generator = events(UUID(p), UUID(aid), a.cookies.get("fh_session"))
    first = next(generator)
    assert first.startswith("data: ") and '"messages"' in first
    assert a.delete(P + f"/projects/{p}/members/{aid}").status_code == 200
    assert next(generator).startswith("event: access-ended")
    generator.close()
    # a revoked login is rejected even if its user's project grant remains valid
    fresh = events(UUID(p), UUID(aid), "invalid-session-token")
    assert next(fresh).startswith("event: access-ended")
    fresh.close()


def test_freelancer_cannot_assign_company_approval_permissions(client):
    f, _, a, aid, _, p = connected(client)
    assert f.get(P + f"/projects/{p}").json()["can_manage"] is False
    res = f.post(P + f"/projects/{p}/members", json=dict(user_id=aid, approver=True))
    assert res.status_code == 404
    assert a.get(P + f"/projects/{p}").json()["can_manage"] is True
