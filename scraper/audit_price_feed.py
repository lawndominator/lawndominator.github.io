#!/usr/bin/env python3
"""Fail closed when the published price/alert feeds are not safe to display.

This is intentionally separate from the scraper's extraction tests. Parser
tests prove individual helpers; this audit inspects every catalog product and
every generated offer as one publication artifact before GitHub Actions may
commit it.
"""

import argparse
import copy
import json
from pathlib import Path
from typing import Optional

import scraper


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def _same_offer(first: Optional[dict], second: Optional[dict]) -> bool:
    if not first or not second:
        return first is second
    try:
        same_price = abs(float(first.get("price")) - float(second.get("price"))) < 0.01
    except (TypeError, ValueError):
        return False
    return bool(
        same_price
        and first.get("retailer") == second.get("retailer")
        and scraper._product_page_key(first.get("url", ""))
        == scraper._product_page_key(second.get("url", ""))
    )


def audit_feed(catalog: dict, feed: dict, alert_feed: dict) -> list[str]:
    issues: list[str] = []
    catalog_products = catalog.get("products") if isinstance(catalog, dict) else None
    feed_products = feed.get("products") if isinstance(feed, dict) else None
    alerts = alert_feed.get("alerts") if isinstance(alert_feed, dict) else None
    if not isinstance(catalog_products, list):
        return ["products.json: products must be an array"]
    if not isinstance(feed_products, list):
        return ["prices.json: products must be an array"]
    if not isinstance(alerts, list):
        return ["price-alerts.json: alerts must be an array"]

    if feed.get("schema_version") != "1.0":
        issues.append("prices.json: unsupported schema_version")
    if feed.get("product_count") != len(feed_products):
        issues.append("prices.json: product_count does not match products length")
    if not scraper._parse_alert_time(str(feed.get("generated_at") or "")):
        issues.append("prices.json: generated_at is missing or invalid")

    catalog_by_id = {int(product["id"]): product for product in catalog_products}
    seen_ids = set()
    seen_slugs = set()
    displayed_count = 0
    shared_pages: dict[str, set[int]] = {}

    for product in feed_products:
        try:
            product_id = int(product["id"])
        except (KeyError, TypeError, ValueError):
            issues.append("prices.json: product has an invalid id")
            continue
        slug = str(product.get("slug") or "")
        label = f"{product_id} {slug or '<missing-slug>'}"
        if product_id in seen_ids:
            issues.append(f"{label}: duplicate product id")
        if not slug or slug in seen_slugs:
            issues.append(f"{label}: missing or duplicate product slug")
        seen_ids.add(product_id)
        seen_slugs.add(slug)

        catalog_product = catalog_by_id.get(product_id)
        if not catalog_product:
            issues.append(f"{label}: product is absent from products.json")
            continue
        if catalog_product.get("slug") != slug:
            issues.append(f"{label}: slug disagrees with products.json")

        offers = product.get("offers")
        if not isinstance(offers, list):
            issues.append(f"{label}: offers must be an array")
            continue

        page_offer_keys = set()
        offers_by_package = {}
        for index, offer in enumerate(offers):
            offer_label = f"{label} offer[{index}]"
            price = scraper._valid_price(offer)
            if offer.get("price") is not None and price is None:
                issues.append(f"{offer_label}: price is not numeric")
                continue
            if price is None or offer.get("excluded") or offer.get("in_stock") is False:
                continue

            displayed_count += 1
            if offer.get("quality_verified") is not True:
                issues.append(
                    f"{offer_label}: displayed price is not independently quality-verified"
                )
            url = str(offer.get("url") or "")
            if not url:
                issues.append(f"{offer_label}: priced offer has no URL")
                continue
            if scraper.is_insecure_retailer_url(url):
                issues.append(f"{offer_label}: priced offer URL is not HTTPS")
            if scraper.is_untrusted_retailer_url(url):
                issues.append(f"{offer_label}: untrusted retailer domain")
            if scraper.is_google_url(url) or scraper.is_bad_product_url(url):
                issues.append(f"{offer_label}: URL is not a direct purchase page")
            if scraper.is_non_retail_offer(offer.get("title", ""), url):
                issues.append(f"{offer_label}: laboratory/non-retail product")
            if not scraper._matches_product(catalog_product, offer.get("title", ""), url):
                issues.append(f"{offer_label}: offer identity does not match catalog product")
            if offer.get("last_checked") and scraper._timestamp_is_stale(str(offer["last_checked"])):
                issues.append(f"{offer_label}: price is older than {scraper.MAX_OFFER_AGE_HOURS:g} hours")

            quantity = offer.get("package_quantity")
            unit_price = offer.get("price_per_unit")
            inferred_package = scraper.infer_package_size(catalog_product, offer)
            if inferred_package and quantity is not None and offer.get("package_unit"):
                try:
                    package_disagrees = (
                        abs(float(quantity) - float(inferred_package["package_quantity"])) > 0.001
                        or str(offer["package_unit"]).lower()
                        != str(inferred_package["package_unit"]).lower()
                    )
                except (TypeError, ValueError):
                    package_disagrees = True
                if package_disagrees:
                    issues.append(
                        f"{offer_label}: published package {offer.get('package_label')} "
                        f"disagrees with retailer text ({inferred_package['package_label']})"
                    )
            if (
                scraper._is_dry_formulation(catalog_product)
                and str(offer.get("package_unit") or "").lower() == "fl oz"
            ):
                issues.append(
                    f"{offer_label}: dry formulation is incorrectly measured in fluid ounces"
                )
            if offer.get("quality_verified") is True and not offer.get("manual_verified"):
                peers = [
                    peer
                    for peer in offers
                    if not peer.get("excluded")
                    and peer.get("quality_verified") is True
                    and peer.get("package_quantity") == offer.get("package_quantity")
                    and peer.get("package_unit") == offer.get("package_unit")
                ]
                entities = {scraper._retailer_entity(peer) for peer in peers}
                if len(entities) < 2:
                    issues.append(
                        f"{offer_label}: price is not independently corroborated"
                    )
            if quantity is not None or unit_price is not None:
                try:
                    expected = price / float(quantity)
                    reported = float(unit_price)
                    tolerance = max(0.02, expected * 0.03)
                    if not offer.get("package_unit") or abs(expected - reported) > tolerance:
                        issues.append(f"{offer_label}: package unit-price arithmetic is inconsistent")
                except (TypeError, ValueError, ZeroDivisionError):
                    issues.append(f"{offer_label}: package/unit-price metadata is incomplete")

            page = scraper._product_page_key(url)
            offer_key = (
                page,
                offer.get("package_quantity"),
                offer.get("package_unit"),
                round(price, 2),
            )
            if page and offer.get("in_stock") is not False and offer_key in page_offer_keys:
                issues.append(f"{offer_label}: duplicate product-page offer")
            if offer.get("in_stock") is not False:
                page_offer_keys.add(offer_key)
            if page:
                shared_pages.setdefault(page, set()).add(product_id)

            if (
                offer.get("in_stock") is not False
                and quantity is not None
                and offer.get("package_unit")
            ):
                try:
                    package_key = (round(float(quantity), 4), str(offer["package_unit"]).lower())
                    offers_by_package.setdefault(package_key, []).append(offer)
                except (TypeError, ValueError):
                    pass

        for cohort in offers_by_package.values():
            current = list(cohort)
            while len(current) >= 3:
                prices = sorted(scraper._valid_price(offer) for offer in current)
                midpoint = len(prices) // 2
                median = (
                    prices[midpoint]
                    if len(prices) % 2
                    else (prices[midpoint - 1] + prices[midpoint]) / 2
                )
                outliers = [
                    offer
                    for offer in current
                    if scraper._valid_price(offer) < median * 0.45
                    or scraper._valid_price(offer) > median * 2.5
                ]
                if not outliers:
                    break
                for offer in outliers:
                    price = scraper._valid_price(offer)
                    issues.append(
                        f"{label}: displayed same-package price ${price:.2f} is an "
                        f"implausible outlier from the ${median:.2f} median"
                    )
                current = [offer for offer in current if offer not in outliers]

        expected_best = scraper.select_best_offer(
            catalog_product,
            offers,
            require_quality_verified=True,
        )
        if not _same_offer(expected_best, product.get("best_price")):
            issues.append(f"{label}: best_price does not match the safest eligible offer")
        if product.get("best_price") and product["best_price"].get("quality_verified") is not True:
            issues.append(f"{label}: best_price is not independently quality-verified")

    for page, product_ids in shared_pages.items():
        if len(product_ids) > 1:
            issues.append(
                f"prices.json: purchase page {page} is displayed for multiple products "
                f"{sorted(product_ids)}"
            )

    minimum_displayed_products = scraper._min_priced_products_floor(
        len(feed_products), 1, scraper.MIN_PRICED_PRODUCTS_PERCENT
    )
    products_with_best = sum(1 for product in feed_products if product.get("best_price"))
    if products_with_best < minimum_displayed_products:
        issues.append(
            f"prices.json: only {products_with_best}/{len(feed_products)} products have a safe best price; "
            f"minimum is {minimum_displayed_products}"
        )
    if displayed_count == 0:
        issues.append("prices.json: no safe priced offers remain")

    current_by_slug = {product.get("slug"): product for product in feed_products}
    seen_alert_ids = set()
    recent_alert_ids = {
        alert.get("id")
        for alert in scraper._recent_alerts(alerts, str(alert_feed.get("generated_at") or ""))
    }
    for index, alert in enumerate(alerts):
        label = f"price-alerts.json alert[{index}]"
        alert_id = alert.get("id")
        if not isinstance(alert_id, str) or not alert_id:
            issues.append(f"{label}: missing id")
        elif alert_id in seen_alert_ids:
            issues.append(f"{label}: duplicate id {alert_id}")
        seen_alert_ids.add(alert_id)
        if alert.get("type") not in {
            "best_price_drop", "major_price_drop", "new_lowest_retailer", "back_in_stock"
        }:
            issues.append(f"{label}: invalid type")
        if not isinstance(alert.get("product_name"), str) or not alert.get("product_name"):
            issues.append(f"{label}: missing product_name")
        if not isinstance(alert.get("product_slug"), str) or not alert.get("product_slug"):
            issues.append(f"{label}: missing product_slug")
        alert_url = str(alert.get("url") or "")
        if (
            not alert_url
            or scraper.is_insecure_retailer_url(alert_url)
            or scraper.is_untrusted_retailer_url(alert_url)
            or scraper.is_bad_product_url(alert_url)
        ):
            issues.append(f"{label}: unsafe or missing purchase URL")
        if alert_id not in recent_alert_ids:
            issues.append(f"{label}: created_at is invalid or outside retention")
        if not scraper._alert_matches_current_best(alert, current_by_slug):
            issues.append(f"{label}: alert does not match the current safe best offer")
        try:
            drop_percent = float(alert.get("drop_percent") or 0)
            if alert.get("type") in {
                "best_price_drop", "major_price_drop", "new_lowest_retailer"
            }:
                old_price = float(alert.get("old_price"))
                new_price = float(alert.get("new_price"))
                expected_drop = (old_price - new_price) / old_price * 100
                if old_price <= new_price or new_price <= 0 or abs(expected_drop - drop_percent) > 0.2:
                    issues.append(f"{label}: price-drop arithmetic is inconsistent")
                if not alert.get("quality_verified"):
                    issues.append(f"{label}: price drop is not independently quality-verified")
        except (TypeError, ValueError):
            issues.append(f"{label}: price or drop_percent is invalid")

    return issues


