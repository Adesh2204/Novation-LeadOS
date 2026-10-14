from leados.pipeline import STAGES


def test_complete_api_discovery_review_feedback_and_dashboard(client):
    result = client.post("/pipeline/run", json={})
    assert result.status_code == 200
    assert result.json()["status"] == "PARTIAL"
    assert result.json()["metrics"]["opportunities_created"] == 44
    assert len(client.get("/verticals").json()) == 9
    assert len(client.get("/signals").json()) == 114
    assert client.get("/health").json()["email_send_enabled"] is False
    assert len(client.get("/companies?data_mode=MOCK").json()) == 40
    rows = client.get("/opportunities?data_mode=MOCK").json()
    assert rows[0]["score"] >= rows[-1]["score"]
    assert len(client.get("/dashboard/today?data_mode=MOCK").json()) == len(rows)
    lead = next(o for o in rows if o["audit_status"] == "VERIFIED")
    oid = lead["id"]
    assert lead["evidence"][0]["content_hash"] and lead["draft"]
    assert client.post(f"/opportunities/{oid}/send").status_code == 403
    approve = client.post(
        f"/opportunities/{oid}/approve", json={"reviewer": "Adesh", "notes": "Reviewed fixture"}
    )
    assert approve.status_code == 200 and approve.json()["human_status"] == "APPROVED"
    assert len(approve.json()["reviews"]) == 1
    assert client.post(f"/opportunities/{oid}/send").json()["detail"]["code"] == "email_send_disabled"
    for status, reason in [("Meeting", None), ("Lost", "Wrong Timing")]:
        response = client.post(
            f"/opportunities/{oid}/feedback",
            json={"status": status, "reason": reason, "buyer_role": "General Counsel"},
        )
        assert response.status_code == 200
    detail = client.get(f"/opportunities/{oid}").json()
    assert len(detail["feedback"]) == 2 and detail["score"] == lead["score"]
    assert all(f["score_snapshot"] == lead["score"] for f in detail["feedback"])
    metrics = client.get("/dashboard/metrics?data_mode=MOCK").json()
    assert metrics["companies"] == 40 and metrics["hot"] > 0 and metrics["needs_research"] > 0
    assert client.post("/pipeline/run", json={}).json()["metrics"]["opportunities_created"] == 0
    assert client.get(f"/opportunities/{oid}").json()["human_status"] == "APPROVED"


def test_research_approval_constraints_filters_and_validation(client):
    client.post("/pipeline/run", json={})
    rows = client.get("/opportunities?data_mode=MOCK").json()
    research = next(o for o in rows if o["audit_status"] != "VERIFIED")
    assert (
        client.post(f"/opportunities/{research['id']}/approve", json={"reviewer": "Test"}).status_code == 409
    )
    lead = next(o for o in rows if o["audit_status"] == "VERIFIED")
    oid = lead["id"]
    assert (
        client.post(f"/opportunities/{oid}/reject", json={"reviewer": "Test"}).json()["human_status"]
        == "REJECTED"
    )
    assert (
        client.post(f"/opportunities/{oid}/research", json={"reviewer": "Test"}).json()["human_status"]
        == "NEEDS_RESEARCH"
    )
    assert client.post(f"/opportunities/{oid}/approve", json={"reviewer": ""}).status_code == 422
    assert client.post(f"/opportunities/{oid}/feedback", json={"status": "Made Up"}).status_code == 422
    assert client.get("/opportunities?min_score=101").status_code == 422
    assert client.get("/opportunities/nonexistent").status_code == 404
    filtered = client.get(
        "/opportunities?data_mode=MOCK&vertical=ai_governance&min_score=80&country=India&date_from=2026-10-01"
    ).json()
    assert filtered and all(o["vertical_id"] == "ai_governance" and o["score"] >= 80 for o in filtered)
    assert client.post(f"/companies/{lead['company_id']}/suppression", json={"opted_out": True}).json()[
        "suppressed"
    ]
    assert client.post(f"/opportunities/{oid}/approve", json={"reviewer": "Test"}).status_code == 409

    # Editing the do-not-contact flag must preserve independently recorded opt-outs.
    client.post(f"/companies/{lead['company_id']}/suppression", json={"do_not_contact": False})
    assert client.get(f"/opportunities/{oid}").json()["suppression_flags"]["opted_out"] is True


def test_n8n_http_stages(client):
    run = client.post("/pipeline/start", json={"company": "Atlas AI Systems"}).json()
    rid = run["run_id"]
    assert client.post(f"/pipeline/runs/{rid}/store").status_code == 409
    for stage in STAGES:
        response = client.post(f"/pipeline/runs/{rid}/{stage}")
        assert response.status_code == 200
    assert response.json()["stage"] == "store"
    assert len(response.json()["human_review_ids"]) == 2
    tasks = client.post(f"/pipeline/runs/{rid}/review-tasks/create").json()
    again = client.post(f"/pipeline/runs/{rid}/review-tasks/create").json()
    assert len(tasks["tasks"]) == 2 and tasks == again
