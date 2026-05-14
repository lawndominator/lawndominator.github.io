#!/usr/bin/env python3
"""
Lawn Dominator — Link Discovery Tool
Searches specialty retailers directly. Specialty Shopify stores work with plain
requests. DoMyOwn blocks bots, so Playwright launches a visible browser window —
solve the CAPTCHA once and the same session is reused for all products.

Usage:
  python scraper/find_links.py               # discover all products
  python scraper/find_links.py --ids 1,2,3   # specific product IDs
  python scraper/find_links.py --reset       # wipe product_sources.json and start over
  python scraper/find_links.py --refind      # re-discover even if sources exist
  python scraper/find_links.py --no-domyown  # skip DoMyOwn
  python scraper/find_links.py --debug-domyown --ids 1

Requirements: pip install requests beautifulsoup4 lxml playwright
              playwright install chromium
"""

import argparse
import json
import os
import re
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

DOMYOWN_PRODUCT_RE = re.compile(r"https?://(?:www\.)?domyown\.com/[^\"'<>\s]+-p-\d+\.html", re.I)


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

def verify_browser(ctx, url: str, base_query: str):
    """Verify a URL in the visible browser session, useful for WAF-protected sites."""
    page = None
    try:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(1200)
        html = page.content()
        price, title = _get_price_and_title(html)
        title = title or page.title()
        return price, title, price is not None and _title_matches(title, base_query)
    except Exception as e:
        return None, str(e)[:50], False
    finally:
        if page:
            page.close()


def _domyown_product_links(soup: BeautifulSoup, limit: int = 5) -> list[str]:
    """Extract DoMyOwn product URLs — format is /slug-p-12345.html, not /products/."""
    seen, links = set(), []
    pattern = re.compile(r"-p-\d+\.html$", re.I)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not pattern.search(href):
            continue
        if a.find_parent(["nav", "header"]):
            continue
        if a.find_parent(class_=re.compile(r"nav|header|menu", re.I)):
            continue
        if href.startswith("/"):
            href = "https://www.domyown.com" + href
        href = href.split("?")[0]
        if href not in seen:
            seen.add(href)
            links.append(href)
        if len(links) >= limit:
            break
    return links


def _domyown_links_from_text(text: str, limit: int = 5) -> list[str]:
    seen, links = set(), []
    for match in DOMYOWN_PRODUCT_RE.finditer(text):
        url = match.group(0).split("?")[0]
        if url not in seen:
            seen.add(url)
            links.append(url)
        if len(links) >= limit:
            break
    return links


