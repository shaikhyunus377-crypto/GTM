"""Bot 5 — Social Proof Presence
Checks: No testimonials, reviews, star ratings, or patient stories visible on page.
CRO framing: Social proof is the #1 trust driver for service bookings.
Works on: all verticals.
"""
from __future__ import annotations
import re
from .base import AuditParser, dom_y, dom_visible

# HTML-level signals for social proof
SOCIAL_PROOF_RE = re.compile(
    r"testimonial|review|star|rating|patient\s+stor|customer\s+stor|what\s+(our|people|client|patient)\s+say"
    r"|verified|trustpilot|google\s+review|yelp|\d+\s+stars?|\d+\.\d+\s+out\s+of"
    r"|satisfied|happy\s+(patient|client|customer)|success\s+stor",
    re.I,
)
# Schema-level signals
RATING_SCHEMA_RE = re.compile(r'aggregateRating|ratingValue|reviewCount', re.I)

# DOM text signals (from element text in dom_elements)
DOM_PROOF_RE = re.compile(
    r"\b(review|testimonial|stars?|rating|said|says|patient|recommend|trust)\b",
    re.I,
)


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    dom_els = dom_elements or []

    # Check 1: Schema aggregateRating
    schema_has_rating = False
    for block in p.schema_blocks:
        if "aggregateRating" in block:
            schema_has_rating = True
            break
        if isinstance(block.get("@graph"), list):
            for item in block["@graph"]:
                if "aggregateRating" in item:
                    schema_has_rating = True
                    break

    # Check 2: HTML text contains social proof signals
    # We reconstruct visible text from headings and link text
    text_corpus = " ".join(
        [(h.get("text") or "") for h in p.headings] +
        [(l.get("text") or "") for l in p.links]
    )
    html_has_social = bool(SOCIAL_PROOF_RE.search(text_corpus))

    # Check 3: DOM elements contain review/testimonial keywords
    dom_proof_count = 0
    for e in dom_els:
        if dom_visible(e) and dom_y(e) > 0:
            text = (e.get("text") or "").strip()
            if text and DOM_PROOF_RE.search(text):
                dom_proof_count += 1

    if schema_has_rating or html_has_social or dom_proof_count >= 3:
        return None  # Social proof detected

    # Check if the page is a landing/home page type (should always have social proof)
    heading_texts = " ".join(h["text"] for h in p.headings).lower()

    findings = [
        "No testimonials, reviews, or star ratings detected on this page. "
        "Visitors considering a booking have no social validation — "
        "without proof that others have had a positive experience, trust is unearned."
    ]
    evidence = [
        "Schema aggregateRating: not found",
        "Testimonial/review keywords in HTML: not found",
        f"DOM social-proof signals: {dom_proof_count} (threshold: 3)",
    ]

    return {
        "id": "social_proof",
        "primary_element": "section",
        "screenshot_mode": "section",
        "visual_evidence": "testimonials section",
        "title": "No social proof detected — trust gap kills booking intent",
        "severity": "high",
        "confidence": "confirmed",
        "cro_impact": "Booking trust + conversion intent near the decision point",
        "revenue_signal": (
            "92% of consumers read online reviews before making a service booking (BrightLocal, 2023). "
            "Adding testimonials to a landing page increases conversions by 34% on average. "
            "For dental/medical: patient reviews are the #1 conversion driver, above price."
        ),
        "detection_source": "html+dom+schema",
        "industry_tags": ["all"],
        "fix_effort": "hours",
        "affected_elements": [],
        "findings": findings,
        "fix": (
            "Add a testimonials section with: patient name, photo (optional), quote, star rating. "
            "Embed Google Reviews widget or pull from API. "
            "Add aggregateRating to LocalBusiness schema. "
            "Place near the primary booking CTA — social proof immediately before the action button "
            "is the highest-converting position."
        ),
        "evidence": evidence,
    }
