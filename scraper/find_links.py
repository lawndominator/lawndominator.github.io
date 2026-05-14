#!/usr/bin/env python3
"""
Lawn Dominator — Link Discovery Tool
Uses DuckDuckGo to find product URLs, then fetches each one to verify
a price exists and show you exactly what was found before saving.

Usage:
  python scraper/find_links.py               # discover + verify all products
  python scraper/find_links.py --ids 1,2,3   # specific product IDs only
  python scraper/find_links.py --refind      # redo even if sources exist
  python scraper/find_links.py --no-verify   # skip price-check (faster, blind)

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

BLOCKLIST = {
    "amazon.com", "walmart.com", "homedepot.com", "lowes.com", "ebay.com",
    "google.com", "bing.com", "duckduckgo.com", "youtube.com", "reddit.com",
    "pinterest.com", "facebook.com", "instagram.com",
}

HEADERS = {
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


# ── Price extraction (same logic as scraper.py) ───────────────────────────────

def _parse_price(text: str):
    text = text.replace(",", "")
    m = re.search(r"(?:\$|USD\s*)\s*(\d+(?:\.\d{1,2})?)", text, re.I)
    if not m:
        m = re.search(r"\b(\d+\.\d{2})\b", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def _extract_price_and_title(html: str, base_url: str):
    """Return (price, page_title) or (None, page_title) from a product page."""
    soup = BeautifulSoup(html, "lxml")
    page_title = soup.title.string.strip() if soup.title and soup.title.string else ""

    # 1. JSON-LD (most reliable)
    for script in soup.select("script[type='application/ld+json']"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue
        for obj in ([data] if isinstance(data, dict) else data if isinstance(data, list) else []):
            if str(obj.get("@type", "")).lower() != "product":
                continue
            offers = obj.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict):
                price = _parse_price(str(offers.get("price") or offers.get("lowPrice") or ""))
                if price:
                    return price, page_title

    # 2. CSS selectors
    price_selectors = [
        "[class*='sale-price']", "[class*='price--sale']", ".price--withoutTax",
        "[itemprop='price']", "[data-price]", "[class*='price']",
        "meta[itemprop='price']", "meta[property='product:price:amount']",
    ]
    for sel in price_selectors:
        elem = soup.select_one(sel)
        if not elem:
            continue
        raw = elem.get("content") or elem.get("data-price") or elem.get_text(" ", strip=True)
        price = _parse_price(raw)
        if price and price >= 5:
            return price, page_title

    return None, page_title


def verify_url(url: str):
    """Fetch a product page and return (price, page_title, ok)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}", False
        price, title = _extract_price_and_title(r.text, url)
        return price, title, price is not None
    except Exception as e:
        return None, str(e)[:60], False


# ── DuckDuckGo search ─────────────────────────────────────────────────────────

def _extract_ddg_urls(html: str, domain_filter: str = "") -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    urls = []
    for a in soup.select("a.result__url, a.result__a"):
        href = a.get("href", "")
        if "duckduckgo.com/l/" in href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            href = urllib.parse.unquote((qs.get("uddg") or [""])[0])
        if not href.startswith("http"):
            continue
        host = urllib.parse.urlparse(href).netloc.lower().lstrip("www.")
        if any(b in host for b in BLOCKLIST):
            continue
        if domain_filter and domain_filter not in host:
            continue
        path = urllib.parse.urlparse(href).path.lower()
        if any(s in path for s in ["/search", "/category", "/collections/all"]):
            continue
        if href not in urls:
            urls.append(href)
    return urls


def ddg_search(query: str, domain: str = "", max_results: int = 3) -> list[str]:
    q = f'"{query}" site:{domain}' if domain else query
    url = f"https://html.duckduckgo.com/html/?{urllib.parse.urlencode({'q': q})}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        time.sleep(1.5)
        if r.status_code != 200:
            return []
        return _extract_ddg_urls(r.text, domain)[:max_results]
    except Exception:
        return []


