#!/usr/bin/env python3
"""
Lawn Dominator — Link Discovery Tool
Searches specialty retailers directly. Specialty Shopify stores work with plain
requests. DoMyOwn blocks bots, so it connects to YOUR already-open Chrome so it
inherits your session/cookies and skips any CAPTCHA.

Usage:
  python scraper/find_links.py               # discover all products
  python scraper/find_links.py --ids 1,2,3   # specific product IDs
  python scraper/find_links.py --reset       # wipe product_sources.json and start over
  python scraper/find_links.py --refind      # re-discover even if sources exist
  python scraper/find_links.py --no-domyown  # skip DoMyOwn (if Chrome step is inconvenient)

For DoMyOwn, the tool will prompt you to relaunch Chrome with remote debugging
enabled (one-time setup). After that it connects silently.

Requirements: pip install requests beautifulsoup4 lxml playwright
              playwright install chromium
"""

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# ── Retailers (plain HTTP requests work from a home IP) ───────────────────────
RETAILERS = [
    {
        "key":    "gci-turf",
        "name":   "GCI Turf Academy",
        "base":   "https://gciturfacademy.com",
        "search": "https://gciturfacademy.com/search?q={query}&type=product",
    },
    {
        "key":    "yard-mastery",
        "name":   "Yard Mastery",
        "base":   "https://yardmastery.com",
        "search": "https://yardmastery.com/search?q={query}&type=product",
    },
    {
        "key":    "lawn-synergy",
        "name":   "Lawn Synergy",
        "base":   "https://lawnsynergy.com",
        "search": "https://lawnsynergy.com/search?q={query}&type=product",
    },
    {
        "key":    "pestrong",
        "name":   "Pestrong",
        "base":   "https://pestrong.com",
        "search": "https://pestrong.com/?s={query}&post_type=product",
    },
]

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


def _base_query(product: dict) -> str:
    """Strip to the base product word: 'Prodiamine', 'Dimension', 'Tenacity'."""
    name = product["name"]
    name = re.sub(r"\s*\([^)]*\)", "", name)
    name = re.sub(r"\s+\d[\d.]*\s*(wdg|wg|ec|sc|sl|df|g|l|ew|flo|plus|pro|gnl)\b.*", "", name, flags=re.I)
    name = re.sub(r"\s+\d[\d.]*(%|g|l)\b.*", "", name, flags=re.I)
    return name.strip()


# ── Price extraction ──────────────────────────────────────────────────────────

def _parse_price(text: str):
    text = str(text).replace(",", "")
    m = re.search(r"(?:\$|USD\s*)\s*(\d+(?:\.\d{1,2})?)", text, re.I)
    if not m:
        m = re.search(r"\b(\d+\.\d{2})\b", text)
    if m:
        try:
            v = float(m.group(1))
            return v if v >= 5 else None
        except ValueError:
            pass
    return None


def _get_price_and_title(html: str):
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""

    # JSON-LD first
    for script in soup.select("script[type='application/ld+json']"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if str(obj.get("@type", "")).lower() != "product":
                continue
            offers = obj.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict):
                price = _parse_price(offers.get("price") or offers.get("lowPrice") or "")
                if price:
                    return price, title

    # CSS fallback
    for sel in ["[itemprop='price']", "[data-price]", ".price--withoutTax",
                "[class*='sale-price']", "[class*='price']"]:
        el = soup.select_one(sel)
        if not el:
            continue
        raw = el.get("content") or el.get("data-price") or el.get_text(" ", strip=True)
        price = _parse_price(raw)
        if price:
            return price, title

    return None, title


def _title_matches(title: str, base_query: str) -> bool:
    """Check that the page is actually about this product, not a random result."""
    words = [w.lower() for w in base_query.split() if len(w) > 3]
    title_lower = title.lower()
    return any(w in title_lower for w in words)


# ── Retailer search ───────────────────────────────────────────────────────────

