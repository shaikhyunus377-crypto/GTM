"""
Bot — Trust Signals
Checks: missing certifications, accreditations, awards, insurance, license badges.
CRO framing: for regulated services (dental, medical, legal), trust badges reduce bounce.
Works on: dental, medical, legal, local_business.
"""
from __future__ import annotations
import re
from .base import AuditParser, dom_y, dom_visible

TRUST_KW = re.compile(
    r"certif|accredit|award|insur|licens|bbb|better\s+business|member|association|"
    r"board\s+certif|ada\b|ama\b|aha\b|jcaho|hipaa|verified|badge|seal",
    re.I,
)


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    dom_els = dom_elements or []

    dom_trust_els = [
        e for e in dom_els
        if TRUST_KW.search(e.get("text") or "")
        and dom_visible(e)
        and dom_y(e) > 0
    ]

    if len(dom_trust_els) >= 2:
        return None

    trust_images = [
        img for img in p.images
        if TRUST_KW.search((img.get("alt") or "") + (img.get("src") or ""))
    ]

    if trust_images:
        return None

    return {
        "id":               "trust_signals",
        "title":            "No trust signals / credential badges detected",
        "severity":         "medium",
        "confidence":       "confirmed",
        "cro_impact":       "Bounce rate + conversion rate for high-consideration decisions",
        "revenue_signal":   "Trust badges increase conversions by 42% for regulated service pages (CXL).",
        "detection_source": "html+dom",
        "industry_tags":    ["dental", "medical", "legal", "local_business"],
        "fix_effort":       "hours",
        "affected_elements": [],
        "findings": [
            "No credential badges, certifications, accreditations, or insurance signals found. "
            "For regulated industries, these are primary conversion trust-builders."
        ],
        "fix": (
            "Add a trust bar below the hero with: board certifications, "
            "association logos (ADA, BBB), insurance accepted, years in practice. "
            "Use image + alt text for each badge so screen readers can announce them."
        ),
        "evidence": [
            f"DOM trust-keyword elements: {len(dom_trust_els)}",
            f"Trust images (alt/src keyword match): {len(trust_images)}",
        ],
    }
