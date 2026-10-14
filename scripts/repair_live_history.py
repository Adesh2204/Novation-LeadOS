"""Append commercial evaluations to live history without changing historical scores/reviews."""

import argparse
import json
from pathlib import Path

from leados.config import settings
from leados.qualification import qualify
from leados.services.master_view_sync import application_storage
from leados.storage.factory import build_storage
from leados.storage.records import (
    AuditLog,
    Company,
    CompanySignal,
    Opportunity,
    ProviderRun,
    SourceDocument,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    storage = build_storage(settings)
    report = []
    with application_storage(storage, refresh=True, force_sync=args.apply):
        companies = {c.id: c for c in storage.list(Company)}
        assessments = {}
        for source in storage.list(SourceDocument):
            if source.record_origin != "LIVE":
                continue
            company = companies[source.company_id]
            q = qualify(
                {
                    **source.model_dump(mode="json"),
                    "company": {
                        "name": company.canonical_name,
                        "sector": company.sector,
                        "country": company.country,
                    },
                }
            )
            assessments[source.id] = q
            report.append(
                {
                    "source_id": source.id,
                    "company": company.canonical_name,
                    "source_url": source.source_url,
                    **q,
                }
            )
        if args.apply:
            for signal in storage.list(CompanySignal):
                if signal.record_origin == "LIVE":
                    values = [
                        assessments[did]
                        for did in signal.evidence_ids
                        if did in assessments
                    ]
                    signal.qualification = next(
                        (q for q in values if q["status"] == "QUALIFIED_SIGNAL"),
                        values[0] if values else {},
                    )
                    for opportunity in storage.list(
                        Opportunity, company_signal_id=signal.id
                    ):
                        opportunity.qualification = signal.qualification
            for run in storage.list(ProviderRun):
                if run.provider != "exa+firecrawl":
                    continue
                results = []
                for old in run.state.get("discovery_results", []):
                    result = dict(old)
                    q = qualify(
                        {
                            "company": {
                                "name": result["company"],
                                "sector": "Unknown",
                                "country": "Unknown",
                            },
                            "snippet": result.get("snippet", ""),
                            "published_date": result.get("published_date"),
                            "company_match": result["company"].casefold()
                            in result.get("snippet", "").casefold(),
                            "confidence": 0.65,
                        }
                    )
                    result.update(
                        record_origin="LIVE", source_origin="LIVE", qualification=q
                    )
                    # Preserve the original outcome separately; never fabricate missing crawl history.
                    result.setdefault("historical_status", old["status"])
                    result.update(
                        status=q["status"],
                        reason=q["reason"],
                        opportunity_ids=[],
                        firecrawl_decision=result.get(
                            "firecrawl_decision", "NEEDS_ADDITIONAL_RESEARCH"
                        ),
                        decision_history_missing="firecrawl_decision" not in old,
                    )
                    results.append(result)
                if results:
                    run.state = {
                        **run.state,
                        "record_origin": "LIVE",
                        "discovery_results": results,
                    }
            storage.add(
                AuditLog(
                    module="commercial_history_audit",
                    action="append_qualification",
                    success=True,
                )
            )
    Path(
        "data/archives/production-repair-20261009/live-history-evaluations.json"
    ).write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "live_sources_evaluated": len(report),
                "applied": args.apply,
                "historical_scores_changed": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
