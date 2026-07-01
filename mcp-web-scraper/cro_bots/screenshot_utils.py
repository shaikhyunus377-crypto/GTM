"""
screenshot_utils.py — Crop and annotate page screenshots per CRO issue.

Given the full-page screenshot (base64 PNG) + the dom_states elements (which
carry real bounding boxes), this locates WHERE each CRO issue lives on the page,
crops that region, and draws a red highlight around the offending element(s) so
the prospect can literally see the problem.

Requires Pillow. Gracefully no-ops if not installed.
"""
from __future__ import annotations
import base64
import io
import re

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

LAYOUT_WIDTH = 1440   # window width used when DOM coordinates were captured
PAD_TOP      = 70
PAD_BOTTOM   = 90
MIN_HEIGHT   = 220    # never return a sliver crop
MAX_HEIGHT   = 900    # cap crop height for readability
OUT_MAX_W    = 1000   # downscale wide crops to keep payload small
MAX_CROPS    = 10     # safety cap on crops per report


# ── image helpers ────────────────────────────────────────────────────────────

def _decode(screenshot_b64: str):
    if not PIL_AVAILABLE:
        return None
    try:
        return Image.open(io.BytesIO(base64.b64decode(screenshot_b64))).convert("RGBA")
    except Exception:
        return None


