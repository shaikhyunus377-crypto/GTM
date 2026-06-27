"""
cro_audit.py — CRO Bot Runner
Runs all CRO bots against HTML + DOM elements and returns a unified report.

Pipeline:
  1. classify site type (drives rule adaptation)
  2. run deterministic bots (objective issues)
  3. run AI bot (semantic observations)
"""
from __future__ import annotations
import json
from datetime import datetime, timezone

from .base import AuditParser
from .bot_site_classifier import classify
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
    bot_page_structure,
    bot_ai_cro,
)

# Bots that accept site_type kwarg
_SITE_TYPE_AWARE = {bot_social_proof, bot_page_structure, bot_ai_cro}

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
    bot_page_structure,
    bot_ai_cro,    # runs last — uses deterministic context
]

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def run_audit(
    html: str,
    dom_elements: list,
    industry: str = "all",
    url: str = "",
) -> dict:
    parser = AuditParser()
    parser.feed(html)

    # Classify site type — drives rule adaptation downstream
    site_type = classify(parser)
    # If caller supplied a specific industry, respect it over classifier
    effective_industry = industry if industry != "all" else site_type

    issues = []
    errors = []

    for bot in BOTS:
        try:
            kwargs: dict = {"p": parser, "dom_elements": dom_elements}
            if bot in _SITE_TYPE_AWARE:
                kwargs["site_type"] = site_type

            result = bot.run(**kwargs)
            if not result:
                continue

            batch = result if isinstance(result, list) else [result]
            for item in batch:
                item.setdefault("origin", "bot")
                item.setdefault("confidence_score", 80)
                issues.append(item)
        except Exception as exc:
            errors.append({"bot": getattr(bot, "__name__", str(bot)), "error": str(exc)})

    issues.sort(key=lambda i: SEVERITY_ORDER.get(i.get("severity", "low"), 3))

    high   = sum(1 for i in issues if i.get("severity") == "high")
    medium = sum(1 for i in issues if i.get("severity") == "medium")
    low    = sum(1 for i in issues if i.get("severity") == "low")

    return {
        "meta": {
            "engine":       "cro_audit",
            "version":      "1.1",
            "url":          url,
            "industry":     effective_industry,
            "site_type":    site_type,
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
