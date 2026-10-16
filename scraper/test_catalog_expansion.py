"""Guards for the 2026-10-16 catalog expansion (ids 400+).

The expansion added products whose only price source is one verified Amazon
ASIN. audit_price_feed.py is an all-or-nothing publish gate, so these tests
prove that such a product can never make it exit nonzero, whatever Amazon
returns, and that the catalog itself keeps the shape the gate and the app
depend on.

Every test here reads only products.json (edited by people, never by the
bots) or synthetic fixtures. They must not read prices.json or
product_sources.json: those are rewritten by every run, and a parser-test
failure aborts the workflow before it can publish.
"""

import copy
import json
import math
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import audit_price_feed
import scraper

ROOT = Path(__file__).resolve().parents[1]
EXPANSION_FIRST_ID = 400
# The price board's category filter (price-board.html PRODUCT_CATEGORY_OPTIONS
# and EQUIPMENT_CATEGORY_OPTIONS). A category outside it never shows up there.
BOARD_CATEGORIES = {
    "pre-emergent", "post-emergent", "pgr", "fungicide", "insecticide",
    "fertilizer", "micronutrient", "macronutrient", "biostimulant",
    "soil-amendment", "moisture-manager", "surfactant",
    "spreader-handheld", "spreader-push", "spreader-tow", "sprayer-backpack",
}


def _catalog() -> dict:
    return json.loads((ROOT / "products.json").read_text(encoding="utf-8"))


def _expansion() -> list[dict]:
    return [p for p in _catalog()["products"] if p["id"] >= EXPANSION_FIRST_ID]


def _listing_title(product: dict) -> str:
    # The last alt name of each expansion product is read off its Amazon
    # listing title, so it is what the Creators API returns.
    return f"{product['alt_names'][-1] if product['alt_names'] else product['name']} listing"


def _amazon_offer(product: dict, price: float, **overrides) -> dict:
    offer = {
        "retailer": "amazon",
        "retailer_name": "Amazon",
        "price": price,
        "url": f"https://www.amazon.com/dp/{product['asin']}?tag=lawndominat0b-20&th=1",
        "in_stock": True,
        "title": _listing_title(product),
        "image": None,
        "last_checked": scraper.now_iso(),
        "source": "amazon_creators_api",
    }
    offer.update(overrides)
    return offer


def _manual_sources(products: list[dict]) -> dict:
    return {
        "products": {
            str(p["id"]): [{
                "url": f"https://www.amazon.com/dp/{p['asin']}",
                "retailer": "amazon",
                "title": _listing_title(p),
                "verified": True,
                "manual_verified": True,
                "source_type": "product",
            }]
            for p in products
            if p.get("asin")
        }
    }


def _corroborated_baseline() -> dict:
    """One ordinary product priced by two independent retailers, so the feed
    under test clears the minimum-priced floor on its own."""
    return {
        "id": 1,
        "slug": "prodiamine-65wdg",
        "name": "Prodiamine 65WDG",
        "category": "pre-emergent",
        "active_ingredient": "prodiamine",
        "alt_names": [],
        "offers": [
            {
                "retailer": retailer,
                "retailer_name": retailer,
                "price": price,
                "url": f"https://{retailer}.example/prodiamine-65wdg-5-lb",
                "title": "Prodiamine 65WDG 5 lb",
                "in_stock": True,
                "last_checked": scraper.now_iso(),
            }
            for retailer, price in (("store-a", 60.0), ("store-b", 64.0))
        ],
        "updated_at": scraper.now_iso(),
    }


def _publish_fast_lane(catalog_products, source_map, fresh_by_id, baseline=()):
    """Run the real fast-lane merge and filters, then the real audit."""
    baseline_by_id = {entry["id"]: copy.deepcopy(entry) for entry in baseline}
    results = []
    for product in catalog_products:
        entry = scraper._merge_fast_lane_product(
            product, baseline_by_id.get(product["id"]), copy.deepcopy(fresh_by_id.get(product["id"]))
        )
        if entry:
            results.append(entry)
    scraper.apply_manual_verified_sources(results, source_map)
    scraper.apply_offer_package_metadata(results)
    scraper.apply_offer_quality_filters(results)
    scraper.sanitize_equipment_results(results)
    generated_at = scraper.now_iso()
    feed = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "product_count": len(results),
        "products": results,
    }
    alerts = scraper.build_price_alerts({}, results, generated_at, [])
    issues = audit_price_feed.audit_feed({"products": catalog_products}, feed, alerts)
    return feed, issues


