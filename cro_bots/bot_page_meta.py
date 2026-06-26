"""Bot 9 — Page Title & Meta Description
Checks: Missing title, too long/short, missing meta description.
CRO framing: Title and description are the ad copy for your page in Google SERP.
Works on: all verticals.
"""
from __future__ import annotations
import re
from .base import AuditParser

TITLE_MIN = 30
TITLE_MAX = 60
DESC_MIN  = 100
DESC_MAX  = 160


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    title = p.title.strip()
    desc  = p.meta_description.strip()

    findings = []
    evidence = []

    # ── Title checks ────────────────────────────────────────────────────────────
    if not title:
        findings.append(
            "Page <title> is missing or empty. "
            "Google will auto-generate a title from page content — usually a bad one. "
            "This is the highest-visibility text in search results."
        )
        evidence.append("<title>: missing")
    elif len(title) > TITLE_MAX:
        findings.append(
            f"Page title is too long ({len(title)} chars — limit: {TITLE_MAX}). "
            f"Google truncates at ~60 chars: '{title[:60]}…' "
            "Truncated titles lose keyword impact and look unprofessional in SERP."
        )
        evidence.append(f"<title> ({len(title)} chars): \"{title[:80]}\"")
    elif len(title) < TITLE_MIN:
        findings.append(
            f"Page title is too short ({len(title)} chars — minimum: {TITLE_MIN}). "
            f"Title: '{title}'. "
            "Short titles waste keyword real estate — add location and service."
        )
        evidence.append(f"<title> ({len(title)} chars): \"{title}\"")

    # ── Meta description checks ─────────────────────────────────────────────────
    if not desc:
        findings.append(
            "Meta description is missing. "
            "Google will pull random page text as the snippet — usually mid-sentence, "
            "with no conversion intent. This is the 'ad copy' below your SERP title."
        )
        evidence.append("meta description: missing")
    elif len(desc) > DESC_MAX:
        findings.append(
            f"Meta description too long ({len(desc)} chars — limit: {DESC_MAX}). "
            "Google truncates with '…' — ensure the CTA appears in first 155 chars."
        )
        evidence.append(f"meta description ({len(desc)} chars): \"{desc[:100]}…\"")
    elif len(desc) < DESC_MIN:
        findings.append(
            f"Meta description too short ({len(desc)} chars — minimum: {DESC_MIN}). "
            "Not enough space for service + location + CTA — expand to 140-160 chars."
        )
        evidence.append(f"meta description ({len(desc)} chars): \"{desc}\"")

    if not findings:
        return None

    return {
        "id": "page_meta",
        "primary_element": "meta",
        "screenshot_mode": "fullpage",
        "visual_evidence": "page <head> source",
        "title": "Page title or meta description missing/misconfigured — SERP click-through damaged",
        "severity": "high" if not title or not desc else "medium",
        "confidence": "confirmed",
        "cro_impact": "Google SERP click-through rate — the first conversion touchpoint",
        "revenue_signal": (
            "Optimised titles and descriptions increase SERP CTR by 5-15% (Backlinko, 2022). "
            "For local businesses, 'near me' searches require location in the title to rank. "
            "A missing description means Google writes your ad for you — always worse."
        ),
        "detection_source": "html",
        "industry_tags": ["all"],
        "fix_effort": "minutes",
        "affected_elements": [
            {"title_length": len(title), "desc_length": len(desc)}
        ],
        "findings": findings,
        "fix": (
            f"Title formula: [Primary Service] in [City] | [Practice Name] (45-60 chars).\n"
            f"Description formula: [Benefit statement]. [Service list]. [CTA] — [Phone/location] (140-160 chars).\n"
            f"Example title: 'Pediatric Dentist in Miami | Children's Dental Specialty'\n"
            f"Example desc: 'Top-rated children's dentist in Miami. Dental cleanings, "
            f"crowns & preventive care. Book a free first visit — (305) 555-1234.'"
        ),
        "evidence": evidence,
    }
