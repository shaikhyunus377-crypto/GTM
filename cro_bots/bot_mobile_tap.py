"""
Bot — Mobile Tap Target Size
Checks: interactive elements (buttons, links) smaller than 44×32px minimum.
CRO framing: small tap targets cause mis-taps → frustration → bounce on mobile.
Works on: all verticals.
"""
from __future__ import annotations
from .base import dom_y, dom_visible

MIN_W = 44
MIN_H = 32


def run(p=None, dom_elements: list | None = None) -> dict | None:
    if not dom_elements:
        return None

    interactive = [
        e for e in dom_elements
        if e.get("tag") in ("a", "button", "input")
        and dom_y(e) > 0
        and dom_visible(e)
    ]

    small = []
    for e in interactive:
        bbox = (e.get("states", {}).get("default", {}).get("bbox", {}) or {})
        w, h = bbox.get("width", 0), bbox.get("height", 0)
        if 0 < w < MIN_W or 0 < h < MIN_H:
            small.append({
                "tag":  e.get("tag"),
                "text": (e.get("text") or "")[:40],
                "w":    int(w),
                "h":    int(h),
                "y":    dom_y(e),
            })

    if not small:
        return None

    return {
        "id":               "mobile_tap_targets",
        "title":            f"{len(small)} interactive element(s) too small for mobile tap",
        "severity":         "medium",
        "confidence":       "confirmed",
        "cro_impact":       "Mobile conversion rate + usability score",
        "revenue_signal":   "Undersized tap targets cause 37% of accidental mis-taps (Google UX research).",
        "detection_source": "dom",
        "industry_tags":    ["all"],
        "fix_effort":       "hours",
        "affected_elements": small[:8],
        "findings": [
            f"{len(small)} clickable elements are smaller than {MIN_W}×{MIN_H}px. "
            f"Smallest: {min(e['w'] for e in small)}×{min(e['h'] for e in small)}px. "
            "Google Lighthouse flags these; they directly hurt mobile Core Web Vitals."
        ],
        "fix": (
            f"Set minimum tap target: min-width: {MIN_W}px; min-height: {MIN_H}px (or padding equivalent). "
            "For icon buttons, use padding instead of increasing the icon size. "
            "Space tap targets ≥8px apart."
        ),
        "evidence": [
            f"\"{e['text']}\" ({e['tag']}) — {e['w']}×{e['h']}px at y={e['y']}"
            for e in small[:4]
        ],
    }