class ExpansionCatalogShape(unittest.TestCase):
    def test_ids_and_slugs_are_unique_across_the_catalog(self):
        products = _catalog()["products"]
        ids = [p["id"] for p in products]
        slugs = [p["slug"] for p in products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertTrue(all(isinstance(i, int) for i in ids))

    def test_expansion_products_have_every_field_the_scraper_reads(self):
        expansion = _expansion()
        self.assertGreaterEqual(len(expansion), 90)
        for product in expansion:
            with self.subTest(product["slug"]):
                for key in ("slug", "name", "category", "search_query", "amazon_query", "active_ingredient"):
                    self.assertIsInstance(product.get(key), str)
                    self.assertTrue(product[key].strip(), key)
                self.assertIsInstance(product.get("alt_names"), list)
                self.assertRegex(product.get("asin") or "", r"^[A-Z0-9]{10}$")
                self.assertRegex(product["slug"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                self.assertIn(product["category"], BOARD_CATEGORIES)

    def test_expansion_is_chemicals_not_equipment(self):
        # Equipment has its own id-keyed price floors (3xx) and drops package
        # metadata; nothing in this block may inherit those rules.
        for product in _expansion():
            with self.subTest(product["slug"]):
                self.assertFalse(scraper.is_equipment_category(product["category"]))
                self.assertIsNone(scraper.max_price_for_product(product))
                self.assertFalse(scraper.is_known_wrong_product_source(
                    product["id"], f"https://www.amazon.com/dp/{product['asin']}", _listing_title(product)
                ))

    def test_no_amazon_listing_is_shared_by_two_products(self):
        # The audit fails the whole feed when one purchase page is displayed
        # for two products, so one ASIN must belong to exactly one product.
        owners = {}
        for product in _catalog()["products"]:
            asin = product.get("asin")
            if asin:
                self.assertNotIn(asin, owners, f"{asin} on {owners.get(asin)} and {product['slug']}")
                owners[asin] = product["slug"]

    def test_listing_titles_prove_product_identity(self):
        for product in _expansion():
            with self.subTest(product["slug"]):
                url = f"https://www.amazon.com/dp/{product['asin']}"
                self.assertTrue(scraper._matches_product(product, _listing_title(product), url))
                self.assertIsNone(scraper._offer_identity_reason(
                    product, _amazon_offer(product, 30.0)
                ))


class AsinOnlyProductCannotFailTheGate(unittest.TestCase):
    """A product whose only source is its ASIN, under every shape of Amazon
    response, must leave the audit with zero issues."""

    PRODUCT = {
        "id": 498,
        "slug": "test-asin-only",
        "name": "Example Turf Fungicide 2SC",
        "category": "fungicide",
        "search_query": "Example Turf Fungicide 2SC",
        "amazon_query": "Example Turf Fungicide 2SC",
        "active_ingredient": "example",
        "alt_names": ["Example Turf Fungicide 2SC"],
        "asin": "B0TESTASIN",
    }
    DRY = {
        "id": 499,
        "slug": "test-asin-only-wsg",
        "name": "Example Insecticide 40 WSG",
        "category": "insecticide",
        "search_query": "Example Insecticide 40 WSG",
        "amazon_query": "Example Insecticide 40 WSG",
        "active_ingredient": "example",
        "alt_names": ["Example Insecticide 40 WSG"],
        "asin": "B0TESTDRY1",
    }

    def _scenarios(self, product):
        title = _listing_title(product)
        return {
            "normal": _amazon_offer(product, 41.37),
            "one cent": _amazon_offer(product, 0.01),
            "below floor": _amazon_offer(product, 4.99),
            "huge": _amazon_offer(product, 9999.0),
            "no price": _amazon_offer(product, None),
            "out of stock": _amazon_offer(product, 41.37, in_stock=False),
            "unknown stock": _amazon_offer(product, 41.37, in_stock=None),
            "wrong product": _amazon_offer(product, 41.37, title="Garden Hose 50 ft"),
            "lab standard": _amazon_offer(product, 41.37, title=f"{title} analytical standard"),
            "no title": _amazon_offer(product, 41.37, title=""),
            "stale": _amazon_offer(
                product, 41.37,
                last_checked=(datetime.now(timezone.utc) - timedelta(hours=72)).isoformat(),
            ),
            "gallons in title": _amazon_offer(product, 41.37, title=f"{title} makes 100 gallons"),
            "fl oz": _amazon_offer(product, 41.37, title=f"{title} 32 fl oz"),
            "zero size": _amazon_offer(product, 41.37, title=f"{title} 0 lb"),
            "multipack": _amazon_offer(product, 41.37, title=f"{title} 5x5gm packets"),
            "http url": _amazon_offer(product, 41.37, url=f"http://www.amazon.com/dp/{product['asin']}"),
            "search url": _amazon_offer(product, 41.37, url="https://www.amazon.com/s?k=example"),
        }

    def _assert_gate_passes(self, manual_verified):
        catalog = [
            {k: v for k, v in _corroborated_baseline().items() if k in ("id", "slug", "name", "category", "active_ingredient", "alt_names")},
            self.PRODUCT,
            self.DRY,
        ]
        sources = _manual_sources([self.PRODUCT, self.DRY]) if manual_verified else {"products": {}}
        for product in (self.PRODUCT, self.DRY):
            for name, offer in self._scenarios(product).items():
                with self.subTest(product=product["slug"], scenario=name, manual_verified=manual_verified):
                    _, issues = _publish_fast_lane(
                        catalog, sources, {product["id"]: offer}, baseline=[_corroborated_baseline()]
                    )
                    self.assertEqual(issues, [])

    def test_asin_only_without_a_verified_source_never_fails_the_audit(self):
        self._assert_gate_passes(manual_verified=False)

    def test_asin_with_a_manual_verified_source_never_fails_the_audit(self):
        self._assert_gate_passes(manual_verified=True)

    def test_unverified_single_source_is_hidden_and_verified_one_publishes(self):
        catalog = [self.PRODUCT]
        offer = {self.PRODUCT["id"]: _amazon_offer(self.PRODUCT, 41.37)}
        hidden, _ = _publish_fast_lane(catalog, {"products": {}}, offer)
        self.assertIsNone(hidden["products"][0]["best_price"])
        shown, issues = _publish_fast_lane(catalog, _manual_sources(catalog), offer)
        self.assertEqual(issues, [])
        self.assertEqual(shown["products"][0]["best_price"]["price"], 41.37)

    def test_dry_product_read_as_fluid_ounces_is_excluded_not_published(self):
        offer = {self.DRY["id"]: _amazon_offer(self.DRY, 41.37, title=f"{_listing_title(self.DRY)} makes 100 gallons")}
        feed, issues = _publish_fast_lane(
            [_corroborated_baseline(), self.DRY], _manual_sources([self.DRY]), offer,
            baseline=[_corroborated_baseline()],
        )
        self.assertEqual(issues, [])
        published = feed["products"][1]["offers"][0]
        self.assertTrue(published["excluded"])
        self.assertEqual(published["exclude_reason"], scraper.DRY_FLUID_OUNCE_REASON)

    def test_gram_packet_multipack_is_the_total_weight(self):
        product = {"id": 411, "name": "Monument 75WG Herbicide"}
        package = scraper.infer_package_size(
            product, {"title": "Monument 75 WG Selective Herbicide - Box of 25 grams (5x5gm packets)"}
        )
        self.assertEqual((package["package_quantity"], package["package_unit"]), (25.0, "g"))


class RealCatalogFastLane(unittest.TestCase):
    """The shipped catalog through the real run_fast_lane entry point."""

    def _run(self, fresh):
        catalog = _catalog()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scraper").mkdir()
            shutil.copy(ROOT / "products.json", root / "products.json")
            (root / "product_sources.json").write_text(json.dumps(_manual_sources(catalog["products"])))
            (root / "prices.json").write_text(json.dumps({
                "schema_version": "1.0",
                "generated_at": scraper.now_iso(),
                "product_count": 1,
                "products": [_corroborated_baseline()],
            }))
            (root / "price-alerts.json").write_text(json.dumps({"alerts": []}))
            calls = []

            def fake_amazon(product, source_map=None):
                calls.append(product["id"])
                return fresh(product)

            with mock.patch.object(scraper, "__file__", str(root / "scraper" / "scraper.py")), \
                    mock.patch.object(scraper, "amazon_result", fake_amazon), \
                    mock.patch.object(audit_price_feed, "ROOT", root), \
                    mock.patch.object(sys, "argv", ["audit_price_feed.py"]):
                scraper.run_fast_lane()
                exit_code = audit_price_feed.main()
                feed = json.loads((root / "prices.json").read_text())
        return catalog, calls, exit_code, feed

    def test_every_product_is_refreshed_and_the_gate_passes(self):
        def fresh(product):
            if not product.get("asin"):
                return None
            # Distinct prices: the same retailer price on 8+ products is
            # treated as a scrape artefact.
            return _amazon_offer(product, round(15 + product["id"] * 0.37, 2))

        catalog, calls, exit_code, feed = self._run(fresh)
        self.assertEqual(sorted(calls), sorted(p["id"] for p in catalog["products"]))
        self.assertEqual(exit_code, 0)
        priced = {p["id"] for p in feed["products"] if p.get("best_price")}
        self.assertTrue({p["id"] for p in _expansion()} <= priced)

    def test_gate_passes_when_amazon_is_down_for_every_product(self):
        catalog, calls, exit_code, feed = self._run(lambda product: None)
        self.assertEqual(len(calls), len(catalog["products"]))
        self.assertEqual(exit_code, 0)
        # Unpriced new products are left out of the fast-lane feed rather than
        # counted against the minimum-priced floor.
        self.assertEqual([p["id"] for p in feed["products"]], [1])


class SweepRotationCoversTheCatalog(unittest.TestCase):
    def test_a_budget_limited_sweep_reaches_every_product(self):
        # The full sweep is time-budgeted; stalest-first ordering must still
        # reach every product of the larger catalog within ceil(N / budget)
        # runs, never-checked (new) products first.
        products = _catalog()["products"]
        budget = 58
        previous = {}
        clock = datetime(2026, 10, 16, tzinfo=timezone.utc)
        seen = set()
        runs = math.ceil(len(products) / budget)
        for run in range(runs):
            order = scraper.order_products_by_staleness(products, previous)
            batch = order[:budget]
            if run == 0:
                self.assertTrue(all(p["id"] not in previous for p in batch))
            clock += timedelta(hours=3)
            for product in batch:
                previous[product["id"]] = {"id": product["id"], "updated_at": clock.isoformat()}
                seen.add(product["id"])
        self.assertEqual(seen, {p["id"] for p in products})

    def test_rotation_keeps_cycling_after_full_coverage(self):
        products = _catalog()["products"]
        budget = 58
        previous = {}
        clock = datetime(2026, 10, 16, tzinfo=timezone.utc)
        last_seen_run = {}
        runs = 3 * math.ceil(len(products) / budget)
        for run in range(runs):
            batch = scraper.order_products_by_staleness(products, previous)[:budget]
            clock += timedelta(hours=3)
            for product in batch:
                previous[product["id"]] = {"id": product["id"], "updated_at": clock.isoformat()}
                last_seen_run[product["id"]] = run
        # No product waits more than one full cycle to be refreshed again.
        cycle = math.ceil(len(products) / budget)
        self.assertTrue(all(runs - 1 - last <= cycle for last in last_seen_run.values()))
        self.assertEqual(len(last_seen_run), len(products))


if __name__ == "__main__":
    unittest.main()
