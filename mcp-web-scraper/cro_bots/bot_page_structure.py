"""
Bot — Page Structure Issues
Detects: hero carousel/slider, navigation overload, CTA hierarchy weakness.

These are layout/UX patterns that reduce conversion regardless of industry.
Returns a LIST of findings (one per detected issue).
"""
from __future__ import annotations
import re
from .base import AuditParser, dom_y, dom_visible, above_fold

# Carousel/slider signal patterns
CAROUSEL_RE = re.compile(
    r"slider|carousel|slick|swiper|owl[\-_]carousel|flexslider|"
    r"hero[\-_]slider|banner[\-_]slider|rotating|autoplay|auto[\-_]?play|"
    r"slide[\-_]?show|hero[\-_]?banner",
    re.I,
)

# Navigation item keywords
NAV_STRUCTURAL_RE = re.compile(
    r"home|about|services|contact|blog|news|resources|faq|portfolio|gallery|"
    r"careers|login|sign\s*in|sign\s*up|member|join|renew|find|search|events|"
    r"advocacy|education|ce\b|chapters?|society|public|donate|volunteer",
    re.I,
)


def _detect_carousel(p: AuditParser, html: str) -> dict | None:
    """Detect hero carousel/auto-rotating slider."""
    # Check class/id patterns in raw HTML
    carousel_in_html = bool(CAROUSEL_RE.search(html))

    # Also look for multiple hero-area images stacked at similar y
    if not carousel_in_html:
        return None

    return {
        "id":               "hero_carousel",
        "title":            "Hero uses auto-rotating carousel or slider",
        "severity":         "high",
        "confidence":       "confirmed",
        "confidence_score": 85,
        "cro_impact":       "Hero conversion rate + message clarity",
        "revenue_signal":   "Rotating carousels reduce CTA click-through by up to 89% vs static hero (Notre Dame study).",
        "detection_source": "html",
        "industry_tags":    ["all"],
        "fix_effort":       "days",
        "origin":           "bot",
        "affected_elements": [],
        "findings": [
            "The hero section uses an auto-rotating carousel or slider. "
            "Carousels split visitor attention across multiple messages, reduce time-on-primary-CTA, "
            "and can delay the booking action by cycling away from it. "
            "Animated sliders also conflict with motion-sensitivity accessibility guidelines."
        ],
        "fix": (
            "Replace the carousel with a single static hero: one headline, one sub-headline, "
            "one primary CTA. If multiple messages are needed, use a tabbed layout or "
            "scroll-triggered sections instead of auto-rotation."
        ),
        "evidence": [
            "Carousel/slider CSS class or JS library pattern detected in page HTML",
        ],
    }


def _detect_nav_overload(dom_elements: list) -> dict | None:
    """Detect navigation with too many top-level items."""
    # Find nav-level links: visible, y < 200px (header zone)
    header_links = [
        e for e in dom_elements
        if e.get("tag") == "a"
        and dom_visible(e)
        and 0 < dom_y(e) <= 200
        and NAV_STRUCTURAL_RE.search(e.get("text") or "")
    ]

    unique_labels = list({(e.get("text") or "").strip()[:40] for e in header_links if (e.get("text") or "").strip()})

    if len(unique_labels) < 7:
        return None

    return {
        "id":               "nav_overload",
        "title":            f"Navigation has {len(unique_labels)} competing items — attention diluted",
        "severity":         "medium",
        "confidence":       "confirmed",
        "confidence_score": 80,
        "cro_impact":       "Primary CTA click-through rate + visitor decision clarity",
        "revenue_signal":   "Hick's Law: decision time doubles with each additional choice. 7+ nav items increase bounce rate.",
        "detection_source": "dom",
        "industry_tags":    ["all"],
        "origin":           "bot",
        "fix_effort":       "hours",
        "affected_elements": [
            {"tag": "a", "text": l[:50], "y": 0} for l in unique_labels[:8]
        ],
        "findings": [
            f"{len(unique_labels)} navigation items detected above y=200px. "
            "When visitors face too many choices before the primary CTA, conversion drops. "
            "Each extra nav item competes with the Join/Book/Contact action."
        ],
        "fix": (
            "Reduce top navigation to 5-6 primary items max. "
            "Move secondary links (FAQ, Classifieds, Events) to a utility bar or footer. "
            "Ensure the primary conversion action (Join, Book, Get Started) is visually dominant "
            "in the header — different color, button-style, right-aligned."
        ),
        "evidence": [f"Nav item: '{l}'" for l in unique_labels[:8]],
    }


def _detect_cta_hierarchy(dom_elements: list) -> dict | None:
    """Detect too many equal-weight CTAs above fold — no clear primary action."""
    fold_ctas = [
        e for e in dom_elements
        if e.get("tag") in ("a", "button")
        and dom_visible(e)
        and 0 < dom_y(e) <= 900
    ]

    unique_cta_labels = list({
        (e.get("text") or "").strip()[:50]
        for e in fold_ctas
        if (e.get("text") or "").strip() and len((e.get("text") or "").strip()) > 2
    })

    # Only flag if many unique CTAs with no obvious primary
    if len(unique_cta_labels) < 6:
        return None

    return {
        "id":               "cta_hierarchy",
        "title":            f"{len(unique_cta_labels)} competing CTAs above the fold — no clear primary action",
        "severity":         "high",
        "confidence":       "confirmed",
        "confidence_score": 80,
        "cro_impact":       "First-impression conversion rate + CTA click-through",
        "revenue_signal":   "Pages with a single primary CTA convert 202% better than pages with multiple competing actions (Wordstream).",
        "detection_source": "dom",
        "industry_tags":    ["all"],
        "origin":           "bot",
        "fix_effort":       "hours",
        "affected_elements": [
            {"tag": "a", "text": l[:50], "y": 0} for l in unique_cta_labels[:6]
        ],
        "findings": [
            f"{len(unique_cta_labels)} unique CTA labels detected in the first 900px. "
            "When visitors see Join, Renew, Find Dentist, Member Savings, Events, "
            "and Classifieds with equal visual weight, they cannot identify the primary action. "
            "Decision paralysis increases and all CTAs underperform."
        ],
        "fix": (
            "Establish a clear CTA hierarchy: one Primary (high-contrast button, e.g. 'Join AzDA'), "
            "one Secondary (outline button, e.g. 'Renew Membership'), "
            "and move tertiary actions (Find Dentist, Events) to the navigation or below the fold. "
            "The primary CTA should be visually dominant within 1 second of landing."
        ),
        "evidence": [f"Above-fold CTA: '{l}'" for l in unique_cta_labels[:8]],
    }


def run(p: AuditParser, dom_elements: list | None = None, site_type: str = "local_business") -> list[dict] | None:
    dom_els = dom_elements or []
    html    = getattr(p, "raw_html", "")

    findings = []

    carousel = _detect_carousel(p, html)
    if carousel:
        findings.append(carousel)

    nav = _detect_nav_overload(dom_els)
    if nav:
        findings.append(nav)

    cta_hier = _detect_cta_hierarchy(dom_els)
    if cta_hier:
        findings.append(cta_hier)

    return findings if findings else None
