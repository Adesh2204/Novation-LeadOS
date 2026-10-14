# LeadOS master-view acceptance report

Verified on 7 October 2026 against the current synthetic dataset and the configured live Google workbook, **NOVATION_LEADOS_MASTER**.

**Applied and validated:** LEADOS_MASTER_VIEW is first and the only visible tab, with 44 unique opportunities covering all nine verticals. The 19 technical tabs and Sheet1 still exist. All technical cell values matched the pre-change backup exactly after setup. The subsequent requested dashboard approval and repeat discovery retained every original technical record ID and all original scores, score components and signal catalog rows.

## 1. Files changed

| File | Change |
|---|---|
| `backend/leados/api.py` | Post-commit startup sync, sync/status endpoints, HTTP sync outcome header |
| `backend/leados/cli.py` | Post-commit sync for seed/run/demo |
| `backend/leados/config.py` | Default-false SHOW_TECHNICAL_SHEETS setting |
| `backend/leados/storage/factory.py` | Application transaction wrapper; preserve existing refresh policy |
| `backend/leados/storage/google_client.py` | Generic metadata field/range parameters, with no projection logic |
| `backend/leados/storage/fake_google_client.py` | Emulate layout, visibility, metadata, whole-column moves, sorting, hyperlinks and bounded reads |
| `scripts/setup_google_sheets.py` | Validate populated technical data, arrange master, format, sync and hide tabs |
| `scripts/validate_google_sheets.py` | Validate master content, unique IDs, headers, visibility and helper columns |
| `scripts/import_leados_data.py` | Sync presentation after successful portable import |
| `scripts/import_legacy_sqlite.py` | Sync presentation after successful legacy import |
| `.env.example` | Document SHOW_TECHNICAL_SHEETS=false |
| `compose.yaml` | Pass visibility setting to backend |
| `README.md` | Current master-view behavior and operational commands |
| `docs/GOOGLE_SHEETS.md` | Master columns, mappings, sync/retry behavior, debug mode and verification boundary |
| `docs/GOOGLE_SHEETS_ACCEPTANCE.md` | Identify prior report as historical and link this revision |

The frontend is unchanged. SHA-256 checks verified all 20 protected engine/storage-contract/knowledge files against the pre-change backup, including engine.py, pipeline.py, safety.py, schemas.py, knowledge.py, StorageProvider, domain records, technical workbook schemas, and GoogleSheetsStorageProvider. The 114-signal catalog and nine vertical definitions remain unchanged.

## 2. Files created

- `backend/leados/services/__init__.py`
- `backend/leados/services/master_view.py`: read-only MasterViewService joins and flattens domain records.
- `backend/leados/services/master_view_sync.py`: application post-commit orchestration, pending markers and provider-specific sink selection.
- `backend/leados/services/master_view_setup.py`: populated-workbook preflight and non-destructive presentation migration.
- `backend/leados/storage/master_view_schema.py`: presentation column constants, separate from the 19 technical schemas.
- `backend/leados/storage/master_view_writer.py`: flat-row persistence and Google presentation layout, with no domain joins.
- `backend/tests/test_master_view.py`: 19 new automated tests.
- `scripts/master_view_acceptance.py`: repeatable network-free full-dataset API acceptance.
- `docs/MASTER_VIEW_ACCEPTANCE.md`: this report.
- `docs/master_view_demo.json`: full simulated-workbook acceptance evidence.
- `docs/master_view_live.json`: actual Google/API acceptance evidence.
- `docs/screenshots/master-view-atlas-approved.jpg`: dashboard approval proof.
- `docs/screenshots/master-view-repeat-discovery.jpg`: repeat-discovery proof.
- `data/master-view-demo-workbook.json`: populated simulated workbook, independently accepted by the validator.

Runtime synchronization also creates a `*-master-view-status.json` sidecar beside the configured storage outbox. Local JSON storage generates a `*-master-view.json` presentation beside its domain data file. These are derived/coordination artifacts, not domain sources of truth.

## 3. LEADOS_MASTER_VIEW columns

Visible columns, in exact order:

```text
company
industry
country
trigger
trigger_date
vertical
recommended_service
why_now
score
score_status
confidence
evidence_status
source
buyer
review_status
outreach_angle
```

Hidden columns Q–T: `opportunity_id`, `company_id`, `primary_source_id`, `updated_at`.

The real workbook has a frozen header and company column, a filter over all 16 visible columns, the 16 requested pixel widths, wrapped/top-aligned body text, percentage confidence, bold headers and nine conditional-formatting rules. API grid metadata confirms real source cells contain hyperlinks. Browser accessibility confirmed that the sole tab in the sheet tab bar is LEADOS_MASTER_VIEW.

