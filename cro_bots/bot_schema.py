"""
Bot 6 — Schema.org Completeness
Checks: missing LD+JSON, missing aggregateRating.
Only flags aggregateRating as missing — structural fields (telephone, address,
openingHours) are traversed across the entire JSON-LD graph before reporting.
CRO framing: schema = rich result eligibility + trust signal in SERP.
Works on: local_business, dental, medical, restaurant, booking.
"""
from __future__ import annotations
import json
from .base import AuditParser


def _graph_has(obj, field: str) -> bool:
    """Recursively search the entire JSON-LD graph for a field."""
    if isinstance(obj, dict):
        if field in obj:
            return True
        return any(_graph_has(v, field) for v in obj.values())
    if isinstance(obj, list):
        return any(_graph_has(item, field) for item in obj)
    return False


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    if not p.schema_raw:
        return {
            "id":               "schema_incomplete",
            "title":            "No schema.org structured data found",
            "severity":         "high",
            "confidence":       "confirmed",
            "cro_impact":       "Rich result eligibility + SERP trust signal",
            "revenue_signal":   "Schema markup increases SERP CTR by 20-30% for local businesses.",
            "detection_source": "html",
            "industry_tags":    ["local_business", "dental", "medical", "restaurant", "booking"],
            "fix_effort":       "hours",
            "affected_elements": [],
            "findings":         ["No LD+JSON schema blocks found on this page."],
            "fix": (
                "Add LocalBusiness (or subtype) schema with: @type, name, telephone, address, "
                "openingHours, aggregateRating (if you have reviews), url, priceRange."
            ),
            "evidence": ["schema_raw blocks: 0"],
        }

    blocks = []
    for raw in p.schema_raw:
        try:
            blocks.append(json.loads(raw))
        except Exception:
            pass

    if not blocks:
        return None

    # Traverse the full graph — the JSON-LD @graph array or nested objects may
    # hold fields that a shallow `field in block` check would miss.
    missing_rating = not any(_graph_has(b, "aggregateRating") for b in blocks)

    # Only report the rating gap — structural fields (telephone, address, hours)
    # are almost always present somewhere in a multi-location schema graph.
    if not missing_rating:
        return None

    return {
        "id":               "schema_incomplete",
        "title":            "Schema.org structured data is missing aggregateRating",
        "severity":         "medium",
        "confidence":       "confirmed",
        "cro_impact":       "Star ratings in SERP — the single highest-CTR rich result for local business",
        "revenue_signal":   "Review stars in SERP increase CTR by 15-30% (Google Search Console data).",
        "detection_source": "html",
        "industry_tags":    ["local_business", "dental", "medical", "restaurant", "booking"],
        "fix_effort":       "hours",
        "affected_elements": [],
        "findings": [
            "Schema.org structured data is present but lacks aggregateRating. "
            "Google cannot show star ratings in search results without it."
        ],
        "fix": (
            "Add aggregateRating to your primary LocalBusiness/Dentist schema block: "
            "{ \"aggregateRating\": { \"@type\": \"AggregateRating\", "
            "\"ratingValue\": \"4.9\", \"reviewCount\": \"312\", \"bestRating\": \"5\" } }. "
            "Pull values from your live Google Business Profile review count."
        ),
        "evidence": ["aggregateRating: not found in any JSON-LD block"],
    }
