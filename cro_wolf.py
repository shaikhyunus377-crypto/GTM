#!/usr/bin/env python3
"""
cro_wolf.py — CRO Confidence Engine
=====================================
Wolf-pattern post-processor for the CRO audit pipeline.

Mirrors wolf.py's architecture exactly:
  - Does NOT detect issues (that's the bots' job)
  - JUDGES issues already found: confirms, scores, or flags for verification
  - Adds gap detection: knows which checks SHOULD exist per industry
  - Produces an audit trail: every decision is backed by evidence refs

Pipeline position:
    cro_audit.py  →  cro_report.json  →  cro_wolf.py  →  cro_final.json

Usage:
    python cro_wolf.py --report cro_report.json --html page.html --dom dom_states.json
    python cro_wolf.py --report cro_report.json --html page.html --dom dom_states.json --industry dental
    python cro_wolf.py --report cro_report.json --html page.html  (DOM optional)
"""

from __future__ import annotations
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


# ───────────────────────────────────────────────────────────────────────────────
#  DECISION HELPERS  (same pattern as wolf.py)
# ───────────────────────────────────────────────────────────────────────────────

def confirm(issue: dict, score: int, reason: str, refs: list[str] | None = None):
    issue["decision"] = "confirmed"
    issue["confidence_score"] = max(issue.get("confidence_score", 0), score)
    issue.setdefault("decision_reasons", []).append(reason)
    if refs:
        issue.setdefault("evidence_refs", []).extend(refs)


def flag_verify(issue: dict, score: int, reason: str, refs: list[str] | None = None):
    if issue.get("decision") == "confirmed":
        issue["confidence_score"] = max(issue.get("confidence_score", 0), score)
        issue.setdefault("decision_reasons", []).append(f"wolf_note: {reason}")
        return
    issue["decision"] = "verification_required"
    issue["confidence_score"] = score
    issue.setdefault("decision_reasons", []).append(reason)
    issue.setdefault("evidence_refs", []).extend(refs or [])


def suppress(issue: dict, reason: str, refs: list[str] | None = None):
    issue["decision"]          = "suppressed"
    issue["confidence_score"]  = 0
    issue.setdefault("decision_reasons", []).append(f"suppressed: {reason}")
    if refs:
        issue.setdefault("evidence_refs", []).extend(refs)


# ───────────────────────────────────────────────────────────────────────────────
#  EVIDENCE EXTRACTORS
# ───────────────────────────────────────────────────────────────────────────────

def extract_h1_evidence(html: str, dom_elements: list) -> dict:
    dom_h1s = [e for e in dom_elements if e.get("tag") == "h1"]
    evidence = {"count": len(dom_h1s), "items": []}
    PROMO_RE = re.compile(
        r"\b(\d+\s*%|off\b|sale\b|deal\b|save\b|discount|free\b|limited\s+time)\b", re.I
    )
    for h in dom_h1s:
        bbox = h.get("states", {}).get("default", {}).get("bbox", {}) or {}
        text = (h.get("text") or "").strip()
        evidence["items"].append({
            "text":        text,
            "y":           bbox.get("y", 0),
            "width":       bbox.get("width", 0),
            "height":      bbox.get("height", 0),
            "is_empty":    not text,
            "is_promo":    bool(PROMO_RE.search(text)),
            "below_fold":  bbox.get("y", 0) > 900 and bbox.get("y", 0) > 0,
        })
    return evidence


def extract_heading_evidence(dom_elements: list) -> dict:
    HEAD_TAGS = {"h1","h2","h3","h4","h5","h6"}
    all_heads = [e for e in dom_elements if e.get("tag") in HEAD_TAGS]
    real_heads = []
    modal_heads = []
    for h in all_heads:
        bbox = h.get("states", {}).get("default", {}).get("bbox", {}) or {}
        y, w, ht = bbox.get("y", 0), bbox.get("width", 0), bbox.get("height", 0)
        if y == 0 and w == 0 and ht == 0:
            modal_heads.append(h)
        else:
            real_heads.append(h)
    skips = []
    visible = [h for h in real_heads if (h.get("text") or "").strip()]
    for i in range(1, len(visible)):
        prev, curr = visible[i-1], visible[i]
        pl = int(prev["tag"][1])
        cl = int(curr["tag"][1])
        if cl > pl + 1:
            skips.append({
                "from": prev["tag"], "from_text": (prev.get("text") or "")[:40],
                "to":   curr["tag"], "to_text":   (curr.get("text") or "")[:40],
                "levels_skipped": cl - pl - 1,
            })
    empty_real = [h for h in real_heads if not (h.get("text") or "").strip()]
    return {
        "total_headings":   len(all_heads),
        "real_headings":    len(real_heads),
        "modal_headings":   len(modal_heads),
        "level_skips":      skips,
        "empty_real_count": len(empty_real),
    }


