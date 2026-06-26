"""
Bot 6 — Schema.org Completeness
Checks: missing LD+JSON, missing aggregateRating, missing openingHours, missing telephone.
CRO framing: schema = rich result eligibility + trust signal in SERP.
Works on: local_business, dental, medical, restaurant, booking.
"""
from __future__ import annotations
import json
from .base import AuditParser

LOCAL_FIELDS = ["telephone", "address", "openingHours"]
TRUST_FIELDS = ["aggregateRating"]


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

    missing_fields = []
    for field in TRUST_FIELDS + LOCAL_FIELDS:
        if not any(field in b for b in blocks):
            missing_fields.append(field)

    if not missing_fields:
        return None

    findings = [
        f"Schema present but missing critical fields: {missing_fields}. "
        "Google uses these for rich results and trust signals."
    ]

    return {
        "id":               "schema_incomplete",
        "title":            "Schema.org structured data is incomplete",
        "severity":         "medium",
        "confidence":       "confirmed",
        "cro_impact":       "Rich result eligibility + SERP trust",
        "revenue_signal":   "Complete schema markup (with ratings) increases CTR by 20-30%.",
        "detection_source": "html",
        "industry_tags":    ["local_business", "dental", "medical", "restaurant", "booking"],
        "fix_effort":       "hours",
        "affected_elements": [],
        "findings":         findings,
        "fix": (
            f"Add missing schema fields: {missing_fields}. "
            "For aggregateRating: include ratingValue, reviewCount, bestRating."
        ),
        "evidence": [f"Missing field: {f}" for f in missing_fields],
    }
