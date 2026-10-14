# Novation LeadOS acceptance report

> Historical SQL foundation report. The current operational persistence uses StorageProvider with local JSON and a Google Sheets adapter. See [GOOGLE_SHEETS_ACCEPTANCE.md](GOOGLE_SHEETS_ACCEPTANCE.md) for current results and [GOOGLE_SHEETS.md](GOOGLE_SHEETS.md) for setup and workbook columns.

Implemented and verified on 6 October 2026 in `/Users/adesh/Novation-LeadOS`. All company intelligence is synthetic fixture data. No live search, LLM, contact, CRM or email service was called, and no API key is needed.

## 1–2. Files created and modified

The workspace was empty before implementation. Every delivered source, configuration, knowledge, fixture, workflow, test and documentation file is newly created; no pre-existing application files were modified. [FILES_CREATED.md](FILES_CREATED.md) lists the complete deliverable inventory. Installed dependencies, generated builds, caches and local databases are excluded from that inventory and ignored by `.gitignore`.

## 3. Architecture implemented

- FastAPI, Pydantic and SQLAlchemy backend, with Alembic migrations. SQLite supports a zero-service local demo; Compose configures PostgreSQL with pgvector.
- Nine durable pipeline stages: discovery → normalization → company resolution → signal detection → ranked vertical routing → knowledge retrieval/research → deterministic scoring → evidence audit → storage. Buyer-role mapping, verified-fact drafts and human review tasks follow these decisions. The API and n8n use the same implementation.
- Seven replaceable provider contracts: search, crawler, LLM, embeddings, contacts, CRM and email. Mock implementations are deterministic and network-free. A shared execution policy supports rate limits, retry-after, backoff, timeouts and concurrency bounds. Future vendor adapters are disabled extension points.
- Versioned knowledge definitions, 114 structured business-event signals, curated services and local embedding retrieval. pgvector extension creation is prepared; mock retrieval uses in-memory cosine ranking, with no database vector index implemented yet.
- Conservative company resolution, URL/content hashes and database uniqueness prevent duplicate organizations, documents, signals and opportunities. Score and evidence snapshots are retained rather than overwritten by repeat discovery.
- Evidence records preserve source, URL, publication/retrieval dates, snippets, confidence and assertion type. Facts, allegations, inferences and commercial theses remain distinguishable. High numeric scores cannot bypass evidence requirements.
- Next.js/TypeScript dashboard with score-sorted opportunities, all requested filters, details, evidence, score components, drafts, human decisions, suppression and append-only feedback.
- Backend outreach checks enforce approval, evidence, suppression and previous-contact restrictions. An independent V1 transport stop blocks email even if `ENABLE_EMAIL_SEND=true`; approval only records a human decision.

## 4. Database tables

There are **20 application tables**, plus Alembic's schema-version table. Foreign keys, indexes and unique constraints are defined in the ORM and migrations.

| Area | Tables |
|---|---|
| Organizations and provenance | `companies`, `company_aliases`, `sources`, `source_documents` |
| Knowledge and detected events | `verticals`, `services`, `signals`, `company_signals` |
| Opportunity snapshots | `opportunities`, `opportunity_evidence`, `score_components`, `decision_maker_roles`, `outreach_drafts` |
| Human decisions and outcomes | `human_reviews`, `human_review_tasks`, `feedback_events` |
| Operations and outreach controls | `provider_runs`, `audit_log`, `suppressions`, `contact_events` |

Feedback stores status and reason separately, with reviewer notes, buyer role, original score and score/knowledge/signal versions. No prediction model has been trained.

## 5–6. Nine verticals and signal count

**114 unique signals** are loaded. Cross-vertical signals contribute to more than one routing count below, so these counts total more than 114. Every signal has structured descriptions, semantic text, keywords, strength, recency policy, source requirements, buyers, services, disqualifiers, examples and version. Every vertical has a checked-in definition under `knowledge/verticals/`.

