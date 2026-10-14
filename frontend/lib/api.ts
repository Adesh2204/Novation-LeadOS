export type Vertical = { id: string; name: string; description: string; services: string[]; buyer_roles: string[] };
export type Claim = { type: string; text: string; evidence_ids: string[] };
export type Evidence = { id: string; source_url: string; source_name: string; source_type: string; published_date: string | null; retrieved_at: string; snippet: string; confidence: number; content_hash: string; assertion_type: string; company_match: boolean; conflict: boolean };
export type Review = { id: string; reviewer: string; decision: string; notes: string; created_at: string };
export type Feedback = { id: string; status: string; reason: string | null; notes: string; buyer_role: string | null; score_snapshot: number; score_version: string; created_at: string };
export type Opportunity = {
  record_origin: string; qualification: Qualification; score_inputs: Record<string, unknown>;
  id: string; company_id: string; company: string; sector: string; country: string; location: string;
  vertical_id: string; vertical_name: string; trigger: string; trigger_date: string | null; age_days: number | null;
  facts: Claim[]; allegations: Claim[]; inferences: Claim[]; commercial_thesis: string; evidence: Evidence[];
  novation_service: string; why_now: string; decision_maker_roles: string[];
  score_components: Record<string, { points: number; maximum: number; rationale: string }>;
  score: number; score_band: string; confidence: number; audit_status: string; audit_reasons: string[];
  recommended_action: string; outreach_angle: string; human_status: string;
  score_version: string; knowledge_version: string; signal_version: string; created_at: string;
  draft: { subjects: string[]; body: string; verified_fact_ids: string[] } | null;
  reviews: Review[]; feedback: Feedback[]; contact_history: { status: string; created_at: string; channel: string }[];
  suppressed: boolean; suppression_flags: { do_not_contact: boolean; opted_out: boolean; bounced: boolean }; email_send_enabled: boolean;
};
export type Metrics = { data_mode: string; unqualified_live_signals: number; companies: number; opportunities: number; hot: number; pending_review: number; needs_research: number; average_score: number; pipeline_runs: number; duplicates_avoided: number; errors: number; by_vertical: Record<string, number> };
export type Run = { run_id: string; status: string; stage: string; metrics: { opportunities_created: number; duplicates_avoided: number; errors: number }; error: string | null; duration_ms: number };
export type LiveDiscoveryEstimate = {
  company_limit: number;
  configured_query_limit: number;
  queries_to_run: number;
  max_exa_results: number;
  estimated_candidates: number;
  max_firecrawl_companies: number;
  max_firecrawl_pages: number;
  worst_case_exa_calls: number;
  worst_case_firecrawl_calls: number;
  dry_run: boolean;
};
export type LiveDiscoverySummary = {
  new_companies: number;
  known_companies: number;
  new_source_documents: number;
  prospects_created: number;
  relevant_prospects: number;
  next_query_offset: number;
  query_ids: string[];
  dedup: Record<string, number>;
  firecrawl_skipped: number;
  firecrawl_verified_pages: number;
  opportunities_updated: number;
  qualification_counts: Record<string, number>;
  run_id: string;
  status: string;
  data_mode: string;
  exa_queries: number;
  exa_results: number;
  exa_unique_companies: number;
  source_supported_companies: number;
  exa_cache_hits: number;
  candidates_screened: number;
  candidates_passed_prescreen: number;
  candidates_discarded_low_relevance: number;
  firecrawl_requests: number;
  firecrawl_pages: number;
  firecrawl_cache_hits: number;
  firecrawl_skipped_low_relevance: number;
  firecrawl_skipped_recent_cache: number;
  firecrawl_errors: number;
  opportunities_created: number;
  duplicates_avoided: number;
  needs_research: number;
  duration_ms: number;
  error: string | null;
  dry_run: boolean;
};

export type SearchFactorItem = {
  name: string;
  weight: number;
  score: number;
  status: string;
  detail: string;
};

export type SearchIntelligence = {
  company: string;
  domain?: string;
  sector?: string;
  country?: string;
  icp_profile: {
    code: string;
    name: string;
    summary: string;
    match_reasons: string[];
    matched_via: string;
  };
  why_searched: string;
  total_factor_score: number;
  score_band: string;
  factors: {
    identifiable_need: SearchFactorItem;
    icp_fit: SearchFactorItem;
    trigger_strength: SearchFactorItem;
    trigger_recency: SearchFactorItem;
    mandate_value: SearchFactorItem;
    buyer_reachability: SearchFactorItem;
    expertise_match: SearchFactorItem;
    evidence_quality: SearchFactorItem;
  };
  outreach: {
    target_roles: string[];
    target_email?: string;
    contacts?: { person_name: string; role: string; contact_email: string; contact_status: string }[];
    subject_options: string[];
    draft_email: string;
    outreach_angle: string;
    recommended_service: string;
    vertical_name: string;
  };
  trigger_summary: string;
  published_date?: string | null;
  source_url?: string;
};