def _encode(img) -> str:
    if img.width > OUT_MAX_W:
        ratio = OUT_MAX_W / img.width
        img = img.resize((OUT_MAX_W, int(img.height * ratio)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def _crop_and_highlight(img, rects: list[dict], region: tuple[int, int] | None) -> str | None:
    """rects/region are in LAYOUT (CSS 1440) px. Returns base64 PNG or None."""
    full_w, full_h = img.size
    scale = full_w / LAYOUT_WIDTH

    if rects:
        y_top    = min(r["y"] for r in rects)
        y_bottom = max(r["y"] + r["height"] for r in rects)
    elif region:
        y_top, y_bottom = region
    else:
        return None

    crop_top    = max(0, int(y_top * scale) - PAD_TOP)
    crop_bottom = min(full_h, int(y_bottom * scale) + PAD_BOTTOM)
    crop_bottom = max(crop_bottom, crop_top + MIN_HEIGHT)
    if crop_bottom - crop_top > MAX_HEIGHT:
        crop_bottom = crop_top + MAX_HEIGHT
    crop_bottom = min(crop_bottom, full_h)
    if crop_bottom <= crop_top:
        return None

    cropped = img.crop((0, crop_top, full_w, crop_bottom))

    if rects:
        draw = ImageDraw.Draw(cropped, "RGBA")
        for r in rects:
            x = int(r["x"] * scale)
            y = int(r["y"] * scale) - crop_top
            w = int(r["width"] * scale)
            h = int(r["height"] * scale)
            if w < 4 or h < 4:
                continue
            # padded halo so the box frames the element rather than covering it
            draw.rectangle([x - 4, y - 4, x + w + 4, y + h + 4],
                           fill=(255, 0, 0, 38), outline=(220, 30, 30, 235), width=3)
    return _encode(cropped)


# ── DOM element helpers ──────────────────────────────────────────────────────

def _bbox(el: dict) -> dict:
    return (el.get("states", {}).get("default", {}).get("bbox", {})) or {}

def _rect(el: dict) -> dict | None:
    b = _bbox(el)
    y, w, h = b.get("y", 0), b.get("width", 0), b.get("height", 0)
    if y > 0 and w > 0 and h > 0:
        return {"x": b.get("x", 0), "y": y, "width": w, "height": h}
    return None

def _text(el: dict) -> str:
    return (el.get("text") or "").lower()


BOOKING_RE = re.compile(r"book|schedul|appoint|reserv|consult|get start|sign up|free trial|contact|call now|get quote|request", re.I)
REVIEW_RE  = re.compile(r"review|testimonial|rating|stars?|\d\.\d\s*/\s*5|verified|what our|clients? say", re.I)
TRUST_RE   = re.compile(r"certif|accredit|award|insur|licens|bbb|trustpilot|guarantee|member of|years? (of )?experience", re.I)
PHONE_RE   = re.compile(r"\+?\d[\d\s\-().]{6,}\d")


def _rects_for_issue(issue: dict, dom: list[dict]) -> tuple[list[dict], tuple[int, int] | None]:
    """Return (highlight_rects, fallback_region) for a given issue."""
    iid = (issue.get("id") or "").lower()

    # 1) affected_elements that already carry coordinates (e.g. mobile tap targets)
    coord_rects = []
    for e in issue.get("affected_elements") or []:
        y = e.get("y", 0); h = e.get("h", e.get("height", 0)); w = e.get("w", e.get("width", 0))
        if y and (w or h):
            coord_rects.append({"x": e.get("x", 0), "y": y, "width": max(w, 40), "height": max(h, 24)})
    if coord_rects:
        return coord_rects[:6], None

    def pick(pred, limit=6):
        out = []
        for el in dom:
            r = _rect(el)
            if r and pred(el):
                out.append(r)
            if len(out) >= limit:
                break
        return out

    headings = ("h1", "h2", "h3", "h4", "h5", "h6")

    # 2) map by issue id → DOM elements
    if iid in ("h1_identity", "h1_missing", "h1"):
        r = pick(lambda e: e.get("tag") == "h1", limit=1) or pick(lambda e: e.get("tag") == "h2", limit=1)
        return r, (0, 700)
    if iid in ("heading_hierarchy", "headings"):
        return pick(lambda e: e.get("tag") in headings, limit=8), (0, 1000)
    if iid in ("cta_above_fold",):
        r = pick(lambda e: e.get("tag") in ("a", "button") and BOOKING_RE.search(_text(e)) and _bbox(e).get("y", 9999) <= 900)
        return r, (0, 800)
    if iid in ("cta_label_quality", "cta_labels"):
        r = pick(lambda e: e.get("tag") in ("a", "button") and _text(e) and (e.get("text") or "") == (e.get("text") or "").upper() and len((e.get("text") or "")) > 2)
        return (r or pick(lambda e: e.get("tag") in ("a", "button"))), None
    if iid in ("conversion_form", "form_missing", "forms"):
        r = pick(lambda e: e.get("tag") == "form")
        r = r or pick(lambda e: e.get("tag") in ("a", "button") and BOOKING_RE.search(_text(e)))
        return r, None
    if iid in ("phone_cta", "phone"):
        return pick(lambda e: PHONE_RE.search(_text(e))), None
    if iid in ("social_proof",):
        return pick(lambda e: REVIEW_RE.search(_text(e))), None
    if iid in ("trust_signals",):
        return pick(lambda e: TRUST_RE.search(_text(e))), None
    if iid in ("lazy_load_images", "images"):
        return pick(lambda e: e.get("tag") == "img", limit=5), None
    if iid in ("mobile_tap_targets",):
        return pick(lambda e: e.get("tag") in ("a", "button") and BOOKING_RE.search(_text(e))), None
    if iid in ("duplicate_ids",):
        dup_ids = {str(a.get("id")) for a in issue.get("affected_elements") or [] if a.get("id")}
        return pick(lambda e: str(e.get("id")) in dup_ids), None

    # 3) hero / structural findings with no element handle → region only
    HERO = {"hero_carousel", "hero_primary_cta_missing", "hero_value_proposition",
            "hero_action_clarity", "offer_clarity", "cta_hierarchy"}
    if iid in HERO:
        return [], (0, 900)
    if iid in ("social_proof_near_cta",):
        return [], (0, 1200)
    if iid in ("nav_overload", "page_structure"):
        return pick(lambda e: e.get("tag") in ("header", "nav")), (0, 240)

    # 4) pure <head>/meta findings (og, schema, page_meta) — nothing to point at
    return [], None


def attach_crops(issues: list[dict], screenshot_b64: str | None, dom_elements: list[dict] | None = None) -> None:
    """
    Mutate each issue in-place: add 'screenshot_crop' (base64 PNG) where a
    location on the page can be determined. Safe to call with missing PIL /
    screenshot / dom.
    """
    if not screenshot_b64 or not PIL_AVAILABLE:
        return
    img = _decode(screenshot_b64)
    if img is None:
        return
    dom = dom_elements or []

    made = 0
    for issue in issues:
        if made >= MAX_CROPS:
            break
        try:
            rects, region = _rects_for_issue(issue, dom)
            crop = _crop_and_highlight(img, rects, region)
        except Exception:
            crop = None
        if crop:
            issue["screenshot_crop"]  = crop
            issue["crop_highlighted"] = bool(rects)
            made += 1
