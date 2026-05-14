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
        "key":    "solutions",
        "name":   "Solutions Pest & Lawn",
        "base":   "https://www.solutionsstores.com",
        "search": "https://www.solutionsstores.com/search?q={query}",
    },
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
    {
        "key":    "keystone-pest-solutions",
        "name":   "Keystone Pest Solutions",
        "base":   "https://www.keystonepestsolutions.com",
        "search": "https://www.keystonepestsolutions.com/index.php?keyword={query}&main_page=advanced_search_result",
    },
    {
        "key":    "diypestwarehouse",
        "name":   "DIY Pest Warehouse",
        "base":   "https://www.diypestwarehouse.com",
        "search": "https://www.diypestwarehouse.com/search?q={query}&type=product",
    },
    {
        "key":    "seed-world",
        "name":   "Seed World",
        "base":   "https://www.seedworldusa.com",
        "search": "https://www.seedworldusa.com/search?q={query}",
    },
    {
        "key":    "seed-barn",
        "name":   "Seed Barn",
        "base":   "https://seedbarn.com",
        "search": "https://seedbarn.com/search?q={query}",
    },
    {
        "key":    "reinders",
        "name":   "Reinders",
        "base":   "https://www.reinders.com",
        "search": "https://www.reinders.com/search?query={query}",
    },
    {
        "key":    "sunspot-supply",
        "name":   "Sunspot Supply",
        "base":   "https://www.sunspotsupply.com",
        "search": "https://www.sunspotsupply.com/search?q={query}",
    },
    {
        "key":    "lawn-care-nut",
        "name":   "Lawn Care Nut",
        "base":   "https://thelawncarenut.com",
        "search": "https://thelawncarenut.com/search?q={query}&type=product",
    },
    {
        "key":    "walmart",
        "name":   "Walmart",
        "base":   "https://www.walmart.com",
        "search": "https://www.walmart.com/search?q={query}",
        "marketplace": True,
    },
    {
        "key":    "amazon",
        "name":   "Amazon",
        "base":   "https://www.amazon.com",
        "search": "https://www.amazon.com/s?k={query}&tag=lawndominator-20",
        "marketplace": True,
    },
    {
        "key":    "ebay",
        "name":   "eBay",
        "base":   "https://www.ebay.com",
        "search": "https://www.ebay.com/sch/i.html?_nkw={query}",
        "marketplace": True,
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
DOMYOWN_HINTS = {
    "prodiamine": [
        "https://www.domyown.com/prodiamine-65-wdg-generic-barricade-p-2495.html",
        "https://www.domyown.com/barricade-65-wg-herbicide-p-1498.html",
    ],
}
_DOMYOWN_SPECIAL_LINKS: list[str] | None = None


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _base_query(product: dict) -> str:
    """Strip to the base product word: 'Prodiamine', 'Dimension', 'Tenacity'."""
    name = product["name"]
    name = re.sub(r"\s*\([^)]*\)", "", name)
    name = re.sub(r"\s+\d[\d.]*\s*(wdg|wg|ec|sc|sl|df|g|l|ew|flo|plus|pro|gnl)\b.*", "", name, flags=re.I)
    name = re.sub(r"\s+\d[\d.]*(%|g|l)\b.*", "", name, flags=re.I)
    return name.strip()


def _split_active_ingredients(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"\s*(?:\+|/|,| and )\s*", value, flags=re.I)
    return [p.strip() for p in parts if len(p.strip()) > 3]


def _product_queries(product: dict) -> list[str]:
    """Search brand names, generic active ingredients, and known alternate names."""
    candidates = [
        product.get("search_query", ""),
        product.get("name", ""),
        _base_query(product),
        product.get("active_ingredient", ""),
        *_split_active_ingredients(product.get("active_ingredient", "")),
        *product.get("alt_names", []),
        product.get("amazon_query", ""),
    ]
    seen, queries = set(), []
    for candidate in candidates:
        candidate = re.sub(r"\s+", " ", str(candidate)).strip()
        if not candidate:
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(candidate)
    return queries[:10]


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


FORMULATION_ALIASES = {
    "65wdg": ["65wdg", "65 wdg", "65wg", "65 wg"],
    "65wg": ["65wg", "65 wg", "65wdg", "65 wdg"],
    "75df": ["75df", "75 df"],
    "60df": ["60df", "60 df"],
    "50wdg": ["50wdg", "50 wdg"],
    "20ew": ["20ew", "20 ew"],
    "2ew": ["2ew", "2 ew"],
    "2sc": ["2sc", "2 sc"],
    "4l": ["4l", "4 l"],
    "4fl": ["4fl", "4 fl"],
    "g": ["granular", "granule", "0.2g", "0.5g", "2g", "6.2g"],
}

FORMULATION_RE = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*(?:wdg|wg|df|ew|sc|sl|ec|fl|l|g)|"
    r"wdg|wg|df|ew|sc|sl|ec|flo|granular|granule)\b",
    re.I,
)


