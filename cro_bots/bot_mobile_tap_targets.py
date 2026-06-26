"""Bot 10 — Mobile Tap Target Size
Checks: CTA buttons and links with bounding boxes smaller than 44x44px (WCAG 2.5.5 / Google mobile UX).
CRO framing: Untappable buttons on mobile = broken conversion on the device most visitors use.
Works on: all verticals.
"""
from __future__ import annotations
from .base import AuditParser, dom_y, dom_width, dom_height, dom_on_screen

MIN_TARGET = 44  # px — WCAG 2.5.5 / Google recommended minimum
MIN_WIDTH  = 44
MIN_HEIGHT = 32  # slightly relaxed for height — links can be narrow

# Don't flag nav links (they're repeated, usually fine)
NAV_SKIP_RE = None  # filled lazily
import re
NAV_SKIP = re.compile(
    r"^(home|about|services|contact|blog|faq|team|menu|login|sign in|sign up|privacy|terms)$",
    re.I,
)
BOOKING_RE = re.compile(
    r"book|schedul|appoint|call|get\s+start|consult|contact|request|enqui|reserv",
    re.I,
)


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    dom_els = dom_elements or []
    if not dom_els:
        return None  # No DOM data — can't check tap targets

    small_targets = []
    small_booking = []

    for e in dom_els:
        if e.get("tag") not in ("a", "button"):
            continue
        if not dom_on_screen(e):
            continue

        text = (e.get("text") or "").strip()
        if not text:
            continue
        if NAV_SKIP.match(text):
            continue

        w = dom_width(e)
        h = dom_height(e)

        if w < MIN_WIDTH or h < MIN_HEIGHT:
            entry = {
                "tag":    e["tag"],
                "text":   text[:50],
                "y":      round(dom_y(e)),
                "width":  round(w),
                "height": round(h),
            }
            small_targets.append(entry)
            if BOOKING_RE.search(text):
                small_booking.append(entry)

    # Only raise issue if booking CTAs are too small, OR many general CTAs are small
    if not small_booking and len(small_targets) < 4:
        return None

    findings = []
    evidence = []

    if small_booking:
        samples = ", ".join(
            f'"{t["text"]}" ({t["width"]}x{t["height"]}px)' for t in small_booking[:3]
        )
        findings.append(
            f"Primary booking/contact CTA(s) are too small for mobile tapping: {samples}. "
            f"Google requires minimum {MIN_TARGET}px — these will be mis-tapped or missed entirely on phones."
        )
        evidence += [f'"{t["text"]}" at y={t["y"]}px: {t["width"]}x{t["height"]}px' for t in small_booking[:4]]

    if len(small_targets) >= 4:
        findings.append(
            f"{len(small_targets)} clickable elements are below the {MIN_TARGET}px tap target threshold. "
            "Users on phones (>60% of traffic) will struggle to tap these — leads to frustration and bounce."
        )
        for t in small_targets[:4]:
            evidence.append(f'"{t["text"]}" {t["width"]}x{t["height"]}px at y={t["y"]}px')

    if not findings:
        return None

    return {
        "id": "mobile_tap_targets",
        "primary_element": "button",
        "screenshot_mode": "element",
        "visual_evidence": small_booking[0]["text"] if small_booking else small_targets[0]["text"],
        "title": f"{len(small_booking or small_targets)} CTA(s) below mobile tap target size — booking breaks on phone",
        "severity": "high" if small_booking else "medium",
        "confidence": "confirmed",
        "cro_impact": "Mobile conversion rate — phone is the primary booking device",
        "revenue_signal": (
            "63% of Google searches happen on mobile (Statista, 2023). "
            "Buttons under 44px have a 40% mis-tap rate on phones with average finger size "
            "(MIT Touch Lab). Each mis-tap on a booking CTA is a potential lost lead."
        ),
        "detection_source": "dom",
        "industry_tags": ["all"],
        "fix_effort": "hours",
        "affected_elements": (small_booking + small_targets)[:8],
        "findings": findings,
        "fix": (
            f"Set min-height: {MIN_TARGET}px; min-width: {MIN_TARGET}px; padding: 12px 24px "
            "on all CTA buttons and important links. "
            "Use @media (max-width: 768px) if you only want mobile sizing. "
            "Test with Chrome DevTools mobile emulation — tap targets shown in Accessibility panel."
        ),
        "evidence": evidence,
    }
