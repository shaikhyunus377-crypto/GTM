"""
Bot — CTA Above the Fold
Checks: no primary action CTA visible within first 800px (above the fold).

Detection strategy (in priority order):
  1. Any <button> element above the fold — buttons are CTAs by definition.
  2. Any <a> or <button> with booking/action keywords in text.
  3. Any <a> or <button> with CTA-pattern CSS classes (btn, cta, button-*, etc.).

Only fires if ALL three signals are absent above the fold AND there are CTAs
somewhere on the page (so we know the site has them — just misplaced).

CRO framing: if a visitor can't see a primary action without scrolling, conversion drops sharply.
Works on: all verticals.
"""
from __future__ import annotations
import re
from .base import dom_y, dom_visible, above_fold

# Broad booking / action intent keywords — intentionally generous to reduce false positives
BOOKING_RE = re.compile(
    r"book|schedul|appoint|reserv|consult|get\s*start|sign\s*up|free\s*trial|"
    r"contact|call\s*now|call\s*us|get\s*quote|request|today\b|now\b|"
    r"start\b|begin|try\s*(free|now|us)?|demo|chat|apply|join\b|buy\b|order\b|"
    r"enroll|register|see\s*(how|us|why)|learn\s*more|find\s*out|discover|"
    r"get\s*(a|an|your|free)|let['']?s\s*go|submit|send",
    re.I,
)

# CSS class patterns that signal a styled CTA button
CTA_CLASS_RE = re.compile(
    r"\b(btn|button|cta|call-to-action|hero.?btn|primary|action|booking|appointment)\b",
    re.I,
)

FOLD_PX = 800


def _classes(e: dict) -> str:
    cls = e.get("class") or []
    if isinstance(cls, list):
        return " ".join(cls)
    return str(cls)


def run(p=None, dom_elements: list | None = None) -> dict | None:
    if not dom_elements:
        return None

    interactive = [
        e for e in dom_elements
        if e.get("tag") in ("a", "button")
        and dom_visible(e)
        and dom_y(e) > 0
    ]

    if not interactive:
        return None

    def is_cta(e: dict) -> bool:
        text = (e.get("text") or "").strip()
        # Buttons (not just links) are primary CTAs unless they're tiny icon-only buttons
        if e.get("tag") == "button" and len(text) > 1:
            return True
        # Keyword match in text
        if BOOKING_RE.search(text):
            return True
        # CTA CSS class
        if CTA_CLASS_RE.search(_classes(e)):
            return True
        return False

    all_ctas   = [e for e in interactive if is_cta(e)]
    above_ctas = [e for e in all_ctas   if above_fold(e, FOLD_PX)]

    # If there are CTAs above the fold → no issue
    if above_ctas:
        return None

    # If there are no CTAs anywhere → not this bot's job to report (conversion_form covers it)
    if not all_ctas:
        return None

    samples = [
        {"tag": e.get("tag"), "text": (e.get("text") or "")[:40], "y": dom_y(e)}
        for e in all_ctas[:4]
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
            f"Action CTAs exist on the page ({len(all_ctas)} found) but none appear "
            f"within the first {FOLD_PX}px. "
            f"The earliest is at y={dom_y(all_ctas[0])}px."
        ],
        "fix": (
            "Move at least one primary CTA (Book, Schedule, Get Started, Call Now) "
            "into the hero section above the fold (y < 600px). "
            "A sticky header with a CTA button is an acceptable alternative."
        ),
        "evidence": [
            f"Nearest CTA: \"{(all_ctas[0].get('text') or '')[:40]}\" "
            f"({all_ctas[0].get('tag')}) at y={dom_y(all_ctas[0])}px"
        ],
    }
