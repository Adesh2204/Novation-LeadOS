# Novation LeadOS production repair — 9 October 2026

Repairs and automated validation are complete. The capped actual acceptance retrieved 10 public sources and saved them to the dashboard and Google Sheets. **NO VERIFIED QUALIFYING OPPORTUNITY FOUND.** Two selected sources require further research, eight remain visible at the company ceiling. No buyer opportunity was manufactured.

The actual acceptance used **2 Exa search requests and 2 Firecrawl single-page requests**, researching two companies. The repeat used **0 new provider requests**, two search-cache hits and two crawl-cache hits, including one cached access-restriction response. Known monetary billing and Firecrawl billed credits are **unavailable**; request counts are not a dollar-cost receipt.

## Proven defects and targeted changes

| Issue / root cause | File and function | Change | Verification |
| --- | --- | --- | --- |
| Zero searches with nonzero results conflated cached evidence and new work. Older duplicate totals added encounters twice across wrapper and pipeline. | `services/live_discovery.py`: `run`; `providers/future/exa.py`: `search`; `pipeline.py`: `_stage` | Explicit actual SDK requests, cache hits and distinct URL/content/company/signal/opportunity counters; retained historical metrics. | Cached end-to-end fixtures, capped actual run, cache-only repeat. |
| Static topic/hiring groups dominated search; same groups always ran first. | `knowledge/search_queries/catalog.yaml`; `LiveDiscoveryService._select_queries` | Nine demand groups cover every existing signal exactly once; explicit query cursor rotates groups. | Catalog coverage and rotation tests; actual privacy and contracts queries. |
| SDK company events could be joined by name across unrelated URLs; source type and confidence were overstated. | `providers/future/exa.py`: `_format_results_to_documents`, `_source_type` | Exact-URL associations; conservative identity/source confidence; provider score separate from topical screen. | SDK-shaped fixture tests; actual normalization. |
| Installed Exa SDK HTTP search lacked the configured transport timeout. | `providers/future/exa.py`: timed SDK HTTP boundary | Bounded HTTP timeout with the same SDK search shape; no automatic paid retries. | Adapter tests, actual searches completed. |
| Every stored URL skipped research regardless of freshness, incomplete text or previous failure. | `services/live_discovery.py`: `run.enrich` | Inspect freshness and source sufficiency; record each crawl decision. | Fresh/stale/sufficient/low-relevance/no-URL/cache/budget fixtures. |
| Guessed additional paths and keyword-based confidence uplift could waste crawl credits or attach content to the wrong source. | `providers/future/firecrawl.py`: `enrich_candidate`, `_attach_page`, `_sync_scrape` | Exact page first, only explicitly discovered extra URLs; preserve excerpt, full text, canonical URL, title, publication metadata, retrieval timestamp and hash. | SDK dictionary/object normalization, additional-page provenance tests; LIC PDF extracted. |
| A real GeM security-block page arrived with HTTP 200 and was initially mistaken for meaningful content. | `qualification.py`: `access_restricted`; Firecrawl adapter; pipeline resolve | Detect block text independently of HTTP status, keep original Exa evidence, surface `ROBOTS_OR_ACCESS_RESTRICTED`, avoid a cached retry, retain replaced body in content history. | Added actual-response regression fixtures; cache-only repeat correctly reports the blocked source. The first acceptance run is preserved with its original pre-fix metrics. |
| Product sellers, hiring, articles and acquisitions could become buyer leads from topical mentions alone. Procurement bidder boilerplate could be mistaken for selling. | `qualification.py`: `qualify`, `company_name_supported` | Separate topic, organization role, external demand and commercial fit; issuer-aware seller rules; explicit identity, date, deadline, eligibility and ICP gates. | Mandatory false positives, issuer-boilerplate regression, trailing-acronym identity test; SBI/Protean historical checks. |
| Related catalog verticals could create several unsupported opportunities. | `pipeline.py`: detect/route; `engine.py`: signal detection | Route only distinct, documented service scopes for qualified live requirements; retain weak sources/observations for research. | Complete mocked pipeline for each of nine verticals and distinct multi-scope tests. |
| Need, mandate and evidence confidence could overstate uncertain demand. | `engine.py`: scoring/audit; `pipeline.py`: research/score/store | Preserve eight weights (25/20/20/10/10/5/5/5); conservative factors; new score version `1.1.0-commercial-gates` stores inputs, source hashes and qualification version. FACT/ALLEGATION/INFERENCE/thesis stay separate. | Deterministic scores, conservative mandate/need, allegation/date/conflict tests. |
| Better evidence did not fully update existing opportunities or preserve prior evaluations. | `pipeline.py`: resolve, `_reevaluate` | Consolidate sources; version content and evaluations; keep prior score/components/status/inputs and human-review history. Do not duplicate the same event. | Repeated datasets, fresh evidence, old-score reevaluation and review-preservation tests. |
| Fixture records polluted production statistics and Sheets. | `storage/records.py`; `services/provenance.py`; `api.py`; `services/master_view.py` | Explicit LIVE/MOCK/LEGACY_UNKNOWN origins, evidence-based migration, reversible archives; default live-only qualified views and explicit development fixtures. | Actual before/after ID audit; API/master-view tests; browser mode switch. |
| Real unqualified research was invisible or described as a business opportunity. | `services/discovery_results.py`; frontend `DiscoveryResults`, `page.tsx`, detail page | Persist all retrieved outcomes including capped/skipped sources; separate live research from qualified opportunities; show reason, role, method, fit, crawl decision and separate confidence measures. Details use explicit origin and qualification for contact/approval eligibility. | Actual 10-source dashboard, 24 historical/current Sheets research rows; disabled contacts/CRM on SBI detail; browser console clean. |
| Provider calls could continue after an emergency stop. | `providers/control.py`; provider adapters; `services/discovery_jobs.py`; `stop_live_discovery.py` | Cooperative job stop and persistent stop-file checks before actual requests; preserve completed transactions. | Stop/budget fixtures; final stop flag and disabled live configuration verified. |
| SDK-mocked tests could write into the application's persistent provider cache. | `tests/conftest.py`; isolated provider fixtures | Isolate test cache and job directories. Archive one exactly matched Apex SDK fixture cache entry; retain real caches and conservative reservation history. | Full mocked suite cannot contaminate production caches. Exact fixture proof in archive. |

