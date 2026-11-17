"""A stored price must keep the time it was really read.

When a retailer page cannot be read (Walmart serves a robot check to every
request), the sweep re-serves the last price it has on file. The sweep then
saves that offer back to product_sources.json and stamps last_seen with the
current time, so the stored price looks freshly checked on every run and
never ages. price_read_at records the last time a price actually came off a
page, and a re-served stored price must not move it.
"""

import unittest

import scraper

STORED = "manual_verified_source"
LONG_AGO = "2026-08-01T12:00:00+00:00"
THIS_RUN = "2099-01-01T00:00:00+00:00"


def saved_source(**extra):
    return {
        "url": "https://store.example/celsius-wg",
        "retailer": "example-store",
        "retailer_name": "Example Store",
        "title": "Celsius WG",
        "price_verified": 13.79,
        "last_seen": "2099-05-16T01:52:11+00:00",
        "in_stock": True,
        **extra,
    }


class StoredPriceReadTimeTest(unittest.TestCase):
    def test_stored_price_offer_reports_when_the_price_was_read(self):
        offer = scraper._offer_from_verified_source(saved_source(price_read_at=LONG_AGO))

        self.assertEqual(offer["source"], STORED)
        self.assertEqual(offer["price_read_at"], LONG_AGO)

    def test_stored_price_offer_does_not_invent_a_read_time(self):
        offer = scraper._offer_from_verified_source(saved_source())

        self.assertNotIn("price_read_at", offer)

    def test_price_read_this_run_records_its_read_time(self):
        results = [{
            "id": 15,
            "name": "Celsius WG",
            "offers": [{
                "retailer": "example-store",
                "retailer_name": "Example Store",
                "price": 14.25,
                "url": "https://store.example/celsius-wg",
                "title": "Celsius WG",
                "last_checked": THIS_RUN,
                "source": "saved_product_source",
            }],
        }]
        source_map = {"products": {"15": [saved_source(price_read_at=LONG_AGO)]}}

        saved = scraper.update_product_sources(source_map, results)["products"]["15"][0]

        self.assertEqual(saved["price_verified"], 14.25)
        self.assertEqual(saved["price_read_at"], THIS_RUN)

    def test_reserving_a_stored_price_does_not_refresh_its_read_time(self):
        source = saved_source(price_read_at=LONG_AGO)
        stored_offer = scraper._offer_from_verified_source(source)
        results = [{"id": 15, "name": "Celsius WG", "offers": [stored_offer]}]

        saved = scraper.update_product_sources({"products": {"15": [source]}}, results)["products"]["15"][0]

        self.assertEqual(saved["price_verified"], 13.79)
        self.assertEqual(saved["price_read_at"], LONG_AGO)

    def test_reserving_a_stored_price_of_unknown_age_leaves_it_unknown(self):
        source = saved_source()
        stored_offer = scraper._offer_from_verified_source(source)
        results = [{"id": 15, "name": "Celsius WG", "offers": [stored_offer]}]

        saved = scraper.update_product_sources({"products": {"15": [source]}}, results)["products"]["15"][0]

        self.assertNotIn("price_read_at", saved)


if __name__ == "__main__":
    unittest.main()
