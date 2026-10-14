# LeadOS implementation plan

## Google Sheets storage revision — 6 October 2026

1. Preserve the existing SQLite data and source, then introduce provider-independent typed records, StorageProvider and repositories.
2. Implement atomic local JSON mock storage, application reference/uniqueness checks, UUIDs, indexes and coordinated writes.
3. Define all sixteen required workbook schemas and necessary support tabs; implement a credential-isolated GoogleSheetsClient, batched storage adapter and fake client.
4. Move pipeline, knowledge seeding, API, safety and CLI persistence behind StorageProvider without changing event, evidence or scoring rules.
5. Add safe workbook setup/validation, JSON/CSV export and import tools; change default environment and Compose away from PostgreSQL.
6. Test both storage providers, quotas/timeouts, manual corruption, reordered rows, concurrency, recovery, all-nine-vertical discovery and retained approval/email safeguards.
7. Validate the full application and document workbook columns, authentication, commands, limits and actual test results. Real Google access remains untested until credentials and a spreadsheet are supplied.

The source and existing database snapshot were backed up under `/private/tmp/leados-before-sheets`; the existing SQLite files are retained.

All seven storage revision phases are complete. Validation passed 243 tests, lint/types, the production frontend build and both inactive workflow checks. A fresh locked setup/seed/demo and an actual 13-node n8n execution passed on JSON storage. Both providers pass core/API integration with a fake Sheets client; preserved IDs, scores, reviews and feedback were checked. See [docs/GOOGLE_SHEETS_ACCEPTANCE.md](docs/GOOGLE_SHEETS_ACCEPTANCE.md) for the full report and live Google/Docker verification boundaries.

## Original foundation plan and historical completion record

Repository audit: the workspace is empty, with no Git repository, application, dependencies, or applicable AGENTS.md. Python 3.12 and Node 24 are available; Docker is not installed on this host.

1. Establish a FastAPI/SQLAlchemy backend, Pydantic contracts, relational schema and Alembic migration. Support PostgreSQL in Docker and SQLite for a zero-service local demo.
2. Author nine versioned vertical definitions, a business-event signal catalog of at least 100 records, and 40 mock companies including adversarial evidence cases.
3. Implement replaceable providers, normalization, conservative company resolution and deduplication; detect signals and route them through local knowledge retrieval.
4. Implement deterministic scoring, provenance and evidence audit, immutable score snapshots, buyer mapping and verified-fact outreach drafts.
5. Expose discovery, company, opportunity, dashboard, review and feedback APIs; enforce approval, suppression and V1 email disablement in the backend.
6. Build a Next.js review dashboard with filters, details, evidence, scores, review decisions and feedback history.
7. Package Docker development services and disabled n8n workflows; document clean-checkout setup and all nine acceptance examples.
8. Run backend tests, lint/type checks, frontend production build, migration checks and workflow validation. Record actual results and any host limitations.

All market intelligence is synthetic and labelled as fixture data. No live external providers, credentials or paid services are used. Future adapter placeholders fail closed.

## Completion record

All eight implementation steps are complete. The final suite has 171 passing tests, clean backend/frontend lint and type checks, a successful production build, SQLite migration execution and offline PostgreSQL SQL validation. Both n8n workflows imported into n8n 2.42.3 inactive; the manual workflow executed all 13 nodes against a fresh database and produced 35 review tasks with no email. A fresh source copy passed setup, migrations, seeding, all-nine-vertical demo and `make validate`. Browser review, feedback, duplicate discovery and responsive detail checks passed.

Docker is unavailable on the host, so actual Compose/PostgreSQL container startup remains unverified. Detailed evidence and remaining live-operation work are in [docs/ACCEPTANCE_REPORT.md](docs/ACCEPTANCE_REPORT.md).
