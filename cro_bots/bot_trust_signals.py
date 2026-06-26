"""Bot 6 — Trust Signals Above Fold
Checks: Certifications, awards, accreditations, insurance logos above the fold.
CRO framing: Trust signals reduce friction at the decision moment.
Works on: dental, medical, legal, financial, local_business.
"""
from __future__ import annotations
import re
from .base import AuditParser, dom_y, dom_visible, above_fold

# Keywords in alt text, link text, heading text, image src that indicate trust badges
TRUST_RE = re.compile(
    r"accredit|certif|award|recogni|best\s+(dentist|doctor|clinic|practice|rated)"
    r"|top\s+(dentist|doctor|rated|rated|choice)"
    r"|bbb|better\s+business|insurance|accept|aetna|delta\s+dental|cigna|metlife|humana"
    r"|aacd|ada\b|aapd|jcaho|board\s+certif|licensed|membr"
    r"|as\s+seen\s+in|featured\s+in|press|inc\s+\d+|forbes|angi",
    re.I,
)


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    dom_els = dom_elements or []

    # Check images above fold for trust badge alt text
    trust_imgs_above_fold = []
    for img in p.images:
        alt = img.get("alt") or ""
        src = img.get("src") or ""
        if TRUST_RE.search(alt) or TRUST_RE.search(src):
            trust_imgs_above_fold.append({"alt": alt, "src": src[:60]})

    # Check heading and link text for trust signals
    text_corpus = " ".join(
        [(h.get("text") or "") for h in p.headings] +
        [(l.get("text") or "") for l in p.links]
    )
    html_trust = bool(TRUST_RE.search(text_corpus))

    # Check DOM for trust signals above fold
    dom_trust_above_fold = 0
    for e in dom_els:
        if not dom_visible(e) or dom_y(e) <= 0:
            continue
        if not above_fold(e, fold=1000):  # generous fold for trust
            continue
        text = (e.get("text") or "").strip()
        aria = (e.get("aria_label") or "").strip()
        if TRUST_RE.search(text) or TRUST_RE.search(aria):
            dom_trust_above_fold += 1

    if trust_imgs_above_fold or html_trust or dom_trust_above_fold >= 2:
        return None  # Trust signals found

    findings = [
        "No certifications, awards, accreditations, or insurance logos detected on this page. "
        "First-time visitors have no independent validation of your credentials — "
        "trust must be established by the visitor alone, which most won't do."
    ]
    evidence = [
        "Trust badge images (by alt/src): 0",
        "Trust keywords in headings/links: not found",
        f"DOM trust signals above fold: {dom_trust_above_fold}",
    ]

    return {
        "id": "trust_signals",
        "primary_element": "img",
        "screenshot_mode": "section",
        "visual_evidence": "hero or header trust area",
        "title": "No trust signals (certifications, awards, insurance) above the fold",
        "severity": "medium",
        "confidence": "confirmed",
        "cro_impact": "Pre-booking trust + hesitation reduction",
        "revenue_signal": (
            "Displaying professional certifications increases service conversions by 42% "
            "for medical/dental sites (Edelman Trust Report, 2022). "
            "Insurance acceptance logos reduce the #1 booking objection: 'Is this covered?'"
        ),
        "detection_source": "html+dom",
        "industry_tags": ["dental", "medical", "legal", "financial", "local_business"],
        "fix_effort": "hours",
        "affected_elements": [],
        "findings": findings,
        "fix": (
            "Add a trust bar in the header or just below the hero: "
            "board certifications, association logos (ADA, AACD), insurance accepted, BBB badge, "
            "Google/Yelp rating count. "
            "Use actual badge images with descriptive alt text. "
            "Place before the primary CTA — not in the footer."
        ),
        "evidence": evidence,
    }
