"""Bot 3 — Phone CTA Clickability
Checks: Phone numbers displayed as text but not wrapped in tel: href links.
CRO framing: On mobile, an un-tappable phone number is a broken conversion path.
Works on: all local business verticals.
"""
from __future__ import annotations
import re
from .base import AuditParser

# North American + international phone patterns
PHONE_TEXT_RE = re.compile(
    r"(?<![\d-])"  # not preceded by digit/dash
    r"(\+?1?[\s\-.]?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4})"
    r"(?![\d-])",  # not followed by digit/dash
    re.I,
)
TEL_HREF_RE  = re.compile(r'href=["\']tel:[+\d\s\-().]+["\']', re.I)
TEL_LINK_TEXT_RE = re.compile(r'<a[^>]+href=["\']tel:[^"\'>]+["\'][^>]*>([^<]+)</a>', re.I | re.S)


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    html = _reconstruct_html(p)
    # This bot works from the parser's raw data instead
    tel_hrefs = p.tel_hrefs  # already parsed

    # Find phone numbers in link text (not tel: href)
    # Strategy: look for <a> tags where the text looks like a phone number
    # but the href is NOT a tel: link
    phone_text_links = []
    for link in p.links:
        text = link.get("text", "").strip()
        href = link.get("href", "")
        if PHONE_TEXT_RE.search(text) and not href.startswith("tel:"):
            phone_text_links.append({"text": text, "href": href})

    # Find bare phone numbers in headings (often in hero sections)
    phone_in_headings = []
    for h in p.headings:
        if PHONE_TEXT_RE.search(h["text"]):
            phone_in_headings.append(h["text"].strip())

    findings = []
    evidence = []

    if not tel_hrefs and not phone_text_links and not phone_in_headings:
        # No phone on page at all — separate issue (trust signal), don't raise here
        return None

    if tel_hrefs and not phone_text_links and not phone_in_headings:
        # Phone correctly linked — no issue
        return None

    if phone_text_links:
        samples = ", ".join(f'"{l["text"]}"' for l in phone_text_links[:3])
        findings.append(
            f"Phone number(s) displayed as plain link text without tel: href: {samples}. "
            "Mobile users cannot tap-to-call — they must copy the number manually. "
            "Estimated 30-60% of local business leads arrive via phone."
        )
        for l in phone_text_links[:3]:
            evidence.append(f'Phone in link text (no tel:): "{l["text"]}" href="{l["href"]}"')

    if phone_in_headings and not tel_hrefs:
        for ph in phone_in_headings[:2]:
            findings.append(
                f'Phone number "{ph}" appears in a heading but has no tel: link anywhere on the page. '
                "This is a critical mobile conversion break — the most prominent number is untappable."
            )
            evidence.append(f'Phone in heading, no tel: href: "{ph}"')

    if not findings:
        return None

    return {
        "id": "phone_cta",
        "primary_element": "a",
        "screenshot_mode": "element",
        "visual_evidence": phone_text_links[0]["text"] if phone_text_links else phone_in_headings[0] if phone_in_headings else "",
        "title": "Phone number not tappable — missing tel: href breaks mobile call conversion",
        "severity": "high",
        "confidence": "confirmed",
        "cro_impact": "Mobile phone-call lead conversion",
        "revenue_signal": (
            "61% of mobile searchers call a business directly from search results (Google). "
            "Local businesses receive 30-60% of leads via phone. "
            "An un-tappable number on mobile converts at near-zero vs 15-30% for tap-to-call."
        ),
        "detection_source": "html",
        "industry_tags": ["local_business", "dental", "medical", "restaurant", "booking"],
        "fix_effort": "minutes",
        "affected_elements": phone_text_links[:5],
        "findings": findings,
        "fix": (
            "Wrap every phone number in a tel: link: "
            "<a href=\"tel:+13055551234\">305-555-1234</a>. "
            "Use E.164 format in href (no spaces/dashes). "
            "Apply to header, footer, hero, and contact section. "
            "Test on a real mobile device — tap to confirm dial intent fires."
        ),
        "evidence": evidence,
    }


def _reconstruct_html(p: AuditParser) -> str:
    """Not needed here — kept for interface consistency."""
    return ""
