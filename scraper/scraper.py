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
import sys
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
SERPAPI_API_KEY   = os.getenv("SERPAPI_API_KEY", "")
AMAZON_TAG        = os.getenv("AMAZON_AFFILIATE_TAG", "lawndominator-20")
AMAZON_ACCESS_KEY = os.getenv("AMAZON_ACCESS_KEY", "")
AMAZON_SECRET_KEY = os.getenv("AMAZON_SECRET_KEY", "")
DOMYOWN_AFFID     = os.getenv("DOMYOWN_AFFILIATE_ID", "")

RATE_LIMIT = 2.0   # seconds between Playwright page loads
SHOPPING_RESULT_LIMIT = int(os.getenv("SHOPPING_RESULT_LIMIT", "10"))
SHOPPING_DETAIL_RESULT_LIMIT = int(os.getenv("SHOPPING_DETAIL_RESULT_LIMIT", "0"))
ORGANIC_RESULT_LIMIT = int(os.getenv("ORGANIC_RESULT_LIMIT", "3"))
ENABLE_SERPAPI_DISCOVERY = os.getenv("ENABLE_SERPAPI_DISCOVERY", "0") == "1"
ENABLE_ORGANIC_DISCOVERY = os.getenv("ENABLE_ORGANIC_DISCOVERY", "1") != "0"
REQUIRE_WEB_DISCOVERY = os.getenv("REQUIRE_WEB_DISCOVERY", "0") == "1"
ENABLE_DIRECT_RETAILER_SEARCH = os.getenv("ENABLE_DIRECT_RETAILER_SEARCH", "0") == "1"
ENABLE_KNOWN_RETAILER_SEARCH = os.getenv("ENABLE_KNOWN_RETAILER_SEARCH", "0") == "1"
ORGANIC_FETCH_TIMEOUT = int(os.getenv("ORGANIC_FETCH_TIMEOUT", "12000"))
KNOWN_RETAILER_LIMIT = int(os.getenv("KNOWN_RETAILER_LIMIT", "8"))
SAVED_SOURCE_LIMIT = int(os.getenv("SAVED_SOURCE_LIMIT", "12"))
MAX_SAVED_SOURCES_PER_PRODUCT = int(os.getenv("MAX_SAVED_SOURCES_PER_PRODUCT", "50"))
MIN_CHEMICAL_PRICE = float(os.getenv("MIN_CHEMICAL_PRICE", "10"))
MIN_SOIL_AMENDMENT_PRICE = float(os.getenv("MIN_SOIL_AMENDMENT_PRICE", "5"))
REPEATED_PRICE_PRODUCT_LIMIT = int(os.getenv("REPEATED_PRICE_PRODUCT_LIMIT", "8"))
MIN_ALERT_DROP_PERCENT = float(os.getenv("MIN_ALERT_DROP_PERCENT", "5"))

# Global browser instance — shared across all scrape calls
_browser: Optional[Browser] = None


def get_browser() -> Browser:
    return _browser


def browser_fetch(url: str, wait: str = "networkidle", timeout: int = 30000) -> Optional[str]:
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
        title = page.title()
        final_url = page.url
        log.info(f"  Page: '{title[:70]}' @ {final_url[:90]}")
        html = page.content()
        page.close()
        ctx.close()
        return html
    except Exception as e:
        log.info(f"  Browser fetch failed: {e.__class__.__name__}: {str(e)[:80]}")
        return None


