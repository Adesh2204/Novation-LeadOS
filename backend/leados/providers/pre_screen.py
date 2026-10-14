import re
from datetime import UTC, date, datetime
from typing import Any

from leados.config import settings
from leados.engine import detect_signals
from leados.knowledge import knowledge
from leados.providers.models import CandidatePreScreenResult


def pre_screen_candidate(
    document: dict[str, Any],
    threshold: float | None = None,
) -> CandidatePreScreenResult:
    """Evaluate candidate relevance BEFORE invoking Firecrawl.

    Ensures only high-probability leads with clear business signals trigger
    credit-consuming deep scraping.
    """
    min_score = threshold if threshold is not None else settings.min_candidate_relevance_for_firecrawl

    company_info = document.get("company", {})
    comp_name = (company_info.get("name") or document.get("company_hint") or "").strip()
    title = (document.get("source_name") or document.get("title") or "").strip()
    snippet = (document.get("snippet") or "").strip()
    combined_text = f"{title} {snippet}".casefold()

    matched_signals = detect_signals(snippet, knowledge.signals, live=True)
    if not matched_signals:
        matched_signals = detect_signals(combined_text, knowledge.signals, live=True)

    # If exact catalog keywords not hit, evaluate live business signal patterns
    live_signal_patterns = [
        (r"\b(dpo\b|data protection officer|privacy officer|privacy lead|privacy counsel)\b", "DPO_HIRING"),
        (r"\b(dpdp|dpdp act|digital personal data protection)\b", "PRIVACY_CONTROL_PROGRAMME"),
        (r"\b(contract manager|contracts lead|clm|contract lifecycle)\b", "CONTRACT_MANAGER_HIRING"),
        (r"\b(legal ops|legal operations|general counsel|compliance officer)\b", "LEGAL_OPS_HIRING"),
        (r"\b(ai governance|responsible ai|ai policy|generative ai|llm deployment)\b", "AI_PRODUCT_LAUNCH"),
        (r"\b(expansion|opening office|new facility|india entry|bengaluru office)\b", "INDIA_MARKET_ENTRY"),
        (r"\b(acquisition|acquired|merger|cross-border transaction)\b", "ACQUISITION"),
    ]
    if not matched_signals:
        for pattern, sig_id in live_signal_patterns:
            if re.search(pattern, combined_text, re.IGNORECASE):
                if sig_id not in matched_signals and sig_id in knowledge.signals:
                    matched_signals.append(sig_id)

    # Score components:
    # 1. Base signal match: up to 0.50
    signal_score = 0.50 if matched_signals else 0.0

    # 2. Key business event indicator keywords: up to 0.30
    event_keywords = [
        "appoint",
        "named",
        "chief",
        "director",
        "dpo",
        "ciso",
        "general counsel",
        "compliance",
        "contract",
        "dpdp",
        "privacy",
        "expansion",
        "launch",
        "hiring",
        "vacancy",
        "acquisition",
        "head of",
        "officer",
    ]
    keyword_hits = sum(1 for kw in event_keywords if kw in combined_text)
    keyword_score = min(0.30, keyword_hits * 0.10)

    # 3. Company identity clarity: up to 0.15
    identity_score = 0.0
    if comp_name and comp_name != "Discovered Enterprise":
        identity_score += 0.10
    if company_info.get("domain") or document.get("domain"):
        identity_score += 0.05

    # 4. Recency bonus: up to 0.05
    recency_score = 0.0
    pub_date_raw = document.get("published_date")
    if pub_date_raw:
        try:
            if isinstance(pub_date_raw, str):
                p_date = date.fromisoformat(pub_date_raw[:10])
            elif isinstance(pub_date_raw, date):
                p_date = pub_date_raw
            else:
                p_date = None
            if p_date:
                days_ago = (datetime.now(UTC).date() - p_date).days
                if 0 <= days_ago <= 30:
                    recency_score = 0.05
        except Exception:
            pass

    total_score = round(min(1.0, signal_score + keyword_score + identity_score + recency_score), 2)

    # Map matched verticals
    matched_verticals: list[str] = []
    for sid in matched_signals:
        sig_def = knowledge.signals.get(sid)
        if sig_def:
            for vid in sig_def.vertical_ids:
                if vid not in matched_verticals:
                    matched_verticals.append(vid)

    qualifies = total_score >= min_score

    rationale = (
        f"Score {total_score} (signals={len(matched_signals)}, keywords={keyword_hits}, "
        f"identity={identity_score > 0}). {'Qualified' if qualifies else 'Discarded (below threshold)'}"
    )

    return CandidatePreScreenResult(
        company_name=comp_name,
        domain=company_info.get("domain"),
        relevance_score=total_score,
        qualifies=qualifies,
        matched_signals=matched_signals,
        matched_verticals=matched_verticals,
        rationale=rationale,
    )
