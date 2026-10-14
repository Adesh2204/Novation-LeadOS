import argparse
import asyncio
import json
from datetime import date

from leados.config import ROOT, settings
from leados.knowledge import knowledge
from leados.pipeline import Pipeline
from leados.services.master_view_sync import application_storage
from leados.storage.factory import build_storage
from leados.storage.records import Company, CompanySignal, DecisionMakerRole, Opportunity, Service


async def main():
    parser = argparse.ArgumentParser(description="LeadOS local mock tools (run from repository root)")
    parser.add_argument("command", choices=["seed", "run", "demo", "validate-workflows"])
    args = parser.parse_args()
    if args.command == "validate-workflows":
        for path in sorted((ROOT / "workflows").glob("*.json")):
            workflow = json.loads(path.read_text())
            assert workflow["active"] is False
            names = {n["name"] for n in workflow["nodes"]}
            assert len(names) == len(workflow["nodes"])
            for origin, connections in workflow["connections"].items():
                assert origin in names
                for outputs in connections["main"]:
                    for edge in outputs:
                        assert edge["node"] in names
            print(f"{path.name}: valid inactive JSON, {len(names)} connected nodes")
        return
    with application_storage(build_storage(settings), refresh=True, force_sync=True) as db:
        if args.command == "seed":
            knowledge.seed(db)
            print(json.dumps({"verticals": len(knowledge.verticals), "signals": len(knowledge.signals)}))
        else:
            result = await Pipeline(db).run()
            print(json.dumps({"run_id": result.id, "status": result.status, "metrics": result.metrics}))
            if result.status == "FAILED":
                raise SystemExit(f"Pipeline failed: {result.error}")
            if args.command == "demo":
                rows = []
                for vid, vertical in knowledge.verticals.items():
                    primary_signals = [
                        s.signal_id for s in knowledge.signals.values() if s.vertical_ids[0] == vid
                    ]
                    candidates = [
                        o
                        for o in db.list(Opportunity, vertical_id=vid)
                        if (cs := db.get(CompanySignal, o.company_signal_id))
                        and cs.signal_key in primary_signals
                    ]
                    candidates.sort(key=lambda o: (o.audit_status != "VERIFIED", -o.score))
                    opportunity = candidates[0] if candidates else None
                    assert opportunity is not None, f"Missing demo for {vid}"
                    company = db.get(Company, opportunity.company_id)
                    assert company is not None
                    service = db.get(Service, opportunity.service_id)
                    assert service is not None
                    rows.append(
                        {
                            "vertical": vertical.name,
                            "company": company.canonical_name,
                            "score": opportunity.score,
                            "band": opportunity.score_band,
                            "audit": opportunity.audit_status,
                            "review": opportunity.human_status,
                            "trigger": opportunity.trigger,
                            "service": service.name,
                            "buyer_roles": [
                                r.role for r in db.list(DecisionMakerRole, opportunity_id=opportunity.id)
                            ],
                        }
                    )
                print(json.dumps({"as_of": str(date.today()), "examples": rows}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