def extract_image_evidence(html: str, dom_elements: list) -> dict:
    IMG_RE = re.compile(r"<img\b([^>]*)>", re.I | re.S)
    ATTR   = re.compile(r"""(\w[\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))""", re.I)
    results = []
    for m in IMG_RE.finditer(html):
        attrs_str = m.group(1)
        attrs = {}
        for am in ATTR.finditer(attrs_str):
            k = am.group(1).lower()
            v = am.group(2) or am.group(3) or am.group(4) or ""
            attrs[k] = v
        src      = attrs.get("src", "").strip()
        data_src = attrs.get("data-src", "").strip()
        alt      = attrs.get("alt", None)
        results.append({
            "src":          src,
            "data_src":     data_src,
            "alt":          alt,
            "has_real_src": bool(src),
            "is_lazy_broken": not src and bool(data_src),
            "is_truly_broken": not src and not data_src,
        })
    lazy_broken   = [r for r in results if r["is_lazy_broken"]]
    truly_broken  = [r for r in results if r["is_truly_broken"]]
    rendered_images = 0
    for el in dom_elements:
        if el.get("tag") != "img":
            continue
        bbox = (el.get("states", {}).get("default", {}).get("bbox", {}))
        if bbox.get("width", 0) > 0 and bbox.get("height", 0) > 0:
            rendered_images += 1
    return {
        "total":          len(results),
        "lazy_broken":    lazy_broken,
        "truly_broken":   truly_broken,
        "lazy_count":     len(lazy_broken),
        "broken_count":   len(truly_broken),
        "rendered_images": rendered_images,
    }


def extract_title_evidence(html: str) -> dict:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    raw   = m.group(1).strip() if m else ""
    clean = re.sub(r"<[^>]+>", "", raw).strip()
    return {"raw": raw, "clean": clean, "length": len(clean), "missing": not clean}


def extract_cta_evidence(dom_elements: list) -> dict:
    PHONE_RE = re.compile(r"^\+?[\d\s\-().]{7,}$")
    cta_els = [e for e in dom_elements if e.get("tag") in ("a", "button")]
    visible = []
    for e in cta_els:
        bbox = e.get("states", {}).get("default", {}).get("bbox", {}) or {}
        y, w = bbox.get("y", 0), bbox.get("width", 0)
        if y > 0 and w > 0:
            visible.append(e)
    labels = [(e.get("text") or "").strip() for e in visible if (e.get("text") or "").strip()]
    counts = Counter(labels)
    all_caps  = sorted({
        l for l in labels
        if l == l.upper() and len(l) > 2
        and re.search(r"[A-Z]", l)
        and not PHONE_RE.match(l)
    })
    repeated  = [(l, c) for l, c in counts.items() if c >= 3 and not PHONE_RE.match(l)]
    phones    = [l for l in labels if PHONE_RE.match(l)]
    phone_rep = Counter(phones)
    return {
        "total_visible_ctas": len(visible),
        "all_caps":           all_caps,
        "all_caps_count":     len(all_caps),
        "repeated":           repeated,
        "phone_labels":       dict(phone_rep),
    }


def extract_og_evidence(html: str) -> dict:
    og  = re.findall(r'<meta[^>]+property=["\']og:[^"\']+["\'][^>]*/?>',      html, re.I)
    tw  = re.findall(r'<meta[^>]+name=["\']twitter:[^"\']+["\'][^>]*/?>',     html, re.I)
    return {"og_count": len(og), "twitter_count": len(tw)}


def extract_schema_evidence(html: str) -> dict:
    blocks = re.findall(r'<script[^>]+ld\+json[^>]*>(.*?)</script>', html, re.S | re.I)
    results = []
    for raw in blocks:
        try:
            d = json.loads(raw)
        except Exception:
            continue
        t = d.get("@type", "")
        if isinstance(t, list):
            t = t[0]
        results.append({
            "type":             t,
            "has_rating":       "aggregateRating" in d,
            "has_hours":        "openingHours"    in d,
            "has_price_range":  "priceRange"      in d,
            "has_telephone":    "telephone"        in d,
            "has_address":      "address"          in d,
        })
    has_any_rating = any(r["has_rating"] for r in results)
    return {"blocks": results, "count": len(results), "has_any_rating": has_any_rating}


def extract_form_evidence(html: str, dom_elements: list) -> dict:
    BOOK_KW = re.compile(r"book|schedule|appointment|reserve|checkout|contact|enqui|signup", re.I)
    forms = re.findall(r"<form\b[^>]*>", html, re.I)
    booking_links = [
        e for e in dom_elements
        if e.get("tag") == "a"
        and BOOK_KW.search((e.get("text") or "") + str(e.get("href") or ""))
    ]
    return {
        "form_count":          len(forms),
        "booking_link_count":  len(booking_links),
        "booking_link_samples": [(e.get("text") or "")[:40] for e in booking_links[:4]],
    }


