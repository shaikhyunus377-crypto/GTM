"""Bot 8 — OG/Twitter Social Meta Tags
Checks: Missing og:title, og:description, og:image, twitter:card.
CRO framing: Social shares without OG tags show generic link previews — kill click-through.
Works on: all verticals.
"""
from __future__ import annotations
from .base import AuditParser

CRITICAL_OG = ["title", "description", "image"]
RECOMMENDED_OG = ["url", "type"]


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    og = p.og_tags
    tw = p.twitter_tags

    missing_og = [k for k in CRITICAL_OG if k not in og or not og[k]]
    missing_tw_card = "card" not in tw

    if not missing_og and not missing_tw_card:
        return None  # All good

    findings = []
    evidence = []

    if missing_og:
        fields = ", ".join(f"og:{f}" for f in missing_og)
        findings.append(
            f"Missing critical Open Graph tags: {fields}. "
            "When this page is shared on Facebook, LinkedIn, WhatsApp, or iMessage, "
            "it shows a blank grey box instead of a branded preview — "
            "click-through rates drop by 50-80% vs a page with OG tags."
        )
        for f in missing_og:
            evidence.append(f"og:{f}: missing")

    if og.get("image") and not og["image"].startswith("http"):
        findings.append(
            f"og:image has a relative URL: '{og['image'][:60]}'. "
            "Social platforms require absolute URLs — the image will not load in link previews."
        )
        evidence.append(f"og:image: relative URL ('{og['image'][:60]}')")

    if missing_tw_card:
        findings.append(
            "Missing twitter:card tag. Twitter/X will show a plain text link instead of "
            "a rich card — significantly lower engagement for any Twitter/X shares."
        )
        evidence.append("twitter:card: missing")

    if not findings:
        return None

    # Report what IS present for context
    if og:
        evidence.append(f"OG tags present: {list(og.keys())}")
    if tw:
        evidence.append(f"Twitter tags present: {list(tw.keys())}")

    return {
        "id": "og_social_meta",
        "primary_element": "meta",
        "screenshot_mode": "fullpage",
        "visual_evidence": "page <head> source",
        "title": "Missing OG/Twitter meta tags — social shares show broken previews",
        "severity": "medium",
        "confidence": "confirmed",
        "cro_impact": "Social sharing click-through rate + referral traffic",
        "revenue_signal": (
            "Social link previews with OG tags get 3x more clicks than plain URLs "
            "(Hootsuite, 2023). For local businesses, patient referrals via WhatsApp and "
            "Facebook are primary word-of-mouth channels — broken previews kill this pipeline."
        ),
        "detection_source": "html",
        "industry_tags": ["all"],
        "fix_effort": "minutes",
        "affected_elements": [],
        "findings": findings,
        "fix": (
            "Add to <head>:\n"
            '<meta property="og:title" content="Your Practice Name — Service | City" />\n'
            '<meta property="og:description" content="150-character description" />\n'
            '<meta property="og:image" content="https://yourdomain.com/og-image.jpg" /> (1200x630px)\n'
            '<meta property="og:url" content="https://yourdomain.com/" />\n'
            '<meta name="twitter:card" content="summary_large_image" />\n'
            "Validate with Facebook Sharing Debugger and Twitter Card Validator."
        ),
        "evidence": evidence,
    }
