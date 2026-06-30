#!/usr/bin/env python3
"""
tech_intelligence.py — Website Tech-Stack Intelligence
======================================================
Runs AFTER the CRO audit. Scans the scraped (rendered, inlined) HTML for the
technologies, paid SaaS tools, ad pixels and commercial signals a business is
using, then scores its digital-marketing maturity.

Pure stdlib (re) — no external deps. Designed to be called with an HTML string:

    from tech_intelligence import run_tech
    intel = run_tech(html_string)

Returns a dict with:
  - per-category detected lists  (cms, page_builders, analytics, crm, ...)
  - summary{}                    flat one-value-per-field view for table/Excel
  - paid_tools[] / paid_tools_count
  - commercial_signals{}
  - commercial_maturity_score    (0-100)
  - qualification_signals[]       human-readable sales hooks
"""
from __future__ import annotations

import re

# ── Expanded tech-stack signature matrix (merged from reference engines) ──────
TECH_SIGNATURES: dict[str, dict[str, list[str]]] = {
    "cms": {
        "WordPress": ["wp-content", "wp-json", "wp-includes"],
        "Shopify":   ["cdn.shopify.com", "shopify.theme"],
        "Webflow":   ["webflow.js", "webflow.com"],
        "Wix":       ["_wixcssrules", "wix.com"],
        "Squarespace": ["squarespace.com", "static1.squarespace"],
        "Adobe Experience Manager (AEM)": ["aem-grid", "experiencefragment", "/content/dam/"],
    },
    "page_builders": {
        "Elementor": ["elementor-", "elementor/"],
        "Divi":      ["et_pb_"],
        "WPBakery":  ["wpb-content-wrapper", "vc_row"],
        "Beaver Builder": ["fl-builder"],
        "Bricks":    ["bricks-builder"],
    },
    "themes": {
        "Astra":         ["/themes/astra/"],
        "GeneratePress": ["generatepress"],
        "Kadence":       ["kadence"],
    },
    "analytics": {
        "Google Analytics":   ["google-analytics.com", "gtag(", "ga4"],
        "Google Tag Manager": ["googletagmanager.com", "gtm-"],
        "Adobe Tag Manager":  ["assets.adobedtm.com", "_satellite"],
    },
    "advertising": {
        "Meta Pixel":      ["connect.facebook.net/en_us/fbevents.js", "fbq("],
        "Google Ads":      ["googleadservices.com", "google_conversion", "aw-"],
        "TikTok Pixel":    ["analytics.tiktok.com", "ttq.track"],
        "LinkedIn Insight": ["snap.licdn.com"],
    },
    "crm": {
        "HubSpot":    ["js.hs-scripts.com", "hubspot.com", "hubspotutk"],
        "Salesforce": ["salesforce.com/common/", "sf-form", "embeddedservice_bootstrap"],
        "Zoho":       ["zoho"],
        "Pipedrive":  ["pipedrive"],
    },
    "forms": {
        "Contact Form 7": ["wpcf7"],
        "WPForms":        ["wpforms-form", "wpforms-submit"],
        "Gravity Forms":  ["gform_", "gravityforms"],
        "Typeform":       ["typeform.com/embed", "embed.typeform.com"],
        "Jotform":        ["jotform.com"],
        "Formstack":      ["formstack.com"],
    },
    "booking_tools": {
        "Calendly":          ["calendly"],
        "Acuity Scheduling": ["acuityscheduling"],
        "SimplyBook":        ["simplybook"],
        "JaneApp":           ["janeapp"],
        "NexHealth":         ["nexhealth"],
    },
    "chat_tools": {
        "Intercom": ["widget.intercom.io", "window.intercomsettings"],
        "Drift":    ["js.driftt.com", "drift.com/include"],
        "Tawk":     ["embed.tawk.to"],
        "Crisp":    ["client.crisp.chat"],
        "Zendesk":  ["static.zdassets.com"],
        "LiveChat": ["livechatinc.com"],
    },
    "heatmaps": {
        "Hotjar":           ["static.hotjar.com", "script.hotjar.com", "hjsettings"],
        "Microsoft Clarity": ["clarity.ms"],
        "Crazy Egg":        ["script.crazyegg.com"],
        "Lucky Orange":     ["luckyorange"],
    },
    "email_marketing": {
        "Mailchimp":      ["chimpstatic.com", "list-manage.com", "mc-embedded"],
        "Klaviyo":        ["static.klaviyo.com", "klaviyo"],
        "ActiveCampaign": ["activecampaign"],
        "Constant Contact": ["constantcontact"],
    },
    "business_tools": {
        "Google Maps API": ["maps.googleapis.com/maps/api"],
        "WhatsApp":        ["wa.me", "api.whatsapp.com"],
    },
}

# Categories that represent PAID / commercial SaaS the business pays for.
PAID_CATEGORIES = ["crm", "forms", "booking_tools", "chat_tools", "heatmaps", "email_marketing"]

# Free/standard form plugins that should NOT count as a "paid tool".
_FREE_FORMS = {"Contact Form 7"}


def _detect(html: str, signatures: dict[str, list[str]]) -> list[str]:
    """Return every tool in this category whose signature is present."""
    found = []
    for tool, patterns in signatures.items():
        for pat in patterns:
            if pat.lower() in html:
                found.append(tool)
                break
    return sorted(set(found))


