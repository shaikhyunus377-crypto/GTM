#!/usr/bin/env python3
"""
email_writer.py — Personalized Cold-Email Generator
====================================================
The final bot in the pipeline. Takes everything we know about a prospect
(contact, Google reviews, CRO issues + fixes, tech stack / paid tools) and
writes a tailored SUBJECT LINE + EMAIL BODY for that specific lead.

Deterministic + pure-stdlib by default (no API key, instant, free). If an
OpenAI key is supplied it will polish the draft; otherwise the template draft
is returned as-is.

    from email_writer import run_email
    out = run_email(lead_dict)            # -> {"subject","body","variants",...}
    out = run_email(lead_dict, openai_key="sk-...")   # optional LLM polish
"""
from __future__ import annotations

import json
import re

# ── helpers ──────────────────────────────────────────────────────────────────

def _first_name(name: str, business: str) -> str:
    name = (name or "").strip()
    if name:
        first = name.split()[0]
        if first.lower() not in ("the", "dr", "dr.", "mr", "mrs", "ms"):
            return first
        parts = name.split()
        if len(parts) > 1:
            return parts[1]
        return first
    return "there"


def _clean(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("none", "null") else s


def _norm_domain(website: str) -> str:
    s = re.sub(r"^https?://(www\.)?", "", (website or "").strip().lower()).strip("/")
    return s.split("/")[0]


# ── core extraction from the assembled lead record ───────────────────────────

def _top_issues(cro: dict) -> list[dict]:
    if not isinstance(cro, dict):
        return []
    issues = cro.get("top_issues") or cro.get("client_report") or cro.get("issues") or []
    out = []
    for i in issues:
        if not isinstance(i, dict):
            continue
        title = _clean(i.get("title") or i.get("id"))
        fix   = _clean(i.get("fix"))
        sev   = _clean(i.get("severity")) or "medium"
        if title:
            out.append({"title": title, "fix": fix, "severity": sev})
    # high severity first
    out.sort(key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["severity"], 3))
    return out


def _build_observations(lead: dict) -> list[str]:
    """Concrete, specific lines we can drop into the email."""
    obs = []
    cro  = lead.get("cro") or {}
    tech = lead.get("tech") or {}
    summary = tech.get("summary") or {}

    issues = _top_issues(cro)
    if issues:
        top = issues[0]
        title = top["title"].rstrip(".")
        line = f"one thing on your homepage — {title[0].lower() + title[1:]}"
        if top.get("fix"):
            fix = top["fix"].rstrip(".")
            line += f". A quick win would be to {fix[0].lower() + fix[1:]}"
        obs.append(line)

    # booking / paid-tool angle
    booking = _clean(summary.get("booking_tools"))
    if booking:
        obs.append(f"I saw you’re already taking bookings through {booking}, so you clearly value turning visitors into appointments")
    elif not booking:
        obs.append("there’s no online booking widget on the site, so visitors have to call to convert — an easy place to capture after-hours leads")

    # analytics gap
    if str(summary.get("google_analytics")).lower() == "no":
        obs.append("I also couldn’t find Google Analytics, which usually means there’s no visibility into where leads drop off")

    return obs


def _subject_variants(lead: dict, issues: list[dict]) -> list[str]:
    biz = _clean(lead.get("business_name")) or _norm_domain(lead.get("website"))
    subs = []
    if issues:
        t = issues[0]["title"].rstrip(".")
        subs.append(f"Quick idea for {biz}’s website")
        subs.append(f"{biz}: {t.lower()}?")
    else:
        subs.append(f"Quick idea for {biz}’s website")
    reviews = lead.get("google_review_count") or 0
    try:
        reviews = int(reviews)
    except Exception:
        reviews = 0
    if reviews >= 25:
        subs.append(f"Turning {biz}’s {reviews} reviews into more bookings")
    subs.append(f"Helping {biz} get more from its website")
    # dedupe, keep order
    seen, out = set(), []
    for s in subs:
        if s.lower() not in seen:
            seen.add(s.lower()); out.append(s)
    return out[:3]


