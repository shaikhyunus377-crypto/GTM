"""
Bot — Social Proof
Checks: missing reviews, testimonials, ratings, or star ratings.
CRO framing: social proof is the #1 trust accelerator for service businesses.
Works on: all verticals.
"""
from __future__ import annotations
import json
import re
from .base import AuditParser, dom_y, dom_visible

REVIEW_KW = re.compile(
    r"review|testimonial|rating|stars?|verified|patient|client\s+said|what\s+our|"
    r"google\s+review|trustpilot|yelp|5[\-\s]star",
    re.I,
)
STAR_RE = re.compile(r"★|☆|⭐|\d(\.\d)?\s*/\s*5|\d(\.\d)?\s*stars?", re.I)


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    dom_els = dom_elements or []

    # Check schema for aggregateRating
    schema_has_rating = False
    for raw in p.schema_raw:
        try:
            d = json.loads(raw)
            if "aggregateRating" in d:
                schema_has_rating = True
        except Exception:
            pass

    if schema_has_rating:
        return None

    # Check HTML for review keywords / star chars
    html_signals = bool(STAR_RE.search(" ".join(
        lnk.get("text","") for lnk in p.links
    )))

    # DOM: count elements containing review-like text
    dom_review_els = [
        e for e in dom_els
        if REVIEW_KW.search(e.get("text") or "")
        and dom_visible(e)
        and dom_y(e) > 0
    ]

    if len(dom_review_els) >= 3 or html_signals:
        return None

    return {
        "id":               "social_proof",
        "title":            "No social proof (reviews / testimonials / ratings) detected",
        "severity":         "high",
        "confidence":       "confirmed",
        "cro_impact":       "Trust score + conversion rate",
        "revenue_signal":   "88% of consumers trust online reviews as much as personal recommendations (BrightLocal).",
        "detection_source": "html+dom",
        "industry_tags":    ["all"],
        "fix_effort":       "days",
        "affected_elements": [],
        "findings": [
            "No star ratings, testimonials, or review signals detected. "
            "Visitors have no third-party trust evidence before converting."
        ],
        "fix": (
            "Add a reviews section: embed Google Reviews widget, or paste 3-5 testimonials "
            "with name, photo, and star rating. Add schema aggregateRating. "
            "For local businesses: display review count and average prominently in the hero."
        ),
        "evidence": [
            f"schema aggregateRating: not found",
            f"DOM review elements: {len(dom_review_els)}",
            f"HTML star/rating signals: {html_signals}",
        ],
    }