def _commercial_signals(html: str) -> dict:
    return {
        "has_phone_number": bool(re.search(r"\+?\d[\d\s\-().]{7,}\d", html)),
        "has_email":        bool(re.search(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", html)),
        "has_whatsapp":     any(p in html for p in ["wa.me", "whatsapp", "api.whatsapp.com"]),
        "has_contact_page": any(p in html for p in ["contact-us", "contact us", "/contact"]),
        "has_booking_cta":  any(p in html for p in [
            "book now", "book a", "schedule", "get a quote", "request a",
            "free consultation", "book an appointment",
        ]),
        "has_review_section": any(p in html for p in [
            "google review", "g.page", "reviews", "testimonial", "what our customers",
        ]),
        "has_map_embed": any(p in html for p in [
            "maps.google.com", "google.com/maps", "maps.googleapis.com",
        ]),
    }


def run_tech(html: str) -> dict:
    """Detect the full tech stack from a rendered HTML string."""
    if not html:
        return {"error": "no HTML", "summary": {}, "paid_tools": [], "paid_tools_count": 0}

    h = html.lower()
    h = re.sub(r"<style.*?</style>", "", h, flags=re.DOTALL | re.IGNORECASE)

    cats = {cat: _detect(h, sigs) for cat, sigs in TECH_SIGNATURES.items()}

    # Paid tools = commercial SaaS categories (minus free form plugins) + ad pixels
    paid_tools: list[str] = []
    for cat in PAID_CATEGORIES:
        for tool in cats[cat]:
            if tool in _FREE_FORMS:
                continue
            if tool not in paid_tools:
                paid_tools.append(tool)
    for ad in cats["advertising"]:
        if ad not in paid_tools:
            paid_tools.append(ad)

    has_ga      = "Google Analytics" in cats["analytics"]
    has_meta    = "Meta Pixel" in cats["advertising"]
    has_gads    = "Google Ads" in cats["advertising"]

    # Flat one-value-per-field view (table / Excel / lead_intelligence_builder)
    first = lambda lst: lst[0] if lst else ""
    summary = {
        "cms":              first(cats["cms"]),
        "page_builder":     first(cats["page_builders"]),
        "theme":            first(cats["themes"]),
        "crm":              first(cats["crm"]),
        "paid_forms":       first([f for f in cats["forms"] if f not in _FREE_FORMS]),
        "booking_tools":    first(cats["booking_tools"]),
        "chat_tool":        first(cats["chat_tools"]),
        "heatmap":          first(cats["heatmaps"]),
        "email_marketing":  first(cats["email_marketing"]),
        "google_analytics": "Yes" if has_ga else "No",
        "meta_ads":         has_meta,
        "google_ads":       has_gads,
    }

    commercial_signals = _commercial_signals(h)

    # Maturity score (0-100)
    score = 20
    if summary["cms"]:           score += 10
    if has_ga:                   score += 15
    if has_meta:                 score += 10
    if has_gads:                 score += 10
    if summary["crm"]:           score += 15
    if summary["booking_tools"]: score += 10
    if summary["paid_forms"]:    score += 5
    if cats["chat_tools"]:       score += 5
    if cats["heatmaps"]:         score += 5
    if cats["email_marketing"]:  score += 5
    score = min(100, score)

    # Human-readable sales hooks
    signals = []
    if summary["cms"]:           signals.append(f"Built on {summary['cms']}")
    if summary["crm"]:           signals.append(f"Uses {summary['crm']} CRM")
    if summary["booking_tools"]: signals.append(f"Online booking via {summary['booking_tools']}")
    if has_meta or has_gads:     signals.append("Actively running paid ads (retargeting in place)")
    if cats["heatmaps"]:         signals.append("Tracks visitor behavior with heatmaps")
    if not has_ga:               signals.append("⚠️ No Google Analytics detected — flying blind on traffic")
    if not paid_tools:           signals.append("⚠️ No paid marketing/CRM tooling — low digital maturity")

    return {
        "meta":               {"engine": "tech_intelligence", "version": "1.0"},
        "cms":                cats["cms"],
        "page_builders":      cats["page_builders"],
        "themes":             cats["themes"],
        "analytics":          cats["analytics"],
        "advertising":        cats["advertising"],
        "crm":                cats["crm"],
        "forms":              cats["forms"],
        "booking_tools":      cats["booking_tools"],
        "chat_tools":         cats["chat_tools"],
        "heatmaps":           cats["heatmaps"],
        "email_marketing":    cats["email_marketing"],
        "business_tools":     cats["business_tools"],
        "commercial_signals": commercial_signals,
        "summary":            summary,
        "paid_tools":         paid_tools,
        "paid_tools_count":   len(paid_tools),
        "commercial_maturity_score": score,
        "qualification_signals":     signals,
    }


if __name__ == "__main__":
    import json, sys
    from pathlib import Path
    if len(sys.argv) < 2:
        print("Usage: python tech_intelligence.py <html_file>")
        sys.exit(1)
    html = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore")
    print(json.dumps(run_tech(html), indent=2))
