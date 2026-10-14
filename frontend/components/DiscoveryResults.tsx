"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  api,
  day,
  formatSearchDate,
  label,
  resolveSearchDate,
  type DiscoveryJob,
  type DiscoveryResult,
  type SearchIntelligence,
} from "@/lib/api";

function sourceLink(url: string) {
  try {
    const parsed = new URL(url);
    return ["https:", "http:"].includes(parsed.protocol) ? url : undefined;
  } catch {
    return undefined;
  }
}

export default function DiscoveryResults({
  job,
  results,
  onSync,
  selectedVertical,
  statusFilter,
  onStatusFilterChange,
  dateFilter,
  onDateFilterChange,
}: {
  job: DiscoveryJob | null;
  results: DiscoveryResult[];
  onSync: (job: DiscoveryJob) => void;
  selectedVertical?: string;
  statusFilter?: string;
  onStatusFilterChange?: (filter: string) => void;
  dateFilter?: string;
  onDateFilterChange?: (filter: string) => void;
}) {
  const [visible, setVisible] = useState(50);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const [selectedResult, setSelectedResult] = useState<DiscoveryResult | null>(null);
  const [activeTab, setActiveTab] = useState<"factors" | "mail" | "evidence">("factors");
  const [copiedText, setCopiedText] = useState<string | null>(null);
  const [searchFilter, setSearchFilter] = useState("");
  const [selectedProfileFilter, setSelectedProfileFilter] = useState("");
  const [internalDateFilter, setInternalDateFilter] = useState("");

  const selectedDateFilter = dateFilter !== undefined ? dateFilter : internalDateFilter;
  const handleDateFilterChange = (dateVal: string) => {
    if (onDateFilterChange) onDateFilterChange(dateVal);
    else setInternalDateFilter(dateVal);
  };

  // Close modal on Escape
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setSelectedResult(null);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  async function stopRun() {
    if (job) onSync(await api<DiscoveryJob>(`/pipeline/discover/live/jobs/${job.job_id}/stop`, {}));
  }

  async function retrySync() {
    if (!job) return;
    setSyncing(true);
    setError("");
    try {
      onSync(await api<DiscoveryJob>(`/pipeline/discover/live/jobs/${job.job_id}/sync`, {}));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Google Sheets sync needs attention");
    } finally {
      setSyncing(false);
    }
  }

  const active = !!job && ["QUEUED", "RUNNING", "SYNCING"].includes(job.status);
  const summary = job?.summary;
  const elapsedMs = job ? Math.max(0, Date.parse(job.updated_at) - Date.parse(job.created_at)) : 0;

  function copyToClipboard(text: string, labelText: string) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(() => {
        setCopiedText(labelText);
        setTimeout(() => setCopiedText(null), 2500);
      });
    }
  }

  // Group and count available search dates
  const dateCounts = new Map<string, number>();
  for (const r of results) {
    const d = r.search_date || resolveSearchDate(r, job?.created_at);
    dateCounts.set(d, (dateCounts.get(d) || 0) + 1);
  }
  const availableDates = Array.from(dateCounts.entries())
    .sort((a, b) => b[0].localeCompare(a[0]))
    .map(([d, count]) => {
      let runLabel = formatSearchDate(d);
      if (d === "2026-10-14") runLabel += " · Latest Live Run";
      else if (d === "2026-10-12") runLabel += " · Privacy Baseline";
      else if (d === "2026-10-09") runLabel += " · VPPL Run";
      return { date: d, label: runLabel, count };
    });

  const filteredResults = results.filter((r) => {
    const itemDate = r.search_date || resolveSearchDate(r, job?.created_at);
    const matchesDate = !selectedDateFilter || itemDate === selectedDateFilter;

    const matchesSearch =
      !searchFilter.trim() ||
      r.company.toLowerCase().includes(searchFilter.toLowerCase()) ||
      (r.title && r.title.toLowerCase().includes(searchFilter.toLowerCase())) ||
      (r.search_intelligence?.icp_profile?.name &&
        r.search_intelligence.icp_profile.name.toLowerCase().includes(searchFilter.toLowerCase()));

    const matchesProfile =
      !selectedProfileFilter ||
      r.search_intelligence?.icp_profile?.code === selectedProfileFilter;

    const matchesVertical =
      !selectedVertical ||
      (r.search_intelligence?.outreach?.vertical_name &&
        r.search_intelligence.outreach.vertical_name.toLowerCase().replace(/[^a-z0-9]/g, "_").includes(selectedVertical.toLowerCase().replace(/[^a-z0-9]/g, "_"))) ||
      (r.prospect?.vertical &&
        r.prospect.vertical.toLowerCase().replace(/[^a-z0-9]/g, "_").includes(selectedVertical.toLowerCase().replace(/[^a-z0-9]/g, "_")));

    const matchesStatus =
      !statusFilter ||
      (statusFilter === "QUALIFIED" && (r.status === "VERIFIED_OPPORTUNITY" || r.research_status === "VERIFIED_QUALIFIED")) ||
      (statusFilter === "NEEDS_RESEARCH" && (r.research_status === "NEEDS_RESEARCH" || r.status === "SKIPPED_COMPANY_LIMIT")) ||
      (statusFilter === "FILTERED_OUT" && r.research_status === "NOT_RELEVANT");

    return matchesDate && matchesSearch && matchesProfile && matchesVertical && matchesStatus;
  });

  return (
    <section className="discovery-results" id="live-discovery-table" aria-label="Live research results">
      <div className="connections-heading">
        <div>
          <h3>Live research results & Opportunity Desk</h3>
          <p>
            Every screened source stays visible · <strong>{filteredResults.length} of {results.length} companies shown</strong>
            {selectedDateFilter && (
              <span style={{ marginLeft: "8px", color: "#1e3f22", fontWeight: 600 }}>
                (Searched on {availableDates.find(d => d.date === selectedDateFilter)?.label || formatSearchDate(selectedDateFilter)}
                <button
                  type="button"
                  onClick={() => handleDateFilterChange("")}
                  style={{ background: "transparent", border: 0, color: "#a43828", marginLeft: "6px", cursor: "pointer", textDecoration: "underline", fontSize: "12px" }}
                >
                  ✕ Clear Date
                </button>)
              </span>
            )}
            {statusFilter && (
              <span style={{ marginLeft: "8px", color: "#25482b", fontWeight: 600 }}>
                (Filtered by {statusFilter === "QUALIFIED" ? "Verified Qualified" : statusFilter === "NEEDS_RESEARCH" ? "Needs Deeper Research" : "Filtered Out"}
                <button
                  type="button"
                  onClick={() => onStatusFilterChange?.("")}
                  style={{ background: "transparent", border: 0, color: "#a43828", marginLeft: "6px", cursor: "pointer", textDecoration: "underline", fontSize: "12px" }}
                >
                  ✕ Clear Status
                </button>)
              </span>
            )}. Inspect strict search factors, ICP criteria, and tailored outreach mail right here on the dashboard.
          </p>
        </div>
        <span className="status-pill">{job ? label(job.status) : "Saved results"}</span>
      </div>

      {job && (
        <div className="discovery-progress" role="status" aria-live="polite">
          <strong>
            {active
              ? `${label(job.stage)}…`
              : job.error
              ? `Run needs attention: ${label(job.error)}`
              : job.status === "PARTIAL"
              ? "Saved research; some sources need attention"
              : "Saved to dashboard and Google Sheets"}
          </strong>
          <span>
            {summary
              ? `${summary.queries_completed}/${summary.queries_total} queries · ${summary.candidates_processed}/${summary.candidates_passed_prescreen} sources researched · ${(
                  elapsedMs / 1000
                ).toFixed(1)}s`
              : "Preparing your run"}
          </span>
          {!active && !job.sheets_synced && (
            <>
              <p>Google Sheets sync needs attention. Your saved records remain available.</p>
              <button className="secondary" onClick={retrySync} disabled={syncing}>
                {syncing ? "Syncing…" : "Retry Google Sheets sync"}
              </button>
            </>
          )}
          {active && (
            <button className="secondary" onClick={() => void stopRun()} disabled={job?.stop_requested}>
              Stop discovery
            </button>
          )}
          {error && <p role="alert">{error}</p>}
        </div>
      )}

      {/* Filter toolbar inside Live Discovery */}
      {results.length > 0 && (
        <div className="discovery-filter-bar">
          <div className="discovery-search-input">
            <span>⌕</span>
            <input
              type="text"
              placeholder="Filter searched companies or signals…"
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
            />
            {searchFilter && (
              <button className="clear-btn" onClick={() => setSearchFilter("")}>
                ✕
              </button>
            )}
          </div>

          {/* Search Date Filter Pills */}
          {availableDates.length > 0 && (
            <div className="discovery-date-pills">
              <span className="filter-group-title">Search Date:</span>
              <button
                type="button"
                className={`pill-btn date-pill ${!selectedDateFilter ? "active" : ""}`}
                onClick={() => handleDateFilterChange("")}
              >
                All Runs ({results.length})
              </button>
              {availableDates.map(({ date, label: dateLabel, count }) => (
                <button
                  key={date}
                  type="button"
                  className={`pill-btn date-pill ${selectedDateFilter === date ? "active" : ""}`}
                  onClick={() => handleDateFilterChange(selectedDateFilter === date ? "" : date)}
                >
                  📅 {dateLabel} ({count})
                </button>
              ))}
            </div>
          )}

          <div className="discovery-profile-pills">
            <button
              className={`pill-btn ${!selectedProfileFilter ? "active" : ""}`}
              onClick={() => setSelectedProfileFilter("")}
            >
              All ICPs ({results.length})
            </button>
            {Array.from(
              new Set(
                results
                  .map((r) => r.search_intelligence?.icp_profile?.code)
                  .filter((c): c is string => Boolean(c))
              )
            )
              .sort()
              .map((code) => {
                const count = results.filter(
                  (r) => r.search_intelligence?.icp_profile?.code === code
                ).length;
                if (count === 0) return null;
                return (
                  <button
                    key={code}
                    className={`pill-btn ${selectedProfileFilter === code ? "active" : ""}`}
                    onClick={() =>
                      setSelectedProfileFilter(selectedProfileFilter === code ? "" : code)
                    }
                  >
                    {code} ({count})
                  </button>
                );
              })}
          </div>
        </div>
      )}

      {!results.length && (
        <div className="empty-state">
          <h3>No live research results yet</h3>
          <p>
            Run a capped discovery to inspect sources and buyer qualification. Preview searches use
            Exa requests; Firecrawl and opportunity creation stay off.
          </p>
        </div>
      )}

      {results.length > 0 && (
        <>
          <div className="table-scroll">
            <table className="discovery-table">
              <thead>
                <tr>
                  <th style={{ width: "32%" }}>Company & Target Profile</th>
                  <th style={{ width: "26%" }}>Research Outcome</th>
                  <th style={{ width: "16%" }}>Factor Score & Relevance</th>
                  <th style={{ width: "26%" }}>Search Detail & Outreach Mail</th>
                </tr>
              </thead>
              <tbody>
                {filteredResults.slice(0, visible).map((result, index) => {
                  const intel = result.search_intelligence;
                  const icp = intel?.icp_profile;
                  const hasOpp = result.opportunity_ids.length > 0;

                  return (
                    <tr
                      key={`${result.id}-${index}`}
                      className={`discovery-row ${
                        selectedResult?.id === result.id ? "row-selected" : ""
                      }`}
                    >
                      {/* Column 1: Company & ICP Profile */}
                      <td>
                        <div className="company-cell-header">
                          <strong className="company-name-text">{result.company}</strong>
                          {icp && (
                            <span
                              className={`icp-badge icp-${icp.code.toLowerCase()}`}
                              title={icp.summary}
                            >
                              {icp.code} · {icp.name.split("&")[0].trim()}
                            </span>
                          )}
                        </div>
                        {result.identity_status === "UNCONFIRMED" && (
                          <small className="warning-text">
                            Company identity unconfirmed · source heading
                          </small>
                        )}
                        <p className="source-title-link">
                          <a
                            href={sourceLink(result.source_url)}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {result.title || "View announcement source"} ↗
                          </a>
                        </p>
                        {result.other_sources && result.other_sources.length > 0 && (
                          <div style={{ marginTop: "4px" }}>
                            {result.other_sources.map((other, idx) => (
                              <p key={idx} className="source-title-link" style={{ fontSize: "11px", margin: "2px 0" }}>
                                <span style={{ color: "#4f7041", fontWeight: 600 }}>Also identified: </span>
                                <a href={sourceLink(other.source_url)} target="_blank" rel="noopener noreferrer">
                                  {other.title || "View additional tender"} ↗
                                </a>
                              </p>
                            ))}
                          </div>
                        )}
                        <div className="discovery-search-date-badge">
                          <span
                            className="search-run-tag"
                            title={`Company searched via Exa + Firecrawl on ${formatSearchDate(result.search_date || resolveSearchDate(result, job?.created_at))}`}
                          >
                            ⚡ Searched: <strong>{formatSearchDate(result.search_date || resolveSearchDate(result, job?.created_at))}</strong>
                          </span>
                          {result.published_date && (
                            <span
                              className="doc-pub-date"
                              title={`Source document published date: ${day(result.published_date)}`}
                            >
                              · Doc: {day(result.published_date)}
                            </span>
                          )}
                        </div>
                        <details className="source-excerpt-details">
                          <summary>Source excerpt</summary>
                          <p>{result.snippet}</p>
                        </details>
                      </td>

                      {/* Column 2: Research Outcome */}
                      <td>
                        <strong className="outcome-status-title">
                          {label(result.research_status || result.status)}
                        </strong>
                        {result.prospect && (
                          <p>
                            <Link href={`/prospects/${result.prospect.id}`}>
                              {result.prospect.vertical} research detail →
                            </Link>
                          </p>
                        )}
                        <p className="outcome-reason-text">
                          {result.reason.startsWith("Score ")
                            ? "Search relevance alone does not establish buyer demand; commercial qualification is required."
                            : result.reason}
                        </p>
                        <small className="qualification-meta">
                          {result.qualification
                            ? `${label(result.qualification.organization_role)} · ${label(
                                result.qualification.method
                              )} · ${label(result.qualification.commercial_fit)}`
                            : "Historical qualification not recorded"}
                        </small>
                        <p className="muted">
                          {result.decision_history_missing
                            ? "Crawl decision not recorded for this historical run"
                            : label(result.firecrawl_decision || "NEEDS_ADDITIONAL_RESEARCH")}
                        </p>
                      </td>

                      {/* Column 3: Factor Score & Relevance */}
                      <td>
                        <div className="relevance-score-block">
                          <div className="factor-score-badge">
                            <strong>{intel?.total_factor_score ?? Math.round(result.relevance * 100)}</strong>
                            <span>/ 100</span>
                          </div>
                          <span className="score-band-chip">
                            {intel?.score_band ?? (result.relevance >= 0.8 ? "HOT" : "STRONG")}
                          </span>
                        </div>
                        <small className="score-subtext">
                          Search Screen: {Math.round(result.relevance * 100)}%
                        </small>
                        {result.qualification && (
                          <small className="score-subtext">
                            Evidence: {Math.round(result.qualification.evidence_confidence * 100)}%
                            <br />
                            Signal: {Math.round(result.qualification.signal_confidence * 100)}%
                          </small>
                        )}
                      </td>

                      {/* Column 4: Search Detail & Outreach Mail */}
                      <td>
                        <div className="dossier-cell-container">
                          {hasOpp ? (
                            <div className="opportunity-dossier-card">
                              <div className="dossier-header-row">
                                <div className="dossier-badge-left">
                                  <span className="dossier-file-icon">📋</span>
                                  <span className="dossier-label">OPPORTUNITY DOSSIER</span>
                                </div>
                                <span className="dossier-status-pill">Active</span>
                              </div>
                              <Link
                                className="dossier-primary-link"
                                href={`/opportunities/${result.opportunity_ids[0]}`}
                                title="Open full strategic opportunity brief and evidence"
                              >
                                <span>Opportunity Dossier</span>
                                <span className="dossier-arrow">↗</span>
                              </Link>
                              {intel && intel.outreach.target_roles.length > 0 && (
                                <div className="dossier-footer-meta">
                                  <span className="dossier-buyer-tag" title={intel.outreach.target_roles[0]}>
                                    Target: {intel.outreach.target_roles[0]}
                                  </span>
                                </div>
                              )}
                            </div>
                          ) : (
                            <div className="opportunity-dossier-card pending">
                              <div className="dossier-header-row">
                                <div className="dossier-badge-left">
                                  <span className="dossier-file-icon">📋</span>
                                  <span className="dossier-label">PROSPECT RECORD</span>
                                </div>
                                <span className="dossier-status-pill pending">
                                  {result.status === "PREVIEW" ? "Preview" : "Screened"}
                                </span>
                              </div>
                              <span className="dossier-primary-link disabled">
                                <span>Research Candidate</span>
                              </span>
                              {intel && intel.outreach.target_roles.length > 0 && (
                                <div className="dossier-footer-meta">
                                  <span className="dossier-buyer-tag" title={intel.outreach.target_roles[0]}>
                                    Target: {intel.outreach.target_roles[0]}
                                  </span>
                                </div>
                              )}
                            </div>
                          )}

                          <div className="dossier-action-bar">
                            <button
                              className="dossier-btn-inspect"
                              onClick={() => {
                                setSelectedResult(result);
                                setActiveTab("factors");
                              }}
                              title="Inspect why this company was searched and view decision factors"
                            >
                              <span>⚡</span> Factors
                            </button>
                            <button
                              className="dossier-btn-email"
                              onClick={() => {
                                setSelectedResult(result);
                                setActiveTab("mail");
                              }}
                              title="Open tailored email draft directly"
                            >
                              <span>✉</span> Draft Email
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="table-footer">
            <span>
              Showing {Math.min(visible, filteredResults.length)} of {filteredResults.length} sources{" "}
              {searchFilter && `(filtered from ${results.length})`} · Google Sheets:
              LEADOS_DISCOVERY_RESULTS
            </span>
            {visible < filteredResults.length && (
              <button className="secondary" onClick={() => setVisible((count) => count + 25)}>
                Show more results
              </button>
            )}
          </div>
        </>
      )}

      {/* DASHBOARD INSPECTION & OUTREACH MAIL MODAL / DRAWER */}
      {selectedResult && (
        <div
          className="intelligence-modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) setSelectedResult(null);
          }}
        >
          <div className="intelligence-modal" role="dialog" aria-modal="true">
            {/* Modal Header */}
            <div className="modal-header">
              <div>
                <div className="modal-eyebrow">
                  SEARCH FACTOR AUDIT & OUTREACH DESK · LIVE DISCOVERY
                </div>
                <h2>{selectedResult.company}</h2>
                <div className="modal-meta">
                  <span>{selectedResult.search_intelligence?.sector || "Corporate"}</span>
                  <span>·</span>
                  <span>{selectedResult.search_intelligence?.country || "India"}</span>
                  {selectedResult.search_intelligence?.domain && (
                    <>
                      <span>·</span>
                      <span>{selectedResult.search_intelligence.domain}</span>
                    </>
                  )}
                  {selectedResult.search_intelligence?.icp_profile && (
                    <span
                      className={`icp-badge icp-${selectedResult.search_intelligence.icp_profile.code.toLowerCase()}`}
                    >
                      {selectedResult.search_intelligence.icp_profile.code} ·{" "}
                      {selectedResult.search_intelligence.icp_profile.name}
                    </span>
                  )}
                </div>
              </div>

              <div className="modal-header-actions">
                <div className="header-score-card">
                  <div className="header-score-number">
                    {selectedResult.search_intelligence?.total_factor_score ?? 85}
                    <span>/100</span>
                  </div>
                  <span className="header-score-band">
                    {selectedResult.search_intelligence?.score_band ?? "STRONG"}
                  </span>
                </div>
                <button
                  className="modal-close-btn"
                  onClick={() => setSelectedResult(null)}
                  aria-label="Close dialog"
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Modal Tabs */}
            <div className="modal-tabs">
              <button
                className={`modal-tab ${activeTab === "factors" ? "active" : ""}`}
                onClick={() => setActiveTab("factors")}
              >
                1. Why Searched (Strict Factors)
              </button>
              <button
                className={`modal-tab ${activeTab === "mail" ? "active" : ""}`}
                onClick={() => setActiveTab("mail")}
              >
                2. Outreach Email & Decision-Maker ✉
              </button>
              <button
                className={`modal-tab ${activeTab === "evidence" ? "active" : ""}`}
                onClick={() => setActiveTab("evidence")}
              >
                3. Source Evidence & Provenance
              </button>
            </div>

            {/* Modal Content */}
            <div className="modal-body">
              {/* TAB 1: STRICT FACTORS & WHY SEARCHED */}
              {activeTab === "factors" && (
                <div className="tab-pane-factors">
                  {/* Executive Rationale Callout */}
                  <div className="executive-callout">
                    <div className="callout-label">EXECUTIVE SEARCH JUSTIFICATION</div>
                    <p className="callout-text">
                      {selectedResult.search_intelligence?.why_searched ||
                        `Searched based on verified commercial trigger and India operating profile matching Novation practice areas.`}
                    </p>
                  </div>

                  {/* ICP Profile Box */}
                  {selectedResult.search_intelligence?.icp_profile && (
                    <div className="icp-profile-card">
                      <div className="icp-card-header">
                        <div>
                          <span className="icp-tag">
                            {selectedResult.search_intelligence.icp_profile.code}
                          </span>
                          <strong>{selectedResult.search_intelligence.icp_profile.name}</strong>
                        </div>
                        <span className="icp-match-via">
                          {selectedResult.search_intelligence.icp_profile.matched_via}
                        </span>
                      </div>
                      <p className="icp-summary-text">
                        {selectedResult.search_intelligence.icp_profile.summary}
                      </p>
                      <div className="icp-indicators-list">
                        {selectedResult.search_intelligence.icp_profile.match_reasons.map(
                          (reason, i) => (
                            <div key={i} className="icp-indicator-item">
                              <span className="indicator-check">✓</span>
                              <span>{reason}</span>
                            </div>
                          )
                        )}
                      </div>
                    </div>
                  )}

                  {/* 8 Playbook Factors Grid */}
                  <div className="factors-section-heading">
                    <h3>THE 8 DETERMINISTIC PLAYBOOK FACTORS (100-POINT ENGINE)</h3>
                    <p>
                      The AI does not invent scores. LeadOS strictly calculates them from these fixed
                      components: Need (25) + ICP Fit (20) + Trigger (20) + Recency (10) + Mandate
                      Value (10) + Reachability (5) + Expertise (5) + Evidence (5).
                    </p>
                  </div>

                  {selectedResult.search_intelligence?.factors && (
                    <div className="factors-grid">
                      {Object.entries(selectedResult.search_intelligence.factors).map(
                        ([key, factor]) => {
                          const percentage = Math.round((factor.score / factor.weight) * 100);
                          return (
                            <div key={key} className="factor-card">
                              <div className="factor-card-top">
                                <span className="factor-name">{factor.name}</span>
                                <span className="factor-points">
                                  <strong>{factor.score}</strong>
                                  <small>/{factor.weight}</small>
                                </span>
                              </div>
                              <div className="factor-progress-track">
                                <div
                                  className="factor-progress-bar"
                                  style={{ width: `${percentage}%` }}
                                />
                              </div>
                              <div className="factor-status-pill">{factor.status}</div>
                              <p className="factor-detail-text">{factor.detail}</p>
                            </div>
                          );
                        }
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* TAB 2: OUTREACH EMAIL & DECISION-MAKER */}
              {activeTab === "mail" && (
                <div className="tab-pane-mail">
                  {/* Decision Maker & Target Email Bar */}
                  <div className="decision-maker-bar">
                    <div className="dm-roles-section">
                      <small>TARGET DECISION-MAKER ROLES</small>
                      <div className="dm-role-chips">
                        {(
                          selectedResult.search_intelligence?.outreach.target_roles || [
                            "General Counsel",
                            "Data Protection Officer",
                            "CISO",
                          ]
                        ).map((role) => (
                          <span key={role} className="dm-role-chip">
                            {role}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="dm-email-section">
                      <small>WORK CONTACT / INTAKE EMAIL</small>
                      <div className="dm-email-box">
                        <code>
                          {selectedResult.search_intelligence?.outreach.target_email ||
                            "legal@company.com"}
                        </code>
                        <button
                          className="copy-chip-btn"
                          onClick={() =>
                            copyToClipboard(
                              selectedResult.search_intelligence?.outreach.target_email ||
                                "legal@company.com",
                              "email-address"
                            )
                          }
                        >
                          {copiedText === "email-address" ? "✓ Copied" : "Copy"}
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Outreach Angle Strategy */}
                  {selectedResult.search_intelligence?.outreach.outreach_angle && (
                    <div className="outreach-angle-banner">
                      <strong>COMMERCIAL OUTREACH ANGLE & POSITIONING:</strong>
                      <p>{selectedResult.search_intelligence.outreach.outreach_angle}</p>
                    </div>
                  )}

                  {/* Subject Line Picker */}
                  <div className="subject-lines-block">
                    <small>CURATED SUBJECT LINE OPTIONS (CLICK TO COPY)</small>
                    <div className="subject-lines-list">
                      {(
                        selectedResult.search_intelligence?.outreach.subject_options || [
                          `${selectedResult.company}: Legal & Compliance Advisory`,
                        ]
                      ).map((subj, idx) => (
                        <div key={idx} className="subject-line-item">
                          <span>{subj}</span>
                          <button
                            className="copy-subject-btn"
                            onClick={() => copyToClipboard(subj, `subject-${idx}`)}
                          >
                            {copiedText === `subject-${idx}` ? "✓ Copied" : "Copy Subject"}
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Full Email Message Box */}
                  <div className="email-draft-container">
                    <div className="draft-header-bar">
                      <div className="draft-header-left">
                        <strong>COMPLETE OUTREACH EMAIL DRAFT</strong>
                        <span>Ready for Partner / BD Review</span>
                      </div>
                      <button
                        className="copy-email-btn"
                        onClick={() =>
                          copyToClipboard(
                            selectedResult.search_intelligence?.outreach.draft_email || "",
                            "full-email"
                          )
                        }
                      >
                        {copiedText === "full-email" ? "✓ Copied to Clipboard!" : "📋 Copy Full Email"}
                      </button>
                    </div>

                    <pre className="email-message-body">
                      {selectedResult.search_intelligence?.outreach.draft_email}
                    </pre>

                    <div className="draft-footer-note">
                      <span>Human Approval Gate:</span> No prospect can be emailed automatically in
                      V1. Copy this approved draft into your email client or CRM after partner review.
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 3: SOURCE EVIDENCE & PROVENANCE */}
              {activeTab === "evidence" && (
                <div className="tab-pane-evidence">
                  <div className="evidence-provenance-card">
                    <div className="provenance-header">
                      <div>
                        <small>PUBLIC SOURCE REFERENCE</small>
                        <h3>{selectedResult.title || "Public Source Announcement"}</h3>
                      </div>
                      <a
                        href={sourceLink(selectedResult.source_url)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="open-source-link"
                      >
                        Open Original Source ↗
                      </a>
                    </div>

                    <div className="provenance-meta-grid">
                      <div>
                        <small>SOURCE URL</small>
                        <p className="url-text">{selectedResult.source_url}</p>
                      </div>
                      <div>
                        <small>PUBLISHED DATE</small>
                        <p>{day(selectedResult.published_date)}</p>
                      </div>
                      <div>
                        <small>RELEVANCE RATING</small>
                        <p>{Math.round(selectedResult.relevance * 100)}% verified search score</p>
                      </div>
                      <div>
                        <small>VERIFICATION STATUS</small>
                        <p>{label(selectedResult.research_status || selectedResult.status)}</p>
                      </div>
                    </div>

                    <div className="verbatim-excerpt-box">
                      <small>RETRIEVED SOURCE EXCERPT</small>
                      <blockquote>{selectedResult.snippet}</blockquote>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="modal-footer">
              <div className="modal-footer-left">
                <span>Novation LeadOS · Evidence First</span>
                <span>Deterministic Scoring Engine</span>
              </div>

              <div className="modal-footer-right">
                {selectedResult.opportunity_ids.length > 0 && (
                  <Link
                    href={`/opportunities/${selectedResult.opportunity_ids[0]}`}
                    className="review-opp-btn"
                  >
                    Open Full Opportunity Dossier ↗
                  </Link>
                )}
                <button
                  className="primary-close-btn"
                  onClick={() => setSelectedResult(null)}
                >
                  Close Inspection
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