def extract_phone_evidence(html: str) -> dict:
    tel_hrefs   = re.findall(r'<a[^>]+href=["\']tel:[^"\']+["\'][^>]*>', html, re.I)
    phone_texts = re.findall(r'<a[^>]*>([^<]*(?:\d{3}[-.\s]\d{3}[-.\s]\d{4})[^<]*)</a>', html, re.I | re.S)
    return {
        "tel_href_count":   len(tel_hrefs),
        "phone_text_count": len(phone_texts),
        "needs_tel_fix":    bool(phone_texts) and not tel_hrefs,
    }


def extract_dupe_id_evidence(dom_elements: list) -> dict:
    visible = [
        e for e in dom_elements
        if (e.get("states", {}).get("default", {}).get("bbox", {}) or {}).get("y", 0) > 0
        and (e.get("states", {}).get("default", {}).get("bbox", {}) or {}).get("width", 0) > 0
    ]
    ids = [e.get("id") for e in visible if e.get("id")]
    dupes = {k: v for k, v in Counter(ids).items() if v > 1}
    return {"duplicate_ids": dupes, "count": len(dupes)}


def extract_cta_above_fold_evidence(dom_elements: list) -> dict:
    """Check for booking-intent CTAs within the first 800px."""
    BOOKING_RE = re.compile(
        r"book|schedul|appoint|reserv|consult|get start|sign up|free trial|contact|call now|get quote",
        re.I,
    )
    fold_px = 800
    cta_els = [
        e for e in dom_elements
        if e.get("tag") in ("a", "button")
    ]
    above_fold_booking = []
    all_booking = []
    for e in cta_els:
        text = (e.get("text") or "").strip()
        bbox = e.get("states", {}).get("default", {}).get("bbox", {}) or {}
        y = bbox.get("y", 0)
        w = bbox.get("width", 0)
        h = bbox.get("height", 0)
        if not BOOKING_RE.search(text):
            continue
        if w == 0 and h == 0:
            continue  # off-screen / cookie modal
        all_booking.append({"text": text[:60], "y": y})
        if 0 < y <= fold_px:
            above_fold_booking.append({"text": text[:60], "y": y})
    return {
        "above_fold_count": len(above_fold_booking),
        "total_booking_ctas": len(all_booking),
        "above_fold_samples": above_fold_booking[:3],
    }


def extract_social_proof_evidence(html: str, dom_elements: list) -> dict:
    """Look for testimonials, reviews, ratings, star patterns."""
    REVIEW_KW = re.compile(
        r"review|testimonial|rating|stars?|\d+\.\d+\s*/\s*5|verified\s+patient|what\s+(our\s+)?client|said\s+about",
        re.I,
    )
    schema_rating = bool(re.search(r'"aggregateRating"', html, re.I))
    star_html = bool(re.search(r"★|&#9733;|fa-star|star-rating|rating-stars", html, re.I))
    keyword_in_html = bool(REVIEW_KW.search(html))

    dom_review_texts = 0
    for e in dom_elements:
        text = (e.get("text") or "")
        bbox = e.get("states", {}).get("default", {}).get("bbox", {}) or {}
        if bbox.get("y", 0) > 0 and REVIEW_KW.search(text):
            dom_review_texts += 1

    return {
        "schema_rating": schema_rating,
        "star_html": star_html,
        "keyword_in_html": keyword_in_html,
        "dom_review_texts": dom_review_texts,
        "has_any_signal": schema_rating or star_html or dom_review_texts > 0,
    }


def extract_trust_signals_evidence(html: str, dom_elements: list) -> dict:
    """Look for trust badges, certifications, awards, insurance logos."""
    TRUST_KW = re.compile(
        r"certif|accredit|award|insur|licens|bbb|yelp|google.*review|trustpilot|verified|member\s+of",
        re.I,
    )
    keyword_in_html = bool(TRUST_KW.search(html))
    trust_images = []
    for e in dom_elements:
        if e.get("tag") == "img":
            alt = (e.get("aria_label") or "").lower()
            if TRUST_KW.search(alt):
                trust_images.append(alt[:50])
    dom_trust_texts = 0
    for e in dom_elements:
        text = (e.get("text") or "")
        bbox = e.get("states", {}).get("default", {}).get("bbox", {}) or {}
        if bbox.get("y", 0) > 0 and TRUST_KW.search(text):
            dom_trust_texts += 1
    return {
        "keyword_in_html": keyword_in_html,
        "trust_images": trust_images[:4],
        "dom_trust_texts": dom_trust_texts,
        "has_any_signal": keyword_in_html or bool(trust_images) or dom_trust_texts > 0,
    }


