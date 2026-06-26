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

import os
import sys
import json
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

# ── CRO modules ───────────────────────────────────────────────────────────────
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

# ── Config ────────────────────────────────────────────────────────────────────
SCRAPINGBEE_API_KEY = os.environ.get("SCRAPINGBEE_API_KEY", "")
HUNTER_API_KEY      = os.environ.get("HUNTER_API_KEY", "")
PORT                = int(os.environ.get("PORT", 8000))
SERVER_VERSION      = "2.2.0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

if CRO_AVAILABLE:
    log.info("CRO modules loaded OK")
else:
    log.warning("CRO modules not available: %s", _cro_import_err if not CRO_AVAILABLE else "")

# ── DOM / Scrape helpers ──────────────────────────────────────────────────────

TAGS = ['a','button','h1','h2','h3','h4','h5','h6','img','input','form','label','section','header','footer']

COORDINATE_JS = (
    "const elements = Array.from(document.querySelectorAll("
    "  'a, button, h1, h2, h3, h4, h5, h6, img, input, form, label, section, header, footer'"
    ")).map(el => {"
    "  const rect = el.getBoundingClientRect();"
    "  return { tag: el.tagName.toLowerCase(), x: rect.left + window.scrollX,"
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


def build_dom_states(html: str, url: str, live_elements: list) -> dict:
    soup     = BeautifulSoup(html, "html.parser")
    elements = []
    for idx, el in enumerate(soup.find_all(TAGS)):
        tag  = el.name
        text = (el.get_text(strip=True) or "")[:150]
        x, y, w, h = 40, 120 + idx * 60, 280, 45
        if idx < len(live_elements):
            live = live_elements[idx]
            if live.get("tag") == tag:
                x = live.get("x", x)
                y = live.get("y", y)
                w = live.get("width", w)
                h = live.get("height", h)
        elements.append({
            "tag":       tag,
            "text":      text,
            "id":        el.get("id"),
            "class":     el.get("class"),
            "role":      el.get("role"),
            "aria_label": el.get("aria-label"),
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


def _run_cro(html: str, dom_elements: list, industry: str, url: str) -> dict:
    try:
        report = run_audit(html, dom_elements, industry=industry, url=url)
        return run_wolf(report, html, dom_elements, industry=industry)
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
    result = {"url": url, "html": None, "dom_states": None, "screenshot_b64": None, "cro_audit": None, "error": None}

    # Step 1 — rendered HTML + coordinate injection
    log.info("Scraping HTML: %s", url)
    try:
        resp = client.get(url, params={
            "render_js":   "true",
            "wait":        "8000",
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
            "wait":                  "4500",
            "screenshot":            "true",
            "screenshot_full_page":  "true",
            "window_width":          "1440",
            "block_ads":             "true",
        })
        if ss.status_code == 200 and len(ss.content) <= 2_000_000:
            result["screenshot_b64"] = base64.b64encode(ss.content).decode()
    except Exception as exc:
        log.warning("Screenshot error: %s", exc)

    # Step 3 — DOM states
    dom = build_dom_states(html, url, live_elements)
    result["dom_states"] = dom

    # Step 4 — CRO audit
    if run_cro and CRO_AVAILABLE:
        log.info("Running CRO audit: %s", url)
        result["cro_audit"] = _run_cro(html, dom["elements"], industry, url)

    return result


# ── Request handlers ──────────────────────────────────────────────────────────

async def healthcheck(request: Request):
    return JSONResponse({
        "status":        "ok",
        "server":        f"GTM Scraper API v{SERVER_VERSION}",
        "cro_available": CRO_AVAILABLE,
        "scrapingbee":   bool(SCRAPINGBEE_API_KEY),
        "hunter":        bool(HUNTER_API_KEY),
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
    run_cro  = body.get("run_cro", True)

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
    hunter_url = f"https://api.hunter.io/v2/domain-search?domain={domain}&api_key={api_key}&limit=10"
    try:
        with urllib.request.urlopen(hunter_url, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as exc:
        return JSONResponse({"error": f"Hunter.io request failed: {exc}"}, status_code=502)

    emails = data.get("data", {}).get("emails", [])
    SENIORITY_SCORE = {"director": 5, "c_suite": 5, "vp": 4, "manager": 3, "senior": 2}
    TITLE_KEYWORDS  = ["owner","founder","ceo","president","director","vp","marketing","growth","sales"]

    def score(e):
        s = SENIORITY_SCORE.get((e.get("seniority") or "").lower(), 0)
        t = (e.get("position") or "").lower()
        s += sum(2 for kw in TITLE_KEYWORDS if kw in t)
        return s

    ranked  = sorted(emails, key=score, reverse=True)
    top     = ranked[:3]

    return JSONResponse({
        "found":      bool(top),
        "domain":     domain,
        "total":      len(emails),
        "top_contacts": [
            {
                "email":    e.get("value"),
                "name":     f"{e.get('first_name','')} {e.get('last_name','')}".strip(),
                "position": e.get("position"),
                "score":    score(e),
            }
            for e in top
        ],
    })


# ── App ───────────────────────────────────────────────────────────────────────

app = Starlette(routes=[
    Route("/",        healthcheck,    methods=["GET"]),
    Route("/scrape",  handle_scrape,  methods=["POST", "OPTIONS"]),
    Route("/cro",     handle_cro,     methods=["POST", "OPTIONS"]),
    Route("/hunter",  handle_hunter,  methods=["POST", "OPTIONS"]),
])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    log.info("Starting GTM Scraper API v%s on port %d", SERVER_VERSION, PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
