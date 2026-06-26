"""
Bot 1 — H1 Identity
Checks: missing H1, empty H1, promotional H1 (discounts/sales copy instead of service identity).
CRO framing: H1 = the highest-trust statement on the page. It must answer "what do you do?"
Works on: all verticals.
"""
from __future__ import annotations
import re
from .base import AuditParser, dom_y

PROMO_RE = re.compile(
    r"\b(\d+\s*%|off\b|sale\b|deal\b|save\b|discount|free\b|limited\s+time)\b", re.I
)


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    dom_els = dom_elements or []
    dom_h1s = [e for e in dom_els if e.get("tag") == "h1"]

    # DOM-first: prefer DOM data if available
    if dom_h1s:
        h1 = dom_h1s[0]
        text = (h1.get("text") or "").strip()
        y    = dom_y(h1)

        if not text:
            return _issue("H1 is empty — the page's primary identity statement is blank", text, y)

        if PROMO_RE.search(text):
            return _issue(
                f"H1 contains promotional copy (\"{text[:60]}\") — "
                "use a service identity statement (e.g. 'Pediatric Dentistry in Miami')",
                text, y,
            )

        if y > 900 and y > 0:
            return _issue(
                f"H1 is below the fold (y={y}px) — visitors see no service headline before scrolling",
                text, y,
            )

        return None  # H1 is valid

    # Fallback: HTML parser
    h1s = [h for h in p.headings if h["tag"] == "h1"]
    if not h1s:
        return _issue("No H1 tag found — page has no primary identity statement", "", 0)

    text = h1s[0].get("text", "").strip()
    if not text:
        return _issue("H1 tag is present but empty", "", 0)

    return None


def _issue(finding: str, text: str, y: int) -> dict:
    return {
        "id":               "h1_identity",
        "title":            "H1 missing or fails identity test",
        "severity":         "high",
        "confidence":       "confirmed",
        "cro_impact":       "First-impression clarity + SEO relevance signal",
        "revenue_signal":   "Pages with clear service H1s convert 23% better on first visit.",
        "detection_source": "dom+html",
        "industry_tags":    ["all"],
        "fix_effort":       "minutes",
        "affected_elements": [{"tag": "h1", "text": text, "y": y}] if text else [],
        "findings":         [finding],
        "fix": (
            "Write the H1 as: [Service] in [Location] — e.g. 'Pediatric Dentist in Miami, FL'. "
            "One H1 per page, placed in the hero section above the fold (y < 600px). "
            "Use CSS for stylistic caps if needed — HTML text stays sentence-case."
        ),
        "evidence": [f"H1 content: \"{text}\""] if text else ["H1 not found or empty"],
    }