def extract_mobile_tap_evidence(dom_elements: list) -> dict:
    """Find booking CTAs with bounding boxes smaller than tap-target minimums."""
    BOOKING_RE = re.compile(
        r"book|schedul|appoint|reserv|consult|get start|sign up|free trial|contact|call now|get quote",
        re.I,
    )
    MIN_W, MIN_H = 44, 32
    small_targets = []
    ok_targets = []
    for e in dom_elements:
        if e.get("tag") not in ("a", "button"):
            continue
        text = (e.get("text") or "").strip()
        if not BOOKING_RE.search(text):
            continue
        bbox = e.get("states", {}).get("default", {}).get("bbox", {}) or {}
        w = bbox.get("width", 0)
        h = bbox.get("height", 0)
        y = bbox.get("y", 0)
        if w == 0 and h == 0:
            continue
        if w < MIN_W or h < MIN_H:
            small_targets.append({"text": text[:50], "width": w, "height": h, "y": y})
        else:
            ok_targets.append({"text": text[:50], "width": w, "height": h})
    return {
        "small_count": len(small_targets),
        "ok_count": len(ok_targets),
        "small_samples": small_targets[:3],
    }


# ───────────────────────────────────────────────────────────────────────────────
#  EVALUATORS  (one per issue type)
# ───────────────────────────────────────────────────────────────────────────────

def eval_h1(issue: dict, ev: dict):
    items = ev.get("items", [])
    if not items:
        confirm(issue, 95, "dom_confirms_no_h1", ["dom_states.json"])
        return
    item = items[0]
    if item["is_empty"]:
        confirm(issue, 90, "dom_h1_text_empty", ["dom_states.json"])
    elif item["is_promo"]:
        confirm(issue, 92, "dom_h1_is_promotional", ["dom_states.json"])
        new_finding = (
            f"H1 contains promotional copy (\"{item['text'][:60]}\") "
            "instead of a service identity statement — "
            "search crawlers treat this as a discount page, not a service page"
        )
        issue["findings"] = [
            new_finding if "empty" in f.lower() else f
            for f in issue.get("findings", [])
        ]
        issue["affected_elements"] = [{"tag": "h1", "text": item["text"], "id": ""}]
        issue["evidence"] = [
            f"H1 content: \"{item['text']}\"",
        ] + [e for e in issue.get("evidence", []) if "y-position" in e or "y=" in e]
    if item["below_fold"]:
        confirm(issue, 88, "dom_h1_below_fold", ["dom_states.json"])
        fold_finding = (
            f"H1 is at y={item['y']}px — below the fold (>900px). "
            "Visitors see no service headline before scrolling; "
            "first-impression trust and relevance signal lost."
        )
        existing = issue.get("findings", [])
        replaced = False
        for i, f in enumerate(existing):
            if "below the fold" in f.lower() or "y=" in f:
                existing[i] = fold_finding
                replaced = True
                break
        if not replaced:
            existing.append(fold_finding)
        issue["findings"] = existing
    if not item["is_empty"] and not item["is_promo"] and not item["below_fold"]:
        suppress(issue, "dom_shows_h1_is_valid", ["dom_states.json"])


def eval_headings(issue: dict, ev: dict):
    if ev.get("level_skips"):
        confirm(issue, 90, "dom_heading_skip_confirmed", ["dom_states.json"])
    if ev.get("empty_real_count", 0) > 0:
        confirm(issue, 85, "dom_real_empty_headings_confirmed", ["dom_states.json"])
    elif ev.get("empty_real_count", 0) == 0:
        issue.setdefault("decision_reasons", []).append(
            "wolf_note: empty_heading_count_was_from_cookie_modal_excluded"
        )
        issue["findings"] = [
            f for f in issue.get("findings", [])
            if "empty heading" not in f.lower()
        ]


def eval_dupe_ids(issue: dict, ev: dict):
    if ev.get("count", 0) > 0:
        confirm(issue, 99, "dom_dupe_ids_confirmed", ["dom_states.json"])
        issue["affected_elements"] = [
            {"id": k, "count": v}
            for k, v in ev["duplicate_ids"].items()
        ]
    else:
        suppress(issue, "dom_shows_no_duplicate_ids", ["dom_states.json"])


