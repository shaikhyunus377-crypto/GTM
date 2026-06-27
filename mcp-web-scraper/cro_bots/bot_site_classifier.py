"""
Bot — Site Type Classifier
Detects the business model of the page so downstream bots can adapt their rules.

Returns a lightweight result that's injected into the audit context.
Does NOT fire as a CRO finding — it's infrastructure.

Site types:
  dental, medical, legal, ecommerce, saas, restaurant,
  association, nonprofit, portfolio, local_business (default)
"""
from __future__ import annotations
import json
import re
from .base import AuditParser

# Keyword signals per type — scored by frequency
_SIGNALS: dict[str, list[str]] = {
    "dental": [
        "dentist", "dental", "tooth", "teeth", "cavity", "implant",
        "orthodont", "braces", "invisalign", "crown", "veneer", "whitening",
        "oral", "enamel", "periodon",
    ],
    "medical": [
        "doctor", "physician", "hospital", "clinic", "patient",
        "surgery", "therapy", "treatment", "medical", "health",
        "diagnosis", "prescription", "specialist",
    ],
    "legal": [
        "attorney", "lawyer", "law firm", "legal", "litigation",
        "settlement", "counsel", "paralegal", "jurisdiction",
    ],
    "ecommerce": [
        "cart", "checkout", "buy now", "add to cart", "shop",
        "shipping", "returns", "product", "order",
    ],
    "saas": [
        "software", "dashboard", "free trial", "pricing", "features",
        "integrations", "api", "subscription", "platform", "workflow",
        "automation", "cloud", "enterprise",
    ],
    "restaurant": [
        "menu", "reservation", "dine", "cuisine", "chef",
        "brunch", "dinner", "lunch", "takeout", "delivery",
    ],
    "association": [
        "member", "membership", "join", "association", "chapter",
        "annual meeting", "advocacy", "dues", "society", "organization",
        "conference", "continuing education", "certif", "renew",
        "board of directors", "nonprofit", "non-profit",
    ],
    "nonprofit": [
        "donate", "donation", "volunteer", "mission", "charity",
        "nonprofit", "501c", "foundation", "grant", "cause",
    ],
    "portfolio": [
        "portfolio", "projects", "my work", "case study", "freelance",
        "designer", "developer", "photographer", "creative",
    ],
}

# Schema @type → site type
_SCHEMA_TYPE_MAP = {
    "Dentist":         "dental",
    "MedicalBusiness": "medical",
    "Hospital":        "medical",
    "LegalService":    "legal",
    "Attorney":        "legal",
    "Restaurant":      "restaurant",
    "FoodEstablishment": "restaurant",
    "SoftwareApplication": "saas",
    "WebApplication":  "saas",
    "NGO":             "nonprofit",
    "Organization":    "association",
    "ProfessionalService": "local_business",
    "LocalBusiness":   "local_business",
}


def _score_html(html_lower: str) -> dict[str, int]:
    scores: dict[str, int] = {t: 0 for t in _SIGNALS}
    for site_type, keywords in _SIGNALS.items():
        for kw in keywords:
            scores[site_type] += html_lower.count(kw)
    return scores


def classify(p: AuditParser) -> str:
    """Return the best-fit site type string."""
    html_lower = getattr(p, "raw_html", "").lower()

    # 1. Schema @type is highest confidence
    for raw in getattr(p, "schema_raw", []):
        try:
            obj = json.loads(raw)
            candidates = []
            if isinstance(obj, dict):
                t = obj.get("@type")
                if isinstance(t, list):
                    candidates = t
                elif t:
                    candidates = [t]
                for item in obj.get("@graph", []):
                    t2 = item.get("@type")
                    if t2:
                        candidates += ([t2] if isinstance(t2, str) else t2)
            for c in candidates:
                if c in _SCHEMA_TYPE_MAP:
                    return _SCHEMA_TYPE_MAP[c]
        except Exception:
            pass

    # 2. Keyword frequency
    scores = _score_html(html_lower)
    best_type, best_score = max(scores.items(), key=lambda x: x[1])
    if best_score >= 3:
        return best_type

    return "local_business"


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    """Returns None — classifier result is injected via cro_audit.py separately."""
    return None
