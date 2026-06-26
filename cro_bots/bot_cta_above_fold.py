"""Bot 2 — CTA Above Fold
Checks: Is there a booking/contact/conversion CTA visible without scrolling (y < fold)?
CRO framing: The fold is the conversion moment — if visitors must scroll to act, most won't.
Works on: all verticals with booking intent.
"""
from __future__ import annotations
import re
from .base import AuditParser, dom_y, dom_width, dom_height, dom_on_screen

FOLD = 800  # conservative fold (mobile-safe)

BOOKING_RE = re.compile(
    r"book|schedul|appoint|reserv|contact|call|get\s+start|sign\s+up|register|"
    r"free\s+consult|get\s+quote|request|enqui|consult|visit|see\s+us|reach\s+out",
    re.I,
)


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    dom_els = dom_elements or []

    # Find all visible above-fold CTAs
    above_fold_ctas = []
    for e in dom_els:
        if e.get("tag") not in ("a", "button"):
            continue
        if not dom_on_screen(e):
            continue
        y = dom_y(e)
        if y <= 0 or y > FOLD:
            continue
        text = (e.get("text") or "").strip()
        if text and BOOKING_RE.search(text):
            above_fold_ctas.append({"tag": e["tag"], "text": text, "y": round(y)})

    if above_fold_ctas:
        return None  # Booking CTA found above fold — no issue

    # Check if there are ANY CTAs above fold at all (even non-booking)
    any_above_fold = [
        e for e in dom_els
        if e.get("tag") in ("a", "button")
        and dom_on_screen(e)
        and 0 < dom_y(e) <= FOLD
        and (e.get("text") or "").strip()
    ]

    # Check if booking CTAs exist anywhere on page (below fold)
    below_fold_booking = [
        {"tag": e["tag"], "text": (e.get("text") or "").strip(), "y": round(dom_y(e))}
        for e in dom_els
        if e.get("tag") in ("a", "button")
        and dom_on_screen(e)
        and dom_y(e) > FOLD
        and BOOKING_RE.search(e.get("text") or "")
    ]

    findings = []
    evidence = []

    if not any_above_fold:
        findings.append(
            f"No clickable elements found above the fold ({FOLD}px). "
            "Visitors land on a passive page with no immediate action — "
            "conversion is impossible without scrolling."
        )
        evidence.append(f"Above-fold CTA count: 0 (fold = {FOLD}px)")
    elif not below_fold_booking:
        findings.append(
            f"No booking/contact CTA found anywhere on page. "
            "Visitors have no direct conversion path — they must hunt for a way to contact or book."
        )
        evidence.append("Booking CTAs found: 0 (page-wide scan)")
    else:
        # Booking CTAs exist but only below fold
        samples = ", ".join(f'"{c["text"][:40]}" (y={c["y"]}px)' for c in below_fold_booking[:3])
        findings.append(
            f"Booking CTAs exist but all are below the fold ({FOLD}px): {samples}. "
            "Users who don't scroll never see a conversion action — estimated 50-80% of mobile visitors."
        )
        evidence.append(f"Above-fold booking CTAs: 0")
        evidence.append(f"Below-fold booking CTAs: {len(below_fold_booking)} found")
        for c in below_fold_booking[:3]:
            evidence.append(f'  "{c["text"]}" at y={c["y"]}px')

    if not findings:
        return None

    return {
        "id": "cta_above_fold",
        "primary_element": "button",
        "screenshot_mode": "section",
        "visual_evidence": "above fold area",
        "title": "No booking CTA visible above the fold — conversion requires scrolling",
        "severity": "high",
        "confidence": "confirmed",
        "cro_impact": "Immediate conversion rate — visitors who don't scroll never convert",
        "revenue_signal": (
            "55% of visitors spend fewer than 15 seconds on a page (Chartbeat). "
            "Pages with a CTA above the fold convert 47% better than those requiring scroll "
            "(HubSpot CTA study). Every booking missed above the fold is direct revenue lost."
        ),
        "detection_source": "dom",
        "industry_tags": ["all"],
        "fix_effort": "hours",
        "affected_elements": below_fold_booking[:5] or [],
        "findings": findings,
        "fix": (
            "Place a primary booking/contact button in the hero section, above 600px. "
            "Use high-contrast colour (not the brand primary if it's low contrast). "
            "Label: '[verb] + [outcome]' — 'Book Free Consultation', 'Call Now', 'Schedule Today'. "
            "Sticky header with CTA also qualifies if it's always visible."
        ),
        "evidence": evidence,
    }