def eval_cta_labels(issue: dict, ev: dict):
    caps_count = ev.get("all_caps_count", 0)
    if caps_count > 0:
        confirm(issue, 88, f"dom_confirms_{caps_count}_all_caps_ctas", ["dom_states.json"])
        title = issue.get("title", "")
        old_count = re.search(r"(\d+) CTA label", title)
        if old_count and int(old_count.group(1)) != caps_count:
            issue["title"] = re.sub(r"\d+ CTA label", f"{caps_count} CTA label", title)
            issue.setdefault("decision_reasons", []).append(
                f"wolf_corrected_count: {old_count.group(1)} → {caps_count}"
            )
        issue["evidence"] = [
            e for e in issue.get("evidence", [])
            if "Cookies Details" not in e
        ]
    elif caps_count == 0:
        suppress(issue, "dom_shows_no_all_caps_visible_ctas", ["dom_states.json"])
    if ev.get("repeated"):
        confirm(issue, 85, "dom_confirms_repeated_labels", ["dom_states.json"])


def eval_og_meta(issue: dict, ev: dict):
    if ev["og_count"] == 0 and ev["twitter_count"] == 0:
        confirm(issue, 99, "html_confirms_zero_og_tags", ["html"])
    elif ev["og_count"] > 0:
        suppress(issue, "html_shows_og_tags_present", ["html"])


def eval_schema(issue: dict, ev: dict):
    if ev["count"] == 0:
        confirm(issue, 95, "html_no_schema_blocks", ["html"])
    elif not ev["has_any_rating"]:
        confirm(issue, 92, "html_schema_missing_aggregateRating", ["html"])
    else:
        suppress(issue, "html_schema_has_rating", ["html"])


def eval_page_meta(issue: dict, ev: dict):
    clean_len = ev["length"]
    if ev["missing"]:
        confirm(issue, 95, "html_title_missing", ["html"])
        return
    for i, finding in enumerate(issue.get("findings", [])):
        old = re.search(r"Title too long \((\d+) chars", finding)
        if old and int(old.group(1)) != clean_len:
            issue["findings"][i] = re.sub(
                r"Title too long \(\d+ chars",
                f"Title too long ({clean_len} chars",
                finding,
            )
            issue.setdefault("decision_reasons", []).append(
                f"wolf_corrected_title_length: {old.group(1)} → {clean_len}"
            )
    corrected_evidence = []
    for e in issue.get("evidence", []):
        e_fixed = re.sub(r"Title \(\d+ chars\)", f"Title ({clean_len} chars)", e)
        e_fixed = re.sub(
            r"(\"Local Dentist[^\"]+?\")Back Button[^\"]*\"",
            r'\1"',
            e_fixed,
        )
        corrected_evidence.append(e_fixed)
    issue["evidence"] = corrected_evidence
    if "fix" in issue:
        fix = issue["fix"]
        fix = re.sub(
            r"(Title:[^\n]*?Current:)\s*\d+\s*chars",
            lambda m: m.group(1) + f" {clean_len} chars",
            fix,
        )
        if "Current:" in issue["fix"] and "Title:" not in issue["fix"]:
            fix = re.sub(r"Current:\s*\d+\s*chars", f"Current: {clean_len} chars", fix, count=1)
        issue["fix"] = fix
    if clean_len > 60:
        confirm(issue, 90, "html_title_too_long", ["html"])
    elif clean_len <= 60:
        suppress(issue, "html_title_within_limit", ["html"])


def eval_lazy_images(issue: dict, ev: dict):
    lazy  = ev.get("lazy_count", 0)
    broken = ev.get("broken_count", 0)
    rendered = ev.get("rendered_images", 0)
    if lazy > 0 and rendered > 0 and broken == 0:
        suppress(issue, "dom_confirms_images_rendered_after_js_hydration", ["dom_states.json"])
        return
    if lazy == 0 and broken == 0:
        suppress(issue, "html_no_images_with_empty_src", ["html"])
        return
    if lazy > 0:
        confirm(issue, 88, f"html_confirms_{lazy}_lazy_broken_images", ["html"])
        issue["evidence"] = [
            f"src=\"\" data-src=\"{img['data_src'][:60]}\" alt=\"{img['alt'] or '(missing)'}\""
            for img in ev["lazy_broken"][:4]
        ]
        issue["title"] = re.sub(r"\d+ image\(s\)", f"{lazy} image(s)", issue.get("title", ""))
    if broken > 0:
        confirm(issue, 95, f"html_confirms_{broken}_truly_broken_images", ["html"])


def eval_forms(issue: dict, ev: dict):
    if ev["form_count"] == 0 and ev["booking_link_count"] == 0:
        confirm(issue, 92, "html_no_forms_no_booking_links", ["html", "dom_states.json"])
    elif ev["form_count"] == 0:
        confirm(issue, 80, "html_no_inline_form_but_booking_links_exist", ["html"])
    else:
        suppress(issue, "html_form_found", ["html"])


