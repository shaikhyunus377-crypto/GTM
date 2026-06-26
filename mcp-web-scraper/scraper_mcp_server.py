#!/usr/bin/env python3
import os
import json
import base64
import logging
import asyncio
import secrets
from urllib.parse import urlparse, urlencode

from bs4 import BeautifulSoup
from scrapingbee import ScrapingBeeClient
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.middleware.cors import CORSMiddleware
import uvicorn

SCRAPINGBEE_API_KEY = os.environ.get("SCRAPINGBEE_API_KEY", "")
OUTPUT_DIR = os.environ.get("SCRAPER_OUTPUT_DIR", "/tmp/scraper_output")
PORT = int(os.environ.get("PORT", 8000))
BASE_URL = os.environ.get("BASE_URL", "https://gtm-production-8ae5.up.railway.app")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

TAGS = ['a','button','h1','h2','h3','h4','h5','h6','img','input','form','label','section','header','footer']

COORDINATE_JS = (
    "const el=Array.from(document.querySelectorAll('a,button,h1,h2,h3,h4,h5,h6,img,input,form,label,section,header,footer'))"
    ".map(e=>{const r=e.getBoundingClientRect();return{tag:e.tagName.toLowerCase(),"
    "x:r.left+window.scrollX,y:r.top+window.scrollY,width:r.width,height:r.height};});"
    "const c=document.createElement('div');c.id='scrapingbee-live-dom-matrices';"
    "c.style.display='none';c.innerText=JSON.stringify(el);document.body.appendChild(c);"
)


def safe_folder(url):
    parsed = urlparse(url)
    name = parsed.netloc.replace("www.", "")
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def build_dom_states(html, url, live_elements):
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


def scrape_sync(url):
    if not SCRAPINGBEE_API_KEY:
        return {"error": "SCRAPINGBEE_API_KEY env var not set."}
    client = ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)
    folder = os.path.join(OUTPUT_DIR, safe_folder(url))
    os.makedirs(folder, exist_ok=True)
    result = {"html_path": None, "dom_states_path": None, "screenshot_path": None,
               "dom_summary": None, "screenshot_b64": None, "error": None}
    try:
        resp = client.get(url, params={
            "render_js": "true", "wait": "4500", "window_width": "1440", "window_height": "2000",
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
        html_path = os.path.join(folder, "full_rendered_inlined.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        result["html_path"] = html_path
    except Exception as exc:
        result["error"] = f"HTML fetch error: {exc}"
        return result
    try:
        ss = client.get(url, params={
            "render_js": "true", "wait": "4500",
            "screenshot": "true", "screenshot_full_page": "true", "window_width": "1440",
        })
        if ss.status_code == 200:
            ss_path = os.path.join(folder, "full_page.png")
            with open(ss_path, "wb") as f:
                f.write(ss.content)
            result["screenshot_path"] = ss_path
            if len(ss.content) <= 750_000:
                result["screenshot_b64"] = base64.b64encode(ss.content).decode()
    except Exception as exc:
        log.warning("Screenshot error: %s", exc)
    dom = build_dom_states(html, url, live_elements)
    dom_path = os.path.join(folder, "dom_states.json")
    with open(dom_path, "w", encoding="utf-8") as f:
        json.dump(dom, f, indent=2, ensure_ascii=False)
    result["dom_states_path"] = dom_path
    result["dom_summary"] = {"total_elements": len(dom["elements"]), "sample": dom["elements"][:5]}
    return result


# ── FastMCP server (handles streamable HTTP at /mcp) ───────────────────────────

fmcp = FastMCP("web-scraper")


@fmcp.tool()
async def scrape_website(url: str) -> str:
    """Scrapes a website using a real headless browser. Returns rendered HTML, DOM element states with bounding boxes, and a full-page screenshot."""
    if not url.startswith("http"):
        return "Error: URL must start with http:// or https://"
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, scrape_sync, url)
    if result.get("error"):
        return f"Scrape failed: {result['error']}"
    return "\n".join([
        f"Scrape complete: {url}",
        f"DOM elements: {result['dom_summary']['total_elements']} extracted",
        f"Sample: {json.dumps(result['dom_summary']['sample'][:3], indent=2)}",
        f"HTML saved: {result['html_path']}",
        f"DOM JSON: {result['dom_states_path']}",
        f"Screenshot: {result.get('screenshot_path') or 'not captured'}",
    ])


# Get the streamable HTTP ASGI app from FastMCP (mounts at /mcp)
mcp_asgi = fmcp.streamable_http_app()


# ── OAuth 2.0 (required by Claude.ai) ──────────────────────────────────────────

async def oauth_protected_resource(request: Request):
    return JSONResponse({
        "resource": BASE_URL,
        "authorization_servers": [BASE_URL],
        "bearer_methods_supported": ["header"],
    })


async def oauth_authorization_server(request: Request):
    return JSONResponse({
        "issuer": BASE_URL,
        "authorization_endpoint": f"{BASE_URL}/oauth/authorize",
        "token_endpoint": f"{BASE_URL}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
    })


async def oauth_authorize(request: Request):
    params = dict(request.query_params)
    redirect_uri = params.get("redirect_uri", "")
    state = params.get("state", "")
    code = secrets.token_urlsafe(32)
    qs = urlencode({k: v for k, v in [("code", code), ("state", state)] if v})
    target = f"{redirect_uri}?{qs}" if redirect_uri else "/"
    return RedirectResponse(url=target, status_code=302)


async def oauth_token(request: Request):
    return JSONResponse({
        "access_token": secrets.token_urlsafe(32),
        "token_type": "bearer",
        "expires_in": 86400,
    })


async def healthcheck(request: Request):
    return JSONResponse({"status": "ok", "server": "web-scraper MCP", "mcp_endpoint": "/mcp"})


# ── Starlette app ─────────────────────────────────────────────────────────────────

web = Starlette(routes=[
    Route("/", healthcheck),
    Route("/.well-known/oauth-protected-resource", oauth_protected_resource),
    Route("/.well-known/oauth-authorization-server", oauth_authorization_server),
    Route("/oauth/authorize", oauth_authorize),
    Route("/oauth/token", oauth_token, methods=["GET", "POST"]),
    Mount("/", app=mcp_asgi),
])

# CORS — required for Claude.ai web (browser makes cross-origin requests)
web.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

if __name__ == "__main__":
    uvicorn.run(web, host="0.0.0.0", port=PORT)