| Vertical | Signals that can route here |
|---|---:|
| Privacy & Data Protection | 17 |
| Contract Lifecycle Management | 15 |
| Vendor & Third-Party Governance | 14 |
| AI Governance | 13 |
| Legal Operations | 12 |
| Investigations & Disputes Support | 13 |
| Transaction Diligence & Integration | 12 |
| Technology Contracts & IP | 13 |
| Corporate Compliance & Entity Coordination | 13 |

## 7–8. Tests performed and actual results

| Verification | Result |
|---|---|
| Backend unit and integration suite | **171 passed** |
| Ruff lint and formatting | Passed |
| Backend mypy | Passed: 36 source files |
| Frontend ESLint and TypeScript | Passed |
| Next.js production build and standalone server | Passed |
| SQLite migration upgrade, downgrade, re-upgrade and ORM parity | Passed |
| PostgreSQL migration SQL generation | Passed; offline SQL only |
| Workflow JSON, connections and inactive flags | Passed: 13 nodes per workflow |
| Actual n8n 2.42.3 imports | Both manual and scheduled exports imported; both inactive |
| Actual manual n8n execution against fresh native backend | Success through all 13 nodes; 44 opportunities, 35 review tasks, no email |
| Clean source copy: `make setup migrate seed demo` | Passed with fresh virtual environment and locked installs, no external keys |
| Clean source copy: `make validate` | Passed: tests, lint, types, production build and workflow validation |
| Browser acceptance | Dashboard, filtering, detail, approval, feedback, repeat discovery and responsive score display verified |
| Docker/Compose and live PostgreSQL startup | **Unverified: Docker is not installed on this host** |

Tests cover all 114 signal detection/routing cases, scoring bands and decay, missing/future dates, exact aliases and distinct domains/countries, Unicode names, URL deduplication, evidence requirements, approval, suppression, previous contact, feedback preservation, empty searches, retry/timeout behavior, malformed research JSON, provider failures and transactional recovery from database errors.

Safety tests spy on email transport and prove it cannot be reached before approval, after approval with sending disabled, or after approval with the flag enabled while V1's independent stop remains. Every suppression flag and previous contact are tested. Unsupported high-score evidence is downgraded; generic AI mentions, funding and new-CFO announcements do not automatically create the claimed opportunities. Allegations do not establish misconduct.

Browser approval and Meeting feedback on Atlas AI Systems are explicitly synthetic acceptance actions. They sent no communication. Screenshots are in [screenshots/](screenshots/). The suite emits one third-party Starlette/httpx deprecation warning, with no test failures.

## 9. Reproducible mock demo

The fixture contains **40 canonical companies and 44 raw market records**, including duplicates, old/weak events, multiple signals/verticals, missing/conflicting evidence, false positives and one invalid URL. Fresh discovery creates **36 company signals and 44 opportunities**, avoiding six duplicates. A second run creates **zero additional companies, signals or opportunities**, avoiding 167 duplicate processing events and preserving reviews and feedback.

The first run reports seven rejection events and one invalid-record error. Its `PARTIAL` result is intentional: the malformed URL is skipped and audited while valid records finish. These are event counters, not counts of rejected opportunities. Stored opportunity bands are 35 HOT, one STRONG, six MONITOR and two IGNORE; eight opportunities require further evidence/research or are rejected. The average first-run numerical score is 90.8. Scores describe synthetic inputs and need commercial calibration before live use.

All nine representative examples below are evidence-verified and queued for human review in the fresh demo. Buyer roles and complete component rationales are recorded in [mock_demo.json](mock_demo.json).

| Vertical | Company | Event | Recommended service | Score |
|---|---|---|---|---:|
| AI Governance | Atlas AI Systems | AI recruitment decision system | AI-use assessment | 96 |
| CLM | Aster Manufacturing | Growing contract review backlog | Contract workflow | 94 |
| Corporate Compliance | Bluebird Global | Indian subsidiary formation | Entity register | 96 |
| Investigations & Disputes | Granite Components | Announced arbitration proceedings | Counsel briefing | 89 |
| Legal Operations | Juniper Group | Growing legal matter backlog | Matter tracker | 94 |
| Privacy | Meridian Health Cloud | India market launch | Privacy readiness assessment | 96 |
| Technology & IP | Twin Name | Software licensing programme | Software licence | 94 |
| Transactions | Pioneer Capital | Acquisition agreement | Contract diligence | 96 |
| Vendor Governance | Cedar Fintech | Large vendor onboarding programme | Vendor intake | 94 |

