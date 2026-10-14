# Live pipeline root cause audit — 9 October 2026

Audit performed before production repair. No provider requests were made during this audit.

## Observed state

The running backend reports 57 companies, 46 opportunities, 35 hot opportunities and 25 provider runs. The last saved export (8 October) contains 44 fixture opportunities and two live opportunities. A fresh export will establish the exact migration inventory. SMTP is off; scheduled n8n workflows are inactive. OpenAI research and embeddings are already explicitly configured; no additional model activation is required.

Screenshot run `run_c05e7fa4-3ca6-41ff-87e9-e80cb1204bdf`: 12 Exa results from two cached searches, zero new Exa requests, zero Firecrawl requests, zero opportunities created, aggregate duplicates 37. This is cache reuse and existing-source processing, not proof of new buyer demand. Its technical run predates persistence of per-result research outcomes; retained source documents and pipeline run states are needed to reconstruct candidates. We will not invent missing per-candidate decisions.

## Traced flow and causes

| Layer / function | Current behavior and consequence | Repair |
| --- | --- | --- |
| `LiveDiscoveryService._select_queries` | First topic-oriented groups always selected; hiring and product-launch searches dominate. | Demand-oriented grouped queries covering all nine verticals and all 114 signal IDs; rotate selection explicitly and retain query IDs. |
| `ExaSearchProvider._format_results_to_documents` | Exact excerpt is retained, but every result is labelled primary news; company extraction may associate an event from another URL by name. | Exact-URL event association, conservative source types, preserve search score separately, explicit live provenance. |
| `LiveDiscoveryService.run.enrich` | Any stored URL skips Firecrawl, regardless of text sufficiency, freshness or previous errors; skip reason is absent. | Inspect exact-source sufficiency and freshness. Persist a decision for every result, separate actual requests/cache/skips/failures. |
| `FirecrawlCrawlerProvider.enrich_candidate` | Stage B guesses paths and does not attach successful additional page content to downstream evidence. Keyword early exit increases confidence without a commercial audit. | Exact-source first; only explicitly discovered relevant additional URLs, preserve separate page provenance; no keyword confidence uplift. |
| `pre_screen_candidate` / `detect_signals` | Search/topic relevance is presented as a business signal; role hiring triggers privacy. | Separate relevance, event evidence and commercial demand. Retain rejected research results with reasons. |
| `route_verticals` / pipeline route | All catalog-related verticals receive candidates; India entry can generate several speculative opportunities. | Require distinct documented service problems per vertical. |
| Pipeline research and scoring | Need/mandate can be inferred by mock/LLM research; legacy weights are correct but buying-intent qualification is absent. | Conservative deterministic commercial gates and versioned scoring inputs. Keep historical scores and reviews intact. |
| Pipeline resolve / route | Existing URL text is never refreshed; new evidence adds to CompanySignal but existing opportunity evidence is not consolidated. | Track URL/content/company/signal/opportunity duplicates separately; merge evidence and retain source versions and historical evaluations. |
| Records / API dashboard / master view | No consistent LIVE/MOCK/LEGACY_UNKNOWN classification. All opportunities and company counts enter production metrics. | Evidence-based provenance migration and reversible mock archive; default live-only qualified views, explicit development mode. |
| Discovery results / frontend | Generic “relevant business signal” copy can appear under no qualifying signal; cached requests and retrieved results are easy to conflate. | Honest research outcomes and clear buying-demand rationale, separate metrics and sections. |
| Google Sheets | Canonical typed records are preserved, projections are synced after commit, retry is idempotent. | Preserve this architecture, append owned schema fields safely, live-only presentation projections. |
| Budgets / jobs | Per-run and daily request reservations exist; no cooperative emergency stop. | Keep bounded concurrency; add a stop switch checked before provider calls, retain completed research on stop. |

## Commercial examples

* SBI Card: the cited DPO job post supports internal privacy hiring. It does not establish outsourced advisory procurement. Research outcome must remain NEEDS_RESEARCH with an explicitly unconfirmed service hypothesis.
* Protean: the cited DPDP governance platform announcement supports solution-provider activity. Without independent purchasing evidence it is NOT_A_BUYER / NO_QUALIFYING_BUYER_SIGNAL, regardless of topical relevance.
* PhonePe: retain the actual source and historical evaluation. Re-evaluate commercial qualification conservatively without rewriting its historical numerical score.

No company-name special cases will be added. The same rules apply to sellers, internal hiring, articles, acquisitions and explicit service requests in all nine verticals.

## Preservation and acceptance plan

Before migration: source backup, fresh Google Sheets export and metadata, classification dry run listing every affected UUID, dependency checks, and durable archive snapshot. Mock records remain recoverable with reviews, drafts and evidence; no business records are deleted. Unknown provenance stays quarantined from production views.

Order: data separation → Exa → Firecrawl → qualification → routing → versioned scoring/evidence → Sheets → frontend → mocked tests → capped actual acceptance → final audit. Actual acceptance is capped across the whole repair at two Exa search requests, three Firecrawl page requests and two deeply researched companies. No email delivery, contact lookup or scheduled workflow activation.

Timing depends on external providers and Google Sheets. The repair will reduce avoidable sequential work and measure actual latency; it cannot guarantee constant latency at arbitrary volume.

## Reconstruction of the screenshot's duplicate count

The outer run `run_c05e7fa4-3ca6-41ff-87e9-e80cb1204bdf` retained 12 search results, screened 12, passed 11 and discarded one. Both queries were cache hits; its 545 ms duration covered no new Exa or Firecrawl request. The inner pipeline run `run_9d99c3b2-091e-4f4c-a26f-d39dad035093` counted 26 duplicate encounters: 11 existing companies, 11 existing documents, two existing company signals and two existing opportunities. The wrapper then added 11 existing-source skips, producing the displayed 37. These were encounters at several layers, not 37 distinct rejected companies.

The 11 retained source candidates were SBI Card (DPO hiring), Protean (privacy product launch), PhonePe (two job sources), Arcesium (closed job page), Norstella, Jobgether, Outreach, LeadSquared, Agrim and EY (job/hiring sources). None of these stored excerpts proved an external service purchase requirement. The old run did not persist the raw discarded result or an individual crawl decision for each source. Those historical omissions remain explicitly labelled; new runs retain all retrieved outcomes and individual crawl decisions.

The repairs preserve historical run metrics and record new deduplication categories separately. See `PRODUCTION_REPAIR_FINAL_REPORT.md` and the durable acceptance ledger for final validation and actual request counts.
