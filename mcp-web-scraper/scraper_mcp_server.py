#!/usr/bin/env python3
"""
Remote MCP Server — Web Scraper
MCP Streamable HTTP transport (POST /mcp) — required by Claude.ai web.
Deploy to Railway; set SCRAPINGBEE_API_KEY and BASE_URL in Railway env vars.
"""

import os
import json
import base64
import logging
import asyncio
import secrets
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
OUTPUT_DIR = os.environ.get("SCRAPER_OUTPUT_DIR", "/tmp/scraper_output")
PORT = int(os.environ.get("PORT", 8000))
BASE_URL = os.environ.get("BASE_URL", "https://gtm-production-8ae5.up.railway.app")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "web-scraper", "version": "1.0.0"}

TOOLS = [{
    "name": "scrape_website",
    "description": (
        "Scrapes a website using a real headless browser (ScrapingBee). "
        "Returns rendered HTML, DOM states JSON with bounding boxes, and a full-page PNG screenshot."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL to scrape, e.g. https://example.com"}
        },
        "required": ["url"],
    },
}]

# ── Scraping logic ──────────────────────────────────────────────────────────────────────

TAGS = ['a','button','h1','h2','h3','h4','h5','h6','img','input','form','label','section','header','footer']
COORDINATE_JS = (
    "const el=Array.from(document.querySelectorAll('a,button,h1,h2,h3,h4,h5,h6,img,input,form,label,section,header,footer'))"
    ".map(e=>{const r=e.getBoundingClientRect();return{tag:e.tagName.toLowerCase(),"
    "x:r.left+window.scrollX,y:r.top+window.scrollY,width:r.width,height:r.height};});"
    "const c=document.createElement('div');c.id='scrapingbee-live-dom-matrices';"
    "c.style.display='none';c.innerText=JSON.stringify(el);document.body.appendChild(c);"
)


def safe_folder(url: str) -> str:
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
        return {"error": "SCRAPINGBEE_API_KEY env var not set."}
    client = ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)
    folder = os.path.join(OUTPUT_DIR, safe_folder(url))
    os.makedirs(folder, exist_ok=True)
    result = {"html_path": None, "dom_states_path": None, "screenshot_path": None,
               "dom_summary": None, "screenshot_b64": None, "error": None}
    try:
        resp = client.get(url, params={
            "render_js": "true", "wait": "4500",
            "window_width": "1440", "window_height": "2000",
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


# ── MCP Streamable HTTP handler (JSON-RPC 2.0) ──────────────────────────────────────

async def dispatch(msg: dict):
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params", {})

    def ok(result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    elif method == "ping":
        return ok({})
    elif method == "tools/list":
        return ok({"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        if name != "scrape_website":
            return err(-32601, f"Unknown tool: {name}")
        url = args.get("url", "").strip()
        if not url.startswith("http"):
            return ok({"content": [{"type": "text", "text": "Error: URL must start with http:// or https://"}], "isError": True})
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, scrape_sync, url)
        if result.get("error"):
            return ok({"content": [{"type": "text", "text": f"Scrape failed: {result['error']}"}], "isError": True})
        lines = [
            f"Scrape complete: {url}", "",
            f"DOM: {result['dom_summary']['total_elements']} elements found", "",
            "Sample elements:", json.dumps(result["dom_summary"]["sample"][:3], indent=2), "",
            f"HTML saved: {result['html_path']}",
            f"DOM JSON: {result['dom_states_path']}",
            f"Screenshot: {result.get('screenshot_path') or 'not captured'}",
        ]
        content = [{"type": "text", "text": "\n".join(lines)}]
        if result.get("screenshot_b64"):
            content.append({"type": "image", "data": result["screenshot_b64"], "mimeType": "image/png"})
        return ok({"content": content, "isError": False})
    elif msg_id is None:
        return None  # notification — no response
    else:
        return err(-32601, f"Method not found: {method}")


async def handle_mcp(request: Request):
    if request.method == "GET":
        # Keep-alive SSE stream for server-initiated messages
        async def event_stream():
            while True:
                yield "event: ping\ndata: {}\n\n"
                await asyncio.sleep(15)
        return StreamingResponse(
            event_stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
        )

    if isinstance(body, list):
        responses = [r for r in [await dispatch(m) for m in body] if r is not None]
        return JSONResponse(responses) if responses else Response(status_code=202)

    result = await dispatch(body)
    if result is None:
        return Response(status_code=202)
    return JSONResponse(result)


# ── OAuth 2.0 (required by Claude.ai web) ─────────────────────────────────────────────────

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
        "scope": "",
    })

async def healthcheck(request: Request):
    return JSONResponse({
        "status": "ok",
        "server": "web-scraper MCP",
        "transport": "streamable-http",
        "endpoint": "/mcp",
    })


# ── App ─────────────────────────────────────────────────────────────────────────────────────

web = Starlette(routes=[
    Route("/", healthcheck),
    Route("/.well-known/oauth-protected-resource", oauth_protected_resource),
    Route("/.well-known/oauth-authorization-server", oauth_authorization_server),
    Route("/oauth/authorize", oauth_authorize),
    Route("/oauth/token", oauth_token, methods=["GET", "POST"]),
    Route("/mcp", handle_mcp, methods=["GET", "POST", "OPTIONS"]),
])

web.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
)

if __name__ == "__main__":
    uvicorn.run(web, host="0.0.0.0", port=PORT)
