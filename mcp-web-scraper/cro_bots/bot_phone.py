"""
Bot 10 — Phone CTA Clickability
Checks: phone numbers displayed as text without tel: href links.
CRO framing: on mobile, unlinked phone numbers = dead leads.
Works on: local_business, dental, medical, restaurant.
"""
from __future__ import annotations
import re
from .base import AuditParser

PHONE_RE = re.compile(r"\b(\+?1?\s*[\(\-]?\d{3}[\)\-\s]\s*\d{3}[\-\s]\d{4})\b")


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    phone_text_links = [
        lnk for lnk in p.links
        if PHONE_RE.search(lnk.get("text") or "")
        and not (lnk.get("href") or "").startswith("tel:")
    ]

    if not phone_text_links and not p.tel_hrefs:
        return None

    if p.tel_hrefs and not phone_text_links:
        return None

    if phone_text_links:
        findings = [
            f"{len(phone_text_links)} phone number link(s) use plain text instead of tel: href. "
            "Mobile users cannot tap to call — they must manually dial."
        ]
        evidence = [
            f"\"{lnk['text'][:40]}\" href=\"{lnk['href'][:40]}\""
            for lnk in phone_text_links[:4]
        ]

        return {
            "id":               "phone_cta",
            "title":            "Phone numbers are not clickable (missing tel: href)",
            "severity":         "high",
            "confidence":       "confirmed",
            "cro_impact":       "Mobile call conversion rate",
            "revenue_signal":   "tel: links increase mobile call-clicks by 35-60% (Google data).",
            "detection_source": "html",
            "industry_tags":    ["local_business", "dental", "medical", "restaurant"],
            "fix_effort":       "minutes",
            "affected_elements": [
                {"tag": "a", "text": lnk["text"][:40], "href": lnk["href"]}
                for lnk in phone_text_links[:4]
            ],
            "findings":  findings,
            "fix": (
                "Wrap every phone number in: <a href='tel:+1XXXXXXXXXX'>XXX-XXX-XXXX</a>. "
                "Ensure the number in href uses no spaces or dashes (tel:+12125551234)."
            ),
            "evidence": evidence,
        }

    return None
