#!/usr/bin/env python3
"""
Lawn Dominator Price Scraper
Runs every 4 hours via GitHub Actions. Finds best prices across retailers
and writes prices.json, which is served as a static file by GitHub Pages.

Retailers:
  - DoMyOwn.com           (specialty lawn chemical retailer — Playwright)
  - Solutions Pest & Lawn (specialty retailer — Playwright)
  - Amazon                (Creators API if credentials set, otherwise affiliate link)

GitHub Secrets:
  AMAZON_AFFILIATE_TAG          - your Amazon Associates tag
  AMAZON_CREATOR_CREDENTIAL_ID  - Creators API credential ID (optional, enables real prices)
  AMAZON_CREATOR_SECRET         - Creators API credential secret (optional)
  AMAZON_CREATOR_VERSION        - Creators API version, defaults to 3.1
  AMAZON_CREATOR_THROTTLING     - Creators API request delay, defaults to 1 second
  KEEPA_API_KEY                 - Keepa API key (optional, enables Amazon prices)
  DOMYOWN_AFFILIATE_ID          - DoMyOwn affiliate ID (optional)
"""

import json
import copy
import os
import re
import sys
import time
import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Browser

VENDOR_DIR = os.path.join(os.path.dirname(__file__), "vendor")
if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Credentials ───────────────────────────────────────────────────────────────
SERPAPI_API_KEY   = os.getenv("SERPAPI_API_KEY", "")
AMAZON_TAG        = os.getenv("AMAZON_AFFILIATE_TAG", "lawndominator-20")
AMAZON_CREATOR_CREDENTIAL_ID = os.getenv("AMAZON_CREATOR_CREDENTIAL_ID", "")
AMAZON_CREATOR_SECRET = os.getenv("AMAZON_CREATOR_SECRET", "")
AMAZON_CREATOR_VERSION = os.getenv("AMAZON_CREATOR_VERSION") or "3.1"
KEEPA_API_KEY     = os.getenv("KEEPA_API_KEY", "")
KEEPA_DOMAIN      = int(os.getenv("KEEPA_DOMAIN", "1"))  # 1 = amazon.com
DOMYOWN_AFFID     = os.getenv("DOMYOWN_AFFILIATE_ID", "")

RATE_LIMIT = 2.0   # seconds between Playwright page loads
SHOPPING_RESULT_LIMIT = int(os.getenv("SHOPPING_RESULT_LIMIT", "10"))
SHOPPING_DETAIL_RESULT_LIMIT = int(os.getenv("SHOPPING_DETAIL_RESULT_LIMIT", "0"))
ORGANIC_RESULT_LIMIT = int(os.getenv("ORGANIC_RESULT_LIMIT", "3"))
ENABLE_SERPAPI_DISCOVERY = os.getenv("ENABLE_SERPAPI_DISCOVERY", "0") == "1"
ENABLE_ORGANIC_DISCOVERY = os.getenv("ENABLE_ORGANIC_DISCOVERY", "1") != "0"
REQUIRE_WEB_DISCOVERY = os.getenv("REQUIRE_WEB_DISCOVERY", "0") == "1"
ENABLE_DIRECT_RETAILER_SEARCH = os.getenv("ENABLE_DIRECT_RETAILER_SEARCH", "0") == "1"

# Stop the sweep cleanly before the CI job timeout kills it. A killed job wrote
# nothing at all; a budgeted one commits everything it managed to refresh.
# Keep this comfortably under `timeout-minutes` in price-scraper.yml.
SWEEP_TIME_BUDGET_SECONDS = int(os.getenv("SWEEP_TIME_BUDGET_SECONDS", "4200"))
# Flush the feed to disk this often, so a hard kill still leaves fresh prices.
CHECKPOINT_EVERY = int(os.getenv("CHECKPOINT_EVERY", "10"))
# Loudly flag a feed whose oldest merchant price has rotted past this age.
MAX_OFFER_AGE_HOURS = float(os.getenv("MAX_OFFER_AGE_HOURS", "48"))
ENABLE_KNOWN_RETAILER_SEARCH = os.getenv("ENABLE_KNOWN_RETAILER_SEARCH", "0") == "1"
ORGANIC_FETCH_TIMEOUT = int(os.getenv("ORGANIC_FETCH_TIMEOUT", "12000"))
KNOWN_RETAILER_LIMIT = int(os.getenv("KNOWN_RETAILER_LIMIT", "8"))
SAVED_SOURCE_LIMIT = int(os.getenv("SAVED_SOURCE_LIMIT", "12"))
MAX_SAVED_SOURCES_PER_PRODUCT = int(os.getenv("MAX_SAVED_SOURCES_PER_PRODUCT", "50"))
MIN_CHEMICAL_PRICE = float(os.getenv("MIN_CHEMICAL_PRICE", "10"))
MIN_SOIL_AMENDMENT_PRICE = float(os.getenv("MIN_SOIL_AMENDMENT_PRICE", "5"))
REPEATED_PRICE_PRODUCT_LIMIT = int(os.getenv("REPEATED_PRICE_PRODUCT_LIMIT", "8"))
MIN_ALERT_DROP_PERCENT = float(os.getenv("MIN_ALERT_DROP_PERCENT", "5"))
PRICE_ALERT_RETENTION_DAYS = int(os.getenv("PRICE_ALERT_RETENTION_DAYS", "7"))
# The old absolute MIN_PRICED_PRODUCTS=1 floor passed as long as a single
# product got a price, so a run that broke extraction for 95% of the catalog
# would still commit a gutted prices.json without failing CI. This adds a
# percentage-of-catalog floor alongside it; the run must clear both.
MIN_PRICED_PRODUCTS_PERCENT = float(os.getenv("MIN_PRICED_PRODUCTS_PERCENT", "50"))

# Global browser instance — shared across all scrape calls
_browser: Optional[Browser] = None
_amazon_creators_disabled = False


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
        url = canonical_product_url(url)
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


def canonical_product_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path
    asin = amazon_asin_from_url(url)
    if ("amazon." in host or host.endswith("amzn.to")) and asin:
        return f"https://www.amazon.com/dp/{asin}"
    return urllib.parse.urldefrag(url)[0].rstrip("/")


