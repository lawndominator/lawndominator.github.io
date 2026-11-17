"""price-history.json: one headline price per product per day.

The feed only ever holds today's prices, so the board could not say whether
today's price is a good one. This records the headline price each day, using
the same rule the website uses to pick it.
"""

import unittest

import price_history


def offer(**over):
    base = {
        "retailer": "store",
        "retailer_name": "Store",
        "price": 50.0,
        "url": "https://store.example/p",
        "in_stock": True,
        "package_label": "5 lb",
        "source": "saved_product_source",
        "quality_verified": True,
    }
    base.update(over)
    return base


def feed(day, *products):
    return {"generated_at": f"{day}T21:58:54+00:00", "products": list(products)}


def product(*offers, slug="prodiamine-65wdg"):
    return {"id": 1, "slug": slug, "name": slug, "offers": list(offers)}


class HeadlineOfferTest(unittest.TestCase):
    def test_lowest_verified_in_stock_price_leads(self):
        best = price_history.headline_offer(product(
            offer(price=73.39),
            offer(price=61.0, retailer="b"),
            offer(price=10.0, retailer="c", quality_verified=False),
            offer(price=11.0, retailer="d", in_stock=False),
            offer(price=12.0, retailer="e", excluded=True),
        ))

        self.assertEqual(best["price"], 61.0)

    def test_a_price_on_file_only_leads_when_nothing_was_read(self):
        stored = offer(price=40.0, retailer="walmart", source="manual_verified_source")

        self.assertEqual(price_history.headline_offer(product(offer(price=48.0), stored))["price"], 48.0)
        self.assertEqual(price_history.headline_offer(product(stored))["price"], 40.0)

    def test_a_scrape_error_far_below_the_pack_is_not_a_price(self):
        best = price_history.headline_offer(product(
            offer(price=5.55, retailer="a"),
            offer(price=60.0, retailer="b"),
            offer(price=70.0, retailer="c"),
            offer(price=125.0, retailer="d"),
        ))

        self.assertEqual(best["price"], 60.0)

    def test_an_amazon_price_counts_only_when_amazon_features_it(self):
        unmarked = offer(price=69.99, retailer="amazon", source="amazon_creators_api")
        featured = offer(price=89.19, retailer="amazon", source="amazon_creators_api", featured_offer=True)

        self.assertIsNone(price_history.headline_offer(product(unmarked)))
        self.assertEqual(price_history.headline_offer(product(unmarked, offer(price=95.0)))["price"], 95.0)
        self.assertEqual(price_history.headline_offer(product(featured, offer(price=95.0)))["price"], 89.19)

    def test_no_headline_without_a_publishable_price(self):
        self.assertIsNone(price_history.headline_offer(product(offer(price=None))))


class RecordTest(unittest.TestCase):
    def test_records_one_point_per_product_per_day(self):
        history = price_history.record({}, feed("2026-11-16", product(offer(price=59.06))))

        self.assertEqual(history["products"]["prodiamine-65wdg"], [["2026-11-16", 59.06, "5 lb"]])

    def test_a_later_run_the_same_day_replaces_the_point(self):
        history = price_history.record({}, feed("2026-11-16", product(offer(price=59.06))))
        history = price_history.record(history, feed("2026-11-16", product(offer(price=57.0))))

        self.assertEqual(history["products"]["prodiamine-65wdg"], [["2026-11-16", 57.0, "5 lb"]])

    def test_a_new_day_appends(self):
        history = price_history.record({}, feed("2026-11-15", product(offer(price=63.33))))
        history = price_history.record(history, feed("2026-11-16", product(offer(price=59.06))))

        self.assertEqual(
            history["products"]["prodiamine-65wdg"],
            [["2026-11-15", 63.33, "5 lb"], ["2026-11-16", 59.06, "5 lb"]],
        )

    def test_an_older_feed_never_rewrites_a_newer_day(self):
        history = price_history.record({}, feed("2026-11-16", product(offer(price=59.06))))
        history = price_history.record(history, feed("2026-11-15", product(offer(price=63.33))))

        self.assertEqual(
            history["products"]["prodiamine-65wdg"],
            [["2026-11-15", 63.33, "5 lb"], ["2026-11-16", 59.06, "5 lb"]],
        )

    def test_a_day_with_no_price_leaves_a_gap_not_a_guess(self):
        history = price_history.record({}, feed("2026-11-15", product(offer(price=63.33))))
        history = price_history.record(history, feed("2026-11-16", product(offer(price=None))))

        self.assertEqual(history["products"]["prodiamine-65wdg"], [["2026-11-15", 63.33, "5 lb"]])

    def test_points_older_than_the_window_are_dropped(self):
        history = price_history.record({}, feed("2026-01-01", product(offer(price=70.0))))
        history = price_history.record(history, feed("2026-11-16", product(offer(price=59.06))), keep_days=120)

        self.assertEqual(history["products"]["prodiamine-65wdg"], [["2026-11-16", 59.06, "5 lb"]])

    def test_records_the_feed_day_it_was_updated_from(self):
        history = price_history.record({}, feed("2026-11-16", product(offer())))

        self.assertEqual(history["updated_at"], "2026-11-16T21:58:54+00:00")
        self.assertEqual(history["schema_version"], "1.0")


if __name__ == "__main__":
    unittest.main()
