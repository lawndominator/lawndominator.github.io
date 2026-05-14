#!/usr/bin/env python3
"""
Lawn Dominator — Link Discovery Tool
Run this locally (not in CI) once to build product_sources.json.
Once saved, the GitHub Actions scraper hits those direct URLs every 4 hours
instead of searching each time — much faster and more reliable.

Usage:
  python scraper/find_links.py                  # discover all 66 products
  python scraper/find_links.py --ids 1,2,3      # only specific product IDs
  python scraper/find_links.py --refind         # re-discover even if sources exist
  python scraper/find_links.py --headless       # invisible browser (default: visible)

Requirements:
  pip install playwright beautifulsoup4 lxml requests
  playwright install chromium
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup, Tag

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: playwright not installed.  Run:  pip install playwright && playwright install chromium")
    sys.exit(1)

# ── Retailer search configs ────────────────────────────────────────────────────
RETAILERS = [
    {
        "key": "domyown",
        "name": "DoMyOwn",
        "base": "https://www.domyown.com",
        "search": "https://www.domyown.com/search?q={query}",
    },
    {
        "key": "solutions",
        "name": "Solutions Pest & Lawn",
        "base": "https://www.solutionspestcontrol.com",
        "search": "https://www.solutionspestcontrol.com/search?q={query}&type=product",
    },
    {
        "key": "yard-mastery",
        "name": "Yard Mastery",
        "base": "https://yardmastery.com",
        "search": "https://yardmastery.com/search?q={query}&type=product",
    },
    {
        "key": "gci-turf",
        "name": "GCI Turf Academy",
        "base": "https://gciturfacademy.com",
        "search": "https://gciturfacademy.com/search?q={query}&type=product",
    },
    {
        "key": "lawn-synergy",
        "name": "Lawn Synergy",
        "base": "https://lawnsynergy.com",
        "search": "https://lawnsynergy.com/search?q={query}&type=product",
    },
    {
        "key": "forestry-distributing",
        "name": "Forestry Distributing",
        "base": "https://www.forestrydistributing.com",
        "search": "https://www.forestrydistributing.com/search?search={query}",
    },
    {
        "key": "pestrong",
        "name": "Pestrong",
        "base": "https://pestrong.com",
        "search": "https://pestrong.com/?s={query}&post_type=product",
    },
    {
        "key": "reinders",
        "name": "Reinders",
        "base": "https://www.reinders.com",
        "search": "https://www.reinders.com/search?query={query}",
    },
    {
        "key": "do-it-best",
        "name": "Do It Best",
        "base": "https://www.doitbest.com",
        "search": "https://www.doitbest.com/search#q={query}&t=product",
    },
]

# Selectors to find the first product link on a search results page
PRODUCT_LINK_SELECTORS = [
    "a[href*='/products/']",        # Shopify product URL pattern
    "a[href*='.html']",             # BigCommerce / custom HTML
    ".productGrid a[href]",         # BigCommerce grid
    "h4.card-title a[href]",        # BigCommerce card
    ".product-item a.product-item__title[href]",
    ".product-item a.product-title[href]",
    ".product-item-info a[href]",
    ".product-name a[href]",
    ".woocommerce-loop-product__title a[href]",
    "li.product a[href]",
    ".grid-product a[href]",
    "[data-product-id] a[href]",
    ".search-result a[href]",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _first_product_link(soup: BeautifulSoup, base: str) -> str | None:
    for sel in PRODUCT_LINK_SELECTORS:
        for a in soup.select(sel):
            href = a.get("href", "")
            if not href or href == "#" or href.startswith("javascript"):
                continue
            if not href.startswith("http"):
                href = urllib.parse.urljoin(base.rstrip("/") + "/", href)
            # Skip if it looks like a category/search page, not a product page
            if any(skip in href for skip in ["/search", "/collections", "/category", "?q="]):
                continue
            return href
    return None


def _duckduckgo_links(query: str, domain: str, page, max_results: int = 3) -> list[str]:
    """Fallback: search DuckDuckGo HTML for product URLs on a specific domain."""
    encoded = urllib.parse.quote_plus(f"{query} site:{domain}")
    try:
        resp = page.goto(
            f"https://html.duckduckgo.com/html/?q={encoded}",
            wait_until="domcontentloaded",
            timeout=15000,
        )
        if not resp or resp.status != 200:
            return []
        html = page.content()
        soup = BeautifulSoup(html, "lxml")
        urls = []
        for a in soup.select("a.result__url, .result__a"):
            href = a.get("href", "")
            # DDG wraps links — extract real URL from uddg param
            if "duckduckgo.com/l/" in href:
                parsed = urllib.parse.urlparse(href)
                qs = urllib.parse.parse_qs(parsed.query)
                href = (qs.get("uddg") or [""])[0]
                href = urllib.parse.unquote(href)
            if href.startswith("http") and domain in href:
                urls.append(href)
            if len(urls) >= max_results:
                break
        return urls
    except Exception:
        return []


def _search_retailer(page, retailer: dict, query: str) -> list[str]:
    """Search a retailer and return up to 5 product page URLs."""
    encoded = urllib.parse.quote_plus(query)
    search_url = retailer["search"].format(query=encoded)
    try:
        resp = page.goto(search_url, wait_until="networkidle", timeout=30000)
        if not resp or resp.status not in (200, 301, 302):
            return []
        # Collect up to 5 product links from the search results page
        html = page.content()
        soup = BeautifulSoup(html, "lxml")
        found = []
        for sel in PRODUCT_LINK_SELECTORS:
            for a in soup.select(sel)[:5]:
                href = a.get("href", "")
                if not href or href == "#":
                    continue
                if not href.startswith("http"):
                    href = urllib.parse.urljoin(retailer["base"].rstrip("/") + "/", href)
                if any(skip in href for skip in ["/search", "?q=", "/collections/all"]):
                    continue
                if href not in found:
                    found.append(href)
                if len(found) >= 5:
                    break
            if found:
                break
        return found
    except Exception as e:
        print(f"      ! {retailer['name']}: {e.__class__.__name__}")
        return []


def discover_product(page, product: dict) -> list[dict]:
    """Find product page URLs across all retailers. Returns list of source dicts."""
    name = product["name"]
    query = product.get("search_query") or name
    sources = []

    for retailer in RETAILERS:
        print(f"    [{retailer['name']}] searching...", end="\r")
        urls = _search_retailer(page, retailer, query)

        # Fallback to DuckDuckGo if direct search found nothing
        if not urls:
            domain = urllib.parse.urlparse(retailer["base"]).netloc.lstrip("www.")
            urls = _duckduckgo_links(query, domain, page)

        for url in urls:
            sources.append({
                "url": url,
                "retailer": retailer["key"],
                "retailer_name": retailer["name"],
                "title": name,
                "image": None,
                "last_seen": now_iso(),
            })
        status = f"✓ {len(urls)} link(s)" if urls else "no results"
        print(f"    [{retailer['name']}] {status}          ")
        time.sleep(0.5)

    return sources


def load_sources(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"schema_version": "1.0", "updated_at": None, "products": {}}


def save_sources(path: Path, data: dict):
    data["updated_at"] = now_iso()
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n  Saved → {path}")


def main():
    parser = argparse.ArgumentParser(description="Discover product page URLs for price scraper")
    parser.add_argument("--ids", help="Comma-separated product IDs to process (default: all)")
    parser.add_argument("--refind", action="store_true", help="Re-discover even if sources already exist")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    repo_root  = script_dir.parent
    products_path = repo_root / "products.json"
    sources_path  = repo_root / "product_sources.json"

    with open(products_path) as f:
        catalog = json.load(f)

    products = catalog["products"]
    if args.ids:
        id_set = {int(i.strip()) for i in args.ids.split(",")}
        products = [p for p in products if p["id"] in id_set]

    sources_data = load_sources(sources_path)
    existing = sources_data.setdefault("products", {})

    total    = len(products)
    new_count = 0

    print(f"\nLawn Dominator — Link Discovery")
    print(f"Products to process: {total}")
    print(f"Retailers: {len(RETAILERS)}")
    print(f"Browser: {'headless' if args.headless else 'visible'}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=args.headless,
            args=["--no-sandbox"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        for i, product in enumerate(products, 1):
            pid  = str(product["id"])
            name = product["name"]

            # Skip if already discovered (unless --refind)
            if not args.refind and pid in existing and existing[pid]:
                print(f"[{i}/{total}] {name} — SKIPPED (already has {len(existing[pid])} source(s))")
                continue

            print(f"[{i}/{total}] {name}")
            sources = discover_product(page, product)

            if sources:
                existing[pid] = sources
                new_count += 1
                print(f"  → {len(sources)} total source(s) found")
            else:
                print(f"  → no sources found")

            # Save incrementally after each product
            save_sources(sources_path, sources_data)
            time.sleep(1.0)

        ctx.close()
        browser.close()

    # Summary
    total_sources = sum(len(v) for v in existing.values())
    products_with_sources = sum(1 for v in existing.values() if v)
    print(f"\n{'='*50}")
    print(f"Done. {products_with_sources}/{len(catalog['products'])} products have sources.")
    print(f"Total URLs saved: {total_sources}")
    print(f"File: {sources_path}")
    print(f"\nNext: commit product_sources.json and push to GitHub.")
    print(f"The scraper will use these direct URLs on every future run.")


if __name__ == "__main__":
    main()
