# Google Sheets storage acceptance report

Date: 6 October 2026. This report supersedes the operational-storage portions of the original SQL foundation report.

Historical report: the later [master-view acceptance report](MASTER_VIEW_ACCEPTANCE.md) records the current live Google connection, hidden technical tabs, projection, and expanded test results. The statements below about missing live credentials apply to the original storage revision.

The Google Sheets adapter is implemented behind StorageProvider. Local JSON remains the default until a workbook and credentials are configured. Both providers run the same core pipeline; Sheets tests use a fake client and HTTP mock transport. **No live Google workbook connection is claimed.**

## 1–2. Files created and modified

[FILES_CREATED.md](FILES_CREATED.md) lists every new and modified file in this revision and the complete delivered source inventory. New work includes twelve storage modules, five setup/validation/transfer scripts, storage acceptance tests, the workbook guide, machine-readable schemas and this report. Existing API, CLI, engine, pipeline, knowledge, safety, environment, dependencies, packaging and tests were adapted. The frontend and canonical knowledge definitions remain the existing application.

Original SQLite files are retained. A source/data backup is under `/private/tmp/leados-before-sheets`. Existing company, source, opportunity, draft, review and feedback IDs were checked against that snapshot; all opportunity scores, component points and review states were preserved. Six older JSON run snapshots without snapshot IDs are normalized to stable UUIDv5 IDs; subsequent exports/imports preserve those IDs.

## 3–5. Workbook design, tabs and every column

Use one workbook titled **NOVATION_LEADOS_MASTER**. Each entity has its own tab. All sixteen requested tabs exist in the schema, plus three support tabs for lossless preservation of publisher metadata, review tasks and contact history.

