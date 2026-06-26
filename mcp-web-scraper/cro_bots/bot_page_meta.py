"""
Bot 7 — Page Title / Meta Description
Checks: missing title, title too long (>60), missing meta description, description too long (>155).
CRO framing: title + description = the paid ad you don't pay for in SERP.
Works on: all verticals.
"""
from __future__ import annotations
from .base import AuditParser


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    title = p.title_text.strip()
    desc  = p.meta_desc.strip()

    findings = []
    evidence  = []

    if not title:
        findings.append("Page <title> is missing — SERP will show URL instead.")
        evidence.append("title: (missing)")
    elif len(title) > 60:
        findings.append(
            f"Title too long ({len(title)} chars) — Google truncates at ~60 chars, "
            "cutting off the location/USP. "
            f"Current: \"{title[:70]}…\""
        )
        evidence.append(f"Title ({len(title)} chars): \"{title[:70]}\"")

    if not desc:
        findings.append(
            "Meta description is missing — Google generates its own snippet, "
            "often from body text that doesn't include a CTA."
        )
        evidence.append("meta description: (missing)")
    elif len(desc) > 155:
        findings.append(
            f"Meta description too long ({len(desc)} chars) — truncated in SERP at ~155 chars."
        )
        evidence.append(f"Description ({len(desc)} chars): \"{desc[:80]}…\"")

    if not findings:
        return None

    return {
        "id":               "page_meta",
        "title":            "Page title or meta description is missing or too long",
        "severity":         "medium",
        "confidence":       "confirmed",
        "cro_impact":       "SERP click-through rate",
        "revenue_signal":   "Optimized title+description improves organic CTR by 5-15%.",
        "detection_source": "html",
        "industry_tags":    ["all"],
        "fix_effort":       "minutes",
        "affected_elements": [],
        "findings":         findings,
        "fix": (
            "Title: [Primary Service] | [Location] | [Brand] — keep under 60 chars. "
            "Description: lead with benefit + CTA — keep under 155 chars. "
            "Include your primary keyword naturally in both."
        ),
        "evidence": evidence,
    }