def _product_links(soup: BeautifulSoup, base: str, limit: int = 5) -> list[str]:
    """Extract unique product page URLs from search result cards only (not nav)."""
    seen, links = set(), []

    # Target actual search result cards — Shopify uses these containers.
    # Skipping nav/header links which pollute results with unrelated products.
    card_selectors = [
        ".card-product a[href*='/products/']",
        ".product-item a[href*='/products/']",
        ".grid__item a[href*='/products/']",
        ".product-card a[href*='/products/']",
        ".productGrid a[href*='/products/']",
        "[data-product-id] a[href*='/products/']",
        # WooCommerce
        "ul.products li.product a[href]",
        ".woocommerce-loop-product__title[href]",
    ]

    candidates = []
    for sel in card_selectors:
        candidates = soup.select(sel)
        if candidates:
            break

    # Last resort: any /products/ link that isn't inside a nav/header element
    if not candidates:
        for a in soup.find_all("a", href=True):
            if "/products/" not in a["href"]:
                continue
            if a.find_parent(["nav", "header"]):
                continue
            if a.find_parent(class_=re.compile(r"nav|header|menu|site-nav", re.I)):
                continue
            candidates.append(a)

    for a in candidates:
        href = a.get("href", "")
        if not href:
            continue
        slug = href.split("/products/")[-1].split("?")[0].strip("/")
        if len(slug) < 3:
            continue
        if href.startswith("/"):
            href = base.rstrip("/") + href
        href = href.split("?")[0]
        if href not in seen:
            seen.add(href)
            links.append(href)
        if len(links) >= limit:
            break
    return links


def search_retailer(retailer: dict, query: str) -> list[str]:
    encoded = urllib.parse.quote_plus(query)
    url = retailer["search"].format(query=encoded)
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "lxml")
        return _product_links(soup, retailer["base"])
    except Exception:
        return []


# ── Verify a product URL ──────────────────────────────────────────────────────

def verify(url: str, base_query: str):
    """
    Fetch url, extract price and title.
    Returns (price, title, ok) where ok means price found AND title matches product.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}", False
        price, title = _get_price_and_title(r.text)
        matches = _title_matches(title, base_query)
        ok = price is not None and matches
        return price, title, ok
    except Exception as e:
        return None, str(e)[:50], False


# ── DoMyOwn via a single persistent Playwright browser ────────────────────────

def setup_domyown_browser():
    """
    Launch one visible browser window, open DoMyOwn, wait for you to confirm
    the page loaded (solve any CAPTCHA if shown). Returns the browser context
    which is reused for all 66 product searches — no new CAPTCHA per search.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  playwright not installed — skipping DoMyOwn.")
        print("  Run: pip install playwright && playwright install chromium")
        return None, None, None

    print("\n  Opening browser for DoMyOwn...")
    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=False,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
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
    # Remove webdriver flag that triggers bot detection
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page.goto("https://www.domyown.com", wait_until="networkidle", timeout=30000)

    print("  Browser open. If you see a CAPTCHA, solve it now.")
    input("  Press Enter when you can see DoMyOwn products normally... ")
    page.close()

    return pw, browser, ctx


def search_domyown(query: str, ctx) -> list[str]:
    """Search DoMyOwn reusing the existing browser context (no new CAPTCHA)."""
    if ctx is None:
        return []
    try:
        page = ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        encoded = urllib.parse.quote_plus(query)
        page.goto(f"https://www.domyown.com/search?q={encoded}", wait_until="networkidle", timeout=20000)
        html = page.content()
        page.close()
        soup = BeautifulSoup(html, "lxml")
        return _product_links(soup, "https://www.domyown.com")
    except Exception as e:
        print(f"    DoMyOwn error: {e.__class__.__name__}: {str(e)[:60]}")
        return []


# ── Discover one product ──────────────────────────────────────────────────────