## Architecture after repair

Exa searches grouped commercial requirements and retains exact source evidence. The pipeline resolves the company and screens the source. Firecrawl researches the exact page only when evidence needs it and the budget permits. Commercial qualification distinguishes a buyer requirement from a seller, internal hire, article or uncertain event. Only supported scopes route to the nine existing verticals. Deterministic scoring and evidence audit govern opportunity eligibility; human review remains required before contact/CRM actions. Canonical typed records commit through the existing StorageProvider, then the live master/research projections synchronize to Google Sheets. The dashboard reads committed records and persisted job progress.

Background discovery uses bounded concurrency and a single writer; dashboard reads remain independent. Repeated triggers, cache reuse and idempotent projection retries protect credits and records. A Sheets projection failure can be retried without another search/crawl. n8n keeps the existing endpoint contracts and remains an inactive orchestrator.

The local health endpoint retains the legacy runtime `mode: mock` setting. Explicit live discovery selects the actual Exa/Firecrawl adapters independently, and the production dashboard defaults to `data_mode=LIVE`. Origin comes from recorded source/provider provenance, so the actual acceptance sources remain LIVE despite the local runtime label.

## Data separation and preservation

Fresh backups and classification dry-run preceded reversible archival. Fixture identification used exact stored fixture URL/content proof and recorded provider/source history, not unfamiliar company names or URL existence.

