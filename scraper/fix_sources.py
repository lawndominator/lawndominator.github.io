#!/usr/bin/env python3
"""Remove bad Amazon entries and re-fill, then search new specialty retailers."""

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

# ASINs we know are wrong — remove these
BAD_ASINS = {
    "B0746S92WW",  # Invatech Italia (saved for STIHL SR 200 — totally wrong)
    "B00JSZ4608",  # STIHL SG20 (saved for STIHL SR 450 — wrong model)
    "B0GCJRKTDS",  # SideKing (saved for Chapin 63985 + 61500 — wrong brand)
    "B0FTGVGDD5",  # Chapin 89000A (saved for Chapin 8201B — wrong model)
    "B0FPGJJ4Y7",  # Brinly BS26BH (saved for BS-36BH — wrong model)
}

# Known-correct ASINs to inject directly
KNOWN_GOOD = {
    247: ("B005FPUHEE", "Chapin 61500 4-Gallon Backpack Sprayer", 71.39),
    224: ("B0FMLBDQ2D", "Brinly BS36BH-A Tow Behind Broadcast Spreader", 339.99),
}

# New specialty retailers to search for equipment
NEW_RETAILERS = [
    {
        "key": "qspray",
        "name": "QSpray",
        "base": "https://www.qspray.com",
        "search": "https://www.qspray.com/search?q={query}&type=product",
    },
    {
        "key": "gemplers",
        "name": "Gemplers",
        "base": "https://www.gemplers.com",
        "search": "https://www.gemplers.com/search?q={query}",
    },
    {
        "key": "sprayer-depot",
        "name": "Sprayer Depot",
        "base": "https://www.sprayerdepot.com",
        "search": "https://www.sprayerdepot.com/search?q={query}&type=product",
    },
    {
        "key": "rittenhouse",
        "name": "M. Rittenhouse",
        "base": "https://www.mrittenhouse.com",
        "search": "https://www.mrittenhouse.com/search?q={query}&type=product",
    },
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
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
        for obj in (data if isinstance(data, list) else [data]):
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
    for sel in ["[itemprop='price']", ".a-price .a-offscreen", ".price--withoutTax",
                "[class*='sale-price']", "[class*='product-price']", ".price"]:
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


def _product_links(html, base):
    soup = BeautifulSoup(html, "lxml")
    seen, links = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            href = base.rstrip("/") + "/" + href.lstrip("/")
        parsed = urllib.parse.urlparse(href)
        base_host = urllib.parse.urlparse(base).netloc.lower().removeprefix("www.")
        host = parsed.netloc.lower().removeprefix("www.")
        if host != base_host:
            continue
        path = parsed.path.lower()
        if "/products/" not in path and "/product/" not in path:
            continue
        if a.find_parent(["nav", "header"]):
            continue
        clean = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
        if clean not in seen:
            seen.add(clean)
            links.append(clean)
        if len(links) >= 6:
            break
    return links


def search_retailer(retailer, query):
    encoded = urllib.parse.quote_plus(query)
    url = retailer["search"].format(query=encoded)
    html = _fetch(url)
    if not html:
        return []
    return _product_links(html, retailer["base"])


def amazon_search(query):
    url = f"https://www.amazon.com/s?k={urllib.parse.quote_plus(query)}"
    html = _fetch(url)
    if not html:
        return []
    asins = []
    seen = set()
    for m in re.finditer(r'/dp/([A-Z0-9]{10})', html):
        asin = m.group(1)
        if asin not in seen:
            seen.add(asin)
            asins.append(asin)
    return [f"https://www.amazon.com/dp/{a}?tag={AMAZON_TAG}" for a in asins[:6]]


def main():
    root = Path(__file__).parent.parent
    catalog = json.loads((root / "products.json").read_text(encoding="utf-8"))
    sources_path = root / "product_sources.json"
    sources_data = json.loads(sources_path.read_text(encoding="utf-8"))

    equipment = [p for p in catalog["products"] if p["id"] >= 200]

    # Step 1: Remove bad ASINs
    removed = 0
    for p in equipment:
        pid = str(p["id"])
        before = sources_data["products"].get(pid, [])
        after = [s for s in before if not any(bad in s.get("url", "") for bad in BAD_ASINS)]
        if len(after) < len(before):
            removed += len(before) - len(after)
            sources_data["products"][pid] = after
    print(f"Removed {removed} bad Amazon entries\n")

    # Step 2: Inject known-correct ASINs
    for pid, (asin, title, price) in KNOWN_GOOD.items():
        url = f"https://www.amazon.com/dp/{asin}?tag={AMAZON_TAG}"
        existing = sources_data["products"].get(str(pid), [])
        if not any("amazon.com" in s.get("url", "") for s in existing):
            existing.append({
                "url": url, "retailer": "amazon", "retailer_name": "Amazon",
                "title": title, "price_verified": price, "verified": True,
                "image": None, "last_seen": now_iso(),
            })
            sources_data["products"][str(pid)] = existing
            print(f"Injected Amazon for {pid}: {title[:50]}")

    # Step 3: Re-search Amazon for products still missing it
    still_missing_amazon = [
        p for p in equipment
        if not any("amazon.com" in s.get("url", "")
                   for s in sources_data["products"].get(str(p["id"]), []))
    ]
    if still_missing_amazon:
        print(f"\nRe-searching Amazon for {len(still_missing_amazon)} products...")
        for p in still_missing_amazon:
            pid = str(p["id"])
            query = p.get("amazon_query") or p.get("search_query") or p["name"]
            print(f"  {p['name'][:50]}")
            for url in amazon_search(query):
                asin = re.search(r'/dp/([A-Z0-9]{10})', url)
                if not asin or asin.group(1) in BAD_ASINS:
                    continue
                html = _fetch(url)
                if not html:
                    time.sleep(0.5)
                    continue
                price, title = _get_price_and_title(html)
                if price and _title_matches(title, query):
                    print(f"    FOUND ${price:.2f} {title[:50]}")
                    sources_data["products"].setdefault(pid, []).append({
                        "url": url, "retailer": "amazon", "retailer_name": "Amazon",
                        "title": title, "price_verified": price, "verified": True,
                        "image": None, "last_seen": now_iso(),
                    })
                    break
                time.sleep(0.3)
            time.sleep(1)

    # Step 4: Hit new specialty retailers for all equipment
    print(f"\nSearching {len(NEW_RETAILERS)} new specialty retailers for {len(equipment)} products...")
    for retailer in NEW_RETAILERS:
        print(f"\n  {retailer['name']}")
        for p in equipment:
            pid = str(p["id"])
            existing_urls = {s.get("url", "") for s in sources_data["products"].get(pid, [])}
            if any(retailer["key"] in s.get("retailer", "") for s in sources_data["products"].get(pid, [])):
                continue  # already have this retailer
            query = p.get("search_query") or p["name"]
            urls = search_retailer(retailer, query)
            for url in urls:
                if url in existing_urls:
                    continue
                html = _fetch(url)
                if not html:
                    time.sleep(0.3)
                    continue
                price, title = _get_price_and_title(html)
                if price and _title_matches(title, query):
                    print(f"    {p['name'][:40]:<40} ${price:<8.2f} {title[:35]}")
                    sources_data["products"].setdefault(pid, []).append({
                        "url": url, "retailer": retailer["key"],
                        "retailer_name": retailer["name"],
                        "title": title, "price_verified": price, "verified": True,
                        "image": None, "last_seen": now_iso(),
                    })
                    existing_urls.add(url)
                time.sleep(0.3)
            time.sleep(0.5)

    sources_data["updated_at"] = now_iso()
    sources_path.write_text(json.dumps(sources_data, indent=2), encoding="utf-8")

    total = sum(len(sources_data["products"].get(str(p["id"]), [])) for p in equipment)
    print(f"\nDone. {total} total sources across {len(equipment)} equipment products.")


if __name__ == "__main__":
    main()
