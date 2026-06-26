"""
Bot 4 — CTA Label Quality
Checks: ALL CAPS, repeated labels, phone numbers as CTAs, generic labels.
CRO framing: every CTA label is a micro-copy conversion decision.
Works on: all verticals.
"""
from __future__ import annotations
import re
from collections import Counter
from .base import dom_y, dom_visible

GENERIC_LABELS = {
    "click here", "read more", "learn more", "more", "here",
    "link", "button", "click", "go", "submit", "ok", "yes", "no",
}
PHONE_RE = re.compile(r"^\+?[\d\s\-().]{7,}$")

NAV_LABELS = {
    "HOME", "ABOUT", "ABOUT US", "OUR TEAM", "TEAM",
    "SERVICES", "OUR SERVICES", "WHAT WE DO",
    "CONTACT", "CONTACT US", "GET IN TOUCH",
    "BLOG", "NEWS", "RESOURCES", "FAQ", "FAQS",
    "PORTFOLIO", "GALLERY", "WORK", "CASE STUDIES",
    "PRIVACY POLICY", "TERMS", "TERMS OF SERVICE", "SITEMAP",
    "PATIENT PORTAL", "LOGIN", "LOG IN", "SIGN IN", "SIGN UP",
    "MENU", "LOCATIONS", "LOCATION", "CAREERS", "JOBS",
}


def run(p=None, dom_elements: list | None = None) -> dict | None:
    if not dom_elements:
        return None

    cta_els = [
        e for e in dom_elements
        if e.get("tag") in ("a", "button")
        and dom_visible(e)
        and dom_y(e) > 0
    ]

    labels       = [(e.get("text") or "").strip() for e in cta_els if (e.get("text") or "").strip()]
    label_counts = Counter(labels)

    all_caps = sorted({
        l for l in labels
        if l.upper() not in NAV_LABELS
        and l == l.upper()
        and len(l) > 2
        and re.search(r"[A-Z]", l)
        and not PHONE_RE.match(l)
    })

    repeated    = [(l, c) for l, c in label_counts.items() if c >= 3 and not PHONE_RE.match(l)]
    phone_labels = [l for l in labels if PHONE_RE.match(l)]
    generics    = [l for l in labels if l.lower() in GENERIC_LABELS]

    findings = []
    evidence  = []

    if all_caps:
        findings.append(
            f"{len(all_caps)} CTA label(s) use ALL CAPS — "
            "screen readers spell them letter-by-letter. "
            "Use CSS text-transform:uppercase instead."
        )
        evidence += [f"ALL CAPS: \"{l}\"" for l in all_caps[:6]]

    if repeated:
        sample = ", ".join(f"\"{l}\" (×{c})" for l, c in repeated[:3])
        findings.append(
            f"Labels repeated 3+ times with no context: {sample}. "
            "Analytics cannot tell which instance drove the conversion."
        )
        evidence += [f"\"{l}\" repeated {c}×" for l, c in repeated[:3]]

    if generics:
        unique_generics = list({l.lower() for l in generics})
        findings.append(
            f"Generic labels found: {unique_generics[:4]}. "
            "Users don't know what they'll get."
        )

    if len(all_caps) <= 2 and not repeated and not generics:
        return None

    return {
        "id":               "cta_label_quality",
        "title":            "CTA labels fracture click intent — ALL CAPS, repeated, or context-free",
        "severity":         "medium",
        "confidence":       "confirmed",
        "cro_impact":       "Click-through rate + analytics attribution",
        "revenue_signal":   "Descriptive CTAs outperform generic labels by 14–202% in A/B tests.",
        "detection_source": "dom",
        "industry_tags":    ["all"],
        "fix_effort":       "hours",
        "affected_elements": [
            {"tag": e.get("tag"), "text": (e.get("text") or "")[:60], "y": dom_y(e)}
            for e in cta_els
            if (e.get("text") or "").strip().upper() == (e.get("text") or "").strip()
            and len((e.get("text") or "").strip()) > 2
        ][:10],
        "findings": findings,
        "fix": (
            "Write every CTA as: [verb] + [specific outcome]. "
            "'Book free consultation', 'See pricing', 'Call our team'. "
            "Apply CSS text-transform:uppercase for visual style — HTML stays sentence-case."
        ),
        "evidence": evidence,
    }