export type OpportunitySummary = Pick<Opportunity, "id" | "company_id" | "company" | "sector" | "country" | "vertical_id" | "vertical_name" | "trigger" | "trigger_date" | "age_days" | "novation_service" | "score" | "score_band" | "confidence" | "audit_status" | "human_status" | "created_at" | "suppressed">;
export type Qualification = { status: string; reason?: string; organization_role: string; service_demand: boolean; commercial_fit: string; method: string; version: string; evidence_confidence: number; signal_confidence: number; llm_review: string; human_review: string; };
export type DiscoveryResult = { identity_status?: string; research_status?: string; prospect?: { id: string; trigger: string; vertical: string; recommended_service: string; research_status: string }; record_origin?: string; qualification?: Qualification; firecrawl_decision?: string; decision_history_missing?: boolean; id: string; company: string; source_url: string; title: string; published_date: string | null; snippet: string; relevance: number; status: string; reason: string; opportunity_ids: string[]; other_sources?: { title?: string; source_url: string; published_date?: string | null }[]; search_intelligence?: SearchIntelligence; search_date?: string };
export type DiscoveryJob = { stop_requested?: boolean; job_id: string; status: string; stage: string; created_at: string; updated_at: string; summary: (LiveDiscoverySummary & { queries_completed: number; queries_total: number; candidates_processed: number; candidates_screened: number; stage: string; results: DiscoveryResult[] }) | null; error: string | null; sheets_synced: boolean };
export type Prospect = { id: string; record_type: string; company: string; industry: string; country: string; domain: string | null; trigger: string; trigger_date: string | null; vertical_id: string; vertical: string; recommended_service: string; why_now: string; research_status: string; confidence: number; evidence_status: string; source: string; source_title: string; source_excerpt: string; retrieved_at: string; buyer_roles: string[]; contact_status: string; uncertainty: string; next_action: string; sources: { id: string; url: string; title: string }[] };
export type LiveReadiness = { ready: boolean; enabled: boolean; stop_active: boolean; email_disabled: boolean; blockers: string[]; remaining_daily_reservations: { exa: number; firecrawl: number }; limits: { queries: number; companies: number; pages: number; results_per_query: number } };
export type DashboardState = { prospects: Prospect[]; verticals: Vertical[]; opportunities: OpportunitySummary[]; metrics: Metrics; discovery_results: DiscoveryResult[] };

const BASE = process.env.NEXT_PUBLIC_API_URL || "/api/backend";
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const signal = AbortSignal.timeout(path === "/pipeline/discover/live" ? 480000 : 45000);
  const response = await fetch(BASE + path, body === undefined ? { cache: "no-store", signal } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status}). Check the supplied fields.`);
  }
  return response.json();
}
export function label(value: string) { return value.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase()); }
export function day(value: string | null) { return value ? new Date(value + (value.length === 10 ? "T00:00:00" : "")).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "Date unavailable"; }

// Known historical run result IDs from Live Discovery runs
const RUN_12_OCT_IDS = new Set([
  "00a172930cb9260c0ed751ce", // NABARD
  "3d89e55446325b22ba6e114b", // IPPB
  "398e53c892ae97fbe6c1518b", // SBI Payments
  "b5b6e033d7b832503e64f772", // NABARD
  "97411d808a72ebfcb29275c4", // LIC
  "ceab1d5ecc31622d2c50770d", // SBISG
  "7927d52bbf6beedea127d85c", // Indian Bank
  "c239e5656d28acaef4ec371e", // NICL
  "2ceff4962660d30122eac1bc", // BGSSL
  "758b2aadc6b9cce9b55152a8", // CSC SPV
]);

const RUN_09_OCT_VPPL_IDS = new Set([
  "b2f3a958d8257751c65537cd", // VPPL
  "9f4d0d1f04e3b76594867ac6", // SBISG
  "93e2efff469756cc65cd8bc6", // NTPC
  "713f6889bb296cda22dcb238", // ICDM
  "a9974ef9b3ab4d5ea21fe7cd", // NBCC
  "54f0b1cf9f272bcd64f628cd", // Non-profit
  "3554b7f0f0f27a535ed31a2a", // BGSSL
  "f34988955968772ab48c221a", // SMFCL
  "7762abd4786f2488128009f1", // Deloitte
  "5ab8c39fdd85a608647ce01a", // KPL
]);

export function formatSearchDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "Date unavailable";
  try {
    const d = new Date(isoDate.length === 10 ? isoDate + "T00:00:00" : isoDate);
    if (isNaN(d.getTime())) return isoDate;
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  } catch {
    return isoDate;
  }
}

export function resolveSearchDate(result: DiscoveryResult, liveJobDate?: string | null): string {
  if (result.search_date) return result.search_date;
  if (RUN_12_OCT_IDS.has(result.id)) return "2026-10-12";
  if (RUN_09_OCT_VPPL_IDS.has(result.id)) return "2026-10-09";

  const c = (result.company || "").toLowerCase();
  if (
    c.includes("vadhvan") || c.includes("vppl") || c.includes("ntpc") ||
    c.includes("nbcc") || c.includes("smfcl") || c.includes("deloitte") ||
    c.includes("corporate data") || c.includes("kpl") || c.includes("union bank") ||
    c.includes("oil india") || c.includes("nsdc") || c.includes("bank of india")
  ) {
    return "2026-10-09";
  }
  if (c.includes("sbi card") || c.includes("protean")) {
    return "2026-10-08";
  }
  if (liveJobDate) return liveJobDate.slice(0, 10);
  return "2026-10-14";
}