def eval_phone(issue: dict, ev: dict):
    if ev["needs_tel_fix"]:
        confirm(issue, 90, "html_phone_text_without_tel_href", ["html"])
    elif ev["tel_href_count"] > 0 and ev["phone_text_count"] > 0:
        confirm(issue, 75, "html_phone_repeated_as_label", ["html"])
    else:
        suppress(issue, "html_phone_correctly_linked_or_absent", ["html"])


def eval_cta_above_fold(issue: dict, ev: dict):
    if ev["above_fold_count"] > 0:
        suppress(issue, f"dom_shows_{ev['above_fold_count']}_booking_ctas_above_fold", ["dom_states.json"])
    elif ev["total_booking_ctas"] > 0:
        confirm(issue, 88, "dom_booking_ctas_exist_but_all_below_fold", ["dom_states.json"])
    else:
        confirm(issue, 85, "dom_no_booking_ctas_detected_at_all", ["dom_states.json"])


def eval_social_proof(issue: dict, ev: dict):
    if ev["has_any_signal"]:
        # Social proof signals exist — check if bot was wrong
        if ev["schema_rating"]:
            suppress(issue, "html_schema_aggregateRating_found", ["html"])
        elif ev["dom_review_texts"] >= 3:
            suppress(issue, "dom_multiple_review_keyword_sections_found", ["dom_states.json"])
        else:
            flag_verify(issue, 60, "some_social_proof_signals_found_verify_visibility", ["html", "dom_states.json"])
    else:
        confirm(issue, 90, "no_social_proof_signals_in_html_or_dom", ["html", "dom_states.json"])


def eval_trust_signals(issue: dict, ev: dict):
    if ev["has_any_signal"]:
        if ev["dom_trust_texts"] >= 2:
            suppress(issue, "dom_trust_signal_sections_confirmed_visible", ["dom_states.json"])
        else:
            flag_verify(issue, 65, "trust_keywords_in_html_but_verify_prominence", ["html"])
    else:
        confirm(issue, 88, "no_trust_signal_keywords_or_images_found", ["html", "dom_states.json"])


def eval_mobile_tap_targets(issue: dict, ev: dict):
    small = ev.get("small_count", 0)
    ok    = ev.get("ok_count", 0)
    if small == 0:
        suppress(issue, "dom_all_booking_ctas_meet_tap_target_minimums", ["dom_states.json"])
    elif ok == 0 and small > 0:
        confirm(issue, 92, f"dom_confirms_{small}_booking_ctas_all_undersized", ["dom_states.json"])
        issue["affected_elements"] = ev["small_samples"]
    else:
        confirm(issue, 85, f"dom_confirms_{small}_of_{small+ok}_booking_ctas_undersized", ["dom_states.json"])
        issue["affected_elements"] = ev["small_samples"]


# ───────────────────────────────────────────────────────────────────────────────
#  GAP DETECTION
# ───────────────────────────────────────────────────────────────────────────────

EXPECTED_BY_INDUSTRY = {
    "all": [
        "h1_identity", "og_social_meta", "page_meta",
        "heading_hierarchy", "cta_above_fold", "social_proof",
    ],
    "local_business": ["phone_cta", "schema_incomplete", "conversion_form", "trust_signals"],
    "dental":         ["phone_cta", "schema_incomplete", "conversion_form", "trust_signals", "mobile_tap_targets"],
    "medical":        ["phone_cta", "schema_incomplete", "conversion_form", "trust_signals", "mobile_tap_targets"],
    "ecommerce":      ["schema_incomplete", "conversion_form", "lazy_load_images", "mobile_tap_targets"],
    "saas":           ["conversion_form", "og_social_meta", "page_meta", "cta_above_fold"],
    "booking":        ["conversion_form", "phone_cta", "cta_above_fold", "mobile_tap_targets"],
    "restaurant":     ["phone_cta", "schema_incomplete", "conversion_form", "trust_signals"],
    "portfolio":      ["og_social_meta", "page_meta", "social_proof"],
}

GAP_DESCRIPTIONS = {
    "h1_identity":        "H1 value proposition check was expected but not found in report",
    "og_social_meta":     "OG/Twitter social sharing check was expected but not found",
    "page_meta":          "Title/meta description check was expected but not found",
    "duplicate_ids":      "Duplicate ID check was expected but not found",
    "heading_hierarchy":  "Heading structure check was expected but not found",
    "phone_cta":          "Phone CTA clickability check expected for this industry",
    "schema_incomplete":  "Schema.org completeness check expected for local business",
    "conversion_form":    "Conversion form check expected for this industry",
    "lazy_load_images":   "Image lazy-load check expected for this industry",
    "cta_label_quality":  "CTA label quality check expected but not found",
    "cta_above_fold":     "Booking CTA above-the-fold check expected but not found",
    "social_proof":       "Social proof / testimonials check expected but not found",
    "trust_signals":      "Trust signals / certifications check expected for this industry",
    "mobile_tap_targets": "Mobile tap target size check expected for this industry",
}