def discover_product(product: dict, domyown_ctx=None) -> list[dict]:
    name  = product["name"]
    query = _base_query(product)
    sources = []

    print(f'  query: "{query}"')

    # DoMyOwn via persistent browser context
    if domyown_ctx is not None:
        urls = search_domyown(query, domyown_ctx)
        for url in urls:
            price, title, ok = verify(url, query)
            short = url.replace("https://", "").replace("www.", "")
            if ok:
                print(f"    {'DoMyOwn':<24} ✓  ${price:<7.2f}  {title[:45]}")
                print(f"    {'':24}    {short[:65]}")
                sources.append({
                    "url":           url,
                    "retailer":      "domyown",
                    "retailer_name": "DoMyOwn",
                    "title":         title,
                    "price_verified": price,
                    "verified":      True,
                    "image":         None,
                    "last_seen":     now_iso(),
                })
            else:
                reason = "wrong product" if price else "no price"
                print(f"    {'DoMyOwn':<24} ✗  ({reason})  {title[:40]}")
            time.sleep(0.3)
        if not urls:
            print(f"    {'DoMyOwn':<24} –")

    for retailer in RETAILERS:
        urls = search_retailer(retailer, query)
        if not urls:
            print(f"    {retailer['name']:<24} –")
            continue

        for url in urls:
            price, title, ok = verify(url, query)
            short = url.replace("https://", "").replace("www.", "")

            if ok:
                print(f"    {retailer['name']:<24} ✓  ${price:<7.2f}  {title[:45]}")
                print(f"    {'':24}    {short[:65]}")
                sources.append({
                    "url":          url,
                    "retailer":     retailer["key"],
                    "retailer_name": retailer["name"],
                    "title":        title,
                    "price_verified": price,
                    "verified":     True,
                    "image":        None,
                    "last_seen":    now_iso(),
                })
            else:
                reason = "wrong product" if price else "no price"
                print(f"    {retailer['name']:<24} ✗  ({reason})  {title[:40]}")
            time.sleep(0.3)

    return sources


# ── File helpers ──────────────────────────────────────────────────────────────

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
    parser.add_argument("--ids",        help="Comma-separated product IDs")
    parser.add_argument("--reset",      action="store_true", help="Clear product_sources.json and start fresh")
    parser.add_argument("--refind",     action="store_true", help="Re-discover even if verified sources exist")
    parser.add_argument("--no-domyown", action="store_true", help="Skip DoMyOwn (skip Chrome setup)")
    args = parser.parse_args()

    root          = Path(__file__).parent.parent
    products_path = root / "products.json"
    sources_path  = root / "product_sources.json"

    if args.reset and sources_path.exists():
        sources_path.unlink()
        print("Reset: product_sources.json deleted.\n")

    with open(products_path) as f:
        catalog = json.load(f)

    products = catalog["products"]
    if args.ids:
        id_set   = {int(i.strip()) for i in args.ids.split(",")}
        products = [p for p in products if p["id"] in id_set]

    sources_data = load_sources(sources_path)
    existing     = sources_data.setdefault("products", {})
    total        = len(products)

    # Set up DoMyOwn browser (one window, one CAPTCHA solve if needed)
    domyown_ctx = None
    if not args.no_domyown:
        pw, browser, domyown_ctx = setup_domyown_browser()

    retailers_count = len(RETAILERS) + (1 if domyown_ctx else 0)
    print(f"Lawn Dominator — Link Discovery  ({total} products, {retailers_count} retailers)\n")

    for i, product in enumerate(products, 1):
        pid  = str(product["id"])
        name = product["name"]

        # Only skip if we already have at least one VERIFIED source
        already_verified = sum(1 for s in existing.get(pid, []) if s.get("verified"))
        if not args.refind and already_verified > 0:
            print(f"[{i}/{total}] {name} — skipped ({already_verified} verified)")
            continue

        print(f"[{i}/{total}] {name}")
        sources = discover_product(product, domyown_ctx=domyown_ctx)
        existing[pid] = sources
        save_sources(sources_path, sources_data)

        print(f"  → {len(sources)} verified source(s) saved\n")

    # Summary
    with_sources = sum(1 for v in existing.values() if any(s.get("verified") for s in v))
    total_urls   = sum(len(v) for v in existing.values())
    print(f"{'='*55}")
    print(f"Done.  {with_sources}/{len(catalog['products'])} products have verified sources")
    print(f"       {total_urls} total URLs in {sources_path.name}")
    print(f"\nNext step:")
    print(f"  git add product_sources.json")
    print(f"  git commit -m 'feat: product sources'")
    print(f"  git push")


if __name__ == "__main__":
    main()
