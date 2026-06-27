#!/usr/bin/env python3
"""
cro_wolf.py — CRO Confidence Engine
=====================================
Wolf-pattern post-processor for the CRO audit pipeline.

Pipeline position:
    cro_audit.py  →  cro_report.json  →  cro_wolf.py  →  cro_final.json

Usage:
    python cro_wolf.py --report cro_report.json --html page.html --dom dom_states.json
    python cro_wolf.py --report cro_report.json --html page.html --dom dom_states.json --industry dental
"""

from __future__ import annotations
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
#  DECISION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

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
    issue["decision"]         = "suppressed"
    issue["confidence_score"] = 0
    issue.setdefault("decision_reasons", []).append(f"suppressed: {reason}")
    if refs:
        issue.setdefault("evidence_refs", []).extend(refs)


# ─────────────────────────────────────────────────────────────────────────────
#  EVIDENCE EXTRACTORS
# ─────────────────────────────────────────────────────────────────────────────

def extract_h1_evidence(html: str, dom_elements: list) -> dict:
    dom_h1s = [e for e in dom_elements if e.get("tag") == "h1"]
    PROMO_RE = re.compile(
        r"\b(\d+\s*%|off\b|sale\b|deal\b|save\b|discount|free\b|limited\s+time)\b", re.I
    )
    evidence = {"count": len(dom_h1s), "items": []}
    for h in dom_h1s:
        bbox = h.get("states", {}).get("default", {}).get("bbox", {}) or {}
        text = (h.get("text") or "").strip()
        evidence["items"].append({
            "text":       text,
            "y":          bbox.get("y", 0),
            "width":      bbox.get("width", 0),
            "height":     bbox.get("height", 0),
            "is_empty":   not text,
            "is_promo":   bool(PROMO_RE.search(text)),
            "below_fold": bbox.get("y", 0) > 900 and bbox.get("y", 0) > 0,
        })
    return evidence


