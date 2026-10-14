"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import StructuredEvidence from "@/components/StructuredEvidence";
import { api, day, label, type Opportunity } from "@/lib/api";

const feedbackStatuses = ["Not Relevant", "Contacted", "No Response", "Responded", "Meeting", "Proposal", "Engaged", "Won", "Lost"];
const reasons = ["Wrong Company", "Wrong Timing", "Wrong Service", "No Budget", "No Relationship", "Conflict", "Existing Counsel", "No Need", "Other"];

export default function OpportunityDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [lead, setLead] = useState<Opportunity | null>(null);
  const [contacts, setContacts] = useState<{ id: string; person_name: string; role: string; contact_email: string; contact_status: string }[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedbackStatus, setFeedbackStatus] = useState("Not Relevant");
  const [reason, setReason] = useState("");
  const [feedbackNotes, setFeedbackNotes] = useState("");
  const [buyerRole, setBuyerRole] = useState("");
  const load = useCallback(async () => { try { setLead(await api<Opportunity>(`/opportunities/${id}`)); setError(""); } catch (e) { setError(e instanceof Error ? e.message : "Unable to load opportunity"); } }, [id]);
  useEffect(() => {
    let active = true;
    api<Opportunity>(`/opportunities/${id}`).then(o => { if (active) setLead(o); })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : "Unable to load opportunity"); });
    return () => { active = false; };
  }, [id]);
  useEffect(() => {
    let active = true;
    api<typeof contacts>(`/opportunities/${id}/contacts`).then(rows => { if (active) setContacts(rows); }).catch(() => {});
    return () => { active = false; };
  }, [id]);
  async function enrich() {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api<{ status: string; contacts: typeof contacts; error?: string }>(`/opportunities/${id}/contacts/enrich`, {});
      setContacts(result.contacts);
      setMessage(result.error ? `Contacts found; verification needs attention: ${result.error}` : `${result.contacts.length} buyer contact(s) found. No email was sent.`);
    } catch (e) { setError(e instanceof Error ? e.message : "Contact lookup failed"); }
    finally { setBusy(false); }
  }
  async function syncCRM() {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api<{ status: string; company_id: string }>(`/opportunities/${id}/crm/sync`, {});
      setMessage(`HubSpot: ${label(result.status)}. No email was sent.`);
    } catch (e) { setError(e instanceof Error ? e.message : "HubSpot sync failed"); }
    finally { setBusy(false); }
  }
  const synthetic = lead?.record_origin === "MOCK";
  const liveQualified = lead?.record_origin === "LIVE" && (lead.qualification?.status === "QUALIFIED_SIGNAL" || Boolean(lead.qualification?.service_demand));
  const canEnrich = !!lead && liveQualified && (lead.audit_status === "VERIFIED" || Boolean(lead.qualification?.service_demand)) && lead.score >= 65 && !lead.suppressed;
  async function decide(decision: string) {
    setBusy(true); setError(""); setMessage("");
    try { setLead(await api<Opportunity>(`/opportunities/${id}/${decision}`, { reviewer, notes })); setMessage("Review saved. No email was sent."); }
    catch (e) { setError(e instanceof Error ? e.message : "Review failed"); }
    finally { setBusy(false); }
  }
  async function saveFeedback() {
    setBusy(true); setError(""); setMessage("");
    try { setLead(await api<Opportunity>(`/opportunities/${id}/feedback`, { status: feedbackStatus, reason: reason || null, notes: feedbackNotes, buyer_role: buyerRole || null })); setFeedbackNotes(""); setMessage("Feedback added to the history. The original score is preserved."); }
    catch (e) { setError(e instanceof Error ? e.message : "Feedback failed"); }
    finally { setBusy(false); }
  }
  async function toggleSuppression() {
    if (!lead) return;
    setBusy(true);
    try { await api(`/companies/${lead.company_id}/suppression`, { do_not_contact: !lead.suppression_flags.do_not_contact, reason: "Updated during human review" }); await load(); setMessage("Company contact preference saved."); }
    catch (e) { setError(e instanceof Error ? e.message : "Preference failed"); }
    finally { setBusy(false); }
  }
  return <Shell><div className="page-content detail-content"><Link href="/" className="back-link">← Back to opportunities</Link>
    {error && <div className="error" role="alert">{error}</div>}{message && <div className="run-result" role="status">{message}</div>}
    {!lead && !error && <div className="empty-state">Loading evidence and review history…</div>}
    {lead && <>
      <div className="detail-heading"><div><div className="eyebrow">OPPORTUNITY BRIEF · {synthetic ? "DEVELOPMENT FIXTURE" : lead.record_origin === "LIVE" ? "LIVE RESEARCH" : "ORIGIN UNRESOLVED"}</div><h1>{lead.company}<span className="heading-dot">.</span></h1><p>{lead.sector} <span>·</span> {lead.country} <span>·</span> {lead.location}</p><div className="detail-tags"><span className="vertical-pill">{lead.vertical_name}</span><span className={`status-pill ${lead.human_status.toLowerCase()}`}><span/>{label(lead.human_status)}</span></div></div><div className="detail-score"><strong>{lead.score}<span>/100</span></strong><span>{lead.score_band} · {lead.recommended_action}</span><small>Deterministic score v{lead.score_version}</small></div></div>
      {!synthetic && <div className="audit-banner attention"><strong>Commercial qualification: {label(lead.qualification?.status || "NEEDS_RESEARCH")}</strong><span>{lead.qualification?.reason || "Buyer-side demand requires further evidence."}</span><p>{lead.qualification?.method || "Not evaluated"} · Human review required</p></div>}
      <div className={`audit-banner ${lead.audit_status === "VERIFIED" ? "verified" : "attention"}`}><strong>{lead.audit_status === "VERIFIED" ? "✓ Evidence verified" : "◎ Evidence needs attention"}</strong><span>{Math.round(lead.confidence * 100)}% confidence · {lead.evidence.length} supporting source{lead.evidence.length !== 1 && "s"}</span>{lead.audit_reasons.map(r => <p key={r}>{r}</p>)}</div>
      <div className="detail-grid"><div className="detail-main">
        <section className="brief-section"><div className="section-label">01 / THE BUSINESS EVENT</div><h2>What happened</h2><p className="large-copy">{lead.trigger}</p><span className="muted">Published {day(lead.trigger_date)} · {lead.age_days === null ? "Age unknown" : `${lead.age_days} days ago`}</span><h3>Why it matters</h3>{lead.inferences.map((c, i) => <p key={i}>{c.text}</p>)}<span className="inference-note">Interpretation by LeadOS. Validate the company’s actual need during review.</span></section>
        <section className="brief-section">
          <div className="section-label">02 / EVIDENCE & PROVENANCE</div>
          <h2>Supporting evidence & procurement intelligence</h2>

          {/* Executive Synthesis: Commercial Inferences & Core Factual Anchors */}
          <div className="evidence-synthesis-grid">
            <div className="synthesis-card inferences-card">
              <div className="synthesis-header">
                <span className="synthesis-badge">💡 COMMERCIAL INFERENCES</span>
                <span className="synthesis-subtitle">LeadOS Strategic Analysis</span>
              </div>
              <div className="inferences-list">
                {lead.inferences.map((c, i) => (
                  <div key={i} className="inference-item">
                    <span className="inference-number">{i + 1}</span>
                    <p>{c.text}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="synthesis-card facts-summary-card">
              <div className="synthesis-header">
                <span className="synthesis-badge factual">✓ VERIFIED FACTUAL BASIS</span>
                <span className="synthesis-subtitle">Core Commercial Anchors</span>
              </div>
              <ul className="facts-summary-list">
                <li><strong>Target Entity:</strong> {lead.company} ({lead.sector}, {lead.location || lead.country})</li>
                <li><strong>Public Trigger:</strong> {lead.trigger}</li>
                <li><strong>Recommended Service:</strong> {lead.novation_service} ({lead.vertical_name})</li>
                <li><strong>Audit Status:</strong> {lead.audit_status === "VERIFIED" ? "Verified qualified requirement" : "Needs research"} · {Math.round(lead.confidence * 100)}% confidence</li>
              </ul>
            </div>
          </div>

          {lead.allegations.length > 0 && (
            <div className="allegation-box">
              <h3>Allegations · unproven</h3>
              {lead.allegations.map((c, i) => <p key={i}>{c.text}</p>)}
            </div>
          )}

          {/* Structured Document Presentation for each piece of evidence */}
          <div className="structured-documents-list">
            {lead.evidence.map(e => (
              <StructuredEvidence
                key={e.id}
                snippet={e.snippet}
                sourceName={e.source_name}
                sourceType={e.source_type}
                sourceUrl={e.source_url}
                confidence={e.confidence}
                publishedDate={e.published_date}
                retrievedAt={e.retrieved_at}
                contentHash={e.content_hash}
                companyName={lead.company}
              />
            ))}
          </div>
        </section>
        <section className="brief-section"><div className="section-label">03 / THE COMMERCIAL THESIS</div><h2>Why Novation fits</h2><p>{lead.commercial_thesis}</p><div className="service-callout"><span>RECOMMENDED SERVICE</span><h3>{lead.novation_service}</h3><p>{lead.vertical_name}</p></div><h3>Why now</h3><p>{lead.why_now}</p><h3>Likely buyer roles</h3><div className="role-list">{lead.decision_maker_roles.map(role => <span key={role}>{role}</span>)}</div><div className="buyer-contacts">{contacts.map(contact => <article key={contact.id}><strong>{contact.person_name}</strong><p>{contact.role} · {label(contact.contact_status)}</p><span>{contact.contact_email}</span></article>)}</div><p className="muted">{synthetic ? "Mock leads use role suggestions. Live contacts require a verified company domain and a strong opportunity." : "Find up to three current buyer contacts in ContactOut and verify their work emails with Snov.io. Provider credits may be used."}</p><button className="secondary" disabled={busy || !canEnrich || contacts.length > 0} onClick={enrich}>{contacts.length ? "Contacts saved" : "Find buyer contacts"}</button></section>
        <section className="brief-section"><div className="section-label">04 / OUTREACH PREPARATION</div><h2>A considered first conversation</h2><p>{lead.outreach_angle}</p>{lead.draft ? <><h3>Subject ideas</h3>{lead.draft.subjects.map(s => <p className="subject-line" key={s}>{s}</p>)}<h3>Draft message</h3><pre className="draft-message">{lead.draft.body}</pre></> : <p className="allegation-box">A draft will be prepared only with verified factual evidence. Resolve the research issues first.</p>}<button disabled className="disabled-send">Email delivery disabled</button><div className="crm-action"><button className="secondary" disabled={busy || !canEnrich || lead.human_status !== "APPROVED"} onClick={syncCRM}>Sync approved lead to HubSpot</button><p className="muted">Approval is required before creating or linking a company in CRM.</p></div></section>
        <section className="brief-section"><div className="section-label">05 / OUTCOME LEARNING</div><h2>Feedback</h2><p className="muted">Record what happened. Status and reason are stored separately.</p><div className="feedback-form"><label>Outcome<select value={feedbackStatus} onChange={e => setFeedbackStatus(e.target.value)}>{feedbackStatuses.map(s => <option key={s}>{s}</option>)}</select></label><label>Reason<select value={reason} onChange={e => setReason(e.target.value)}><option value="">No reason selected</option>{reasons.map(s => <option key={s}>{s}</option>)}</select></label><label>Buyer role<select value={buyerRole} onChange={e => setBuyerRole(e.target.value)}><option value="">Not recorded</option>{lead.decision_maker_roles.map(s => <option key={s}>{s}</option>)}</select></label><label className="full-width">Notes<textarea value={feedbackNotes} onChange={e => setFeedbackNotes(e.target.value)} placeholder="Context from your conversation…"/></label></div><button className="secondary" disabled={busy} onClick={saveFeedback}>Save feedback</button><div className="history">{lead.feedback.map(f => <article key={f.id}><strong>{f.status}</strong><span>{f.reason || "No reason recorded"} · {day(f.created_at)}</span><p>{f.notes}</p><small>Original score: {f.score_snapshot} · score v{f.score_version}{f.buyer_role && ` · ${f.buyer_role}`}</small></article>)}</div></section>
      </div><aside className="detail-aside"><section className="review-card"><div className="section-label">YOUR DECISION</div><h2>Human review</h2><p>Approval records readiness for eventual outreach. It sends no email.</p><label>Reviewer name<input value={reviewer} onChange={e => setReviewer(e.target.value)} placeholder="Your name" maxLength={150}/></label><label>Review notes<textarea value={notes} onChange={e => setNotes(e.target.value)} placeholder="Why is this relevant?" maxLength={5000}/></label><button className="primary" disabled={busy || !reviewer.trim() || (!synthetic && !liveQualified) || (lead.audit_status !== "VERIFIED" && !lead.qualification?.service_demand) || lead.suppressed} onClick={() => decide("approve")}>✓ Approve for outreach</button><button className="secondary" disabled={busy || !reviewer.trim()} onClick={() => decide("research")}>Need more research</button><button className="reject-button" disabled={busy || !reviewer.trim()} onClick={() => decide("reject")}>Reject opportunity</button><div className="contact-status"><strong>{lead.suppressed ? "Company suppressed" : "Contact safeguards"}</strong><p>{lead.contact_history.length ? `${lead.contact_history.length} previous contact event(s) recorded.` : "No previous contact recorded."}</p><button className="text-button" disabled={busy} onClick={toggleSuppression}>{lead.suppression_flags.do_not_contact ? "Remove do-not-contact flag" : "Mark company do not contact"}</button></div></section>
        <section className="score-card"><div className="section-label">TRANSPARENT BY DESIGN</div><h2>Score breakdown</h2>{Object.entries(lead.score_components).map(([name, part]) => <div className="score-part" key={name} title={part.rationale}><div><span>{label(name)}</span><strong>{part.points}<small>/{part.maximum}</small></strong></div><div className="score-track"><span style={{ width: `${part.points / part.maximum * 100}%` }}/></div><p>{part.rationale}</p></div>)}<div className="score-total"><strong>Total</strong><strong>{lead.score}/100</strong></div><small>Knowledge v{lead.knowledge_version}<br/>Signal v{lead.signal_version}</small>{lead.audit_status !== "VERIFIED" && <p className="muted">The numerical score is preserved. Evidence review prevents a HOT classification.</p>}</section>
        <section className="review-history"><h3>Review history</h3>{lead.reviews.length ? lead.reviews.map(r => <article key={r.id}><strong>{label(r.decision)}</strong><span>{r.reviewer} · {day(r.created_at)}</span><p>{r.notes}</p></article>) : <p className="muted">Awaiting the first human decision.</p>}</section>
      </aside></div>
    </>}
  </div></Shell>;
}
