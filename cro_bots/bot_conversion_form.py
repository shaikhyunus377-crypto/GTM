"""Bot 4 — Conversion Form Presence & Friction
Checks: No inline contact/booking form, OR form has excessive required fields.
CRO framing: Forms are the final step before a lead is captured.
Works on: all verticals.
"""
from __future__ import annotations
import re
from .base import AuditParser, dom_y, dom_visible

BOOKING_RE = re.compile(
    r"book|schedul|appoint|reserv|contact|enqui|request|consult|get\s+start|sign\s+up|reach\s+out",
    re.I,
)
# Fields that add friction without adding qualification value
FRICTION_FIELDS = {"address", "company", "dob", "birth", "ssn", "gender", "age", "country", "zip", "postal"}


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    dom_els = dom_elements or []

    # Check for forms in HTML
    html_forms = p.forms

    # Check for booking-intent links (alternative to forms)
    booking_links = [
        e for e in dom_els
        if e.get("tag") == "a"
        and dom_visible(e)
        and dom_y(e) > 0
        and BOOKING_RE.search(e.get("text") or "")
    ]

    findings = []
    evidence = []

    if not html_forms:
        if len(booking_links) < 2:
            # No form AND barely any booking links = hard conversion break
            findings.append(
                "No contact or booking form found on this page. "
                "Visitors who are ready to convert have no immediate action path — "
                "they must find a contact method manually (phone, email hunt, etc.)."
            )
            evidence.append("HTML <form> elements: 0")
            evidence.append(f"Booking-intent links: {len(booking_links)}")
        else:
            # Has booking links but no form — flag for moderate friction
            findings.append(
                f"No inline form found. Conversion relies on {len(booking_links)} booking link(s) "
                "redirecting to an external page. Each redirect step loses ~20% of leads."
            )
            evidence.append("HTML <form> elements: 0")
            evidence.append(f"Booking links present: {len(booking_links)}")
            for bl in booking_links[:3]:
                evidence.append(f'  Booking link: "{(bl.get("text") or "")[:40]}"')
    else:
        # Form exists — check field friction
        for form in html_forms:
            fields = form.get("fields", [])
            required_count = sum(1 for f in fields if f.get("required"))
            friction = [f for f in fields if any(kw in (f.get("name","") + f.get("type","")).lower() for kw in FRICTION_FIELDS)]

            if required_count > 5:
                findings.append(
                    f"Form has {required_count} required fields — every extra field reduces "
                    "completion by 11% on average (Formstack, 2023). "
                    "Reduce to 3-4 essential fields (name, phone/email, message)."
                )
                evidence.append(f"Required fields: {required_count} (optimal: ≤4)")

            if friction:
                names = ", ".join(f.get("name",f.get("type","?")) for f in friction[:3])
                findings.append(
                    f"High-friction fields detected: {names}. "
                    "These are qualification questions that feel invasive at first contact — "
                    "move them to a post-submission follow-up."
                )
                evidence.append(f"Friction fields: {names}")

    if not findings:
        return None

    return {
        "id": "conversion_form",
        "primary_element": "form",
        "screenshot_mode": "section",
        "visual_evidence": "form or contact section",
        "title": "Conversion form missing or has high friction — leads lost at final step",
        "severity": "high" if not html_forms else "medium",
        "confidence": "confirmed",
        "cro_impact": "Lead capture rate + form completion rate",
        "revenue_signal": (
            "Removing one form field increases completions by 26% on average. "
            "Pages with inline forms convert 3x more leads than redirect-only contact flows "
            "(HubSpot, 2022). A missing form is a direct booking revenue gap."
        ),
        "detection_source": "html+dom",
        "industry_tags": ["all"],
        "fix_effort": "hours",
        "affected_elements": [{"form_count": len(html_forms), "booking_links": len(booking_links)}],
        "findings": findings,
        "fix": (
            "Add an inline contact/booking form with: Name, Phone or Email, optional Message. "
            "Label submit button with outcome: 'Request Free Consultation' not 'Submit'. "
            "Embed on every service page — don't rely on a separate contact page. "
            "If using a third-party booking widget, embed inline (not a link to external URL)."
        ),
        "evidence": evidence,
    }
