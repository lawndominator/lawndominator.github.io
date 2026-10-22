"""The alarm that would have caught the 2026-09-03 outage in one cycle."""

import unittest
from datetime import datetime, timedelta, timezone

import check_published_feed as monitor


def feed(generated_at: str, priced_offers: int) -> dict:
    return {
        "generated_at": generated_at,
        "products": [
            {
                "slug": "prodiamine-65wdg",
                "offers": [
                    {"price": 100.0 + index, "url": "https://example.com"}
                    for index in range(priced_offers)
                ],
            }
        ],
    }


class PublishedFeedMonitorTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 3, 16, 0, tzinfo=timezone.utc)
        self.fresh = self.now.isoformat()

    def test_a_healthy_feed_raises_nothing(self):
        self.assertEqual(monitor.feed_problems(feed(self.fresh, 900), self.now), [])

    def test_catches_the_frozen_feed(self):
        # The scraper stopped committing at 02:16Z; by 09:46 a customer noticed.
        stale = (self.now - timedelta(hours=13, minutes=44)).isoformat()
        problems = monitor.feed_problems(feed(stale, 900), self.now)
        self.assertTrue(any("old" in problem for problem in problems), problems)

    def test_catches_the_gutted_feed_even_when_it_is_fresh(self):
        # The website served a current generated_at with zero prices in it.
        problems = monitor.feed_problems(feed(self.fresh, 0), self.now)
        self.assertTrue(any("priced offer" in problem for problem in problems), problems)

    def test_catches_an_empty_or_broken_artifact(self):
        self.assertTrue(monitor.feed_problems({"products": []}, self.now))
        self.assertTrue(monitor.feed_problems({}, self.now))

    def test_reports_a_missing_or_unparseable_timestamp(self):
        problems = monitor.feed_problems(feed("not a date", 900), self.now)
        self.assertTrue(any("generated_at" in problem for problem in problems), problems)

    def test_accepts_both_offset_and_z_timestamps(self):
        self.assertIsNotNone(monitor.parse_generated_at("2026-09-03T16:00:00Z"))
        self.assertIsNotNone(monitor.parse_generated_at("2026-09-03T16:00:00+00:00"))
        self.assertIsNone(monitor.parse_generated_at(""))


if __name__ == "__main__":
    unittest.main()
