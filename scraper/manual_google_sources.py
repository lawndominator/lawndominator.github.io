#!/usr/bin/env python3
"""
Manual Google source recorder.

Opens Brave with Google for each product. Browse normally, open as many merchant
product pages as needed, then use the floating controls injected into every tab:

  Record link       save the current tab for the current product
  Record all tabs   save all open merchant/product tabs for the current product
  Next product      move to the next product when you are done with this one

The recorder writes directly to product_sources.json so GitHub Actions can keep
checking those known URLs for price changes.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from find_links import (
    RETAILERS,
    _get_price_and_title,
    _product_queries,
    launch_browser_context,
    load_sources,
    now_iso,
    save_sources,
)


BAD_PATH_PARTS = (
    "/cart",
    "/checkout",
    "/account",
    "/login",
    "/signin",
    "/wishlist",
    "/search",
    "/s?",
    "/gp/cart",
    "/gp/aw/c",
)

RETAILER_NAMES = {retailer["key"]: retailer["name"] for retailer in RETAILERS}
RETAILER_HOST_HINTS = {
    "amazon.com": ("amazon", "Amazon"),
    "ebay.com": ("ebay", "eBay"),
    "walmart.com": ("walmart", "Walmart"),
    "domyown.com": ("domyown", "DoMyOwn"),
    "solutionsstores.com": ("solutions", "Solutions Pest & Lawn"),
    "solutionspestcontrol.com": ("solutions", "Solutions Pest & Lawn"),
}


def _host(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _retailer_from_url(url: str) -> tuple[str, str]:
    host = _host(url)
    for hint, retailer in RETAILER_HOST_HINTS.items():
        if host == hint or host.endswith("." + hint):
            return retailer

    key = re.sub(r"[^a-z0-9]+", "-", host.split(".")[0]).strip("-") or "web"
    return key, RETAILER_NAMES.get(key) or host.replace("-", " ").split(".")[0].title()


def _is_google_url(url: str) -> bool:
    host = _host(url)
    return host == "google.com" or host.endswith(".google.com")


def _is_bad_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parsed.query.lower()
    if not parsed.scheme.startswith("http"):
        return True
    if any(part in path for part in BAD_PATH_PARTS):
        return True
    if "amazon." in host and path.rstrip("/") == "/s":
        return True
    if "ebay." in host and path.startswith("/sch"):
        return True
    return "notify" in path or "notify" in query


def _canonical_from_html(html: str) -> str | None:
    match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
    if match:
        return match.group(1)
    match = re.search(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if match:
        return match.group(1)
    return None


def _resolve_google_redirect(url: str) -> str:
    if not _is_google_url(url):
        return url
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    for key in ("url", "q"):
        value = params.get(key, [""])[0]
        if value.startswith("http"):
            return value
    return url


def _normalize_url(url: str, html: str = "") -> str:
    url = _resolve_google_redirect(urllib.parse.urldefrag(url)[0].strip())
    canonical = _canonical_from_html(html)
    if canonical and canonical.startswith("http") and not _is_google_url(canonical):
        url = canonical

    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path

    amazon = re.search(r"/(?:[^/]+/)?(?:dp|gp/product)/([A-Z0-9]{10})", path, re.I)
    if "amazon." in host and amazon:
        return f"https://www.amazon.com/dp/{amazon.group(1).upper()}"

    ebay = re.search(r"/itm/(?:[^/]+/)?(\d+)", path, re.I)
    if "ebay." in host and ebay:
        return f"https://www.ebay.com/itm/{ebay.group(1)}"

    walmart = re.search(r"/ip/(?:[^/]+/)?(\d+)", path, re.I)
    if "walmart." in host and walmart:
        return f"https://www.walmart.com/ip/{walmart.group(1)}"

    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def _source_exists(sources: list[dict], url: str) -> bool:
    normalized = urllib.parse.urldefrag(url)[0].rstrip("/")
    return any(urllib.parse.urldefrag(s.get("url", ""))[0].rstrip("/") == normalized for s in sources)


def _record_source(page, product: dict, sources_data: dict, sources_path: Path) -> bool:
    try:
        raw_url = page.url
        html = page.content()
        title = page.title()
    except PlaywrightError as exc:
        print(f"  Could not read tab: {exc.__class__.__name__}")
        return False

    url = _normalize_url(raw_url, html)
    if _is_google_url(url):
        print(f"  Not recorded: still on Google ({raw_url})")
        return False
    if _is_bad_url(url):
        print(f"  Not recorded: cart/search/account URL ({url})")
        return False

    price, extracted_title = _get_price_and_title(html)
    title = (extracted_title or title or product["name"]).strip()
    retailer, retailer_name = _retailer_from_url(url)
    product_sources = sources_data.setdefault("products", {}).setdefault(str(product["id"]), [])

    source = {
        "url": url,
        "retailer": retailer,
        "retailer_name": retailer_name,
        "title": title[:180],
        "price_verified": price,
        "verified": True,
        "manual_verified": True,
        "source_type": "product",
        "image": None,
        "last_seen": now_iso(),
    }

    if _source_exists(product_sources, url):
        for existing in product_sources:
            if urllib.parse.urldefrag(existing.get("url", ""))[0].rstrip("/") == url:
                existing.update({key: value for key, value in source.items() if value is not None})
                break
        status = "Updated"
    else:
        product_sources.insert(0, source)
        status = "Recorded"

    save_sources(sources_path, sources_data)
    price_text = f"${price:.2f}" if price is not None else "$n/a"
    print(f"  {status:<8} {retailer_name:<24} {price_text:<8} {title[:70]}")
    print(f"           {url}")
    return True


def _google_url(product: dict) -> str:
    queries = _product_queries(product)
    query = f"{queries[0]} buy price"
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)


def _amazon_url(product: dict) -> str:
    query = product.get("amazon_query") or product.get("search_query") or product["name"]
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(f"site:amazon.com {query}")


def _ebay_url(product: dict) -> str:
    query = product.get("search_query") or product["name"]
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(f"site:ebay.com {query}")


def _overlay_script(product: dict, index: int, total: int, recorded_count: int) -> str:
    name = json.dumps(product["name"])
    queries = json.dumps(" | ".join(_product_queries(product)[:5]))
    google_url = json.dumps(_google_url(product))
    amazon_url = json.dumps(_amazon_url(product))
    ebay_url = json.dumps(_ebay_url(product))
    return f"""
