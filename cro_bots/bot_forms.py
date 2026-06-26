"""
Bot 9 — Conversion Form Presence
Checks: no inline form and no booking-intent link.
CRO framing: form = the primary lead capture mechanism. Its absence is a conversion gap.
Works on: local_business, dental, medical, booking, restaurant, saas.
"""
from __future__ import annotations
import re
from .base import AuditParser, dom_y

BOOK_KW = re.compile(
    r"book|schedule|appointment|reserve|checkout|contact|enqui|signup|get\s*start|consult|quote",
    re.I,
)


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    dom_els = dom_elements or []

    has_form = bool(p.forms)

    booking_links = [
        e for e in dom_els
        if e.get("tag") == "a"
        and BOOK_KW.search((e.get("text") or "") + str(e.get("href") or ""))
        and dom_y(e) > 0
    ]

    # Also check HTML links
    html_booking_links = [
        lnk for lnk in p.links
        if BOOK_KW.search((lnk.get("text") or "") + (lnk.get("href") or ""))
    ]

    total_booking = len(booking_links) + len(html_booking_links)

    if has_form or total_booking >= 2:
        return None

    findings = []
    evidence  = []

    if not has_form:
        findings.append(
            "No inline contact/booking form found. "
            "Users who don't call must leave the page to convert — friction kills leads."
        )
        evidence.append("form tags found: 0")

    if total_booking < 2:
        findings.append(
            "No clear booking/appointment CTA links detected. "
            "Users have no obvious path to schedule or enquire."
        )
        evidence.append(f"booking-intent links found: {total_booking}")

    return {
        "id":               "conversion_form",
        "title":            "No inline conversion form or booking CTA detected",
        "severity":         "high",
        "confidence":       "confirmed",
        "cro_impact":       "Lead capture rate",
        "revenue_signal":   "Embedding a contact form on the homepage increases conversions by 27% vs phone-only.",
        "detection_source": "html+dom",
        "industry_tags":    ["local_business", "dental", "medical", "booking", "restaurant", "saas"],
        "fix_effort":       "days",
        "affected_elements": [],
        "findings":         findings,
        "fix": (
            "Add a short inline form (Name, Phone/Email, Message) in the hero or a sticky sidebar. "
            "Include a clear CTA button: 'Book a free consultation' or 'Request a callback'. "
            "Integrate with CRM (HubSpot, Pipedrive) for immediate follow-up."
        ),
        "evidence": evidence,
    }