def search_domyown_web(query: str, ctx, limit: int = 5) -> list[str]:
    """Fallback to public search results for DoMyOwn product pages."""
    page = None
    try:
        page = ctx.new_page()
        encoded = urllib.parse.quote_plus(f'site:domyown.com "{query}"')
        page.goto(f"https://www.bing.com/search?q={encoded}", wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(1500)
        html = page.content()
        links = _domyown_links_from_text(html, limit=limit)
        if links:
            return links

        soup = BeautifulSoup(html, "lxml")
        candidates = []
        for a in soup.select("a[href*='domyown.com/']"):
            href = a.get("href", "").split("?")[0]
            if re.search(r"-p-\d+\.html$", href, re.I):
                candidates.append(href)
        return list(dict.fromkeys(candidates))[:limit]
    except Exception as e:
        print(f"    DoMyOwn web-search error: {e.__class__.__name__}: {str(e)[:60]}")
        return []
    finally:
        if page:
            page.close()


def search_domyown(query: str, ctx) -> list[str]:
    """Search DoMyOwn reusing the existing browser context (no new CAPTCHA)."""
    if ctx is None:
        return []
    encoded = urllib.parse.quote_plus(query)
    search_urls = [
        f"https://www.domyown.com/search?w={encoded}",
        f"https://www.domyown.com/search?q={encoded}",
        f"https://www.domyown.com/search?searchterm={encoded}",
    ]
    for search_url in search_urls:
        try:
            page = ctx.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page.goto(search_url, wait_until="networkidle", timeout=20000)
            html = page.content()
            final_url = page.url
            page.close()
            soup = BeautifulSoup(html, "lxml")
            title = (soup.title.string or "").strip() if soup.title else ""
            # Detect home page redirect
            if "do it yourself" in title.lower() or "pest control products" in title.lower() or final_url == "https://www.domyown.com/":
                print(f"    DoMyOwn: {search_url.split('?')[1]} → home page redirect, trying next")
                continue
            links = _domyown_product_links(soup)
            print(f"    DoMyOwn: {search_url.split('?')[1]} → \"{title[:50]}\" ({len(links)} links)")
            if links:
                return links
        except Exception as e:
            print(f"    DoMyOwn error: {e.__class__.__name__}: {str(e)[:60]}")
    print("    DoMyOwn: site search found no product links, trying Bing site search")
    return search_domyown_web(query, ctx)


# ── Discover one product ──────────────────────────────────────────────────────

def discover_product(product: dict, domyown_ctx=None) -> list[dict]:
    name  = product["name"]
    query = _base_query(product)
    sources = []

    print(f'  query: "{query}"')

    # DoMyOwn via persistent browser context
    if domyown_ctx is not None:
        urls = search_domyown(query, domyown_ctx)
        found = False
        for url in urls:
            price, title, ok = verify_browser(domyown_ctx, url, query)
            if ok:
                short = url.replace("https://", "").replace("www.", "")
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
                found = True
            time.sleep(0.3)
        if not found:
            print(f"    {'DoMyOwn':<24} –")

    for retailer in RETAILERS:
        urls = search_retailer(retailer, query)
        found = False
        for url in urls:
            price, title, ok = verify(url, query)
            if ok:
                short = url.replace("https://", "").replace("www.", "")
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
                found = True
            time.sleep(0.3)
        if not found:
            print(f"    {retailer['name']:<24} –")

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

def find_brave_executable() -> str | None:
    candidates = [
        os.environ.get("BRAVE_PATH", ""),
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        str(Path.home() / r"AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def launch_browser_context(pw, root: Path, profile_dir: str):
    common = {
        "user_data_dir": str(root / profile_dir),
        "headless": False,
        "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1280, "height": 900},
    }
    brave = find_brave_executable()
    if brave:
        print(f"Using Brave: {brave}")
        return pw.chromium.launch_persistent_context(executable_path=brave, **common)

    print("Brave not found. Falling back to Playwright Chromium.")
    return pw.chromium.launch_persistent_context(**common)


def _run_discovery(products, catalog, existing, sources_path, sources_data, domyown_ctx):
    total = len(products)
    retailers_count = len(RETAILERS) + (1 if domyown_ctx else 0)
    print(f"Lawn Dominator — Link Discovery  ({total} products, {retailers_count} retailers)\n")

    for i, product in enumerate(products, 1):
        pid  = str(product["id"])
        name = product["name"]

        already_verified = sum(1 for s in existing.get(pid, []) if s.get("verified"))
        if already_verified > 0:
            print(f"[{i}/{total}] {name} — skipped ({already_verified} verified)")
            continue

        print(f"[{i}/{total}] {name}")
        sources = discover_product(product, domyown_ctx=domyown_ctx)
        existing[pid] = sources
        save_sources(sources_path, sources_data)
        print(f"  → {len(sources)} verified source(s) saved\n")

    with_sources = sum(1 for v in existing.values() if any(s.get("verified") for s in v))
    total_urls   = sum(len(v) for v in existing.values())
    print(f"{'='*55}")
    print(f"Done.  {with_sources}/{len(catalog['products'])} products have verified sources")
    print(f"       {total_urls} total URLs in {sources_path.name}")
    print(f"\nNext step:")
    print(f"  git add product_sources.json")
    print(f"  git commit -m 'feat: product sources'")
    print(f"  git push")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids",        help="Comma-separated product IDs")
    parser.add_argument("--reset",      action="store_true", help="Clear product_sources.json and start fresh")
    parser.add_argument("--refind",     action="store_true", help="Re-discover even if verified sources exist")
    parser.add_argument("--no-domyown", action="store_true", help="Skip DoMyOwn (skip Chrome setup)")
    parser.add_argument("--debug-domyown", action="store_true", help="Accepted for compatibility; DoMyOwn search logging is always enabled")
    parser.add_argument("--profile-dir", default="scraper/browser-profile", help="Persistent browser profile dir for solved DoMyOwn challenges")
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

    if args.refind:
        # Clear verified flag so _run_discovery won't skip anything
        sources_data = {"schema_version": "1.0", "updated_at": None, "products": {}}
    else:
        sources_data = load_sources(sources_path)
    existing = sources_data.setdefault("products", {})

    if args.no_domyown:
        _run_discovery(products, catalog, existing, sources_path, sources_data, domyown_ctx=None)
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed — skipping DoMyOwn.")
        print("Run: pip install playwright && playwright install chromium")
        _run_discovery(products, catalog, existing, sources_path, sources_data, domyown_ctx=None)
        return

    print("\nOpening browser for DoMyOwn...")
    with sync_playwright() as pw:
        ctx = launch_browser_context(pw, root, args.profile_dir)
        page = ctx.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page.goto("https://www.domyown.com", wait_until="networkidle", timeout=30000)
        print("Browser open. If you see a CAPTCHA, solve it now.")
        input("Press Enter when DoMyOwn products are visible... ")
        page.close()

        _run_discovery(products, catalog, existing, sources_path, sources_data, domyown_ctx=ctx)
        ctx.close()


if __name__ == "__main__":
    main()
