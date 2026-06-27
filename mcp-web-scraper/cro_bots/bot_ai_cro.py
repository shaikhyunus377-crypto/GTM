"""
Bot — AI CRO Analyst (GPT-4o-mini)
Returns a LIST of atomic issues, each independently scoreable by Wolf.

Design principles:
- Each finding is one specific, verifiable observation
- Evidence must quote actual page content (CTAs detected, headline text, etc.)
- Confidence is calibrated per finding type — subjective CRO never > 85
- Finding IDs are stable slugs so Wolf can evaluate them individually
- No key is set without concrete grounding in the extracted page context
"""
from __future__ import annotations
import json
import os
from .base import AuditParser, dom_y, dom_visible

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Calibrated confidence ceilings by finding category
CONFIDENCE_CEILING = {
    "hero_value_proposition":   85,
    "hero_primary_cta_missing": 80,
    "hero_action_clarity":      65,  # most subjective
    "offer_clarity":            80,
    "social_proof_near_cta":    75,
}
DEFAULT_CONFIDENCE_CEILING = 75


def _extract_page_context(p: AuditParser, dom_elements: list) -> dict:
    headings = getattr(p, "headings", [])
    h1 = next((h["text"] for h in headings if h.get("tag") == "h1"), "")

    # Above-fold CTAs — the raw signals the AI will cite in evidence
    fold_ctas = []
    for e in (dom_elements or []):
        if e.get("tag") in ("a", "button") and dom_visible(e):
            y = dom_y(e)
            if 0 < y <= 900:
                text = (e.get("text") or "").strip()
                if text and 1 < len(text) < 80:
                    fold_ctas.append({"tag": e.get("tag"), "text": text, "y": y})

    # First booking-intent CTA anywhere on page
    booking_kw = ("book", "schedul", "appoint", "reserv", "consult", "get start",
                  "sign up", "free trial", "call now", "get quote", "request",
                  "buy", "order", "enroll", "register", "demo")
    first_booking_cta = None
    for e in sorted((dom_elements or []), key=lambda x: dom_y(x)):
        if e.get("tag") in ("a", "button") and dom_visible(e) and dom_y(e) > 0:
            text = (e.get("text") or "").lower()
            if any(kw in text for kw in booking_kw):
                first_booking_cta = {"text": (e.get("text") or "").strip(), "y": dom_y(e)}
                break

    # Unique visible CTA texts
    seen = set()
    all_ctas = []
    for e in (dom_elements or []):
        if e.get("tag") in ("a", "button") and dom_visible(e) and dom_y(e) > 0:
            text = (e.get("text") or "").strip()
            if text and len(text) < 80 and text not in seen:
                seen.add(text)
                all_ctas.append(text)

    # Social proof keyword presence
    html_lower = getattr(p, "raw_html", "").lower()
    social_found = [kw for kw in
        ("review", "rating", "testimonial", "stars", "5-star", "award", "certified", "google")
        if kw in html_lower]

    schema_types = []
    for raw in getattr(p, "schema_raw", []):
        try:
            obj = json.loads(raw)
            t = obj.get("@type") or (obj.get("@graph") or [{}])[0].get("@type", "")
            if t:
                schema_types.append(t if isinstance(t, str) else str(t))
        except Exception:
            pass

    return {
        "page_title":         getattr(p, "title_text", "").strip(),
        "meta_desc":          getattr(p, "meta_desc", "").strip(),
        "h1":                 h1,
        "hero_headings":      [h["text"] for h in headings[:6]],
        "fold_ctas":          fold_ctas,               # with y-positions
        "first_booking_cta":  first_booking_cta,       # None if absent
        "all_cta_sample":     all_ctas[:20],
        "social_proof_found": social_found,
        "schema_types":       schema_types,
        "has_form":           bool(getattr(p, "forms", [])),
        "has_phone":          bool(getattr(p, "tel_hrefs", [])),
    }