def fetch_saved_source(url: str) -> Optional[str]:
    """Fetch a known product URL quickly; saved pages do not need search-style waits."""
    html = browser_fetch(url, wait="domcontentloaded", timeout=ORGANIC_FETCH_TIMEOUT)
    if html:
        return html

    response = safe_get(url, timeout=max(8, ORGANIC_FETCH_TIMEOUT // 1000))
    if response:
        log.info(f"  Requests fallback OK {url[:90]}")
        return response.text
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
    m = re.search(r"(?:\$|USD\s*)\s*(\d+(?:\.\d{1,2})?)", text, re.I)
    if not m:
        m = re.search(r"\b(\d+\.\d{2})\b", text)
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
    if retailer == "amazon" and AMAZON_TAG:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query = [(key, value) for key, value in query if key.lower() != "tag"]
        query.append(("tag", AMAZON_TAG))
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
    if retailer == "domyown" and DOMYOWN_AFFID and "affid=" not in url:
        url += ("&" if "?" in url else "?") + f"affid={DOMYOWN_AFFID}"
    return url


def retailer_key(name_or_url: str) -> str:
    value = name_or_url.lower().strip()
    if "://" in value:
        host = urllib.parse.urlparse(value).netloc.lower()
        value = host[4:] if host.startswith("www.") else host
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "web"


def retailer_name_from_url(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    if not host:
        return "Online Retailer"
    return host.split(".")[0].replace("-", " ").title()


def is_google_url(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host == "google.com" or host.endswith(".google.com")


def is_bad_product_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parsed.query.lower()
    bad_path_parts = (
        "/cart", "/checkout", "/account", "/login", "/search", "/collections/",
        "/category/", "/categories/", "/catalogsearch/", "/wishlist",
    )
    if any(part in path for part in bad_path_parts):
        return True
    if ("amazon.com" in host or host.endswith("amzn.to")) and path.rstrip("/") == "/s":
        return True
    if "search" in query or query.startswith("k="):
        return True
    if "ebay." in host and path.startswith("/sch"):
        return True
    return "notify" in path or "notify" in query


def offer_key(offer: dict) -> tuple:
    normalized_url = urllib.parse.urldefrag(offer.get("url", ""))[0].rstrip("/")
    return (offer.get("retailer"), normalized_url, offer.get("price"))


def add_offer(offers: list[dict], offer: Optional[dict]) -> bool:
    if not offer:
        return False
    if any(offer_key(existing) == offer_key(offer) for existing in offers):
        return False
    offers.append(offer)
    return True


def min_price_for_product(product: dict) -> float:
    if product.get("category") == "soil-amendment":
        return MIN_SOIL_AMENDMENT_PRICE
    return MIN_CHEMICAL_PRICE


def select_best_offer(product: dict, offers: list[dict]) -> Optional[dict]:
    priced = [
        o for o in offers
        if o.get("price") is not None
        and not o.get("excluded")
        and not is_google_url(o.get("url", ""))
        and not is_bad_product_url(o.get("url", ""))
        and float(o["price"]) >= min_price_for_product(product)
    ]
    priced.sort(key=lambda o: o["price"])
    return priced[0] if priced else None


def apply_offer_quality_filters(results: list[dict]) -> None:
    repeated_prices: dict[tuple, set] = {}
    for product in results:
        for offer in product.get("offers", []):
            if offer.get("price") is None:
                continue
            key = (offer.get("retailer"), round(float(offer["price"]), 2))
            repeated_prices.setdefault(key, set()).add(product["id"])

    repeated_bad = {
        key for key, product_ids in repeated_prices.items()
        if len(product_ids) >= REPEATED_PRICE_PRODUCT_LIMIT
    }

    for product in results:
        floor = min_price_for_product(product)
        for offer in product.get("offers", []):
            if offer.get("price") is None:
                continue

            price = round(float(offer["price"]), 2)
            key = (offer.get("retailer"), price)
            if is_google_url(offer.get("url", "")):
                offer["excluded"] = True
                offer["exclude_reason"] = "Google Shopping intermediary URL, merchant link not resolved"
            elif is_bad_product_url(offer.get("url", "")):
                offer["excluded"] = True
                offer["exclude_reason"] = "cart/search/notify URL, not a product purchase page"
            elif price < floor:
                offer["excluded"] = True
                offer["exclude_reason"] = f"below ${floor:.2f} minimum for this category"
            elif key in repeated_bad:
                offer["excluded"] = True
                offer["exclude_reason"] = "same retailer/price repeated across many unrelated products"

        product["best_price"] = select_best_offer(product, product.get("offers", []))


def preserve_last_good_products(results: list[dict], previous_products: dict) -> list[dict]:
    preserved = []
    for product in results:
        previous = previous_products.get(product["id"])
        if product.get("best_price") or not previous or not previous.get("best_price"):
            preserved.append(product)
            continue

        entry = previous.copy()
        entry["stale"] = True
        entry["stale_reason"] = "latest run had no valid priced purchase URL"
        preserved.append(entry)
        log.warning(f"  Preserved last-good data for {product.get('name')}")
    return preserved


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _offer_price(offer: Optional[dict]) -> Optional[float]:
    if not offer or offer.get("price") is None:
        return None
    try:
        return float(offer["price"])
    except (TypeError, ValueError):
        return None


def _drop_percent(old_price: float, new_price: float) -> float:
    if old_price <= 0 or new_price >= old_price:
        return 0.0
    return ((old_price - new_price) / old_price) * 100


def _alert_id(product_slug: str, alert_type: str, old_offer: Optional[dict], new_offer: dict) -> str:
    old_price = _offer_price(old_offer)
    new_price = _offer_price(new_offer)
    retailer = new_offer.get("retailer") or "retailer"
    return ":".join([
        product_slug,
        alert_type,
        retailer,
        f"{old_price:.2f}" if old_price is not None else "none",
        f"{new_price:.2f}" if new_price is not None else "none",
    ])


def _alert_payload(
    product: dict,
    alert_type: str,
    old_offer: Optional[dict],
    new_offer: dict,
    generated_at: str,
    drop_percent: float = 0.0,
) -> dict:
    old_price = _offer_price(old_offer)
    new_price = _offer_price(new_offer)
    return {
        "id": _alert_id(product["slug"], alert_type, old_offer, new_offer),
        "type": alert_type,
        "product_id": product["id"],
        "product_slug": product["slug"],
        "product_name": product["name"],
        "category": product.get("category"),
        "old_price": round(old_price, 2) if old_price is not None else None,
        "new_price": round(new_price, 2) if new_price is not None else None,
        "drop_percent": round(drop_percent, 1),
        "old_retailer": old_offer.get("retailer_name") if old_offer else None,
        "new_retailer": new_offer.get("retailer_name"),
        "url": new_offer.get("url"),
        "in_stock": new_offer.get("in_stock"),
        "created_at": generated_at,
    }


def build_price_alerts(previous_products: dict, current_products: list[dict], generated_at: str) -> dict:
    alerts = []
    previous_by_slug = {
        product.get("slug"): product
        for product in previous_products.values()
        if product.get("slug")
    }

    for product in current_products:
        old_product = previous_by_slug.get(product.get("slug")) or previous_products.get(product.get("id"))
        if not old_product:
            continue

        old_best = old_product.get("best_price")
        new_best = product.get("best_price")
        old_price = _offer_price(old_best)
        new_price = _offer_price(new_best)
        if not new_best or new_price is None:
            continue

        if old_price is not None and new_best.get("in_stock") is not False:
            drop = _drop_percent(old_price, new_price)
            if drop >= MIN_ALERT_DROP_PERCENT:
                if drop >= 10:
                    alerts.append(_alert_payload(product, "major_price_drop", old_best, new_best, generated_at, drop))
                else:
                    alerts.append(_alert_payload(product, "best_price_drop", old_best, new_best, generated_at, drop))

            old_retailer = old_best.get("retailer") if old_best else None
            new_retailer = new_best.get("retailer")
            if new_retailer and old_retailer and new_retailer != old_retailer and new_price < old_price:
                alerts.append(_alert_payload(product, "new_lowest_retailer", old_best, new_best, generated_at, drop))

        if old_best and old_best.get("in_stock") is False and new_best.get("in_stock") is True:
            alerts.append(_alert_payload(product, "back_in_stock", old_best, new_best, generated_at, 0.0))

    unique_alerts = {}
    for alert in alerts:
        unique_alerts[alert["id"]] = alert

    return {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "min_drop_percent": MIN_ALERT_DROP_PERCENT,
        "alert_count": len(unique_alerts),
        "alerts": list(unique_alerts.values()),
    }


def _absolute_url(base_url: str, href: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", href)


def _offer_product_url(base_url: str, href: str, retailer: str) -> Optional[str]:
    """Resolve an offer link without letting cart/search URLs replace the product page."""
    resolved = _absolute_url(base_url, href or base_url)
    if is_google_url(resolved) or is_bad_product_url(resolved):
        resolved = urllib.parse.urldefrag(base_url)[0].rstrip("/")
    if is_google_url(resolved) or is_bad_product_url(resolved):
        return None
    return append_affiliate(resolved, retailer)


def _iter_jsonld_objects(value):
    if isinstance(value, list):
        for item in value:
            yield from _iter_jsonld_objects(item)
    elif isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if graph:
            yield from _iter_jsonld_objects(graph)


def _jsonld_product_offer(soup: BeautifulSoup, base_url: str, retailer: str, retailer_name: str) -> Optional[dict]:
    for script in soup.select("script[type='application/ld+json']"):
        if not script.string:
            continue
        try:
            payload = json.loads(script.string)
        except json.JSONDecodeError:
            continue
        for obj in _iter_jsonld_objects(payload):
            obj_type = obj.get("@type")
            if isinstance(obj_type, list):
                is_product = any(str(t).lower() == "product" for t in obj_type)
            else:
                is_product = str(obj_type).lower() == "product"
            if not is_product:
                continue

            offers = obj.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if not isinstance(offers, dict):
                continue

            price = parse_price(str(offers.get("price") or offers.get("lowPrice") or ""))
            if price is None:
                continue

            href = offers.get("url") or obj.get("url") or base_url
            product_url = _offer_product_url(base_url, href, retailer)
            if not product_url:
                continue
            return {
                "retailer": retailer,
                "retailer_name": retailer_name,
                "price": price,
                "url": product_url,
                "in_stock": "outofstock" not in str(offers.get("availability", "")).lower(),
                "last_checked": now_iso(),
            }
    return None


def _price_from_node(node) -> Optional[float]:
    selectors = [
        "[class*='sale-price']", "[class*='price--sale']", ".price--withoutTax",
        "[itemprop='price']", "[data-price]", "[class*='price']", "meta[itemprop='price']",
        "meta[property='product:price:amount']",
    ]
    for sel in selectors:
        elem = node.select_one(sel)
        if not elem:
            continue
        raw = elem.get("content") or elem.get("data-price") or elem.get_text(" ", strip=True)
        price = parse_price(raw)
        if price is not None:
            return price
    return parse_price(node.get_text(" ", strip=True))


def _extract_from_soup(soup: BeautifulSoup, base_url: str, retailer: str, retailer_name: str) -> Optional[dict]:
    """Generic price + link extractor from parsed HTML."""
    jsonld_result = _jsonld_product_offer(soup, base_url, retailer, retailer_name)
    if jsonld_result:
        return jsonld_result

    card_selectors = [
        "[data-product-id]", ".product-item", ".product-card",
        ".productCard", ".card", "li.product", "article.product",
        ".grid-product", ".search-result-item", ".product", ".product-item-info",
        ".product.details.product-item-details", "[class*='product-item']",
    ]

    candidates = []
    for sel in card_selectors:
        candidates.extend(soup.select(sel))
    candidates.append(soup)

    for search_root in candidates:
        price = _price_from_node(search_root)
        if price is None:
            continue

        link_elem = (
            search_root.select_one("a[href*='/products/']")
            or search_root.select_one("a[href*='.html']")
            or search_root.select_one("h2 a[href], h3 a[href], h4 a[href], .product-item-link[href]")
            or search_root.select_one("a[href]")
        )
        href = link_elem.get("href", base_url) if link_elem else base_url
        product_url = _offer_product_url(base_url, href, retailer)
        if not product_url:
            continue

        text = search_root.get_text(" ", strip=True).lower()
        in_stock = "out of stock" not in text and "currently unavailable" not in text

        return {
            "retailer":      retailer,
            "retailer_name": retailer_name,
            "price":         price,
            "url":           product_url,
            "in_stock":      in_stock,
            "title":         link_elem.get_text(" ", strip=True) if link_elem else "",
            "last_checked":  now_iso(),
        }
    return None


# ── DoMyOwn scraper ───────────────────────────────────────────────────────────
# Broad web discovery

def _serpapi_search(params: dict) -> Optional[dict]:
    if not SERPAPI_API_KEY:
        return None
    try:
        r = _session.get(
            "https://serpapi.com/search.json",
            params={**params, "api_key": SERPAPI_API_KEY},
            timeout=30,
        )
        if r.status_code != 200:
            log.info(f"  SerpApi HTTP {r.status_code}: {r.text[:100]}")
            return None
        return r.json()
    except Exception as e:
        log.info(f"  SerpApi failed: {e.__class__.__name__}: {str(e)[:100]}")
        return None


def _product_match_terms(product: dict) -> list[str]:
    terms = []
    values = [product.get("name"), product.get("search_query"), *product.get("alt_names", [])]
    for value in values:
        if not value:
            continue
        cleaned = re.sub(r"\([^)]*\)", "", value).strip().lower()
        if cleaned:
            terms.append(cleaned)
    if product.get("active_ingredient"):
        terms.append(str(product["active_ingredient"]).split("+")[0].strip().lower())
    return terms


def _matches_product(product: dict, title: str, source: str = "") -> bool:
    haystack = f"{title} {source}".lower()
    for term in _product_match_terms(product):
        tokens = [t for t in re.findall(r"[a-z0-9]+", term) if len(t) > 1]
        if len(tokens) == 1 and tokens[0] in haystack:
            return True
        if len(tokens) > 1 and sum(1 for t in tokens if t in haystack) >= min(2, len(tokens)):
            return True
    return False


def _shopping_offer(product: dict, item: dict) -> Optional[dict]:
    title = item.get("title") or ""
    source = item.get("source") or item.get("seller") or ""
    if not _matches_product(product, title, source):
        return None

    price = item.get("extracted_price")
    if price is None:
        price = parse_price(str(item.get("price", "")))
    if price is None:
        return None

    url = item.get("link") or item.get("product_link") or item.get("serpapi_product_api")
    if not url:
        return None

    retailer = retailer_key(source or url)
    return {
        "retailer": retailer,
        "retailer_name": source or retailer_name_from_url(url),
        "price": float(price),
        "url": append_affiliate(url, retailer),
        "in_stock": None,
        "source": "google_shopping",
        "title": title,
        "image": item.get("thumbnail") or item.get("serpapi_thumbnail"),
        "last_checked": now_iso(),
    }


def _shopping_store_offer(product: dict, item: dict, store: dict) -> Optional[dict]:
    title = store.get("title") or item.get("title") or ""
    source = store.get("name") or item.get("source") or item.get("seller") or ""
    if not _matches_product(product, title, source):
        return None

    price = store.get("extracted_price") or store.get("extracted_total")
    if price is None:
        price = parse_price(str(store.get("price") or store.get("total") or ""))
    if price is None:
        return None

    url = store.get("direct_link") or store.get("link")
    if not url or is_google_url(url):
        return None

    retailer = retailer_key(source or url)
    return {
        "retailer": retailer,
        "retailer_name": source or retailer_name_from_url(url),
        "price": float(price),
        "url": append_affiliate(url, retailer),
        "in_stock": None,
        "source": "google_shopping_store",
        "title": title,
        "image": item.get("thumbnail") or item.get("serpapi_thumbnail"),
        "last_checked": now_iso(),
    }


def _shopping_detail_offers(product: dict, item: dict) -> list[dict]:
    token = item.get("immersive_product_page_token")
    if not token:
        return []

    payload = _serpapi_search({
        "engine": "google_immersive_product",
        "page_token": token,
        "more_stores": "1",
        "gl": "us",
        "hl": "en",
    })
    if not payload:
        return []

    stores = payload.get("product_results", {}).get("stores", [])
    offers = []
    for store in stores:
        add_offer(offers, _shopping_store_offer(product, item, store))
    return offers


def scrape_google_shopping(product: dict) -> list[dict]:
    query = product.get("shopping_query") or product.get("search_query") or product["name"]
    payload = _serpapi_search({
        "engine": "google_shopping",
        "q": query,
        "gl": "us",
        "hl": "en",
        "num": SHOPPING_RESULT_LIMIT,
    })
    if not payload:
        return []

    offers = []
    shopping_results = payload.get("shopping_results", [])[:SHOPPING_RESULT_LIMIT]
    for item in shopping_results[:SHOPPING_DETAIL_RESULT_LIMIT]:
        for offer in _shopping_detail_offers(product, item):
            add_offer(offers, offer)

    for item in shopping_results:
        offer = _shopping_offer(product, item)
        if offer and is_google_url(offer.get("url", "")):
            offer["excluded"] = True
            offer["exclude_reason"] = "Google Shopping intermediary URL, merchant link not resolved"
        add_offer(offers, offer)
    return offers


def scrape_discovered_web_pages(product: dict) -> list[dict]:
    if not ENABLE_ORGANIC_DISCOVERY:
        return []

    query = f'"{product.get("search_query") or product["name"]}" buy price'
    payload = _serpapi_search({
        "engine": "google",
        "q": query,
        "gl": "us",
        "hl": "en",
        "num": ORGANIC_RESULT_LIMIT,
    })
    if not payload:
        return []

    offers = []
    for result in payload.get("organic_results", [])[:ORGANIC_RESULT_LIMIT]:
        url = result.get("link")
        title = result.get("title") or ""
        if not url or not _matches_product(product, title, result.get("snippet", "")):
            continue

        time.sleep(RATE_LIMIT)
        html = browser_fetch(url, timeout=ORGANIC_FETCH_TIMEOUT)
        if not html:
            continue
        retailer = retailer_key(url)
        offer = _extract_from_soup(
            BeautifulSoup(html, "lxml"),
            url,
            retailer,
            retailer_name_from_url(url),
        )
        if offer:
            offer["source"] = "google_organic"
            add_offer(offers, offer)
    return offers


def scrape_web_discovery(product: dict) -> list[dict]:
    if not ENABLE_SERPAPI_DISCOVERY:
        return []
    if not SERPAPI_API_KEY:
        return []

    offers = []
    for offer in scrape_google_shopping(product):
        add_offer(offers, offer)
    for offer in scrape_discovered_web_pages(product):
        add_offer(offers, offer)
    return offers


KNOWN_RETAILERS = [
    {
        "key": "solutions",
        "name": "Solutions Pest & Lawn",
        "base": "https://www.solutionspestcontrol.com",
        "search": "https://www.solutionspestcontrol.com/search?q={query}&type=product",
    },
    {
        "key": "domyown",
        "name": "DoMyOwn",
        "base": "https://www.domyown.com",
        "search": "https://www.domyown.com/search?w={query}",
    },
    {
        "key": "seed-world",
        "name": "Seed World",
        "base": "https://www.seedworldusa.com",
        "search": "https://www.seedworldusa.com/search?q={query}",
    },
    {
        "key": "seed-barn",
        "name": "Seed Barn",
        "base": "https://seedbarn.com",
        "search": "https://seedbarn.com/search?q={query}",
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
        "key": "yard-mastery",
        "name": "Yard Mastery",
        "base": "https://yardmastery.com",
        "search": "https://yardmastery.com/search?q={query}",
    },
    {
        "key": "gci-turf-academy",
        "name": "GCI Turf Academy",
        "base": "https://gciturfacademy.com",
        "search": "https://gciturfacademy.com/search?q={query}",
    },
    {
        "key": "lawn-synergy",
        "name": "Lawn Synergy",
        "base": "https://lawnsynergy.com",
        "search": "https://lawnsynergy.com/search?q={query}",
    },
]


def scrape_known_retailers(product: dict) -> list[dict]:
    if not ENABLE_KNOWN_RETAILER_SEARCH:
        return []

    offers = []
    query = product.get("search_query") or product["name"]
    encoded = urllib.parse.quote_plus(query)
    for retailer in KNOWN_RETAILERS[:KNOWN_RETAILER_LIMIT]:
        url = retailer["search"].format(query=encoded)
        html = browser_fetch(url, timeout=ORGANIC_FETCH_TIMEOUT)
        if not html:
            continue
        offer = _extract_from_soup(
            BeautifulSoup(html, "lxml"),
            retailer["base"],
            retailer["key"],
            retailer["name"],
        )
        if offer and _matches_product(product, offer.get("title", ""), retailer["name"]):
            offer["source"] = "known_retailer_search"
            add_offer(offers, offer)
        time.sleep(0.5)
    return offers


def load_product_sources(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"schema_version": "1.0", "updated_at": None, "products": {}}

    if "products" not in data:
        data["products"] = {}
    return data


def _source_entries(source_map: dict, product_id: int) -> list[dict]:
    entries = []
    for source in source_map.get("products", {}).get(str(product_id), []):
        url = source.get("url", "")
        if not url or is_google_url(url) or is_bad_product_url(url):
            continue
        if source.get("verified") is False:
            continue
        source_type = source.get("source_type", "product")
        if source_type != "product":
            continue
        entries.append(source)

    if not entries or SAVED_SOURCE_LIMIT <= 0 or len(entries) <= SAVED_SOURCE_LIMIT:
        return entries

    cursors = source_map.setdefault("refresh_cursors", {})
    start = int(cursors.get(str(product_id), 0)) % len(entries)
    selected = [entries[(start + offset) % len(entries)] for offset in range(SAVED_SOURCE_LIMIT)]
    cursors[str(product_id)] = (start + SAVED_SOURCE_LIMIT) % len(entries)
    return selected


def scrape_saved_sources(product: dict, source_map: dict) -> list[dict]:
    offers = []
    for source in _source_entries(source_map, product["id"]):
        url = source.get("url")
        if not url or is_google_url(url):
            continue
        html = fetch_saved_source(url)
        if not html:
            continue

        retailer = source.get("retailer") or retailer_key(url)
        retailer_name = source.get("retailer_name") or retailer_name_from_url(url)
        offer = _extract_from_soup(
            BeautifulSoup(html, "lxml"),
            url,
            retailer,
            retailer_name,
        )
        if offer:
            match_title = offer.get("title") or source.get("title") or ""
            if not source.get("manual_verified") and not _matches_product(product, match_title, url):
                log.info(f"  Saved source mismatch skipped: {match_title[:70]} @ {url[:80]}")
                continue
            if is_bad_product_url(offer.get("url", "")) and not is_bad_product_url(url):
                offer["url"] = append_affiliate(url, retailer)
                if source.get("title"):
                    offer["title"] = source["title"]
            offer["source"] = "saved_product_source"
            offer["image"] = source.get("image") or offer.get("image")
            add_offer(offers, offer)
        time.sleep(0.5)
    return offers


def update_product_sources(source_map: dict, results: list[dict]) -> dict:
    products = source_map.setdefault("products", {})
    for product in results:
        product_id = str(product["id"])
        existing = {
            urllib.parse.urldefrag(src.get("url", ""))[0].rstrip("/"): src
            for src in products.get(product_id, [])
            if src.get("url") and not is_google_url(src.get("url", ""))
        }

        for offer in product.get("offers", []):
            url = offer.get("url", "")
            if not url or is_google_url(url) or offer.get("excluded"):
                continue
            normalized = urllib.parse.urldefrag(url)[0].rstrip("/")
            previous_source = existing.get(normalized, {})
            updated_source = {
                "url": normalized,
                "retailer": offer.get("retailer") or retailer_key(url),
                "retailer_name": offer.get("retailer_name") or retailer_name_from_url(url),
                "title": offer.get("title") or product.get("name"),
                "image": offer.get("image"),
                "last_seen": now_iso(),
            }
            for key in ("verified", "manual_verified", "price_verified", "source_type"):
                if key in previous_source:
                    updated_source[key] = previous_source[key]
            existing[normalized] = updated_source

        products[product_id] = list(existing.values())[:MAX_SAVED_SOURCES_PER_PRODUCT]

    source_map["updated_at"] = now_iso()
    return source_map


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
        f"https://www.domyown.com/catalogsearch/result/?q={encoded}",
    ]:
        html = browser_fetch(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        title = (soup.title.string or "") if soup.title else ""
        # If we landed on the home page the URL didn't work — skip it
        if "do it yourself" in title.lower() or "pest control products" in title.lower():
            log.info(f"  DoMyOwn: search URL redirected to home page, skipping")
            time.sleep(1.0)
            continue
        result = _extract_from_soup(soup, "https://www.domyown.com", "domyown", "DoMyOwn")
        if result:
            return result
        log.info(f"  DoMyOwn: page loaded but no price found in HTML")
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
        f"https://www.solutionspestcontrol.com/search?q={encoded}&type=product",
        f"https://www.solutionspestcontrol.com/search?q={encoded}",
    ]:
        html = browser_fetch(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        title = (soup.title.string or "") if soup.title else ""
        if not title:
            log.info(f"  Solutions: got empty title, skipping")
            time.sleep(1.0)
            continue
        result = _extract_from_soup(soup, "https://www.solutionspestcontrol.com", "solutions", "Solutions Pest & Lawn")
        if result:
            return result
        log.info(f"  Solutions: page '{title[:60]}' loaded but no price found")
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

    if REQUIRE_WEB_DISCOVERY and ENABLE_SERPAPI_DISCOVERY and not SERPAPI_API_KEY:
        log.error("SERPAPI_API_KEY is required for broad web price discovery.")
        sys.exit(1)

    script_dir    = os.path.dirname(os.path.abspath(__file__))
    repo_root     = os.path.dirname(script_dir)
    products_path = os.path.join(repo_root, "products.json")
    prices_path   = os.path.join(repo_root, "prices.json")
    alerts_path   = os.path.join(repo_root, "price-alerts.json")
    sources_path  = os.path.join(repo_root, "product_sources.json")

    with open(products_path) as f:
        catalog = json.load(f)
    source_map = load_product_sources(sources_path)

    try:
        with open(prices_path) as f:
            existing_data = json.load(f)
        stale_map = {p["id"]: p for p in existing_data.get("products", [])}
    except FileNotFoundError:
        existing_data = {"products": []}
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

            saved_offers = scrape_saved_sources(product, source_map)
            for offer in saved_offers:
                add_offer(offers, offer)
            log.info(f"  Saved    {len(saved_offers)} cached merchant offers")

            # DoMyOwn — all specialty categories
            if ENABLE_DIRECT_RETAILER_SEARCH and cat != "fertilizer-consumer":
                time.sleep(RATE_LIMIT)
                r = scrape_domyown(product)
                if add_offer(offers, r):
                    log.info(f"  DoMyOwn  ${r['price']:.2f}")
                else:
                    log.info(f"  DoMyOwn  no result")
            elif not ENABLE_DIRECT_RETAILER_SEARCH:
                log.info("  DoMyOwn  skipped (direct retailer search disabled)")

            # Solutions Pest & Lawn — herbicides, fungicides, insecticides, PGRs
            if ENABLE_DIRECT_RETAILER_SEARCH and cat in ("fungicide", "insecticide", "pre-emergent", "post-emergent", "pgr"):
                time.sleep(RATE_LIMIT)
                r = scrape_solutions(product)
                if add_offer(offers, r):
                    log.info(f"  Solutions ${r['price']:.2f}")
                else:
                    log.info(f"  Solutions no result")
            elif not ENABLE_DIRECT_RETAILER_SEARCH:
                log.info("  Solutions skipped (direct retailer search disabled)")

            known_offers = scrape_known_retailers(product)
            for offer in known_offers:
                add_offer(offers, offer)
            log.info(f"  Known    {len(known_offers)} direct retailer offers")

            # Web discovery via Google Shopping/search API for broader price coverage.
            web_offers = scrape_web_discovery(product)
            for offer in web_offers:
                add_offer(offers, offer)
            if ENABLE_SERPAPI_DISCOVERY and SERPAPI_API_KEY:
                log.info(f"  Web      {len(web_offers)} priced offers")
            else:
                log.info("  Web      skipped (SerpApi discovery disabled)")

            # Amazon — all products
            time.sleep(RATE_LIMIT)
            r = amazon_result(product)
            if add_offer(offers, r):
                price_str = f"${r['price']:.2f}" if r.get("price") else "(link only)"
                log.info(f"  Amazon   {price_str}")

            best = select_best_offer(product, offers)

            if (not offers or best is None) and pid in stale_map and stale_map[pid].get("best_price"):
                entry = stale_map[pid].copy()
                entry["stale"] = True
                entry["stale_reason"] = "no eligible priced best offer in latest run"
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

    apply_offer_quality_filters(results)
    results = preserve_last_good_products(results, stale_map)
    source_map = update_product_sources(source_map, results)

    generated_at = now_iso()
    output = {
        "schema_version": "1.0",
        "generated_at":   generated_at,
        "product_count":  len(results),
        "products":       results,
    }
    alerts_output = build_price_alerts(stale_map, results, generated_at)

    with open(prices_path, "w") as f:
        json.dump(output, f, indent=2)
    with open(alerts_path, "w") as f:
        json.dump(alerts_output, f, indent=2)
    with open(sources_path, "w") as f:
        json.dump(source_map, f, indent=2)

    found = sum(1 for p in results if p.get("best_price"))
    log.info(f"\nDone. {found}/{len(results)} products have a best price.")
    log.info(f"Written to {prices_path}")
    log.info(f"Written to {alerts_path} ({alerts_output['alert_count']} alerts)")
    log.info(f"Written to {sources_path}")

    min_priced = int(os.getenv("MIN_PRICED_PRODUCTS", "1"))
    if found < min_priced:
        log.error(f"Only {found}/{len(results)} products have prices; expected at least {min_priced}.")
        sys.exit(1)


if __name__ == "__main__":
    run()