Atlas also routes to Privacy. Its AI Governance score is 25 need + 20 ICP + 20 trigger + 10 recency + 8 scope + 3 role reachability + 5 expertise + 5 evidence = **96/100**. Suggested buyers are CISO, General Counsel, HR Head and Privacy Head. They are role types, with no invented personal contacts. Its verified fixture evidence permits a draft and human review; it never enables delivery.

Run the terminal demo with `make demo`. For a fresh isolated database plus approval/feedback/send-block/deduplication assertions and report regeneration, run:

```sh
.venv/bin/python scripts/acceptance_demo.py
```

Fixture dates are anchored around 6 October 2026. Production calculations use the assessment date, so rerunning on a later date can lower recency scores; tests use a fixed anchor date.

## 10. n8n workflow location

- [workflows/mock_manual.json](../workflows/mock_manual.json)
- [workflows/mock_schedule.json](../workflows/mock_schedule.json)

Both exports are inactive. The schedule remains disabled. The final branch creates human review tasks only for verified scores ≥80. There are no email or CRM-write nodes. [n8n_validation.json](n8n_validation.json) records actual import and fresh native execution results. Native execution used temporary copies pointing at `127.0.0.1:8001`; the delivered exports use `http://backend:8000` for Compose. For native n8n, change every HTTP-node backend URL to `http://127.0.0.1:8000`.

## 11. Exact local startup instructions

Prerequisites: Python 3.12+, Node.js 24 and npm. From a fresh copy:

```sh
cd /Users/adesh/Novation-LeadOS
cp .env.example .env
make setup migrate seed demo
```

Start the API in one terminal:

```sh
cd /Users/adesh/Novation-LeadOS
make backend
```

Start the dashboard in another:

```sh
cd /Users/adesh/Novation-LeadOS
make frontend
```

Open [http://localhost:3000](http://localhost:3000) and [API documentation](http://localhost:8000/docs). Dependencies and demo data are already installed in the delivered workspace. The API and production dashboard were left running at these addresses after acceptance; stop them before starting replacements on the same ports.

Run `make validate` for the complete local suite. The [README](../README.md) documents Docker setup, migrations, n8n startup/import commands, API requests, production frontend startup and provider selection. Docker instructions are supplied but have not been exercised on this host.

## 12. Remaining TODOs and limitations

- Exercise Compose, live PostgreSQL migrations and pgvector extension installation on a host with Docker. This is the remaining environment verification.
- Calibrate signal recall, evidence reliability and commercial score assumptions with Novation before relying on live market results.
- Implement and contract-test selected real provider adapters before setting their selectors. The present adapters fail closed.
- Add database vector persistence/indexing if a larger real knowledge corpus warrants it.
- Add authentication/authorization, backup and retention policies before shared deployment. This foundation is designed for a local single user.
- Define real contact identity, suppression imports and CRM mapping before integrating contact/CRM systems.
- Any future email capability requires an intentional code change to the independent V1 stop, along with preserved approval, evidence, suppression and prior-contact tests. A flag alone cannot enable delivery.

## 13. External API extension points

| Provider contract | Prepared vendor extension |
|---|---|
| SearchProvider | Exa |
| CrawlerProvider | Firecrawl; another crawler such as Apify can implement the same contract |
| LLMProvider / EmbeddingProvider | OpenAI |
| ContactProvider | Apollo; another search/contact service can implement the same contract |
| CRMProvider | HubSpot |
| EmailProvider | SMTP, with V1 delivery independently blocked |

These are **disabled adapters, not working live integrations**. Implement the adapter using environment-held credentials, validate outputs and failure behavior, then select it through configuration. The core entity resolution, scoring, evidence, review and feedback logic does not need vendor-specific changes.
