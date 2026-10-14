"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Provider = { id: string; label: string; status: string; error?: string; checked_at?: string; optional?: boolean };
type Status = { providers: Provider[] };
const labels: Record<string, string> = { connected: "Connected", configured: "Ready to check", missing: "Key needed", needs_attention: "Needs attention", disabled: "Disabled", not_connected: "Not connected" };

export default function Connections() {
  const [status, setStatus] = useState<Status | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api<Status>("/providers/status").then(data => { if (active) setStatus(data); }).catch(() => { if (active) setError("Connection status is unavailable."); });
    return () => { active = false; };
  }, []);
  async function check() {
    setChecking(true); setError("");
    try { setStatus(await api<Status>("/providers/check", {})); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to check connections."); }
    finally { setChecking(false); }
  }
  return <section className="connections" aria-label="Service connections">
    <div className="connections-heading"><div><h3>Service connections</h3><p>Research, buyer contacts and CRM · delivery stays disabled</p></div><button className="secondary" disabled={checking} onClick={check}>{checking ? "Checking…" : "Check connections"}</button></div>
    {error && <p role="alert" className="connection-error">{error}</p>}
    <div className="connection-grid">{status?.providers.map(provider => <div className={`connection-item ${provider.status}`} key={provider.id} title={provider.error || (provider.checked_at ? `Last checked: ${new Date(provider.checked_at).toLocaleString()}` : provider.id === "exa" ? "Verified when discovery runs; this check does not spend search credits." : "Check to verify access.")}><span className="connection-dot"/><div><strong>{provider.label}</strong><span>{labels[provider.status] || provider.status}{provider.optional ? " · optional" : ""}</span></div></div>)}</div>
  </section>;
}
