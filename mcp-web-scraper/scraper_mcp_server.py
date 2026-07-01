#!/usr/bin/env python3
"""
GTM Scraper API — REST backend for the CRO audit SaaS.
Endpoints:
  GET  /            — healthcheck
  POST /scrape      — scrape a URL (ScrapingBee) + optional CRO audit
  POST /cro         — run CRO audit on caller-supplied HTML + DOM
  POST /hunter      — Hunter.io decision-maker lookup

Deploy to Railway. Required env vars:
  SCRAPINGBEE_API_KEY
  HUNTER_API_KEY      (optional)
"""

from __future__ import annotations

import os
import sys
import json
import re
import base64
import logging
import asyncio
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
import uvicorn

# ── CRO modules ─────────────────────────────────────────────────────────────────────────────
THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

try:
    from cro_bots.cro_audit import run_audit
    from cro_wolf import run_wolf
    CRO_AVAILABLE = True
except ImportError as e:
    CRO_AVAILABLE = False
    _cro_import_err = str(e)

# ── Technology intelligence (runs after the CRO audit) ───────────────────────
try:
    from tech_intelligence import run_tech
    TECH_AVAILABLE = True
except ImportError as e:
    TECH_AVAILABLE = False
    _tech_import_err = str(e)

    def run_tech(html):  # type: ignore
        return {"error": "tech_intelligence module not available", "summary": {}}

# ── Personalized email writer (final bot in the pipeline) ────────────────────
try:
    from email_writer import run_email
    EMAIL_AVAILABLE = True
except ImportError as e:
    EMAIL_AVAILABLE = False
    _email_import_err = str(e)

    def run_email(lead, openai_key=""):  # type: ignore
        return {"error": "email_writer module not available", "subject": "", "body": ""}

# ── Config ────────────────────────────────────────────────────────────────────────────
SCRAPINGBEE_API_KEY = os.environ.get("SCRAPINGBEE_API_KEY", "")
HUNTER_API_KEY      = os.environ.get("HUNTER_API_KEY", "")
OPENAI_API_KEY      = os.environ.get("OPENAI_API_KEY", "")
PORT                = int(os.environ.get("PORT", 8000))
SERVER_VERSION      = "2.6.1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

if CRO_AVAILABLE:
    log.info("CRO modules loaded OK")
else:
    log.warning("CRO modules not available: %s", _cro_import_err if not CRO_AVAILABLE else "")

# ── DOM / Scrape helpers ────────────────────────────────────────────────────────────────────
TAGS = ['a','button','h1','h2','h3','h4','h5','h6','img','input','form','label','section','header','footer']

COORDINATE_JS = (
    # visible(): walk ancestors — an element on an inactive carousel slide is
    # hidden via display/visibility/opacity/aria-hidden even though its
    # getBoundingClientRect still returns a plausible box. We record real
    # visibility so highlights never land on off-slide / hidden elements.
    "const visible = (el) => {"
    "  let p = el;"
    "  while (p && p.nodeType === 1) {"
    "    const s = getComputedStyle(p);"
    "    if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity || '1') === 0) return false;"
    "    if (p.getAttribute && p.getAttribute('aria-hidden') === 'true') return false;"
    "    p = p.parentElement;"
    "  }"
    "  return true;"
    "};"
    "const elements = Array.from(document.querySelectorAll("
    "  'a, button, h1, h2, h3, h4, h5, h6, img, input, form, label, section, header, footer'"
    ")).map(el => {"
    "  const rect = el.getBoundingClientRect();"
    "  return { tag: el.tagName.toLowerCase(),"
    "           text: (el.innerText || el.textContent || '').replace(/\\s+/g,' ').trim().slice(0,60),"
    "           vis: visible(el),"
    "           x: rect.left + window.scrollX,"
    "           y: rect.top + window.scrollY, width: rect.width, height: rect.height };"
    "});"
    "const c = document.createElement('div');"
    "c.id = 'scrapingbee-live-dom-matrices';"
    "c.style.display = 'none';"
    "c.innerText = JSON.stringify(elements);"
    "document.body.appendChild(c);"
)


