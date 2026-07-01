"""
screenshot_utils.py — Crop and annotate page screenshots per CRO issue.

Produces an evidence image per issue in the reference style:
  • a baked-in header band: ISSUE / Evidence Strategy / System Match Confidence /
    Context Target String
  • a tight ORANGE box around the specific offending element when it can be
    located on the *visible* page (high confidence)
  • a clean orange section frame ("Contextual Layout Framing Viewport") when the
    issue is layout-level and no single element applies (low confidence)
  • nothing (crop skipped) when a specific element exists only on a hidden /
    off-slide carousel panel — never highlight blank space.

Requires Pillow. Gracefully no-ops if not installed.
"""
from __future__ import annotations
import base64
import io
import re

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

LAYOUT_WIDTH = 1440
PAD_TOP      = 70
PAD_BOTTOM   = 90
MIN_HEIGHT   = 240
MAX_HEIGHT   = 940
OUT_MAX_W    = 1000
MAX_CROPS    = 10
HEADER_H     = 96

ORANGE       = (245, 158, 11, 255)
ORANGE_FILL  = (245, 158, 11, 45)


# ── fonts (Pillow >=10.1 gives a bundled sizeable default — no system dep) ────

def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        try:
            return ImageFont.load_default()
        except Exception:
            return None


# ── image helpers ────────────────────────────────────────────────────────────

def _decode(b64: str):
    if not PIL_AVAILABLE:
        return None
    try:
        return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
    except Exception:
        return None


def _encode(img) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


_ASCII_MAP = {
    "—": "-", "–": "-", "‒": "-", "−": "-",
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "•": "*", "…": "...", " ": " ",
}

def _safe(s: str) -> str:
    """Header font only covers Latin text — map smart punctuation to ASCII and
    drop emoji / non-Latin so nothing renders as a 'tofu' box."""
    s = "".join(_ASCII_MAP.get(ch, ch) for ch in (s or ""))
    return "".join(ch for ch in s if 32 <= ord(ch) <= 255).strip()