def _tokens(text: str) -> set[str]:
    original = text.lower()
    compact = re.sub(r"[^a-z0-9]+", " ", text.lower())
    joined = compact.replace(" ", "")
    tokens = set(compact.split())
    tokens.add(joined)
    for m in re.finditer(r"\b(\d+(?:\.\d+)?)\s*([a-z]+)\b", original):
        tokens.add((m.group(1) + m.group(2)).replace(".", ""))
    return tokens


def _required_formulations(product: dict) -> list[str]:
    values = [product.get("name", ""), product.get("search_query", "")]
    found = []
    for value in values:
        for match in FORMULATION_RE.findall(value):
            token = re.sub(r"\s+", "", match.lower())
            if token and token not in found:
                found.append(token)
    return found


def _has_required_formulation(product: dict, title: str, url: str) -> bool:
    required = _required_formulations(product)
    if not required:
        return True
    haystack = f"{title} {url}"
    title_tokens = _tokens(haystack)
    for token in required:
        aliases = FORMULATION_ALIASES.get(token, [token])
        alias_tokens = {re.sub(r"[^a-z0-9]+", "", a.lower()) for a in aliases}
        if title_tokens & alias_tokens:
            return True
    return False


def _matches_product(product: dict, title: str, url: str = "", query: str = "") -> bool:
    if not _title_matches(title, query or product.get("search_query", "")):
        return False
    return _has_required_formulation(product, title, url)


# ── Retailer search ───────────────────────────────────────────────────────────

def _normalize_product_url(href: str, base: str, retailer_key: str) -> str | None:
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None

    href = urllib.parse.urljoin(base.rstrip("/") + "/", href)
    parsed = urllib.parse.urlparse(href)
    base_host = urllib.parse.urlparse(base).netloc.lower().removeprefix("www.")
    host = parsed.netloc.lower().removeprefix("www.")
    if host != base_host:
        return None

    path = parsed.path
    lower_path = path.lower()

    if retailer_key == "amazon":
        if "/sspa/" in lower_path:
            target = urllib.parse.parse_qs(parsed.query).get("url", [""])[0]
            if target:
                return _normalize_product_url(target, base, retailer_key)
        match = re.search(r"/(?:[^/]+/)?dp/([A-Z0-9]{10})", path, re.I)
        if not match:
            return None
        return f"https://www.amazon.com/dp/{match.group(1)}?tag=lawndominator-20"

    if retailer_key == "ebay":
        match = re.search(r"/itm/(?:[^/]+/)?(\d+)", path, re.I)
        if not match:
            return None
        return f"https://www.ebay.com/itm/{match.group(1)}"

    if retailer_key == "walmart":
        if "/ip/" not in lower_path:
            return None
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

    product_patterns = [
        r"/products/[^/?#]+",
        r"/product/[^/?#]+",
        r"/[^/?#]+-p-\d+\.html",
        r"/[^/?#]+/p/\d+",
    ]
    if not any(re.search(pattern, lower_path, re.I) for pattern in product_patterns):
        return None

    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", ""))


def _product_links(soup: BeautifulSoup, base: str, retailer_key: str = "", limit: int = 8) -> list[str]:
    """Extract unique product page URLs from search result cards only (not nav)."""
    seen, links = set(), []

    # Target actual search result cards — Shopify uses these containers.
    # Skipping nav/header links which pollute results with unrelated products.
    card_selectors = [
        ".card-product a[href]",
        ".product-item a[href]",
        ".grid__item a[href]",
        ".product-card a[href]",
        ".productGrid a[href]",
        "[data-product-id] a[href]",
        # WooCommerce
        "ul.products li.product a[href]",
        ".woocommerce-loop-product__title a[href]",
        ".woocommerce-loop-product__title[href]",
        # Marketplaces
        "[data-component-type='s-search-result'] a[href]",
        ".s-result-item a[href]",
        ".s-item a[href]",
        "[data-testid='item-stack'] a[href]",
        "[data-item-id] a[href]",
    ]

    candidates = []
    for sel in card_selectors:
        candidates = soup.select(sel)
        if candidates:
            break

    # Last resort: any product-looking link that isn't inside a nav/header element.
    if not candidates:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not _normalize_product_url(href, base, retailer_key):
                continue
            if a.find_parent(["nav", "header"]):
                continue
            if a.find_parent(class_=re.compile(r"nav|header|menu|site-nav", re.I)):
                continue
            candidates.append(a)

    for a in candidates:
        href = _normalize_product_url(a.get("href", ""), base, retailer_key)
        if not href:
            continue
        if href not in seen:
            seen.add(href)
            links.append(href)
        if len(links) >= limit:
            break
    return links


def _fetch_with_browser(ctx, url: str) -> str | None:
    page = ctx.new_page()
    try:
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1200)
        return page.content()
    except Exception:
        return None
    finally:
        try:
            page.close()
        except Exception:
            pass