SYSTEM_PROMPT = """You are a senior CRO analyst auditing a landing page for conversion friction.

CRITICAL: The page_context includes `site_type`. Adapt your analysis to the business model:
- "dental" / "medical" / "local_business": Book appointment, insurance, reviews, call CTA
- "association": Membership value, join CTA, member benefits, renewal, advocacy
- "saas": Trial CTA, pricing clarity, feature benefits, integration proof
- "ecommerce": Product clarity, buy CTA, shipping/returns, reviews
- "nonprofit": Donate CTA, mission clarity, impact proof
- "restaurant": Reservation CTA, menu clarity, hours

STRICT RULES:
1. Every finding's `evidence` MUST quote actual detected text from page_context.
   BAD: "No primary CTA detected"
   GOOD: "Above-fold CTAs: 'Explore Services' (a, y=420), 'View All' (a, y=510). No booking-intent CTA."
2. Adapt findings to the site_type — do NOT apply dental rules to associations.
3. `confidence` calibration:
   - Verifiable (missing CTA, no booking link): 70–80
   - Subjective (weak value prop): 75–85
   - Very subjective (label style): 50–65
4. Each finding is a SEPARATE atomic issue with a stable snake_case `id`.
5. Return ONLY findings you are highly confident are real problems.
6. `fix` must reference what was detected — no generic advice.
7. Maximum 3 findings. Fewer is better.
8. `finding` must explain WHY it hurts conversions for THIS type of site.

Valid finding IDs:
- hero_primary_cta_missing    (no primary conversion CTA in first 900px for this site type)
- hero_value_proposition      (hero doesn't answer: why choose this org/service over alternatives?)
- hero_action_clarity         (CTAs encourage browsing instead of the primary conversion action)
- offer_clarity               (no specific offer, incentive, or membership benefit visible above fold)
- social_proof_near_cta       (no social proof proximate to the primary CTA — only if you can verify distance)

Respond ONLY with valid JSON:
{
  "findings": [
    {
      "id": "hero_primary_cta_missing",
      "title": "Short one-line title",
      "severity": "high|medium|low",
      "confidence": 75,
      "finding": "One paragraph: what's missing and why it reduces conversions",
      "evidence": ["Quote from page: exact CTA text detected at y=Npx", "..."],
      "fix": "Specific fix referencing what was detected",
      "revenue_signal": "One supporting stat — leave empty string if unsure"
    }
  ]
}"""

USER_PROMPT = """Audit this page. Use ONLY the data below as evidence — do not assume anything not in this context.

{context}"""


def _call_openai(context: dict) -> list[dict]:
    try:
        import urllib.request

        payload = json.dumps({
            "model": "gpt-4o-mini",
            "temperature": 0.1,
            "max_tokens": 1000,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": USER_PROMPT.format(
                    context=json.dumps(context, indent=2)
                )},
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
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = json.loads(resp.read())

        content = body["choices"][0]["message"]["content"]
        return json.loads(content).get("findings", [])

    except Exception as exc:
        return [{"_error": str(exc)}]


def run(p: AuditParser | None = None, dom_elements: list | None = None, site_type: str = "local_business") -> list[dict] | None:
    """Returns a LIST of atomic issue dicts, or None if nothing to report."""
    if not OPENAI_API_KEY:
        return None

    ctx = _extract_page_context(p or AuditParser(), dom_elements or [])
    ctx["site_type"] = site_type
    raw = _call_openai(ctx)

    valid_ids = {
        "hero_primary_cta_missing",
        "hero_value_proposition",
        "hero_action_clarity",
        "offer_clarity",
        "social_proof_near_cta",
    }

    issues = []
    for f in raw:
        if not isinstance(f, dict) or "_error" in f:
            continue
        if f.get("id") not in valid_ids:
            continue
        if not f.get("title") or not f.get("finding"):
            continue
        evidence = f.get("evidence", [])
        # Reject if evidence is just restating the conclusion (< 30 chars total)
        if sum(len(e) for e in evidence) < 30:
            continue

        finding_id = f["id"]
        ceiling    = CONFIDENCE_CEILING.get(finding_id, DEFAULT_CONFIDENCE_CEILING)
        confidence = min(int(f.get("confidence", 70)), ceiling)

        issues.append({
            "id":               finding_id,
            "title":            f["title"],
            "severity":         f.get("severity", "medium"),
            "confidence":       "confirmed",
            "confidence_score": confidence,
            "cro_impact":       "Hero conversion rate",
            "revenue_signal":   f.get("revenue_signal", ""),
            "detection_source": "ai",
            "industry_tags":    ["all"],
            "fix_effort":       "hours",
            "origin":           "ai_bot",
            "affected_elements": [],
            "findings":         [f["finding"]],
            "fix":              f.get("fix", ""),
            "evidence":         evidence,
        })

    return issues if issues else None
