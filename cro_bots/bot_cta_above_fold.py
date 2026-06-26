"""
Bot — CTA Above the Fold
Checks: no booking/action CTA visible within first 800px (above the fold).
CRO framing: if a visitor can't see a primary action without scrolling, conversion drops sharply.
Works on: all verticals.
"""
from __future__ import annotations
import re
from .base import dom_y, dom_visible, above_fold

BOOKING_RE = re.compile(
    r"book|schedul|appoint|reserv|consult|get\s*start|sign\s*up|free\s*trial|contact|call\s*now|get\s*quote|request",
    re.I,
)

FOLD_PX = 800


def run(p=None, dom_elements: list | None = None) -> dict | None:
    if not dom_elements:
        return None

    booking_ctas = [
        e for e in dom_elements
        if e.get("tag") in ("a", "button")
        and BOOKING_RE.search(e.get("text") or "")
        and dom_visible(e)
        and dom_y(e) > 0
    ]

    above = [e for e in booking_ctas if above_fold(e, FOLD_PX)]

    if above:
        return None

    if not booking_ctas:
        return None

    samples = [
        {"tag": e.get("tag"), "text": (e.get("text") or "")[:40], "y": dom_y(e)}
        for e in booking_ctas[:4]
    ]

    return {
        "id":               "cta_above_fold",
        "title":            "No primary action CTA is visible above the fold",
        "severity":         "high",
        "confidence":       "confirmed",
        "cro_impact":       "First-impression conversion rate",
        "revenue_signal":   "CTAs visible above the fold increase conversions by 41% (Unbounce).",
        "detection_source": "dom",
        "industry_tags":    ["all"],
        "fix_effort":       "hours",
        "affected_elements": samples,
        "findings": [
            f"Booking/action CTAs exist (found {len(booking_ctas)}) but none are above the fold "
            f"(first {FOLD_PX}px). The earliest is at y={dom_y(booking_ctas[0])}px."
        ],
        "fix": (
            "Move at least one primary CTA (Book, Schedule, Get Started) into the hero section. "
            "Target y < 600px. Use a sticky header or floating button as a fallback."
        ),
        "evidence": [
            f"Nearest booking CTA: \"{(booking_ctas[0].get('text') or '')[:40]}\" at y={dom_y(booking_ctas[0])}px"
        ],
    }