(() => {{
  const old = document.getElementById('ld-source-recorder');
  if (old) old.remove();

  const box = document.createElement('div');
  box.id = 'ld-source-recorder';
  box.style.cssText = `
    position: fixed; z-index: 2147483647; top: 12px; right: 12px;
    width: 390px; padding: 12px; color: #111827; background: #ffffff;
    border: 2px solid #111827; border-radius: 8px;
    font: 13px/1.35 Arial, sans-serif; box-shadow: 0 12px 32px rgba(0,0,0,.28);
  `;
  box.innerHTML = `
    <div style="font-weight:700; font-size:15px; margin-bottom:3px;">${{ {name} }}</div>
    <div style="font-size:12px; color:#4b5563; margin-bottom:8px;">{index}/{total} - {recorded_count} saved</div>
    <div style="font-size:11px; color:#6b7280; margin-bottom:8px;">${{ {queries} }}</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">
      <button id="ld-record" style="padding:8px; font-weight:700;">Record link</button>
      <button id="ld-record-all" style="padding:8px; font-weight:700;">Record all tabs</button>
      <button id="ld-next" style="padding:8px;">Next product</button>
      <button id="ld-skip" style="padding:8px;">Skip</button>
      <button id="ld-google" style="padding:8px;">Google</button>
      <button id="ld-amazon" style="padding:8px;">Amazon Google</button>
      <button id="ld-ebay" style="padding:8px;">eBay Google</button>
      <button id="ld-hide" style="padding:8px;">Hide</button>
    </div>
    <div style="font-size:11px; color:#6b7280; margin-top:8px;">Open merchant pages, record the real product URL, then hit Next when this product is done.</div>
  `;
  document.documentElement.appendChild(box);

  const set = (action) => {{ window.__ldSourceRecorderAction = action; }};
  document.getElementById('ld-record').onclick = () => set('record');
  document.getElementById('ld-record-all').onclick = () => set('record_all');
  document.getElementById('ld-next').onclick = () => set('next');
  document.getElementById('ld-skip').onclick = () => set('skip');
  document.getElementById('ld-google').onclick = () => {{ location.href = {google_url}; }};
  document.getElementById('ld-amazon').onclick = () => {{ location.href = {amazon_url}; }};
  document.getElementById('ld-ebay').onclick = () => {{ location.href = {ebay_url}; }};
  document.getElementById('ld-hide').onclick = () => box.remove();
}})();
"""


def _safe_inject(page, product: dict, index: int, total: int, recorded_count: int) -> str | None:
    try:
        page.evaluate(_overlay_script(product, index, total, recorded_count))
        action = page.evaluate("window.__ldSourceRecorderAction || null")
        if action:
            page.evaluate("window.__ldSourceRecorderAction = null")
        return action
    except PlaywrightError:
        return None


def _record_all_tabs(ctx, product: dict, sources_data: dict, sources_path: Path) -> int:
    count = 0
    for page in list(ctx.pages):
        try:
            url = page.url
        except PlaywrightError:
            continue
        if _is_google_url(url) or url == "about:blank":
            continue
        if _record_source(page, product, sources_data, sources_path):
            count += 1
    return count


def _close_extra_tabs(ctx, keep_page) -> None:
    for page in list(ctx.pages):
        if page == keep_page:
            continue
        try:
            page.close()
        except PlaywrightError:
            pass


def _select_products(catalog: dict, ids: str | None, start_id: int | None) -> list[dict]:
    products = catalog["products"]
    if ids:
        selected = {int(v.strip()) for v in ids.split(",") if v.strip()}
        products = [product for product in products if int(product["id"]) in selected]
    if start_id is not None:
        started = False
        result = []
        for product in products:
            if int(product["id"]) == start_id:
                started = True
            if started:
                result.append(product)
        products = result
    return products


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", help="Comma-separated product IDs to record")
    parser.add_argument("--start-id", type=int, help="Start at this product ID and continue forward")
    parser.add_argument("--profile-dir", default="scraper/manual-google-profile")
    parser.add_argument("--output", default="product_sources.json")
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    catalog = json.loads((root / "products.json").read_text(encoding="utf-8"))
    sources_path = root / args.output
    sources_data = load_sources(sources_path)
    products = _select_products(catalog, args.ids, args.start_id)

    if not products:
        print("No products selected.")
        return 2

    print(f"Manual source recorder: {len(products)} product(s)")
    print("Use the floating controls in Brave. Close the browser window to stop.\n")

    with sync_playwright() as pw:
        ctx = launch_browser_context(pw, root, args.profile_dir)
        page = ctx.new_page()

        for index, product in enumerate(products, 1):
            saved = sources_data.setdefault("products", {}).setdefault(str(product["id"]), [])
            print(f"[{index}/{len(products)}] {product['name']} ({len(saved)} existing sources)")
            page.goto(_google_url(product), wait_until="domcontentloaded", timeout=30000)

            while True:
                if not ctx.pages:
                    print("\nBrowser closed.")
                    return 0

                recorded_count = len(sources_data.get("products", {}).get(str(product["id"]), []))
                handled = False
                for candidate in list(ctx.pages):
                    action = _safe_inject(candidate, product, index, len(products), recorded_count)
                    if not action:
                        continue

                    if action == "record":
                        _record_source(candidate, product, sources_data, sources_path)
                        handled = True
                    elif action == "record_all":
                        count = _record_all_tabs(ctx, product, sources_data, sources_path)
                        print(f"  Recorded {count} tab(s) for {product['name']}")
                        handled = True
                    elif action in ("next", "skip"):
                        print(f"  Done with {product['name']}\n")
                        page = candidate
                        _close_extra_tabs(ctx, page)
                        handled = True
                        break

                if action in ("next", "skip"):
                    break
                if not handled:
                    ctx.pages[0].wait_for_timeout(500)

        print("All selected products are done.")
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
