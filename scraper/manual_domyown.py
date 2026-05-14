#!/usr/bin/env python3
"""
Manual DoMyOwn source recorder.

Opens Brave with a small overlay. For each product, click to the right DoMyOwn
product page, then press "Record URL". The script saves that product URL to
product_sources.json so GitHub Actions can refresh the price later.
"""

import argparse
import json
import re
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

from find_links import (
    _get_price_and_title,
    _matches_product,
    _product_queries,
    launch_browser_context,
    load_sources,
    now_iso,
    save_sources,
)


DOMYOWN_PRODUCT_RE = re.compile(r"^https?://(?:www\.)?domyown\.com/[^?#]+-p-\d+\.html", re.I)


def _source_exists(sources: list[dict], url: str) -> bool:
    normalized = urllib.parse.urldefrag(url)[0].rstrip("/")
    return any(urllib.parse.urldefrag(s.get("url", ""))[0].rstrip("/") == normalized for s in sources)


def _upsert_source(sources_data: dict, product: dict, source: dict, refind: bool) -> None:
    products = sources_data.setdefault("products", {})
    pid = str(product["id"])
    current = products.setdefault(pid, [])
    if refind:
        current[:] = [s for s in current if s.get("retailer") != "domyown"]
    if not _source_exists(current, source["url"]):
        current.insert(0, source)


def _overlay_script(product: dict, index: int, total: int, queries: list[str]) -> str:
    name = json.dumps(product["name"])
    query_text = json.dumps(" | ".join(queries[:5]))
    search_url = json.dumps(
        "https://www.google.com/search?q="
        + urllib.parse.quote_plus(f"site:domyown.com {product.get('search_query') or product['name']}")
    )
    specials_url = json.dumps("https://www.domyown.com/specials?page=all")
    return f"""
(() => {{
  const old = document.getElementById('ld-domyown-recorder');
  if (old) old.remove();
  const box = document.createElement('div');
  box.id = 'ld-domyown-recorder';
  box.style.cssText = `
    position: fixed; z-index: 2147483647; top: 12px; right: 12px;
    width: 360px; padding: 12px; color: #111827; background: #ffffff;
    border: 2px solid #111827; border-radius: 8px;
    font: 13px/1.35 Arial, sans-serif; box-shadow: 0 12px 32px rgba(0,0,0,.28);
  `;
  box.innerHTML = `
    <div style="font-weight:700; font-size:14px; margin-bottom:4px;">${{ {name} }}</div>
    <div style="font-size:12px; color:#4b5563; margin-bottom:8px;">{index}/{total} &nbsp; ${{ {query_text} }}</div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px;">
      <button id="ld-record" style="padding:8px; font-weight:700;">Record URL</button>
      <button id="ld-skip" style="padding:8px;">Skip</button>
      <button id="ld-search" style="padding:8px;">Google Search</button>
      <button id="ld-specials" style="padding:8px;">Specials</button>
    </div>
    <div style="font-size:11px; color:#6b7280; margin-top:8px;">Click a DoMyOwn product page, then Record URL.</div>
  `;
  document.documentElement.appendChild(box);
  document.getElementById('ld-record').onclick = () => window.__ldAction = 'record';
  document.getElementById('ld-skip').onclick = () => window.__ldAction = 'skip';
  document.getElementById('ld-search').onclick = () => location.href = {search_url};
  document.getElementById('ld-specials').onclick = () => location.href = {specials_url};
}})();
"""


def _wait_action(page, product: dict, index: int, total: int, queries: list[str]) -> str:
    script = _overlay_script(product, index, total, queries)
    while True:
        try:
            page.evaluate(script)
            action = page.evaluate("window.__ldAction || null")
            if action:
                page.evaluate("window.__ldAction = null")
                return action
        except Exception:
            pass
        page.wait_for_timeout(500)


def _record_current_page(page, product: dict, sources_data: dict, sources_path: Path, refind: bool) -> bool:
    url = urllib.parse.urldefrag(page.url)[0].rstrip("/")
    if not DOMYOWN_PRODUCT_RE.match(url):
        print(f"  Not a DoMyOwn product URL: {url}")
        return False

    html = page.content()
    price, title = _get_price_and_title(html)
    title = title or page.title()
    queries = _product_queries(product)
    matched = any(_matches_product(product, title, url, query) for query in queries)
    if not matched:
        print(f"  Warning: title did not match strict rules: {title[:90]}")

    source = {
        "url": url,
        "retailer": "domyown",
        "retailer_name": "DoMyOwn",
        "title": title,
        "price_verified": price,
        "verified": True,
        "manual_verified": True,
        "image": None,
        "last_seen": now_iso(),
    }
    _upsert_source(sources_data, product, source, refind)
    save_sources(sources_path, sources_data)
    print(f"  Recorded DoMyOwn: ${price if price is not None else 'n/a'}  {title[:80]}")
    print(f"  {url}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", help="Comma-separated product IDs")
    parser.add_argument("--refind", action="store_true", help="Replace existing DoMyOwn sources for selected products")
    parser.add_argument("--profile-dir", default="scraper/domyown-manual-profile")
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    products_path = root / "products.json"
    sources_path = root / "product_sources.json"
    catalog = json.loads(products_path.read_text())
    sources_data = load_sources(sources_path)

    products = catalog["products"]
    if args.ids:
        ids = {int(v.strip()) for v in args.ids.split(",") if v.strip()}
        products = [p for p in products if p["id"] in ids]

    existing = sources_data.setdefault("products", {})
    with sync_playwright() as pw:
        ctx = launch_browser_context(pw, root, args.profile_dir)
        page = ctx.new_page()
        page.goto("https://www.domyown.com/specials?page=all", wait_until="domcontentloaded", timeout=30000)

        for index, product in enumerate(products, 1):
            current = existing.get(str(product["id"]), [])
            has_domyown = any(s.get("retailer") == "domyown" and s.get("verified") for s in current)
            if has_domyown and not args.refind:
                print(f"[{index}/{len(products)}] {product['name']} - skipped existing DoMyOwn source")
                continue

            queries = _product_queries(product)
            print(f"[{index}/{len(products)}] {product['name']}")
            print(f"  Search terms: {', '.join(queries[:5])}")
            page.goto(
                "https://www.google.com/search?q="
                + urllib.parse.quote_plus(f"site:domyown.com {queries[0]}"),
                wait_until="domcontentloaded",
                timeout=30000,
            )

            while True:
                action = _wait_action(page, product, index, len(products), queries)
                if action == "skip":
                    print("  Skipped")
                    break
                if action == "record" and _record_current_page(page, product, sources_data, sources_path, args.refind):
                    break

        ctx.close()


if __name__ == "__main__":
    main()