def search_retailer(retailer: dict, query: str, ctx=None) -> list[str]:
    encoded = urllib.parse.quote_plus(query)
    url = retailer["search"].format(query=encoded)
    try:
        html = None
        if ctx is not None:
            html = _fetch_with_browser(ctx, url)
        if not html:
            r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
            if r.status_code != 200:
                return []
            html = r.text
        soup = BeautifulSoup(html, "lxml")
        return _product_links(soup, retailer["base"], retailer["key"])
    except Exception:
        return []


def verify_retailer_url(retailer: dict, url: str, query: str, ctx=None, product: dict | None = None):
    if ctx is not None:
        price, title, ok = verify_browser(ctx, url, query)
        if ok and (product is None or _matches_product(product, title, url, query)):
            return price, title, True
    price, title, ok = verify(url, query)
    if ok and (product is None or _matches_product(product, title, url, query)):
        return price, title, True
    return price, title, False


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


def _query_terms(query: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 3]


def _link_text_matches(a, query: str) -> bool:
    terms = _query_terms(query)
    if not terms:
        return False
    text = a.get_text(" ", strip=True).lower()
    href = a.get("href", "").lower()
    haystack = f"{text} {href}"
    return any(term in haystack for term in terms)


def _domyown_special_product_links(soup: BeautifulSoup, query: str, limit: int = 8) -> list[str]:
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
        if not _link_text_matches(a, query):
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


def search_domyown_specials(query: str, ctx, limit: int = 8) -> list[str]:
    """Use DoMyOwn's sale catalog, which exposes real product links and sale prices."""
    global _DOMYOWN_SPECIAL_LINKS
    if ctx is None:
        return []
    try:
        if _DOMYOWN_SPECIAL_LINKS is None:
            page = ctx.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page.goto("https://www.domyown.com/specials?page=all", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
            soup = BeautifulSoup(page.content(), "lxml")
            page.close()

            seen, links = set(), []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not re.search(r"-p-\d+\.html$", href, re.I):
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
            _DOMYOWN_SPECIAL_LINKS = links

        terms = _query_terms(query)
        matches = []
        for url in _DOMYOWN_SPECIAL_LINKS:
            slug = urllib.parse.urlparse(url).path.lower()
            if any(term in slug for term in terms):
                matches.append(url)
            if len(matches) >= limit:
                break
        return matches
    except Exception as e:
        print(f"    DoMyOwn specials error: {e.__class__.__name__}: {str(e)[:60]}")
        return []


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


def search_domyown_hints(query: str, limit: int = 5) -> list[str]:
    normalized = query.lower().strip()
    links = []
    for key, urls in DOMYOWN_HINTS.items():
        if key in normalized:
            links.extend(urls)
    return links[:limit]


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
    print("    DoMyOwn: site search found no product links, trying known product hints")
    links = search_domyown_hints(query)
    if links:
        return links
    print("    DoMyOwn: no known hint, trying specials page")
    links = search_domyown_specials(query, ctx)
    if links:
        return links
    print("    DoMyOwn: no specials match, trying Bing site search")
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
        urls = search_retailer(retailer, query, ctx=domyown_ctx)
        found = False
        for url in urls:
            price, title, ok = verify_retailer_url(retailer, url, query, ctx=domyown_ctx)
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

def discover_product_multi(product: dict, domyown_ctx=None) -> list[dict]:
    queries = _product_queries(product)
    sources = []
    seen_urls = set()

    print(f'  queries: {", ".join(repr(q) for q in queries[:6])}')

    if domyown_ctx is not None:
        found = False
        for query in queries:
            for url in search_domyown(query, domyown_ctx):
                if url in seen_urls:
                    continue
                price, title, ok = verify_browser(domyown_ctx, url, query)
                ok = ok and _matches_product(product, title, url, query)
                if ok:
                    seen_urls.add(url)
                    short = url.replace("https://", "").replace("www.", "")
                    print(f"    {'DoMyOwn':<24} OK ${price:<7.2f}  {title[:45]}")
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
            if found:
                break
        if not found:
            print(f"    {'DoMyOwn':<24} -")

    for retailer in RETAILERS:
        found = False
        for query in queries[:6]:
            for url in search_retailer(retailer, query, ctx=domyown_ctx):
                if url in seen_urls:
                    continue
                price, title, ok = verify_retailer_url(retailer, url, query, ctx=domyown_ctx, product=product)
                if ok:
                    seen_urls.add(url)
                    short = url.replace("https://", "").replace("www.", "")
                    print(f"    {retailer['name']:<24} OK ${price:<7.2f}  {title[:45]}")
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
            if found:
                break
        if not found:
            print(f"    {retailer['name']:<24} -")

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
        sources = discover_product_multi(product, domyown_ctx=domyown_ctx)
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

        _run_discovery(products, catalog, existing, sources_path, sources_data, domyown_ctx=ctx)
        page.close()
        ctx.close()


if __name__ == "__main__":
    main()
