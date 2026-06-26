#!/usr/bin/env python3
"""
Remote MCP Server + REST Scrape API
POST /scrape  — Hunter.io decision maker check -> full scrape + CRO audit
POST /cro     — Run CRO audit on already-scraped HTML/DOM
POST /mcp     — MCP Streamable HTTP for Claude.ai web
"""

import os
import sys
import json
import base64
import logging
import asyncio
import secrets
import urllib.request
from urllib.parse import urlparse, urlencode

from bs4 import BeautifulSoup
from scrapingbee import ScrapingBeeClient
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.middleware.cors import CORSMiddleware
import uvicorn

SCRAPINGBEE_API_KEY = os.environ.get("SCRAPINGBEE_API_KEY", "")
HUNTER_API_KEY      = os.environ.get("HUNTER_API_KEY", "")
PORT     = int(os.environ.get("PORT", 8000))
BASE_URL = os.environ.get("BASE_URL", "https://gtm-production-8ae5.up.railway.app")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# cro_bots may live alongside this file (mcp-web-scraper/cro_bots/)
# or one level up (repo root cro_bots/). Try both.
THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(THIS_DIR)
for _p in [THIS_DIR, REPO_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from cro_bots.cro_audit import run_audit
    from cro_wolf import run_wolf
    CRO_AVAILABLE = True
    log.info("CRO modules loaded OK (repo_root=%s)", REPO_ROOT)
except ImportError as e:
    log.warning("CRO modules not available: %s", e)
    CRO_AVAILABLE = False

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "web-scraper", "version": "2.2.0"}

TOOLS = [{
    "name": "scrape_website",
    "description": "Checks Hunter.io for a decision maker, scrapes the site, and runs a 10-bot CRO audit.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "industry": {"type": "string", "description": "dental|medical|ecommerce|saas|booking|restaurant|local_business|portfolio (default: all)"},
        },
        "required": ["url"],
    },
}]

DM_TITLES = [
    "ceo","chief executive","founder","co-founder","president","owner",
    "cto","cfo","coo","cmo","cpo","chief",
    "vp ","vice president","svp","evp",
    "director","head of","managing director","general manager",
    "partner","principal","managing partner",
]


def extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "").split(":")[0]
    except Exception:
        return ""


def hunter_lookup(domain: str, api_key: str) -> dict:
    if not api_key:
        return {"found": False, "error": "No Hunter API key"}
    try:
        qs  = urlencode({"domain": domain, "api_key": api_key, "limit": 20})
        req = urllib.request.urlopen(f"https://api.hunter.io/v2/domain-search?{qs}", timeout=15)
        data = json.loads(req.read())
    except Exception as exc:
        log.warning("Hunter error %s: %s", domain, exc)
        return {"found": False, "error": str(exc)}

    emails = data.get("data", {}).get("emails", [])
    if not emails:
        return {"found": False, "error": "No emails found"}

    def dm_score(e):
        score = 0
        title     = (e.get("position")  or "").lower()
        seniority = (e.get("seniority") or "").lower()
        if seniority == "executive": score += 100
        elif seniority == "senior":  score += 50
        for i, kw in enumerate(DM_TITLES):
            if kw in title:
                score += (len(DM_TITLES) - i) * 10
                break
        score += int(e.get("confidence", 0))
        return score

    best  = max(emails, key=dm_score)
    score = dm_score(best)
    if score == 0:
        return {"found": False, "error": "No decision-maker title found"}
    return {
        "found":      True,
        "first_name": best.get("first_name")    or "",
        "last_name":  best.get("last_name")     or "",
        "email":      best.get("value")         or "",
        "phone":      best.get("phone_number")  or "",
        "title":      best.get("position")      or "",
        "confidence": best.get("confidence",    0),
    }


# ---------------------------------------------------------------------------
# Scraping helpers
# ---------------------------------------------------------------------------

TAGS = ['a','button','h1','h2','h3','h4','h5','h6',
         'img','input','form','label','section','header','footer']

COORDINATE_JS = (
    "const el=Array.from(document.querySelectorAll("
    "'a,button,h1,h2,h3,h4,h5,h6,img,input,form,label,section,header,footer'))"
    ".map(e=>{const r=e.getBoundingClientRect();"
    "return{tag:e.tagName.toLowerCase(),"
    "x:r.left+window.scrollX,y:r.top+window.scrollY,"
    "width:r.width,height:r.height};});"
    "const c=document.createElement('div');"
    "c.id='scrapingbee-live-dom-matrices';c.style.display='none';"
    "c.innerText=JSON.stringify(el);document.body.appendChild(c);"
)


