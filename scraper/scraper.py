#!/usr/bin/env python3
"""
Lawn Dominator Price Scraper
Runs every 4 hours via GitHub Actions. Finds best prices across retailers
and writes prices.json, which is served as a static file by GitHub Pages.

Retailers:
  - DoMyOwn.com           (specialty lawn chemical retailer — Playwright)
  - Solutions Pest & Lawn (specialty retailer — Playwright)
  - Amazon                (PA API if credentials set, otherwise affiliate link)

GitHub Secrets:
  AMAZON_AFFILIATE_TAG   - your Amazon Associates tag
  AMAZON_ACCESS_KEY      - PA API access key (optional, enables real prices)
  AMAZON_SECRET_KEY      - PA API secret key (optional)
  DOMYOWN_AFFILIATE_ID   - DoMyOwn affiliate ID (optional)
"""

import json
import os
import re
import time
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Browser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Credentials ───────────────────────────────────────────────────────────────
AMAZON_TAG        = os.getenv("AMAZON_AFFILIATE_TAG", "lawndominator-20")
AMAZON_ACCESS_KEY = os.getenv("AMAZON_ACCESS_KEY", "")
AMAZON_SECRET_KEY = os.getenv("AMAZON_SECRET_KEY", "")
DOMYOWN_AFFID     = os.getenv("DOMYOWN_AFFILIATE_ID", "")

RATE_LIMIT = 2.0   # seconds between Playwright page loads

# Global browser instance — shared across all scrape calls
_browser: Optional[Browser] = None


def get_browser() -> Browser:
    return _browser


def browser_fetch(url: str, wait: str = "domcontentloaded", timeout: int = 25000) -> Optional[str]:
    """Load URL in headless Chromium, return rendered HTML. Handles JS challenges."""
    try:
        ctx = get_browser().new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()
        resp = page.goto(url, wait_until=wait, timeout=timeout)
        if resp and resp.status != 200:
            log.info(f"  Browser HTTP {resp.status} — {url[:80]}")
            page.close()
            ctx.close()
            return None
        html = page.content()
        page.close()
        ctx.close()
        return html
    except Exception as e:
        log.info(f"  Browser fetch failed: {e.__class__.__name__}: {str(e)[:80]}")
        return None


# ── Simple requests session for Amazon (no Cloudflare) ───────────────────────
_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
})