| Tab | Purpose | Column specification |
|---|---|---|
| COMPANIES | Canonical companies and observations | [Columns](GOOGLE_SHEETS.md#companies) |
| COMPANY_ALIASES | Names/domain clues and resolution confidence | [Columns](GOOGLE_SHEETS.md#company_aliases) |
| SOURCES | Documents, hashes, provenance and assertions | [Columns](GOOGLE_SHEETS.md#sources) |
| SIGNALS | Runtime UUID catalog metadata | [Columns](GOOGLE_SHEETS.md#signals) |
| COMPANY_SIGNALS | Company/event identity and linked documents | [Columns](GOOGLE_SHEETS.md#company_signals) |
| OPPORTUNITIES | Official scores, recommendations and review state | [Columns](GOOGLE_SHEETS.md#opportunities) |
| OPPORTUNITY_EVIDENCE | Opportunity/document links | [Columns](GOOGLE_SHEETS.md#opportunity_evidence) |
| SCORE_COMPONENTS | Scoring explanation snapshots | [Columns](GOOGLE_SHEETS.md#score_components) |
| BUYER_ROLES | Role mappings and contact validation state | [Columns](GOOGLE_SHEETS.md#buyer_roles) |
| OUTREACH_DRAFTS | Evidence-backed draft and approval fields | [Columns](GOOGLE_SHEETS.md#outreach_drafts) |
| HUMAN_REVIEWS | Append-only decisions | [Columns](GOOGLE_SHEETS.md#human_reviews) |
| FEEDBACK | Append-only outcomes and score/version snapshot | [Columns](GOOGLE_SHEETS.md#feedback) |
| SUPPRESSION_LIST | Company/domain/email exclusions | [Columns](GOOGLE_SHEETS.md#suppression_list) |
| PROVIDER_RUNS | Append-only versioned run snapshots | [Columns](GOOGLE_SHEETS.md#provider_runs) |
| AUDIT_LOG | Append-only action/error history | [Columns](GOOGLE_SHEETS.md#audit_log) |
| SYSTEM_CONFIG | Allowlisted non-sensitive configuration | [Columns](GOOGLE_SHEETS.md#system_config) |
| SOURCE_PUBLISHERS | Support: source origin/reliability metadata | [Columns](GOOGLE_SHEETS.md#source_publishers) |
| HUMAN_REVIEW_TASKS | Support: durable review queue | [Columns](GOOGLE_SHEETS.md#human_review_tasks) |
| CONTACT_EVENTS | Support: previous-contact safeguards | [Columns](GOOGLE_SHEETS.md#contact_events) |

The linked guide lists **every column**, including all required directive columns and extra fields needed to preserve existing data. [workbook_schema.json](workbook_schema.json) is the machine-readable specification generated from the actual mapper. Setup freezes headers, adds filters/dropdowns, uses restrained band colors and adds structural ID edit warnings without deleting rows.

Operational IDs are immutable UUIDs, never row numbers. Existing UUIDs remain unchanged; runtime signal UUIDv5 IDs retain canonical catalog codes separately. Vertical/service references stay stable knowledge keys. Dates are ISO 8601 UTC. Knowledge files remain canonical outside Sheets.

## 6. Storage abstraction

`storage/records.py` defines vendor-independent typed records. `StorageProvider` supplies typed CRUD, domain-facing company/signal/opportunity/evidence/score/review/feedback/draft/audit methods, indexes, integrity checks and coordinated units of work. Seven repositories use that contract. `MockStorageProvider` persists atomically to JSON; `GoogleSheetsStorageProvider` maps records through `workbook.py` and delegates API transport/authentication to `GoogleSheetsClient`.

Selection occurs in `storage/factory.py`. API dependencies commit before returning success. Core API, CLI, engine, pipeline, knowledge and safety modules import neither SQL nor Google client code; an AST test enforces this boundary. SQL models/migrations are isolated legacy import artifacts. A future SQL provider implements the same contract and portable import/export.

## 7. Deduplication and integrity

Company resolution uses normalized domains, exact normalized names/known aliases and country conservatively. Similar names with different domains are not merged. Documents use SHA-256 content and URL hashes, with observation timestamps refreshed on repeat collection. Company-signal records aggregate corroborating documents for one company/signal/event key. Opportunity fingerprints hash company UUID, vertical, signal UUID and event-day bucket.

Repeat discovery retains IDs, score components, reviews and feedback and creates zero new opportunities. References and unique keys are checked in the application. Sheets reads validate IDs, types, statuses, hashes, evidence assertions, score totals/bands and component completeness. Invalid rows and dependants are quarantined and audited; raw rows remain available for correction. Known corrupt identities/fingerprints cannot create replacement duplicates.

## 8. Batching and coordination

Reads use bounded `batchGet` ranges and indexed in-memory caches during a unit of work. Changed records accumulate into grouped append/update requests in one `batchUpdate`; tests verify a full 44-opportunity discovery commits as one adapter write batch. Fresh UUID lookups and baseline comparisons precede updates. Extra user columns/formulas are omitted from owned update ranges.

API requests serialize through an async lock. Writes also use a filesystem lock shared by CLI jobs on the same host. Provider-run revisions, reviews, feedback and audits append; mutable company/opportunity/draft state updates by UUID. Use one writer host with shared lock/outbox paths. A human sort during the narrow lookup/write interval cannot be fully prevented by Sheets; edit structural data between runs.

## 9. Retry and error handling

The REST client has configurable timeouts, a local request-rate ceiling, bounded retries and exponential backoff. Authentication/permission/missing-workbook errors fail with safe categories. Quota, network, timeout and server errors receive bounded handling. Error responses omit credentials and Google response secrets.

A durable JSON outbox records intended writes before transport. Each atomic batch carries a commit UUID. Ambiguous timeouts re-read that marker before retrying, so a completed append is not repeated. Exhausted writes retain the outbox and block new writes until recovery, including recovery from a new provider instance. Candidate integrity failures preserve successful candidates and report processed/successful/failed counts. Transport failures reconcile the whole atomic batch.

Default limits: three attempts, 15-second timeout, 45 requests/minute locally, 10,000 rows/tab and a 1.8 MB batch cap. These are implementation limits, not capacity guarantees for live Google. Oversized batches fail clearly. Export/archive growing history and migrate storage when scale warrants it.

## 10–11. Tests performed and results

| Verification | Actual result |
|---|---|
| `make validate` | **243 passed**; lint, formatting, backend/frontend types, production frontend build and workflow checks passed |
| Core/API integration on both providers | Same pipeline and safety behavior on JSON and actual Sheets adapter with fake client |
| Nine-vertical fixture discovery | 40 companies, 36 company signals, 44 opportunities; all nine verticals represented |
| Atlas integration | AI Governance and Privacy, score 96, linked evidence, draft and review task |
| Duplicate discovery | Zero new companies/sources/signals/opportunities; 167 duplicate observations avoided |
| Row/header sorting and extra formula column | UUID-targeted update retained identities and extra cells |
| Missing tabs/headers, duplicates and corrupt values | Safe structural errors or quarantined/audited rows; unaffected data remains usable |
| Corrupt assertion categories/content hashes | Unsupported opportunities could not remain VERIFIED |
| Two writers and stale human edits | Writers serialized; stale overwrite blocked |
| Quota/timeout/server errors | Bounded retries; no duplicate appends |
| Server commit followed by lost response | Commit marker acknowledged the existing write |
| Exhausted write and new-provider recovery | Prior records retained; pending batch recovered once |
| JSON/CSV export and import | UUIDs, scores, reviews, feedback and all run-snapshot IDs preserved; repeated import idempotent |
| Full preserved-data export → fake Sheets | 40 companies/44 opportunities and histories imported within batch cap; seven snapshot IDs preserved; approximately 1.10 MB request |
| Approval/suppression/contact safeguards | A manually edited APPROVED cell cannot substitute for an approved review; email remains blocked |
| Actual native n8n 2.42.3 execution | All 13 nodes successful on fresh JSON storage; 44 opportunities, 35 review tasks, no email |
| Clean source copy | Locked `make setup`, `make seed` and all-nine-vertical `make demo` passed without SQL migration or Google credentials |
| Browser on migrated JSON | Dashboard/repeat discovery passed; original Atlas approval, feedback and disabled send button retained |
| Compose structure | YAML/services/volumes checked; PostgreSQL removed from runtime configuration |

Evidence: [mock_demo.json](mock_demo.json), [n8n_validation.json](n8n_validation.json), [dashboard screenshot](screenshots/storage-dashboard.jpg), [preserved Atlas review screenshot](screenshots/storage-atlas.jpg).

The fixture intentionally includes one invalid URL; PARTIAL reports that skipped input while all 44 valid opportunities store successfully (`processed=44`, `successful=44`, `failed=0`). The test runner emits one upstream Starlette/httpx deprecation warning. Native n8n warns that its optional internal Python runner is unavailable; these HTTP/IF workflows do not need it and completed successfully.

## 12. Local commands

From the repository root:

```sh
cp .env.example .env
make setup seed demo
make backend
# In another terminal:
make frontend
```

Open [the dashboard](http://localhost:3000), [API docs](http://localhost:8000/docs) and [storage health](http://localhost:8000/storage/health).

```sh
make validate
.venv/bin/python scripts/setup_google_sheets.py --mock
.venv/bin/python scripts/validate_google_sheets.py --mock
.venv/bin/python scripts/export_leados_data.py --output data/export
```

The `--mock` commands simulate a workbook locally; their accessible/connected flags describe that fake workbook, not a live Google connection.

## 13. Connect Google Sheets later

Enable Sheets API in a Google Cloud project, create a dedicated service account, and obtain its JSON key through your allowed credential process. Keep the key outside the repository. Create NOVATION_LEADOS_MASTER and share only that workbook with the service-account email as Editor. Copy its spreadsheet ID into configuration.

The sole scope is `https://www.googleapis.com/auth/spreadsheets`; no Drive scope is requested. This scope permits spreadsheets the service account can access, so restrict actual file access using sharing. Service-account authentication is implemented; interactive OAuth is not.

Export local data first, set the Google environment values below, then:

```sh
.venv/bin/python scripts/setup_google_sheets.py
.venv/bin/python scripts/validate_google_sheets.py
.venv/bin/python scripts/import_leados_data.py --input data/export/leados.json
make seed
make backend
```

Detailed credential/sharing instructions and official references are in [GOOGLE_SHEETS.md](GOOGLE_SHEETS.md#authentication-and-access). Initialization verifies the existing named workbook; it does not create or choose a different workbook automatically. Use `validate_google_sheets.py --recover` for a pending outbox.

## 14. Environment variables

Local defaults and all provider placeholders are in [.env.example](../.env.example). The storage configuration is:

```dotenv
LEADOS_MODE=mock
LEADOS_STORAGE=mock
MOCK_STORAGE_PATH=./data/leados.json
GOOGLE_SHEETS_ENABLED=false
GOOGLE_SPREADSHEET_ID=
GOOGLE_SERVICE_ACCOUNT_JSON_PATH=
# Optional alternative environment secret: GOOGLE_SERVICE_ACCOUNT_JSON=
ENABLE_EMAIL_SEND=false
STORAGE_LOCK_PATH=./data/storage-writer.lock
STORAGE_OUTBOX_PATH=./data/sheets-outbox.json
SHEETS_TIMEOUT_SECONDS=15
SHEETS_MAX_ATTEMPTS=3
SHEETS_REQUESTS_PER_MINUTE=45
SHEETS_MAX_ROWS=10000
```

To connect, set LEADOS_STORAGE=google_sheets, GOOGLE_SHEETS_ENABLED=true, the spreadsheet ID and credential path. Market/research mode can remain mock independently of persistence. Secrets are never stored in SYSTEM_CONFIG or other tabs. Compose requires a local N8N_ENCRYPTION_KEY and a private read-only credential mount if using a file inside a container.

## 15. Remaining live integrations and verification boundary

Google service-account exchange, real workbook access, rendered Google formatting and real quota behavior await credentials/workbook and were not tested. Docker is unavailable on this host, so container startup is unverified. Search/crawling/LLM/contacts/CRM adapters for Exa, Firecrawl, OpenAI, Apollo and HubSpot remain disabled extension points. SMTP remains unintegrated with an independent V1 transport stop; no email was sent. Canonical knowledge retrieval remains local, and a production embedding/vector provider or future SQL provider requires its own adapter and integration tests.