def _short(s: str, n: int) -> str:
    s = _safe(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "..."


# ── DOM helpers ──────────────────────────────────────────────────────────────

def _bbox(el: dict) -> dict:
    return (el.get("states", {}).get("default", {}).get("bbox", {})) or {}

def _rect(el: dict):
    if el.get("visible") is False:          # hidden / inactive carousel slide
        return None
    b = _bbox(el)
    y, w, h = b.get("y", 0), b.get("width", 0), b.get("height", 0)
    if y > 0 and w > 0 and h > 0:
        return {"x": b.get("x", 0), "y": y, "width": w, "height": h}
    return None

def _text(el: dict) -> str:
    return (el.get("text") or "").lower()

def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip().lower()


BOOKING_RE = re.compile(r"book|schedul|appoint|reserv|consult|get\s*start|sign\s*up|free\s*trial|contact|call\s*now|get\s*quote|request|today|appointment", re.I)
REVIEW_RE  = re.compile(r"review|testimonial|rating|stars?|\d\.\d\s*/\s*5|verified|what our|clients? say|patients? say", re.I)
TRUST_RE   = re.compile(r"certif|accredit|award|insur|licens|bbb|trustpilot|guarantee|member of|years? (of )?experience|before\s*&?\s*after", re.I)
PHONE_RE   = re.compile(r"\+?\d[\d\s\-().]{6,}\d")


def _category(iid: str) -> str:
    if iid in ("heading_hierarchy", "headings", "h1_identity", "h1_missing", "h1",
               "hero_value_proposition", "offer_clarity", "page_meta"):
        return "MESSAGE CLARITY"
    if iid in ("cta_label_quality", "cta_labels", "conversion_form", "forms",
               "form_missing", "cta_above_fold", "cta_hierarchy", "phone_cta",
               "hero_primary_cta_missing", "hero_action_clarity", "mobile_tap_targets"):
        return "CTA CLARITY"
    if iid in ("trust_signals", "social_proof", "social_proof_near_cta",
               "lazy_load_images", "images"):
        return "TRUST CLARITY"
    if iid in ("nav_overload", "page_structure", "duplicate_ids"):
        return "NAVIGATION FRICTION"
    if iid in ("og_social_meta", "schema_incomplete"):
        return "SEO CLARITY"
    return "UX CLARITY"


def _quoted(issue: dict) -> list[str]:
    txt = " ".join((issue.get("findings") or []) + (issue.get("evidence") or []))
    return [_norm(q) for q in re.findall(r"[\"']([^\"']{3,70})[\"']", txt)]


# ── geometry / blank guards ──────────────────────────────────────────────────

def _valid_geom(r: dict, page_h: float) -> bool:
    x, y, w, h = r["x"], r["y"], r["width"], r["height"]
    if w < 8 or h < 8:                       return False
    if y <= 0 or y >= page_h - 4:            return False
    if x < -30 or x > LAYOUT_WIDTH + 30:     return False
    if x + w < 10:                           return False
    return True

def _is_blank(img, r: dict, scale: float) -> bool:
    try:
        x0 = max(0, int(r["x"] * scale));                 y0 = max(0, int(r["y"] * scale))
        x1 = min(img.width, int((r["x"] + r["width"]) * scale))
        y1 = min(img.height, int((r["y"] + r["height"]) * scale))
        if x1 - x0 < 6 or y1 - y0 < 6:
            return True
        lo, hi = img.crop((x0, y0, x1, y1)).convert("L").getextrema()
        return (hi - lo) < 8
    except Exception:
        return False


# ── per-issue location ───────────────────────────────────────────────────────

def _locate(issue: dict, dom: list[dict]):
    """Return (targets, region, category, allow_frame).
    targets = list of (rect, element) for the specific offending element(s)."""
    iid = (issue.get("id") or "").lower()
    cat = _category(iid)
    H   = ("h1", "h2", "h3", "h4", "h5", "h6")

    def vis(pred, lim=8):
        out = []
        for el in dom:
            r = _rect(el)
            if r and pred(el):
                out.append((r, el))
            if len(out) >= lim:
                break
        return out

    # affected_elements that already carry coordinates
    coord = []
    for e in issue.get("affected_elements") or []:
        y = e.get("y", 0); w = e.get("w", e.get("width", 0)); h = e.get("h", e.get("height", 0))
        if y and (w or h):
            coord.append(({"x": e.get("x", 0), "y": y, "width": max(w, 40), "height": max(h, 24)}, e))
    if coord:
        return coord[:6], None, cat, False

    if iid in ("heading_hierarchy", "headings"):
        quoted = _quoted(issue)
        t = []
        for el in dom:
            if el.get("tag") in H:
                r = _rect(el)
                if not r:
                    continue
                nt = _norm(el.get("text", ""))
                if not quoted or any(nt and (nt in q or q in nt) for q in quoted):
                    t.append((r, el))
            if len(t) >= 6:
                break
        return t, None, cat, False
    if iid in ("h1_identity", "h1_missing", "h1"):
        return vis(lambda e: e.get("tag") == "h1", 1), (0, 700), cat, False
    if iid in ("cta_label_quality", "cta_labels"):
        r = vis(lambda e: e.get("tag") in ("a", "button") and (e.get("text") or "") == (e.get("text") or "").upper() and len((e.get("text") or "")) > 2)
        return (r or vis(lambda e: e.get("tag") in ("a", "button"))), None, cat, False
    if iid in ("conversion_form", "forms", "form_missing"):
        return (vis(lambda e: e.get("tag") == "form") or
                vis(lambda e: e.get("tag") in ("a", "button") and BOOKING_RE.search(_text(e)))), None, cat, False
    if iid in ("phone_cta", "phone"):
        return vis(lambda e: bool(PHONE_RE.search(_text(e)))), None, cat, False
    if iid in ("social_proof",):
        return vis(lambda e: bool(REVIEW_RE.search(_text(e)))), (0, 1200), cat, True
    if iid in ("trust_signals",):
        return vis(lambda e: bool(TRUST_RE.search(_text(e)))), None, cat, False
    if iid in ("lazy_load_images", "images"):
        return vis(lambda e: e.get("tag") == "img", 5), None, cat, False
    if iid in ("mobile_tap_targets",):
        return vis(lambda e: e.get("tag") in ("a", "button") and BOOKING_RE.search(_text(e))), None, cat, False
    if iid in ("duplicate_ids",):
        dup = {str(a.get("id")) for a in issue.get("affected_elements") or [] if a.get("id")}
        return vis(lambda e: str(e.get("id")) in dup), None, cat, False
    if iid in ("cta_above_fold",):
        return vis(lambda e: e.get("tag") in ("a", "button") and BOOKING_RE.search(_text(e)) and _bbox(e).get("y", 9999) <= 900), (0, 800), cat, True

    HERO = {"hero_carousel", "hero_primary_cta_missing", "hero_value_proposition",
            "hero_action_clarity", "offer_clarity", "cta_hierarchy"}
    if iid in HERO:
        return [], (0, 900), cat, True
    if iid in ("social_proof_near_cta",):
        return [], (0, 1200), cat, True
    if iid in ("nav_overload", "page_structure"):
        return vis(lambda e: e.get("tag") in ("header", "nav")), (0, 240), cat, True

    return [], None, cat, False


# ── rendering ────────────────────────────────────────────────────────────────

def _compose(crop, title, cat, conf, context) -> str:
    W = crop.width
    canvas = Image.new("RGB", (W, HEADER_H + crop.height), (255, 255, 255))
    canvas.paste(crop.convert("RGB"), (0, HEADER_H))
    d = ImageDraw.Draw(canvas)
    f1, f2 = _font(20), _font(14)
    if f1:
        d.text((16, 12), f"ISSUE: {_short(title, 56)}  ({cat})", fill=(17, 24, 39), font=f1)
    if f2:
        d.text((16, 46), f"Evidence Strategy: SECTION      |      System Match Confidence: {conf:.2f}",
               fill=(100, 116, 139), font=f2)
        d.text((16, 68), f'Context Target String: "{_short(context, 74)}"',
               fill=(100, 116, 139), font=f2)
    d.line([(0, HEADER_H - 1), (W, HEADER_H - 1)], fill=(226, 232, 240), width=1)
    return _encode(canvas)


def _render(img, rects, region, scale, title, cat, conf, context, frame: bool):
    full_w, full_h = img.size
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

    crop = img.crop((0, crop_top, full_w, crop_bottom)).convert("RGB")
    draw = ImageDraw.Draw(crop, "RGBA")

    if frame:
        draw.rectangle([4, 4, crop.width - 5, crop.height - 5], outline=ORANGE, width=6)
    else:
        for r in rects:
            x = int(r["x"] * scale)
            y = int(r["y"] * scale) - crop_top
            w = int(r["width"] * scale)
            h = int(r["height"] * scale)
            if w < 4 or h < 4:
                continue
            draw.rectangle([x - 5, y - 5, x + w + 5, y + h + 5],
                           fill=ORANGE_FILL, outline=ORANGE, width=4)

    if crop.width > OUT_MAX_W:
        ratio = OUT_MAX_W / crop.width
        crop = crop.resize((OUT_MAX_W, int(crop.height * ratio)))

    return _compose(crop, title, cat, conf, context)


def attach_crops(issues: list[dict], screenshot_b64, dom_elements=None) -> None:
    if not screenshot_b64 or not PIL_AVAILABLE:
        return
    img = _decode(screenshot_b64)
    if img is None:
        return
    dom    = dom_elements or []
    scale  = img.width / LAYOUT_WIDTH
    page_h = img.height / scale

    made = 0
    for issue in issues:
        if made >= MAX_CROPS:
            break
        try:
            targets, region, cat, allow_frame = _locate(issue, dom)
            title = issue.get("title") or issue.get("id") or "Issue"

            valid = [(r, el) for (r, el) in targets
                     if _valid_geom(r, page_h) and not _is_blank(img, r, scale)]

            if valid:
                rects   = [r for r, _ in valid]
                context = _short((valid[0][1].get("text") or "").strip(), 74) or "Matched element"
                crop = _render(img, rects, None, scale, title, cat, 0.75, context, frame=False)
                highlighted = True
            elif allow_frame and region:
                crop = _render(img, [], region, scale, title, cat, 0.30,
                               "Contextual Layout Framing Viewport", frame=True)
                highlighted = False
            else:
                continue  # specific element not visible → skip, no blank box
        except Exception:
            crop = None
            highlighted = False

        if crop:
            issue["screenshot_crop"]  = crop
            issue["crop_highlighted"] = highlighted
            made += 1