def safe_folder(url: str) -> str:
    parsed = urlparse(url)
    name   = parsed.netloc.replace("www.", "")
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def _norm_txt(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip().lower()[:60]


def build_dom_states(html: str, url: str, live_elements: list) -> dict:
    soup     = BeautifulSoup(html, "html.parser")
    elements = []

    # Index live (browser-measured) elements by tag, preserving order, each with
    # a "used" flag so we can consume matches. We match soup elements to their
    # real coordinates by (tag + text) first, then positionally within the tag —
    # far more reliable than the previous global-index alignment.
    live_by_tag: dict[str, list] = {}
    for le in (live_elements or []):
        live_by_tag.setdefault(le.get("tag"), []).append([le, False])

    def take(tag: str, text: str):
        pool = live_by_tag.get(tag)
        if not pool:
            return None
        nt = _norm_txt(text)
        if nt:
            for pair in pool:
                if not pair[1] and _norm_txt(pair[0].get("text", "")) == nt:
                    pair[1] = True
                    return pair[0]
        for pair in pool:            # positional fallback within same tag
            if not pair[1]:
                pair[1] = True
                return pair[0]
        return None

    for idx, el in enumerate(soup.find_all(TAGS)):
        tag  = el.name
        text = (el.get_text(strip=True) or "")[:150]
        x, y, w, h = 40, 120 + idx * 60, 280, 45
        visible = True
        live = take(tag, text)
        if live:
            x = live.get("x", x)
            y = live.get("y", y)
            w = live.get("width", w)
            h = live.get("height", h)
            visible = bool(live.get("vis", True))
        elements.append({
            "tag":       tag,
            "text":      text,
            "id":        el.get("id"),
            "class":     el.get("class"),
            "role":      el.get("role"),
            "aria_label": el.get("aria-label"),
            "visible":   visible,
            "states": {
                "default": {
                    "display":    "block",
                    "visibility": "visible",
                    "bbox":       {"x": int(x), "y": int(y), "width": int(w), "height": int(h)},
                }
            },
        })
    return {
        "meta":     {"engine": "ScrapingBee", "url": url, "status": "success"},
        "elements": elements,
    }


try:
    from cro_bots.screenshot_utils import attach_crops
    CROPS_AVAILABLE = True
except ImportError:
    CROPS_AVAILABLE = False

    def attach_crops(issues, screenshot_b64, dom_elements=None):  # type: ignore
        pass


def _run_cro(html: str, dom_elements: list, industry: str, url: str,
             screenshot_b64: str | None = None) -> dict:
    try:
        report = run_audit(html, dom_elements, industry=industry, url=url)
        wolf   = run_wolf(report, html, dom_elements, industry=industry)
        if screenshot_b64 and wolf.get("client_report"):
            attach_crops(wolf["client_report"], screenshot_b64, dom_elements)
        return wolf
    except Exception as exc:
        log.warning("CRO error for %s: %s", url, exc, exc_info=True)
        return {"error": str(exc)}


def scrape_sync(url: str, run_cro: bool = True, industry: str = "all") -> dict:
    if not SCRAPINGBEE_API_KEY:
        return {"error": "SCRAPINGBEE_API_KEY not set on server"}

    try:
        from scrapingbee import ScrapingBeeClient
    except ImportError:
        return {"error": "scrapingbee package not installed"}

    client = ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)
    result = {
        "url": url,
        "html": None,
        "dom_states": None,
        "screenshot_b64": None,
        "screenshot_error": None,
        "cro_audit": None,
        "tech_intelligence": None,
        "error": None,
    }

    # Step 1 — rendered HTML + coordinate injection
    log.info("Scraping HTML: %s", url)
    try:
        resp = client.get(url, params={
            "render_js":   "true",
            "wait":        "3500",
            "window_width":  "1440",
            "window_height": "2000",
            "js_scenario": {"instructions": [{"evaluate": COORDINATE_JS}]},
            "block_ads":   "true",
        })
        if resp.status_code != 200:
            result["error"] = f"ScrapingBee HTTP {resp.status_code}"
            return result

        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        container = soup.find(id="scrapingbee-live-dom-matrices")
        live_elements = []
        if container and container.text:
            try:
                live_elements = json.loads(container.text)
            except Exception:
                pass
            container.decompose()
            html = str(soup)

        result["html"] = html

    except Exception as exc:
        result["error"] = f"HTML fetch error: {exc}"
        return result

    # Step 2 — screenshot
    log.info("Capturing screenshot: %s", url)
    try:
        ss = client.get(url, params={
            "render_js":             "true",
            "wait":                  "2500",
            "screenshot":            "true",
            "screenshot_full_page":  "true",
            "window_width":          "1440",
            "block_ads":             "true",
        })
        if ss.status_code == 200:
            size_kb = len(ss.content) // 1024
            if len(ss.content) <= 1_500_000:
                result["screenshot_b64"] = base64.b64encode(ss.content).decode()
            else:
                result["screenshot_error"] = f"Too large ({size_kb}KB > 1500KB)"
                log.warning("Screenshot too large for %s: %dKB", url, size_kb)
        else:
            result["screenshot_error"] = f"ScrapingBee HTTP {ss.status_code}"
            log.warning("Screenshot HTTP error for %s: %d", url, ss.status_code)
    except Exception as exc:
        result["screenshot_error"] = str(exc)
        log.warning("Screenshot error for %s: %s", url, exc)

    # Step 3 — DOM states
    dom = build_dom_states(html, url, live_elements)
    result["dom_states"] = dom

    # Step 4 — CRO audit (pass screenshot for per-issue crops)
    if run_cro and CRO_AVAILABLE:
        log.info("Running CRO audit: %s", url)
        result["cro_audit"] = _run_cro(
            html, dom["elements"], industry, url,
            screenshot_b64=result.get("screenshot_b64"),
        )

    # Step 5 — Technology intelligence (tech stack, paid tools, ad pixels)
    if TECH_AVAILABLE:
        log.info("Running tech intelligence: %s", url)
        try:
            result["tech_intelligence"] = run_tech(html)
        except Exception as exc:
            log.warning("Tech intel error for %s: %s", url, exc)
            result["tech_intelligence"] = {"error": str(exc), "summary": {}}

    return result


