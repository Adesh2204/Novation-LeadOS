# LeadOS integrations

The pipeline works without SMTP or n8n. Email delivery stays disabled; approving an opportunity does not send a message.

## Current flow

1. **Mock discovery** runs the deterministic fixture pipeline with mock providers and no paid API calls.
2. **Live preview** searches Exa with explicit query/result ceilings and caching. It screens candidates without crawling, calling OpenAI or creating companies/opportunities.
3. **Live discovery** searches selected verticals, screens candidates, deduplicates evidence and scrapes exact source pages with Firecrawl. `FULL_LIVE` uses OpenAI embeddings to rank vetted services and structured research to explain the opportunity. The fixed scoring engine calculates the final score. Evidence verification and human review remain separate gates.
4. **Find buyer contacts** searches ContactOut for at most three current buyer profiles with company work emails. Snov.io checks deliverability. Unknown, catch-all, failed and pending results stay unverified. Mock, suppressed and weak leads cannot use external contact lookup.
5. **Sync approved lead to HubSpot** requires the latest human approval and verified evidence. It links an existing company by domain or creates a company with the approved brief. It preserves existing company information and prevents duplicate syncs.
6. Google Sheets stores records and updates `LEADOS_MASTER_VIEW` after commit. Original scores remain versioned.

## Environment

Credentials stay in `.env`; the frontend receives status only.

| Variable | Connection |
| --- | --- |
| `EXA_API_KEY` | Search and source excerpts |
| `FIRECRAWL_API_KEY` | Bounded scraping and credit-usage check |
| `OPENAI_API_KEY` | Structured research, service embeddings and review-only drafts |
| `CONTACT_OUT_API_KEY` | ContactOut authentication via its `token` header |
| `SNOVIO_USER_ID`, `SNOVIO_SECRET` | OAuth client credentials; access token cached in memory |
| `HUBSPOT_ACCESS_TOKEN` | HubSpot private app bearer token |
| Google service account settings | Google Sheets persistence |
| `N8N_ENCRYPTION_KEY`, `N8N_SECURE_COOKIE` | Optional container settings; these do not establish a running n8n connection |

The local configuration uses `LLM_PROVIDER=openai`, `EMBEDDING_PROVIDER=openai`, `CONTACT_PROVIDER=contactout_snovio`, `CRM_PROVIDER=hubspot` and `LIVE_RESEARCH_MODE=FULL_LIVE`. Mock discovery has a separate provider bundle. Live preview defaults to one query.

`Check connections` verifies authenticated access without sending emails or creating CRM companies. It does not spend Exa search credits. Exa is checked through bounded discovery. Status records contain only safe categories and timestamps. A green check reports the last successful check; future account quotas and source availability can change.

## Optional services

The API runs the complete workflow directly. n8n uses an optional Compose profile: `docker compose --profile automation up -d n8n`. Its workflows remain inactive. SMTP is neither configured nor required.

## Verification on 8 October 2026

- Authenticated OpenAI, ContactOut, Snov.io, HubSpot, Firecrawl and Google Sheets checks passed. A bounded real Exa search and one-page Firecrawl test passed.
- An isolated real OpenAI run completed service embeddings, research, deterministic scoring and four draft generations.
- The Google-backed live preview returned HTTP 200 and completed without creating opportunities.
- A real-source trial retained an inaccessible page for research. Natural hiring language was tested through detection, scoring, evidence auditing and storage validation. Unknown dates and invented evidence URLs are never promoted to facts.
- ContactOut people search was checked with one profile and `reveal_info=false`. Snov.io deliverability handling and CRM writes were tested with mock transport data. No real contact details were revealed or sent to Snov.io; no CRM company was created during acceptance testing.
- The app has contract tests for both storage implementations, stage ordering, retry/credit limits, citations, approval gates, deduplication and failures.
- Final validation passed: 341 tests, with two opt-in live tests skipped by the standard suite. Both live tests passed separately. Ruff, ESLint, mypy, TypeScript, the production build and both inactive n8n workflow definitions passed.
- Typography uses self-hosted Inter, larger body/table text and responsive controls. See [desktop](screenshots/live-discovery-connected.jpg) and [mobile](screenshots/live-discovery-mobile.jpg) views.

Request shapes were checked against official [OpenAI](https://developers.openai.com/api/docs/guides/structured-outputs), [ContactOut](https://api.contactout.com/), [Snov.io](https://snov.io/api), [HubSpot](https://developers.hubspot.com/docs/api-reference/legacy/crm/objects/companies/guide) and [Firecrawl](https://github.com/firecrawl/firecrawl/tree/main/apps/python-sdk) references.

## Dashboard, live discovery and latency

- The browser uses `/api/backend` on the frontend origin. Next.js forwards to the local API; Compose uses its internal backend service. Browser requests no longer depend on resolving a separate localhost origin.
- `make dev` starts frontend and backend together, reuses existing listeners and stops only processes it started.
- `/dashboard/state` returns one compact committed snapshot. Dashboard reads do not hold the discovery writer lock or read Google Sheets repeatedly. Indexed lookups retain insertion order; large opportunity lists render 100 rows at a time while filters use all loaded summaries.
- The live button starts a persisted job with HTTP 202. Progress survives refresh; duplicate starts attach to the active run. A restarted server marks interrupted work for review instead of replaying paid calls.
- Exa searches, source scraping and AI research use bounded concurrency (default three). Shared embeddings and source/query caches avoid repeated work. Atomic daily reservations preserve provider credit ceilings.
- Every retrieved unique source is displayed, including previews, low relevance, duplicates and sources beyond the company/research ceiling. The same results are persisted in ProviderRun records and projected into the visible `LEADOS_DISCOVERY_RESULTS` Google tab. Qualified opportunities still appear in `LEADOS_MASTER_VIEW` and the opportunity table.
- Query and company controls show effective ceilings. Catalog size, configured budgets and daily quotas apply. A source page or provider can remain unavailable; the app retains useful results for research and reports partial completion.
- Completion is shown only after the business commit and Sheets projection. A projection failure keeps committed records and provides a retry that does not repeat discovery calls. Large research views use incremental, bounded Sheets batches.

Acceptance on 8 October 2026: six frontend-to-backend dashboard requests took 651.8 ms cold and 5.7–9.3 ms warm (warm median 8.1 ms). A one-query, one-company live run reused cached search results and completed in 8.46 seconds including Google Sheets sync. Both retrieved sources matched actual rows in the visible research tab. One remained Needs Research and one was explicitly skipped by the company ceiling; no new opportunity was invented. All 46 existing opportunities, 368 score components, 36 drafts and two human approvals were preserved. One existing opportunity's last-seen timestamp advanced through the normal duplicate path.

These timings describe the tested local dataset, not a fixed latency guarantee for new searches, additional companies, slow websites or exhausted provider quotas. Acceptance also covered 2,000 research projection rows, concurrent requests, partial search failures, provider caps, sync failures, restarts and deterministic score equivalence.
