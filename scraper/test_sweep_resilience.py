"""Regression tests for the sweep-resilience fix.

The bug these guard: the full Playwright sweep ran the catalog in fixed order
and wrote prices.json only after the final product. Once the catalog outgrew
the 60 minute job timeout the run was killed mid-pass and published NOTHING,
so every non-Amazon price froze for ten days while the Amazon fast lane kept
generated_at looking current.
"""

import unittest
from datetime import datetime, timedelta, timezone

from scraper import (
    merge_unprocessed_products,
    offer_age_summary,
    order_products_by_staleness,
)


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


class OrderProductsByStaleness(unittest.TestCase):
    def test_least_recently_checked_goes_first(self):
        products = [{"id": 1}, {"id": 2}, {"id": 3}]
        previous = {
            1: {"id": 1, "updated_at": _iso(1)},
            2: {"id": 2, "updated_at": _iso(240)},
            3: {"id": 3, "updated_at": _iso(48)},
        }
        self.assertEqual(
            [p["id"] for p in order_products_by_staleness(products, previous)],
            [2, 3, 1],
        )

    def test_never_checked_products_go_first(self):
        products = [{"id": 1}, {"id": 2}]
        previous = {1: {"id": 1, "updated_at": _iso(5)}}
        self.assertEqual(
            [p["id"] for p in order_products_by_staleness(products, previous)],
            [2, 1],
        )

    def test_offer_last_checked_counts_as_freshness(self):
        products = [{"id": 1}, {"id": 2}]
        previous = {
            1: {"id": 1, "offers": [{"last_checked": _iso(200)}]},
            2: {"id": 2, "offers": [{"last_checked": _iso(2)}]},
        }
        self.assertEqual(
            [p["id"] for p in order_products_by_staleness(products, previous)],
            [1, 2],
        )

    def test_a_short_run_then_resumes_where_data_is_stalest(self):
        # The property that makes the sweep self-healing: refresh the first
        # half, and the next run's order starts with the half still stale.
        products = [{"id": i} for i in range(1, 7)]
        previous = {i: {"id": i, "updated_at": _iso(100 + i)} for i in range(1, 7)}
        first_pass = order_products_by_staleness(products, previous)[:3]
        for product in first_pass:
            previous[product["id"]] = {"id": product["id"], "updated_at": _iso(0)}
        second_pass = order_products_by_staleness(products, previous)[:3]
        self.assertFalse(
            {p["id"] for p in first_pass} & {p["id"] for p in second_pass},
            "a second run must not redo what the first run just refreshed",
        )


class MergeUnprocessedProducts(unittest.TestCase):
    def test_partial_run_still_publishes_the_whole_catalog(self):
        catalog = [{"id": 1}, {"id": 2}, {"id": 3}]
        results = [{"id": 1, "best_price": {"price": 10}}]
        previous = {
            2: {"id": 2, "best_price": {"price": 20}},
            3: {"id": 3, "best_price": {"price": 30}},
        }
        merged = merge_unprocessed_products(results, previous, catalog)
        self.assertEqual([e["id"] for e in merged], [1, 2, 3])

    def test_carried_products_are_marked_stale(self):
        catalog = [{"id": 1}, {"id": 2}]
        results = [{"id": 1, "best_price": {"price": 10}}]
        previous = {2: {"id": 2, "best_price": {"price": 20}}}
        merged = merge_unprocessed_products(results, previous, catalog)
        carried = next(e for e in merged if e["id"] == 2)
        self.assertTrue(carried["stale"])
        self.assertEqual(carried["stale_reason"], "not reached in latest sweep")

    def test_freshly_scraped_products_are_not_marked_stale(self):
        catalog = [{"id": 1}]
        results = [{"id": 1, "best_price": {"price": 10}}]
        merged = merge_unprocessed_products(results, {1: {"id": 1}}, catalog)
        self.assertNotIn("stale", merged[0])

    def test_does_not_invent_products_with_no_previous_data(self):
        catalog = [{"id": 1}, {"id": 2}]
        merged = merge_unprocessed_products([{"id": 1}], {}, catalog)
        self.assertEqual([e["id"] for e in merged], [1])

    def test_previous_entry_is_not_mutated(self):
        catalog = [{"id": 1}]
        previous = {1: {"id": 1, "best_price": {"price": 20}}}
        merge_unprocessed_products([], previous, catalog)
        self.assertNotIn("stale", previous[1])


class OfferAgeSummary(unittest.TestCase):
    def test_reports_oldest_and_median(self):
        products = [
            {"id": 1, "updated_at": _iso(1)},
            {"id": 2, "updated_at": _iso(5)},
            {"id": 3, "updated_at": _iso(240)},
        ]
        summary = offer_age_summary(products)
        self.assertEqual(summary["count"], 3)
        self.assertAlmostEqual(summary["oldest_hours"], 240, delta=1)
        self.assertAlmostEqual(summary["median_hours"], 5, delta=1)

    def test_catches_the_ten_day_freeze_this_fix_was_written_for(self):
        products = [{"id": 1, "updated_at": _iso(24)}, {"id": 2, "updated_at": _iso(240)}]
        self.assertGreater(offer_age_summary(products)["oldest_hours"], 48)

    def test_handles_a_feed_with_no_timestamps(self):
        summary = offer_age_summary([{"id": 1}])
        self.assertEqual(summary["count"], 0)
        self.assertIsNone(summary["oldest_hours"])


if __name__ == "__main__":
    unittest.main()
