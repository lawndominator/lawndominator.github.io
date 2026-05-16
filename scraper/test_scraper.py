import unittest

from bs4 import BeautifulSoup

import scraper


class ScraperExtractionTests(unittest.TestCase):
    def test_append_affiliate_replaces_existing_amazon_tag(self):
        self.assertEqual(
            scraper.append_affiliate("https://www.amazon.com/dp/B0BTN1DPMD?tag=wrong-20&psc=1", "amazon"),
            "https://www.amazon.com/dp/B0BTN1DPMD?psc=1&tag=lawndominator-20",
        )

    def test_parse_price_requires_price_like_text(self):
        self.assertEqual(scraper.parse_price("$79.98"), 79.98)
        self.assertEqual(scraper.parse_price("As low as $81"), 81.0)
        self.assertEqual(scraper.parse_price("Min : 81.99 - Max : 81.99"), 81.99)
        self.assertIsNone(scraper.parse_price("Prodiamine 65 WDG"))

    def test_extracts_card_price_and_joins_relative_url(self):
        soup = BeautifulSoup(
            """
            <div class="product-item">
              <a class="product-item-link" href="/prodiamine-65-wdg-barricade-herbicide">
                Prodiamine 65 WDG
              </a>
              <span class="price">$75.49</span>
            </div>
            """,
            "lxml",
        )

        result = scraper._extract_from_soup(
            soup,
            "https://www.solutionsstores.com",
            "solutions",
            "Solutions Pest & Lawn",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["price"], 75.49)
        self.assertEqual(
            result["url"],
            "https://www.solutionsstores.com/prodiamine-65-wdg-barricade-herbicide",
        )

    def test_extracts_product_jsonld_offer(self):
        soup = BeautifulSoup(
            """
            <script type="application/ld+json">
            {
              "@type": "Product",
              "url": "/prodiamine-65-wdg-generic-barricade-p-2495.html",
              "offers": {
                "@type": "Offer",
                "price": "79.98",
                "availability": "https://schema.org/InStock"
              }
            }
            </script>
            """,
            "lxml",
        )

        result = scraper._extract_from_soup(
            soup,
            "https://www.domyown.com",
            "domyown",
            "DoMyOwn",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["price"], 79.98)
        self.assertEqual(
            result["url"],
            "https://www.domyown.com/prodiamine-65-wdg-generic-barricade-p-2495.html",
        )

    def test_normalizes_google_shopping_offer(self):
        product = {
            "name": "Prodiamine 65WDG",
            "search_query": "Prodiamine 65WDG",
            "alt_names": ["Quali-Pro Prodiamine 65WDG"],
            "active_ingredient": "prodiamine",
        }
        item = {
            "title": "Quali-Pro Prodiamine 65 WDG Herbicide",
            "source": "Example Lawn Supply",
            "extracted_price": 79.98,
            "link": "https://example.com/prodiamine-65-wdg",
            "thumbnail": "https://example.com/prodiamine.webp",
        }

        offer = scraper._shopping_offer(product, item)

        self.assertIsNotNone(offer)
        self.assertEqual(offer["retailer"], "example-lawn-supply")
        self.assertEqual(offer["retailer_name"], "Example Lawn Supply")
        self.assertEqual(offer["price"], 79.98)
        self.assertEqual(offer["source"], "google_shopping")
        self.assertEqual(offer["image"], "https://example.com/prodiamine.webp")

    def test_normalizes_google_shopping_store_offer_with_direct_link(self):
        product = {
            "name": "Prodiamine 65WDG",
            "search_query": "Prodiamine 65WDG",
            "alt_names": [],
            "active_ingredient": "prodiamine",
        }
        item = {
            "title": "Prodiamine 65 WDG",
            "thumbnail": "https://example.com/prodiamine.webp",
        }
        store = {
            "name": "Solutions Pest & Lawn",
            "title": "Prodiamine 65 WDG",
            "extracted_price": 75.49,
            "link": "https://www.solutionsstores.com/prodiamine-65-wdg",
        }

        offer = scraper._shopping_store_offer(product, item, store)

        self.assertIsNotNone(offer)
        self.assertEqual(offer["retailer"], "solutions-pest-lawn")
        self.assertEqual(offer["url"], "https://www.solutionsstores.com/prodiamine-65-wdg")
        self.assertEqual(offer["source"], "google_shopping_store")

    def test_rejects_google_intermediary_store_links(self):
        product = {
            "name": "Prodiamine 65WDG",
            "search_query": "Prodiamine 65WDG",
            "alt_names": [],
            "active_ingredient": "prodiamine",
        }
        store = {
            "name": "Google Store",
            "title": "Prodiamine 65 WDG",
            "extracted_price": 75.49,
            "link": "https://www.google.com/search?ibp=oshop",
        }

        self.assertIsNone(scraper._shopping_store_offer(product, {}, store))

    def test_rejects_unrelated_google_shopping_offer(self):
        product = {
            "name": "Prodiamine 65WDG",
            "search_query": "Prodiamine 65WDG",
            "alt_names": [],
            "active_ingredient": "prodiamine",
        }
        item = {
            "title": "Generic Lawn Sprayer",
            "source": "Example Store",
            "price": "$19.99",
            "link": "https://example.com/sprayer",
        }

        self.assertIsNone(scraper._shopping_offer(product, item))

    def test_best_offer_ignores_google_intermediary_urls(self):
        product = {"id": 1, "category": "post-emergent"}
        offers = [
            {"retailer": "google", "retailer_name": "Google", "price": 12.0, "url": "https://www.google.com/search?ibp=oshop"},
            {"retailer": "merchant", "retailer_name": "Merchant", "price": 19.98, "url": "https://merchant.example/product"},
        ]

        best = scraper.select_best_offer(product, offers)

        self.assertEqual(best["retailer"], "merchant")

    def test_best_offer_ignores_cart_notify_and_out_of_stock_urls(self):
        product = {"id": 1, "category": "soil-amendment"}
        offers = [
            {
                "retailer": "amazon",
                "retailer_name": "Amazon",
                "price": 21.99,
                "url": "https://www.amazon.com/gp/cart/view.html?tag=lawndominator-20",
                "in_stock": True,
            },
            {
                "retailer": "domyown",
                "retailer_name": "DoMyOwn",
                "price": 26.17,
                "url": "https://www.domyown.com/products/26683/notify",
                "in_stock": False,
            },
            {
                "retailer": "merchant",
                "retailer_name": "Merchant",
                "price": 31.0,
                "url": "https://merchant.example/feature-6-0-0",
                "in_stock": True,
            },
            {
                "retailer": "amazon",
                "retailer_name": "Amazon",
                "price": 19.99,
                "url": "https://www.amazon.com/s?k=Celsius+WG",
                "in_stock": True,
            },
        ]

        best = scraper.select_best_offer(product, offers)

        self.assertEqual(best["retailer"], "merchant")

    def test_bad_product_url_rejects_amazon_search(self):
        self.assertTrue(
            scraper.is_bad_product_url(
                "https://www.amazon.com/s?k=Feature+6-0-0+iron+fertilizer+lawn&tag=lawndominator-20"
            )
        )
        self.assertTrue(
            scraper.is_bad_product_url(
                "https://www.ebay.com/sch/i.html?_nkw=Celsius+WG"
            )
        )

    def test_best_offer_allows_out_of_stock_product_page_for_display(self):
        product = {"id": 1, "category": "soil-amendment"}
        offers = [
            {
                "retailer": "domyown",
                "retailer_name": "DoMyOwn",
                "price": 26.17,
                "url": "https://www.domyown.com/feature-water-soluble-micronutrients-p-26683.html",
                "in_stock": False,
            },
            {
                "retailer": "amazon",
                "retailer_name": "Amazon",
                "price": 69.24,
                "url": "https://www.amazon.com/Feature-6-0-0-1-Bag/dp/B076TFPB1Z?tag=lawndominator-20",
                "in_stock": True,
            },
        ]

        best = scraper.select_best_offer(product, offers)

        self.assertEqual(best["retailer"], "domyown")

    def test_extract_uses_product_page_when_offer_link_is_cart(self):
        soup = BeautifulSoup(
            """
            <div class="product">
              <a href="/gp/cart/view.html">Cart</a>
              <span class="price">$42.88</span>
            </div>
            """,
            "lxml",
        )

        result = scraper._extract_from_soup(
            soup,
            "https://www.amazon.com/dp/B0BTN1DPMD",
            "amazon",
            "Amazon",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["url"], "https://www.amazon.com/dp/B0BTN1DPMD?tag=lawndominator-20")

    def test_select_best_ignores_below_category_floor(self):
        product = {"id": 1, "category": "post-emergent"}
        offers = [
            {"retailer": "cheap", "retailer_name": "Cheap", "price": 5.55},
            {"retailer": "real", "retailer_name": "Real", "price": 19.98},
        ]

        best = scraper.select_best_offer(product, offers)

        self.assertEqual(best["retailer"], "real")

    def test_quality_filter_excludes_repeated_flat_prices(self):
        results = []
        for i in range(scraper.REPEATED_PRICE_PRODUCT_LIMIT):
            results.append({
                "id": i,
                "category": "fungicide",
                "offers": [
                    {"retailer": "flat-price-store", "retailer_name": "Flat Price Store", "price": 12.34},
                    {"retailer": "real-store", "retailer_name": "Real Store", "price": 50 + i},
                ],
                "best_price": None,
            })

        scraper.apply_offer_quality_filters(results)

        for product in results:
            flat_offer = product["offers"][0]
            self.assertTrue(flat_offer["excluded"])
            self.assertEqual(product["best_price"]["retailer"], "real-store")

    def test_quality_filter_excludes_cart_and_notify_urls(self):
        results = [{
            "id": 118,
            "name": "Feature 6-0-0 Iron Fertilizer",
            "category": "soil-amendment",
            "offers": [
                {
                    "retailer": "amazon",
                    "retailer_name": "Amazon",
                    "price": 21.99,
                    "url": "https://www.amazon.com/gp/cart/view.html?tag=lawndominator-20",
                    "in_stock": True,
                },
                {
                    "retailer": "domyown",
                    "retailer_name": "DoMyOwn",
                    "price": 26.17,
                    "url": "https://www.domyown.com/products/26683/notify",
                    "in_stock": False,
                },
            ],
            "best_price": None,
        }]

        scraper.apply_offer_quality_filters(results)

        self.assertTrue(results[0]["offers"][0]["excluded"])
        self.assertTrue(results[0]["offers"][1]["excluded"])
        self.assertIsNone(results[0]["best_price"])

    def test_preserves_last_good_product_when_current_run_has_no_valid_best(self):
        current = [{
            "id": 118,
            "slug": "feature-6-0-0",
            "name": "Feature 6-0-0 Iron Fertilizer",
            "category": "soil-amendment",
            "offers": [
                {
                    "retailer": "amazon",
                    "retailer_name": "Amazon",
                    "price": 21.99,
                    "url": "https://www.amazon.com/gp/cart/view.html?tag=lawndominator-20",
                    "in_stock": True,
                    "excluded": True,
                },
            ],
            "best_price": None,
        }]
        previous = {
            118: {
                "id": 118,
                "slug": "feature-6-0-0",
                "name": "Feature 6-0-0 Iron Fertilizer",
                "category": "soil-amendment",
                "offers": [
                    {
                        "retailer": "domyown",
                        "retailer_name": "DoMyOwn",
                        "price": 26.17,
                        "url": "https://www.domyown.com/feature-water-soluble-micronutrients-p-26683.html",
                        "in_stock": True,
                    },
                ],
                "best_price": {
                    "retailer": "domyown",
                    "retailer_name": "DoMyOwn",
                    "price": 26.17,
                    "url": "https://www.domyown.com/feature-water-soluble-micronutrients-p-26683.html",
                    "in_stock": True,
                },
            }
        }

        preserved = scraper.preserve_last_good_products(current, previous)

        self.assertTrue(preserved[0]["stale"])
        self.assertEqual(preserved[0]["best_price"]["retailer"], "domyown")

    def test_update_product_sources_saves_only_real_merchant_urls(self):
        source_map = {"schema_version": "1.0", "products": {}}
        results = [{
            "id": 1,
            "name": "Prodiamine 65WDG",
            "offers": [
                {
                    "retailer": "google",
                    "retailer_name": "Google",
                    "price": 12.0,
                    "url": "https://www.google.com/search?ibp=oshop",
                },
                {
                    "retailer": "merchant",
                    "retailer_name": "Merchant",
                    "price": 75.49,
                    "url": "https://merchant.example/prodiamine#reviews",
                    "title": "Prodiamine 65 WDG",
                    "image": "https://merchant.example/prodiamine.webp",
                },
            ],
        }]

        updated = scraper.update_product_sources(source_map, results)

        self.assertEqual(len(updated["products"]["1"]), 1)
        self.assertEqual(updated["products"]["1"][0]["url"], "https://merchant.example/prodiamine")
        self.assertEqual(updated["products"]["1"][0]["retailer_name"], "Merchant")

    def test_verified_source_becomes_priced_offer(self):
        offer = scraper._offer_from_verified_source({
            "url": "https://www.amazon.com/dp/B0BTKTVN76",
            "retailer": "amazon",
            "retailer_name": "Amazon",
            "title": "Celsius WG",
            "price_verified": 13.79,
            "last_seen": "2026-05-16T01:52:11+00:00",
        })

        self.assertIsNotNone(offer)
        self.assertEqual(offer["price"], 13.79)
        self.assertEqual(offer["source"], "manual_verified_source")
        self.assertEqual(offer["url"], "https://www.amazon.com/dp/B0BTKTVN76?tag=lawndominator-20")

    def test_verified_source_rejects_unpriced_amazon_search(self):
        offer = scraper._offer_from_verified_source({
            "url": "https://www.amazon.com/s?k=Celsius+WG&tag=lawndominator-20",
            "retailer": "amazon",
            "retailer_name": "Amazon",
            "price_verified": None,
        })

        self.assertIsNone(offer)

    def test_build_price_alerts_detects_best_price_drop(self):
        previous = {
            1: {
                "id": 1,
                "slug": "prodiamine-65wdg",
                "name": "Prodiamine 65WDG",
                "best_price": {
                    "retailer": "old-store",
                    "retailer_name": "Old Store",
                    "price": 100.0,
                    "url": "https://old.example/product",
                    "in_stock": True,
                },
            }
        }
        current = [{
            "id": 1,
            "slug": "prodiamine-65wdg",
            "name": "Prodiamine 65WDG",
            "category": "pre-emergent",
            "best_price": {
                "retailer": "new-store",
                "retailer_name": "New Store",
                "price": 89.0,
                "url": "https://new.example/product",
                "in_stock": True,
            },
        }]

        output = scraper.build_price_alerts(previous, current, "2026-05-14T16:00:00+00:00")

        self.assertEqual(output["alert_count"], 2)
        alert_types = {alert["type"] for alert in output["alerts"]}
        self.assertEqual(alert_types, {"major_price_drop", "new_lowest_retailer"})
        drop_alert = next(alert for alert in output["alerts"] if alert["type"] == "major_price_drop")
        self.assertEqual(drop_alert["product_slug"], "prodiamine-65wdg")
        self.assertEqual(drop_alert["old_price"], 100.0)
        self.assertEqual(drop_alert["new_price"], 89.0)
        self.assertEqual(drop_alert["drop_percent"], 11.0)

    def test_build_price_alerts_ignores_small_drop(self):
        previous = {
            1: {
                "id": 1,
                "slug": "prodiamine-65wdg",
                "name": "Prodiamine 65WDG",
                "best_price": {"retailer": "store", "retailer_name": "Store", "price": 100.0},
            }
        }
        current = [{
            "id": 1,
            "slug": "prodiamine-65wdg",
            "name": "Prodiamine 65WDG",
            "category": "pre-emergent",
            "best_price": {"retailer": "store", "retailer_name": "Store", "price": 96.0},
        }]

        output = scraper.build_price_alerts(previous, current, "2026-05-14T16:00:00+00:00")

        self.assertEqual(output["alert_count"], 0)

    def test_build_price_alerts_ignores_out_of_stock_drop(self):
        previous = {
            1: {
                "id": 1,
                "slug": "feature-6-0-0",
                "name": "Feature 6-0-0 Iron Fertilizer",
                "best_price": {"retailer": "store", "retailer_name": "Store", "price": 100.0},
            }
        }
        current = [{
            "id": 1,
            "slug": "feature-6-0-0",
            "name": "Feature 6-0-0 Iron Fertilizer",
            "category": "soil-amendment",
            "best_price": {
                "retailer": "store",
                "retailer_name": "Store",
                "price": 50.0,
                "in_stock": False,
            },
        }]

        output = scraper.build_price_alerts(previous, current, "2026-05-14T16:00:00+00:00")

        self.assertEqual(output["alert_count"], 0)

    def test_build_price_alerts_detects_back_in_stock(self):
        previous = {
            1: {
                "id": 1,
                "slug": "prodiamine-65wdg",
                "name": "Prodiamine 65WDG",
                "best_price": {
                    "retailer": "store",
                    "retailer_name": "Store",
                    "price": 100.0,
                    "in_stock": False,
                },
            }
        }
        current = [{
            "id": 1,
            "slug": "prodiamine-65wdg",
            "name": "Prodiamine 65WDG",
            "category": "pre-emergent",
            "best_price": {
                "retailer": "store",
                "retailer_name": "Store",
                "price": 100.0,
                "url": "https://store.example/product",
                "in_stock": True,
            },
        }]

        output = scraper.build_price_alerts(previous, current, "2026-05-14T16:00:00+00:00")

        self.assertEqual(output["alert_count"], 1)
        self.assertEqual(output["alerts"][0]["type"], "back_in_stock")


if __name__ == "__main__":
    unittest.main()
