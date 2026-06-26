# Web Scraper MCP — Setup Guide

## 1. Install dependencies

```bash
pip install -r requirements.txt
```

## 2. Connect to Claude Desktop

Open `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac)
or `%APPDATA%\Claude\claude_desktop_config.json` (Windows) and add:

```json
{
  "mcpServers": {
    "web-scraper": {
      "command": "python",
      "args": ["/absolute/path/to/scraper_mcp_server.py"],
      "env": {
        "SCRAPINGBEE_API_KEY": "YOUR_SCRAPINGBEE_KEY",
        "SCRAPER_OUTPUT_DIR": "/absolute/path/to/output_folder"
      }
    }
  }
}
```

Replace the paths with real absolute paths on your machine.

## 3. Restart Claude Desktop

Quit and reopen Claude Desktop. You should see **web-scraper** listed under
connected MCP servers (hammer icon in the toolbar).

## 4. Use it in Claude chat

Just say:

> **Scrape https://example.com**

Claude will call `scrape_website`, and you'll get back:
- A summary of extracted DOM elements
- The full-page screenshot displayed inline (if ≤ 750 KB)
- All three files saved locally:
  - `full_rendered_inlined.html`
  - `dom_states.json`
  - `full_page.png`

## Environment variables (optional)

| Variable | Default | Purpose |
|---|---|---|
| `SCRAPINGBEE_API_KEY` | hardcoded fallback | Your ScrapingBee API key |
| `SCRAPER_OUTPUT_DIR` | `~/scraper_output` | Where files are saved |

Setting `SCRAPINGBEE_API_KEY` via env is recommended over hardcoding it.