## 4. How rows are generated

MasterViewService reads stored typed records through the unchanged StorageProvider. It groups related records once and emits one row per Opportunity:

- Company canonical name, sector/industry and country come from Company.
- Trigger, date, why-now, total score, official score band and confidence come from Opportunity.
- Human-readable vertical and service labels come from the canonical stored catalog references.
- For verified opportunities, eligible linked sources are checked with the existing evidence auditor. A source must be company-matched, factual, non-conflicting and otherwise eligible under the existing rules. Selection prefers confidence, then publication date, retrieval time and stable ID. Unsupported sources stay blank.
- Buyer is the first available role in the vertical's existing priority order, with confidence/stable tie-breakers; one role is displayed.
- Review uses the latest valid HUMAN_REVIEWS record by timestamp and ID. Without a review, verified opportunities show PENDING REVIEW; others require research. A manually edited opportunity/master status cannot substitute for a review.
- Outreach is the first subject from the newest draft, falling back to the opportunity angle. The dashboard retains the full message and all subject alternatives.

Rows sort by score descending, trigger date descending and opportunity ID. No Sheet formulas calculate scores, evidence, reviews or any other decision.

## 5. Sheets hidden

All 19 technical tabs remain present and hidden:

```text
COMPANIES
COMPANY_ALIASES
SOURCES
SIGNALS
COMPANY_SIGNALS
OPPORTUNITIES
OPPORTUNITY_EVIDENCE
SCORE_COMPONENTS
BUYER_ROLES
OUTREACH_DRAFTS
HUMAN_REVIEWS
FEEDBACK
SUPPRESSION_LIST
PROVIDER_RUNS
AUDIT_LOG
SYSTEM_CONFIG
SOURCE_PUBLISHERS
HUMAN_REVIEW_TASKS
CONTACT_EVENTS
```

The pre-existing Sheet1 is hidden too, with its contents retained, so only the master is visible. `SHOW_TECHNICAL_SHEETS=true` exposes all tabs for debugging; the four master helper columns remain hidden.

## 6. Automatic sync

API/CLI application transactions compare a fingerprint of projection-relevant domain records before and after work. After a successful domain commit, changed discovery/company/opportunity/evidence/buyer/draft/review/feedback records trigger a fresh stored-data projection and sync. Startup, CLI seed/run/demo and imports also sync. Future discovery providers using these application entry points inherit the hook.

Google mode reads and writes the presentation in batches. JSON mode writes a local presentation file and never accesses Google. Existing detailed dashboard behavior is retained.

Projection errors preserve the successful business commit and record a pending marker. A changed business write, application startup, CLI run or `POST /storage/master-view/sync` retries. `GET /storage/master-view/status` independently compares actual sheet rows with the backend projection and reports counts, last sync, duplicates, headers, visibility, content match and pending state. Successful business HTTP writes report `X-LeadOS-Master-View: synced` or `pending`.

## 7. Duplicate prevention

The hidden opportunity_id is the identity. The writer reads existing IDs, updates changed rows, appends missing opportunities in one grouped append request, and blanks only its 20 owned cells for obsolete or duplicate presentation rows. User-added columns and technical records are preserved; sorting moves complete rows together.

After an ambiguous committed response, retries re-read IDs/content before appending. A successful no-op sync performs no writes. The current 44-row projection fits in one atomic Google batch; bounded retries and the existing writer lock coordinate operations on one host.

## 8. Tests performed

- Full existing/new backend regression suite on both JSON storage and the actual Sheets adapter with its fake transport.
- 19 master-view tests covering creation, columns/formatting, one row per opportunity, sort order, source ranking, buyer selection, latest review, outreach, authoritative review behavior, manual-cell correction, duplicate repair, header repair/preflight, extra-column preservation, hidden tabs, debug unhide, atomic batches, lost-response retry, no-op writes, automatic API discovery/review/feedback and recovery after projection failure.
- Repeatable acceptance script using fresh simulated Google storage and the real API lifecycle: discover all fixtures, approve Atlas, rediscover, validate status and compare technical values before/after manual presentation sync.
- Actual setup and validator commands against the existing populated Google workbook; exact technical-cell comparison with the pre-change backup.
- Real API and dashboard checks: approve Atlas AI Systems in AI Governance; run repeat mock discovery through the dashboard; independently read and validate Google master rows.
- SHA-256 protected-file check, Python lint/format/type checks, frontend lint/types/production build and inactive workflow validation.

## 9. Test results