def detect_gaps(issues: list[dict], industry: str) -> list[dict]:
    found_ids = {iss.get("id", "") for iss in issues}
    expected  = set(EXPECTED_BY_INDUSTRY.get("all", []))
    expected |= set(EXPECTED_BY_INDUSTRY.get(industry, []))
    gaps = []
    for check_id in expected:
        if check_id in found_ids:
            continue
        if f"{check_id}_passed" in found_ids:
            continue
        gaps.append({
            "id":              f"gap_{check_id}",
            "title":           GAP_DESCRIPTIONS.get(check_id, f"Expected check missing: {check_id}"),
            "severity":        "medium",
            "confidence":      "possible",
            "decision":        "verification_required",
            "confidence_score": 0,
            "decision_reasons": ["gap_detector_expected_check_missing"],
            "evidence_refs":   [],
            "cro_impact":      "Unknown — check was not run or produced no findings",
            "revenue_signal":  "Verify this check ran correctly against your page",
            "fix":             f"Re-run the {check_id} bot and inspect manually",
            "findings":        [GAP_DESCRIPTIONS.get(check_id, "")],
            "evidence":        [],
            "origin":          "gap_detector",
        })
    return gaps


# ───────────────────────────────────────────────────────────────────────────────
#  MAIN RUNNER
# ───────────────────────────────────────────────────────────────────────────────

EVALUATOR_MAP = {
    "h1_identity":        (eval_h1,                 "h1_ev"),
    "h1_missing":         (eval_h1,                 "h1_ev"),
    "heading_hierarchy":  (eval_headings,            "heading_ev"),
    "duplicate_ids":      (eval_dupe_ids,            "dupe_ev"),
    "cta_label_quality":  (eval_cta_labels,          "cta_ev"),
    "og_social_meta":     (eval_og_meta,             "og_ev"),
    "schema_incomplete":  (eval_schema,              "schema_ev"),
    "schema_missing":     (eval_schema,              "schema_ev"),
    "page_meta":          (eval_page_meta,           "meta_ev"),
    "lazy_load_images":   (eval_lazy_images,         "img_ev"),
    "conversion_form":    (eval_forms,               "form_ev"),
    "phone_cta":          (eval_phone,               "phone_ev"),
    "cta_above_fold":     (eval_cta_above_fold,      "fold_ev"),
    "social_proof":       (eval_social_proof,        "social_ev"),
    "trust_signals":      (eval_trust_signals,       "trust_ev"),
    "mobile_tap_targets": (eval_mobile_tap_targets,  "tap_ev"),
}


