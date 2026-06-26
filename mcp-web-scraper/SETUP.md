# Web Scraper MCP — Setup Guide

## Railway Deployment

1. Go to **railway.app** → New Project → Deploy from GitHub repo → select **GTM**
2. Set **Root Directory** to `mcp-web-scraper` in service settings
3. Add environment variables in Railway → Variables:

| Key | Value |
|-----|-------|
| `SCRAPINGBEE_API_KEY` | your ScrapingBee API key |
| `BASE_URL` | your Railway public URL (e.g. `https://gtm-production-8ae5.up.railway.app`) |

4. Generate a public domain: Railway → Settings → Domains → Generate Domain

## Connect to Claude.ai (web / mobile Chrome)

1. Open **claude.ai** in Chrome
2. Go to **Settings → Integrations** (or the connectors panel)
3. Click **Add custom connector** and enter:
   - **URL:** `https://your-railway-url.up.railway.app/mcp`
   - Leave OAuth fields blank (auto-approved)
4. Click Connect — it should show as connected

## Use it in chat

Just say: **"Scrape https://example.com"**

Claude will call `scrape_website` and return:
- Full-page screenshot shown inline
- DOM element summary with bounding boxes
- Rendered HTML + dom_states.json saved on the server

## Endpoint reference

| Path | Purpose |
|------|---------|
| `GET /` | Health check |
| `POST /mcp` | MCP Streamable HTTP (main endpoint) |
| `GET /mcp` | SSE keep-alive stream |
| `GET /.well-known/oauth-protected-resource` | OAuth metadata |
| `GET /.well-known/oauth-authorization-server` | OAuth metadata |
| `GET /oauth/authorize` | OAuth authorize (auto-approves) |
| `POST /oauth/token` | OAuth token (auto-issues) |