# ── Request handlers ─────────────────────────────────────────────────────────────────────────

async def healthcheck(request: Request):
    return JSONResponse({
        "status":        "ok",
        "server":        f"GTM Scraper API v{SERVER_VERSION}",
        "cro_available": CRO_AVAILABLE,
        "tech_available": TECH_AVAILABLE,
        "email_available": EMAIL_AVAILABLE,
        "scrapingbee":   bool(SCRAPINGBEE_API_KEY),
        "hunter":        bool(HUNTER_API_KEY),
        "openai":        bool(OPENAI_API_KEY),
    })


async def handle_scrape(request: Request):
    if request.method == "OPTIONS":
        return JSONResponse({}, status_code=200)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    url = (body.get("url") or "").strip()
    if not url.startswith("http"):
        return JSONResponse({"error": "url must start with http:// or https://"}, status_code=400)

    industry = (body.get("industry") or "all").strip()
    run_cro  = body.get("run_cro", False)

    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, scrape_sync, url, run_cro, industry)
    return JSONResponse(result)


async def handle_cro(request: Request):
    if request.method == "OPTIONS":
        return JSONResponse({}, status_code=200)
    if not CRO_AVAILABLE:
        return JSONResponse({"error": "CRO module not available on this server"}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    html         = body.get("html", "")
    dom_elements = body.get("dom_elements", [])
    url          = body.get("url", "")
    industry     = (body.get("industry") or "all").strip()

    if not html:
        return JSONResponse({"error": "html is required"}, status_code=400)

    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run_cro, html, dom_elements, industry, url)
    return JSONResponse(result)


async def handle_tech(request: Request):
    """POST /tech — run technology intelligence on caller-supplied HTML."""
    if request.method == "OPTIONS":
        return JSONResponse({}, status_code=200)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    html = body.get("html", "")
    if not html:
        return JSONResponse({"error": "html is required"}, status_code=400)

    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_tech, html)
    return JSONResponse(result)