def safe_slug(url: str) -> str:
    name = urlparse(url).netloc.replace("www.", "")
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def build_dom_states(html: str, url: str, live: list) -> dict:
    soup     = BeautifulSoup(html, "html.parser")
    elements = []
    for idx, el in enumerate(soup.find_all(TAGS)):
        tag  = el.name
        text = (el.get_text(strip=True) or "")[:150]
        x, y, w, h = 40, 120 + idx * 60, 280, 45
        if idx < len(live) and live[idx].get("tag") == tag:
            lv = live[idx]
            x, y = lv.get("x", x), lv.get("y", y)
            w, h = lv.get("width", w), lv.get("height", h)
        elements.append({
            "tag": tag, "text": text,
            "id":         el.get("id"),
            "class":      el.get("class"),
            "role":       el.get("role"),
            "aria_label": el.get("aria-label"),
            "states": {"default": {
                "display": "block", "visibility": "visible",
                "bbox": {"x": int(x), "y": int(y),
                          "width": int(w), "height": int(h)},
            }},
        })
    return {"meta": {"engine": "ScrapingBee", "url": url, "status": "success"},
            "elements": elements}


def scrape_sync(url: str) -> dict:
    if not SCRAPINGBEE_API_KEY:
        return {"error": "SCRAPINGBEE_API_KEY not configured"}
    client = ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)
    result = {"error": None, "html": None, "dom_states": None,
              "dom_summary": None, "screenshot_b64": None,
              "slug": safe_slug(url)}
    try:
        resp = client.get(url, params={
            "render_js":    "true",
            "wait":         "8000",
            "wait_browser": "networkidle2",
            "window_width": "1440",
            "window_height":"900",
            "block_ads":    "true",
            "js_scenario": {"instructions": [{"evaluate": COORDINATE_JS}]},
        })
        if resp.status_code != 200:
            result["error"] = f"ScrapingBee HTTP {resp.status_code}"
            return result
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        container = soup.find(id="scrapingbee-live-dom-matrices")
        live = []
        if container and container.text:
            try:
                live = json.loads(container.text)
                container.decompose()
                html = str(soup)
            except Exception:
                pass
        result["html"] = html
    except Exception as exc:
        result["error"] = f"Scrape error: {exc}"
        return result

    try:
        ss = client.get(url, params={
            "render_js":          "true",
            "wait":               "8000",
            "wait_browser":       "networkidle2",
            "screenshot":         "true",
            "screenshot_full_page": "true",
            "window_width":       "1440",
            "block_ads":          "true",
        })
        if ss.status_code == 200:
            result["screenshot_b64"] = base64.b64encode(ss.content).decode()
    except Exception as exc:
        log.warning("Screenshot error: %s", exc)

    dom = build_dom_states(html, url, live)
    result["dom_states"]  = dom
    result["dom_summary"] = {
        "total_elements": len(dom["elements"]),
        "sample":         dom["elements"][:5],
    }
    return result


def _run_cro(html: str, dom_elements: list, industry: str, url: str) -> dict:
    """Synchronous CRO pipeline: 10 bots + wolf post-processor."""
    try:
        report = run_audit(html, dom_elements, industry=industry, url=url)
        return run_wolf(report, html, dom_elements, industry=industry)
    except Exception as exc:
        log.warning("CRO error for %s: %s", url, exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

async def handle_scrape_api(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    url = body.get("url", "").strip()
    if not url.startswith("http"):
        return JSONResponse({"error": "url must start with http"}, status_code=400)

    industry    = (body.get("industry", "") or "all").strip()
    hunter_key  = (body.get("hunter_api_key", "") or "").strip() or HUNTER_API_KEY
    skip_hunter = body.get("skip_hunter", False)

    hunter_data = None
    if not skip_hunter and hunter_key:
        log.info("Hunter lookup: %s", extract_domain(url))
        hunter_data = hunter_lookup(extract_domain(url), hunter_key)
        if not hunter_data.get("found"):
            return JSONResponse({"no_decision_maker": True,
                                 "hunter_data": hunter_data, "url": url})

    log.info("Scraping: %s", url)
    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, scrape_sync, url)
    result["hunter_data"]      = hunter_data
    result["no_decision_maker"] = False

    if not result.get("error") and result.get("html") and CRO_AVAILABLE:
        dom_els = result.get("dom_states", {}).get("elements", [])
        result["cro_audit"] = await loop.run_in_executor(
            None, _run_cro, result["html"], dom_els, industry, url
        )
    else:
        result["cro_audit"] = None

    return JSONResponse(result)


async def handle_cro_api(request: Request):
    """Run CRO audit on caller-supplied HTML + DOM elements."""
    if not CRO_AVAILABLE:
        return JSONResponse({"error": "CRO module not available on this server"}, status_code=503)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    html         = body.get("html", "")
    dom_elements = body.get("dom_elements", [])
    url          = body.get("url", "")
    industry     = (body.get("industry", "") or "all").strip()

    if not html:
        return JSONResponse({"error": "html is required"}, status_code=400)

    log.info("CRO audit request: %s (%s)", url, industry)
    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run_cro, html, dom_elements, industry, url)
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# MCP Streamable HTTP
# ---------------------------------------------------------------------------

