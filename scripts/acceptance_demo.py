"""Reproduce the V1 acceptance demo against a fresh, temporary database."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from leados.api import app
from leados.knowledge import knowledge
from leados.storage.factory import get_db
from leados.storage.mock import MockStorageProvider


def demo():
    with TemporaryDirectory(prefix="leados-acceptance-") as directory:
        db = MockStorageProvider(Path(directory) / "acceptance.json")
        with db.transaction():
            knowledge.seed(db)

        async def dependency():
            with db.transaction(refresh=True):
                yield db

        app.dependency_overrides[get_db] = dependency
        try:
            client = TestClient(app)
            first = client.post("/pipeline/run", json={}).json()
            rows = client.get("/opportunities").json()
            examples = []
            for vid in knowledge.verticals:
                primary_signals = [
                    s for s in knowledge.signals.values() if s.vertical_ids[0] == vid
                ]
                triggers = {s.description for s in primary_signals}
                lead = next(
                    o
                    for o in rows
                    if o["vertical_id"] == vid
                    and o["audit_status"] == "VERIFIED"
                    and o["trigger"] in triggers
                )
                examples.append(
                    {
                        key: lead[key]
                        for key in [
                            "company",
                            "sector",
                            "vertical_id",
                            "vertical_name",
                            "trigger",
                            "trigger_date",
                            "novation_service",
                            "decision_maker_roles",
                            "score",
                            "score_band",
                            "score_components",
                            "audit_status",
                            "human_status",
                        ]
                    }
                )
            atlas = next(
                o
                for o in rows
                if o["company"] == "Atlas AI Systems"
                and o["vertical_id"] == "ai_governance"
            )
            oid = atlas["id"]
            review = client.post(
                f"/opportunities/{oid}/approve",
                json={
                    "reviewer": "Acceptance demo",
                    "notes": "Verified synthetic fixture",
                },
            )
            assert review.status_code == 200
            feedback = client.post(
                f"/opportunities/{oid}/feedback",
                json={
                    "status": "Meeting",
                    "buyer_role": "HR Head",
                    "notes": "Synthetic acceptance example; no actual contact",
                },
            )
            assert feedback.status_code == 200
            send = client.post(f"/opportunities/{oid}/send")
            assert send.status_code == 403
            second = client.post("/pipeline/run", json={}).json()
            assert second["metrics"]["opportunities_created"] == 0
            assert client.get(f"/opportunities/{oid}").json()["score"] == atlas["score"]
            metrics = client.get("/dashboard/metrics").json()
            return {
                "synthetic": True,
                "first_run": first["metrics"],
                "repeat_run": second["metrics"],
                "examples": examples,
                "review": "APPROVED",
                "feedback": "Meeting",
                "send_denied": send.json()["detail"]["code"],
                "metrics": metrics,
            }
        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    result = demo()
    output = Path(__file__).resolve().parents[1] / "docs/mock_demo.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        f"Acceptance passed: {len(result['examples'])} verticals, {result['metrics']['companies']} companies, "
        f"{result['metrics']['opportunities']} opportunities; repeat creates zero; email denied."
    )