async def handle_email(request: Request):
    """POST /email — write a personalized subject + body for one prospect.
    Body: { lead:{...}, openai_key?:"" }  (openai_key optional; falls back to env)."""
    if request.method == "OPTIONS":
        return JSONResponse({}, status_code=200)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    lead       = body.get("lead") or body
    openai_key = (body.get("openai_key") or OPENAI_API_KEY or "").strip()
    if not isinstance(lead, dict) or not (lead.get("business_name") or lead.get("website")):
        return JSONResponse({"error": "lead with at least business_name or website is required"}, status_code=400)

    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_email, lead, openai_key)
    return JSONResponse(result)


async def handle_hunter(request: Request):
    if request.method == "OPTIONS":
        return JSONResponse({}, status_code=200)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    domain   = (body.get("domain") or "").strip()
    api_key  = (body.get("api_key") or HUNTER_API_KEY or "").strip()

    if not domain:
        return JSONResponse({"error": "domain is required"}, status_code=400)
    if not api_key:
        return JSONResponse({"error": "Hunter.io API key required (set HUNTER_API_KEY env var or pass api_key in body)"}, status_code=400)

    import urllib.request
    hunter_url = f"https://api.hunter.io/v2/domain-search?domain={domain}&api_key={api_key}&limit=20"
    try:
        with urllib.request.urlopen(hunter_url, timeout=20) as r:
            data = json.loads(r.read())
    except Exception as exc:
        return JSONResponse({"error": f"Hunter.io request failed: {exc}"}, status_code=502)

    hunter_data = data.get("data", {})
    emails      = hunter_data.get("emails", [])
    organization = hunter_data.get("organization", "") or ""
    company_website = f"https://{domain}"

    # Hunter seniority field values: junior, senior, executive, director, manager
    # "executive" = C-suite (CEO/CTO/CFO). "c_suite" is NOT a Hunter value.
    SENIORITY_SCORE = {
        "executive": 6,   # CEO, CTO, CFO, CMO
        "director":  5,
        "manager":   3,
        "senior":    2,
        "junior":    0,
    }
    TITLE_KEYWORDS = [
        "owner", "founder", "ceo", "cto", "cfo", "cmo", "coo",
        "president", "director", "vp", "vice president",
        "marketing", "growth", "sales", "business development",
        "partner", "principal",
    ]

    def score(e):
        s = SENIORITY_SCORE.get((e.get("seniority") or "").lower(), 0)
        t = (e.get("position") or "").lower()
        s += sum(2 for kw in TITLE_KEYWORDS if kw in t)
        return s

    ranked = sorted(emails, key=score, reverse=True)
    top    = ranked[:5]  # return top 5 so frontend can show all options

    return JSONResponse({
        "found":           bool(top),
        "domain":          domain,
        "company_name":    organization,
        "company_website": company_website,
        "total":           len(emails),
        "top_contacts": [
            {
                "email":      e.get("value"),
                "name":       f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                "first_name": e.get("first_name", ""),
                "last_name":  e.get("last_name", ""),
                "position":   e.get("position") or "",
                "seniority":  e.get("seniority") or "",
                "department": e.get("department") or "",
                "linkedin":   e.get("linkedin") or "",
                "phone":      e.get("phone_number") or "",
                "confidence": e.get("confidence", 0),
                "score":      score(e),
            }
            for e in top
        ],
    })


# ── App ───────────────────────────────────────────────────────────────────────────────

app = Starlette(routes=[
    Route("/",        healthcheck,    methods=["GET"]),
    Route("/scrape",  handle_scrape,  methods=["POST", "OPTIONS"]),
    Route("/cro",     handle_cro,     methods=["POST", "OPTIONS"]),
    Route("/tech",    handle_tech,    methods=["POST", "OPTIONS"]),
    Route("/email",   handle_email,   methods=["POST", "OPTIONS"]),
    Route("/hunter",  handle_hunter,  methods=["POST", "OPTIONS"]),
])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

web = app  # alias for nixpacks/uvicorn auto-detection

if __name__ == "__main__":
    log.info("Starting GTM Scraper API v%s on port %d", SERVER_VERSION, PORT)
    uvicorn.run("scraper_mcp_server:web", host="0.0.0.0", port=PORT, reload=False)
