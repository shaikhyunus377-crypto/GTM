#!/usr/bin/env python3
"""
Remote MCP Server + REST Scrape API
POST /scrape  — Hunter.io decision maker check -> full scrape + CRO audit
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

# Add repo root to path so cro_bots is importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from cro_bots.cro_audit import run_audit
    from cro_wolf import run_wolf
    CRO_AVAILABLE = True
except ImportError as e:
    log.warning("CRO modules not available: %s", e)
    CRO_AVAILABLE = False

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "web-scraper", "version": "2.1.0"}

TOOLS = [{
    "name": "scrape_website",
    "description": "Checks Hunter.io for a decision maker, scrapes the site, and runs a 10-bot CRO audit. Returns rendered HTML, DOM states, screenshot, contact info, and CRO findings.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "industry": {"type": "string", "description": "Industry for CRO gap detection: dental, medical, ecommerce, saas, booking, restaurant, local_business, portfolio (default: all)"},
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
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        return domain.split(":")[0]
    except Exception:
        return ""


def hunter_lookup(domain: str, api_key: str) -> dict:
    if not api_key:
        return {"found": False, "error": "No Hunter API key provided"}
    try:
        qs = urlencode({"domain": domain, "api_key": api_key, "limit": 20})
        url = f"https://api.hunter.io/v2/domain-search?{qs}"
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        log.warning("Hunter API error for %s: %s", domain, exc)
        return {"found": False, "error": str(exc)}

    emails = data.get("data", {}).get("emails", [])
    if not emails:
        return {"found": False, "error": "No emails found on domain"}

    def dm_score(e):
        score = 0
        title = (e.get("position") or "").lower()
        seniority = (e.get("seniority") or "").lower()
        if seniority == "executive": score += 100
        elif seniority == "senior":  score += 50
        for i, kw in enumerate(DM_TITLES):
            if kw in title:
                score += (len(DM_TITLES) - i) * 10
                break
        score += int(e.get("confidence", 0))
        return score

    best = max(emails, key=dm_score)
    score = dm_score(best)

    if score == 0:
        return {"found": False, "error": "No decision maker found (no executive/director titles)"}

    return {
        "found": True,
        "first_name": best.get("first_name") or "",
        "last_name":  best.get("last_name")  or "",
        "email":      best.get("value")       or "",
        "phone":      best.get("phone_number") or "",
        "title":      best.get("position")    or "",
        "confidence": best.get("confidence",  0),
    }


# -- Scraping -----------------------------------------------------------------

TAGS = ['a','button','h1','h2','h3','h4','h5','h6','img','input','form','label','section','header','footer']
COORDINATE_JS = (
    "const el=Array.from(document.querySelectorAll('a,button,h1,h2,h3,h4,h5,h6,img,input,form,label,section,header,footer'))"
    ".map(e=>{const r=e.getBoundingClientRect();return{tag:e.tagName.toLowerCase(),"
    "x:r.left+window.scrollX,y:r.top+window.scrollY,width:r.width,height:r.height};});"
    "const c=document.createElement('div');c.id='scrapingbee-live-dom-matrices';"
    "c.style.display='none';c.innerText=JSON.stringify(el);document.body.appendChild(c);"
)


def safe_slug(url: str) -> str:
    parsed = urlparse(url)
    name = parsed.netloc.replace("www.", "")
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def build_dom_states(html: str, url: str, live_elements: list) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    elements = []
    for idx, el in enumerate(soup.find_all(TAGS)):
        tag = el.name
        text = (el.get_text(strip=True) or "")[:150]
        x, y, w, h = 40, 120 + idx * 60, 280, 45
        if idx < len(live_elements):
            live = live_elements[idx]
            if live.get("tag") == tag:
                x, y = live.get("x", x), live.get("y", y)
                w, h = live.get("width", w), live.get("height", h)
        elements.append({
            "tag": tag, "text": text,
            "id": el.get("id"), "class": el.get("class"),
            "role": el.get("role"), "aria_label": el.get("aria-label"),
            "states": {"default": {"display": "block", "visibility": "visible",
                "bbox": {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}}},
        })
    return {"meta": {"engine": "ScrapingBee", "url": url, "status": "success"}, "elements": elements}


def scrape_sync(url: str) -> dict:
    if not SCRAPINGBEE_API_KEY:
        return {"error": "SCRAPINGBEE_API_KEY not set"}
    client = ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)
    result = {"error": None, "html": None, "dom_states": None,
              "dom_summary": None, "screenshot_b64": None, "slug": safe_slug(url)}

    try:
        resp = client.get(url, params={
            "render_js": "true",
            "wait": "8000",
            "wait_browser": "networkidle2",
            "window_width": "1440",
            "window_height": "900",
            "block_ads": "true",
            "js_scenario": {"instructions": [{"evaluate": COORDINATE_JS}]},
        })
        if resp.status_code != 200:
            result["error"] = f"ScrapingBee failed: {resp.status_code}"
            return result
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        container = soup.find(id="scrapingbee-live-dom-matrices")
        live_elements = []
        if container and container.text:
            try:
                live_elements = json.loads(container.text)
                container.decompose()
                html = str(soup)
            except Exception:
                pass
        result["html"] = html
    except Exception as exc:
        result["error"] = f"HTML fetch error: {exc}"
        return result

    try:
        ss = client.get(url, params={
            "render_js": "true",
            "wait": "8000",
            "wait_browser": "networkidle2",
            "screenshot": "true",
            "screenshot_full_page": "true",
            "window_width": "1440",
            "block_ads": "true",
        })
        if ss.status_code == 200:
            result["screenshot_b64"] = base64.b64encode(ss.content).decode()
    except Exception as exc:
        log.warning("Screenshot error: %s", exc)

    dom = build_dom_states(html, url, live_elements)
    result["dom_states"] = dom
    result["dom_summary"] = {
        "total_elements": len(dom["elements"]),
        "sample": dom["elements"][:5],
    }
    return result


def run_cro_audit(html: str, dom_elements: list, industry: str, url: str) -> dict | None:
    if not CRO_AVAILABLE:
        return None
    try:
        report = run_audit(html, dom_elements, industry=industry, url=url)
        final  = run_wolf(report, html, dom_elements, industry=industry)
        return final
    except Exception as exc:
        log.warning("CRO audit error: %s", exc)
        return {"error": str(exc)}


# -- REST /scrape API ---------------------------------------------------------

async def handle_scrape_api(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    url = body.get("url", "").strip()
    if not url.startswith("http"):
        return JSONResponse({"error": "URL must start with http:// or https://"}, status_code=400)

    industry = body.get("industry", "all").strip() or "all"
    hunter_key = body.get("hunter_api_key", "").strip() or HUNTER_API_KEY
    skip_hunter = body.get("skip_hunter", False)

    hunter_data = None
    if not skip_hunter and hunter_key:
        domain = extract_domain(url)
        log.info("Hunter lookup: %s", domain)
        hunter_data = hunter_lookup(domain, hunter_key)
        if not hunter_data.get("found"):
            return JSONResponse({
                "no_decision_maker": True,
                "hunter_data": hunter_data,
                "url": url,
            })

    log.info("Scraping: %s", url)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, scrape_sync, url)
    result["hunter_data"] = hunter_data
    result["no_decision_maker"] = False

    # Run CRO audit if scrape succeeded
    if not result.get("error") and result.get("html") and CRO_AVAILABLE:
        dom_elements = result.get("dom_states", {}).get("elements", [])
        cro = await loop.run_in_executor(
            None, run_cro_audit, result["html"], dom_elements, industry, url
        )
        result["cro_audit"] = cro
    else:
        result["cro_audit"] = None

    return JSONResponse(result)


# -- MCP Streamable HTTP ------------------------------------------------------

async def dispatch(msg: dict):
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params", {})
    def ok(r): return {"jsonrpc":"2.0","id":msg_id,"result":r}
    def err(c,m): return {"jsonrpc":"2.0","id":msg_id,"error":{"code":c,"message":m}}

    if method == "initialize":
        return ok({"protocolVersion":MCP_PROTOCOL_VERSION,"capabilities":{"tools":{}},"serverInfo":SERVER_INFO})
    elif method == "ping": return ok({})
    elif method == "tools/list": return ok({"tools":TOOLS})
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments",{})
        if name != "scrape_website": return err(-32601,f"Unknown tool: {name}")
        url = args.get("url","").strip()
        industry = args.get("industry", "all") or "all"
        if not url.startswith("http"):
            return ok({"content":[{"type":"text","text":"Error: URL must start with http"}],"isError":True})
        loop = asyncio.get_event_loop()
        hunter_key = HUNTER_API_KEY
        if hunter_key:
            domain = extract_domain(url)
            hd = hunter_lookup(domain, hunter_key)
            if not hd.get("found"):
                return ok({"content":[{"type":"text","text":f"No decision maker found for {domain}. Skipping scrape."}],"isError":False})
        result = await loop.run_in_executor(None, scrape_sync, url)
        if result.get("error"):
            return ok({"content":[{"type":"text","text":f"Scrape failed: {result['error']}"}],"isError":True})
        lines = [f"Scrape complete: {url}","",f"DOM: {result['dom_summary']['total_elements']} elements"]
        if CRO_AVAILABLE:
            dom_elements = result.get("dom_states", {}).get("elements", [])
            cro = await loop.run_in_executor(None, run_cro_audit, result["html"], dom_elements, industry, url)
            if cro and not cro.get("error"):
                s = cro.get("summary", {})
                lines += ["", f"CRO Audit: {s.get('confirmed_high',0)} HIGH, {s.get('confirmed_medium',0)} MEDIUM issues, {s.get('gaps_detected',0)} gaps detected"]
                for iss in (cro.get("issues") or [])[:5]:
                    if iss.get("decision") != "suppressed":
                        lines.append(f"  [{iss.get('severity','?').upper()}] {iss.get('title','')[:80]}")
        content = [{"type":"text","text":"\n".join(lines)}]
        if result.get("screenshot_b64"):
            content.append({"type":"image","data":result["screenshot_b64"],"mimeType":"image/png"})
        return ok({"content":content,"isError":False})
    elif msg_id is None: return None
    else: return err(-32601,f"Method not found: {method}")


async def handle_mcp(request: Request):
    if request.method == "GET":
        async def es():
            while True: yield "event: ping\ndata: {}\n\n"; await asyncio.sleep(15)
        return StreamingResponse(es(), media_type="text/event-stream",
            headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
    try: body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Parse error"}},status_code=400)
    if isinstance(body, list):
        responses = [r for r in [await dispatch(m) for m in body] if r is not None]
        return JSONResponse(responses) if responses else Response(status_code=202)
    result = await dispatch(body)
    return Response(status_code=202) if result is None else JSONResponse(result)


# -- OAuth --------------------------------------------------------------------

async def oauth_protected_resource(request: Request):
    return JSONResponse({"resource":BASE_URL,"authorization_servers":[BASE_URL],"bearer_methods_supported":["header"]})
async def oauth_authorization_server(request: Request):
    return JSONResponse({"issuer":BASE_URL,"authorization_endpoint":f"{BASE_URL}/oauth/authorize",
        "token_endpoint":f"{BASE_URL}/oauth/token","response_types_supported":["code"],
        "grant_types_supported":["authorization_code"],"code_challenge_methods_supported":["S256"]})
async def oauth_authorize(request: Request):
    p = dict(request.query_params)
    code = secrets.token_urlsafe(32)
    qs = urlencode({k:v for k,v in [("code",code),("state",p.get("state",""))] if v})
    return RedirectResponse(url=f"{p.get('redirect_uri','')}?{qs}" if p.get("redirect_uri") else "/",status_code=302)
async def oauth_token(request: Request):
    return JSONResponse({"access_token":secrets.token_urlsafe(32),"token_type":"bearer","expires_in":86400,"scope":""})
async def healthcheck(request: Request):
    return JSONResponse({"status":"ok","server":"web-scraper MCP + REST API v2.1","cro_available":CRO_AVAILABLE})


# -- App ----------------------------------------------------------------------

web = Starlette(routes=[
    Route("/", healthcheck),
    Route("/.well-known/oauth-protected-resource", oauth_protected_resource),
    Route("/.well-known/oauth-authorization-server", oauth_authorization_server),
    Route("/oauth/authorize", oauth_authorize),
    Route("/oauth/token", oauth_token, methods=["GET","POST"]),
    Route("/mcp", handle_mcp, methods=["GET","POST","OPTIONS"]),
    Route("/scrape", handle_scrape_api, methods=["POST","OPTIONS"]),
])
web.add_middleware(CORSMiddleware, allow_origins=["*"],
    allow_methods=["GET","POST","DELETE","OPTIONS"], allow_headers=["*"], allow_credentials=False)

if __name__ == "__main__":
    uvicorn.run(web, host="0.0.0.0", port=PORT)