def safe_get(url: str, timeout: int = 15) -> Optional[requests.Response]:
    try:
        r = _session.get(url, timeout=timeout)
        return r if r.status_code == 200 else None
    except Exception:
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_price(text: str) -> Optional[float]:
    text = text.replace(",", "")
    m = re.search(r"\$?\s*(\d+\.\d{1,2})", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def search_variants(product: dict, base_key: str = "search_query") -> list[str]:
    seen, variants = set(), []

    def add(term):
        t = term.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            variants.append(t)

    add(product.get(base_key, product.get("search_query", "")))
    if ai := product.get("active_ingredient"):
        add(ai)
    for alt in product.get("alt_names", []):
        add(alt)
    return variants


def append_affiliate(url: str, retailer: str) -> str:
    if retailer == "amazon" and AMAZON_TAG and "tag=" not in url:
        url += ("&" if "?" in url else "?") + f"tag={AMAZON_TAG}"
    if retailer == "domyown" and DOMYOWN_AFFID and "affid=" not in url:
        url += ("&" if "?" in url else "?") + f"affid={DOMYOWN_AFFID}"
    return url


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_from_soup(soup: BeautifulSoup, base_url: str, retailer: str, retailer_name: str) -> Optional[dict]:
    """Generic price + link extractor from parsed HTML."""
    card_selectors = [
        "[data-product-id]", ".product-item", ".product-card",
        ".productCard", ".card", "li.product", "article.product",
        ".grid-product", ".search-result-item", ".product",
    ]
    card = None
    for sel in card_selectors:
        card = soup.select_one(sel)
        if card:
            break

    search_root = card or soup

    price_elem = (
        search_root.select_one("[class*='sale-price']")
        or search_root.select_one("[class*='price--sale']")
        or search_root.select_one(".price--withoutTax")
        or search_root.select_one("[itemprop='price']")
        or search_root.select_one("[class*='price']")
    )
    link_elem = (
        search_root.select_one("a[href*='/products/']")
        or search_root.select_one("a[href*='.html']")
        or search_root.select_one("h2 a, h3 a, h4 a")
        or search_root.select_one("a[href]")
    )

    if not price_elem:
        return None

    price = parse_price(price_elem.get("content") or price_elem.get_text(strip=True))
    if not price:
        return None

    href = link_elem.get("href", base_url) if link_elem else base_url
    product_url = href if href.startswith("http") else base_url.rstrip("/").rsplit("/", 2)[0] + href
    product_url = append_affiliate(product_url, retailer)

    return {
        "retailer":      retailer,
        "retailer_name": retailer_name,
        "price":         price,
        "url":           product_url,
        "in_stock":      True,
        "last_checked":  now_iso(),
    }


# ── DoMyOwn scraper ───────────────────────────────────────────────────────────

def scrape_domyown(product: dict) -> Optional[dict]:
    queries = search_variants(product, base_key="domyown_query")
    for query in queries:
        result = _domyown_search(query)
        if result:
            return result
        time.sleep(1.0)
    return None


def _domyown_search(query: str) -> Optional[dict]:
    encoded = urllib.parse.quote_plus(query)
    for url in [
        f"https://www.domyown.com/search?q={encoded}",
        f"https://www.domyown.com/search?searchterm={encoded}",
    ]:
        html = browser_fetch(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        result = _extract_from_soup(soup, "https://www.domyown.com", "domyown", "DoMyOwn")
        if result:
            return result
        time.sleep(1.0)
    return None


# ── Solutions Pest & Lawn scraper ─────────────────────────────────────────────

def scrape_solutions(product: dict) -> Optional[dict]:
    queries = search_variants(product)
    for query in queries:
        result = _solutions_search(query)
        if result:
            return result
        time.sleep(1.0)
    return None


def _solutions_search(query: str) -> Optional[dict]:
    encoded = urllib.parse.quote_plus(query)
    for url in [
        f"https://www.solutionsstores.com/search?q={encoded}&type=product",
        f"https://www.solutionsstores.com/search?q={encoded}",
    ]:
        html = browser_fetch(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        result = _extract_from_soup(soup, "https://www.solutionsstores.com", "solutions", "Solutions Pest & Lawn")
        if result:
            return result
        time.sleep(1.0)
    return None


# ── Amazon ────────────────────────────────────────────────────────────────────

def amazon_result(product: dict) -> Optional[dict]:
    if AMAZON_ACCESS_KEY and AMAZON_SECRET_KEY:
        return _amazon_paapi(product)
    return _amazon_affiliate_link(product)


def _amazon_affiliate_link(product: dict) -> dict:
    query   = product.get("amazon_query") or product["search_query"]
    encoded = urllib.parse.quote_plus(query)
    url     = f"https://www.amazon.com/s?k={encoded}&tag={AMAZON_TAG}"
    return {
        "retailer":      "amazon",
        "retailer_name": "Amazon",
        "price":         None,
        "url":           url,
        "in_stock":      None,
        "note":          "Live price shown on Amazon",
        "last_checked":  now_iso(),
    }


def _amazon_paapi(product: dict) -> dict:
    try:
        from paapi5_python_sdk.api.default_api import DefaultApi
        from paapi5_python_sdk.models.search_items_request import SearchItemsRequest
        from paapi5_python_sdk.models.search_items_resource import SearchItemsResource
        from paapi5_python_sdk.models.partner_type import PartnerType
        from paapi5_python_sdk.configuration import Configuration
        from paapi5_python_sdk.api_client import ApiClient

        config             = Configuration()
        config.access_key  = AMAZON_ACCESS_KEY
        config.secret_key  = AMAZON_SECRET_KEY
        config.host        = "webservices.amazon.com"
        config.region      = "us-east-1"
        client             = DefaultApi(ApiClient(config))
        query              = product.get("amazon_query") or product["search_query"]

        req = SearchItemsRequest(
            partner_tag=AMAZON_TAG,
            partner_type=PartnerType.ASSOCIATES,
            keywords=query,
            search_index="LawnAndGarden",
            item_count=1,
            resources=[
                SearchItemsResource.OFFERS_LISTINGS_PRICE,
                SearchItemsResource.ITEMINFO_TITLE,
                SearchItemsResource.OFFERS_LISTINGS_AVAILABILITY_MESSAGE,
            ],
        )
        response = client.search_items(req)
        if not response.search_result or not response.search_result.items:
            return _amazon_affiliate_link(product)

        item     = response.search_result.items[0]
        price    = None
        in_stock = None
        if item.offers and item.offers.listings:
            listing = item.offers.listings[0]
            if listing.price:
                price = float(listing.price.amount)
            if listing.availability and listing.availability.message:
                in_stock = "In Stock" in listing.availability.message

        url = item.detail_page_url or _amazon_affiliate_link(product)["url"]
        return {
            "retailer":      "amazon",
            "retailer_name": "Amazon",
            "price":         price,
            "url":           append_affiliate(url, "amazon"),
            "in_stock":      in_stock,
            "last_checked":  now_iso(),
        }
    except ImportError:
        return _amazon_affiliate_link(product)
    except Exception as e:
        log.warning(f"Amazon PA API error: {e}")
        return _amazon_affiliate_link(product)


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    global _browser

    script_dir    = os.path.dirname(os.path.abspath(__file__))
    repo_root     = os.path.dirname(script_dir)
    products_path = os.path.join(repo_root, "products.json")
    prices_path   = os.path.join(repo_root, "prices.json")

    with open(products_path) as f:
        catalog = json.load(f)

    try:
        with open(prices_path) as f:
            existing_data = json.load(f)
        stale_map = {p["id"]: p for p in existing_data.get("products", [])}
    except FileNotFoundError:
        stale_map = {}

    results = []
    total   = len(catalog["products"])

    with sync_playwright() as pw:
        _browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        log.info("Playwright browser launched")

        for i, product in enumerate(catalog["products"], 1):
            pid  = product["id"]
            name = product["name"]
            cat  = product["category"]
            log.info(f"[{i}/{total}] {name}")

            offers = []

            # DoMyOwn — all specialty categories
            if cat != "fertilizer-consumer":
                time.sleep(RATE_LIMIT)
                r = scrape_domyown(product)
                if r:
                    offers.append(r)
                    log.info(f"  DoMyOwn  ${r['price']:.2f}")
                else:
                    log.info(f"  DoMyOwn  no result")

            # Solutions Pest & Lawn — herbicides, fungicides, insecticides, PGRs
            if cat in ("fungicide", "insecticide", "pre-emergent", "post-emergent", "pgr"):
                time.sleep(RATE_LIMIT)
                r = scrape_solutions(product)
                if r:
                    offers.append(r)
                    log.info(f"  Solutions ${r['price']:.2f}")
                else:
                    log.info(f"  Solutions no result")

            # Amazon — all products
            time.sleep(RATE_LIMIT)
            r = amazon_result(product)
            if r:
                offers.append(r)
                price_str = f"${r['price']:.2f}" if r.get("price") else "(link only)"
                log.info(f"  Amazon   {price_str}")

            priced = [o for o in offers if o.get("price") is not None]
            best   = min(priced, key=lambda o: o["price"]) if priced else None

            if not offers and pid in stale_map:
                entry = stale_map[pid].copy()
                entry["stale"] = True
                results.append(entry)
                log.warning(f"  Using stale data")
                continue

            results.append({
                "id":                pid,
                "slug":              product["slug"],
                "name":              name,
                "category":          cat,
                "active_ingredient": product.get("active_ingredient", ""),
                "alt_names":         product.get("alt_names", []),
                "offers":            offers,
                "best_price":        best,
                "updated_at":        now_iso(),
            })

        _browser.close()

    output = {
        "schema_version": "1.0",
        "generated_at":   now_iso(),
        "product_count":  len(results),
        "products":       results,
    }

    with open(prices_path, "w") as f:
        json.dump(output, f, indent=2)

    found = sum(1 for p in results if p.get("best_price"))
    log.info(f"\nDone. {found}/{len(results)} products have a best price.")
    log.info(f"Written to {prices_path}")


if __name__ == "__main__":
    run()
