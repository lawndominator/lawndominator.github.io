#!/usr/bin/env python3
"""
Lawn Dominator — Link Discovery Tool
Uses DuckDuckGo plain-HTML search to find direct product page URLs.
No browser, no CAPTCHA — just HTTP requests.

Usage:
  python scraper/find_links.py               # discover all products
  python scraper/find_links.py --ids 1,2,3   # specific product IDs only
  python scraper/find_links.py --refind      # re-run even if sources exist

Requirements (already in requirements.txt):
  pip install requests beautifulsoup4 lxml
"""

import argparse
import json
import re
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

RETAILERS = [
    {"key": "domyown",               "name": "DoMyOwn",               "domain": "domyown.com"},
    {"key": "solutions",             "name": "Solutions Pest & Lawn",  "domain": "solutionspestcontrol.com"},
    {"key": "yard-mastery",          "name": "Yard Mastery",           "domain": "yardmastery.com"},
    {"key": "gci-turf",              "name": "GCI Turf Academy",       "domain": "gciturfacademy.com"},
    {"key": "lawn-synergy",          "name": "Lawn Synergy",           "domain": "lawnsynergy.com"},
    {"key": "pestrong",              "name": "Pestrong",               "domain": "pestrong.com"},
    {"key": "do-my-pest",            "name": "Do My Pest",             "domain": "domypest.com"},
    {"key": "pestmall",              "name": "PestMall",               "domain": "pestmall.com"},
    {"key": "forestry-distributing", "name": "Forestry Distributing",  "domain": "forestrydistributing.com"},
    {"key": "reinders",              "name": "Reinders",               "domain": "reinders.com"},
]

# Domains we never want as sources
BLOCKLIST = {
    "amazon.com", "walmart.com", "homedepot.com", "lowes.com", "ebay.com",
    "google.com", "bing.com", "duckduckgo.com", "youtube.com", "reddit.com",
    "pinterest.com", "facebook.com", "instagram.com",
}

DDG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _extract_ddg_urls(html: str, domain_filter: str = "") -> list[str]:
    """Pull real URLs out of a DuckDuckGo HTML results page."""
    soup = BeautifulSoup(html, "lxml")
    urls = []

    for a in soup.select("a.result__url, a.result__a"):
        href = a.get("href", "")

        # DDG wraps outbound links — decode uddg param
        if "duckduckgo.com/l/" in href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            href = urllib.parse.unquote((qs.get("uddg") or [""])[0])

        if not href.startswith("http"):
            continue

        parsed = urllib.parse.urlparse(href)
        host = parsed.netloc.lower().lstrip("www.")

        if any(blocked in host for blocked in BLOCKLIST):
            continue
        if domain_filter and domain_filter not in host:
            continue

        # Prefer product pages over category/search pages
        path = parsed.path.lower()
        if any(skip in path for skip in ["/search", "/category", "/collections/all"]):
            continue

        if href not in urls:
            urls.append(href)

    return urls


def ddg_search(query: str, domain: str = "", max_results: int = 5, delay: float = 1.5) -> list[str]:
    """Search DuckDuckGo HTML and return up to max_results URLs."""
    q = f'"{query}" site:{domain}' if domain else query
    params = urllib.parse.urlencode({"q": q})
    url = f"https://html.duckduckgo.com/html/?{params}"

    try:
        r = requests.get(url, headers=DDG_HEADERS, timeout=15)
        time.sleep(delay)  # be polite to DDG
        if r.status_code != 200:
            return []
        return _extract_ddg_urls(r.text, domain)[:max_results]
    except Exception as e:
        print(f"      DDG error: {e}")
        return []


def _base_query(product: dict) -> str:
    """Strip to the core product word — 'Prodiamine', 'Dimension', 'Tenacity', etc."""
    name = product["name"]
    # Drop parenthetical (e.g. "(Pendimethalin)"), formulation codes, percentages
    name = re.sub(r"\s*\([^)]*\)", "", name)
    name = re.sub(r"\s+\d[\d.]*\s*(wdg|wg|ec|sc|sl|df|g|l|ew|flo|plus|pro|gnl)\b.*", "", name, flags=re.I)
    name = re.sub(r"\s+\d[\d.]*(%|g|l)\b.*", "", name, flags=re.I)
    return name.strip()


def discover_product(product: dict) -> list[dict]:
    name  = product["name"]
    query = _base_query(product)
    sources = []
    seen_urls = set()

    print(f"  search term: \"{query}\"")

    # Per-retailer site-specific search
    for retailer in RETAILERS:
        urls = ddg_search(query, domain=retailer["domain"], max_results=3)
        for url in urls:
            if url not in seen_urls:
                seen_urls.add(url)
                sources.append({
                    "url": url,
                    "retailer": retailer["key"],
                    "retailer_name": retailer["name"],
                    "title": name,
                    "image": None,
                    "last_seen": now_iso(),
                })
        status = f"  {len(urls)} link(s)" if urls else "  –"
        print(f"    {retailer['name']:<28} {status}")

    # Broad search to catch any other specialty stores
    broad_query = f"{query} buy herbicide lawn specialty"
    broad_urls  = ddg_search(broad_query, domain="", max_results=10, delay=2.0)
    added = 0
    for url in broad_urls:
        if url not in seen_urls:
            seen_urls.add(url)
            host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.").split(".")[0]
            sources.append({
                "url": url,
                "retailer": re.sub(r"[^a-z0-9]+", "-", host),
                "retailer_name": host.replace("-", " ").title(),
                "title": name,
                "image": None,
                "last_seen": now_iso(),
            })
            added += 1
    if added:
        print(f"    Broad search                     +{added} more")

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids",    help="Comma-separated product IDs (default: all)")
    parser.add_argument("--refind", action="store_true", help="Re-discover even if sources exist")
    args = parser.parse_args()

    root          = Path(__file__).parent.parent
    products_path = root / "products.json"
    sources_path  = root / "product_sources.json"

    with open(products_path) as f:
        catalog = json.load(f)

    products = catalog["products"]
    if args.ids:
        id_set   = {int(i.strip()) for i in args.ids.split(",")}
        products = [p for p in products if p["id"] in id_set]

    sources_data = load_sources(sources_path)
    existing     = sources_data.setdefault("products", {})

    total = len(products)
    print(f"\nLawn Dominator — Link Discovery  ({total} products, {len(RETAILERS)} retailers)\n")

    for i, product in enumerate(products, 1):
        pid  = str(product["id"])
        name = product["name"]

        if not args.refind and pid in existing and existing[pid]:
            print(f"[{i}/{total}] {name} — skipped ({len(existing[pid])} sources already saved)")
            continue

        print(f"[{i}/{total}] {name}")
        sources = discover_product(product)
        existing[pid] = sources
        save_sources(sources_path, sources_data)

        total_found = len(sources)
        print(f"  → {total_found} URL(s) saved\n")

    # Final summary
    with_sources = sum(1 for v in existing.values() if v)
    total_urls   = sum(len(v) for v in existing.values())
    print(f"Done.  {with_sources}/{len(catalog['products'])} products have sources  ({total_urls} total URLs)")
    print(f"File:  {sources_path}")
    print(f"\nCommit and push product_sources.json, then the scraper will use direct URLs.")


if __name__ == "__main__":
    main()