def sanitize_existing_feed() -> None:
    catalog = _load("products.json")
    feed = _load("prices.json")
    alert_feed = _load("price-alerts.json")
    source_map = _load("product_sources.json")
    products = copy.deepcopy(feed.get("products", []))

    # Use the corrected catalog identity fields in the published rows.
    catalog_by_id = {int(product["id"]): product for product in catalog["products"]}
    for product in products:
        catalog_product = catalog_by_id.get(int(product.get("id", -1)))
        if not catalog_product:
            continue
        for key in ("slug", "name", "category", "active_ingredient", "alt_names"):
            if key in catalog_product:
                product[key] = copy.deepcopy(catalog_product[key])

        # Older published offers predate the explicit manual_verified field.
        # Recover it from the authoritative source registry by canonical page,
        # rather than trusting the offer's descriptive `source` string.
        source_entries = source_map.get("products", {}).get(str(product["id"]), [])
        manually_verified_pages = {
            scraper._product_page_key(str(source.get("url") or ""))
            for source in source_entries
            if source.get("manual_verified")
        }
        for offer in product.get("offers", []):
            if scraper._product_page_key(str(offer.get("url") or "")) in manually_verified_pages:
                offer["manual_verified"] = True

    scraper.apply_offer_package_metadata(products)
    scraper.apply_offer_quality_filters(products)
    scraper.sanitize_equipment_results(products)
    generated_at = str(feed.get("generated_at") or scraper.now_iso())
    output = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "product_count": len(products),
        "products": products,
    }
    alerts_output = scraper.build_price_alerts(
        {}, products, generated_at, alert_feed.get("alerts", [])
    )
    health_output = scraper.build_source_health(
        catalog["products"], source_map, products, generated_at
    )

    for name, payload in (
        ("prices.json", output),
        ("price-alerts.json", alerts_output),
        ("source-health.json", health_output),
    ):
        (ROOT / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sanitize",
        action="store_true",
        help="Apply the same fail-closed filters to the checked-in feed before auditing it.",
    )
    args = parser.parse_args()
    if args.sanitize:
        sanitize_existing_feed()

    issues = audit_feed(_load("products.json"), _load("prices.json"), _load("price-alerts.json"))
    if issues:
        print(f"price feed audit failed with {len(issues)} issue(s):")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("price feed audit passed: every displayed price, source, package, best offer, and alert is safe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