| Record | Archived MOCK | LIVE before acceptance | LIVE after acceptance | LEGACY_UNKNOWN |
| --- | ---: | ---: | ---: | ---: |
| Company | 40 | 17 | 19 | 0 |
| Source publisher | 41 | 17 | 19 | 0 |
| Source document | 41 | 18 | 20 | 0 |
| Company signal observation | 36 | 2 | 6 | 0 |
| Opportunity | 44 | 2 | 2 | 0 |

**No original UUID was deleted.** All 46 original opportunity scores, score versions and human statuses match the backup. All 368 score components, 48 evidence links, 36 drafts, both human reviews and feedback records are unchanged. All 114 signal definitions and nine vertical/71 service definitions are preserved. Vertical/service objects are derived from the repository on each refresh, so their transient `created_at` values differ between exports; their IDs and definitions match. Two historical research-run states gained explicit origin/qualification annotations, with their prior outcomes retained. Historical numerical scores were not silently recomputed.

SBI Card's historical score remains 72, PhonePe's 73, both version 1.0.0 and NEEDS_RESEARCH. Their historical hypotheses remain inspectable but excluded from qualified live views. Protean's product launch is NOT_A_BUYER without separate purchase evidence. Development fixtures remain available explicitly; switching the UI mode does not write mock rows to production Sheets.

The final workbook validates all schemas and references, no pending write/outbox, zero validation errors. `LEADOS_MASTER_VIEW`: **0 rows**, matching zero verified qualifying live opportunities. `LEADOS_DISCOVERY_RESULTS`: **24 LIVE rows** across historical and both acceptance runs; the latest dashboard shows all 10 latest results. No unowned columns/tabs existed in the actual snapshot; mocked preservation tests cover them. Workbook was never reset.

### Canonical inventory

| Entity | Before | After |
| --- | ---: | ---: |
| Vertical | 9 | 9 |
| Service | 71 | 71 |
| Company | 57 | 59 |
| CompanyAlias | 57 | 59 |
| Source | 58 | 60 |
| SourceDocument | 59 | 61 |
| Signal | 114 | 114 |
| CompanySignal | 38 | 42 |
| Opportunity | 46 | 46 |
| OpportunityEvidence | 48 | 48 |
| ScoreComponent | 368 | 368 |
| DecisionMakerRole | 182 | 182 |
| OutreachDraft | 36 | 36 |
| HumanReview | 2 | 2 |
| HumanReviewTask | 35 | 35 |
| FeedbackEvent | 0 | 0 |
| Suppression | 0 | 0 |
| ContactEvent | 0 | 0 |
| ProviderRun | 25 | 29 |
| AuditLog | 128 | 151 |
| SystemConfig | 7 | 7 |

## Actual live research and usage

The Exa groups were `privacy_demand` and `clm_demand`, five results each; no pagination. Two selected companies were NABARD and LIC. Firecrawl fetched their exact returned URLs. LIC supplied meaningful PDF text with title, canonical/source URL, hash and retrieval time. GeM supplied an access-block body; this is an external source restriction, not verified tender evidence. Publication metadata and current closing/eligibility/sector verification were insufficient to promote either candidate.

| Run | Actual Exa | Actual Firecrawl | Search cache | Crawl cache | New/updated opportunities | Sheets acknowledgement |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Initial capped acceptance | 2 | 2 | 0 | 0 | 0 / 0 | Saved |
| Same dataset, cache only | 0 | 0 | 2 | 2 | 0 / 0 | Saved |
| Total actual requests | **2** | **2** | | | | |

The repeat correctly has **PARTIAL** status: one cached security restriction, two NEEDS_RESEARCH candidates, zero rejected selected candidates, eight explicitly capped sources, no new company/opportunity duplicates. Its six duplicate encounters are two existing companies, two URLs and two company signals; one source-content history was repaired. The first run had one TOPIC_MATCH_ONLY and one NEEDS_RESEARCH outcome before the security-body correction; its original history remains preserved.

