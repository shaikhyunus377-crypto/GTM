"""Bot 7 — LocalBusiness Schema Completeness
Checks: Missing schema, or schema missing revenue-critical fields (phone, hours, rating, address).
CRO framing: Schema drives rich results in Google — hours, phone, rating appear in SERP.
Works on: local_business, dental, medical, restaurant, booking.
"""
from __future__ import annotations
import re
from .base import AuditParser

LOCAL_TYPES = {
    "LocalBusiness", "MedicalClinic", "Dentist", "Physician", "Hospital",
    "Restaurant", "LegalService", "FinancialService", "HomeAndConstructionBusiness",
    "ProfessionalService", "HealthAndBeautyBusiness", "SportsActivityLocation",
    "ChildCare", "DaySpa", "AutoRepair", "Plumber", "Electrician",
}

CRITICAL_FIELDS = {
    "telephone":      "Phone number (drives direct calls from SERP)",
    "openingHours":   "Business hours (shown in Google Knowledge Panel)",
    "address":        "Address (required for local pack ranking)",
    "aggregateRating":"Star rating (shown in rich results — 35% higher CTR)",
}
IMPORTANT_FIELDS = {
    "priceRange":     "Price range ($$) — booking confidence signal",
    "image":          "Business image — shown in Knowledge Panel",
    "url":            "Canonical URL — deduplication signal",
    "description":    "Business description — shown in Knowledge Panel",
}


def _flatten_schema(block: dict) -> list[dict]:
    """Handle @graph arrays and single objects."""
    if "@graph" in block and isinstance(block["@graph"], list):
        return block["@graph"]
    return [block]


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    if not p.schema_blocks:
        return {
            "id": "schema_incomplete",
            "primary_element": "script",
            "screenshot_mode": "fullpage",
            "visual_evidence": "page source",
            "title": "No Schema.org markup found — invisible to Google rich results",
            "severity": "high",
            "confidence": "confirmed",
            "cro_impact": "Google SERP click-through rate + local pack visibility",
            "revenue_signal": (
                "Local businesses with complete LocalBusiness schema get 35% more clicks from "
                "Google rich results. Dentist/medical schema enables star ratings, phone, and hours "
                "in SERP — missing these means competitors with schema win the click."
            ),
            "detection_source": "html",
            "industry_tags": ["local_business","dental","medical","restaurant","booking"],
            "fix_effort": "hours",
            "affected_elements": [],
            "findings": ["No LD+JSON or Schema.org markup detected in page HTML."],
            "fix": (
                "Add LocalBusiness (or subtype: Dentist, MedicalClinic, Restaurant) schema as LD+JSON in <head>. "
                "Required fields: @type, name, telephone, address (PostalAddress), "
                "openingHours, url, aggregateRating (if reviews exist). "
                "Validate with Google's Rich Results Test."
            ),
            "evidence": ["LD+JSON blocks found: 0"],
        }

    # Find the most relevant local business schema block
    local_block = None
    for raw_block in p.schema_blocks:
        for item in _flatten_schema(raw_block):
            schema_type = item.get("@type", "")
            if isinstance(schema_type, list):
                schema_type = schema_type[0]
            if schema_type in LOCAL_TYPES:
                local_block = item
                break
        if local_block:
            break

    if not local_block:
        return {
            "id": "schema_incomplete",
            "primary_element": "script",
            "screenshot_mode": "fullpage",
            "visual_evidence": "page source",
            "title": "Schema present but no LocalBusiness type — local SEO signals missing",
            "severity": "medium",
            "confidence": "confirmed",
            "cro_impact": "Local SEO + Google Knowledge Panel data",
            "revenue_signal": (
                "Competing pages with LocalBusiness schema outrank those without it in local pack results. "
                "Missing type means no rich phone/hours/rating in SERP."
            ),
            "detection_source": "html",
            "industry_tags": ["local_business","dental","medical","restaurant","booking"],
            "fix_effort": "hours",
            "affected_elements": [],
            "findings": [f"Schema blocks found ({len(p.schema_blocks)}) but none match a LocalBusiness type."],
            "fix": "Change @type to LocalBusiness or a subtype (Dentist, MedicalClinic, etc.).",
            "evidence": [f"Schema @types found: {[b.get('@type','?') for b in p.schema_blocks[:5]]}"],
        }

    # Check critical fields
    missing_critical = {k: v for k, v in CRITICAL_FIELDS.items() if k not in local_block}
    missing_important = {k: v for k, v in IMPORTANT_FIELDS.items() if k not in local_block}

    if not missing_critical:
        return None  # All critical fields present

    findings = []
    evidence = []
    schema_type = local_block.get("@type", "LocalBusiness")

    for field, desc in missing_critical.items():
        findings.append(f"Missing critical field '{field}': {desc}")
        evidence.append(f"Schema.{field}: not present")

    for field, desc in list(missing_important.items())[:2]:
        findings.append(f"Missing recommended field '{field}': {desc}")
        evidence.append(f"Schema.{field}: not present")

    return {
        "id": "schema_incomplete",
        "primary_element": "script",
        "screenshot_mode": "fullpage",
        "visual_evidence": "page source — schema block",
        "title": f"{schema_type} schema incomplete — {len(missing_critical)} critical fields missing",
        "severity": "medium",
        "confidence": "confirmed",
        "cro_impact": "Google SERP rich results + local pack click-through rate",
        "revenue_signal": (
            "Pages with aggregateRating in schema get 35% higher SERP CTR. "
            "Missing telephone means Google can't show your number in SERP — "
            "competitors with phone visible in rich results get the direct call."
        ),
        "detection_source": "html",
        "industry_tags": ["local_business","dental","medical","restaurant","booking"],
        "fix_effort": "hours",
        "affected_elements": [{"schema_type": schema_type, "missing": list(missing_critical.keys())}],
        "findings": findings,
        "fix": (
            f"Add missing fields to your {schema_type} schema: "
            + ", ".join(missing_critical.keys()) +
            ". Validate with Google Rich Results Test (search.google.com/test/rich-results)."
        ),
        "evidence": evidence,
    }
