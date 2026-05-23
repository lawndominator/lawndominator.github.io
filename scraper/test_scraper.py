import unittest

from bs4 import BeautifulSoup

import scraper


class ScraperExtractionTests(unittest.TestCase):
    def test_append_affiliate_replaces_existing_amazon_tag(self):
        self.assertEqual(
            scraper.append_affiliate("https://www.amazon.com/dp/B0BTN1DPMD?tag=wrong-20&psc=1", "amazon"),
            "https://www.amazon.com/dp/B0BTN1DPMD?tag=lawndominator-20",
        )

    def test_canonical_product_url_normalizes_amazon_refs(self):
        self.assertEqual(
            scraper.canonical_product_url(
                "https://www.amazon.com/Feature-6-0-0-1-Bag/dp/B076TFPB1Z/ref=sr_1_1?sr=8-1&tag=wrong"
            ),
            "https://www.amazon.com/dp/B076TFPB1Z",
        )

    def test_amazon_asin_from_url(self):
        self.assertEqual(
            scraper.amazon_asin_from_url("https://www.amazon.com/gp/product/B076TFPB1Z?psc=1"),
            "B076TFPB1Z",
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
              "image": "https://www.domyown.com/images/prodiamine.jpg",
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
        self.assertEqual(result["image"], "https://www.domyown.com/images/prodiamine.jpg")

    def test_page_out_of_stock_overrides_jsonld_availability(self):
        soup = BeautifulSoup(
            """
            <script type="application/ld+json">
            {
              "@type": "Product",
              "name": "Certainty Turf Herbicide",
              "offers": {
                "@type": "Offer",
                "price": "105.95",
                "availability": "https://schema.org/InStock",
                "url": "https://pestrong.com/product/certainty-turf-herbicide-1-25-oz"
              }
            }
            </script>
            <main><h1>Certainty Turf Herbicide</h1><button>Sold Out</button></main>
            """,
            "lxml",
        )

        result = scraper._extract_from_soup(
            soup,
            "https://pestrong.com/product/certainty-turf-herbicide-1-25-oz",
            "pestrong",
            "Pestrong",
        )

        self.assertEqual(result["price"], 105.95)
        self.assertFalse(result["in_stock"])

    def test_extracts_meta_product_image(self):
        soup = BeautifulSoup(
            """
            <meta property="og:image" content="/images/prodiamine.jpg" />
            <div class="product-item">
              <a class="product-item-link" href="/prodiamine-65-wdg">Prodiamine 65 WDG</a>
              <span class="price">$79.98</span>
            </div>
            """,
            "lxml",
        )

        result = scraper._extract_from_soup(
            soup,
            "https://example.com/products/prodiamine-65-wdg",
            "example",
            "Example",
        )

        self.assertEqual(result["image"], "https://example.com/images/prodiamine.jpg")

    def test_rejects_placeholder_product_image(self):
        soup = BeautifulSoup(
            """
            <meta property="og:image" content="/media/catalog/product/placeholder/default/missing-image-base.png" />
            <div class="product-item">
              <a class="product-item-link" href="/prodiamine-65-wdg">Prodiamine 65 WDG</a>
              <span class="price">$79.98</span>
            </div>
            """,
            "lxml",
        )

        result = scraper._extract_from_soup(
            soup,
            "https://example.com/products/prodiamine-65-wdg",
            "example",
            "Example",
        )

        self.assertIsNone(result["image"])

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

    def test_best_offer_ignores_out_of_stock_product_page(self):
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

        self.assertEqual(best["retailer"], "amazon")

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

    def test_infers_dry_package_size_from_offer_url(self):
        package = scraper.infer_package_size({}, {
            "url": "https://seedbarn.com/products/pendulum-2g-herbicide-40-lbs",
            "price": 115.95,
        })

        self.assertEqual(package["package_label"], "40 lb")
        self.assertEqual(package["package_unit"], "lb")

    def test_infers_liquid_package_size_from_offer_title(self):
        package = scraper.infer_package_size({}, {
            "title": "Dimension 2EW Herbicide - 0.5 Half Gallon (64 ounces)",
            "price": 142.58,
        })

        self.assertEqual(package["package_label"], "64 fl oz")
        self.assertEqual(package["package_quantity"], 64.0)

    def test_infers_decimal_gallon_package_size(self):
        package = scraper.infer_package_size({}, {
            "title": "Dimension 2EW Dithiopyr 2.5 Gallon Size",
            "price": 509.95,
        })

        self.assertEqual(package["package_label"], "2.5 gal")
        self.assertEqual(package["package_quantity"], 320.0)

    def test_infers_single_gallon_package_size_without_number(self):
        package = scraper.infer_package_size({}, {
            "url": "https://store.example/products/specticle-flo-herbicide-gallon",
            "price": 2151.50,
        })

        self.assertEqual(package["package_label"], "1 gal")
        self.assertEqual(package["package_quantity"], 128.0)

    def test_manual_prodiamine_pages_are_five_pounds(self):
        package = scraper.infer_package_size(
            {"id": 1},
            {
                "retailer": "solutions",
                "title": "Prodiamine 65WDG",
                "url": "https://www.solutionsstores.com/prodiamine-65-wdg-barricade-herbicide",
            },
        )

        self.assertEqual(package["package_label"], "5 lb")
        self.assertEqual(package["package_quantity"], 5.0)

    def test_manual_prodiamine_sku_page_is_five_pounds(self):
        package = scraper.infer_package_size(
            {"id": 1},
            {
                "retailer": "pestmanagementsupply",
                "title": "",
                "url": "https://www.pestmanagementsupply.com/csi83013356.html",
            },
        )

        self.assertEqual(package["package_label"], "5 lb")

    def test_known_wrong_dimension_sources_are_rejected(self):
        self.assertTrue(
            scraper.is_known_wrong_product_source(
                2,
                "https://sodsolutions.com/shop/weed-control/pre-emergent-weed-control/crabgrass-control-plus-0-0-7-with-0-37-prodiamine-herbicide",
                "(4 Reviews)",
            )
        )
        self.assertTrue(
            scraper.is_known_wrong_product_source(
                2,
                "https://www.seedworldusa.com/products/alyce-clover-seed",
                "Alyce Clover",
            )
        )

    def test_alyce_clover_source_is_globally_rejected(self):
        self.assertTrue(
            scraper.is_known_wrong_product_source(
                8,
                "https://www.seedworldusa.com/products/alyce-clover-seed",
                "Alyce Clover",
            )
        )

    def test_manual_dimension_urls_are_sized(self):
        one_gal = scraper.infer_package_size(
            {"id": 2},
            {
                "retailer": "chemicalwarehouse",
                "url": "https://chemicalwarehouse.com/products/dithiopyr-2l?variant=39630369128511",
            },
        )
        two_half_gal = scraper.infer_package_size(
            {"id": 2},
            {
                "retailer": "chemicalwarehouse",
                "url": "https://chemicalwarehouse.com/products/dithiopyr-2-ew?variant=41276310028351",
            },
        )
        half_gal = scraper.infer_package_size(
            {"id": 2},
            {
                "retailer": "domyown",
                "url": "https://www.domyown.com/dimension-2ew-herbicide-p-1494.html",
            },
        )

        self.assertEqual(one_gal["package_label"], "1 gal")
        self.assertEqual(two_half_gal["package_label"], "2.5 gal")
        self.assertEqual(half_gal["package_label"], "64 fl oz")

    def test_manual_granular_pre_emergent_sizes_are_sized(self):
        cases = [
            (3, "domyown", "Ronstar G (Oxadiazon 2G)", "https://www.domyown.com/ronstar-herbicide-p-1496.html", "50 lb"),
            (5, "domyown", "Pendulum 2G", "https://www.domyown.com/pendulum-2g-granular-herbicide-p-1498.html", "40 lb"),
            (6, "amazon", "Gallery 75 DF Specialty Herbicide", "https://www.amazon.com/dp/B004JX6QO8", "1 lb"),
            (7, "domyown", "Specticle G (Indaziflam)", "https://www.domyown.com/specticle-herbicide-p-4519.html", "50 lb"),
        ]

        for product_id, retailer, title, url, expected in cases:
            with self.subTest(product_id=product_id, retailer=retailer):
                package = scraper.infer_package_size(
                    {"id": product_id},
                    {"retailer": retailer, "title": title, "url": url},
                )
                self.assertEqual(package["package_label"], expected)

    def test_manual_post_emergent_sizes_are_sized(self):
        cases = [
            (15, "lawnsynergy", "Celsius WG Herbicide", "https://lawnsynergy.com/products/celsius-wg-herbicide", 14.86, "0.226 fl oz"),
            (17, "golfcourselawn", "Drive XLR8 Herbicide", "https://golfcourselawn.store/products/drive-xlr8-herbicide-crabgrass-weed-killer", 84.99, "64 fl oz"),
            (20, "amazon", "0 Cart", "https://www.amazon.com/dp/B0CB96F141", 37.70, "8 fl oz"),
            (21, "domyown", "Tenacity Turf Herbicide", "https://www.domyown.com/tenacity-herbicide-p-1877.html", 66.64, "8 fl oz"),
            (23, "domyown", "Sulfentrazone 4L Select", "https://www.domyown.com/sulfentrazone-4l-select-p-17100.html", 60.48, "6 fl oz"),
            (24, "domyown", "Pylex Herbicide", "https://www.domyown.com/pylex-herbicide-oz-p-23029.html", 416.00, "4 fl oz"),
            (29, "domyown", "Katana Turf Herbicide", "https://www.domyown.com/katana-turf-herbicide-p-10316.html", 300.89, "5 fl oz"),
        ]

        for product_id, retailer, title, url, price, expected in cases:
            with self.subTest(product_id=product_id, retailer=retailer):
                package = scraper.infer_package_size(
                    {"id": product_id},
                    {"retailer": retailer, "title": title, "url": url, "price": price},
                )
                self.assertEqual(package["package_label"], expected)

    def test_manual_pgr_sizes_are_sized(self):
        cases = [
            (35, "chemicalwarehouse", "Primo Maxx", "https://chemicalwarehouse.com/products/primo-maxx", 32.00, "4 fl oz"),
            (36, "sunspot-supply", "T-Nex Plant Growth Regulator", "https://www.sunspotsupply.com/products/t-nex-plant-growth-regulator-2-5-gallons", 362.00, "2.5 gal"),
            (37, "sunspot-supply", "Anuew EZ", "https://www.sunspotsupply.com/products/anuew-ez-plant-growth-regulator-for-turf-25", 813.96, "2.5 gal"),
        ]

        for product_id, retailer, title, url, price, expected in cases:
            with self.subTest(product_id=product_id, retailer=retailer):
                package = scraper.infer_package_size(
                    {"id": product_id},
                    {"retailer": retailer, "title": title, "url": url, "price": price},
                )
                self.assertEqual(package["package_label"], expected)

    def test_known_wrong_non_product_pages_are_rejected(self):
        self.assertTrue(scraper.is_known_wrong_product_source(9, "https://arborchem.com/topic/privacy", "Privacy Policy"))
        self.assertTrue(scraper.is_known_wrong_product_source(17, "https://www.forestrydistributing.com/register", "Register"))
        self.assertTrue(scraper.is_known_wrong_product_source(25, "https://www.ourprosolutions.com/product/gallery-75-df-specialty-herbicide-isoxaben-75", "Gallery 75 DF Specialty Herbicide Isoxaben 75% $ 159.49"))

    def test_known_wrong_cross_product_sources_are_rejected(self):
        self.assertTrue(
            scraper.is_known_wrong_product_source(
                2,
                "https://sodsolutions.com/shop/weed-control/speedzone-broadleaf-herbicide-for-turf",
                "(2 Reviews)",
            )
        )
        self.assertTrue(
            scraper.is_known_wrong_product_source(
                59,
                "https://lawnsynergy.com/products/headway-g-fungicide",
                "It's Time To Apply Fungicide",
            )
        )
        self.assertTrue(
            scraper.is_known_wrong_product_source(
                116,
                "https://yardmastery.com/products/hydr8-liquicuretm-soil-surfactant-wetting-agent",
                "Hydr8 Liquicure",
            )
        )
        self.assertTrue(
            scraper.is_known_wrong_product_source(
                81,
                "https://www.domyown.com/bayer-kontos-insecticide-p-21398.html",
                "Kontos SC",
            )
        )
        self.assertTrue(
            scraper.is_known_wrong_product_source(
                23,
                "https://www.ourprosolutions.com/product/basagran-t-o-herbicide-1-gallon",
                "Basagran T/O Herbicide. 1 Gallon $ 98.99",
            )
        )
        self.assertTrue(
            scraper.is_known_wrong_product_source(
                71,
                "https://gciturfacademy.com/products/acelepryn-sc-insecticide",
                "Acelepryn SC Insecticide",
            )
        )
        self.assertTrue(
            scraper.is_known_wrong_product_source(
                138,
                "https://www.amazon.com/dp/B07KXZHMK1",
                "The Andersons Humic DG Organic Soil Amendment",
            )
        )
        self.assertTrue(
            scraper.is_known_wrong_product_source(
                16,
                "https://diypestcontrol.com/empero-selective-herbicide",
                "Empero Selective Herbicide",
            )
        )

    def test_manual_remaining_product_sizes_are_sized(self):
        cases = [
            (8, "domyown", "Hi-Yield Atrazine Weed Killer", "https://www.domyown.com/hiyield-atrazine-weed-killer-p-2023.html", 24.48, "32 fl oz"),
            (16, "solutions", "Certainty WDG (Sulfosulfuron)", "https://www.solutionsstores.com/certainty-turf-herbicide", 110.77, "1.25 fl oz"),
            (18, "amazon", "Sedgehammer Plus Turf Herbicide - 1 Pack of 13.5 Gram", "https://www.amazon.com/dp/B007PHMAYK", 13.99, "13.5 g"),
            (27, "pestrong", "Trimec Classic Broadleaf Herbicide", "https://pestrong.com/product/trimec-classic-broadleaf-herbicide-2-5", 204.95, "2.5 gal"),
            (52, "lawn-synergy", "Headway G Granular Fungicide", "https://lawnsynergy.com/products/headway-g-fungicide", 79.99, "30 lb"),
            (58, "pestrong", "Emerald Fungicide", "https://pestrong.com/product/emerald-fungicide-for-golf-course-0-49-lbs", 159.95, "0.49 lb"),
            (71, "domyown", "Acelepryn G Insecticide", "https://www.domyown.com/acelepryn-insecticide-p-15739.html", 125.0, "25 lb"),
            (79, "sunspot-supply", "Zylam Liquid Systemic Insecticide", "https://www.sunspotsupply.com/products/zylam-liquid-insecticide-quart", 149.75, "32 fl oz"),
            (116, "domyown", "Revolution Soil Surfactant", "https://www.domyown.com/aquatrols-revolution-soil-surfactant-p-10332.html", 457.50, "2.5 gal"),
            (118, "amazon", "Feature, 1 Bag", "https://www.amazon.com/dp/B076TFPB1Z", 30.00, "2.5 lb"),
        ]

        for product_id, retailer, title, url, price, expected in cases:
            with self.subTest(product_id=product_id, retailer=retailer):
                package = scraper.infer_package_size(
                    {"id": product_id},
                    {"retailer": retailer, "title": title, "url": url, "price": price},
                )
                self.assertEqual(package["package_label"], expected)

    def test_apply_offer_package_metadata_adds_price_per_unit(self):
        results = [{
            "id": 5,
            "offers": [{
                "title": "Pendulum 2G Herbicide - 20 Lbs.",
                "price": 75.75,
                "url": "https://store.example/pendulum-2g-20-lbs",
            }],
        }]

        scraper.apply_offer_package_metadata(results)

        offer = results[0]["offers"][0]
        self.assertEqual(offer["package_label"], "20 lb")
        self.assertEqual(offer["price_per_unit"], 3.79)

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

    def test_update_product_sources_drops_existing_search_urls(self):
        source_map = {
            "schema_version": "1.0",
            "products": {
                "1": [{
                    "url": "https://www.amazon.com/s?k=Prodiamine+65WDG&tag=lawndominator-20",
                    "retailer": "amazon",
                    "retailer_name": "Amazon",
                }]
            },
        }
        results = [{"id": 1, "name": "Prodiamine 65WDG", "offers": []}]

        updated = scraper.update_product_sources(source_map, results)

        self.assertEqual(updated["products"]["1"], [])

    def test_update_product_sources_dedupes_amazon_affiliate_variants(self):
        source_map = {
            "schema_version": "1.0",
            "products": {
                "118": [{
                    "url": "https://www.amazon.com/Feature-6-0-0-1-Bag/dp/B076TFPB1Z",
                    "retailer": "amazon",
                    "retailer_name": "Amazon",
                    "price_verified": 13.74,
                }]
            },
        }
        results = [{
            "id": 118,
            "name": "Feature 6-0-0",
            "offers": [{
                "retailer": "amazon",
                "retailer_name": "Amazon",
                "price": 13.74,
                "url": "https://www.amazon.com/dp/B076TFPB1Z?tag=lawndominator-20",
            }],
        }]

        updated = scraper.update_product_sources(source_map, results)

        self.assertEqual(len(updated["products"]["118"]), 1)
        self.assertEqual(updated["products"]["118"][0]["url"], "https://www.amazon.com/dp/B076TFPB1Z")
        self.assertNotIn("price_verified", updated["products"]["118"][0])

    def test_verified_source_becomes_priced_offer(self):
        offer = scraper._offer_from_verified_source({
            "url": "https://store.example/celsius-wg",
            "retailer": "example-store",
            "retailer_name": "Example Store",
            "title": "Celsius WG",
            "price_verified": 13.79,
            "last_seen": "2026-05-16T01:52:11+00:00",
        })

        self.assertIsNotNone(offer)
        self.assertEqual(offer["price"], 13.79)
        self.assertEqual(offer["source"], "manual_verified_source")
        self.assertEqual(offer["url"], "https://store.example/celsius-wg")

    def test_verified_source_drops_placeholder_image(self):
        offer = scraper._offer_from_verified_source({
            "url": "https://store.example/celsius-wg",
            "retailer": "example-store",
            "retailer_name": "Example Store",
            "title": "Celsius WG",
            "price_verified": 13.79,
            "image": "https://store.example/placeholder/default/missing-image-base.png",
        })

        self.assertIsNone(offer["image"])

    def test_verified_source_does_not_use_stored_amazon_price(self):
        offer = scraper._offer_from_verified_source({
            "url": "https://www.amazon.com/dp/B076TFPB1Z",
            "retailer": "amazon",
            "retailer_name": "Amazon",
            "title": "Feature 6-0-0",
            "price_verified": 13.74,
        })

        self.assertIsNone(offer)

    def test_build_source_health_reports_source_statuses(self):
        previous_limit = scraper.SAVED_SOURCE_LIMIT
        scraper.SAVED_SOURCE_LIMIT = 1
        try:
            catalog = [{
                "id": 1,
                "slug": "prodiamine-65wdg",
                "name": "Prodiamine 65WDG",
                "category": "pre-emergent",
            }]
            source_map = {
                "products": {
                    "1": [
                        {
                            "url": "https://merchant.example/prodiamine",
                            "retailer": "merchant",
                            "retailer_name": "Merchant",
                            "manual_verified": True,
                        },
                        {
                            "url": "https://other.example/prodiamine",
                            "retailer": "other",
                            "retailer_name": "Other",
                        },
                    ]
                }
            }
            results = [{
                "id": 1,
                "offers": [{
                    "url": "https://merchant.example/prodiamine",
                    "retailer": "merchant",
                    "retailer_name": "Merchant",
                    "price": 64.99,
                }],
            }]

            health = scraper.build_source_health(catalog, source_map, results, "2026-05-21T00:00:00+00:00")

            self.assertEqual(health["totals"]["sources"], 2)
            self.assertEqual(health["totals"]["included_sources"], 1)
            self.assertEqual(health["totals"]["not_included_sources"], 1)
            self.assertEqual(health["reason_counts"]["included"], 1)
            self.assertEqual(health["reason_counts"]["not_checked_saved_source_limit"], 1)
        finally:
            scraper.SAVED_SOURCE_LIMIT = previous_limit

    def test_keepa_current_price_uses_lowest_current_offer(self):
        product = {"stats": {"current": [3099, 3299, -1, -1, -1, -1, -1, -1, -1, -1, 3199]}}

        self.assertEqual(scraper._keepa_current_price(product), 30.99)

    def test_keepa_image_url_uses_first_image_filename(self):
        product = {"imagesCSV": "81abc123.jpg,71def456.jpg"}

        self.assertEqual(
            scraper._keepa_image_url(product),
            "https://m.media-amazon.com/images/I/81abc123.jpg",
        )

    def test_keepa_image_url_allows_absolute_url(self):
        product = {"imagesCSV": "https://example.com/product.jpg"}

        self.assertEqual(scraper._keepa_image_url(product), "https://example.com/product.jpg")

    def test_keepa_image_url_uses_new_images_field(self):
        product = {"images": [{"l": "91large.jpg", "m": "81medium.jpg"}]}

        self.assertEqual(
            scraper._keepa_image_url(product),
            "https://m.media-amazon.com/images/I/91large.jpg",
        )

    def test_verified_source_rejects_unpriced_amazon_search(self):
        offer = scraper._offer_from_verified_source({
            "url": "https://www.amazon.com/s?k=Celsius+WG&tag=lawndominator-20",
            "retailer": "amazon",
            "retailer_name": "Amazon",
            "price_verified": None,
        })

        self.assertIsNone(offer)

    def test_source_entries_always_include_priced_sources(self):
        previous_limit = scraper.SAVED_SOURCE_LIMIT
        scraper.SAVED_SOURCE_LIMIT = 2
        try:
            source_map = {
                "products": {
                    "118": [
                        {"url": "https://store.example/one", "source_type": "product"},
                        {"url": "https://store.example/two", "source_type": "product"},
                        {
                            "url": "https://www.amazon.com/dp/B076TFPB1Z",
                            "retailer": "amazon",
                            "price_verified": 13.74,
                            "source_type": "product",
                        },
                    ]
                }
            }

            entries = scraper._source_entries(source_map, 118)

            self.assertEqual(len(entries), 2)
            self.assertTrue(any(entry.get("retailer") == "amazon" for entry in entries))
        finally:
            scraper.SAVED_SOURCE_LIMIT = previous_limit

    def test_source_entries_prioritizes_manual_verified_sources(self):
        previous_limit = scraper.SAVED_SOURCE_LIMIT
        scraper.SAVED_SOURCE_LIMIT = 2
        try:
            source_map = {
                "products": {
                    "15": [
                        {
                            "url": "https://manual-one.example/celsius",
                            "manual_verified": True,
                            "source_type": "product",
                        },
                        {
                            "url": "https://manual-two.example/celsius",
                            "manual_verified": True,
                            "source_type": "product",
                        },
                        {
                            "url": "https://auto.example/celsius",
                            "source_type": "product",
                        },
                    ]
                }
            }

            entries = scraper._source_entries(source_map, 15)

            self.assertEqual(len(entries), 2)
            self.assertTrue(all(entry.get("manual_verified") for entry in entries))
        finally:
            scraper.SAVED_SOURCE_LIMIT = previous_limit

    def test_scrape_saved_sources_uses_verified_price_when_fetch_fails(self):
        previous_fetch = scraper.fetch_saved_source
        scraper.fetch_saved_source = lambda url: None
        try:
            offers = scraper.scrape_saved_sources(
                {"id": 15, "name": "Celsius WG"},
                {
                    "products": {
                        "15": [{
                            "url": "https://store.example/celsius-wg",
                            "retailer": "example-store",
                            "retailer_name": "Example Store",
                            "title": "Celsius WG",
                            "price_verified": 13.79,
                            "in_stock": True,
                            "manual_verified": True,
                            "package_quantity": 10.0,
                            "package_unit": "oz",
                            "package_label": "10 oz",
                        }]
                    }
                },
            )

            self.assertEqual(len(offers), 1)
            self.assertEqual(offers[0]["source"], "manual_verified_source")
            self.assertEqual(offers[0]["price"], 13.79)
            self.assertEqual(offers[0]["package_label"], "10 oz")
        finally:
            scraper.fetch_saved_source = previous_fetch

    def test_scrape_saved_sources_falls_back_when_manual_extracts_wrong_url(self):
        previous_fetch = scraper.fetch_saved_source
        scraper.fetch_saved_source = lambda url: """
            <div class="product">
              <a href="https://store.example/products/not-the-product">Wrong Product</a>
              <span class="price">$1.25</span>
            </div>
        """
        try:
            offers = scraper.scrape_saved_sources(
                {"id": 15, "name": "Celsius WG"},
                {
                    "products": {
                        "15": [{
                            "url": "https://store.example/products/celsius-wg",
                            "retailer": "example-store",
                            "retailer_name": "Example Store",
                            "title": "Celsius WG",
                            "price_verified": 22.99,
                            "manual_verified": True,
                        }]
                    }
                },
            )

            self.assertEqual(len(offers), 1)
            self.assertEqual(offers[0]["source"], "manual_verified_source")
            self.assertEqual(offers[0]["price"], 22.99)
            self.assertEqual(offers[0]["url"], "https://store.example/products/celsius-wg")
        finally:
            scraper.fetch_saved_source = previous_fetch

    def test_scrape_saved_sources_normalizes_variant_url_to_saved_source(self):
        previous_fetch = scraper.fetch_saved_source
        scraper.fetch_saved_source = lambda url: """
            <script type="application/ld+json">
            {
              "@type": "Product",
              "name": "Celsius WG",
              "offers": {
                "@type": "Offer",
                "price": "22.99",
                "url": "https://store.example/products/celsius-wg?variant=123"
              }
            }
            </script>
        """
        try:
            offers = scraper.scrape_saved_sources(
                {"id": 15, "name": "Celsius WG"},
                {
                    "products": {
                        "15": [{
                            "url": "https://store.example/products/celsius-wg",
                            "retailer": "example-store",
                            "retailer_name": "Example Store",
                            "title": "Celsius WG",
                            "manual_verified": True,
                        }]
                    }
                },
            )

            self.assertEqual(len(offers), 1)
            self.assertEqual(offers[0]["source"], "saved_product_source")
            self.assertEqual(offers[0]["url"], "https://store.example/products/celsius-wg")
        finally:
            scraper.fetch_saved_source = previous_fetch

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

    def test_build_price_alerts_retains_recent_previous_alerts(self):
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
            "best_price": {"retailer": "store", "retailer_name": "Store", "price": 100.0},
        }]
        previous_alerts = [{
            "id": "old-but-recent",
            "type": "best_price_drop",
            "product_id": 2,
            "product_slug": "dimension-2ew",
            "created_at": "2026-05-13T16:00:00+00:00",
        }]

        output = scraper.build_price_alerts(
            previous,
            current,
            "2026-05-14T16:00:00+00:00",
            previous_alerts,
        )

        self.assertEqual(output["current_alert_count"], 0)
        self.assertEqual(output["alert_count"], 1)
        self.assertEqual(output["alerts"][0]["id"], "old-but-recent")

    def test_build_price_alerts_prunes_expired_previous_alerts(self):
        previous_alerts = [{
            "id": "expired",
            "type": "best_price_drop",
            "product_id": 2,
            "product_slug": "dimension-2ew",
            "created_at": "2026-05-01T16:00:00+00:00",
        }]

        output = scraper.build_price_alerts(
            {},
            [],
            "2026-05-14T16:00:00+00:00",
            previous_alerts,
        )

        self.assertEqual(output["alert_count"], 0)
        self.assertEqual(output["alerts"], [])


if __name__ == "__main__":
    unittest.main()