def _base_query(product: dict) -> str:
    name = product["name"]
    name = re.sub(r"\s*\([^)]*\)", "", name)
    name = re.sub(r"\s+\d[\d.]*\s*(wdg|wg|ec|sc|sl|df|g|l|ew|flo|plus|pro|gnl)\b.*", "", name, flags=re.I)
    name = re.sub(r"\s+\d[\d.]*(%|g|l)\b.*", "", name, flags=re.I)
    return name.strip()


# ── Discovery ─────────────────────────────────────────────────────────────────

def discover_product(product: dict, do_verify: bool = True) -> list[dict]:
    name  = product["name"]
    query = _base_query(product)
    sources = []
    seen_urls = set()

    print(f'  searching: "{query}"')

    for retailer in RETAILERS:
        urls = ddg_search(query, domain=retailer["domain"])
        if not urls:
            print(f"    {retailer['name']:<28} –")
            continue

        for url in urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)

            if do_verify:
                price, title, ok = verify_url(url)
                short_url = url.replace("https://", "").replace("www.", "")
                if ok:
                    print(f"    {retailer['name']:<28} ✓  ${price:<8.2f}  {title[:50]}")
                    print(f"    {'':28}    {short_url[:70]}")
                else:
                    print(f"    {retailer['name']:<28} ✗  no price  {title[:40]}")
                    print(f"    {'':28}    {short_url[:70]}")
            else:
                ok = True
                price = None
                title = name
                print(f"    {retailer['name']:<28} {url[:60]}")

            sources.append({
                "url": url,
                "retailer": retailer["key"],
                "retailer_name": retailer["name"],
                "title": title or name,
                "price_verified": price,
                "verified": ok,
                "image": None,
                "last_seen": now_iso(),
            })

    # Broad DDG search for any retailer not in our list
    broad = ddg_search(f"{query} buy lawn specialty", max_results=8)
    added = 0
    for url in broad:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.").split(".")[0]

        if do_verify:
            price, title, ok = verify_url(url)
            if not ok:
                continue
            print(f"    {'(broad) ' + host:<28} ✓  ${price:<8.2f}  {title[:50]}")
        else:
            price, title, ok = None, name, True

        sources.append({
            "url": url,
            "retailer": re.sub(r"[^a-z0-9]+", "-", host),
            "retailer_name": host.replace("-", " ").title(),
            "title": title or name,
            "price_verified": price,
            "verified": ok,
            "image": None,
            "last_seen": now_iso(),
        })
        added += 1

    verified = sum(1 for s in sources if s.get("verified"))
    print(f"  → {verified} verified source(s), {len(sources)} total\n")
    return sources


# ── File I/O ──────────────────────────────────────────────────────────────────

def load_sources(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"schema_version": "1.0", "updated_at": None, "products": {}}


def save_sources(path: Path, data: dict):
    data["updated_at"] = now_iso()
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids",       help="Comma-separated product IDs (default: all)")
    parser.add_argument("--refind",    action="store_true", help="Re-discover even if sources exist")
    parser.add_argument("--no-verify", action="store_true", help="Skip price verification (faster)")
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
    do_verify    = not args.no_verify

    total = len(products)
    print(f"\nLawn Dominator — Link Discovery  ({total} products)")
    print(f"Verification: {'ON — will show price + title for each link' if do_verify else 'OFF'}\n")

    for i, product in enumerate(products, 1):
        pid  = str(product["id"])
        name = product["name"]

        if not args.refind and pid in existing and existing[pid]:
            print(f"[{i}/{total}] {name} — skipped ({len(existing[pid])} sources already saved)")
            continue

        print(f"[{i}/{total}] {name}")
        sources = discover_product(product, do_verify=do_verify)
        existing[pid] = sources
        save_sources(sources_path, sources_data)

    with_sources = sum(1 for v in existing.values() if v)
    total_urls   = sum(len(v) for v in existing.values())
    verified     = sum(1 for v in existing.values() for s in v if s.get("verified"))
    print(f"{'='*60}")
    print(f"Done.  {with_sources}/{len(catalog['products'])} products have sources")
    print(f"       {verified} verified (price found)  /  {total_urls} total URLs")
    print(f"File:  {sources_path}")
    print(f"\nNext: git add product_sources.json && git commit -m 'feat: product sources' && git push")


if __name__ == "__main__":
    main()
