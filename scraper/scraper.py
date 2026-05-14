#!/usr/bin/env python3
"""
Lawn Dominator Price Scraper
Runs nightly via GitHub Actions. Finds best prices across retailers
and writes prices.json, which is served as a static file by GitHub Pages.

Retailers:
  - DoMyOwn.com  (specialty lawn chemical retailer)
  - PestMall.com (specialty retailer)
  - Amazon       (PA API if credentials set, otherwise affiliate search link)

Set these as GitHub Secrets to enable full functionality:
  AMAZON_AFFILIATE_TAG   - your Amazon Associates tag (e.g. lawndominators-20)
  AMAZON_ACCESS_KEY      - PA API access key (optional, enables real prices)
  AMAZON_SECRET_KEY      - PA API secret key (optional)
  DOMYOWN_AFFILIATE_ID   - DoMyOwn affiliate ID (optional, appended to links)
"""

import json
import os
import re
import time
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import cloudscraper
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Affiliate / API credentials from environment ──────────────────────────────
AMAZON_TAG        = os.getenv("AMAZON_AFFILIATE_TAG", "lawndominator-20")
AMAZON_ACCESS_KEY = os.getenv("AMAZON_ACCESS_KEY", "")
AMAZON_SECRET_KEY = os.getenv("AMAZON_SECRET_KEY", "")
DOMYOWN_AFFID     = os.getenv("DOMYOWN_AFFILIATE_ID", "")

RATE_LIMIT = 3.0  # seconds between requests per domain

# ── cloudscraper session — handles Cloudflare JS challenges automatically ─────
session = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "mobile": False}
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_get(url: str, timeout: int = 20) -> Optional[cloudscraper.requests.Response]:
    try:
        resp = session.get(url, timeout=timeout)
        if resp.status_code != 200:
            log.info(f"  HTTP {resp.status_code} — {url[:80]}")
            return None
        return resp
    except Exception as e:
        log.info(f"  Request failed — {e.__class__.__name__}: {e}"[:120])
    return None


