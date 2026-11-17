#!/usr/bin/env python3
"""Keep price-history.json: one headline price per product per day.

prices.json only ever holds the current prices, so nothing downstream can say
whether today's price is high or low. Each feed write calls this to record
the day's headline price per product. The website draws the trend from it.

    python scraper/price_history.py                    # record today's feed
    python scraper/price_history.py --backfill 2026-09-04   # rebuild from git

The headline rule here must stay the same as the website's (toBoardRows in
lawndominator-website src/lib/prices.ts): verified, in stock, scrape errors
removed, and a price read on the last sweep ahead of a price on file.

Two differences, both because the record only holds prices somebody read: on
a day when Amazon's price could not be confirmed the board shows the best store
price, and when no store could be read it shows the price on file. The record
keeps no point for either day.
"""

import argparse
import json
import os
import statistics
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = "1.0"
KEEP_DAYS = 180
STORED_PRICE_SOURCE = "manual_verified_source"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _publishable(offer: dict) -> bool:
    price = offer.get("price")
    # An Amazon API price counts only when Amazon marked it as the featured
    # offer. Before 2026-11-17 the scraper recorded whichever listing came
    # first, which could be a price nobody saw on the product page.
    if offer.get("source") == "amazon_creators_api" and offer.get("featured_offer") is not True:
        return False
    return (
        isinstance(price, (int, float))
        and price > 0
        and offer.get("in_stock") is not False
        and not offer.get("excluded")
        and offer.get("quality_verified") is True
    )


def _size(offer: dict) -> str:
    return str(offer.get("package_label") or "").strip()


def _without_scrape_errors(offers: list) -> list:
    """Within one package size, a price under 30% of the median of three or
    more offers is a shipping fee or an accessory, not a deal."""
    by_size: dict = {}
    for offer in offers:
        by_size.setdefault(_size(offer), []).append(offer)
    kept = []
    for group in by_size.values():
        if len(group) < 3:
            kept.extend(group)
            continue
        median = statistics.median(o["price"] for o in group)
        kept.extend(o for o in group if o["price"] >= median * 0.3)
    return kept


def headline_offer(product: dict) -> Optional[dict]:
    offers = _without_scrape_errors([o for o in product.get("offers", []) if _publishable(o)])
    if not offers:
        return None
    read = [o for o in offers if o.get("source") != STORED_PRICE_SOURCE]
    return min(read or offers, key=lambda o: o["price"])


def _amazon_price_unconfirmed(product: dict) -> bool:
    """Amazon had a price for this product that it did not mark as featured,
    so what a shopper would have paid there that day is unknown."""
    return any(
        o.get("source") == "amazon_creators_api"
        and isinstance(o.get("price"), (int, float))
        and o.get("in_stock") is not False
        and o.get("featured_offer") is not True
        for o in product.get("offers", [])
    )


def record(history: dict, feed: dict, keep_days: int = KEEP_DAYS) -> dict:
    """Return `history` with the feed's day recorded. Idempotent per day, and
    safe to call with feeds out of order."""
    day = str(feed["generated_at"])[:10]
    products = {slug: list(points) for slug, points in (history.get("products") or {}).items()}

    for product in feed.get("products", []):
        slug = product.get("slug")
        best = headline_offer(product)
        if not slug or best is None:
            continue
        # The day is left as a gap rather than given the next store's price:
        # that would make the first confirmed Amazon price look like a record
        # low it may never have been.
        if _amazon_price_unconfirmed(product):
            continue
        # A price on file was not read that day, so it is not that day's price.
        if best.get("source") == STORED_PRICE_SOURCE:
            continue
        point = [day, round(float(best["price"]), 2), _size(best) or None]
        points = [p for p in products.get(slug, []) if p[0] != day]
        points.append(point)
        products[slug] = points

    latest = max([day, str(history.get("updated_at") or "")[:10]])
    cutoff = (date.fromisoformat(latest) - timedelta(days=keep_days)).isoformat()
    for slug in list(products):
        kept = sorted((p for p in products[slug] if p[0] >= cutoff), key=lambda p: p[0])
        if kept:
            products[slug] = kept
        else:
            del products[slug]

    newer = str(feed["generated_at"]) >= str(history.get("updated_at") or "")
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": feed["generated_at"] if newer else history["updated_at"],
        "products": dict(sorted(products.items())),
    }


def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _write(path: Path, history: dict) -> None:
    # One product per line: compact, and a daily diff shows what changed.
    lines = [
        f'  {json.dumps(slug)}: {json.dumps(points, separators=(",", ":"))}'
        for slug, points in history["products"].items()
    ]
    path.write_text(
        "{\n"
        f'"schema_version": {json.dumps(history["schema_version"])},\n'
        f'"updated_at": {json.dumps(history["updated_at"])},\n'
        '"products": {\n' + ",\n".join(lines) + "\n}\n}\n"
    )


def _git(*args: str, env_tz: Optional[str] = None) -> str:
    env = {**os.environ, "TZ": env_tz} if env_tz else None
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], check=True, capture_output=True, text=True, env=env
    ).stdout


def backfill(history: dict, since: str) -> dict:
    """Rebuild from the committed prices.json files since `since`, using the
    last feed committed on each UTC day."""
    last_sha_of_day: dict = {}
    log = _git(
        "log", f"--since={since}T00:00:00Z", "--date=iso-strict-local",
        "--format=%H %cd", "--reverse", "--", "prices.json",
        env_tz="UTC",
    )
    for line in log.splitlines():
        sha, committed = line.split()
        last_sha_of_day[committed[:10]] = sha
    for day in sorted(last_sha_of_day):
        try:
            feed = json.loads(_git("show", f"{last_sha_of_day[day]}:prices.json"))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        if str(feed.get("generated_at") or "")[:10] >= since:
            history = record(history, feed)
    return history


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--backfill", metavar="YYYY-MM-DD", help="rebuild from git history since this day")
    args = parser.parse_args()

    path = REPO_ROOT / "price-history.json"
    history = _load(path)
    if args.backfill:
        history = backfill(history, args.backfill)
    history = record(history, json.loads((REPO_ROOT / "prices.json").read_text()))
    _write(path, history)
    days = {p[0] for points in history["products"].values() for p in points}
    print(f"price history: {len(history['products'])} products, {len(days)} days, through {max(days)}")


if __name__ == "__main__":
    main()
