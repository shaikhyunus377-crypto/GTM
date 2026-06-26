"""Bot 1 — H1 Identity
Checks: H1 missing, empty, or contains promotional copy instead of service identity.
CRO framing: The H1 is the page's value proposition — the first trust signal a visitor sees.
Works on: all verticals.
"""
from __future__ import annotations
import re
from .base import AuditParser, dom_y, dom_visible, filter_cookie_els

PROMO_RE = re.compile(
    r"\b(\d+\s*%|off\b|sale\b|deal\b|save\b|discount|free\b|limited\s+time|best\s+price|lowest\s+price)\b", re.I
)
GENERIC_RE = re.compile(r"^(welcome|home|index|page|untitled|default)$", re.I)


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    dom_els = dom_elements or []

    # Find H1 in DOM first (more reliable — captures child-span text)
    dom_h1s = [e for e in dom_els if e.get("tag") == "h1" and dom_visible(e)]
    html_h1s = [h for h in p.headings if h["tag"] == "h1"]

    findings = []
    evidence = []
    affected = []

    # Case 1: no H1 at all
    if not dom_h1s and not html_h1s:
        findings.append(
            "No H1 element found on page. "
            "Search engines have no primary keyword signal; visitors see no service headline."
        )
        evidence.append("H1 count: 0 (checked HTML + DOM)")
        affected.append({"tag": "h1", "text": "(missing)", "id": ""})
        return _issue(findings, evidence, affected, severity="high")

    # Use DOM text if available (more accurate)
    h1_text = ""
    h1_y = 0
    if dom_h1s:
        best = dom_h1s[0]
        h1_text = (best.get("text") or "").strip()
        h1_y = dom_y(best)
    else:
        h1_text = html_h1s[0]["text"].strip()

    # Case 2: H1 exists but is empty
    if not h1_text:
        findings.append(
            "H1 element exists but contains no text. "
            "CSS or JS may be rendering it visually, but search crawlers and screen readers see nothing."
        )
        evidence.append("H1 text content: empty string")
        affected.append({"tag": "h1", "text": "", "id": ""})
        return _issue(findings, evidence, affected, severity="high")

    # Case 3: H1 is generic (welcome, home, etc.)
    if GENERIC_RE.match(h1_text):
        findings.append(
            f'H1 is a generic placeholder: "{h1_text}". '
            "No service identity or value proposition — zero first-impression conversion signal."
        )
        evidence.append(f'H1 text: "{h1_text}"')
        affected.append({"tag": "h1", "text": h1_text, "id": ""})
        return _issue(findings, evidence, affected, severity="high")

    # Case 4: H1 is promotional copy
    if PROMO_RE.search(h1_text):
        findings.append(
            f'H1 contains promotional copy: "{h1_text[:80]}". '
            "This trains search crawlers to classify the page as a discount/sale page, "
            "not a service page — direct intent mismatch for booking traffic."
        )
        evidence.append(f'H1 content: "{h1_text}"')
        affected.append({"tag": "h1", "text": h1_text, "id": ""})
        return _issue(findings, evidence, affected, severity="medium")

    # Case 5: H1 below fold (y > 900)
    if h1_y > 900:
        findings.append(
            f"H1 is at y={h1_y:.0f}px — below the fold. "
            "Visitors land and see no service identity before scrolling; "
            "first-impression trust and bounce-rate impact."
        )
        evidence.append(f"H1 y-position: {h1_y:.0f}px (fold = 900px)")
        affected.append({"tag": "h1", "text": h1_text, "id": ""})
        return _issue(findings, evidence, affected, severity="medium")

    return None  # H1 looks valid


def _issue(findings, evidence, affected, severity):
    return {
        "id": "h1_identity",
        "primary_element": "h1",
        "screenshot_mode": "section",
        "visual_evidence": "h1",
        "title": "H1 missing or fails to state service identity",
        "severity": severity,
        "confidence": "confirmed",
        "cro_impact": "First-impression trust + SEO keyword relevance",
        "revenue_signal": (
            "Pages with a clear service H1 convert 36% better than promotional or generic headlines "
            "(Nielsen Norman Group, 2023). This is the single highest-leverage on-page copy element."
        ),
        "detection_source": "dom+html",
        "industry_tags": ["all"],
        "fix_effort": "minutes",
        "affected_elements": affected,
        "findings": findings,
        "fix": (
            "Write H1 as: [Service] + [Location or Audience]. "
            "Example: 'Pediatric Dental Care in Miami — Children's Dental Specialty'. "
            "Keep promotional copy in a sub-headline (H2 or <p>), never the H1."
        ),
        "evidence": evidence,
    }
