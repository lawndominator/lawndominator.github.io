#!/usr/bin/env python3
"""Alarm on the feed customers actually receive.

The scraper can be green while the published feed is useless. That happened on
2026-09-03: the publish gate failed on one offer so nothing was committed for
13 hours, and because the website fails closed on unverified prices it served
0 priced offers out of 1,814 available upstream. Nothing noticed. A customer
did.

This checks the public URL rather than the repo, because the repo being fine is
not the thing that matters, and it checks that prices are actually present, not
just that the file parses.
"""

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Optional

PRICES_URL = "https://lawndominators.com/prices.json"
DEFAULT_MAX_AGE_HOURS = 12.0
DEFAULT_MIN_PRICED_OFFERS = 50


def parse_generated_at(value: str) -> Optional[datetime]:
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def feed_problems(
    feed: dict,
    now: datetime,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    min_priced_offers: int = DEFAULT_MIN_PRICED_OFFERS,
) -> list[str]:
    problems: list[str] = []
    products = feed.get("products")
    if not isinstance(products, list) or not products:
        return ["published feed has no products"]

    generated = parse_generated_at(str(feed.get("generated_at") or ""))
    if generated is None:
        problems.append("published feed has no valid generated_at")
    else:
        age_hours = (now - generated).total_seconds() / 3600
        if age_hours > max_age_hours:
            problems.append(
                f"published feed is {age_hours:.1f}h old (limit {max_age_hours:.0f}h); "
                "the scraper is probably not committing"
            )

    priced = sum(
        1
        for product in products
        for offer in (product.get("offers") or [])
        if isinstance(offer.get("price"), (int, float))
    )
    if priced < min_priced_offers:
        problems.append(
            f"published feed carries {priced} priced offer(s), below {min_priced_offers}; "
            "the proxy is probably filtering everything out"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=PRICES_URL)
    parser.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS)
    parser.add_argument(
        "--min-priced-offers", type=int, default=DEFAULT_MIN_PRICED_OFFERS
    )
    args = parser.parse_args()

    request = urllib.request.Request(
        args.url, headers={"User-Agent": "lawndominators-feed-monitor"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        feed = json.loads(response.read().decode("utf-8"))

    problems = feed_problems(
        feed,
        datetime.now(timezone.utc),
        args.max_age_hours,
        args.min_priced_offers,
    )
    if problems:
        print(f"published price feed is unhealthy ({args.url}):")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print(f"published price feed is healthy ({args.url})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
