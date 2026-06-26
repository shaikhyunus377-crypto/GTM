"""
Bot 5 — OG / Twitter Social Meta
Checks: missing og:title, og:description, og:image, twitter:card.
CRO framing: social shares without OG tags show blank previews — kills referral CTR.
Works on: all verticals.
"""
from __future__ import annotations
from .base import AuditParser

REQUIRED_OG = {"og:title", "og:description", "og:image"}
REQUIRED_TW = {"twitter:card"}


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    og_props = {t["property"] for t in p.og_tags}
    tw_names = {t["name"] for t in p.twitter_tags}

    missing_og = REQUIRED_OG - og_props
    missing_tw = REQUIRED_TW - tw_names

    if not missing_og and not missing_tw:
        return None

    findings = []
    evidence  = []

    if missing_og:
        findings.append(
            f"Missing OG tags: {sorted(missing_og)}. "
            "Social shares (Facebook, LinkedIn, WhatsApp) will show blank previews."
        )
        evidence += [f"Missing: {t}" for t in sorted(missing_og)]

    if missing_tw:
        findings.append(
            "Missing twitter:card — Twitter/X shares won't render a rich card."
        )
        evidence.append("Missing: twitter:card")

    return {
        "id":               "og_social_meta",
        "title":            "OG / Twitter social meta tags missing",
        "severity":         "medium",
        "confidence":       "confirmed",
        "cro_impact":       "Social sharing CTR + referral traffic quality",
        "revenue_signal":   "Pages with complete OG tags get 3× more click-throughs from social shares.",
        "detection_source": "html",
        "industry_tags":    ["all"],
        "fix_effort":       "minutes",
        "affected_elements": [],
        "findings":         findings,
        "fix": (
            "Add to <head>: og:title, og:description (≤155 chars), og:image (1200×630px), "
            "og:url, og:type. Add twitter:card='summary_large_image', twitter:title, twitter:description."
        ),
        "evidence": evidence,
    }
