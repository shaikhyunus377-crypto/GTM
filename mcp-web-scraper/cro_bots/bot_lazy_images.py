"""
Bot 8 — Lazy Load Image Integrity
Checks: images with src="" and data-src (broken lazy load), truly broken images (no src, no data-src).
CRO framing: broken images destroy trust and product/service presentation.
Works on: all verticals.
"""
from __future__ import annotations
from .base import AuditParser


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    lazy_broken  = [img for img in p.images if not img["src"] and img["data_src"]]
    truly_broken = [img for img in p.images if not img["src"] and not img["data_src"]]

    findings = []
    evidence  = []

    if lazy_broken:
        findings.append(
            f"{len(lazy_broken)} image(s) have src=\"\" with data-src set — "
            "they are broken without JavaScript or a lazy-load observer. "
            "Server-side rendered HTML shows blank boxes."
        )
        evidence += [
            f"src=\"\" data-src=\"{img['data_src'][:60]}\" alt=\"{img['alt'] or '(missing)'}\""
            for img in lazy_broken[:4]
        ]

    if truly_broken:
        findings.append(
            f"{len(truly_broken)} image(s) have no src and no data-src — "
            "these images cannot load under any condition."
        )
        evidence += [f"alt=\"{img['alt'] or '(missing)'}\" — no src" for img in truly_broken[:4]]

    if not findings:
        return None

    return {
        "id":               "lazy_load_images",
        "title":            f"{len(lazy_broken) + len(truly_broken)} image(s) broken or lazy-load dependent",
        "severity":         "medium",
        "confidence":       "confirmed",
        "cro_impact":       "Page trust + product/service presentation",
        "revenue_signal":   "Broken images reduce trust scores by 47% (Baymard Institute).",
        "detection_source": "html",
        "industry_tags":    ["all"],
        "fix_effort":       "hours",
        "affected_elements": [],
        "findings":         findings,
        "fix": (
            "For lazy-load images: use <img src='placeholder.jpg' data-src='real.jpg'> "
            "AND ensure IntersectionObserver JS runs on all browsers. "
            "Add native lazy: <img loading='lazy' src='real.jpg'>. "
            "Remove truly broken image tags or replace with valid src."
        ),
        "evidence": evidence,
    }
