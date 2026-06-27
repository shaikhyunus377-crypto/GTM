"""
Bot — Social Proof
Broad detection across all site types:
  - Dental/medical: Google reviews, star ratings, patient testimonials
  - Associations: member quotes, success stories, member count
  - SaaS: customer logos, case studies, ratings
  - Ecommerce: product reviews, buyer counts
A blockquote with attribution IS social proof.
A member photo with name and quote IS social proof.
"""
from __future__ import annotations
import json
import re
from .base import AuditParser, dom_y, dom_visible

STAR_RE = re.compile(r"★|☆|⭐|\d(\.\d)?\s*/\s*5|\d(\.\d)?\s*star", re.I)

SOCIAL_KW = re.compile(
    r"testimonial|review|rating|verified|recommend|endorse|"
    r"said|says|quote|story|stories|"
    r"member\s+since|years?\s+(?:as\s+a\s+)?member|member\s+spotlight|"
    r"customer|client|patient|student|donor|alumni|"
    r"success\s+stor|case\s+stud|"
    r"trustpilot|g2\b|capterra|yelp|google\s+review|bbb|"
    r"award|winner|recognized|featured\s+in|as\s+seen\s+in|"
    r"join\s+\d+|over\s+\d+\s+member|more\s+than\s+\d+",
    re.I,
)

# Quote followed by a proper name attribution
ATTRIBUTION_RE = re.compile(
    r'["“‘].{20,400}["”’]\s*[-—]?\s*[A-Z][a-z]+\s+[A-Z]',
    re.S,
)

# "4,000+ members", "200 reviews", etc.
NUMERIC_SOCIAL_RE = re.compile(
    r"\b\d[\d,]*\+?\s*(?:member|review|client|patient|customer|student|rating|award)",
    re.I,
)


def run(p: AuditParser, dom_elements: list | None = None, site_type: str = "local_business") -> dict | None:
    dom_els = dom_elements or []
    html    = getattr(p, "raw_html", "")

    # Schema aggregateRating → definitive pass
    schema_json = " ".join(getattr(p, "schema_raw", []))
    if "aggregateRating" in schema_json:
        return None

    # Star characters
    if STAR_RE.search(html):
        return None

    # Attributed quote pattern (Name after quote)
    if ATTRIBUTION_RE.search(html):
        return None

    # Numeric social proof
    if NUMERIC_SOCIAL_RE.search(html):
        return None

    # DOM: blockquotes or social-keyword elements
    dom_social_els = [
        e for e in dom_els
        if (e.get("tag") == "blockquote" or SOCIAL_KW.search(e.get("text") or ""))
        and dom_visible(e) and dom_y(e) > 0
    ]
    if len(dom_social_els) >= 3:
        return None

    # HTML keyword count (softer threshold)
    html_signals = len(re.findall(SOCIAL_KW, html))
    if html_signals >= 4:
        return None

    # Adapt message to site type
    if site_type == "association":
        finding = (
            "No member testimonials, success stories, or member count signals detected. "
            "Prospective members need peer validation — existing member voices are the "
            "primary conversion driver for professional associations."
        )
        fix = (
            "Add a member spotlight with: photo, name, specialty, and a 1-2 sentence quote. "
            "Show a member count prominently ('Join 5,000+ Arizona dentists'). "
            "Link to a member success story or career outcome."
        )
    elif site_type == "saas":
        finding = "No customer logos, ratings (G2/Capterra), or case study signals detected."
        fix = "Add a customer logo bar, embed a G2 rating widget, or link to case studies."
    elif site_type == "nonprofit":
        finding = "No donor stories, impact numbers, or beneficiary testimonials detected."
        fix = "Add impact statistics ('3,000 families served') and 1-2 beneficiary quotes."
    else:
        finding = (
            "No star ratings, testimonials, attributed quotes, or review signals detected. "
            "Visitors have no third-party trust evidence before converting."
        )
        fix = (
            "Add 3-5 testimonials with name, photo, and result. "
            "Embed Google Reviews or add schema aggregateRating. "
            "For local businesses: show review count prominently in the hero."
        )

    return {
        "id":               "social_proof",
        "title":            "No social proof or testimonial signals detected",
        "severity":         "high",
        "confidence":       "confirmed",
        "cro_impact":       "Trust score + first-impression conversion rate",
        "revenue_signal":   "88% of consumers trust peer reviews as much as personal recommendations (BrightLocal).",
        "detection_source": "html+dom",
        "industry_tags":    ["all"],
        "fix_effort":       "days",
        "affected_elements": [],
        "findings":         [finding],
        "fix":              fix,
        "evidence": [
            f"Social proof keyword matches in DOM: {len(dom_social_els)}",
            f"HTML social proof signal count: {html_signals}",
            "No attributed quote pattern (quoted text + author name) found",
            "No numeric social proof (e.g. '4,000+ members') found",
        ],
    }
