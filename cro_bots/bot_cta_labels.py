"""
Bot 4 — CTA Label Quality
Checks: ALL CAPS conversion CTAs (not nav), generic labels.
Repeated labels are only flagged if they are conversion-intent (not navigation).

Key rules:
  - Navigation labels (Home, Services, About, etc.) are excluded from all checks
  - Repeated labels are only flagged if they repeat ≥5× AND are not nav/structural
  - Phone numbers as labels are intentionally excluded (they're useful)

CRO framing: every conversion CTA label is a micro-copy decision.
Works on: all verticals.
"""
from __future__ import annotations
import re
from collections import Counter
from .base import dom_y, dom_visible

GENERIC_LABELS = {
    "click here", "read more", "learn more", "more", "here",
    "link", "button", "click", "go", "ok", "yes", "no",
}

PHONE_RE = re.compile(r"^\+?[\d\s\-().]{7,}$")

# Structural / navigation labels — never a CTA quality issue
NAV_LABELS = {
    "HOME", "ABOUT", "ABOUT US", "OUR TEAM", "TEAM", "STAFF", "DOCTORS",
    "SERVICES", "OUR SERVICES", "WHAT WE DO", "TREATMENTS", "PROCEDURES",
    "CONTACT", "CONTACT US", "GET IN TOUCH", "REACH US",
    "BLOG", "NEWS", "RESOURCES", "FAQ", "FAQS", "ARTICLES",
    "PORTFOLIO", "GALLERY", "WORK", "CASE STUDIES", "BEFORE & AFTER", "BEFORE AND AFTER",
    "PRIVACY POLICY", "TERMS", "TERMS OF SERVICE", "SITEMAP", "ACCESSIBILITY",
    "PATIENT PORTAL", "LOGIN", "LOG IN", "SIGN IN", "SIGN UP",
    "MENU", "LOCATIONS", "LOCATION", "CAREERS", "JOBS", "EMPLOYMENT",
    "VIEW ALL", "SEE ALL", "ALL SERVICES", "ALL LOCATIONS",
    "BACK", "NEXT", "PREVIOUS", "PREV", "CLOSE", "OPEN", "EXPAND",
    "EN", "ES", "FR", "DE", "PT",  # language switchers
    "ENGLISH", "ESPAÑOL", "ESPAÑOL", "FRENCH",
    "SEARCH", "SUBMIT", "SEND", "APPLY",
    "FACEBOOK", "INSTAGRAM", "TWITTER", "LINKEDIN", "YOUTUBE", "YELP", "GOOGLE",
    "EMERGENCY", "URGENT CARE", "NEW PATIENT", "NEW PATIENTS",
    "FINANCING", "INSURANCE", "PAYMENT", "PAY ONLINE", "PAY NOW",
}

# Structural labels that are fine to repeat (footer vs header, etc.)
STRUCTURAL_REPEAT_LABELS = NAV_LABELS | {
    "REQUEST APPOINTMENT", "BOOK NOW", "CALL NOW", "SCHEDULE NOW",
    "BOOK APPOINTMENT", "MAKE APPOINTMENT",
}


def run(p=None, dom_elements: list | None = None) -> dict | None:
    if not dom_elements:
        return None

    cta_els = [
        e for e in dom_elements
        if e.get("tag") in ("a", "button")
        and dom_visible(e)
        and dom_y(e) > 0
    ]

    labels       = [(e.get("text") or "").strip() for e in cta_els if (e.get("text") or "").strip()]
    label_counts = Counter(labels)

    # ALL CAPS that are not navigation labels and not phone numbers
    all_caps = sorted({
        l for l in labels
        if l.upper() not in NAV_LABELS
        and l.upper() not in STRUCTURAL_REPEAT_LABELS
        and l == l.upper()
        and len(l) > 3
        and re.search(r"[A-Z]", l)
        and not PHONE_RE.match(l)
    })

    # Repeated conversion labels — raise threshold to 5× and exclude nav/structural
    repeated = [
        (l, c) for l, c in label_counts.items()
        if c >= 5
        and not PHONE_RE.match(l)
        and l.upper() not in STRUCTURAL_REPEAT_LABELS
        and l.lower() not in GENERIC_LABELS
    ]

    # Truly generic labels (no destination signal at all)
    generics = [
        l for l in labels
        if l.lower() in GENERIC_LABELS
        and l.upper() not in NAV_LABELS
    ]

    findings = []
    evidence  = []

    if all_caps:
        findings.append(
            f"{len(all_caps)} conversion CTA(s) use ALL CAPS text — "
            "screen readers spell them letter-by-letter (V-I-E-W S-E-R-V-I-C-E-S). "
            "Use CSS text-transform:uppercase to preserve visual style without harming accessibility."
        )
        evidence += [f"ALL CAPS conversion CTA: \"{l}\"" for l in all_caps[:5]]

    if repeated:
        sample = ", ".join(f"\"{l}\" (×{c})" for l, c in repeated[:3])
        findings.append(
            f"Conversion labels repeated 5+ times with no context differentiation: {sample}. "
            "GA4 cannot attribute which instance drove the click."
        )
        evidence += [f"\"{l}\" repeated {c}×" for l, c in repeated[:3]]

    if generics:
        unique_g = list({l.lower() for l in generics})[:4]
        findings.append(
            f"Generic labels with no destination signal: {unique_g}. "
            "Users can't predict what they'll get — increases hesitation."
        )

    # Require at least one meaningful finding — ≤2 all-caps items alone is not actionable
    if len(all_caps) <= 2 and not repeated and not generics:
        return None

    return {
        "id":               "cta_label_quality",
        "title":            "Conversion CTA labels use ALL CAPS or are too generic",
        "severity":         "medium",
        "confidence":       "confirmed",
        "cro_impact":       "Click-through rate + GA4 attribution accuracy",
        "revenue_signal":   "Descriptive CTAs outperform generic labels by 14-202% in A/B tests (HubSpot).",
        "detection_source": "dom",
        "industry_tags":    ["all"],
        "fix_effort":       "hours",
        "affected_elements": [
            {"tag": e.get("tag"), "text": (e.get("text") or "")[:60], "y": dom_y(e)}
            for e in cta_els
            if (e.get("text") or "").strip() in all_caps
        ][:8],
        "findings": findings,
        "fix": (
            "Write every conversion CTA as: [verb] + [specific outcome]. "
            "'Book free consultation', 'See implant pricing', 'Call our Miami office'. "
            "Apply CSS text-transform:uppercase for visual caps — HTML stays sentence-case. "
            "Add data-cta-location attributes for GA4 event segmentation."
        ),
        "evidence": evidence,
    }
