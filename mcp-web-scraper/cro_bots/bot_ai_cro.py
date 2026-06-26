"""
Bot — AI CRO Analyst (GPT-4o-mini)
Analyzes hero CTA quality, value proposition, urgency, offer clarity,
and social proof placement using semantic understanding.

Only fires when OPENAI_API_KEY is set. Falls back gracefully if not.
Returns 0–3 specific, high-confidence findings. Never returns vague issues.
"""
from __future__ import annotations
import json
import os
import re
from .base import AuditParser, dom_y, dom_visible, above_fold

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Absolute minimum evidence threshold — if GPT returns fewer than 2 tokens
# of justification, the finding is dropped.
MIN_JUSTIFICATION_LEN = 20


def _extract_page_context(p: AuditParser, dom_elements: list) -> dict:
    """Pull the key signals GPT needs to reason about CRO quality."""
    headings = p.headings if hasattr(p, "headings") else []

    h1 = next((h["text"] for h in headings if h.get("tag") == "h1"), "")
    hero_headings = [h.get("text", "") for h in headings[:8]]

    # Above-fold CTAs (first 900px)
    fold_ctas = []
    for e in (dom_elements or []):
        if e.get("tag") in ("a", "button") and dom_visible(e):
            y = dom_y(e)
            if 0 < y <= 900:
                text = (e.get("text") or "").strip()
                if text and len(text) < 80:
                    fold_ctas.append({"tag": e.get("tag"), "text": text, "y": y})

    # Unique visible CTA texts for label analysis
    all_cta_texts = []
    for e in (dom_elements or []):
        if e.get("tag") in ("a", "button") and dom_visible(e) and dom_y(e) > 0:
            text = (e.get("text") or "").strip()
            if text and len(text) < 80:
                all_cta_texts.append(text)

    # Social proof keyword presence in raw HTML
    social_signals = []
    html_lower = getattr(p, "raw_html", "").lower()
    for kw in ("review", "rating", "testimonial", "google", "stars", "5-star", "award", "certified"):
        if kw in html_lower:
            social_signals.append(kw)

    # Schema @type(s)
    schema_types = []
    for raw in getattr(p, "schema_raw", []):
        try:
            obj = json.loads(raw)
            t = obj.get("@type") or (obj.get("@graph") or [{}])[0].get("@type", "")
            if t:
                schema_types.append(t if isinstance(t, str) else str(t))
        except Exception:
            pass

    phone = getattr(p, "tel_hrefs", [])

    return {
        "page_title":     getattr(p, "title_text", "").strip(),
        "meta_desc":      getattr(p, "meta_desc", "").strip(),
        "h1":             h1,
        "hero_headings":  hero_headings,
        "fold_ctas":      fold_ctas[:10],
        "all_cta_sample": list(dict.fromkeys(all_cta_texts))[:15],
        "social_signals": social_signals,
        "schema_types":   schema_types,
        "has_form":       bool(getattr(p, "forms", [])),
        "has_phone":      bool(phone),
    }


SYSTEM_PROMPT = """You are a senior CRO (Conversion Rate Optimisation) analyst.
You audit landing pages for conversion problems that directly reduce revenue.

Rules:
- Only report findings you are CERTAIN are problems, not speculative improvements
- Each finding must name a SPECIFIC element or missing element found on this page
- Do NOT flag things that might already exist but weren't extracted (e.g. do not guess)
- Do NOT repeat what schema or other bots already detect
- Maximum 3 findings total; fewer is better if evidence is weak
- Each finding severity: "high" | "medium" | "low"
- Each finding must have a concrete fix a developer can implement in hours

Respond ONLY with valid JSON, no markdown, no commentary:
{
  "findings": [
    {
      "id": "snake_case_unique_id",
      "title": "One-line title",
      "severity": "high|medium|low",
      "finding": "One paragraph explaining the specific problem with evidence from the page",
      "fix": "Specific actionable fix",
      "revenue_signal": "One stat or principle (optional, leave empty string if unsure)"
    }
  ]
}
"""

USER_PROMPT_TEMPLATE = """Audit this page for CRO problems. Focus on:
1. Hero CTA — is the primary action clear, urgent, and benefit-led?
2. Value proposition — does the hero communicate WHY this business over competitors?
3. Offer clarity — is there a specific offer, price, or incentive visible?
4. CTA quality — do above-fold CTAs use generic labels like "Submit" or "Click Here"?
5. Social proof proximity — is there ANY social proof near the primary CTA?

Page data:
{context}

Respond only if you find genuine, specific problems. If the page looks good, return {{"findings": []}}.
"""


def _call_openai(context: dict) -> list[dict]:
    """Call GPT-4o-mini and return list of finding dicts."""
    try:
        import urllib.request
        import urllib.error

        context_str = json.dumps(context, indent=2)
        payload = json.dumps({
            "model": "gpt-4o-mini",
            "temperature": 0.1,
            "max_tokens": 800,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": USER_PROMPT_TEMPLATE.format(context=context_str)},
            ],
            "response_format": {"type": "json_object"},
        }).encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {OPENAI_API_KEY}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read())

        content = body["choices"][0]["message"]["content"]
        parsed  = json.loads(content)
        return parsed.get("findings", [])

    except Exception as exc:
        return [{"_error": str(exc)}]


def run(p: AuditParser | None = None, dom_elements: list | None = None) -> dict | None:
    if not OPENAI_API_KEY:
        return None  # Silently skip — no key configured

    ctx = _extract_page_context(p or AuditParser(), dom_elements or [])

    raw_findings = _call_openai(ctx)
    if not raw_findings:
        return None

    # Filter out any error entries or findings with no real justification
    valid = [
        f for f in raw_findings
        if isinstance(f, dict)
        and "id" in f
        and "title" in f
        and len(f.get("finding", "")) >= MIN_JUSTIFICATION_LEN
        and "_error" not in f
    ]

    if not valid:
        return None

    # Use highest severity from the set
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    valid.sort(key=lambda f: sev_rank.get(f.get("severity", "low"), 2))
    top_sev = valid[0].get("severity", "medium")

    # Build findings list and evidence
    findings_text = [f["finding"] for f in valid]
    evidence      = [f["title"]   for f in valid]
    fix_texts     = [f["fix"]     for f in valid if f.get("fix")]
    revenue_sigs  = [f["revenue_signal"] for f in valid if f.get("revenue_signal")]

    return {
        "id":               "ai_cro_analysis",
        "title":            "AI CRO analysis identified conversion friction",
        "severity":         top_sev,
        "confidence":       "confirmed",
        "confidence_score": 80,
        "cro_impact":       "Hero conversion rate + first-impression quality",
        "revenue_signal":   revenue_sigs[0] if revenue_sigs else "",
        "detection_source": "ai",
        "industry_tags":    ["all"],
        "fix_effort":       "hours",
        "origin":           "ai_bot",
        "affected_elements": [],
        "findings":         findings_text,
        "fix":              " | ".join(fix_texts),
        "evidence":         evidence,
        "ai_findings":      valid,  # full structured list for modal rendering
    }