def run_wolf(
    report:       dict,
    html:         str,
    dom_elements: list,
    industry:     str = "all",
) -> dict:
    issues = report.get("issues", [])

    for issue in issues:
        issue.setdefault("decision",          "confirmed")
        issue.setdefault("confidence_score",  80)
        issue.setdefault("decision_reasons",  ["bot_confirmed"])
        issue.setdefault("evidence_refs",     [])
        issue.setdefault("origin",            "bot")

    evidence = {
        "h1_ev":      extract_h1_evidence(html, dom_elements),
        "heading_ev": extract_heading_evidence(dom_elements),
        "dupe_ev":    extract_dupe_id_evidence(dom_elements),
        "cta_ev":     extract_cta_evidence(dom_elements),
        "og_ev":      extract_og_evidence(html),
        "schema_ev":  extract_schema_evidence(html),
        "meta_ev":    extract_title_evidence(html),
        "img_ev":     extract_image_evidence(html, dom_elements),
        "form_ev":    extract_form_evidence(html, dom_elements),
        "phone_ev":   extract_phone_evidence(html),
        "fold_ev":    extract_cta_above_fold_evidence(dom_elements),
        "social_ev":  extract_social_proof_evidence(html, dom_elements),
        "trust_ev":   extract_trust_signals_evidence(html, dom_elements),
        "tap_ev":     extract_mobile_tap_evidence(dom_elements),
    }

    for issue in issues:
        issue_id = issue.get("id", "")
        if issue_id in EVALUATOR_MAP:
            evaluator_fn, ev_key = EVALUATOR_MAP[issue_id]
            try:
                evaluator_fn(issue, evidence[ev_key])
            except Exception as exc:
                issue.setdefault("decision_reasons", []).append(f"wolf_eval_error: {exc}")

    active_issues = [i for i in issues if i.get("decision") != "suppressed"]

    form_ev  = evidence["form_ev"]
    phone_ev = evidence["phone_ev"]
    meta_ev  = evidence["meta_ev"]
    fold_ev  = evidence["fold_ev"]
    social_ev = evidence["social_ev"]
    trust_ev  = evidence["trust_ev"]
    tap_ev    = evidence["tap_ev"]

    if form_ev["booking_link_count"] >= 3 or form_ev["form_count"] > 0:
        active_issues.append({"id": "conversion_form_passed"})
    if phone_ev["tel_href_count"] > 0 and not phone_ev["needs_tel_fix"]:
        active_issues.append({"id": "phone_cta_passed"})
    if not meta_ev["missing"]:
        active_issues.append({"id": "page_meta_passed"})
    if fold_ev["above_fold_count"] > 0:
        active_issues.append({"id": "cta_above_fold_passed"})
    if social_ev["has_any_signal"]:
        active_issues.append({"id": "social_proof_passed"})
    if trust_ev["has_any_signal"]:
        active_issues.append({"id": "trust_signals_passed"})
    if tap_ev["small_count"] == 0:
        active_issues.append({"id": "mobile_tap_targets_passed"})

    gaps = detect_gaps(active_issues, industry)

    active    = [i for i in issues if i.get("decision") != "suppressed"]
    suppressed = [i for i in issues if i.get("decision") == "suppressed"]
    all_out   = active + gaps

    def sort_key(x):
        dec = x.get("decision", "")
        sev = x.get("severity", "low")
        d   = {"confirmed": 0, "verification_required": 1, "suppressed": 2}.get(dec, 3)
        s   = {"high": 0, "medium": 1, "low": 2}.get(sev, 3)
        return (d, s)

    all_out.sort(key=sort_key)

    return {
        "meta": {
            "engine":       "cro_wolf",
            "version":      "1.1",
            "industry":     industry,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "summary": {
            "total":                  len(all_out),
            "confirmed_high":         sum(1 for i in all_out if i.get("decision") == "confirmed" and i.get("severity") == "high"),
            "confirmed_medium":       sum(1 for i in all_out if i.get("decision") == "confirmed" and i.get("severity") == "medium"),
            "verification_required":  sum(1 for i in all_out if i.get("decision") == "verification_required"),
            "suppressed":             len(suppressed),
            "gaps_detected":          len(gaps),
        },
        "issues":     all_out,
        "suppressed": suppressed,
        "evidence_summary": {
            k: {
                kk: vv for kk, vv in v.items()
                if kk not in ("lazy_broken", "truly_broken", "blocks", "items", "small_samples")
            }
            for k, v in evidence.items()
        },
    }


# ───────────────────────────────────────────────────────────────────────────────
#  CLI
# ───────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="CRO Wolf — post-processing confidence engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cro_wolf.py --report cro_report.json --html page.html --dom dom_states.json
  python cro_wolf.py --report cro_report.json --html page.html --dom dom_states.json --industry dental
  python cro_wolf.py --report cro_report.json --html page.html --output cro_final.json
        """
    )
    ap.add_argument("--report",   required=True,  help="cro_report.json from cro_audit.py")
    ap.add_argument("--html",     required=True,  help="full_rendered_inlined.html")
    ap.add_argument("--dom",      default=None,   help="dom_states.json (optional but recommended)")
    ap.add_argument("--industry", default="all",  help="Industry tag: dental, ecommerce, saas, booking, restaurant, local_business (default: all)")
    ap.add_argument("--output",   default=None,   help="Output path (default: prints JSON to stdout)")
    args = ap.parse_args()

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"Error: report not found: {report_path}", file=sys.stderr)
        sys.exit(1)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    html_path = Path(args.html)
    if not html_path.exists():
        print(f"Error: HTML not found: {html_path}", file=sys.stderr)
        sys.exit(1)
    html = html_path.read_text(encoding="utf-8", errors="ignore")

    dom_elements = []
    if args.dom:
        dom_path = Path(args.dom)
        if dom_path.exists():
            dom_data     = json.loads(dom_path.read_text(encoding="utf-8"))
            dom_elements = dom_data.get("elements", [])
        else:
            print(f"Warning: DOM file not found: {dom_path}", file=sys.stderr)

    result = run_wolf(report, html, dom_elements, industry=args.industry)

    out_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(out_json, encoding="utf-8")
        s = result["summary"]
        print(f"[cro_wolf] Done →  {args.output}")
        print(f"  Confirmed HIGH    : {s['confirmed_high']}")
        print(f"  Confirmed MEDIUM  : {s['confirmed_medium']}")
        print(f"  Needs verification: {s['verification_required']}")
        print(f"  Suppressed (FP)   : {s['suppressed']}")
        print(f"  Gaps detected     : {s['gaps_detected']}")
    else:
        print(out_json)

    sys.exit(result["summary"]["confirmed_high"])


if __name__ == "__main__":
    main()
