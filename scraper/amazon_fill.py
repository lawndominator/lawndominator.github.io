#!/usr/bin/env python3
"""Fill missing Amazon links for products that have no amazon.com source."""

import json
import re
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

AMAZON_TAG = "lawndominator-20"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _amazon_search_url(query):
    return f"https://www.amazon.com/s?k={urllib.parse.quote_plus(query)}"


def _extract_asins(html):
    asins = []
    seen = set()
    for m in re.finditer(r'/dp/([A-Z0-9]{10})', html):
        asin = m.group(1)
        if asin not in seen:
            seen.add(asin)
            asins.append(asin)
    return asins[:8]


def _fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


def _get_price_and_title(html):
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    for script in soup.select("script[type='application/ld+json']"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if str(obj.get("@type", "")).lower() != "product":
                continue
            offers = obj.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict):
                raw = offers.get("price") or offers.get("lowPrice") or ""
                m = re.search(r"(\d+(?:\.\d{1,2})?)", str(raw))
                if m:
                    price = float(m.group(1))
                    if price >= 5:
                        return price, title
    for sel in ["[data-asin-price]", "#priceblock_ourprice", "#priceblock_dealprice",
                ".a-price .a-offscreen", "[data-price]", ".a-color-price"]:
        el = soup.select_one(sel)
        if el:
            raw = el.get("content") or el.get("data-price") or el.get_text(" ", strip=True)
            m = re.search(r"(\d+(?:\.\d{1,2})?)", str(raw).replace(",", ""))
            if m:
                price = float(m.group(1))
                if price >= 5:
                    return price, title
    return None, title


def _title_matches(title, query):
    words = [w.lower() for w in query.split() if len(w) > 3]
    t = title.lower()
    return sum(1 for w in words if w in t) >= max(1, len(words) // 2)


def find_amazon_link(product):
    queries = [
        product.get("search_query", ""),
        product.get("name", ""),
        product.get("amazon_query", ""),
    ]
    queries = list(dict.fromkeys(q for q in queries if q))

    for query in queries[:3]:
        html = _fetch(_amazon_search_url(query))
        if not html:
            time.sleep(1)
            continue
        asins = _extract_asins(html)
        for asin in asins:
            url = f"https://www.amazon.com/dp/{asin}?tag={AMAZON_TAG}"
            page = _fetch(url)
            if not page:
                time.sleep(0.5)
                continue
            price, title = _get_price_and_title(page)
            if price and _title_matches(title, query):
                return url, price, title
            time.sleep(0.3)
        time.sleep(1.5)
    return None, None, None


def main():
    root = Path(__file__).parent.parent
    catalog = json.loads((root / "products.json").read_text(encoding="utf-8"))
    sources_path = root / "product_sources.json"
    sources_data = json.loads(sources_path.read_text(encoding="utf-8"))

    missing = []
    for p in catalog["products"]:
        if p["id"] < 200:
            continue
        srcs = sources_data["products"].get(str(p["id"]), [])
        if not any("amazon.com" in s.get("url", "") for s in srcs):
            missing.append(p)

    print(f"{len(missing)} equipment products missing Amazon links\n")

    for i, product in enumerate(missing, 1):
        pid = str(product["id"])
        print(f"[{i}/{len(missing)}] {product['name']}")
        url, price, title = find_amazon_link(product)
        if url:
            print(f"  FOUND  ${price:<8.2f}  {title[:55]}")
            print(f"         {url[:70]}")
            sources_data["products"].setdefault(pid, []).append({
                "url": url,
                "retailer": "amazon",
                "retailer_name": "Amazon",
                "title": title,
                "price_verified": price,
                "verified": True,
                "image": None,
                "last_seen": now_iso(),
            })
            sources_data["updated_at"] = now_iso()
            sources_path.write_text(json.dumps(sources_data, indent=2), encoding="utf-8")
        else:
            print(f"  not found")
        time.sleep(1)

    found = sum(1 for p in missing if any(
        "amazon.com" in s.get("url", "")
        for s in sources_data["products"].get(str(p["id"]), [])
    ))
    print(f"\nDone. {found}/{len(missing)} filled.")


if __name__ == "__main__":
    main()