async def dispatch(msg: dict):
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params", {})
    def ok(r):  return {"jsonrpc": "2.0", "id": msg_id, "result": r}
    def err(c, m): return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": c, "message": m}}

    if method == "initialize":
        return ok({"protocolVersion": MCP_PROTOCOL_VERSION,
                   "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO})
    if method == "ping":        return ok({})
    if method == "tools/list":  return ok({"tools": TOOLS})
    if method == "tools/call":
        name     = params.get("name")
        args     = params.get("arguments", {})
        industry = (args.get("industry") or "all").strip()
        if name != "scrape_website":
            return err(-32601, f"Unknown tool: {name}")
        url = args.get("url", "").strip()
        if not url.startswith("http"):
            return ok({"content": [{"type": "text", "text": "Error: URL must start with http"}],
                        "isError": True})
        loop = asyncio.get_event_loop()
        if HUNTER_API_KEY:
            hd = hunter_lookup(extract_domain(url), HUNTER_API_KEY)
            if not hd.get("found"):
                return ok({"content": [{"type": "text",
                    "text": f"No decision maker found for {extract_domain(url)}. Skipping."}],
                    "isError": False})
        result = await loop.run_in_executor(None, scrape_sync, url)
        if result.get("error"):
            return ok({"content": [{"type": "text",
                "text": f"Scrape failed: {result['error']}"}], "isError": True})
        lines = [f"Scrape complete: {url}", "",
                  f"DOM elements: {result['dom_summary']['total_elements']}"]
        if CRO_AVAILABLE:
            dom_els = result.get("dom_states", {}).get("elements", [])
            cro = await loop.run_in_executor(None, _run_cro, result["html"], dom_els, industry, url)
            if cro and not cro.get("error"):
                s = cro.get("summary", {})
                lines += ["", f"CRO: {s.get('confirmed_high',0)} HIGH  "
                              f"{s.get('confirmed_medium',0)} MEDIUM  "
                              f"{s.get('gaps_detected',0)} gaps"]
                for iss in (cro.get("issues") or [])[:5]:
                    if iss.get("decision") != "suppressed":
                        lines.append(f"  [{iss.get('severity','?').upper()}] {iss.get('title','')[:80]}")
        content = [{"type": "text", "text": "\n".join(lines)}]
        if result.get("screenshot_b64"):
            content.append({"type": "image",
                "data": result["screenshot_b64"], "mimeType": "image/png"})
        return ok({"content": content, "isError": False})
    if msg_id is None: return None
    return err(-32601, f"Method not found: {method}")


async def handle_mcp(request: Request):
    if request.method == "GET":
        async def es():
            while True:
                yield "event: ping\ndata: {}\n\n"
                await asyncio.sleep(15)
        return StreamingResponse(es(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None,
            "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
    if isinstance(body, list):
        responses = [r for r in [await dispatch(m) for m in body] if r is not None]
        return JSONResponse(responses) if responses else Response(status_code=202)
    result = await dispatch(body)
    return Response(status_code=202) if result is None else JSONResponse(result)


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

async def oauth_protected_resource(request: Request):
    return JSONResponse({"resource": BASE_URL, "authorization_servers": [BASE_URL],
                          "bearer_methods_supported": ["header"]})

async def oauth_authorization_server(request: Request):
    return JSONResponse({
        "issuer": BASE_URL,
        "authorization_endpoint": f"{BASE_URL}/oauth/authorize",
        "token_endpoint":         f"{BASE_URL}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported":    ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
    })

async def oauth_authorize(request: Request):
    p    = dict(request.query_params)
    code = secrets.token_urlsafe(32)
    qs   = urlencode({k: v for k, v in [("code", code), ("state", p.get("state", ""))] if v})
    dest = f"{p['redirect_uri']}?{qs}" if p.get("redirect_uri") else "/"
    return RedirectResponse(url=dest, status_code=302)

async def oauth_token(request: Request):
    return JSONResponse({"access_token": secrets.token_urlsafe(32),
                          "token_type": "bearer", "expires_in": 86400, "scope": ""})

async def healthcheck(request: Request):
    return JSONResponse({"status": "ok",
                          "server": f"web-scraper MCP + REST v2.2",
                          "cro_available": CRO_AVAILABLE})


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

web = Starlette(routes=[
    Route("/",  healthcheck),
    Route("/.well-known/oauth-protected-resource",  oauth_protected_resource),
    Route("/.well-known/oauth-authorization-server", oauth_authorization_server),
    Route("/oauth/authorize", oauth_authorize),
    Route("/oauth/token",     oauth_token,        methods=["GET", "POST"]),
    Route("/mcp",    handle_mcp,        methods=["GET", "POST", "OPTIONS"]),
    Route("/scrape", handle_scrape_api, methods=["POST", "OPTIONS"]),
    Route("/cro",    handle_cro_api,    methods=["POST", "OPTIONS"]),
])
web.add_middleware(CORSMiddleware, allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"], allow_credentials=False)

if __name__ == "__main__":
    uvicorn.run(web, host="0.0.0.0", port=PORT)
