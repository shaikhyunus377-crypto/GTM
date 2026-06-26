#!/usr/bin/env python3
"""
MCP Server — Web Scraper
Exposes scrape_website as an MCP tool so Claude can call it from chat.
"""

import os
import json
import base64
import logging
import asyncio
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from scrapingbee import ScrapingBeeClient
import mcp.server.stdio
from mcp.server import Server
from mcp.types import Tool, TextContent, ImageContent

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG — override via environment variable for security
# ──────────────────────────────────────────────────────────────────────────────
SCRAPINGBEE_API_KEY = os.environ.get(
    "SCRAPINGBEE_API_KEY",
    "F1UC5UDJEHBDZXQH6A0SYJWDGAHP2H26XQWPEZBK6PZ6TT7Q159D7FUFCTMBTWG1BRZH0BQNJXF5RBB4",
)
OUTPUT_DIR = os.environ.get("SCRAPER_OUTPUT_DIR", os.path.expanduser("~/scraper_output"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

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

TAGS = ['a', 'button', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'img', 'input', 'form', 'label', 'section', 'header', 'footer']


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
                x = live.get("x", x)
                y = live.get("y", y)
                w = live.get("width", w)
                h = live.get("height", h)
        elements.append({
            "tag": tag,
            "text": text,
            "id": el.get("id"),
            "class": el.get("class"),
            "role": el.get("role"),
            "aria_label": el.get("aria-label"),
            "states": {
                "default": {
                    "display": "block",
                    "visibility": "visible",
                    "bbox": {"x": int(x), "y": int(y), "width": int(w), "height": int(h)},
                }
            },
        })
    return {
        "meta": {"engine": "ScrapingBee", "url": url, "status": "success"},
        "elements": elements,
    }


# ──────────────────────────────────────────────────────────────────────────────
# CORE SCRAPE FUNCTION  (sync, runs in thread-pool via asyncio)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_sync(url: str) -> dict:
    """Returns dict with keys: html_path, dom_states_path, screenshot_path, dom_summary, error"""
    client = ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)
    folder = os.path.join(OUTPUT_DIR, safe_folder(url))
    os.makedirs(folder, exist_ok=True)

    result: dict = {
        "html_path": None,
        "dom_states_path": None,
        "screenshot_path": None,
        "dom_summary": None,
        "screenshot_b64": None,
        "error": None,
    }

    # ── STEP 1: Rendered HTML + live coordinate injection ────────────────────
    log.info("Step 1 — fetching rendered HTML: %s", url)
    html = ""
    live_elements: list = []
    try:
        resp = client.get(
            url,
            params={
                "render_js": "true",
                "wait": "4500",
                "window_width": "1440",
                "window_height": "2000",
                "js_scenario": {"instructions": [{"evaluate": COORDINATE_JS}]},
            },
        )
        if resp.status_code != 200:
            result["error"] = f"ScrapingBee HTML fetch failed: {resp.status_code}"
            return result

        html = resp.text

        # Extract injected coordinate container
        soup = BeautifulSoup(html, "html.parser")
        container = soup.find(id="scrapingbee-live-dom-matrices")
        if container and container.text:
            live_elements = json.loads(container.text)
            container.decompose()
            html = str(soup)

        html_path = os.path.join(folder, "full_rendered_inlined.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        result["html_path"] = html_path
        log.info("Saved HTML → %s", html_path)

    except Exception as exc:
        result["error"] = f"HTML fetch error: {exc}"
        return result

    # ── STEP 2: Full-page screenshot ─────────────────────────────────────────
    log.info("Step 2 — capturing screenshot")
    try:
        ss_resp = client.get(
            url,
            params={
                "render_js": "true",
                "wait": "4500",
                "screenshot": "true",
                "screenshot_full_page": "true",
                "window_width": "1440",
            },
        )
        if ss_resp.status_code == 200:
            ss_path = os.path.join(folder, "full_page.png")
            with open(ss_path, "wb") as f:
                f.write(ss_resp.content)
            result["screenshot_path"] = ss_path
            # Encode small preview (cap at 1 MB base64) for inline MCP response
            if len(ss_resp.content) <= 750_000:
                result["screenshot_b64"] = base64.b64encode(ss_resp.content).decode()
            log.info("Saved screenshot → %s", ss_path)
        else:
            log.warning("Screenshot failed: %s", ss_resp.status_code)
    except Exception as exc:
        log.warning("Screenshot error: %s", exc)

    # ── STEP 3: Build and save dom_states.json ────────────────────────────────
    log.info("Step 3 — building dom_states.json")
    dom = build_dom_states(html, url, live_elements)
    dom_path = os.path.join(folder, "dom_states.json")
    with open(dom_path, "w", encoding="utf-8") as f:
        json.dump(dom, f, indent=2, ensure_ascii=False)
    result["dom_states_path"] = dom_path
    result["dom_summary"] = {
        "total_elements": len(dom["elements"]),
        "sample": dom["elements"][:5],
    }
    log.info("Saved dom_states.json → %s", dom_path)

    return result


# ──────────────────────────────────────────────────────────────────────────────
# MCP SERVER
# ──────────────────────────────────────────────────────────────────────────────

app = Server("web-scraper")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="scrape_website",
            description=(
                "Scrapes a website using a real headless browser via ScrapingBee. "
                "Returns: (1) fully rendered HTML with inline JS executed, "
                "(2) DOM states JSON with bounding-box coordinates for every key element, "
                "(3) full-page PNG screenshot. "
                "All files are also saved to disk for later use."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL to scrape (e.g. https://example.com)",
                    }
                },
                "required": ["url"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name != "scrape_website":
        raise ValueError(f"Unknown tool: {name}")

    url = arguments.get("url", "").strip()
    if not url.startswith("http"):
        return [TextContent(type="text", text="Error: URL must start with http:// or https://")]

    # Run the blocking scrape in a thread so we don't block the event loop
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, scrape_sync, url)

    content = []

    if result["error"]:
        content.append(TextContent(type="text", text=f"Scrape failed: {result['error']}"))
        return content

    summary_lines = [
        f"Scrape complete for: {url}",
        f"",
        f"Files saved to: {os.path.dirname(result['html_path'])}",
        f"  • HTML       → {result['html_path']}",
        f"  • DOM states → {result['dom_states_path']}",
        f"  • Screenshot → {result['screenshot_path'] or 'not captured'}",
        f"",
        f"DOM summary: {result['dom_summary']['total_elements']} elements extracted.",
        f"",
        f"Sample elements (first 5):",
        json.dumps(result["dom_summary"]["sample"], indent=2),
    ]
    content.append(TextContent(type="text", text="\n".join(summary_lines)))

    # Attach screenshot inline if small enough
    if result.get("screenshot_b64"):
        content.append(
            ImageContent(
                type="image",
                data=result["screenshot_b64"],
                mimeType="image/png",
            )
        )

    return content


async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
