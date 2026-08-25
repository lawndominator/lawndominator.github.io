"""Multi-variant product page handling.

Ground truth these are built from, read off DoMyOwn's live Specticle FLO page
(https://www.domyown.com/specticle-flo-p-2797.html) on 2026-08-25:

    {"name": "Specticle FLO Herbicide",          "price": "340.02",
     "availability": "https://schema.org/OutOfStock", "sku": "2797"}
    {"name": "Specticle FLO Herbicide - Gallon", "price": "2143.03",
     "availability": "https://schema.org/InStock",    "sku": "12894"}

The catalog product is the 18 oz. Publishing the gallon because it happens to
be the in-stock one would quote $2,143 as the price of an 18 oz bottle.
"""

import unittest

from scraper import _offer_availability_in_stock, select_jsonld_offer

DOMYOWN_URL = "https://www.domyown.com/specticle-flo-p-2797.html"
DOMYOWN_OFFERS = [
    {
        "name": "Specticle FLO Herbicide",
        "price": "340.02",
        "availability": "https://schema.org/OutOfStock",
        "sku": "2797",
    },
    {
        "name": "Specticle FLO Herbicide - Gallon",
        "price": "2143.03",
        "availability": "https://schema.org/InStock",
        "sku": "12894",
    },
]


class SelectJsonldOffer(unittest.TestCase):
    def test_picks_the_variant_named_by_the_page_url_sku(self):
        chosen = select_jsonld_offer(
            DOMYOWN_OFFERS, page_url=DOMYOWN_URL, product_name="Specticle FLO Herbicide"
        )
        self.assertEqual(chosen["price"], "340.02")

    def test_does_not_quote_a_gallon_as_the_price_of_an_18_oz(self):
        chosen = select_jsonld_offer(
            DOMYOWN_OFFERS, page_url=DOMYOWN_URL, product_name="Specticle FLO Herbicide"
        )
        self.assertNotIn("Gallon", chosen["name"])

    def test_does_not_prefer_a_variant_merely_because_it_is_in_stock(self):
        # The regression this guards: ranking by availability picked the
        # in-stock gallon over the out-of-stock 18 oz the catalog asked for.
        chosen = select_jsonld_offer(
            DOMYOWN_OFFERS, page_url=DOMYOWN_URL, product_name="Specticle FLO Herbicide"
        )
        self.assertEqual(chosen["sku"], "2797")

    def test_falls_back_to_exact_name_match_when_the_url_has_no_sku(self):
        chosen = select_jsonld_offer(
            DOMYOWN_OFFERS,
            page_url="https://example.com/specticle",
            product_name="Specticle FLO Herbicide",
        )
        self.assertEqual(chosen["price"], "340.02")

    def test_falls_back_to_the_first_offer_with_no_other_signal(self):
        chosen = select_jsonld_offer(DOMYOWN_OFFERS, page_url="", product_name="")
        self.assertEqual(chosen["price"], "340.02")

    def test_skips_variants_with_no_parseable_price(self):
        offers = [{"name": "Call for pricing"}, {"name": "Jug", "price": "12.00"}]
        self.assertEqual(select_jsonld_offer(offers)["price"], "12.00")

    def test_accepts_a_single_offer_object(self):
        self.assertEqual(select_jsonld_offer({"price": "9.99"})["price"], "9.99")

    def test_returns_none_when_nothing_is_priced(self):
        self.assertIsNone(select_jsonld_offer([{"name": "x"}]))
        self.assertIsNone(select_jsonld_offer(None))

    def test_short_skus_do_not_match_random_url_substrings(self):
        offers = [
            {"name": "Small", "price": "5.00", "sku": "1"},
            {"name": "Big", "price": "50.00", "sku": "99887"},
        ]
        chosen = select_jsonld_offer(
            offers, page_url="https://shop.example.com/item-99887", product_name=""
        )
        self.assertEqual(chosen["sku"], "99887")


class OfferAvailability(unittest.TestCase):
    def test_reads_schema_org_urls(self):
        self.assertIs(
            _offer_availability_in_stock({"availability": "https://schema.org/InStock"}),
            True,
        )
        self.assertIs(
            _offer_availability_in_stock({"availability": "https://schema.org/OutOfStock"}),
            False,
        )

    def test_domyown_18oz_is_genuinely_out_of_stock(self):
        self.assertIs(_offer_availability_in_stock(DOMYOWN_OFFERS[0]), False)

    def test_absent_or_unrecognised_availability_is_unknown(self):
        # None means "fall back to the page heuristic", not "in stock".
        self.assertIsNone(_offer_availability_in_stock({}))
        self.assertIsNone(_offer_availability_in_stock({"availability": ""}))
        self.assertIsNone(_offer_availability_in_stock({"availability": "mystery"}))

    def test_backorder_and_preorder_count_as_purchasable(self):
        self.assertIs(
            _offer_availability_in_stock({"availability": "http://schema.org/BackOrder"}),
            True,
        )


if __name__ == "__main__":
    unittest.main()
