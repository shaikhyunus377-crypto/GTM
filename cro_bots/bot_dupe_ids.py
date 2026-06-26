"""
Bot 3 — Duplicate IDs
Checks: same id attribute on multiple visible elements.
CRO framing: duplicate IDs break JS (querySelector returns only first), anchor links, and form labels.
Works on: all verticals.
"""
from __future__ import annotations
from collections import Counter
from .base import dom_y, dom_visible


def run(p=None, dom_elements: list | None = None) -> dict | None:
    if not dom_elements:
        return None

    visible = [
        e for e in dom_elements
        if dom_y(e) > 0 and dom_visible(e) and e.get("id")
    ]

    id_counts = Counter(e["id"] for e in visible)
    dupes = {k: v for k, v in id_counts.items() if v > 1}

    if not dupes:
        return None

    findings = [
        f"{len(dupes)} duplicate ID(s) found among visible elements: {list(dupes.keys())[:4]}. "
        "querySelector() returns only the first match — JS breaks silently. "
        "Anchor links and form <label for=> skip to the wrong element."
    ]
    evidence = [f"id=\"{k}\" appears {v} times" for k, v in list(dupes.items())[:6]]

    return {
        "id":               "duplicate_ids",
        "title":            f"{len(dupes)} duplicate HTML id attribute(s) found",
        "severity":         "medium",
        "confidence":       "confirmed",
        "cro_impact":       "Form functionality + JS event binding + anchor links",
        "revenue_signal":   "Duplicate IDs break form submissions — directly kills conversions.",
        "detection_source": "dom",
        "industry_tags":    ["all"],
        "fix_effort":       "hours",
        "affected_elements": [{"id": k, "count": v} for k, v in dupes.items()],
        "findings":         findings,
        "fix": (
            "Each id attribute must be unique within a page. "
            "For repeated components (e.g. carousels), use class instead of id, "
            "or append a suffix: id='form-hero', id='form-footer'."
        ),
        "evidence": evidence,
    }
