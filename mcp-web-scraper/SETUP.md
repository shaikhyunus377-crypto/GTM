# Web Scraper MCP — Mobile/Web Setup (Railway)

## Deploy to Railway (one-time, no terminal needed)

1. Go to **railway.app** and sign in with GitHub
2. Click **New Project → Deploy from GitHub repo**
3. Select your **GTM** repo
4. When asked for root directory, set it to **`mcp-web-scraper`**
5. Railway auto-detects `railway.toml` and deploys

## Set your API key in Railway

In Railway → your service → **Variables**, add:

| Key | Value |
|-----|-------|
| `SCRAPINGBEE_API_KEY` | your ScrapingBee key |

## Get your public URL

Railway → your service → **Settings → Domains** → Generate Domain.
It will look like: `https://gtm-production-xxxx.up.railway.app`

## Connect to Claude.ai (web / mobile)

1. Open **claude.ai** in Chrome
2. Go to **Settings → Integrations**
3. Add a new MCP server:
   - **URL:** `https://your-railway-url.up.railway.app/sse`
   - **Name:** Web Scraper

## Use it in chat

Just say: **"Scrape https://example.com"**

Claude will call `scrape_website` and return:
- DOM element summary
- Full-page screenshot shown inline in chat
- Rendered HTML + dom_states.json saved on the server