def _is_amazon_url(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    return host == "amazon.com" or host.endswith(".amazon.com") or host == "amzn.to"


def _same_product_path(first_url: str, second_url: str) -> bool:
    first = urllib.parse.urlparse(first_url)
    second = urllib.parse.urlparse(second_url)
    return (
        first.netloc.lower().removeprefix("www.") == second.netloc.lower().removeprefix("www.")
        and urllib.parse.unquote(first.path).rstrip("/").lower()
        == urllib.parse.unquote(second.path).rstrip("/").lower()
    )


def _offer_matches_source_url(source_url: str, offer_url: str) -> bool:
    if not source_url or not offer_url:
        return False
    source = canonical_product_url(source_url)
    offer = canonical_product_url(offer_url)
    return source == offer or _same_product_path(source, offer)


def amazon_asin_from_url(url: str) -> Optional[str]:
    path = urllib.parse.urlparse(url).path
    match = re.search(r"/(?:[^/]+/)?(?:dp|gp/product)/([A-Z0-9]{10})", path, re.I)
    return match.group(1).upper() if match else None


def is_bad_product_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parsed.query.lower()
    bad_path_parts = (
        "/cart", "/checkout", "/account", "/login", "/search", "/collections/",
        "/category/", "/categories/", "/catalogsearch/", "/wishlist", "/write-review",
    )
    if any(part in path for part in bad_path_parts):
        return True
    if ("amazon.com" in host or host.endswith("amzn.to")) and path.rstrip("/") == "/s":
        return True
    if "search" in query or query.startswith("k="):
        return True
    if "ebay." in host and path.startswith("/sch"):
        return True
    if "mkrittenhouse.com" in host:
        return True
    if "keystonepestsolutions.com" in host and path.rstrip("/") in {"", "/index.php"}:
        return True
    if "mycorrhizalonline.com" in host and path.rstrip("/") in {"", "/"}:
        return True
    if path.endswith("/online-shop-2.html"):
        return True
    return "notify" in path or "notify" in query


def offer_key(offer: dict) -> tuple:
    normalized_url = canonical_product_url(offer.get("url", ""))
    return (offer.get("retailer"), normalized_url, offer.get("price"))


def add_offer(offers: list[dict], offer: Optional[dict]) -> bool:
    if not offer:
        return False
    if any(offer_key(existing) == offer_key(offer) for existing in offers):
        return False
    offers.append(offer)
    return True


def min_price_for_product(product: dict) -> float:
    category = product.get("category")
    product_id = int(product.get("id", 0))
    product_minimums = {
        36: 80,  # T-Nex 1AS gallon false scrape guard
    }
    if product_id in product_minimums:
        return product_minimums[product_id]
    equipment_minimums = {
        310: 300,  # LESCO 101186 high wheel
        311: 300,  # LESCO 092807 50 lb
        314: 300,  # Spyker P70 commercial drop
        315: 300,  # Spyker Ergo-PRO
        322: 150,
        323: 150,
        324: 150,
        330: 150,
        331: 150,
        332: 150,
        333: 150,
        335: 500,
        344: 300,
        345: 500,
        346: 100,
        348: 100,
        349: 100,
        351: 150,
        353: 250,
    }
    if is_equipment_category(category) and product_id in equipment_minimums:
        return equipment_minimums[product_id]
    if category == "spreader-handheld":
        return 10
    if category in {"spreader-push", "spreader-tow"}:
        return 20
    if category == "sprayer-backpack":
        return 100
    if product.get("category") in {"soil-amendment", "micronutrient", "fertilizer-consumer"}:
        return MIN_SOIL_AMENDMENT_PRICE
    return MIN_CHEMICAL_PRICE


def max_price_for_product(product: dict) -> Optional[float]:
    """Ceiling above which an offer is not a real consumer purchase.

    Some product pages list a homeowner size alongside a commercial drum, and
    the bulk listing can win best-price on unit cost: Specticle FLO published a
    $2,247.32 128 fl oz gallon as the best price of an 18 fl oz bottle, because
    $17.56/oz beats the bottle's $18.89/oz. Nobody using this app is buying the
    gallon.

    Per product rather than global, because the right ceiling is a fact about
    the product. Equipment is legitimately expensive (a LESCO high wheel is
    $700), so a blanket cap would delete real prices. Add an entry here when a
    product's page carries a bulk size the app should ignore.
    """
    product_maximums = {
        4: 500,  # Spectacle Flo: 18 fl oz bottle, not the $2,247 gallon
    }
    return product_maximums.get(int(product.get("id", 0)))


def _exceeds_max_price(product: dict, offer: dict) -> bool:
    ceiling = max_price_for_product(product)
    if ceiling is None:
        return False
    try:
        return float(offer["price"]) > ceiling
    except (TypeError, ValueError, KeyError):
        return False


def _valid_price(offer: dict) -> Optional[float]:
    try:
        return float(offer["price"])
    except (KeyError, TypeError, ValueError):
        return None


def _valid_unit_price(offer: dict) -> Optional[float]:
    try:
        unit_price = float(offer["price_per_unit"])
        quantity = float(offer["package_quantity"])
    except (KeyError, TypeError, ValueError):
        return None
    if unit_price <= 0 or quantity <= 0 or not offer.get("package_unit"):
        return None
    return unit_price


def select_best_offer(product: dict, offers: list[dict]) -> Optional[dict]:
    priced = [
        o for o in offers
        if o.get("price") is not None
        and not o.get("excluded")
        and o.get("in_stock") is not False
        and not is_google_url(o.get("url", ""))
        and not is_bad_product_url(o.get("url", ""))
        and float(o["price"]) >= min_price_for_product(product)
        and not _exceeds_max_price(product, o)
    ]
    comparable_by_unit: dict[str, list[dict]] = {}
    for offer in priced:
        if _valid_unit_price(offer) is None:
            continue
        comparable_by_unit.setdefault(str(offer.get("package_unit")), []).append(offer)

    comparable_groups = [
        group for group in comparable_by_unit.values()
        if len(group) >= 2
    ]
    if comparable_groups:
        largest_group = max(comparable_groups, key=len)
        largest_group.sort(key=lambda o: (_valid_unit_price(o), _valid_price(o)))
        return largest_group[0]

    priced.sort(key=lambda o: _valid_price(o))
    return priced[0] if priced else None


def _offer_size_text(offer: dict) -> str:
    return " ".join(str(offer.get(key) or "") for key in ("title", "url")).lower()


def _package(quantity: float, unit: str) -> dict:
    if unit == "fl oz":
        if quantity == 64:
            label = "64 fl oz"
        elif quantity % 128 == 0:
            label = f"{quantity / 128:g} gal"
        elif quantity > 128:
            label = f"{quantity / 128:g} gal"
        elif quantity == 32:
            label = "32 fl oz"
        else:
            label = f"{quantity:g} fl oz"
    else:
        label = f"{quantity:g} {unit}"
    return {
        "package_quantity": quantity,
        "package_unit": unit,
        "package_label": label,
    }


def manual_package_size(product: dict, offer: dict) -> Optional[dict]:
    url = str(offer.get("url") or "").lower()
    title = str(offer.get("title") or "").lower()
    retailer = str(offer.get("retailer") or "").lower()
    product_id = product.get("id")
    text = f"{title} {url}"

    if product_id == 1 and ("prodiamine" in text or "csi83013356" in url):
        if retailer in {
            "solutions",
            "pestmanagementsupply",
            "yardmastery",
            "gci-turf",
            "domyown",
            "amazon",
            "pestrong",
        }:
            return _package(5.0, "lb")

    if product_id == 2:
        if "dithiopyr-2l" in url:
            return _package(128.0, "fl oz")
        if "dithiopyr-2-ew" in url:
            return _package(320.0, "fl oz")
        if (
            "dimension-2ew-herbicide" in url
            or "dimension-2ew" in url
            or "p-1494" in url
            or "b0051gxxpw" in url
        ):
            return _package(64.0, "fl oz")

    if product_id == 3 and ("ronstar" in text or "oxadiazon-2g" in url or "oxadiazon 2g" in title):
        return _package(50.0, "lb")

    if product_id == 5 and "pendulum-2g" in url:
        if "20-lbs" in url or "20 lb" in title or "20 lbs" in title:
            return _package(20.0, "lb")
        return _package(40.0, "lb")

    if product_id == 6 and ("gallery" in text or "isoxaben" in text or "b004jx6qo8" in url):
        return _package(1.0, "lb")

    if product_id == 7 and ("specticle-g" in url or "specticle g" in title):
        return _package(50.0, "lb")

    if product_id == 4 and ("specticle-flo" in url or "specticle flo" in title or "spectacle flo" in title):
        if "gallon" in text or "1-gal" in url:
            return _package(128.0, "fl oz")
        return _package(18.0, "fl oz")

    if product_id == 8 and ("atrazine" in text or "st-augustine-weed-killer" in url):
        return _package(32.0, "fl oz")

    if product_id == 9 and ("pendulum-aquacap" in url or "pendulum aquacap" in title or "pendulum aqua cap" in title):
        if "15-gal" in url or "15 gal" in title:
            return _package(1920.0, "fl oz")
        return _package(320.0, "fl oz")

    if product_id == 15 and "celsius" in text:
        if "10oz" in text or "10 oz" in text or "10 ounce" in text:
            return _package(10.0, "fl oz")
        if retailer == "domyown" and (offer.get("price") or 0) and float(offer["price"]) > 100:
            return _package(10.0, "fl oz")
        return _package(0.226, "fl oz")

    if product_id == 17 and ("drive-xlr8" in url or "drive xlr8" in title):
        return _package(64.0, "fl oz")

    if product_id == 16 and ("certainty" in text or "sulfosulfuron" in text or "sertay" in text):
        return _package(1.25, "fl oz")

    if product_id == 18 and ("sedgehammer" in text or "halosulfuron" in text):
        return _package(13.5, "g")

    if product_id == 19 and ("speedzone" in text or "speed-zone" in url):
        if retailer in {"diypestcontrol"} or (offer.get("price") is not None and float(offer["price"]) < 70):
            return _package(32.0, "fl oz")
        return _package(128.0, "fl oz")

    if product_id == 20 and (
        "manor" in text
        or "msm-turf" in url
        or "msm turf" in title
        or "amtide-msm" in url
        or "b0cb96f141" in url
    ):
        return _package(8.0, "fl oz")

    if product_id == 21 and ("tenacity" in text or "mesotrione" in text):
        if "0-5-gallon" in url:
            return _package(64.0, "fl oz")
        return _package(8.0, "fl oz")

    if product_id == 22 and ("turflon" in text or "triclopyr" in text):
        if "gal" in text or (offer.get("price") is not None and float(offer["price"]) > 120):
            return _package(128.0, "fl oz")
        return _package(8.0, "fl oz")

    if product_id == 23 and ("dismiss" in text or "sulfentrazone" in text):
        if "64" in text or (offer.get("price") is not None and float(offer["price"]) > 150):
            return _package(64.0, "fl oz")
        if "sulfentrazone-4l-select" in url or (offer.get("price") is not None and float(offer["price"]) < 75):
            return _package(6.0, "fl oz")
        return _package(6.0, "fl oz")

    if product_id == 24 and ("pylex" in text or "topramezone" in text):
        return _package(4.0, "fl oz")

    if product_id == 26 and "q4" in text:
        return _package(32.0, "fl oz")

    if product_id == 27 and ("trimec" in text or "2-5" in url):
        if "2-5" in url or "2.5" in text:
            return _package(320.0, "fl oz")
        return _package(128.0, "fl oz")

    if product_id == 25 and ("msma" in text or "target-6-plus" in url):
        if "5 gallons" in title or "5 gallon" in title:
            return _package(640.0, "fl oz")
        return _package(320.0, "fl oz")

    if product_id == 28 and ("revolver" in text or "foramsulfuron" in text):
        if "87-oz" in url or "87 oz" in title:
            return _package(87.0, "fl oz")
        return _package(32.0, "fl oz")

    if product_id == 29 and ("katana" in text or "flazasulfuron" in text):
        return _package(5.0, "fl oz")

    if product_id == 35 and ("primo" in text or "trinexapac" in text):
        if "1-gallon" in url or "1 gallon" in title:
            return _package(128.0, "fl oz")
        if retailer == "domyown" and (offer.get("price") or 0) and float(offer["price"]) > 200:
            return _package(128.0, "fl oz")
        return _package(4.0, "fl oz")

    if product_id == 36 and ("t-nex" in text or "tnex" in text or "trinexapac" in text):
        if "2-5-gallon" in url or "2.5 gallon" in title or (offer.get("price") is not None and float(offer["price"]) > 250):
            return _package(320.0, "fl oz")
        return _package(128.0, "fl oz")

    if product_id == 37 and ("anuew" in text or "prohexadione" in text):
        if "2.5" in text or (offer.get("price") is not None and float(offer["price"]) > 500):
            return _package(320.0, "fl oz")
        if "1.5" in text or "seed-barn" in url:
            return _package(1.5, "lb")
        return _package(64.0, "fl oz")

    if product_id == 38 and ("trimmit" in text or "paclobutrazol" in text):
        if "2.5" in text or (offer.get("price") is not None and float(offer["price"]) > 500):
            return _package(320.0, "fl oz")
        return _package(128.0, "fl oz")

    if product_id == 39 and ("cutless" in text or "flurprimidol" in text):
        if "40 lb" in text or "40-lb" in url:
            return _package(40.0, "lb")
        return _package(128.0, "fl oz")

    if product_id == 40 and ("proxy" in text or "embark" in text or "mefluidide" in text):
        return _package(128.0, "fl oz")

    if product_id == 41 and ("pramaxis" in text or "trinexapac" in text):
        if "2.5" in text or (offer.get("price") is not None and float(offer["price"]) > 250):
            return _package(320.0, "fl oz")
        if "gal" in text or (offer.get("price") is not None and float(offer["price"]) > 100):
            return _package(128.0, "fl oz")
        return _package(8.0, "fl oz")

    if product_id == 50 and ("propiconazole" in text or "banner" in text or "ppz" in text):
        price = float(offer["price"]) if offer.get("price") is not None else 0
        if "2-5" in url or "2.5" in text or price > 250:
            return _package(320.0, "fl oz")
        if price < 40:
            return _package(16.0, "fl oz")
        return _package(32.0, "fl oz")

    if product_id == 51 and ("heritage" in text or "azoxystrobin" in text or "azoxy" in text):
        if "lb" in text or "heritage-action" in url:
            return _package(1.0, "lb")
        if "32" in text or "2sc" in text:
            return _package(32.0, "fl oz")
        return _package(4.0, "fl oz")

    if product_id == 52 and ("headway" in text):
        if "gal" in text:
            return _package(128.0, "fl oz")
        return _package(30.0, "lb")

    if product_id == 53 and "armada" in text:
        return _package(2.0, "lb")

    if product_id == 54 and "pillar" in text:
        return _package(43.5, "fl oz")

    if product_id == 55 and ("cleary" in text or "3336" in text or "thiophanate" in text):
        if "30" in text and ("lb" in text or "pound" in text):
            return _package(30.0, "lb")
        if "8" in text and "oz" in text:
            return _package(8.0, "fl oz")
        return _package(32.0, "fl oz")

    if product_id == 56 and ("eagle" in text or "myclobutanil" in text):
        if "gallon" in text or "1-gal" in url:
            return _package(128.0, "fl oz")
        return _package(16.0, "fl oz")

    if product_id == 57 and ("daconil" in text or "chlorothalonil" in text or "echo" in text):
        if "40-lb" in url or "40 lb" in title:
            return _package(40.0, "lb")
        if "5-lb" in url or "5 lb" in title:
            return _package(5.0, "lb")
        if "2-5" in url or "2.5" in text:
            return _package(320.0, "fl oz")
        return _package(16.0, "fl oz")

    if product_id == 58 and "emerald" in text:
        return _package(0.49, "lb")

    if product_id == 59 and ("medallion" in text or "fludioxonil" in text):
        return _package(8.0, "fl oz")

    if product_id == 60 and ("subdue" in text or "mefenoxam" in text):
        if "25 lb" in text or "25-lb" in url:
            return _package(25.0, "lb")
        return _package(128.0, "fl oz")

    if product_id == 61 and ("velista" in text or "penthiopyrad" in text):
        return _package(22.0, "fl oz")

    if product_id == 70 and "acelepryn" in text:
        if offer.get("price") is not None and float(offer["price"]) > 500:
            return _package(128.0, "fl oz")
        return _package(4.0, "fl oz")

    if product_id == 71 and "acelepryn" in text:
        return _package(25.0, "lb")

    if product_id == 72 and ("merit" in text or "imidacloprid" in text):
        return _package(30.0, "lb")

    if product_id == 73 and ("dylox" in text or "trichlorfon" in text):
        return _package(30.0, "lb")

    if product_id == 74 and ("bifen" in text or "bifenthrin" in text):
        if offer.get("price") is not None and float(offer["price"]) < 35:
            return _package(32.0, "fl oz")
        return _package(128.0, "fl oz")

    if product_id == 75 and ("talstar" in text or "bifenthrin 0.2" in text):
        return _package(25.0, "lb")

    if product_id == 76 and "meridian" in text:
        return _package(40.0, "lb")

    if product_id == 77 and "arena" in text:
        return _package(30.0, "lb")

    if product_id == 78 and ("demand" in text or "lambda" in text):
        if "gal" in text:
            return _package(128.0, "fl oz")
        return _package(8.0, "fl oz")

    if product_id == 79 and "zylam" in text:
        return _package(32.0, "fl oz")

    if product_id == 80 and ("avid" in text or "abamectin" in text or "ardent" in text):
        if "gallon" in text or "1 gal" in text or (offer.get("price") is not None and float(offer["price"]) > 300):
            return _package(128.0, "fl oz")
        if "quart" in text or "1 qt" in text:
            return _package(32.0, "fl oz")
        return _package(8.0, "fl oz")

    if product_id == 81 and "movento" in text:
        return _package(32.0, "fl oz")

    if product_id == 82 and "mainspring" in text:
        return _package(16.0, "fl oz")

    if product_id == 83 and "forbid" in text:
        return _package(8.0, "fl oz")

    if product_id == 84 and "tetrasan" in text:
        return _package(1.0, "lb")

    if product_id == 85 and "kontos" in text:
        if "32" in text or (offer.get("price") is not None and float(offer["price"]) > 500):
            return _package(32.0, "fl oz")
        return _package(8.0, "fl oz")

    if product_id == 86 and "tristar" in text:
        if "quart" in text:
            return _package(32.0, "fl oz")
        if "gallon" in text or (offer.get("price") is not None and float(offer["price"]) > 500):
            return _package(128.0, "fl oz")
        return _package(8.0, "fl oz")

    if product_id == 115 and "hydretain" in text:
        if "granular" in text or "3-lb" in url or "3 lbs" in text:
            return _package(3.0, "lb")
        return _package(32.0, "fl oz")

    if product_id == 116 and "revolution" in text:
        return _package(320.0, "fl oz")

    if product_id == 117 and ("mycoapply" in text or "mycorrhizal" in text):
        return _package(20.0, "lb")

    if product_id == 118 and "feature" in text:
        return _package(2.5, "lb")

    if product_id == 131 and ("pgf-balanced" in text or "pgf balanced" in text):
        return _package(18.0, "lb")

    if product_id == 135 and ("black-gypsum" in text or "black gypsum" in text):
        return _package(50.0, "lb")

    if product_id == 137 and ("dirt-booster" in text or "dirt booster" in text):
        return _package(20.0, "lb")

    if product_id == 138 and ("humic-dg-charx" in text or "humic dg charx" in text or "charx" in text):
        return _package(40.0, "lb")

    if product_id == 156 and ("greene-effect" in text or "greene effect" in text or "green effect" in text):
        if "b098zr65hx" in url or "2 gallon" in text or "2-gallon" in text:
            return _package(256.0, "fl oz")
        if "5 gallon" in text or "5-gallon" in text:
            return _package(640.0, "fl oz")
        return _package(128.0, "fl oz")

    if product_id == 195 and ("hydretain" in text or "acehardware.com" in url):
        if "15" in text and ("lb" in text or "lbs" in text or "pound" in text):
            return _package(15.0, "lb")
        if "6000 sq ft" in text or "6,000 sq ft" in text or "acehardware.com" in url:
            return _package(15.0, "lb")
        return _package(3.0, "lb")

    if product_id == 199 and ("carbonizpn" in text or "essential-g" in text):
        return _package(40.0, "lb")

    if product_id == 206 and ("blade-iron" in text or "blade iron" in text):
        return _package(320.0, "fl oz")

    if product_id == 207 and ("turf-nectar" in text or "turf nectar" in text or "elemax" in text or "ele-max" in text):
        return _package(320.0, "fl oz")

    if product_id == 208 and ("chelated-liquid-iron" in text or "chelated liquid iron" in text):
        if "1 gallon" in text or "1-gallon" in text or "diypestcontrol.com" in url:
            return _package(128.0, "fl oz")
        return _package(16.0, "fl oz")

    if product_id == 210 and ("main-event-dry-iron" in text or "main event dry iron" in text or "quest products" in text):
        return _package(3.0, "lb")

    if product_id == 215 and ("sulfate-of-potash" in text or "sulfate of potash" in text):
        if "50#" in text or "50-lb" in text or "50 lb" in text:
            return _package(50.0, "lb")
        return _package(20.0, "lb")

    if product_id == 221 and ("carbonpro-g" in text or "carbon pro g" in text):
        return _package(40.0, "lb")

    if product_id == 224 and ("46-0-0" in text or "urea" in text):
        return _package(50.0, "lb")

    if product_id in {223, 225, 226} and "lesco" in text:
        return _package(50.0, "lb")

    if product_id == 229 and ("moisture-manager" in text or "moisture manager" in text):
        if "32 oz" in text or "32-oz" in text or "32 ounce" in text:
            return _package(32.0, "fl oz")
        if "1 gallon" in text or "1-gallon" in text:
            return _package(128.0, "fl oz")
        if "2.5 gallon" in text or "2-5 gallon" in text or "2-5-gal" in text:
            return _package(320.0, "fl oz")
        return _package(32.0, "fl oz")

    return None


def infer_package_size(product: dict, offer: dict) -> Optional[dict]:
    manual = manual_package_size(product, offer)
    if manual:
        return manual

    text = _offer_size_text(offer)
    if not text:
        return None

    if re.search(r"\b(?:half|1/2)\s*-?\s*(?:gal|gallon)\b", text):
        return _package(64.0, "fl oz")

    liquid_match = re.search(
        r"\b(\d+(?:\.\d+)?)\s*[-_]?\s*(?:fl\.?\s*)?(oz|ounce|ounces|gal|gallon|gallons|qt|quart|quarts)\b",
        text,
    )
    if liquid_match:
        value = float(liquid_match.group(1))
        unit = liquid_match.group(2)
        if unit.startswith("gal"):
            quantity = value * 128
        elif unit.startswith("qt") or unit.startswith("quart"):
            quantity = value * 32
        else:
            quantity = value
        return _package(quantity, "fl oz")

    if re.search(r"\b(?:gal|gallon)\b", text):
        return _package(128.0, "fl oz")

    dry_match = re.search(r"\b(\d+(?:\.\d+)?)\s*[-_]?\s*(lb|lbs|pound|pounds)\b", text)
    if dry_match:
        quantity = float(dry_match.group(1))
        return _package(quantity, "lb")

    return None


def is_known_wrong_product_source(product_id: int, url: str, title: str = "") -> bool:
    text = f"{url} {title}".lower()
    if 200 <= int(product_id) < 300 and "rittenhouse" in text:
        return True
    if int(product_id) == 249 and "b09n3mtwbg" in text:
        return True
    if "alyce-clover" in text:
        return True
    if "/topic/privacy" in text or "privacy policy" == title.strip().lower():
        return True
    if "/register" in text or title.strip().lower() in {"register", "home"}:
        return True
    if ".pdf" in urllib.parse.urlparse(url).path.lower() or title.strip().lower() == "product label":
        return True
    if "just a moment" == title.strip().lower():
        return True
    if "golf-course-lawn-academy" in text:
        return True
    if "headway-g-fungicide" in text and product_id != 52:
        return True
    if "speedzone-broadleaf" in text and product_id != 19:
        return True
    if "basagran" in text:
        return True
    if product_id == 16 and "empero" in text:
        return True
    if product_id == 75 and "bifenthrin-7-9f-select" in text:
        return True
    if product_id == 79 and ("2.7 lbs" in text or "2-7-lbs" in text or "venom-insecticide" in text):
        return True
    if product_id == 81 and "kontos" in text:
        return True
    if product_id == 71 and ("acelepryn-sc" in text or "acelepryn sc" in text):
        return True
    if product_id == 116 and "hydr8" in text:
        return True
    if product_id == 210 and "sunspotsupply.com/products/main-event-dry-iron-10-micros" in text and "main-event-dry-iron-10-micros-3" not in text:
        return True
    if product_id == 71 and "acelepryn-4oz" in text:
        return True
    if product_id != 53 and "armada-50-wdg" in text:
        return True
    if product_id != 6 and ("gallery-75" in text or "gallery 75" in text or "isoxaben 75" in text):
        return True
    if product_id == 2 and "crabgrass-control-plus" in text:
        return True
    if product_id == 23 and "ourprosolutions.com/product/" in text and "dismiss" not in text:
        return True
    if product_id == 25 and "ourprosolutions.com/product/" in text and not any(term in text for term in ("msma", "target-6", "target 6")):
        return True
    if product_id == 25 and "roundup-custom" in text:
        return True
    if product_id == 41 and "pasture-pro" in text:
        return True
    if product_id == 138 and ("b07kxz_hmk1".replace("_", "") in text or ("humic dg" in text and "charx" not in text)):
        return True
    return False


def apply_offer_package_metadata(results: list[dict]) -> None:
    for product in results:
        package_keys = set()
        priced_offer_count = 0
        priced_without_package = 0
        for offer in product.get("offers", []):
            if offer.get("price") is not None:
                priced_offer_count += 1
            package = infer_package_size(product, offer)
            if not package:
                if offer.get("price") is not None:
                    priced_without_package += 1
                continue
            offer.update(package)
            if offer.get("price") is not None and package["package_quantity"]:
                offer["price_per_unit"] = round(float(offer["price"]) / float(package["package_quantity"]), 2)
                package_keys.add((package["package_quantity"], package["package_unit"]))

        if len(package_keys) > 1:
            product["has_multiple_sizes"] = True
        if priced_offer_count > 1 and priced_without_package:
            product["needs_size_review"] = True


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
        ceiling = max_price_for_product(product)
        for offer in product.get("offers", []):
            if offer.get("price") is None:
                continue

            price = round(float(offer["price"]), 2)
            key = (offer.get("retailer"), price)
            if is_known_wrong_product_source(product["id"], offer.get("url", ""), offer.get("title", "")):
                offer["excluded"] = True
                offer["exclude_reason"] = "known wrong product source for this product"
            elif is_google_url(offer.get("url", "")):
                offer["excluded"] = True
                offer["exclude_reason"] = "Google Shopping intermediary URL, merchant link not resolved"
            elif is_bad_product_url(offer.get("url", "")):
                offer["excluded"] = True
                offer["exclude_reason"] = "cart/search/notify URL, not a product purchase page"
            elif price < floor:
                offer["excluded"] = True
                offer["exclude_reason"] = f"below ${floor:.2f} minimum for this category"
            elif ceiling is not None and price > ceiling:
                # Bulk sizes nobody using this app is buying. Excluded outright
                # so the offer never renders, not merely skipped for best price.
                offer["excluded"] = True
                offer["exclude_reason"] = f"above ${ceiling:.2f} maximum for this product"
            elif key in repeated_bad:
                offer["excluded"] = True
                offer["exclude_reason"] = "same retailer/price repeated across many unrelated products"

        product["best_price"] = select_best_offer(product, product.get("offers", []))


def sanitize_equipment_results(results: list[dict]) -> None:
    unit_keys = ("package_quantity", "package_unit", "package_label", "price_per_unit", "quantity", "unit")
    for product in results:
        if not is_equipment_category(product.get("category", "")):
            continue
        clean_offers = []
        floor = min_price_for_product(product)
        for offer in product.get("offers", []):
            price = offer.get("price")
            try:
                price_ok = price is not None and float(price) >= floor
            except (TypeError, ValueError):
                price_ok = False
            if (
                offer.get("excluded")
                or offer.get("in_stock") is False
                or not price_ok
                or is_google_url(offer.get("url", ""))
                or is_bad_product_url(offer.get("url", ""))
                or is_known_wrong_product_source(product["id"], offer.get("url", ""), offer.get("title", ""))
            ):
                continue
            for key in unit_keys:
                offer.pop(key, None)
            clean_offers.append(offer)
        product["offers"] = clean_offers
        product["best_price"] = select_best_offer(product, clean_offers)
        product.pop("has_multiple_sizes", None)
        product.pop("needs_size_review", None)


def sanitize_equipment_sources(source_map: dict, catalog_products: list[dict]) -> None:
    product_by_id = {str(product["id"]): product for product in catalog_products}
    unit_keys = ("package_quantity", "package_unit", "package_label", "price_per_unit", "quantity", "unit")
    for product_id, entries in list(source_map.get("products", {}).items()):
        product = product_by_id.get(str(product_id))
        if not product or not is_equipment_category(product.get("category", "")):
            continue
        floor = min_price_for_product(product)
        kept = []
        for source in entries or []:
            price = source.get("price_verified")
            try:
                low_price = price is not None and float(price) < floor
            except (TypeError, ValueError):
                low_price = False
            if (
                low_price
                or is_bad_product_url(source.get("url", ""))
                or is_known_wrong_product_source(product["id"], source.get("url", ""), source.get("title", ""))
            ):
                continue
            for key in unit_keys:
                source.pop(key, None)
            kept.append(source)
        source_map["products"][product_id] = kept


# ---------------------------------------------------------------------------
# Sweep scheduling: staleness ordering, checkpointing, and completeness.
#
# The full Playwright sweep used to run the catalog in fixed order and write
# prices.json only after the very last product. Once the catalog outgrew the
# job timeout the run was killed mid-pass and wrote NOTHING, so every
# non-Amazon price froze while the Amazon fast lane kept refreshing
# generated_at. The feed advertised today's date over ten-day-old merchant
# prices and nothing failed loudly.
#
# Three changes make the sweep degrade gracefully instead of catastrophically:
#   * least-recently-checked products go first, so whatever a run misses is
#     exactly what the next run starts with;
#   * the feed is written at checkpoints, so a kill costs the tail, not the run;
#   * unprocessed products are carried forward, so a partial write is still a
#     COMPLETE feed rather than a truncated one.
# ---------------------------------------------------------------------------

def _product_checked_at(entry: Optional[dict]) -> float:
    """Epoch seconds this product's data was last refreshed. 0.0 if never."""
    if not entry:
        return 0.0
    stamps = []
    for value in (entry.get("updated_at"),):
        parsed = _parse_alert_time(value) if value else None
        if parsed:
            stamps.append(parsed.timestamp())
    for offer in entry.get("offers") or []:
        parsed = _parse_alert_time(offer.get("last_checked")) if offer.get("last_checked") else None
        if parsed:
            stamps.append(parsed.timestamp())
    return max(stamps) if stamps else 0.0


def _publish_feed(
    results: list[dict],
    stale_map: dict,
    source_map: dict,
    catalog: dict,
    existing_alerts: list,
    prices_path,
    alerts_path,
    health_path,
    sources_path,
    emit_alerts: bool,
):
    """Write a COMPLETE feed from however much of the sweep has finished.

    Safe to call mid-sweep. Products this run has not reached are carried
    forward from the previous feed and marked stale, so a checkpoint never
    publishes a truncated catalog.
    """
    results = list(results)
    apply_offer_package_metadata(results)
    apply_offer_quality_filters(results)
    results = preserve_last_good_products(results, stale_map)
    results = merge_unprocessed_products(results, stale_map, catalog["products"])
    apply_offer_quality_filters(results)
    sanitize_equipment_results(results)
    source_map = update_product_sources(source_map, results)
    sanitize_equipment_sources(source_map, catalog["products"])

    generated_at = now_iso()
    output = {
        "schema_version": "1.0",
        "generated_at":   generated_at,
        "product_count":  len(results),
        "products":       results,
    }
    health_output = build_source_health(catalog["products"], source_map, results, generated_at)

    with open(prices_path, "w") as f:
        json.dump(output, f, indent=2)
    with open(health_path, "w") as f:
        json.dump(health_output, f, indent=2)
    with open(sources_path, "w") as f:
        json.dump(source_map, f, indent=2)

    # Alerts compare this feed against the previous one, so they are computed
    # once at the end of the sweep. Emitting them at every checkpoint would
    # diff a partial feed against a full one and invent drops.
    if emit_alerts:
        alerts_output = build_price_alerts(stale_map, results, generated_at, existing_alerts)
        with open(alerts_path, "w") as f:
            json.dump(alerts_output, f, indent=2)
        log.info(f"Written to {alerts_path} ({alerts_output['alert_count']} alerts)")

    found = sum(1 for p in results if p.get("best_price"))
    return results, source_map, found


def order_products_by_staleness(products: list[dict], previous: dict) -> list[dict]:
    """Least-recently-checked first, so a short run refreshes what is oldest.

    This is what makes the sweep self-healing: a run that only gets halfway
    through still fixes the half that was most out of date, and the next run
    picks up exactly where the data is now stalest. No shard index to keep in
    sync with a catalog that changes.
    """
    return sorted(
        products,
        key=lambda product: (
            _product_checked_at(previous.get(product["id"])),
            product["id"],
        ),
    )


def merge_unprocessed_products(
    results: list[dict],
    previous: dict,
    catalog_products: list[dict],
) -> list[dict]:
    """Return a feed covering the whole catalog, not just what this run reached.

    preserve_last_good_products only walks entries already in `results`, so on
    its own a checkpoint or an interrupted sweep would publish a feed missing
    every product the run had not got to yet. Those would vanish from the app.
    """
    seen = {entry["id"] for entry in results}
    merged = list(results)
    for product in catalog_products:
        pid = product["id"]
        if pid in seen:
            continue
        carried = previous.get(pid)
        if not carried:
            continue
        entry = carried.copy()
        entry["stale"] = True
        entry["stale_reason"] = "not reached in latest sweep"
        merged.append(entry)
    merged.sort(key=lambda entry: entry["id"])
    return merged


def offer_age_summary(products: list[dict], now: Optional[float] = None) -> dict:
    """Oldest and median offer age in hours, for the staleness alarm."""
    reference = now if now is not None else datetime.now(timezone.utc).timestamp()
    ages = []
    for entry in products:
        checked = _product_checked_at(entry)
        if checked:
            ages.append(max(0.0, (reference - checked) / 3600.0))
    if not ages:
        return {"count": 0, "oldest_hours": None, "median_hours": None}
    ages.sort()
    mid = len(ages) // 2
    median = ages[mid] if len(ages) % 2 else (ages[mid - 1] + ages[mid]) / 2
    return {
        "count": len(ages),
        "oldest_hours": round(ages[-1], 1),
        "median_hours": round(median, 1),
    }


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


def _same_offer_package(old_offer: Optional[dict], new_offer: Optional[dict]) -> bool:
    if not old_offer or not new_offer:
        return False
    old_unit = old_offer.get("package_unit")
    new_unit = new_offer.get("package_unit")
    old_quantity = old_offer.get("package_quantity")
    new_quantity = new_offer.get("package_quantity")
    if old_unit and new_unit and old_quantity and new_quantity:
        try:
            return old_unit == new_unit and abs(float(old_quantity) - float(new_quantity)) < 0.001
        except (TypeError, ValueError):
            return False
    return False


def _same_offer_source(old_offer: Optional[dict], new_offer: Optional[dict]) -> bool:
    if not old_offer or not new_offer:
        return False
    old_retailer = old_offer.get("retailer")
    new_retailer = new_offer.get("retailer")
    old_url = canonical_product_url(old_offer.get("url", ""))
    new_url = canonical_product_url(new_offer.get("url", ""))
    return bool(old_retailer and old_retailer == new_retailer and old_url and old_url == new_url)


def _trusted_extreme_drop(old_offer: Optional[dict], new_offer: dict) -> bool:
    return _same_offer_source(old_offer, new_offer) and _same_offer_package(old_offer, new_offer)


def _confirmed_package_mismatch(old_offer: Optional[dict], new_offer: Optional[dict]) -> bool:
    """True only when both offers report package data and it disagrees --
    never for missing/unconfirmed data, which the percent-tiered checks below
    already handle. Runs at every drop size so a package downgrade (e.g. a
    128 fl oz jug swapped for a 32 fl oz bottle) can't pass as a discount just
    because the resulting percent drop is under the 40% tier."""
    if not old_offer or not new_offer:
        return False
    has_package_data = all(
        offer.get("package_unit") and offer.get("package_quantity")
        for offer in (old_offer, new_offer)
    )
    return has_package_data and not _same_offer_package(old_offer, new_offer)


def _min_priced_products_floor(total_products: int, min_absolute: int, min_percent: float) -> int:
    """The run must produce at least this many priced products. Combines an
    absolute floor (catches an empty/near-empty catalog) with a
    percentage-of-catalog floor (catches a partial extraction collapse that
    an absolute floor of 1 would silently let through)."""
    return max(min_absolute, int(total_products * min_percent / 100))


def _is_suspicious_drop(old_offer: Optional[dict], new_offer: dict, drop_percent: float) -> bool:
    if _confirmed_package_mismatch(old_offer, new_offer):
        return True
    if drop_percent < 40:
        return False
    if not _same_offer_package(old_offer, new_offer):
        return True
    if drop_percent >= 60 and not _same_offer_source(old_offer, new_offer):
        return True
    return False


def _should_emit_price_drop_alert(old_offer: Optional[dict], new_offer: dict, drop_percent: float) -> bool:
    if drop_percent < MIN_ALERT_DROP_PERCENT:
        return False
    return not _is_suspicious_drop(old_offer, new_offer, drop_percent)


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


def _parse_alert_time(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recent_alerts(alerts: list[dict], generated_at: str) -> list[dict]:
    generated_time = _parse_alert_time(generated_at) or datetime.now(timezone.utc)
    cutoff = generated_time - timedelta(days=PRICE_ALERT_RETENTION_DAYS)
    recent = []
    for alert in alerts:
        created_at = _parse_alert_time(alert.get("created_at", ""))
        if created_at and created_at >= cutoff:
            recent.append(alert)
    recent.sort(key=lambda alert: alert.get("created_at", ""), reverse=True)
    return recent


def _alert_matches_current_best(alert: dict, current_by_slug: dict) -> bool:
    product = current_by_slug.get(alert.get("product_slug"))
    if not product:
        return False
    best = product.get("best_price") or {}
    alert_price = alert.get("new_price")
    best_price = _offer_price(best)
    if alert_price is None or best_price is None:
        return False
    try:
        if abs(float(alert_price) - best_price) >= 0.01:
            return False
    except (TypeError, ValueError):
        return False

    alert_retailer = str(alert.get("new_retailer") or "").lower()
    best_retailer = str(best.get("retailer_name") or best.get("retailer") or "").lower()
    if alert_retailer and best_retailer and alert_retailer != best_retailer:
        return False

    alert_url = alert.get("url")
    best_url = best.get("url")
    if alert_url and best_url and not _offer_matches_source_url(alert_url, best_url):
        return False

    return True


def build_price_alerts(
    previous_products: dict,
    current_products: list[dict],
    generated_at: str,
    previous_alerts: Optional[list[dict]] = None,
) -> dict:
    alerts = []
    current_by_slug = {
        product.get("slug"): product
        for product in current_products
        if product.get("slug")
    }
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
            emit_drop_alert = _should_emit_price_drop_alert(old_best, new_best, drop)
            if emit_drop_alert:
                if drop >= 10:
                    alerts.append(_alert_payload(product, "major_price_drop", old_best, new_best, generated_at, drop))
                else:
                    alerts.append(_alert_payload(product, "best_price_drop", old_best, new_best, generated_at, drop))

            old_retailer = old_best.get("retailer") if old_best else None
            new_retailer = new_best.get("retailer")
            if emit_drop_alert and new_retailer and old_retailer and new_retailer != old_retailer and new_price < old_price:
                alerts.append(_alert_payload(product, "new_lowest_retailer", old_best, new_best, generated_at, drop))

        if old_best and old_best.get("in_stock") is False and new_best.get("in_stock") is True:
            alerts.append(_alert_payload(product, "back_in_stock", old_best, new_best, generated_at, 0.0))

    current_alert_ids = {alert["id"] for alert in alerts}
    unique_alerts = {}
    retained_previous_alerts = [
        alert for alert in _recent_alerts(previous_alerts or [], generated_at)
        if _alert_matches_current_best(alert, current_by_slug)
    ]
    for alert in alerts + retained_previous_alerts:
        unique_alerts[alert["id"]] = alert
    retained_alerts = _recent_alerts(list(unique_alerts.values()), generated_at)

    return {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "min_drop_percent": MIN_ALERT_DROP_PERCENT,
        "retention_days": PRICE_ALERT_RETENTION_DAYS,
        "current_alert_count": len(current_alert_ids),
        "alert_count": len(retained_alerts),
        "alerts": retained_alerts,
    }


def _absolute_url(base_url: str, href: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", href)


def _absolute_image_url(base_url: str, src: str) -> Optional[str]:
    src = str(src or "").strip()
    if not src or src.startswith(("data:", "blob:")):
        return None
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", src)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if _is_bad_image_url(url):
        return None
    return url


def _is_bad_image_url(url: str) -> bool:
    lower = url.lower()
    bad_parts = (
        "placeholder",
        "missing-image",
        "no-image",
        "noimage",
        "default-image",
        "favicon",
        "logo",
        "sprite",
    )
    return any(part in lower for part in bad_parts)


def _stored_image_url(url: str) -> Optional[str]:
    if not url or _is_bad_image_url(url):
        return None
    return str(url)


def _offer_product_url(base_url: str, href: str, retailer: str) -> Optional[str]:
    """Resolve an offer link without letting cart/search URLs replace the product page."""
    resolved = _absolute_url(base_url, href or base_url)
    if is_google_url(resolved) or is_bad_product_url(resolved):
        resolved = urllib.parse.urldefrag(base_url)[0].rstrip("/")
    if is_google_url(resolved) or is_bad_product_url(resolved):
        return None
    resolved = canonical_product_url(resolved)
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

            offers = select_jsonld_offer(
                obj.get("offers"),
                page_url=base_url,
                product_name=str(obj.get("name") or ""),
            )
            if not isinstance(offers, dict):
                continue

            price = parse_price(str(offers.get("price") or offers.get("lowPrice") or ""))
            if price is None:
                continue

            href = offers.get("url") or obj.get("url") or base_url
            product_url = _offer_product_url(base_url, href, retailer)
            if not product_url:
                continue
            image = _jsonld_image_url(obj, base_url)

            # Availability: the page-text heuristic reads the whole document,
            # so it cannot be attributed to one variant. On a multi-variant page
            # (DoMyOwn lists an 18 oz and a gallon) it would mark every size out
            # of stock as soon as any one of them sold out. Trust the chosen
            # variant's own availability there.
            #
            # On a single-variant page the page text IS about that variant, and
            # merchants do leave stale InStock in JSON-LD while the page says
            # Sold Out, so the override still applies.
            in_stock = _offer_availability_in_stock(offers)
            single_variant = len(priced_jsonld_offers(obj.get("offers"))) <= 1
            if in_stock is None or single_variant:
                if _page_indicates_out_of_stock(soup):
                    in_stock = False
                elif in_stock is None:
                    in_stock = True
            return {
                "retailer": retailer,
                "retailer_name": retailer_name,
                "price": price,
                "url": product_url,
                "in_stock": in_stock,
                "image": image,
                "last_checked": now_iso(),
            }
    return None


def _offer_availability_in_stock(offer: dict) -> Optional[bool]:
    """True/False from an offer's own schema.org availability, None if absent."""
    raw = offer.get("availability")
    if raw is None:
        return None
    text = str(raw).lower()
    if not text.strip():
        return None
    if "outofstock" in text or "soldout" in text or "discontinued" in text:
        return False
    if "instock" in text or "onlineonly" in text or "limitedavailability" in text or "presale" in text or "backorder" in text:
        return True
    return None


def priced_jsonld_offers(offers) -> list:
    """Every variant on the page that carries a parseable price."""
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return []
    return [
        offer
        for offer in offers
        if isinstance(offer, dict)
        and parse_price(str(offer.get("price") or offer.get("lowPrice") or "")) is not None
    ]


def select_jsonld_offer(
    offers,
    page_url: str = "",
    product_name: str = "",
) -> Optional[dict]:
    """Choose which variant on a multi-variant product page to price.

    Merchant pages routinely list several sizes in one JSON-LD block. DoMyOwn's
    Specticle FLO page carries the 18 oz at $340.02 (out of stock) and a gallon
    at $2,143.03 (in stock). The catalog product IS the 18 oz, so we must
    publish the 18 oz and report it honestly as out of stock. Picking whatever
    happens to be in stock would quote a $2,143 gallon as the price of an 18 oz
    bottle, and picking the cheapest would break the moment a page lists a
    smaller trial size.

    So: identify the page's PRIMARY variant. The SKU embedded in the page URL is
    the strongest signal, then an exact name match against the product, then
    the merchant's own first-listed offer, which is what this used to take
    unconditionally.
    """
    priced = priced_jsonld_offers(offers)
    if not priced:
        return None
    if len(priced) == 1:
        return priced[0]

    # 1. SKU that appears in the page URL. DoMyOwn's 18 oz is sku 2797 and its
    #    page is .../specticle-flo-p-2797.html, which names the variant exactly.
    url_text = (page_url or "").lower()
    if url_text:
        for offer in priced:
            sku = str(offer.get("sku") or "").strip().lower()
            if sku and len(sku) >= 3 and sku in url_text:
                return offer

    # 2. Exact name match. Size variants nearly always append a qualifier
    #    ("... - Gallon"), so the bare product name is the primary listing.
    target = (product_name or "").strip().lower()
    if target:
        for offer in priced:
            if str(offer.get("name") or "").strip().lower() == target:
                return offer

    # 3. The merchant's first-listed offer, the long-standing behaviour.
    return priced[0]


def _page_indicates_out_of_stock(soup: BeautifulSoup) -> bool:
    text = soup.get_text(" ", strip=True).lower()
    leading = text[:4000]
    return any(phrase in leading for phrase in ("out of stock", "sold out", "currently unavailable"))


def _jsonld_image_url(obj: dict, base_url: str) -> Optional[str]:
    image = obj.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    return _absolute_image_url(base_url, image or "")


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


def _primary_product_price_from_soup(soup: BeautifulSoup) -> Optional[float]:
    selectors = [
        ".product-info-main .product-info-price [data-price-type='finalPrice'][data-price-amount]",
        ".product-info-main [data-price-type='finalPrice'][data-price-amount]",
        ".product-info-price [data-price-type='finalPrice'][data-price-amount]",
        ".product-info-main [itemprop='price']",
        ".product-info-main meta[property='product:price:amount']",
        ".summary .price",
        ".productView-price",
        ".product__price",
        ".product-single__price",
    ]
    for sel in selectors:
        elem = soup.select_one(sel)
        if not elem:
            continue
        raw = (
            elem.get("data-price-amount")
            or elem.get("content")
            or elem.get("data-price")
            or elem.get_text(" ", strip=True)
        )
        price = parse_price(raw)
        if price is not None:
            return price
    return None


def _primary_product_title_from_soup(soup: BeautifulSoup) -> str:
    selectors = [
        ".product-info-main h1",
        "h1.page-title",
        ".page-title",
        "[itemprop='name']",
        "h1",
    ]
    for sel in selectors:
        elem = soup.select_one(sel)
        if elem:
            title = elem.get_text(" ", strip=True)
            if title:
                return title
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return ""


def _image_from_node(node, base_url: str) -> Optional[str]:
    selectors = [
        "meta[property='og:image']",
        "meta[name='twitter:image']",
        "meta[itemprop='image']",
        "img[itemprop='image']",
        ".productView-image img",
        ".product-single__photo img",
        ".product__media img",
        ".product-gallery img",
        ".product-image img",
        ".product img",
        "img",
    ]
    for sel in selectors:
        elem = node.select_one(sel)
        if not elem:
            continue
        src = (
            elem.get("content")
            or elem.get("data-src")
            or elem.get("data-original")
            or elem.get("src")
            or elem.get("srcset", "").split(",")[0].strip().split(" ")[0]
        )
        image = _absolute_image_url(base_url, src or "")
        if image:
            return image
    return None


def _extract_from_soup(
    soup: BeautifulSoup,
    base_url: str,
    retailer: str,
    retailer_name: str,
    product: Optional[dict] = None,
) -> Optional[dict]:
    """Generic price + link extractor from parsed HTML."""
    jsonld_result = _jsonld_product_offer(soup, base_url, retailer, retailer_name)
    if jsonld_result:
        return jsonld_result

    primary_price = _primary_product_price_from_soup(soup)
    if primary_price is not None:
        return {
            "retailer":      retailer,
            "retailer_name": retailer_name,
            "price":         primary_price,
            "url":           base_url,
            "in_stock":      not _page_indicates_out_of_stock(soup),
            "title":         _primary_product_title_from_soup(soup),
            "image":         _image_from_node(soup, base_url),
            "last_checked":  now_iso(),
        }

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
        title = link_elem.get_text(" ", strip=True) if link_elem else ""
        if product and not _matches_product(product, title, product_url):
            continue

        text = search_root.get_text(" ", strip=True).lower()
        in_stock = not any(phrase in text for phrase in ("out of stock", "sold out", "currently unavailable"))

        return {
            "retailer":      retailer,
            "retailer_name": retailer_name,
            "price":         price,
            "url":           product_url,
            "in_stock":      in_stock,
            "title":         title,
            "image":         _image_from_node(search_root, base_url) or _image_from_node(soup, base_url),
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
            product,
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
            product,
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


def is_equipment_category(category: str) -> bool:
    return category in {
        "spreader-handheld",
        "spreader-push",
        "spreader-tow",
        "sprayer-backpack",
    }


def _source_entries(source_map: dict, product_id: int, product: Optional[dict] = None) -> list[dict]:
    entries = []
    for source in source_map.get("products", {}).get(str(product_id), []):
        url = source.get("url", "")
        if not url or is_google_url(url) or is_bad_product_url(url):
            continue
        if is_known_wrong_product_source(product_id, url, source.get("title", "")):
            continue
        if source.get("verified") is False:
            continue
        source_type = source.get("source_type", "product")
        if source_type != "product":
            continue
        if product and is_equipment_category(product.get("category", "")) and not source.get("manual_verified"):
            continue
        entries.append(source)

    priced_entries = []
    priority_urls = set()
    for entry in entries:
        if entry.get("price_verified") is None:
            continue
        normalized = canonical_product_url(entry.get("url", ""))
        if normalized in priority_urls:
            continue
        priority_urls.add(normalized)
        priced_entries.append(entry)

    manual_unpriced_entries = [
        entry for entry in entries
        if entry.get("manual_verified")
        and entry.get("price_verified") is None
        and canonical_product_url(entry.get("url", "")) not in priority_urls
    ]
    auto_unpriced_entries = [
        entry for entry in entries
        if not entry.get("manual_verified")
        and entry.get("price_verified") is None
        and canonical_product_url(entry.get("url", "")) not in priority_urls
    ]

    if not entries or SAVED_SOURCE_LIMIT <= 0:
        return entries
    if len(entries) <= SAVED_SOURCE_LIMIT:
        return entries

    cursors = source_map.setdefault("refresh_cursors", {})
    remaining = max(0, SAVED_SOURCE_LIMIT - len(priced_entries))
    if remaining <= 0:
        return priced_entries

    selected_manual = manual_unpriced_entries[:remaining]
    remaining -= len(selected_manual)
    if remaining <= 0 or not auto_unpriced_entries:
        return priced_entries + selected_manual

    start = int(cursors.get(str(product_id), 0)) % len(auto_unpriced_entries)
    selected_rotating = [
        auto_unpriced_entries[(start + offset) % len(auto_unpriced_entries)]
        for offset in range(min(remaining, len(auto_unpriced_entries)))
    ]
    cursors[str(product_id)] = (start + len(selected_rotating)) % len(auto_unpriced_entries)
    return priced_entries + selected_manual + selected_rotating


def _apply_source_metadata(offer: dict, source: dict) -> dict:
    if source.get("title") and not offer.get("title"):
        offer["title"] = source["title"]
    offer["image"] = _stored_image_url(source.get("image")) or offer.get("image")
    for key in ("package_quantity", "package_unit", "package_label", "price_per_unit"):
        if key not in offer and key in source:
            offer[key] = source[key]
    return offer


def scrape_saved_sources(product: dict, source_map: dict) -> list[dict]:
    offers = []
    for source in _source_entries(source_map, product["id"], product):
        url = source.get("url")
        if not url or is_google_url(url):
            continue
        if source.get("retailer") == "amazon" or "amazon.com" in url:
            continue
        if is_known_wrong_product_source(product["id"], url, source.get("title", "")):
            continue
        html = fetch_saved_source(url)
        if not html:
            fallback = _offer_from_verified_source(source)
            if fallback:
                add_offer(offers, fallback)
            continue

        retailer = source.get("retailer") or retailer_key(url)
        retailer_name = source.get("retailer_name") or retailer_name_from_url(url)
        offer = _extract_from_soup(
            BeautifulSoup(html, "lxml"),
            url,
            retailer,
            retailer_name,
            product,
        )
        if offer:
            source_url = canonical_product_url(url)
            offer_url = canonical_product_url(offer.get("url", ""))
            if is_known_wrong_product_source(product["id"], offer.get("url", ""), offer.get("title", "")):
                log.info(f"  Saved source wrong product skipped: {(offer.get('title') or '')[:70]} @ {(offer.get('url') or '')[:80]}")
                continue
            if offer_url != source_url:
                if _same_product_path(source_url, offer_url):
                    offer["url"] = append_affiliate(source_url, retailer)
                elif source.get("manual_verified"):
                    fallback = _offer_from_verified_source(source)
                    if fallback:
                        add_offer(offers, fallback)
                    continue
                else:
                    log.info(f"  Saved source URL mismatch skipped: offer {offer_url[:60]} vs saved {source_url[:60]}")
                    continue
            match_title = offer.get("title") or source.get("title") or ""
            if not source.get("manual_verified") and not _matches_product(product, match_title, url):
                log.info(f"  Saved source mismatch skipped: {match_title[:70]} @ {url[:80]}")
                continue
            if is_bad_product_url(offer.get("url", "")) and not is_bad_product_url(url):
                offer["url"] = append_affiliate(url, retailer)
                if source.get("title"):
                    offer["title"] = source["title"]
            offer["source"] = "saved_product_source"
            _apply_source_metadata(offer, source)
            add_offer(offers, offer)
        else:
            fallback = _offer_from_verified_source(source)
            if fallback:
                add_offer(offers, fallback)
            continue
        time.sleep(0.5)
    return offers


def _offer_from_verified_source(source: dict) -> Optional[dict]:
    url = source.get("url", "")
    retailer = source.get("retailer") or retailer_key(url)
    if retailer == "amazon":
        return None

    price = source.get("price_verified")
    if price is None:
        return None
    if not url or is_google_url(url) or is_bad_product_url(url):
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    return {
        "retailer": retailer,
        "retailer_name": source.get("retailer_name") or retailer_name_from_url(url),
        "price": price,
        "url": append_affiliate(url, retailer),
        "in_stock": source.get("in_stock", True),
        "title": source.get("title", ""),
        "last_checked": source.get("last_seen") or now_iso(),
        "source": "manual_verified_source",
        "image": _stored_image_url(source.get("image")),
        **{
            key: source[key]
            for key in ("package_quantity", "package_unit", "package_label", "price_per_unit")
            if key in source
        },
    }


def update_product_sources(source_map: dict, results: list[dict]) -> dict:
    products = source_map.setdefault("products", {})
    for product in results:
        product_id = str(product["id"])
        existing = {
            canonical_product_url(src.get("url", "")): src
            for src in products.get(product_id, [])
            if src.get("url")
            and not is_google_url(src.get("url", ""))
            and not is_bad_product_url(src.get("url", ""))
            and not is_known_wrong_product_source(product["id"], src.get("url", ""), src.get("title", ""))
        }

        for offer in product.get("offers", []):
            url = offer.get("url", "")
            if not url or is_google_url(url) or offer.get("excluded"):
                continue
            normalized = canonical_product_url(url)
            if is_bad_product_url(normalized):
                continue
            if is_known_wrong_product_source(product["id"], normalized, offer.get("title", "")):
                continue
            previous_source = existing.get(normalized, {})
            updated_source = {
                "url": normalized,
                "retailer": offer.get("retailer") or retailer_key(url),
                "retailer_name": offer.get("retailer_name") or retailer_name_from_url(url),
                "title": offer.get("title") or product.get("name"),
                "image": offer.get("image"),
                "last_seen": now_iso(),
            }
            if offer.get("price") is not None and updated_source["retailer"] != "amazon":
                updated_source["price_verified"] = round(float(offer["price"]), 2)
            if "in_stock" in offer:
                updated_source["in_stock"] = offer.get("in_stock")
            for key in ("package_quantity", "package_unit", "package_label", "price_per_unit"):
                if key in offer:
                    updated_source[key] = offer[key]
            for key in ("verified", "manual_verified", "price_verified", "source_type"):
                if key == "price_verified" and updated_source["retailer"] == "amazon":
                    continue
                if key == "price_verified" and key in updated_source:
                    continue
                if key in previous_source:
                    updated_source[key] = previous_source[key]
            existing[normalized] = updated_source

        products[product_id] = list(existing.values())[:MAX_SAVED_SOURCES_PER_PRODUCT]

    source_map["updated_at"] = now_iso()
    return source_map


def _valid_source_reason(product: dict, source: dict) -> Optional[str]:
    url = source.get("url", "")
    if not url:
        return "missing_url"
    if is_google_url(url):
        return "google_or_search_url"
    if is_bad_product_url(url):
        return "not_product_purchase_page"
    if is_known_wrong_product_source(product["id"], url, source.get("title", "")):
        return "known_wrong_product"
    if source.get("verified") is False:
        return "source_marked_unverified"
    if source.get("source_type", "product") != "product":
        return "not_product_source"
    return None


def _offer_health_reason(product: dict, offer: dict) -> str:
    if offer.get("excluded"):
        return offer.get("exclude_reason") or "excluded"
    if offer.get("price") is None:
        return "no_price"
    if is_google_url(offer.get("url", "")):
        return "google_or_search_url"
    if is_bad_product_url(offer.get("url", "")):
        return "not_product_purchase_page"
    try:
        if float(offer["price"]) < min_price_for_product(product):
            return f"below ${min_price_for_product(product):.2f} minimum for this category"
    except (TypeError, ValueError):
        return "invalid_price"
    return "included"


def build_source_health(catalog_products: list[dict], source_map: dict, results: list[dict], generated_at: str) -> dict:
    result_by_id = {str(product["id"]): product for product in results}
    source_map_for_selection = copy.deepcopy(source_map)
    product_reports = []
    totals = {
        "sources": 0,
        "manual_verified_sources": 0,
        "included_sources": 0,
        "not_included_sources": 0,
        "invalid_sources": 0,
    }
    reason_counts: dict[str, int] = {}

    for product in catalog_products:
        product_id = str(product["id"])
        result = result_by_id.get(product_id, {})
        selected_urls = {
            canonical_product_url(source.get("url", ""))
            for source in _source_entries(source_map_for_selection, product["id"], product)
            if source.get("url")
        }

        offers_by_url: dict[str, list[dict]] = {}
        for offer in result.get("offers", []):
            url = offer.get("url", "")
            if not url:
                continue
            offers_by_url.setdefault(canonical_product_url(url), []).append(offer)

        source_reports = []
        product_totals = {
            "sources": 0,
            "included_sources": 0,
            "not_included_sources": 0,
            "invalid_sources": 0,
        }

        for source in source_map.get("products", {}).get(product_id, []):
            totals["sources"] += 1
            product_totals["sources"] += 1
            if source.get("manual_verified"):
                totals["manual_verified_sources"] += 1

            url = source.get("url", "")
            normalized_url = canonical_product_url(url) if url else ""
            invalid_reason = _valid_source_reason(product, source)
            matched_offers = offers_by_url.get(normalized_url, [])

            if invalid_reason:
                status = "invalid"
                reason = invalid_reason
                offer = None
                totals["invalid_sources"] += 1
                product_totals["invalid_sources"] += 1
            elif matched_offers:
                offer = min(
                    matched_offers,
                    key=lambda item: float(item["price"]) if item.get("price") is not None else float("inf"),
                )
                reason = _offer_health_reason(product, offer)
                status = "included" if reason == "included" else "not_included"
            elif normalized_url not in selected_urls:
                status = "not_included"
                reason = "not_checked_saved_source_limit"
                offer = None
            else:
                status = "not_included"
                reason = "no_extracted_offer"
                offer = None

            if status == "included":
                totals["included_sources"] += 1
                product_totals["included_sources"] += 1
            elif status != "invalid":
                totals["not_included_sources"] += 1
                product_totals["not_included_sources"] += 1

            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            source_reports.append({
                "url": url,
                "retailer": source.get("retailer") or retailer_key(url),
                "retailer_name": source.get("retailer_name") or retailer_name_from_url(url),
                "manual_verified": bool(source.get("manual_verified")),
                "status": status,
                "reason": reason,
                "price": offer.get("price") if offer else None,
                "offer_url": offer.get("url") if offer else None,
            })

        product_reports.append({
            "id": product["id"],
            "slug": product.get("slug"),
            "name": product.get("name"),
            "category": product.get("category"),
            **product_totals,
            "sources": source_reports,
        })

    return {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "saved_source_limit": SAVED_SOURCE_LIMIT,
        "totals": totals,
        "reason_counts": dict(sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))),
        "products": product_reports,
    }


def scrape_domyown(product: dict) -> Optional[dict]:
    queries = search_variants(product, base_key="domyown_query")
    for query in queries:
        result = _domyown_search(query, product)
        if result:
            return result
        time.sleep(1.0)
    return None


def _domyown_search(query: str, product: dict) -> Optional[dict]:
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
        result = _extract_from_soup(soup, "https://www.domyown.com", "domyown", "DoMyOwn", product)
        if result:
            return result
        log.info(f"  DoMyOwn: page loaded but no price found in HTML")
        time.sleep(1.0)
    return None


# ── Solutions Pest & Lawn scraper ─────────────────────────────────────────────

def scrape_solutions(product: dict) -> Optional[dict]:
    queries = search_variants(product)
    for query in queries:
        result = _solutions_search(query, product)
        if result:
            return result
        time.sleep(1.0)
    return None


def _solutions_search(query: str, product: dict) -> Optional[dict]:
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
        result = _extract_from_soup(soup, "https://www.solutionspestcontrol.com", "solutions", "Solutions Pest & Lawn", product)
        if result:
            return result
        log.info(f"  Solutions: page '{title[:60]}' loaded but no price found")
        time.sleep(1.0)
    return None


# ── Amazon ────────────────────────────────────────────────────────────────────

def amazon_result(product: dict, source_map: Optional[dict] = None) -> Optional[dict]:
    source_map = source_map or {}
    if not _amazon_asins_for_product(product, source_map):
        return None
    if AMAZON_CREATOR_CREDENTIAL_ID and AMAZON_CREATOR_SECRET:
        creators = _amazon_creators_api(product, source_map)
        if creators and creators.get("source") == "amazon_creators_api":
            return creators
    keepa = _amazon_keepa(product, source_map)
    if keepa:
        return keepa
    return None


def _amazon_paapi(product: dict, source_map: Optional[dict] = None) -> dict:
    source_map = source_map or {}
    asins = _amazon_asins_for_product(product, source_map)
    if not asins:
        return _amazon_affiliate_link(product)

    offer = amazon_result(product, source_map)
    if offer:
        return offer

    return {
        **_amazon_affiliate_link(product),
        "url": append_affiliate(f"https://www.amazon.com/dp/{asins[0]}", "amazon"),
    }


def _amazon_asins_for_product(product: dict, source_map: dict) -> list[str]:
    asins = []

    def add(value):
        value = str(value or "").upper()
        if re.fullmatch(r"[A-Z0-9]{10}", value) and value not in asins:
            asins.append(value)

    add(product.get("asin"))
    for source in source_map.get("products", {}).get(str(product["id"]), []):
        if not _verified_amazon_source(product, source):
            continue
        if source.get("retailer") == "amazon" or "amazon.com" in source.get("url", ""):
            add(amazon_asin_from_url(source.get("url", "")))
    return asins


def _tokenize_product_text(value: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", str(value or "").lower()) if len(t) > 1]


def _exact_product_phrases(product: dict) -> list[str]:
    phrases = []
    values = [product.get("name"), *product.get("alt_names", [])]
    for value in values:
        if not value:
            continue
        for candidate in (str(value), re.sub(r"\([^)]*\)", "", str(value))):
            candidate = re.sub(r"\s+", " ", candidate).strip().lower()
            tokens = _tokenize_product_text(candidate)
            if len(tokens) >= 2 and candidate not in phrases:
                phrases.append(candidate)
    return phrases


def _verified_amazon_source(product: dict, source: dict) -> bool:
    is_amazon = source.get("retailer") == "amazon" or "amazon.com" in source.get("url", "")
    if not is_amazon:
        return False

    source_asin = amazon_asin_from_url(source.get("url", ""))
    product_asin = str(product.get("asin") or "").upper()
    if product_asin and source_asin == product_asin:
        return True
    if product_asin and is_equipment_category(product.get("category", "")):
        return False
    if is_equipment_category(product.get("category", "")) and not source.get("manual_verified"):
        return False

    title = str(source.get("title") or "")
    haystack = f"{title} {source.get('url', '')}".lower()
    if any(phrase and phrase in haystack for phrase in _exact_product_phrases(product)):
        return True

    return False


def _keepa_current_price(product_data: dict) -> Optional[float]:
    stats = product_data.get("stats") or {}
    current = stats.get("current") or []
    candidate_indexes = (0, 1, 10, 18)
    candidates = []
    for index in candidate_indexes:
        if index >= len(current):
            continue
        value = current[index]
        if isinstance(value, (int, float)) and value > 0:
            candidates.append(float(value) / 100)
    return min(candidates) if candidates else None


def _keepa_image_url(product_data: dict) -> Optional[str]:
    image_entries = product_data.get("images") or []
    if image_entries:
        first = image_entries[0] or {}
        filename = first.get("l") or first.get("m")
        if filename:
            return f"https://m.media-amazon.com/images/I/{filename}"

    images = product_data.get("imagesCSV") or ""
    if not images:
        return None
    filename = str(images).split(",")[0].strip()
    if not filename:
        return None
    if filename.startswith(("http://", "https://")):
        return filename
    return f"https://m.media-amazon.com/images/I/{filename}"


def _amazon_keepa(product: dict, source_map: dict) -> Optional[dict]:
    if not KEEPA_API_KEY:
        return None

    for asin in _amazon_asins_for_product(product, source_map):
        try:
            response = _session.get(
                "https://api.keepa.com/product",
                params={
                    "key": KEEPA_API_KEY,
                    "domain": KEEPA_DOMAIN,
                    "asin": asin,
                    "stats": 1,
                },
                timeout=20,
            )
            if response.status_code != 200:
                log.info(f"  Keepa HTTP {response.status_code} for {asin}: {response.text[:100]}")
                continue
            payload = response.json()
        except Exception as e:
            log.info(f"  Keepa failed for {asin}: {e.__class__.__name__}: {str(e)[:100]}")
            continue

        products = payload.get("products") or []
        if not products:
            continue
        item = products[0]
        price = _keepa_current_price(item)
        if price is None:
            log.info(f"  Keepa no current price for {asin}")
            continue
        return {
            "retailer": "amazon",
            "retailer_name": "Amazon",
            "price": price,
            "url": append_affiliate(f"https://www.amazon.com/dp/{asin}", "amazon"),
            "in_stock": True,
            "title": item.get("title") or product.get("name", ""),
            "image": _keepa_image_url(item),
            "last_checked": now_iso(),
            "source": "keepa",
        }

    return None


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
        "last_checked":  now_iso(),
    }


def _attr_chain(value, *names):
    for name in names:
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get(name)
        else:
            value = getattr(value, name, None)
    return value


def _amazon_item_title(item) -> str:
    return (
        _attr_chain(item, "item_info", "title", "display_value")
        or _attr_chain(item, "item_info", "title", "displayValue")
        or _attr_chain(item, "item_info", "title")
        or ""
    )


def _amazon_item_price(item) -> Optional[float]:
    listings = _attr_chain(item, "offers_v2", "listings") or []
    for listing in listings:
        amount = _attr_chain(listing, "price", "money", "amount")
        if amount is not None:
            return float(amount)
    return None


def _amazon_item_in_stock(item) -> Optional[bool]:
    listings = _attr_chain(item, "offers_v2", "listings") or []
    for listing in listings:
        availability_type = str(_attr_chain(listing, "availability", "type") or "").lower()
        availability_msg = str(_attr_chain(listing, "availability", "message") or "").lower()
        if availability_type or availability_msg:
            unavailable = ("out" in availability_type or "unavailable" in availability_type or "out of stock" in availability_msg)
            return not unavailable
    return None


def _amazon_item_image(item) -> Optional[str]:
    return (
        _attr_chain(item, "images", "primary", "large", "url")
        or _attr_chain(item, "images", "primary", "medium", "url")
        or _attr_chain(item, "images", "primary", "small", "url")
    )


def _amazon_item_offer(item, product: dict) -> dict:
    url = _attr_chain(item, "detail_page_url") or _attr_chain(item, "detailPageURL") or _amazon_affiliate_link(product)["url"]
    return {
        "retailer":      "amazon",
        "retailer_name": "Amazon",
        "price":         _amazon_item_price(item),
        "url":           append_affiliate(url, "amazon"),
        "in_stock":      _amazon_item_in_stock(item),
        "title":         _amazon_item_title(item) or product.get("name", ""),
        "image":         _amazon_item_image(item),
        "last_checked":  now_iso(),
        "source":        "amazon_creators_api",
    }


def _amazon_creators_api(product: dict, source_map: Optional[dict] = None) -> dict:
    global _amazon_creators_disabled
    if _amazon_creators_disabled:
        return None

    try:
        from amazon_creatorsapi import AmazonCreatorsApi, Country
        from amazon_creatorsapi.models import GetItemsResource, SearchItemsResource

        client = AmazonCreatorsApi(
            credential_id=AMAZON_CREATOR_CREDENTIAL_ID,
            credential_secret=AMAZON_CREATOR_SECRET,
            version=AMAZON_CREATOR_VERSION,
            tag=AMAZON_TAG,
            country=Country.US,
            throttling=float(os.getenv("AMAZON_CREATOR_THROTTLING") or "1"),
        )
        asins = _amazon_asins_for_product(product, source_map or {})
        used_exact_asin = bool(asins)
        if used_exact_asin:
            items = client.get_items(
                items=asins[:10],
                resources=[
                    GetItemsResource.OFFERS_V2_DOT_LISTINGS_DOT_PRICE,
                    GetItemsResource.OFFERS_V2_DOT_LISTINGS_DOT_AVAILABILITY,
                    GetItemsResource.ITEM_INFO_DOT_TITLE,
                    GetItemsResource.IMAGES_DOT_PRIMARY_DOT_LARGE,
                ],
            )
        else:
            query = product.get("amazon_query") or product["search_query"]
            response = client.search_items(
                keywords=query,
                item_count=1,
                resources=[
                    SearchItemsResource.OFFERS_V2_DOT_LISTINGS_DOT_PRICE,
                    SearchItemsResource.OFFERS_V2_DOT_LISTINGS_DOT_AVAILABILITY,
                    SearchItemsResource.ITEM_INFO_DOT_TITLE,
                    SearchItemsResource.IMAGES_DOT_PRIMARY_DOT_LARGE,
                ],
            )
            items = _attr_chain(response, "search_result", "items") or _attr_chain(response, "items") or []
        if not items:
            return None

        for item in items:
            offer = _amazon_item_offer(item, product)
            if used_exact_asin or _matches_product(product, offer.get("title", ""), offer.get("url", "")):
                return offer

        return None
    except ImportError as e:
        log.warning(f"Amazon Creators API unavailable: {e}")
        return None
    except Exception as e:
        if "AssociateNotEligible" in str(e):
            _amazon_creators_disabled = True
        log.warning(f"Amazon Creators API error: {e}")
        return None


def _merge_fast_lane_product(
    product: dict, baseline: Optional[dict], fresh_amazon: Optional[dict]
) -> Optional[dict]:
    """Patches only the amazon offer into an existing product entry, leaving
    every other retailer's last-full-sweep offer untouched -- the fast lane
    never runs Playwright, so it has nothing fresh to say about them.
    Returns None when there's nothing to report yet (no prior full-sweep
    entry and no fresh Amazon offer): a brand-new catalog product the next
    full sweep will pick up, not something the fast lane should fabricate."""
    offers = list(baseline.get("offers", [])) if baseline else []
    if fresh_amazon:
        offers = [offer for offer in offers if offer.get("retailer") != "amazon"]
        offers.append(fresh_amazon)

    if not offers:
        return baseline

    return {
        "id": product["id"],
        "slug": product["slug"],
        "name": product["name"],
        "category": product["category"],
        "active_ingredient": product.get("active_ingredient", ""),
        "alt_names": product.get("alt_names", []),
        "offers": offers,
        "best_price": select_best_offer(product, offers),
        "updated_at": now_iso() if fresh_amazon else (baseline or {}).get("updated_at", now_iso()),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def run_fast_lane():
    """API-only refresh (Amazon Creators API / Keepa, via amazon_result) for
    every catalog product, run on a tighter schedule than the full Playwright
    sweep since it makes a handful of HTTP calls instead of loading and
    scraping every saved source URL in a real browser. Existing offers from
    the last full sweep are preserved for every retailer this lane doesn't
    touch -- see _merge_fast_lane_product."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    products_path = os.path.join(repo_root, "products.json")
    prices_path = os.path.join(repo_root, "prices.json")
    alerts_path = os.path.join(repo_root, "price-alerts.json")
    health_path = os.path.join(repo_root, "source-health.json")
    sources_path = os.path.join(repo_root, "product_sources.json")

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

    try:
        with open(alerts_path) as f:
            existing_alerts = json.load(f).get("alerts", [])
    except (FileNotFoundError, json.JSONDecodeError):
        existing_alerts = []

    results = []
    updated = 0
    for product in catalog["products"]:
        baseline = stale_map.get(product["id"])
        fresh_amazon = amazon_result(product, source_map)
        if fresh_amazon:
            updated += 1
        entry = _merge_fast_lane_product(product, baseline, fresh_amazon)
        if entry:
            results.append(entry)

    apply_offer_package_metadata(results)
    apply_offer_quality_filters(results)
    sanitize_equipment_results(results)

    generated_at = now_iso()
    output = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "product_count": len(results),
        "products": results,
    }
    alerts_output = build_price_alerts(stale_map, results, generated_at, existing_alerts)
    health_output = build_source_health(catalog["products"], source_map, results, generated_at)

    with open(prices_path, "w") as f:
        json.dump(output, f, indent=2)
    with open(alerts_path, "w") as f:
        json.dump(alerts_output, f, indent=2)
    with open(health_path, "w") as f:
        json.dump(health_output, f, indent=2)

    log.info(
        f"Fast lane done. Refreshed Amazon pricing for {updated}/{len(catalog['products'])} products."
    )
    log.info(f"Written to {prices_path}")
    log.info(f"Written to {alerts_path} ({alerts_output['alert_count']} alerts)")
    log.info(f"Written to {health_path}")


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
    health_path   = os.path.join(repo_root, "source-health.json")
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

    try:
        with open(alerts_path) as f:
            existing_alerts = json.load(f).get("alerts", [])
    except (FileNotFoundError, json.JSONDecodeError):
        existing_alerts = []

    results = []
    total   = len(catalog["products"])

    # Refresh the stalest products first. A run that cannot finish the catalog
    # then fixes the worst data rather than redoing the same head every time.
    sweep_order = order_products_by_staleness(catalog["products"], stale_map)
    entering = offer_age_summary(list(stale_map.values()))
    log.info(
        f"Sweep order: stalest first. Feed on entry: oldest "
        f"{entering['oldest_hours']}h, median {entering['median_hours']}h "
        f"across {entering['count']} products."
    )
    sweep_started = time.monotonic()
    budget_exhausted = False

    with sync_playwright() as pw:
        _browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        log.info("Playwright browser launched")

        for i, product in enumerate(sweep_order, 1):
            elapsed = time.monotonic() - sweep_started
            if elapsed > SWEEP_TIME_BUDGET_SECONDS:
                budget_exhausted = True
                log.warning(
                    f"Time budget reached after {elapsed / 60:.1f} min at "
                    f"{i - 1}/{total} products. Publishing what is refreshed; "
                    f"the next run resumes with the stalest remaining."
                )
                break

            if i > 1 and (i - 1) % CHECKPOINT_EVERY == 0:
                _publish_feed(
                    results, stale_map, source_map, catalog, existing_alerts,
                    prices_path, alerts_path, health_path, sources_path,
                    emit_alerts=False,
                )
                log.info(f"  Checkpoint written at {i - 1}/{total}")

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
            r = amazon_result(product, source_map)
            is_usable_amazon = r and (
                r.get("price") is not None or not is_bad_product_url(r.get("url", ""))
            )
            if is_usable_amazon and add_offer(offers, r):
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

    results, source_map, found = _publish_feed(
        results,
        stale_map,
        source_map,
        catalog,
        existing_alerts,
        prices_path,
        alerts_path,
        health_path,
        sources_path,
        emit_alerts=True,
    )
    leaving = offer_age_summary(results)
    log.info(
        f"Feed on exit: oldest {leaving['oldest_hours']}h, median "
        f"{leaving['median_hours']}h across {leaving['count']} products."
    )
    if budget_exhausted:
        log.warning(
            "Sweep was cut short by its time budget. Expected when the catalog "
            "outgrows one run; the next run continues from the stalest."
        )
    # The failure this guards against is silent: the Amazon fast lane keeps
    # generated_at looking current while merchant prices quietly rot, which is
    # exactly how the feed reached ten days stale without anyone noticing.
    if (
        leaving["oldest_hours"] is not None
        and leaving["oldest_hours"] > MAX_OFFER_AGE_HOURS
    ):
        log.error(
            f"STALE FEED: oldest product data is {leaving['oldest_hours']}h old, "
            f"past the {MAX_OFFER_AGE_HOURS}h limit. The sweep is not keeping up "
            f"with the catalog. Raise timeout-minutes and SWEEP_TIME_BUDGET_SECONDS, "
            f"or split the sweep across more runs."
        )

    log.info(f"\nDone. {found}/{len(results)} products have a best price.")
    log.info(f"Written to {prices_path}")
    log.info(f"Written to {health_path}")
    log.info(f"Written to {sources_path}")

    min_priced_absolute = int(os.getenv("MIN_PRICED_PRODUCTS", "1"))
    min_priced = _min_priced_products_floor(
        len(results), min_priced_absolute, MIN_PRICED_PRODUCTS_PERCENT
    )
    if found < min_priced:
        log.error(
            f"Only {found}/{len(results)} products have prices; expected at least "
            f"{min_priced} ({MIN_PRICED_PRODUCTS_PERCENT:.0f}% of {len(results)}, "
            f"or {min_priced_absolute} absolute -- whichever is higher)."
        )
        sys.exit(1)


if __name__ == "__main__":
    if "--fast-lane" in sys.argv:
        run_fast_lane()
    else:
        run()