def parse_price(text: str) -> Optional[float]:
    """Extract first dollar amount from a string."""
    text = text.replace(",", "")
    match = re.search(r"\$?\s*([\d]+\.[\d]{1,2})", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def search_variants(product: dict, base_key: str = "search_query") -> list[str]:
    """
    Build an ordered list of search terms to try for a product.
    Uses the primary search_query first, then active_ingredient, then alt_names.
    This ensures we find the right product even when retailers spell names differently.
    """
    seen = set()
    variants = []

    def add(term):
        t = term.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            variants.append(t)

    add(product.get(base_key, product.get("search_query", "")))

    # Active ingredient is the most reliable fallback — it's on every label
    ai = product.get("active_ingredient")
    if ai:
        add(ai)

    # Alternate spellings / brand names
    for alt in product.get("alt_names", []):
        add(alt)

    return variants


def append_affiliate(url: str, retailer: str) -> str:
    """Append affiliate tracking parameters where applicable."""
    if retailer == "amazon" and AMAZON_TAG and "tag=" not in url:
        sep = "&" if "?" in url else "?"
        url += f"{sep}tag={AMAZON_TAG}"
    if retailer == "domyown" and DOMYOWN_AFFID and "affid=" not in url:
        sep = "&" if "?" in url else "?"
        url += f"{sep}affid={DOMYOWN_AFFID}"
    return url


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── DoMyOwn scraper ───────────────────────────────────────────────────────────

def scrape_domyown(product: dict) -> Optional[dict]:
    # Try primary query first, then fall back through active_ingredient and alt_names
    queries = search_variants(product, base_key="domyown_query")

    for query in queries:
        result = _domyown_search(product, query)
        if result:
            return result
        time.sleep(1.0)  # brief pause between fallback attempts

    return None


def _domyown_search(product: dict, query: str) -> Optional[dict]:
    encoded = urllib.parse.quote_plus(query)
    search_url = f"https://www.domyown.com/do-my-own-search.aspx?searchtext={encoded}"

    resp = safe_get(search_url)
    if not resp:
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # Try multiple selector patterns — DoMyOwn has updated their markup over time
    selectors = [
        ".productResultsItem",
        ".product-results-item",
        ".search-product-item",
        "[data-product-id]",
        ".product-item",
    ]
    item = None
    for sel in selectors:
        item = soup.select_one(sel)
        if item:
            break

    if not item:
        # Last resort: find any price on the page
        price_tags = soup.select(".price, .product-price, [class*='price']")
        if not price_tags:
            log.info(f"  DoMyOwn: no results for '{query}' (body len={len(resp.text)})")
            return None
        price = parse_price(price_tags[0].get_text(strip=True))
        if not price:
            return None
        link = soup.select_one("a[href*='/p-']") or soup.select_one("h2 a, h3 a, .product-title a")
        href = link["href"] if link else search_url
        product_url = href if href.startswith("http") else "https://www.domyown.com" + href
        product_url = append_affiliate(product_url, "domyown")
        return {
            "retailer": "domyown",
            "retailer_name": "DoMyOwn",
            "price": price,
            "url": product_url,
            "in_stock": True,
            "last_checked": now_iso(),
        }

    price_elem = (
        item.select_one(".price")
        or item.select_one(".product-price")
        or item.select_one("[class*='price']")
    )
    link_elem = item.select_one("a[href]")

    if not price_elem or not link_elem:
        return None

    price = parse_price(price_elem.get_text(strip=True))
    if not price:
        return None

    href = link_elem.get("href", "")
    product_url = href if href.startswith("http") else "https://www.domyown.com" + href
    product_url = append_affiliate(product_url, "domyown")

    return {
        "retailer": "domyown",
        "retailer_name": "DoMyOwn",
        "price": price,
        "url": product_url,
        "in_stock": True,
        "last_checked": now_iso(),
    }


# ── PestMall scraper ──────────────────────────────────────────────────────────

def scrape_pestmall(product: dict) -> Optional[dict]:
    for query in search_variants(product):
        result = _pestmall_search(product, query)
        if result:
            return result
        time.sleep(1.0)
    return None


def _pestmall_search(product: dict, query: str) -> Optional[dict]:
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.pestmall.com/search.php?search_query={encoded}"

    resp = safe_get(url)
    if not resp:
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    item = (
        soup.select_one(".listItem")
        or soup.select_one(".product-item--grid")
        or soup.select_one(".productGrid .product")
        or soup.select_one("[data-product-id]")
    )
    if not item:
        return None

    price_elem = (
        item.select_one(".price--withoutTax")
        or item.select_one(".price")
        or item.select_one("[data-product-price]")
    )
    link_elem = (
        item.select_one("a.card-title")
        or item.select_one(".product-title a")
        or item.select_one("h4 a, h3 a")
    )

    if not price_elem or not link_elem:
        return None

    price = parse_price(price_elem.get_text(strip=True))
    if not price:
        return None

    href = link_elem.get("href", "")
    product_url = href if href.startswith("http") else "https://www.pestmall.com" + href

    return {
        "retailer": "pestmall",
        "retailer_name": "PestMall",
        "price": price,
        "url": product_url,
        "in_stock": True,
        "last_checked": now_iso(),
    }


# ── Amazon ────────────────────────────────────────────────────────────────────

def amazon_result(product: dict) -> Optional[dict]:
    """
    Returns real price via PA API if credentials are set,
    otherwise returns an affiliate search link (price shown live on Amazon).
    """
    if AMAZON_ACCESS_KEY and AMAZON_SECRET_KEY:
        return _amazon_paapi(product)
    return _amazon_affiliate_link(product)


def _amazon_affiliate_link(product: dict) -> dict:
    query = product.get("amazon_query") or product["search_query"]
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.amazon.com/s?k={encoded}&tag={AMAZON_TAG}"
    return {
        "retailer": "amazon",
        "retailer_name": "Amazon",
        "price": None,
        "url": url,
        "in_stock": None,
        "note": "Live price shown on Amazon",
        "last_checked": now_iso(),
    }


def _amazon_paapi(product: dict) -> dict:
    """
    Uses Amazon PA API 5.0.
    Install: pip install paapi5-python-sdk
    Docs: https://webservices.amazon.com/paapi5/documentation/
    """
    try:
        import paapi5_python_sdk as paapi
        from paapi5_python_sdk.api.default_api import DefaultApi
        from paapi5_python_sdk.models.search_items_request import SearchItemsRequest
        from paapi5_python_sdk.models.search_items_resource import SearchItemsResource
        from paapi5_python_sdk.models.partner_type import PartnerType
        from paapi5_python_sdk.configuration import Configuration
        from paapi5_python_sdk.api_client import ApiClient

        config = Configuration()
        config.access_key = AMAZON_ACCESS_KEY
        config.secret_key = AMAZON_SECRET_KEY
        config.host = "webservices.amazon.com"
        config.region = "us-east-1"

        client = DefaultApi(ApiClient(config))
        query = product.get("amazon_query") or product["search_query"]

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

        item = response.search_result.items[0]
        price = None
        in_stock = None

        if item.offers and item.offers.listings:
            listing = item.offers.listings[0]
            if listing.price:
                price = float(listing.price.amount)
            if listing.availability and listing.availability.message:
                in_stock = "In Stock" in listing.availability.message

        url = item.detail_page_url or _amazon_affiliate_link(product)["url"]
        url = append_affiliate(url, "amazon")

        return {
            "retailer": "amazon",
            "retailer_name": "Amazon",
            "price": price,
            "url": url,
            "in_stock": in_stock,
            "last_checked": now_iso(),
        }

    except ImportError:
        log.warning("paapi5-python-sdk not installed — using affiliate link")
        return _amazon_affiliate_link(product)
    except Exception as e:
        log.warning(f"Amazon PA API error for '{product['name']}': {e}")
        return _amazon_affiliate_link(product)


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)

    products_path = os.path.join(repo_root, "products.json")
    prices_path   = os.path.join(repo_root, "prices.json")

    with open(products_path) as f:
        catalog = json.load(f)

    # Load existing prices so stale data can be preserved on failures
    try:
        with open(prices_path) as f:
            existing_data = json.load(f)
        stale_map = {p["id"]: p for p in existing_data.get("products", [])}
    except FileNotFoundError:
        stale_map = {}

    results = []
    total = len(catalog["products"])

    for i, product in enumerate(catalog["products"], 1):
        pid   = product["id"]
        name  = product["name"]
        cat   = product["category"]
        log.info(f"[{i}/{total}] {name}")

        offers = []

        # --- DoMyOwn (all pro + specialty categories) ---
        if cat not in ("fertilizer-consumer",):
            time.sleep(RATE_LIMIT)
            result = scrape_domyown(product)
            if result:
                offers.append(result)
                log.info(f"  DoMyOwn  ${result['price']:.2f}")
            else:
                log.debug(f"  DoMyOwn  no result")

        # --- PestMall (fungicides, insecticides, herbicides only) ---
        if cat in ("fungicide", "insecticide", "pre-emergent", "post-emergent", "pgr"):
            time.sleep(RATE_LIMIT)
            result = scrape_pestmall(product)
            if result:
                offers.append(result)
                log.info(f"  PestMall ${result['price']:.2f}")
            else:
                log.debug(f"  PestMall no result")

        # --- Amazon (all products) ---
        time.sleep(RATE_LIMIT)
        result = amazon_result(product)
        if result:
            offers.append(result)
            price_str = f"${result['price']:.2f}" if result.get("price") else "(link only)"
            log.info(f"  Amazon   {price_str}")

        # Determine best price among offers that have a real price
        priced_offers = [o for o in offers if o.get("price") is not None]
        best = min(priced_offers, key=lambda o: o["price"]) if priced_offers else None

        if not offers and pid in stale_map:
            entry = stale_map[pid].copy()
            entry["stale"] = True
            results.append(entry)
            log.warning(f"  Using stale data")
            continue

        results.append({
            "id":         pid,
            "slug":       product["slug"],
            "name":       name,
            "category":   cat,
            "offers":     offers,
            "best_price": best,
            "updated_at": now_iso(),
        })

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
