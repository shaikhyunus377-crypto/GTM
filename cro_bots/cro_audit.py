#!/usr/bin/env python3
"""
cro_audit.py — CRO Audit Runner
================================
Runs all 10 CRO bots against a scraped page's artifacts.

Usage:
    python -m cro_bots.cro_audit --html page.html --dom dom_states.json
    python -m cro_bots.cro_audit --html page.html --dom dom_states.json --industry dental --output report.json
    python -m cro_bots.cro_audit --html page.html --industry all

Inputs come from the scraper:
    - full_rendered_inlined.html
    - dom_states.json
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .base import AuditParser
from . import (
    bot_h1_identity,
    bot_cta_above_fold,
    bot_phone_cta,
    bot_conversion_form,
    bot_social_proof,
    bot_trust_signals,
    bot_schema_local,
    bot_og_meta,
    bot_page_meta,
    bot_mobile_tap_targets,
)

BOTS = [
    ("h1_identity",       bot_h1_identity),
    ("cta_above_fold",    bot_cta_above_fold),
    ("phone_cta",         bot_phone_cta),
    ("conversion_form",   bot_conversion_form),
    ("social_proof",      bot_social_proof),
    ("trust_signals",     bot_trust_signals),
    ("schema_incomplete", bot_schema_local),
    ("og_social_meta",    bot_og_meta),
    ("page_meta",         bot_page_meta),
    ("mobile_tap_targets",bot_mobile_tap_targets),
]

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def run_audit(
    html: str,
    dom_elements: list,
    industry: str = "all",
    url: str = "",
) -> dict:
    p = AuditParser(html)
    issues = []
    errors = []

    for bot_id, bot_module in BOTS:
        try:
            result = bot_module.run(p, dom_elements)
            if result is not None:
                result.setdefault("origin", "bot")
                issues.append(result)
        except Exception as exc:
            errors.append({"bot": bot_id, "error": str(exc)})

    # Sort: high → medium → low, then alphabetical
    issues.sort(key=lambda x: (
        SEVERITY_ORDER.get(x.get("severity", "low"), 9),
        x.get("id", ""),
    ))

    return {
        "meta": {
            "engine":       "cro_audit",
            "version":      "1.0",
            "industry":     industry,
            "url":          url,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "bots_run":     len(BOTS),
            "bots_fired":   len(issues),
            "errors":       errors,
        },
        "summary": {
            "total_issues":   len(issues),
            "high":           sum(1 for i in issues if i.get("severity") == "high"),
            "medium":         sum(1 for i in issues if i.get("severity") == "medium"),
            "low":            sum(1 for i in issues if i.get("severity") == "low"),
        },
        "issues": issues,
    }


def main():
    ap = argparse.ArgumentParser(
        description="CRO Audit — run all 10 bots against scraped page artifacts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m cro_bots.cro_audit --html page.html --dom dom_states.json
  python -m cro_bots.cro_audit --html page.html --dom dom_states.json --industry dental --output report.json
        """
    )
    ap.add_argument("--html",     required=True, help="full_rendered_inlined.html from scraper")
    ap.add_argument("--dom",      default=None,  help="dom_states.json from scraper")
    ap.add_argument("--industry", default="all", help="dental | medical | ecommerce | saas | local_business | all")
    ap.add_argument("--url",      default="",    help="URL of the scraped page (for report metadata)")
    ap.add_argument("--output",   default=None,  help="Output JSON path (default: stdout)")
    args = ap.parse_args()

    html_path = Path(args.html)
    if not html_path.exists():
        print(f"Error: HTML file not found: {html_path}", file=sys.stderr)
        sys.exit(1)
    html = html_path.read_text(encoding="utf-8", errors="ignore")

    dom_elements = []
    if args.dom:
        dom_path = Path(args.dom)
        if dom_path.exists():
            dom_data = json.loads(dom_path.read_text(encoding="utf-8"))
            dom_elements = dom_data.get("elements", [])
        else:
            print(f"Warning: DOM file not found: {dom_path}", file=sys.stderr)

    report = run_audit(html, dom_elements, industry=args.industry, url=args.url)
    out = json.dumps(report, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        s = report["summary"]
        print(f"[cro_audit] {report['meta']['bots_fired']}/{report['meta']['bots_run']} bots fired → {args.output}")
        print(f"  HIGH:   {s['high']}")
        print(f"  MEDIUM: {s['medium']}")
        print(f"  LOW:    {s['low']}")
    else:
        print(out)


if __name__ == "__main__":
    main()
