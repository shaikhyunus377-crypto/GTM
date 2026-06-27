"""
screenshot_utils.py — Crop and annotate page screenshots per CRO issue.

Requires Pillow. Gracefully no-ops if not installed.
"""
from __future__ import annotations
import base64
import io

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# How many px above/below the issue region to include
PAD_TOP    = 60
PAD_BOTTOM = 120
MIN_HEIGHT = 200   # never return a sliver crop
MAX_HEIGHT = 900   # cap crop height for readability


def _decode(screenshot_b64: str) -> "Image.Image | None":
    if not PIL_AVAILABLE:
        return None
    try:
        data = base64.b64decode(screenshot_b64)
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def _encode(img: "Image.Image") -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def _highlight_rects(draw: "ImageDraw.Draw", rects: list[dict], scale: float):
    """Draw red semi-transparent highlight boxes around each element rect."""
    for r in rects:
        x  = int(r.get("x", r.get("left", 0)) * scale)
        y  = int(r.get("y", r.get("top",  0)) * scale)
        w  = int(r.get("width",  r.get("w", 0)) * scale)
        h  = int(r.get("height", r.get("h", 0)) * scale)
        if w < 4 or h < 4:
            continue
        # Semi-transparent fill
        draw.rectangle([x, y, x+w, y+h], fill=(255, 0, 0, 40), outline=(220, 30, 30, 220), width=2)


def crop_issue_screenshot(
    screenshot_b64: str,
    y_top:    int,
    y_bottom: int,
    highlight_rects: list[dict] | None = None,
    img_width: int = 1440,
) -> str | None:
    """
    Crop the full-page screenshot to [y_top-PAD_TOP .. y_bottom+PAD_BOTTOM],
    draw red highlight boxes for each element, return new base64 PNG.

    Returns None if PIL is not available or on any error.
    """
    if not PIL_AVAILABLE or not screenshot_b64:
        return None

    img = _decode(screenshot_b64)
    if img is None:
        return None

    full_w, full_h = img.size
    # Scale factor: screenshot may be captured at a different width than the DOM coords
    scale = full_w / img_width

    crop_top    = max(0, int(y_top    * scale) - PAD_TOP)
    crop_bottom = min(full_h, int(y_bottom * scale) + PAD_BOTTOM)
    crop_bottom = max(crop_bottom, crop_top + MIN_HEIGHT)

    # Cap height
    if crop_bottom - crop_top > MAX_HEIGHT:
        crop_bottom = crop_top + MAX_HEIGHT

    cropped = img.crop((0, crop_top, full_w, crop_bottom))

    if highlight_rects:
        draw = ImageDraw.Draw(cropped, "RGBA")
        # Adjust rect y-coords relative to the crop
        adjusted = [{**r, "y": r.get("y", r.get("top", 0)) - int(crop_top / scale)} for r in highlight_rects]
        _highlight_rects(draw, adjusted, scale)

    return _encode(cropped)


# ── Per-issue crop helper ──────────────────────────────────────────────────────

def _affected_bbox(issue: dict) -> tuple[int, int, list[dict]]:
    """Return (y_top, y_bottom, rects) for an issue's affected elements."""
    els = issue.get("affected_elements") or []
    ys  = []
    rects = []
    for e in els:
        y = e.get("y", 0)
        h = e.get("h", e.get("height", 30))
        w = e.get("w", e.get("width", 0))
        x = e.get("x", 0)
        if y > 0:
            ys.append(y)
            rects.append({"x": x, "y": y, "width": max(w, 4), "height": max(h, 4)})
    if ys:
        return min(ys), max(ys) + 60, rects
    return 0, 0, []


# Regions for AI hero findings (no affected_elements, but known to be hero section)
_AI_HERO_REGION = {
    "hero_primary_cta_missing":  (0, 800),
    "hero_value_proposition":    (0, 700),
    "hero_action_clarity":       (0, 900),
    "offer_clarity":             (0, 900),
    "social_proof_near_cta":     (0, 1200),
}

# Static regions for deterministic findings without elements
_STATIC_REGION = {
    "cta_above_fold":  (0, 800),
    "hero_carousel":   (0, 900),
    "cta_hierarchy":   (0, 900),
    "nav_overload":    (0, 200),
}


def attach_crops(issues: list[dict], screenshot_b64: str | None) -> None:
    """
    Mutate each issue dict in-place: add 'screenshot_crop' (base64 PNG or None).
    Safe to call even if PIL is missing or screenshot_b64 is None.
    """
    if not screenshot_b64 or not PIL_AVAILABLE:
        return

    for issue in issues:
        issue_id = issue.get("id", "")
        crop = None

        # AI hero findings — use fixed hero region
        if issue_id in _AI_HERO_REGION:
            y_top, y_bottom = _AI_HERO_REGION[issue_id]
            crop = crop_issue_screenshot(screenshot_b64, y_top, y_bottom)

        # Static region findings
        elif issue_id in _STATIC_REGION:
            y_top, y_bottom = _STATIC_REGION[issue_id]
            crop = crop_issue_screenshot(screenshot_b64, y_top, y_bottom)

        # Findings with affected_elements
        elif issue.get("affected_elements"):
            y_top, y_bottom, rects = _affected_bbox(issue)
            if y_top > 0:
                crop = crop_issue_screenshot(screenshot_b64, y_top, y_bottom, highlight_rects=rects)

        if crop:
            issue["screenshot_crop"] = crop
