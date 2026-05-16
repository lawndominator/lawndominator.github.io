#!/usr/bin/env python3
"""
Automated product-source discovery for Lawn Dominator.

This is a local/offline curation step. It finds candidate merchant URLs for each
product and writes product_sources.json. The scheduled price scraper then checks
those saved URLs for price changes without needing a paid discovery API.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Iterable

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCTS_PATH = os.path.join(ROOT, "products.json")
SOURCES_PATH = os.path.join(ROOT, "product_sources.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

RETAILERS = [
    {
        "key": "domyown",
        "name": "DoMyOwn",
        "host": "domyown.com",
        "search": "https://www.domyown.com/search?w={query}",
    },
    {
        "key": "solutions",
        "name": "Solutions Pest & Lawn",
        "host": "solutionsstores.com",
        "search": "https://www.solutionsstores.com/search?q={query}",
    },
    {
        "key": "seed-world",
        "name": "Seed World",
        "host": "seedworldusa.com",
        "search": "https://www.seedworldusa.com/search?q={query}",
    },
    {
        "key": "seed-barn",
        "name": "Seed Barn",
        "host": "seedbarn.com",
        "search": "https://seedbarn.com/search?q={query}",
    },
    {
        "key": "forestry-distributing",
        "name": "Forestry Distributing",
        "host": "forestrydistributing.com",
        "search": "https://www.forestrydistributing.com/search?search={query}",
    },
    {
        "key": "pestrong",
        "name": "Pestrong",
        "host": "pestrong.com",
        "search": "https://pestrong.com/?s={query}&post_type=product",
    },
    {
        "key": "reinders",
        "name": "Reinders",
        "host": "reinders.com",
        "search": "https://www.reinders.com/search?query={query}",
    },
    {
        "key": "keystone-pest-solutions",
        "name": "Keystone Pest Solutions",
        "host": "keystonepestsolutions.com",
        "search": "https://www.keystonepestsolutions.com/catalogsearch/result/?q={query}",
    },
    {
        "key": "lawn-synergy",
        "name": "Lawn Synergy",
        "host": "lawnsynergy.com",
        "search": "https://lawnsynergy.com/search?q={query}",
    },
    {
        "key": "gci-turf-academy",
        "name": "GCI Turf Academy",
        "host": "gciturfacademy.com",
        "search": "https://gciturfacademy.com/search?q={query}",
    },
    {
        "key": "yard-mastery",
        "name": "Yard Mastery",
        "host": "yardmastery.com",
        "search": "https://yardmastery.com/search?q={query}",
    },
    {
        "key": "amazon",
        "name": "Amazon",
        "host": "amazon.com",
        "search": "https://www.amazon.com/s?k={query}&tag={amazon_tag}",
        "search_only": True,
    },
    {
        "key": "ebay",
        "name": "eBay",
        "host": "ebay.com",
        "search": "https://www.ebay.com/sch/i.html?_nkw={query}",
    },
]

SEARCH_ENGINES = [
    "https://www.bing.com/search?q={query}",
    "https://duckduckgo.com/html/?q={query}",
]

BLOCKED_PATH_BITS = (
    "/cart", "/checkout", "/account", "/login", "/privacy", "/terms",
    "/blog", "/article", "/guide", "/category", "/collections/all",
    "/search", "/collections", "/pages", "/cdn-cgi",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: str, fallback: dict) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return fallback


def save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


_playwright = None
_browser = None


def fetch(url: str, timeout: int = 20) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code >= 400:
            return ""
        return resp.text
    except requests.RequestException:
        return ""


def browser_fetch(url: str, timeout_ms: int = 18000) -> str:
    if not _browser:
        return ""
    context = None
    try:
        context = _browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="en-US",
        )
        page = context.new_page()
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        if response and response.status >= 400:
            return ""
        page.wait_for_timeout(1200)
        return page.content()
    except Exception:
        return ""
    finally:
        if context:
            context.close()


def normalize_url(url: str, base: str = "") -> str:
    absolute = urllib.parse.urljoin(base, url)
    parsed = urllib.parse.urlparse(absolute)
    clean_query = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower().startswith(("utm_", "fbclid", "gclid", "srsltid")):
            continue
        clean_query.append((key, value))
    return urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc.lower(),
        parsed.path.rstrip("/") or "/",
        "",
        urllib.parse.urlencode(clean_query, doseq=True),
        "",
    ))


def host(url: str) -> str:
    value = urllib.parse.urlparse(url).netloc.lower()
    return value[4:] if value.startswith("www.") else value


def is_google_url(url: str) -> bool:
    h = host(url)
    return h == "google.com" or h.endswith(".google.com")


def visible_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def product_terms(product: dict) -> list[str]:
    values = [
        product.get("name", ""),
        product.get("search_query", ""),
        product.get("active_ingredient", ""),
        *product.get("alt_names", []),
    ]
    terms = []
    for value in values:
        cleaned = re.sub(r"\([^)]*\)", "", str(value)).lower()
        tokens = [t for t in re.findall(r"[a-z0-9]+", cleaned) if len(t) > 1]
        if tokens:
            terms.append(" ".join(tokens))
    return terms


def score_candidate(product: dict, title: str, url: str) -> int:
    haystack = f"{title} {url}".lower()
    score = 0
    for term in product_terms(product):
        tokens = term.split()
        hits = sum(1 for token in tokens if token in haystack)
        if hits == len(tokens):
            score += 8
        elif hits >= min(2, len(tokens)):
            score += 4
        elif hits == 1 and len(tokens) == 1:
            score += 3
    if product.get("slug", "").replace("-", "") in re.sub(r"[^a-z0-9]", "", url.lower()):
        score += 5
    if any(bit in urllib.parse.urlparse(url).path.lower() for bit in ("/product", "/products", ".html", "/p/")):
        score += 2
    return score


def bad_candidate(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return True
    if is_google_url(url):
        return True
    path = parsed.path.lower()
    return any(bit in path for bit in BLOCKED_PATH_BITS)


def anchors_from_html(html: str, base_url: str) -> Iterable[tuple[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "")
        title = visible_text(anchor.get_text(" ", strip=True))
        if not title:
            title = visible_text(anchor.get("aria-label", "") or anchor.get("title", ""))
        yield title, normalize_url(href, base_url)


def discover_retailer_candidates(product: dict, retailer: dict, limit: int, use_browser: bool) -> list[dict]:
    query = urllib.parse.quote_plus(product.get("search_query") or product["name"])
    amazon_tag = os.getenv("AMAZON_AFFILIATE_TAG", "lawndominator-20")
    search_url = retailer["search"].format(query=query, amazon_tag=amazon_tag)

    if retailer.get("search_only"):
        return [{
            "url": normalize_url(search_url),
            "retailer": retailer["key"],
            "retailer_name": retailer["name"],
            "title": f"{product['name']} search results",
            "source": "marketplace_search",
            "source_type": "search",
            "confidence": 1,
            "last_seen": now_iso(),
        }]

    html = browser_fetch(search_url) if use_browser else fetch(search_url)
    candidates = {}
    if html:
        for title, url in anchors_from_html(html, search_url):
            if bad_candidate(url) or retailer["host"] not in host(url):
                continue
            score = score_candidate(product, title, url)
            if score < 4:
                continue
            candidates[url] = {
                "url": url,
                "retailer": retailer["key"],
                "retailer_name": retailer["name"],
                "title": title or product["name"],
                "source": "retailer_search",
                "source_type": "product",
                "confidence": score,
                "last_seen": now_iso(),
            }

    return sorted(candidates.values(), key=lambda c: c["confidence"], reverse=True)[:limit]


def discover_web_candidates(product: dict, retailer: dict, per_engine_limit: int, use_browser: bool) -> list[dict]:
    query = urllib.parse.quote_plus(f'site:{retailer["host"]} "{product.get("search_query") or product["name"]}"')
    candidates = {}
    for template in SEARCH_ENGINES:
        html = browser_fetch(template.format(query=query)) if use_browser else fetch(template.format(query=query))
        if not html:
            continue
        for title, url in anchors_from_html(html, template):
            if bad_candidate(url) or retailer["host"] not in host(url):
                continue
            score = score_candidate(product, title, url)
            if score < 4:
                continue
            candidates[url] = {
                "url": url,
                "retailer": retailer["key"],
                "retailer_name": retailer["name"],
                "title": title or product["name"],
                "source": "web_search",
                "source_type": "product",
                "confidence": score,
                "last_seen": now_iso(),
            }
        time.sleep(0.8)
    return sorted(candidates.values(), key=lambda c: c["confidence"], reverse=True)[:per_engine_limit]


def merge_sources(existing: list[dict], new_sources: list[dict], limit: int) -> list[dict]:
    merged = {}
    for item in [*existing, *new_sources]:
        url = item.get("url")
        if not url or is_google_url(url):
            continue
        normalized = normalize_url(url)
        copy = {**item, "url": normalized}
        current = merged.get(normalized)
        if not current or copy.get("confidence", 0) > current.get("confidence", 0):
            merged[normalized] = copy
    return sorted(merged.values(), key=lambda c: c.get("confidence", 0), reverse=True)[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover merchant product URLs for product_sources.json")
    parser.add_argument("--max-products", type=int, default=0, help="Only process the first N products, 0 means all")
    parser.add_argument("--start", type=int, default=0, help="Skip the first N products")
    parser.add_argument("--max-links", type=int, default=10, help="Maximum saved links per product")
    parser.add_argument("--retailer-limit", type=int, default=0, help="Only use first N retailer definitions, 0 means all")
    parser.add_argument("--web-search", action="store_true", help="Also search Bing/DuckDuckGo for site-specific URLs")
    parser.add_argument("--browser", action="store_true", help="Use local Playwright Chromium for JS-rendered search pages")
    parser.add_argument("--delay", type=float, default=0.8, help="Delay between retailer requests")
    args = parser.parse_args()

    catalog = load_json(PRODUCTS_PATH, {"products": []})
    sources = load_json(SOURCES_PATH, {"schema_version": "1.0", "updated_at": None, "products": {}})
    sources.setdefault("products", {})

    products = catalog.get("products", [])[args.start:]
    if args.max_products:
        products = products[:args.max_products]

    retailers = RETAILERS[:args.retailer_limit] if args.retailer_limit else RETAILERS
    global _playwright, _browser
    if args.browser:
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True)

    try:
        for index, product in enumerate(products, args.start + 1):
            print(f"[{index}] {product['name']}")
            discovered = []
            for retailer in retailers:
                retailer_candidates = discover_retailer_candidates(product, retailer, 2, args.browser)
                discovered.extend(retailer_candidates)
                if args.web_search and not retailer.get("search_only"):
                    discovered.extend(discover_web_candidates(product, retailer, 1, args.browser))
                time.sleep(args.delay)

            product_id = str(product["id"])
            existing = sources["products"].get(product_id, [])
            sources["products"][product_id] = merge_sources(existing, discovered, args.max_links)
            print(f"  saved {len(sources['products'][product_id])} links")
            save_json(SOURCES_PATH, {**sources, "updated_at": now_iso()})
    finally:
        if _browser:
            _browser.close()
        if _playwright:
            _playwright.stop()

    sources["updated_at"] = now_iso()
    save_json(SOURCES_PATH, sources)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