Pipeline/provider processing: initial **20.985 s**, cached repeat **0.495 s**. Full job time including workbook loading/commit/projections: **29.939 s** and **9.028 s** respectively. The dashboard displays full job time. The small sample does not establish latency at arbitrary volume. Sheets latency dominates the cached run; batch writes, limits, caching and bounded work reduce avoidable overhead.

Local daily usage is a **reservation counter**, containing early SDK-mocked test reservations; it is not billing. The durable acceptance ledger and actual adapter counters independently agree on two real calls per provider. No monetary zero-spend claim is made. No OpenAI research/embedding, contact lookup, CRM write or email send occurred in this acceptance because no candidate reached the qualified research gate. Existing credentials were retained unchanged and never printed.

| Candidate / source | Verified source link | Final outcome / crawl | Reason and preliminary assessment |
| --- | --- | --- | --- |
| NABARD | [REQUEST FOR PROPOSAL (RFP) FOR Selection of a Consultant for Implementation of the Digital Personal Data Protection Act, 2023 and development of a Privacy Framework including DPIA](https://fulfilment.gem.gov.in/contract/slafds?fileDownloadPath=SLA_UPLOAD_PATH%2F2026%2FFeb%2FGEM_2026_B_7295746%2FCLM0012%2FRFP_224f86bd-8618-44eb-b7441772100015780_buyer104.nbar.mh.pdf) | NEEDS_RESEARCH / ROBOTS_OR_ACCESS_RESTRICTED | Source is unavailable, closed or access restricted; demand cannot be verified. |
| Life Insurance Corporation of India (LIC) | [Request for Proposal (RFP) / Tender Document](https://licindia.in/documents/20121/1643572/Request+for+Proposal%28RFP%29+Document.pdf/75f24279-6047-8445-578d-d1b9450f44f5?t=1768394930367) | NEEDS_RESEARCH / CACHE_REUSED | A procurement topic is mentioned; the organization issuing a current requirement needs verification. |
| SBI Payment Services Private Limited (SBI Payments) | [REF: SBI PAYMENTS/VM/2026-27/06 DATED 06.05.2026](https://www.sbipayments.com/pdf/2026-2027/DPDP-Act-Consultant-RFP-Final-6-5-2026.pdf) | SKIPPED_COMPANY_LIMIT / BUDGET_EXHAUSTED | The configured company ceiling was reached; retained for a later run. Preliminary evidence check: Buyer identity must be supported by the source text; Source reliability needs verification; Publication timing is unknown, future or stale; Procurement closing date requires verification; Company sector or country needs ICP verification |
| Indian Bank | [IndianBankClassification: Internal](https://fulfilment.gem.gov.in/contract/slafds?fileDownloadPath=SLA_UPLOAD_PATH%2F2026%2FJul%2FGEM_2026_B_7823086%2FCLM0010%2FIBDPDPRFP_5ae86435-480a-43f5-80461784813053030_FGMO_BHUB_PAO3.pdf) | SKIPPED_COMPANY_LIMIT / BUDGET_EXHAUSTED | The configured company ceiling was reached; retained for a later run. Preliminary evidence check: Source reliability needs verification; Publication timing is unknown, future or stale; Procurement closing date requires verification; Company sector or country needs ICP verification |
| Oil India Limited | [OIL INDIA LIMITED](https://fulfilment.gem.gov.in/contract/slafds?fileDownloadPath=SLA_UPLOAD_PATH%2F2026%2FAug%2FGEM_2026_B_7850622%2FCLM0010%2FCORR_1_RES_c7fecbfd-30b4-4797-85cc1787735862926_oil.dul.contract.buycon19.c_p.pdf) | SKIPPED_COMPANY_LIMIT / BUDGET_EXHAUSTED | The configured company ceiling was reached; retained for a later run. Preliminary evidence check: Buyer identity must be supported by the source text; Source reliability needs verification; Publication timing is unknown, future or stale; Procurement closing date requires verification; Bidder eligibility requires verification; Company sector or country needs ICP verification; Adjacent sector requires human ICP fit verification |
| [PDF] RFP 26 | [[PDF] RFP 26-04 Contract Lifecycle Management (CLM ... - IN.gov](https://www.in.gov/inprs/files/rfp-documents/RFP26-04ContractLifecycleManagementCRMSystemResponsestoInquiries.pdf) | SKIPPED_COMPANY_LIMIT / BUDGET_EXHAUSTED | The configured company ceiling was reached; retained for a later run. Preliminary evidence check: A procurement topic is mentioned; the organization issuing a current requirement needs verification. |
| National Skill Development Corporation (NSDC) and NSDC International Limited (NSDCI) | [Tender For Selection Of A Law Firm For Review Stan,  57628269 22-09-2026](https://www.tenderdetail.com/Indian-Tenders/TenderNotice/57628269/9f02d7c0b76ac9e197fc52434773b98f) | SKIPPED_COMPANY_LIMIT / BUDGET_EXHAUSTED | The configured company ceiling was reached; retained for a later run. Preliminary evidence check: Procurement is mentioned; the issuing organization and a suitable Novation service scope require verification. |
| Bank of India | [Request for Proposal for Procurement of Litigation Management Solution (SaaS Model) on Subscription Basis](https://fulfilment.gem.gov.in/contract/slafds?fileDownloadPath=SLA_UPLOAD_PATH%2F2026%2FFeb%2FGEM_2026_B_7231118%2FCLM0010%2FRFPLegal_0dd6790c-e51b-4c0d-9c731770896500934_Chiranjeevi.T.pdf) | SKIPPED_COMPANY_LIMIT / BUDGET_EXHAUSTED | The configured company ceiling was reached; retained for a later run. Preliminary evidence check: Procurement is mentioned; the issuing organization and a suitable Novation service scope require verification. |
| BGSSL | [RFP for Appointment of Labour Law Consultant for Statutory Compliance and Support Services for BGSSL](https://fulfilment.gem.gov.in/contract/slafds?fileDownloadPath=SLA_UPLOAD_PATH%2F2026%2FAug%2FGEM_2026_B_7931311%2FCLM0010%2FRFP_ce815ea2-6707-40d3-b9811787204076076_Manager.Procurement%40BGSSL.pdf) | SKIPPED_COMPANY_LIMIT / BUDGET_EXHAUSTED | The configured company ceiling was reached; retained for a later run. Preliminary evidence check: Procurement is mentioned; the issuing organization and a suitable Novation service scope require verification. |
| CSC e-Governance Services India Ltd (CSC SPV) | [Selection of Consultant for Readiness, Roadmap & Implementation of the Data Privacy Governance Framework to comply with Digital Personal Data Protection Act 2023, Rule 2025](https://fulfilment.gem.gov.in/contract/slafds?fileDownloadPath=SLA_UPLOAD_PATH%2F2026%2FAug%2FGEM_2026_B_7869758%2FCLM0012%2FDPDP_7b598243-10f9-495d-98231785754921085_kapil.rathore%40nic.in.pdf) | SKIPPED_COMPANY_LIMIT / BUDGET_EXHAUSTED | The configured company ceiling was reached; retained for a later run. Preliminary evidence check: TOPIC_MATCH_ONLY: no concrete buyer requirement is supported by this source. |

The IN.gov `[PDF] RFP 26` string is an unresolved search-title fallback, not a verified organization. Capped rows' preliminary assessments are not completed evidence audits. They remain visible as skipped; none were silently promoted. Further coverage would require a separately budgeted search group, authoritative current tender/requirement pages, explicit closing dates and eligibility, verified buyer identity/sector and a service scope Novation can deliver. The current task's two-company research cap is exhausted; no further paid requests were attempted.

## Testing and independent verification

Previous backend coverage: **341 passing cases** plus two opt-in live tests. Added coverage: **65 cases** (parameterized cases count individually). Final `make validate`: **406 passed, 2 skipped, 0 failed**, backend run 90.04 s. Ruff and format checks pass (100 Python files), mypy passes (68 source files), ESLint and TypeScript pass, Next.js production build succeeds, both n8n JSON workflows validate with 13 connected nodes and inactive state. Opt-in unrestricted provider tests remain skipped; the capped script provides the actual acceptance instead.

Intermediate failures were corrected before completion: four positive contact/CRM fixtures now explicitly model live external demand under mocked adapters; mypy optional SDK metadata/enum typing; frontend qualification reason typing; issuer-sensitive procurement boilerplate. No test expectation permits a synthetic lead to call a live contact vendor.

Automated coverage includes all nine verticals, 114-signal coverage, commercial false positives, qualified public requirements, routing, conservative deterministic score inputs, assertions, aliases, URL/content/event deduplication, evidence consolidation, history preservation, source sufficiency, provider failures, access restrictions, per-run/daily budgets, cache-only repeats, cooperative stop, API filters, Sheets post-commit/retry behavior, additive schemas and 2,000-row projection chunking/idempotence.

Actual verification: backend health passes; Exa returns normalized sources; Firecrawl extracts one meaningful PDF and one reported block; Google Sheets validates and matches projections; browser shows 19 LIVE companies, zero qualified opportunities, ten latest source outcomes and saved-to-Sheets status. Explicit development mode shows the 40 companies/44 archived fixture opportunities. SBI historical detail shows qualification uncertainty with contact and CRM buttons disabled. Desktop width 1280 and mobile width 390 have no document overflow; Inter is loaded locally, console has no warnings/errors. Discovery estimates correctly enforce the configured page ceilings. Screenshots are in `docs/screenshots/production-repair-desktop.png` and `production-repair-mobile.png`.

## Commands

Run from `/Users/adesh/Novation-LeadOS`. Existing services are already running; `make dev` safely reuses occupied application ports.

```sh
# Backend / frontend, in separate terminals
make backend
make frontend
# Or the combined local launcher
make dev

# Full automated validation / backend tests
make validate
make test

# Offline estimate: no provider requests
.venv/bin/python scripts/safe_live_acceptance.py

# Safe actual acceptance: persistent 2-search / 3-page ledger, 2 companies
.venv/bin/python scripts/safe_live_acceptance.py --execute
# Repeat the same sample while forbidding every new provider reservation
.venv/bin/python scripts/safe_live_acceptance.py --execute --repeat-cached

# Read exact actual acceptance usage
cat data/archives/production-repair-20261009/acceptance-usage.json
# Read configured health / local reservation counters, not vendor billing
curl --fail http://localhost:8000/providers/exa/health
curl --fail http://localhost:8000/providers/firecrawl/health

# Validate actual Sheets; retry a pending projection without research
.venv/bin/python scripts/validate_google_sheets.py
curl --fail -X POST http://localhost:8000/storage/master-view/sync

# Classification dry run; no deletion
.venv/bin/python scripts/archive_mock_records.py

# Emergency stop
.venv/bin/python scripts/stop_live_discovery.py
```

A search-preview discovery can be requested through the existing endpoint, but **it can consume Exa credits** even though crawling, AI and business-record creation stay off:

```sh
curl --fail -X POST http://localhost:8000/pipeline/discover/live/jobs   -H 'Content-Type: application/json'   --data '{"dry_run":true,"max_queries":1,"max_companies":2,"query_offset":0}'
```

Final state is deliberately stopped: `LIVE_DISCOVERY_ENABLED=false`, persistent `data/discovery-jobs/STOP_LIVE_DISCOVERY`, `ENABLE_EMAIL_SEND=false`, independent SMTP transport stop unchanged. Execution commands remain blocked until deliberately rearmed for a new authorized window; **do not clear the acceptance ledger or run unrestricted live-provider tests** to repeat this task. Settings-only n8n encryption/cookie keys do not constitute a running n8n connection. Scheduling stays inactive.

## Evidence and recovery artifacts

- `docs/LIVE_PIPELINE_ROOT_CAUSE_AUDIT.md`: original trace and exact historical duplicate reconstruction.
- `data/archives/production-repair-20261009/before.json`, `classification-dry-run.json`, `before-apply/`, `after-apply/`, `final-export/`: canonical backups, proposed UUIDs, archive proof and final data.
- `workbook-before-presentation-repair.json`, `workbook-final.json`: full workbook metadata and cells.
- `preservation-audit.json`, `unowned-cells-audit.json`, `final-sheets-validation.json`, `final-runtime-sheets-sync.json`, `final-dashboard-state.json`, `final-backend-health.json`: independent final checks.
- `acceptance-usage.json`: persistent caps, actual summaries and both saved jobs; no secret values.
- `automated-validation.log`: final complete validation output.
- `/private/tmp/leados-production-repair-20261009/source/`: original code/configuration backup; separate protected settings backup retains credentials.

Archives retain all business records and their stable IDs. Reversing a mock archive means changing the logical archive flags and using explicit development mode; it does not require deleting/recreating Sheets or restoring mock rows to live presentation.

## Completion status and practical limits

| Status | Work |
| --- | --- |
| DONE | Root-cause audit, backups, reversible separation, grouped search/crawl repairs, commercial gates, nine-vertical routing, versioned evaluations, live projections, dashboard controls/fonts and safety stops. |
| TESTED | Full mocked suite/build/lint/types/workflows; capped actual Exa/Firecrawl; actual Sheets; cache repeat; ID/score/review preservation; desktop/mobile UI; no live mocks or email sends. |
| NOT YET TESTED | A genuinely qualified real buyer progressing through scoring into the dashboard/master view; live breadth across all nine groups; high-volume real vendor/workbook latency; actual contact verification/CRM write for a newly qualified lead. These paths have mocked coverage, not a new real-world success claim. |
| BLOCKED | NABARD's exact GeM page is security restricted. Current procurement dates, eligibility and commercial delivery fit remain unverified in this sample. No attempt was made to bypass the restriction. |

A zero-row master view is the correct verified result for this sample. Email and n8n execution remain intentionally inactive. The application cannot guarantee flawless latency for unlimited companies or success from external providers; it now bounds work, preserves partial progress and explains those limits.

## Source files changed against the pre-repair backup

- `backend/leados/api.py`
- `backend/leados/engine.py`
- `backend/leados/pipeline.py`
- `backend/leados/providers/control.py`
- `backend/leados/providers/future/exa.py`
- `backend/leados/providers/future/firecrawl.py`
- `backend/leados/providers/future/openai.py`
- `backend/leados/providers/models.py`
- `backend/leados/qualification.py`
- `backend/leados/schemas.py`
- `backend/leados/services/contact_enrichment.py`
- `backend/leados/services/discovery_jobs.py`
- `backend/leados/services/discovery_results.py`
- `backend/leados/services/live_discovery.py`
- `backend/leados/services/master_view.py`
- `backend/leados/services/provenance.py`
- `backend/leados/storage/records.py`
- `backend/leados/storage/workbook.py`
- `backend/tests/conftest.py`
- `backend/tests/test_api.py`
- `backend/tests/test_connected_pipeline.py`
- `backend/tests/test_discovery_jobs.py`
- `backend/tests/test_exa.py`
- `backend/tests/test_master_view.py`
- `backend/tests/test_production_repair.py`
- `frontend/app/globals.css`
- `frontend/app/opportunities/[id]/page.tsx`
- `frontend/app/page.tsx`
- `frontend/components/DiscoveryResults.tsx`
- `frontend/lib/api.ts`
- `knowledge/search_queries/catalog.yaml`
- `scripts/archive_mock_records.py`
- `scripts/full_workbook_backup.py`
- `scripts/repair_live_history.py`
- `scripts/safe_live_acceptance.py`
- `scripts/stop_live_discovery.py`
