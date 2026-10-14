"""Reject unmistakable document headings as organisation identities."""

import re


def document_heading(name: str) -> bool:
    return bool(
        re.match(
            r"^\s*(?:\[pdf\]\s*)?(?:request\s+for\s+(?:proposal|empanelment)|rfp\b|tender\s+(?:notice|document)|(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}\s*$)",
            name,
            re.IGNORECASE,
        )
    )


def company_dedup_key(name: str) -> str:
    n = (name or "").lower().strip()
    if not n:
        return ""
    if "baroda global shared" in n or "bgssl" in n:
        return "bgssl"
    if "sbi-sg" in n or "sbisg" in n:
        return "sbi-sg"
    if "nabard" in n:
        return "nabard"
    if "india post payments" in n or "ippb" in n:
        return "ippb"
    if "life insurance corporation" in n or re.search(r"\blic\b", n):
        return "lic"
    if "sbi payment" in n:
        return "sbi payments"
    if "vadhvan port" in n or "vppl" in n:
        return "vppl"
    if "deloitte" in n:
        return "deloitte"
    if "nbcc" in n:
        return "nbcc"
    if "ntpc" in n:
        return "ntpc"
    if "csc e-governance" in n or "csc spv" in n:
        return "csc"
    if "union bank" in n:
        return "union bank"
    if "bank of india" in n:
        return "bank of india"
    if "oil india" in n:
        return "oil india"
    if "indian bank" in n:
        return "indian bank"
    if "national insurance" in n or "nicl" in n:
        return "nicl"
    if "national skill development" in n or "nsdc" in n:
        return "nsdc"

    n = re.sub(r"\s*\(.*?\)", "", n)
    n = re.sub(r"[\.,]", "", n)
    n = re.sub(r"\b(pvt|ltd|limited|private|llp|spv|inc|corp|corporation)\b", "", n)
    return " ".join(n.split())

