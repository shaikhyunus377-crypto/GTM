#!/usr/bin/env python3
"""
pipeline.py  — GTM AI Agent Full Pipeline
==========================================
Exposes two endpoints the AI agent uses:

  POST /get-leads   — Apify Google Maps search → returns businesses with websites
  POST /pipeline    — Full pipeline: leads → scrape → CRO → Hunter contact
  GET  /pipeline/status/{job_id}  — poll async job
  GET  /            — health check

Deploy alongside or instead of the existing server.
All keys passed per-request — no env vars required.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import traceback
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

# Import existing CRO pipeline
try:
    from cro_bots.cro_audit import run_audit
    from cro_wolf import run_wolf
    CRO_AVAILABLE = True
except ImportError:
    CRO_AVAILABLE = False

APP_VERSION = "1.0.0"

# In-memory job store for async pipeline jobs
_jobs: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# APIFY  —  Google Maps scraper
# ─────────────────────────────────────────────────────────────────────────────

APIF_ACTOR = "compass~crawler-google-places"


async def apify_search(
    client: httpx.AsyncClient,
    token: str,
    search_term: str,
    max_results: int,
    country: str,
) -> list[dict]:
    """Run one Apify actor and return raw items."""
    payload = {
        "searchStringsArray":        [search_term],
        "maxCrawledPlacesPerSearch": min(max_results + 30, 200),
        "language":                  "en",
        "skipClosedPlaces":          True,
    }
    if country:
        payload["countryCode"] = country.lower()

    run_resp = await client.post(
        f"https://api.apify.com/v2/acts/{APIF_ACTOR}/runs",
        params={"token": token},
        json=payload,
        timeout=30,
    )
    if run_resp.status_code in (401, 403):
        raise ValueError(f"Invalid Apify token ({run_resp.status_code})")
    if not run_resp.is_success:
        err = run_resp.json().get("error", {}).get("message", f"HTTP {run_resp.status_code}")
        raise ValueError(f"Apify run failed: {err}")

    run_data   = run_resp.json()
    run_id     = run_data["data"]["id"]
    dataset_id = run_data["data"]["defaultDatasetId"]

    # Poll until done
    status = "READY"
    fails  = 0
    while status in ("READY", "RUNNING"):
        await asyncio.sleep(4)
        try:
            sr = await client.get(
                f"https://api.apify.com/v2/actor-runs/{run_id}",
                params={"token": token},
                timeout=15,
            )
            sd         = sr.json()
            status     = sd["data"]["status"]
            dataset_id = sd["data"].get("defaultDatasetId", dataset_id)
            fails      = 0
        except Exception:
            fails += 1
            if fails > 5:
                status = "FAILED"

    if status != "SUCCEEDED":
        return []

    items_resp = await client.get(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items",
        params={"token": token, "limit": 300, "clean": "true"},
        timeout=30,
    )
    if not items_resp.is_success:
        return []
    data = items_resp.json()
    return data if isinstance(data, list) else data.get("items", [])


def extract_zip(address: str) -> str | None:
    if not address:
        return None
    us = re.search(r"\b(\d{5})(?:-\d{4})?\b", address)
    if us:
        return us.group(1)
    uk = re.search(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})\b", address, re.I)
    if uk:
        return re.sub(r"\s+", " ", uk.group(1)).strip()
    ca = re.search(r"\b([A-Z]\d[A-Z]\s*\d[A-Z]\d)\b", address, re.I)
    if ca:
        return re.sub(r"\s+", " ", ca.group(1)).strip()
    return None


def niche_keywords(niche: str) -> list[str]:
    n = niche.lower()
    table = [
        (r"dental|dentist",            ["dentist","dental clinic","dental office","family dentistry","cosmetic dentist","orthodontist","pediatric dentist","emergency dentist"]),
        (r"chiropract",                ["chiropractor","chiropractic clinic","chiropractic office","spine specialist","back pain clinic"]),
        (r"physiother|physical ther",  ["physical therapy","physiotherapy clinic","rehabilitation center","sports rehab"]),
        (r"medical|doctor|physician",  ["medical clinic","doctor office","primary care physician","family doctor","urgent care","health clinic"]),
        (r"lawyer|attorney|law firm",  ["law firm","attorney office","legal services","personal injury lawyer","family lawyer"]),
        (r"restaurant|diner|bistro",   ["restaurant","diner","bistro","eatery","family restaurant"]),
        (r"cafe|coffee",               ["cafe","coffee shop","coffee house","espresso bar"]),
        (r"gym|fitness|crossfit",      ["gym","fitness center","health club","crossfit box","personal training studio"]),
        (r"salon|hair|barbershop",     ["hair salon","beauty salon","barber shop","hair stylist"]),
        (r"nail",                      ["nail salon","nail spa","manicure pedicure"]),
        (r"spa|massage",               ["spa","massage therapy","day spa","wellness center"]),
        (r"plumb",                     ["plumber","plumbing service","plumbing company","drain cleaning"]),
        (r"electric",                  ["electrician","electrical contractor","electrical service"]),
        (r"hvac|air condition|heating",["HVAC","air conditioning","heating and cooling","AC repair"]),
        (r"roof",                      ["roofing company","roof repair","roof replacement","roofing contractor"]),
        (r"real estate|realtor",       ["real estate agent","realtor","real estate office","property agent"]),
        (r"mortgage|loan broker",      ["mortgage broker","mortgage lender","home loan"]),
        (r"account|bookkeep",          ["accountant","accounting firm","CPA","bookkeeper","tax accountant"]),
        (r"insurance",                 ["insurance agent","insurance broker","life insurance","auto insurance"]),
        (r"auto repair|mechanic",      ["auto repair shop","mechanic","car repair","auto service"]),
        (r"car dealer",                ["car dealership","auto dealer","used car dealer"]),
        (r"hotel|motel|inn",           ["hotel","motel","inn","bed and breakfast"]),
        (r"landscap|lawn",             ["landscaping company","lawn care","lawn service"]),
        (r"cleaning|janitorial",       ["cleaning service","house cleaning","commercial cleaning"]),
        (r"vet|veterinar",             ["veterinarian","animal clinic","pet clinic","animal hospital"]),
        (r"optom|eye doctor|vision",   ["optometrist","eye doctor","vision center","eye clinic"]),
        (r"pharmacy|drugstore",        ["pharmacy","drugstore","compounding pharmacy"]),
        (r"tutoring|tutor",            ["tutoring center","tutor","learning center"]),
        (r"daycare|childcare|nursery", ["daycare","childcare center","nursery","preschool"]),
    ]
    for pattern, kws in table:
        if re.search(pattern, n):
            return kws
    base = niche.strip()
    return [base, base + " near me", base + " service", base + " company", "best " + base, "local " + base]


async def find_leads(
    token: str,
    niche: str,
    city: str,
    country: str,
    count: int,
    min_reviews: int,
    max_reviews: int,
    progress_cb=None,
) -> tuple[list[dict], list[str]]:
    """
    Two-phase Apify search:
      Phase 1 — broad city search to discover zip codes
      Phase 2 — iterate zip × keyword until count reached
    Returns (leads_list, zips_searched)
    """
    keywords    = niche_keywords(niche)
    country_str = f", {country}" if country else ""
    found       = {}   # website → lead dict
    seen_places = set()
    discovered  = {}   # zip → 0

    def process_items(items: list[dict]) -> int:
        added = 0
        for item in items:
            if len(found) >= count:
                break
            website = item.get("website") or item.get("url")
            if not website:
                continue
            reviews = item.get("reviewsCount") or item.get("totalReviews") or 0
            if reviews < min_reviews:
                continue
            if max_reviews and reviews > max_reviews:
                continue
            dk = item.get("placeId") or f"{item.get('title')}|{item.get('address')}"
            if dk in seen_places:
                continue
            seen_places.add(dk)
            norm = website if website.startswith("http") else "https://" + website
            if norm in found:
                continue
            found[norm] = {
                "website":  norm,
                "name":     item.get("title") or item.get("name") or "",
                "address":  item.get("address") or "",
                "phone":    item.get("phone") or item.get("phoneUnformatted") or "",
                "reviews":  reviews,
                "rating":   item.get("totalScore"),
                "category": item.get("categoryName") or (item.get("categories") or [""])[0],
            }
            added += 1
            z = extract_zip(item.get("address") or "")
            if z and z not in discovered:
                discovered[z] = 0
        # collect zips from no-website businesses too
        for item in items:
            z = extract_zip(item.get("address") or "")
            if z and z not in discovered:
                discovered[z] = 0
        return added

    limits = httpx.Limits(max_connections=5, max_keepalive_connections=2)
    async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
        # Phase 1
        if progress_cb:
            await progress_cb(f"Phase 1: discovering zip codes in {city}...")
        broad_term  = f"{keywords[0]} in {city}{country_str}"
        broad_items = await apify_search(client, token, broad_term, 100, country)
        process_items(broad_items)

        zip_list = list(discovered.keys())
        if progress_cb:
            await progress_cb(f"Found {len(zip_list)} zip codes, {len(found)}/{count} leads")

        # Phase 2  —  zip × keyword queue
        queue = []
        for z in zip_list:
            queue.append({"zip": z, "kw": keywords[0]})
        for ki in range(1, len(keywords)):
            for z in zip_list:
                queue.append({"zip": z, "kw": keywords[ki]})
        for kw in keywords[1:]:
            queue.append({"zip": None, "kw": kw})

        for entry in queue:
            if len(found) >= count:
                break
            z   = entry["zip"]
            kw  = entry["kw"]
            loc = f"{z}, {city}{country_str}" if z else f"{city}{country_str}"
            term = f"{kw} in {loc}"
            if progress_cb:
                await progress_cb(f"Searching '{term}' ({len(found)}/{count})")
            items = await apify_search(client, token, term, count - len(found), country)
            process_items(items)
            # dynamic zip discovery
            for item in items:
                z2 = extract_zip(item.get("address") or "")
                if z2 and z2 not in discovered:
                    discovered[z2] = 0
                    queue.append({"zip": z2, "kw": keywords[0]})

    return list(found.values()), list(discovered.keys())


# ─────────────────────────────────────────────────────────────────────────────
# WEB SCRAPER
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


async def scrape_website(client: httpx.AsyncClient, url: str, scrapingbee_key: str = "") -> dict:
    """Fetch HTML of a website. Uses ScrapingBee if key provided."""
    try:
        if scrapingbee_key:
            resp = await client.get(
                "https://app.scrapingbee.com/api/v1/",
                params={
                    "api_key":         scrapingbee_key,
                    "url":             url,
                    "render_js":       "true",
                    "block_ads":       "true",
                    "block_resources": "false",
                    "premium_proxy":   "false",
                },
                timeout=45,
            )
        else:
            resp = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)

        if resp.is_success:
            return {"html": resp.text, "status": "ok", "error": None}
        return {"html": "", "status": "error", "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"html": "", "status": "error", "error": str(e)[:120]}


# ─────────────────────────────────────────────────────────────────────────────
# CRO AUDIT
# ─────────────────────────────────────────────────────────────────────────────

def run_cro_pipeline(html: str, dom_elements: list, industry: str, url: str) -> dict:
    if not CRO_AVAILABLE or not html:
        return {"error": "CRO not available or no HTML", "summary": {}}
    try:
        report = run_audit(html, dom_elements, industry=industry, url=url)
        final  = run_wolf(report, html, dom_elements, industry=industry)
        cs     = final.get("summary", {})
        # Build client-friendly summary
        issues = [
            i for i in final.get("issues", [])
            if i.get("decision") == "confirmed"
            and i.get("severity") in ("high", "medium")
        ]
        return {
            "summary": {
                "high":   cs.get("confirmed_high", 0),
                "medium": cs.get("confirmed_medium", 0),
            },
            "top_issues": [
                {
                    "id":       i.get("id"),
                    "title":    i.get("title"),
                    "severity": i.get("severity"),
                    "fix":      i.get("fix", "")[:200],
                }
                for i in issues[:6]
            ],
            "pitch_angle": _pitch_angle(issues),
        }
    except Exception as e:
        return {"error": str(e), "summary": {}}


def _pitch_angle(issues: list[dict]) -> str:
    """Generate a one-line sales pitch angle from CRO issues."""
    if not issues:
        return "Website looks solid — pitch on growth opportunities."
    high = [i for i in issues if i.get("severity") == "high"]
    main = (high or issues)[0]
    title = main.get("title", "")
    severity = main.get("severity", "medium")
    prefix = "\U0001f6a8 Critical" if severity == "high" else "⚠️ Important"
    return f"{prefix}: {title}"


# ─────────────────────────────────────────────────────────────────────────────
# HUNTER.IO  —  Decision maker finder
# ─────────────────────────────────────────────────────────────────────────────

async def find_contact(client: httpx.AsyncClient, domain: str, hunter_key: str) -> dict:
    if not hunter_key or not domain:
        return {"found": False, "error": "No Hunter key"}
    domain = re.sub(r"^https?://(www\.)?|/.*$", "", domain)
    try:
        resp = await client.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": hunter_key, "limit": 5},
            timeout=15,
        )
        data = resp.json()
        emails = (data.get("data") or {}).get("emails", [])
        if not emails:
            return {"found": False, "total": 0}
        top = emails[0]
        return {
            "found":    True,
            "name":     f"{top.get('first_name','')} {top.get('last_name','')}".strip(),
            "email":    top.get("value", ""),
            "position": top.get("position", ""),
            "seniority":top.get("seniority", ""),
            "linkedin": top.get("linkedin", ""),
            "company":  (data.get("data") or {}).get("organization", ""),
            "total":    len(emails),
            "all_contacts": [
                {
                    "name":     f"{e.get('first_name','')} {e.get('last_name','')}".strip(),
                    "email":    e.get("value", ""),
                    "position": e.get("position", ""),
                    "linkedin": e.get("linkedin", ""),
                }
                for e in emails
            ],
        }
    except Exception as e:
        return {"found": False, "error": str(e)[:120]}


# ─────────────────────────────────────────────────────────────────────────────
# FULL PIPELINE RUNNER
# ─────────────────────────────────────────────────────────────────────────────

async def run_pipeline(
    job_id: str,
    apify_token: str,
    niche: str,
    city: str,
    country: str,
    count: int,
    min_reviews: int,
    max_reviews: int,
    hunter_key: str,
    scrapingbee_key: str,
    industry: str,
):
    job = _jobs[job_id]

    def update(stage: str, detail: str = "", pct: int = None):
        job["stage"]  = stage
        job["detail"] = detail
        if pct is not None:
            job["progress"] = pct
        job["updated_at"] = datetime.now(timezone.utc).isoformat()

    try:
        # ── Step 1: Get leads from Apify ──
        update("finding_leads", f"Searching Google Maps for '{niche}' in {city}", 5)
        leads, zips = await find_leads(
            apify_token, niche, city, country, count,
            min_reviews, max_reviews,
            progress_cb=lambda msg: update("finding_leads", msg),
        )
        update("leads_found", f"{len(leads)} leads found across {len(zips)} zip codes", 30)

        if not leads:
            job["status"]  = "done"
            job["result"]  = {"leads": [], "summary": {"total_leads": 0}}
            return

        # ── Step 2-4: Scrape + CRO + Hunter per lead ──
        results = []
        limits  = httpx.Limits(max_connections=8, max_keepalive_connections=4)

        async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
            sem = asyncio.Semaphore(3)  # max 3 concurrent scrapers

            async def process_lead(i: int, lead: dict) -> dict:
                async with sem:
                    pct = 30 + int((i / len(leads)) * 65)
                    update(
                        "processing",
                        f"Processing {i+1}/{len(leads)}: {lead['name'] or lead['website']}",
                        pct,
                    )
                    out = {**lead}

                    # Scrape
                    scrape = await scrape_website(client, lead["website"], scrapingbee_key)
                    out["scrape_status"] = scrape["status"]
                    out["scrape_error"]  = scrape.get("error")

                    # CRO
                    if scrape["html"]:
                        out["cro"] = run_cro_pipeline(
                            scrape["html"], [], industry, lead["website"]
                        )
                    else:
                        out["cro"] = {"error": "no HTML", "summary": {}}

                    # Hunter contact
                    domain = re.sub(r"^https?://(www\.)?|/.*$", "", lead["website"])
                    out["contact"] = await find_contact(client, domain, hunter_key)

                    return out

            tasks   = [process_lead(i, lead) for i, lead in enumerate(leads)]
            results = await asyncio.gather(*tasks, return_exceptions=False)

        # ── Step 5: Build summary ──
        update("building_summary", "", 97)
        with_contact = sum(1 for r in results if r.get("contact", {}).get("found"))
        with_cro     = sum(1 for r in results if r.get("cro") and not r["cro"].get("error"))
        high_issues  = sum(1 for r in results for _ in range(r.get("cro", {}).get("summary", {}).get("high", 0)))

        job["status"] = "done"
        job["result"] = {
            "summary": {
                "total_leads":    len(results),
                "with_contact":   with_contact,
                "with_cro_audit": with_cro,
                "total_high_cro": high_issues,
                "niche":          niche,
                "city":           city,
                "country":        country,
                "zips_searched":  zips,
                "generated_at":   datetime.now(timezone.utc).isoformat(),
            },
            "leads": results,
        }
        job["progress"] = 100
        update("done", f"Pipeline complete: {len(results)} leads", 100)

    except Exception as e:
        job["status"] = "error"
        job["error"]  = str(e)
        job["trace"]  = traceback.format_exc()[-800:]
        update("error", str(e))


# ─────────────────────────────────────────────────────────────────────────────
# HTTP HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

async def handle_health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status":        "ok",
        "service":       "GTM Pipeline Agent",
        "version":       APP_VERSION,
        "cro_available": CRO_AVAILABLE,
        "endpoints": ["/get-leads", "/pipeline", "/pipeline/status/{job_id}"],
    })


async def handle_get_leads(request: Request) -> JSONResponse:
    """
    POST /get-leads
    Body: { apify_token, niche, city, country?, count?, min_reviews?, max_reviews? }
    Returns leads immediately (may take 1-3 min for large counts).
    """
    body = await request.json()
    token       = body.get("apify_token", "").strip()
    niche       = body.get("niche", "").strip()
    city        = body.get("city", "").strip()
    country     = body.get("country", "").strip()
    count       = max(1, min(200, int(body.get("count", 20))))
    min_reviews = int(body.get("min_reviews", 0))
    max_reviews = int(body.get("max_reviews", 0))

    if not token:
        return JSONResponse({"error": "apify_token required"}, status_code=400)
    if not niche:
        return JSONResponse({"error": "niche required"}, status_code=400)
    if not city:
        return JSONResponse({"error": "city required"}, status_code=400)

    try:
        leads, zips = await find_leads(
            token, niche, city, country, count, min_reviews, max_reviews
        )
        return JSONResponse({
            "leads":        leads,
            "total":        len(leads),
            "city":         city,
            "niche":        niche,
            "zips_searched": zips,
        })
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def handle_pipeline_start(request: Request) -> JSONResponse:
    """
    POST /pipeline
    Body: {
      apify_token, niche, city,
      country?, count?, min_reviews?, max_reviews?,
      hunter_key?, scrapingbee_key?, industry?
    }
    Returns { job_id } immediately. Poll /pipeline/status/{job_id} for results.
    """
    body = await request.json()
    token           = body.get("apify_token", "").strip()
    niche           = body.get("niche", "").strip()
    city            = body.get("city", "").strip()
    country         = body.get("country", "").strip()
    count           = max(1, min(100, int(body.get("count", 10))))
    min_reviews     = int(body.get("min_reviews", 0))
    max_reviews     = int(body.get("max_reviews", 0))
    hunter_key      = body.get("hunter_key", "").strip()
    scrapingbee_key = body.get("scrapingbee_key", "").strip()
    industry        = body.get("industry", "local_business").strip()

    if not token:
        return JSONResponse({"error": "apify_token required"}, status_code=400)
    if not niche:
        return JSONResponse({"error": "niche required"}, status_code=400)
    if not city:
        return JSONResponse({"error": "city required"}, status_code=400)

    job_id = f"{int(time.time()*1000)}-{niche[:10].replace(' ','-')}"
    _jobs[job_id] = {
        "id":         job_id,
        "status":     "running",
        "stage":      "starting",
        "detail":     "",
        "progress":   0,
        "result":     None,
        "error":      None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "params":     {"niche": niche, "city": city, "country": country, "count": count},
    }

    # Fire and forget — run in background
    asyncio.create_task(run_pipeline(
        job_id, token, niche, city, country, count,
        min_reviews, max_reviews, hunter_key, scrapingbee_key, industry,
    ))

    return JSONResponse({
        "job_id":     job_id,
        "status":     "running",
        "message":    f"Pipeline started for '{niche}' in {city}. Poll /pipeline/status/{job_id} for results.",
        "poll_url":   f"/pipeline/status/{job_id}",
        "estimated_minutes": max(2, count // 3),
    })


async def handle_pipeline_status(request: Request) -> JSONResponse:
    """
    GET /pipeline/status/{job_id}
    Returns current job state, or full results when done.
    """
    job_id = request.path_params.get("job_id", "")
    job    = _jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    resp = {
        "job_id":     job["id"],
        "status":     job["status"],
        "stage":      job["stage"],
        "detail":     job["detail"],
        "progress":   job["progress"],
        "params":     job["params"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }
    if job["status"] == "done":
        resp["result"] = job["result"]
    elif job["status"] == "error":
        resp["error"] = job["error"]

    return JSONResponse(resp)


async def handle_pipeline_sync(request: Request) -> JSONResponse:
    """
    POST /pipeline/sync
    Same as /pipeline but waits and returns results directly.
    Use only for small counts (<=10 leads) to avoid timeout.
    """
    body            = await request.json()
    token           = body.get("apify_token", "").strip()
    niche           = body.get("niche", "").strip()
    city            = body.get("city", "").strip()
    country         = body.get("country", "").strip()
    count           = max(1, min(10, int(body.get("count", 3))))
    min_reviews     = int(body.get("min_reviews", 0))
    max_reviews     = int(body.get("max_reviews", 0))
    hunter_key      = body.get("hunter_key", "").strip()
    scrapingbee_key = body.get("scrapingbee_key", "").strip()
    industry        = body.get("industry", "local_business").strip()

    if not token:
        return JSONResponse({"error": "apify_token required"}, status_code=400)

    job_id = f"sync-{int(time.time()*1000)}"
    _jobs[job_id] = {
        "id": job_id, "status": "running", "stage": "starting",
        "detail": "", "progress": 0, "result": None, "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "params": {"niche": niche, "city": city, "count": count},
    }
    await run_pipeline(
        job_id, token, niche, city, country, count,
        min_reviews, max_reviews, hunter_key, scrapingbee_key, industry,
    )
    job = _jobs[job_id]
    if job["status"] == "error":
        return JSONResponse({"error": job["error"]}, status_code=500)
    return JSONResponse(job["result"])


# ─────────────────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────────────────

routes = [
    Route("/",                        handle_health,          methods=["GET"]),
    Route("/get-leads",               handle_get_leads,       methods=["POST"]),
    Route("/pipeline",                handle_pipeline_start,  methods=["POST"]),
    Route("/pipeline/sync",           handle_pipeline_sync,   methods=["POST"]),
    Route("/pipeline/status/{job_id}", handle_pipeline_status, methods=["GET"]),
]

app = Starlette(routes=routes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