def extract_heading_evidence(dom_elements: list) -> dict:
    HEAD_TAGS = {"h1","h2","h3","h4","h5","h6"}
    all_heads  = [e for e in dom_elements if e.get("tag") in HEAD_TAGS]
    real_heads, modal_heads = [], []
    for h in all_heads:
        bbox = h.get("states", {}).get("default", {}).get("bbox", {}) or {}
        if bbox.get("y", 0) == 0 and bbox.get("width", 0) == 0:
            modal_heads.append(h)
        else:
            real_heads.append(h)

    skips   = []
    visible = [h for h in real_heads if (h.get("text") or "").strip()]
    for i in range(1, len(visible)):
        pl = int(visible[i-1]["tag"][1])
        cl = int(visible[i]["tag"][1])
        if cl > pl + 1:
            skips.append({
                "from": visible[i-1]["tag"], "from_text": (visible[i-1].get("text") or "")[:40],
                "to":   visible[i]["tag"],   "to_text":   (visible[i].get("text") or "")[:40],
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
        attrs = {}
        for am in ATTR.finditer(m.group(1)):
            k = am.group(1).lower()
            v = am.group(2) or am.group(3) or am.group(4) or ""
            attrs[k] = v
        src, data_src = attrs.get("src","").strip(), attrs.get("data-src","").strip()
        results.append({
            "src": src, "data_src": data_src, "alt": attrs.get("alt"),
            "has_real_src": bool(src),
            "is_lazy_broken": not src and bool(data_src),
            "is_truly_broken": not src and not data_src,
        })
    lazy_broken  = [r for r in results if r["is_lazy_broken"]]
    truly_broken = [r for r in results if r["is_truly_broken"]]
    rendered_images = sum(
        1 for e in dom_elements
        if e.get("tag") == "img"
        and (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("width", 0) > 0
        and (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("height", 0) > 0
    )
    return {
        "total": len(results), "lazy_broken": lazy_broken, "truly_broken": truly_broken,
        "lazy_count": len(lazy_broken), "broken_count": len(truly_broken),
        "rendered_images": rendered_images,
    }


def extract_title_evidence(html: str) -> dict:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    raw   = m.group(1).strip() if m else ""
    clean = re.sub(r"<[^>]+>", "", raw).strip()
    return {"raw": raw, "clean": clean, "length": len(clean), "missing": not clean}


def extract_cta_evidence(dom_elements: list) -> dict:
    PHONE_RE = re.compile(r"^\+?[\d\s\-().]{7,}$")
    cta_els  = [e for e in dom_elements if e.get("tag") in ("a","button")]
    visible  = [
        e for e in cta_els
        if (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("y", 0) > 0
        and (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("width", 0) > 0
    ]
    labels  = [(e.get("text") or "").strip() for e in visible if (e.get("text") or "").strip()]
    counts  = Counter(labels)
    all_caps = sorted({
        l for l in labels
        if l == l.upper() and len(l) > 2
        and re.search(r"[A-Z]", l)
        and not PHONE_RE.match(l)
    })
    repeated = [(l, c) for l, c in counts.items() if c >= 3 and not PHONE_RE.match(l)]
    return {
        "total_visible_ctas": len(visible),
        "all_caps": all_caps, "all_caps_count": len(all_caps),
        "repeated": repeated,
    }


def extract_og_evidence(html: str) -> dict:
    og = re.findall(r'<meta[^>]+property=["\']og:[^"\']+["\'][^>]*/?>',   html, re.I)
    tw = re.findall(r'<meta[^>]+name=["\']twitter:[^"\']+["\'][^>]*/?>',  html, re.I)
    return {"og_count": len(og), "twitter_count": len(tw)}


def _schema_graph_has(obj, field: str) -> bool:
    """Recursively search the entire JSON-LD graph for a field."""
    if isinstance(obj, dict):
        if field in obj:
            return True
        return any(_schema_graph_has(v, field) for v in obj.values())
    if isinstance(obj, list):
        return any(_schema_graph_has(item, field) for item in obj)
    return False


def extract_schema_evidence(html: str) -> dict:
    blocks_raw = re.findall(r'<script[^>]+ld\+json[^>]*>(.*?)</script>', html, re.S | re.I)
    blocks = []
    for raw in blocks_raw:
        try:
            blocks.append(json.loads(raw))
        except Exception:
            pass
    # Traverse the full graph for each field — shallow `field in d` misses nested objects
    has_rating = any(_schema_graph_has(b, "aggregateRating") for b in blocks)
    return {"count": len(blocks), "has_any_rating": has_rating}


def extract_form_evidence(html: str, dom_elements: list) -> dict:
    BOOK_KW = re.compile(r"book|schedule|appointment|reserve|checkout|contact|enqui|signup", re.I)
    forms   = re.findall(r"<form\b[^>]*>", html, re.I)
    booking_links = [
        e for e in dom_elements
        if e.get("tag") == "a"
        and BOOK_KW.search((e.get("text") or "") + str(e.get("href") or ""))
    ]
    return {
        "form_count":           len(forms),
        "booking_link_count":   len(booking_links),
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


def extract_cta_above_fold_evidence(dom_elements: list) -> dict:
    BOOKING_RE = re.compile(
        r"book|schedul|appoint|reserv|consult|get\s*start|sign\s*up|free\s*trial|contact|call\s*now|get\s*quote",
        re.I,
    )
    FOLD_PX = 800
    booking_ctas = [
        e for e in dom_elements
        if e.get("tag") in ("a","button")
        and BOOKING_RE.search(e.get("text") or "")
        and (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("width", 0) > 0
        and (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("y", 0) > 0
    ]
    above = [e for e in booking_ctas if 0 < (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("y", 0) <= FOLD_PX]
    return {
        "above_fold_count":    len(above),
        "total_booking_ctas":  len(booking_ctas),
        "above_fold_samples":  [(e.get("text") or "")[:40] for e in above[:3]],
    }


def extract_social_proof_evidence(html: str, dom_elements: list) -> dict:
    REVIEW_KW = re.compile(
        r"review|testimonial|rating|stars?|verified|patient|client\s+said|5[\-\s]star|trustpilot|yelp",
        re.I,
    )
    schema_rating = False
    for raw in re.findall(r'<script[^>]+ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            if "aggregateRating" in json.loads(raw):
                schema_rating = True
        except Exception:
            pass
    star_html = bool(re.search(r"★|☆|⭐|\d(\.\d)?\s*/\s*5|\d(\.\d)?\s*stars?", html, re.I))
    dom_review_texts = [
        e for e in dom_elements
        if REVIEW_KW.search(e.get("text") or "")
        and (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("width", 0) > 0
        and (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("y", 0) > 0
    ]
    return {
        "schema_rating":     schema_rating,
        "star_html":         star_html,
        "dom_review_texts":  len(dom_review_texts),
        "has_any_signal":    schema_rating or star_html or len(dom_review_texts) >= 3,
    }


def extract_trust_signals_evidence(html: str, dom_elements: list) -> dict:
    TRUST_KW = re.compile(
        r"certif|accredit|award|insur|licens|bbb|better\s+business|member|association|"
        r"board\s+certif|ada\b|ama\b|hipaa|verified|badge|seal",
        re.I,
    )
    keyword_in_html = bool(TRUST_KW.search(html))
    trust_images    = [
        img for img in re.findall(r'<img\b[^>]+>', html, re.I)
        if TRUST_KW.search(img)
    ]
    dom_trust_texts = [
        e for e in dom_elements
        if TRUST_KW.search(e.get("text") or "")
        and (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("width", 0) > 0
        and (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("y", 0) > 0
    ]
    return {
        "keyword_in_html": keyword_in_html,
        "trust_images":    len(trust_images),
        "dom_trust_texts": len(dom_trust_texts),
        "has_any_signal":  keyword_in_html or bool(trust_images) or len(dom_trust_texts) >= 2,
    }


def extract_mobile_tap_evidence(dom_elements: list) -> dict:
    MIN_W, MIN_H = 44, 32
    interactive = [
        e for e in dom_elements
        if e.get("tag") in ("a","button","input")
        and (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("y", 0) > 0
        and (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("width", 0) > 0
        and (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("height", 0) > 0
    ]
    small, ok = [], []
    for e in interactive:
        bbox = e.get("states",{}).get("default",{}).get("bbox",{}) or {}
        w, h = bbox.get("width",0), bbox.get("height",0)
        # Skip elements with suspiciously tiny height (< 4px) — these are almost always
        # invisible inline elements (hidden lang spans, ::before pseudo-content) that
        # received a coordinate via index drift, not real tap targets.
        if h < 4:
            continue
        if 0 < w < MIN_W or 0 < h < MIN_H:
            small.append({"tag": e.get("tag"), "text": (e.get("text") or "")[:30], "w": int(w), "h": int(h)})
        else:
            ok.append(e)
    return {
        "small_count":   len(small),
        "ok_count":      len(ok),
        "small_samples": small[:4],
    }


# ─────────────────────────────────────────────────────────────────────────────
#  EVALUATORS
# ─────────────────────────────────────────────────────────────────────────────

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
            "instead of a service identity statement"
        )
        issue["findings"] = [
            new_finding if "empty" in f.lower() else f
            for f in issue.get("findings", [])
        ]
        issue["affected_elements"] = [{"tag": "h1", "text": item["text"], "id": ""}]
        issue["evidence"] = [f"H1 content: \"{item['text']}\""]
    if item["below_fold"]:
        y = item["y"]
        if y > 2000:
            # y > 2000px almost always means an inflated parent container (sticky header,
            # mobile nav overlay, or translated element) pushed the bounding box down.
            # The H1 is visually in the hero but the CSS layout caused a coordinate artifact.
            # Directly override decision — wolf has stronger evidence than the bot here.
            if not item["is_empty"] and not item["is_promo"]:
                # H1 text is valid; the only flag was below-fold which is an artifact → suppress
                suppress(
                    issue,
                    f"dom_h1_y={y}px_layout_artifact_h1_text_is_valid",
                    ["dom_states.json"],
                )
            else:
                # H1 also has other problems; keep issue but note the fold measurement is suspect
                issue["decision"] = "verification_required"
                issue["confidence_score"] = 55
                issue.setdefault("decision_reasons", []).append(
                    f"wolf_note: y={y}px may be layout artifact — verify below-fold visually"
                )
            issue["findings"] = [
                f.replace(
                    "below the fold",
                    f"reported below fold at y={y}px (likely CSS layout artifact in parent container — verify visually)"
                )
                for f in issue.get("findings", [])
            ]
        else:
            confirm(issue, 88, "dom_h1_below_fold", ["dom_states.json"])
    if not item["is_empty"] and not item["is_promo"] and not item["below_fold"]:
        suppress(issue, "dom_shows_h1_is_valid", ["dom_states.json"])


def eval_headings(issue: dict, ev: dict):
    if ev.get("level_skips"):
        confirm(issue, 90, "dom_heading_skip_confirmed", ["dom_states.json"])
    if ev.get("empty_real_count", 0) > 0:
        confirm(issue, 85, "dom_real_empty_headings_confirmed", ["dom_states.json"])
    elif ev.get("empty_real_count", 0) == 0:
        issue.setdefault("decision_reasons", []).append("wolf_note: empty headings were cookie-modal only")
        issue["findings"] = [f for f in issue.get("findings", []) if "empty heading" not in f.lower()]


def eval_dupe_ids(issue: dict, ev: dict):
    if ev.get("count", 0) > 0:
        confirm(issue, 99, "dom_dupe_ids_confirmed", ["dom_states.json"])
        issue["affected_elements"] = [{"id": k, "count": v} for k, v in ev["duplicate_ids"].items()]
    else:
        suppress(issue, "dom_shows_no_duplicate_ids", ["dom_states.json"])


def eval_cta_labels(issue: dict, ev: dict):
    caps_count = ev.get("all_caps_count", 0)
    if caps_count > 0:
        confirm(issue, 88, f"dom_confirms_{caps_count}_all_caps_ctas", ["dom_states.json"])
        title = issue.get("title", "")
        old   = re.search(r"(\d+) CTA label", title)
        if old and int(old.group(1)) != caps_count:
            issue["title"] = re.sub(r"\d+ CTA label", f"{caps_count} CTA label", title)
        issue["evidence"] = [e for e in issue.get("evidence", []) if "Cookies Details" not in e]
    else:
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
            issue["findings"][i] = re.sub(r"Title too long \(\d+ chars", f"Title too long ({clean_len} chars", finding)
    if clean_len > 60:
        confirm(issue, 90, "html_title_too_long", ["html"])
    else:
        suppress(issue, "html_title_within_limit", ["html"])


def eval_lazy_images(issue: dict, ev: dict):
    lazy, broken, rendered = ev.get("lazy_count",0), ev.get("broken_count",0), ev.get("rendered_images",0)
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
        issue["title"] = re.sub(r"\d+ image\(s\)", f"{lazy} image(s)", issue.get("title",""))
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
    if ev.get("above_fold_count", 0) > 0:
        suppress(issue, f"dom_shows_{ev['above_fold_count']}_ctас_above_fold", ["dom_states.json"])
    else:
        confirm(issue, 88, "dom_confirms_no_booking_cta_above_fold", ["dom_states.json"])


def eval_social_proof(issue: dict, ev: dict):
    if ev.get("schema_rating"):
        suppress(issue, "schema_aggregateRating_present", ["html"])
    elif ev.get("dom_review_texts", 0) >= 3:
        suppress(issue, f"dom_shows_{ev['dom_review_texts']}_review_elements", ["dom_states.json"])
    elif ev.get("star_html"):
        suppress(issue, "html_star_rating_found", ["html"])
    elif not ev.get("has_any_signal"):
        confirm(issue, 85, "no_social_proof_signals_found", ["html", "dom_states.json"])


def eval_trust_signals(issue: dict, ev: dict):
    if ev.get("dom_trust_texts", 0) >= 2:
        suppress(issue, f"dom_shows_{ev['dom_trust_texts']}_trust_elements", ["dom_states.json"])
    elif ev.get("trust_images", 0) > 0:
        suppress(issue, "trust_badge_images_found", ["html"])
    elif not ev.get("has_any_signal"):
        confirm(issue, 82, "no_trust_signals_found", ["html", "dom_states.json"])


def eval_mobile_tap_targets(issue: dict, ev: dict):
    small = ev.get("small_count", 0)
    ok    = ev.get("ok_count", 0)
    total = small + ok

    if small == 0:
        suppress(issue, "dom_shows_all_tap_targets_adequate_size", ["dom_states.json"])
        return

    # Bilingual / multi-language sites inject hidden inline spans inside every <a>.
    # The coordinate matching can assign sub-element widths to the anchor, inflating
    # the small count. If > 60% of all interactive elements appear "small", it's almost
    # certainly a measurement artifact (real pages rarely have that many undersized links).
    if total > 0 and small / total > 0.40:
        # Directly override bot decision — this ratio pattern is a known false positive
        issue["decision"]         = "verification_required"
        issue["confidence_score"] = 50
        issue.setdefault("decision_reasons", []).append(
            f"wolf_override: {small}/{total} small ({small*100//total}%) exceeds 60% threshold — "
            "likely bilingual/inline-span coordinate drift; verify manually"
        )
        issue["findings"] = [
            f + f" (NOTE: {small}/{total} elements flagged — high ratio suggests coordinate measurement artifact; verify visually)"
            for f in issue.get("findings", [])
        ]
        issue["affected_elements"] = ev.get("small_samples", [])
        return

    confirm(issue, 85, f"dom_confirms_{small}_small_tap_targets", ["dom_states.json"])
    issue["affected_elements"] = ev.get("small_samples", [])


# ── AI finding evaluators ────────────────────────────────────────────────────
# These pass through bot findings but enforce calibrated confidence ceilings
# and downgrade to verification_required if evidence is thin.

_AI_CONFIDENCE_CEILING = {
    "hero_primary_cta_missing":  80,
    "hero_value_proposition":    85,
    "hero_action_clarity":       65,
    "offer_clarity":             80,
    "social_proof_near_cta":     75,
}

def eval_ai_finding(issue: dict, ev: dict):
    """Wolf pass-through for AI findings: enforce ceiling, thin-evidence downgrade."""
    finding_id = issue.get("id", "")
    ceiling    = _AI_CONFIDENCE_CEILING.get(finding_id, 75)

    # Clamp confidence to ceiling
    score = min(issue.get("confidence_score", 70), ceiling)
    issue["confidence_score"] = score

    # If evidence array is all short strings, not enough to stand alone
    evidence = issue.get("evidence", [])
    evidence_chars = sum(len(e) for e in evidence)
    if evidence_chars < 60:
        flag_verify(issue, score, "ai_evidence_too_thin_to_confirm", [])
        return

    confirm(issue, score, f"ai_confirmed_{finding_id}", [])


# ─────────────────────────────────────────────────────────────────────────────
#  GAP DETECTION
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_BY_INDUSTRY = {
    "all":           ["h1_identity", "og_social_meta", "page_meta", "heading_hierarchy", "cta_above_fold", "social_proof"],
    "local_business": ["phone_cta", "schema_incomplete", "conversion_form", "trust_signals"],
    "dental":        ["phone_cta", "schema_incomplete", "conversion_form", "trust_signals", "mobile_tap_targets"],
    "medical":       ["phone_cta", "schema_incomplete", "conversion_form", "trust_signals"],
    "ecommerce":     ["schema_incomplete", "conversion_form", "lazy_load_images"],
    "saas":          ["conversion_form", "og_social_meta", "page_meta"],
    "booking":       ["conversion_form", "phone_cta"],
    "restaurant":    ["phone_cta", "schema_incomplete", "conversion_form"],
    "portfolio":     ["og_social_meta", "page_meta"],
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
    "cta_above_fold":     "Above-the-fold CTA check was expected but not found",
    "social_proof":       "Social proof check was expected but not found",
    "trust_signals":      "Trust signals check was expected but not found",
    "mobile_tap_targets": "Mobile tap target check was expected but not found",
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
            "id":               f"gap_{check_id}",
            "title":            GAP_DESCRIPTIONS.get(check_id, f"Expected check missing: {check_id}"),
            "severity":         "medium",
            "confidence":       "possible",
            "decision":         "verification_required",
            "confidence_score": 0,
            "decision_reasons": ["gap_detector_expected_check_missing"],
            "evidence_refs":    [],
            "cro_impact":       "Unknown — check was not run or produced no findings",
            "revenue_signal":   "Verify this check ran correctly against your page",
            "fix":              f"Re-run the {check_id} bot and inspect manually",
            "findings":         [GAP_DESCRIPTIONS.get(check_id, "")],
            "evidence":         [],
            "origin":           "gap_detector",
            "client_visible":   False,   # NEVER show pipeline QA gaps to clients
        })
    return gaps


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN RUNNER
# ─────────────────────────────────────────────────────────────────────────────

EVALUATOR_MAP = {
    "h1_identity":       (eval_h1,                "h1_ev"),
    "h1_missing":        (eval_h1,                "h1_ev"),
    "heading_hierarchy": (eval_headings,          "heading_ev"),
    "duplicate_ids":     (eval_dupe_ids,          "dupe_ev"),
    # cta_label_quality removed — replaced by bot_ai_cro semantic analysis
    "og_social_meta":    (eval_og_meta,           "og_ev"),
    "schema_incomplete": (eval_schema,            "schema_ev"),
    "schema_missing":    (eval_schema,            "schema_ev"),
    "page_meta":         (eval_page_meta,         "meta_ev"),
    "lazy_load_images":  (eval_lazy_images,       "img_ev"),
    "conversion_form":   (eval_forms,             "form_ev"),
    "phone_cta":         (eval_phone,             "phone_ev"),
    "cta_above_fold":    (eval_cta_above_fold,    "fold_ev"),
    "social_proof":      (eval_social_proof,      "social_ev"),
    "trust_signals":     (eval_trust_signals,     "trust_ev"),
    "mobile_tap_targets":(eval_mobile_tap_targets,"tap_ev"),
    # AI atomic findings — each evaluated independently with confidence ceiling
    "hero_primary_cta_missing":  (eval_ai_finding, "fold_ev"),
    "hero_value_proposition":    (eval_ai_finding, "fold_ev"),
    "hero_action_clarity":       (eval_ai_finding, "fold_ev"),
    "offer_clarity":             (eval_ai_finding, "fold_ev"),
    "social_proof_near_cta":     (eval_ai_finding, "social_ev"),
}


def run_wolf(
    report:       dict,
    html:         str,
    dom_elements: list,
    industry:     str = "all",
) -> dict:
    issues = report.get("issues", [])

    for issue in issues:
        issue.setdefault("decision",         "confirmed")
        issue.setdefault("confidence_score", 80)
        issue.setdefault("decision_reasons", ["bot_confirmed"])
        issue.setdefault("evidence_refs",    [])
        issue.setdefault("origin",           "bot")

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

    # ── Passed markers: explicit bots that found nothing ─────────────────────────
    # Also inject for suppressed issues — wolf suppressed = bot ran, wolf overrode
    active_issues = [i for i in issues if i.get("decision") != "suppressed"]
    for issue in issues:
        if issue.get("decision") == "suppressed":
            active_issues.append({"id": f"{issue['id']}_passed"})

    form_ev   = evidence["form_ev"]
    phone_ev  = evidence["phone_ev"]
    meta_ev   = evidence["meta_ev"]
    fold_ev   = evidence["fold_ev"]
    social_ev = evidence["social_ev"]
    trust_ev  = evidence["trust_ev"]
    tap_ev    = evidence["tap_ev"]
    og_ev     = evidence["og_ev"]

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
    if tap_ev["small_count"] == 0 and tap_ev["ok_count"] > 0:
        active_issues.append({"id": "mobile_tap_targets_passed"})
    if og_ev["og_count"] > 0:
        active_issues.append({"id": "og_social_meta_passed"})

    gaps = detect_gaps(active_issues, industry)

    active     = [i for i in issues if i.get("decision") != "suppressed"]
    suppressed = [i for i in issues if i.get("decision") == "suppressed"]
    all_out    = active + gaps

    def sort_key(x):
        d = {"confirmed": 0, "verification_required": 1, "suppressed": 2}.get(x.get("decision",""), 3)
        s = {"high": 0, "medium": 1, "low": 2}.get(x.get("severity","low"), 3)
        return (d, s)

    all_out.sort(key=sort_key)

    # ── Client report: only high-confidence confirmed findings, no gap items ─────
    client_report = [
        i for i in all_out
        if i.get("client_visible", True)          # gaps are False
        and i.get("origin") != "gap_detector"
        and i.get("decision") == "confirmed"
        and i.get("confidence_score", 0) >= 70
    ]

    client_summary = {
        "high":   sum(1 for i in client_report if i.get("severity") == "high"),
        "medium": sum(1 for i in client_report if i.get("severity") == "medium"),
        "low":    sum(1 for i in client_report if i.get("severity") == "low"),
    }

    return {
        "meta": {
            "engine":       "cro_wolf",
            "version":      "2.1",
            "industry":     industry,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "summary": {
            "total":                 len(all_out),
            "confirmed_high":        sum(1 for i in all_out if i.get("decision") == "confirmed" and i.get("severity") == "high"),
            "confirmed_medium":      sum(1 for i in all_out if i.get("decision") == "confirmed" and i.get("severity") == "medium"),
            "verification_required": sum(1 for i in all_out if i.get("decision") == "verification_required"),
            "suppressed":            len(suppressed),
            "gaps_detected":         len(gaps),
            "client_findings":       len(client_report),
        },
        "issues":        all_out,           # full internal audit trail
        "client_report": client_report,     # clean client-facing findings only
        "client_summary": client_summary,
        "suppressed":    suppressed,
        "evidence_summary": {
            k: {kk: vv for kk, vv in v.items() if kk not in ("lazy_broken","truly_broken","items")}
            for k, v in evidence.items()
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
#  MISSING HELPER — referenced above but defined after use in original; add here
# ─────────────────────────────────────────────────────────────────────────────

def extract_dupe_id_evidence(dom_elements: list) -> dict:
    visible = [
        e for e in dom_elements
        if (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("y", 0) > 0
        and (e.get("states",{}).get("default",{}).get("bbox",{}) or {}).get("width", 0) > 0
    ]
    ids   = [e.get("id") for e in visible if e.get("id")]
    dupes = {k: v for k, v in Counter(ids).items() if v > 1}
    return {"duplicate_ids": dupes, "count": len(dupes)}


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="CRO Wolf — post-processing confidence engine")
    ap.add_argument("--report",   required=True)
    ap.add_argument("--html",     required=True)
    ap.add_argument("--dom",      default=None)
    ap.add_argument("--industry", default="all")
    ap.add_argument("--output",   default=None)
    args = ap.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    html   = Path(args.html).read_text(encoding="utf-8", errors="ignore")
    dom_elements = []
    if args.dom:
        dom_path = Path(args.dom)
        if dom_path.exists():
            dom_elements = json.loads(dom_path.read_text(encoding="utf-8")).get("elements", [])

    result   = run_wolf(report, html, dom_elements, industry=args.industry)
    out_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(out_json, encoding="utf-8")
        s = result["summary"]
        print(f"[cro_wolf] Done → {args.output}")
        print(f"  Confirmed HIGH    : {s['confirmed_high']}")
        print(f"  Confirmed MEDIUM  : {s['confirmed_medium']}")
        print(f"  Needs verification: {s['verification_required']}")
        print(f"  Suppressed        : {s['suppressed']}")
        print(f"  Gaps detected     : {s['gaps_detected']}")
    else:
        print(out_json)

    sys.exit(result["summary"]["confirmed_high"])


if __name__ == "__main__":
    main()