def _build_body(lead: dict, observations: list[str]) -> str:
    first = _first_name(_clean(lead.get("contact_name")), _clean(lead.get("business_name")))
    biz   = _clean(lead.get("business_name")) or _norm_domain(lead.get("website"))
    cat   = _clean(lead.get("category")) or "practice"

    rating  = lead.get("google_rating") or 0
    reviews = lead.get("google_review_count") or 0
    try:
        rating = float(rating)
    except Exception:
        rating = 0.0
    try:
        reviews = int(reviews)
    except Exception:
        reviews = 0

    # opener — reference real reputation when we have it
    if rating >= 4.0 and reviews >= 10:
        opener = (f"I came across {biz} — a {rating:.1f}★ rating across {reviews} Google reviews is "
                  f"genuinely impressive, you’ve clearly earned your patients’ trust.")
    elif reviews >= 5:
        opener = f"I came across {biz} and spent a few minutes on your website."
    else:
        opener = f"I came across {biz} and took a closer look at your website."

    # the specific observation(s)
    if observations:
        body_obs = "While I was there, I noticed " + observations[0] + "."
        if len(observations) > 1:
            body_obs += " " + observations[1][0].upper() + observations[1][1:] + "."
    else:
        body_obs = "While I was there, a couple of small changes stood out that could help more visitors take action."

    value = (f"We help local {cat.lower()}s turn the traffic they already have into more booked "
             f"appointments — usually without spending a dollar more on ads.")

    cta = ("Worth a quick 10-minute call to walk you through what I found? "
           "Happy to send over a short free audit either way.")

    body = (
        f"Hi {first},\n\n"
        f"{opener}\n\n"
        f"{body_obs}\n\n"
        f"{value}\n\n"
        f"{cta}\n\n"
        f"Best,\n[Your Name]"
    )
    return body


def run_email(lead: dict, openai_key: str = "") -> dict:
    """Generate a personalized subject + body for one prospect."""
    if not isinstance(lead, dict):
        return {"error": "lead must be an object", "subject": "", "body": ""}

    issues       = _top_issues(lead.get("cro") or {})
    observations = _build_observations(lead)
    variants     = _subject_variants(lead, issues)
    subject      = variants[0] if variants else f"Quick idea for your website"
    body         = _build_body(lead, observations)

    result = {
        "subject":          subject,
        "subject_variants": variants,
        "body":             body,
        "personalization": {
            "used_contact_name": bool(_clean(lead.get("contact_name"))),
            "used_reviews":      bool(lead.get("google_review_count")),
            "used_cro_issue":    bool(issues),
            "observations":      observations,
        },
        "generated_by": "template",
    }

    # Optional LLM polish (only if a key is provided)
    if openai_key:
        try:
            polished = _openai_polish(lead, result, openai_key)
            if polished:
                result.update(polished)
                result["generated_by"] = "openai"
        except Exception as e:
            result["llm_error"] = str(e)[:160]

    return result


def _openai_polish(lead: dict, draft: dict, openai_key: str) -> dict | None:
    """Ask OpenAI to rewrite the draft more naturally. Best-effort."""
    import urllib.request
    prompt = (
        "You are an expert cold-email copywriter for a web/CRO agency. "
        "Rewrite the draft below into a warm, concise, non-salesy cold email (max 130 words). "
        "Keep every specific factual detail (business name, reviews, the website issue). "
        "Return STRICT JSON: {\"subject\": \"...\", \"body\": \"...\"}.\n\n"
        f"LEAD DATA:\n{json.dumps({k: lead.get(k) for k in ('business_name','contact_name','category','google_rating','google_review_count')}, ensure_ascii=False)}\n\n"
        f"DRAFT SUBJECT: {draft['subject']}\nDRAFT BODY:\n{draft['body']}"
    )
    payload = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    if parsed.get("subject") and parsed.get("body"):
        return {"subject": parsed["subject"].strip(), "body": parsed["body"].strip()}
    return None


if __name__ == "__main__":
    import sys
    sample = {
        "business_name": "Making You Smile NYC", "website": "https://makingyousmile.nyc",
        "category": "Dental Clinic", "city": "New York",
        "contact_name": "Ziad Jalbout", "contact_role": "Owner",
        "google_rating": 4.8, "google_review_count": 120,
        "cro": {"top_issues": [
            {"title": "No booking CTA above the fold", "fix": "Add a visible 'Book Now' button in the hero", "severity": "high"},
            {"title": "Missing social proof on homepage", "fix": "Surface your Google reviews near the top", "severity": "medium"},
        ], "pitch_angle": "🚨 Critical: No booking CTA above the fold"},
        "tech": {"summary": {"cms": "WordPress", "booking_tools": "NexHealth", "google_analytics": "No"},
                 "paid_tools": ["NexHealth"], "commercial_maturity_score": 40},
    }
    print(json.dumps(run_email(sample), indent=2, ensure_ascii=False))
