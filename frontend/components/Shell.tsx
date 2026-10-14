import Link from "next/link";
import type { Vertical } from "@/lib/api";

export function Mark() {
  return <svg width="30" height="30" viewBox="0 0 30 30" fill="none" aria-hidden="true"><path d="M4 25V5h6l10 15V5h6v20h-6L10 10v15H4Z" fill="currentColor"/></svg>;
}
export default function Shell({ children, verticals = [], selected = "", onSelect }: {
  children: React.ReactNode; verticals?: Vertical[]; selected?: string; onSelect?: (id: string) => void;
}) {
  return <div className="app-shell">
    <aside className="sidebar">
      <Link href="/" className="brand"><Mark/><div>novation<span>STRATEGY</span></div></Link>
      <div className="workspace-label">INTELLIGENCE WORKSPACE</div>
      <Link href="/" className="nav-item active"><span>◫</span> Opportunity review <span className="nav-arrow">↗</span></Link>
      <div className="workspace-label vertical-heading">NOVATION VERTICALS</div>
      <nav aria-label="Vertical filters">{verticals.map((v, i) => <button key={v.id} className={`vertical-nav ${selected === v.id ? "selected" : ""}`} onClick={() => onSelect?.(selected === v.id ? "" : v.id)}><span className="nav-number">{String(i + 1).padStart(2, "0")}</span>{v.name}</button>)}</nav>
      <div className="sidebar-footer"><div className="mode-indicator"><span/> EVIDENCE FIRST</div><p>Live research & mock discovery.<br/>Every opportunity starts with evidence.</p><div className="version">LEADOS <span>v0.1</span></div></div>
    </aside>
    <main className="main"><header className="topbar"><span>LeadOS <span className="slash">/</span> Business development</span><div className="topbar-right"><span className="safety-pill">◉ &nbsp; Email delivery disabled</span><span className="avatar">NS</span></div></header>{children}</main>
  </div>;
}
