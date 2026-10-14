"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, day, label, type Prospect, type Vertical } from "@/lib/api";

export default function ProspectDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [prospect, setProspect] = useState<Prospect | null>(null);
  const [verticals, setVerticals] = useState<Vertical[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    Promise.all([api<Prospect>(`/prospects/${id}`), api<Vertical[]>("/verticals")])
      .then(([p, v]) => { if (active) { setProspect(p); setVerticals(v); } })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : "Research detail unavailable"); });
    return () => { active = false; };
  }, [id]);
  return <Shell verticals={verticals}><div className="page-content"><Link href="/">← Opportunity desk</Link>
    {error && <div className="error" role="alert">{error}</div>}
    {!prospect && !error && <p>Loading research…</p>}
    {prospect && <>
      <div className="page-heading"><div><div className="eyebrow">LIVE COMPANY RESEARCH</div><h1>{prospect.company}</h1><p>{prospect.industry} · {prospect.country} · {prospect.domain || "Domain unconfirmed"}</p></div><span className="status-pill needs_research">{label(prospect.research_status)}</span></div>
      <section className="research-detail"><h2>Business event and source</h2><p>{prospect.trigger} · {day(prospect.trigger_date)}</p><p>Retrieved {day(prospect.retrieved_at)} · {Math.round(prospect.confidence * 100)}% source confidence · {label(prospect.evidence_status)}</p><p>{prospect.source_title}</p><blockquote>{prospect.source_excerpt}</blockquote><div>{prospect.sources.map(s => <p key={s.id}><a href={s.url} target="_blank" rel="noreferrer">{s.title || "Public evidence"} ↗</a></p>)}</div></section>
      <section className="research-detail"><h2>Possible service relevance</h2><p>{prospect.vertical} · {prospect.recommended_service}</p><p>{prospect.why_now}</p><h3>Unconfirmed assumptions</h3><p>{prospect.uncertainty}</p><h3>Possible buyer roles</h3><p>{prospect.buyer_roles.join(" / ")}</p><p>Recommended roles only. No named person or verified contact has been retrieved.</p><h3>Next action</h3><p>{prospect.next_action}</p><p>This research has no opportunity score. Qualified opportunities must pass the existing evidence and commercial gates. Email delivery is disabled.</p></section>
    </>}
  </div></Shell>;
}