| Check | Result |
|---|---|
| Final backend suite | **262 passed**; 243 existing tests plus 19 new tests |
| Master/storage suite after live metadata correction | **67 passed** |
| Python lint and formatting | Passed; 74 files formatted |
| Backend mypy | Passed; 54 source files |
| Frontend lint, TypeScript and production build | Passed |
| Workflow validation | Both inactive 13-node workflows valid |
| Fresh full fixture run | 40 companies, 36 company signals, 44 opportunities, all 9 verticals |
| Simulated and live repeat discovery | 0 opportunities created; 167 duplicate observations avoided; 44 rows retained |
| Actual Google validator | valid=true, rows=expected_rows=44, duplicates=0, pending=false |
| Default visibility | Only LEADOS_MASTER_VIEW visible and first; 19 technical tabs plus Sheet1 hidden |
| Setup preservation | Every technical cell exactly matched the pre-change backup |
| Post-review/discovery preservation | Every original technical record ID retained; all original scores/components/catalog rows unchanged |
| Atlas review through dashboard | Same opportunity ID, APPROVED automatically, score 96/HOT, buyer General Counsel |
| Unsupported evidence | Weak AI Rumors shows NEEDS RESEARCH with blank source; existing score 93/MONITOR preserved |
| Source links | Selected verified URL matches stored evidence; real Google hyperlink metadata present |
| Email safety | Existing and new safety tests pass; dashboard delivery remains disabled |

The fixture intentionally contains one invalid URL. PARTIAL means that input was skipped; all 44 valid opportunities were handled successfully. It is not a failed master sync.

The live API uses the configured Google service account. No credentials were copied to this report or workbook. The actual Google metadata behavior was exercised: a ranges-filtered metadata request omits other sheets, so the writer requests all sheet properties/column metadata with a field mask excluding cell values. The emulator now models this behavior too.

Evidence: [simulated acceptance](master_view_demo.json), [live acceptance](master_view_live.json), [approval proof](screenshots/master-view-atlas-approved.jpg), [repeat discovery proof](screenshots/master-view-repeat-discovery.jpg). Pre-change source/workbook backups remain under `/private/tmp/leados-before-master-view` on this host.

## 10. Exact command to apply to the existing Google workbook

The configured workbook has already been updated. These commands are safe to repeat from the project root with the existing `.env` and credential file:

```sh
cd /Users/adesh/Novation-LeadOS
.venv/bin/python scripts/setup_google_sheets.py
```

To temporarily expose technical sheets:

```sh
.venv/bin/python scripts/setup_google_sheets.py --show-technical-sheets
```

Run normal setup again to restore default hiding. For persistent debug mode, set SHOW_TECHNICAL_SHEETS=true and restart the backend; validator configuration must match.

## 11. Exact command to validate

```sh
cd /Users/adesh/Novation-LeadOS
.venv/bin/python scripts/validate_google_sheets.py
```

For a workbook intentionally in debug mode, add `--show-technical-sheets`. For a pending technical write, `--recover` reconciles the technical outbox first; use setup/manual master sync afterward if the projection is stale.

To reproduce full acceptance without live Google:

```sh
.venv/bin/python scripts/master_view_acceptance.py
.venv/bin/python scripts/validate_google_sheets.py --mock --input data/master-view-demo-workbook.json
```

## 12. Remaining limitations

- The sources/companies are synthetic. `.example` hyperlinks correctly point to the selected fixture evidence identifiers; they are not public articles that can be visited. Real discovery adapters remain disabled in V1.
- Existing evidence-aware score bands remain authoritative. A high numeric score can be MONITOR or IGNORE when evidence fails, so sorting by numeric score can interleave those rows with HOT leads. Applying a simple threshold label would change the existing business logic and was deliberately avoided.
- Pending presentation sync has bounded immediate retries and the application/manual retry paths above; it has no independent timed background worker. Read-only requests do not retry it.
- Direct third-party technical-sheet edits require manual sync, startup or a later relevant application write; they are not watched continuously. Generated master cells are overwritten from domain records, with an edit warning rather than hard access restrictions.
- Sheets writes coordinate on one host/shared lock and outbox paths. Uncoordinated writers on separate machines and simultaneous human structural edits are outside that guarantee. Existing 10,000-row and 1.8 MB batch limits remain; larger deployments need a more scalable store.
- Docker execution and sustained Google quota/load testing remain unverified. Actual live authentication, setup, data preservation, discovery/review sync, visibility and source hyperlink metadata were tested.
- The optional frontend sync button was omitted; automatic refresh and the manual sync API are available.
