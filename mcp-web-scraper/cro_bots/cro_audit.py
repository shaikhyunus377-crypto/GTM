"""
cro_audit.py — CRO Bot Runner
Runs all CRO bots against HTML + DOM elements and returns a unified report.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone

from .base import AuditParser
from . import (
    bot_h1,
    bot_headings,
    bot_dupe_ids,
    bot_og_meta,
    bot_schema,
    bot_page_meta,
    bot_lazy_images,
    bot_forms,
    bot_phone,
    bot_cta_above_fold,
    bot_social_proof,
    bot_trust_signals,
    bot_mobile_tap,
    bot_ai_cro,
)

BOTS = [
    bot_h1,
    bot_headings,
    bot_dupe_ids,
    bot_og_meta,
    bot_schema,
    bot_page_meta,
    bot_lazy_images,
    bot_forms,
    bot_phone,
    bot_cta_above_fold,
    bot_social_proof,
    bot_trust_signals,
    bot_mobile_tap,
    bot_ai_cro,     # AI semantic analysis — runs last; no-op without OPENAI_API_KEY
]

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def run_audit(
    html: str,
    dom_elements: list,
    industry: str = "all",
    url: str = "",
) -> dict:
    """
    Run all CRO bots on the given HTML and DOM elements.
    Returns a structured report dict.
    """
    # Parse HTML once
    parser = AuditParser()
    parser.feed(html)

    issues = []
    errors = []

    for bot in BOTS:
        try:
            result = bot.run(p=parser, dom_elements=dom_elements)
            if result:
                result.setdefault("origin", "bot")
                result.setdefault("confidence_score", 80)
                issues.append(result)
        except Exception as exc:
            errors.append({"bot": bot.__name__, "error": str(exc)})

    # Sort by severity
    issues.sort(key=lambda i: SEVERITY_ORDER.get(i.get("severity", "low"), 3))

    high   = sum(1 for i in issues if i.get("severity") == "high")
    medium = sum(1 for i in issues if i.get("severity") == "medium")
    low    = sum(1 for i in issues if i.get("severity") == "low")

    return {
        "meta": {
            "engine":       "cro_audit",
            "version":      "1.0",
            "url":          url,
            "industry":     industry,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "bots_run":     len(BOTS),
        },
        "summary": {
            "total":  len(issues),
            "high":   high,
            "medium": medium,
            "low":    low,
            "errors": len(errors),
        },
        "issues": issues,
        "errors": errors,
    }
