"""Per-product price ceiling.

Specticle FLO's offer list carries both the 18 fl oz bottle the catalog means
and a 128 fl oz gallon. On unit price the gallon wins ($17.56/oz against
$18.89/oz), so the live feed published $2,247.32 as the best price of an 18 oz
bottle. Nobody using this app is buying the gallon.
"""

import unittest

from scraper import (
    apply_offer_quality_filters,
    max_price_for_product,
    select_best_offer,
)

SPECTICLE = {"id": 4, "slug": "spectacle-flo", "category": "pre-emergent"}
SPREADER = {"id": 310, "slug": "lesco-high-wheel-80", "category": "spreader-push"}


def offer(price, qty, retailer, unit="fl oz"):
    return {
        "retailer": retailer,
        "retailer_name": retailer,
        "price": price,
        "url": f"https://{retailer}.example.com/p/specticle",
        "in_stock": True,
        "package_quantity": qty,
        "package_unit": unit,
        "price_per_unit": round(price / qty, 2),
    }


class MaxPriceForProduct(unittest.TestCase):
    def test_specticle_is_capped(self):
        self.assertEqual(max_price_for_product(SPECTICLE), 500)

    def test_products_without_an_entry_are_uncapped(self):
        self.assertIsNone(max_price_for_product({"id": 9999}))

    def test_expensive_equipment_is_not_capped(self):
        # A LESCO high wheel is legitimately $700; a blanket cap would delete
        # real prices, which is why the ceiling is per product.
        self.assertIsNone(max_price_for_product(SPREADER))


class BestOfferRespectsCeiling(unittest.TestCase):
    def test_the_gallon_is_never_the_best_price(self):
        offers = [
            offer(354.68, 18, "sunspot"),
            offer(387.77, 18, "seedbarn"),
            offer(2247.32, 128, "sunspot-gallon"),
        ]
        best = select_best_offer(SPECTICLE, offers)
        self.assertEqual(best["price"], 354.68)

    def test_an_uncapped_product_still_prefers_bulk_value(self):
        # The existing unit-price behaviour is deliberate for products where
        # the bigger size is a real consumer purchase.
        product = {"id": 9999, "category": "pre-emergent"}
        offers = [offer(100.00, 10, "small"), offer(150.00, 20, "large")]
        self.assertEqual(select_best_offer(product, offers)["retailer"], "large")


class CeilingExcludesFromTheFeed(unittest.TestCase):
    def test_over_ceiling_offers_are_marked_excluded(self):
        product = dict(SPECTICLE)
        product["offers"] = [
            offer(354.68, 18, "sunspot"),
            offer(2247.32, 128, "sunspot-gallon"),
        ]
        apply_offer_quality_filters([product])
        gallon = next(o for o in product["offers"] if o["price"] == 2247.32)
        bottle = next(o for o in product["offers"] if o["price"] == 354.68)
        self.assertTrue(gallon["excluded"])
        self.assertIn("maximum", gallon["exclude_reason"])
        self.assertFalse(bottle.get("excluded"))

    def test_best_price_after_filtering_is_the_bottle(self):
        product = dict(SPECTICLE)
        product["offers"] = [
            offer(354.68, 18, "sunspot"),
            offer(2247.32, 128, "sunspot-gallon"),
        ]
        apply_offer_quality_filters([product])
        self.assertEqual(product["best_price"]["price"], 354.68)


if __name__ == "__main__":
    unittest.main()


class JunkUrlsAreNotProductPages(unittest.TestCase):
    """Retailer Q&A pages carry a price in their markup but sell nothing.

    Both of these were live sources feeding phantom best prices on 2026-08-25:
    a Specticle FLO answer page priced at $340.02, and a Turflon Ester question
    page priced at $49.98 while claiming a 128 fl oz gallon that really costs
    about $170.
    """

    def test_domyown_answer_pages_are_rejected(self):
        from scraper import is_bad_product_url
        self.assertTrue(is_bad_product_url(
            "https://www.domyown.com/does-this-specticle-flo-have-distinct-smell-and-color-a-1.html"
        ))
        self.assertTrue(is_bad_product_url(
            "https://www.domyown.com/can-monterey-turflon-ester-herbicide-be-applied-qa-79253.html"
        ))

    def test_real_product_pages_still_pass(self):
        from scraper import is_bad_product_url
        for url in (
            "https://www.domyown.com/specticle-flo-p-2797.html",
            "https://pestrong.com/product/specticle-flo-pre-emergent-herbicide-18-oz-gallon/",
            "https://www.sunspotsupply.com/products/specticle-flo-18oz",
            "https://seedbarn.com/products/specticle-flo-herbicide-18-ounces",
        ):
            self.assertFalse(is_bad_product_url(url), url)

    def test_a_product_slug_beginning_with_how_is_not_treated_as_an_article(self):
        from scraper import is_bad_product_url
        self.assertFalse(is_bad_product_url("https://shop.example.com/products/how-to-kit"))


class CombinedSizeUrls(unittest.TestCase):
    def test_an_explicit_18_oz_beats_the_word_gallon_in_the_same_url(self):
        from scraper import infer_package_size
        product = {"id": 4, "category": "pre-emergent"}
        got = infer_package_size(product, {
            "url": "https://pestrong.com/product/specticle-flo-pre-emergent-herbicide-18-oz-gallon/",
            "title": None,
        })
        self.assertEqual(got["package_quantity"], 18.0)

    def test_a_genuine_gallon_url_is_still_a_gallon(self):
        from scraper import infer_package_size
        product = {"id": 4, "category": "pre-emergent"}
        got = infer_package_size(product, {
            "url": "https://www.sunspotsupply.com/products/specticle-flo-herbicide-gallon",
            "title": None,
        })
        self.assertEqual(got["package_quantity"], 128.0)
