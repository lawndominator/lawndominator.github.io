"""A sudden lower Amazon price is held back until it has lasted a day.

Amazon's API reports the featured offer's item price and nothing about
shipping. When two sellers land at the same total, Amazon rotates the featured
offer between them, and the API price jumps with it. Seen 2026-11-16 to 17 on
Drexel Simazine 4L (B0GJ6SLY12): eight reads in eleven hours alternated between
$89.19 and $69.99, every one flagged as the featured offer, while the product
page showed $89.19 with free shipping and "New (3) from $89.19 & FREE
Shipping". The $69.99 offer costs the shopper $89.19 too, once shipping is
added, so publishing it understates what they pay and fires a 21% "price
drop" that never happened.

The API cannot tell the two cases apart, so the feed is cautious: a featured
price more than 5% under the one already published is not published while the
higher price has been read in the last 24 hours. A real cut shows up a day
late. A rise, or a small move, shows up at once.
"""

import unittest
from datetime import datetime, timedelta, timezone

import scraper

NOW = datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc)
URL = "https://www.amazon.com/dp/B0GJ6SLY12?tag=lawndominator-20"


def hours_ago(hours):
    return (NOW - timedelta(hours=hours)).isoformat()


def amazon(price, **over):
    base = {
        "retailer": "amazon",
        "retailer_name": "Amazon",
        "price": price,
        "url": URL,
        "in_stock": True,
        "last_checked": NOW.isoformat(),
        "source": "amazon_creators_api",
        "featured_offer": True,
    }
    base.update(over)
    return base


def published(price, seen_hours_ago, **over):
    return amazon(price, last_checked=hours_ago(seen_hours_ago), price_seen_at=hours_ago(seen_hours_ago), **over)


def settle(fresh, previous):
    return scraper.settle_amazon_price(fresh, previous, now=NOW)


class AmazonPriceHoldTest(unittest.TestCase):
    def test_a_sudden_lower_price_does_not_replace_one_read_hours_ago(self):
        offer = settle(amazon(69.99), published(89.19, 2))

        self.assertEqual(offer["price"], 89.19)
        self.assertEqual(offer["price_reading"], 69.99)
        # The $89.19 was last read two hours ago, and the feed says so.
        self.assertEqual(offer["price_seen_at"], hours_ago(2))
        # Amazon was checked just now.
        self.assertEqual(offer["last_checked"], NOW.isoformat())

    def test_the_hold_survives_run_after_run_while_the_higher_price_keeps_coming_back(self):
        held = settle(amazon(69.99), published(89.19, 2))
        again = settle(amazon(69.99), held)

        self.assertEqual(again["price"], 89.19)
        self.assertEqual(again["price_seen_at"], hours_ago(2))

    def test_a_lower_price_that_lasts_a_day_is_published(self):
        offer = settle(amazon(69.99), published(89.19, 25))

        self.assertEqual(offer["price"], 69.99)
        self.assertEqual(offer["price_seen_at"], NOW.isoformat())
        self.assertNotIn("price_reading", offer)

    def test_a_held_price_is_released_a_day_after_the_higher_one_was_last_read(self):
        held = settle(amazon(69.99), published(89.19, 2))
        held["price_seen_at"] = hours_ago(24.5)

        self.assertEqual(settle(amazon(69.99), held)["price"], 69.99)

    def test_a_rise_is_published_at_once(self):
        offer = settle(amazon(89.19), published(69.99, 2))

        self.assertEqual(offer["price"], 89.19)
        self.assertEqual(offer["price_seen_at"], NOW.isoformat())

    def test_a_small_move_down_is_published_at_once(self):
        # Sellers reprice by cents all day; that is the real price moving.
        offer = settle(amazon(31.41), published(32.95, 2))

        self.assertEqual(offer["price"], 31.41)
        self.assertNotIn("price_reading", offer)

    def test_any_drop_big_enough_to_alert_on_is_held(self):
        self.assertEqual(scraper.AMAZON_PRICE_HOLD_PERCENT, scraper.MIN_ALERT_DROP_PERCENT)
        self.assertEqual(settle(amazon(95.0), published(100.0, 2))["price"], 100.0)
        self.assertEqual(settle(amazon(95.01), published(100.0, 2))["price"], 95.01)

    def test_the_first_read_of_a_product_is_published(self):
        self.assertEqual(settle(amazon(69.99), None)["price"], 69.99)
        self.assertEqual(settle(amazon(69.99), None)["price_seen_at"], NOW.isoformat())

    def test_a_previous_price_amazon_never_featured_is_not_a_reference(self):
        unconfirmed = published(89.19, 2, featured_offer=False)

        self.assertEqual(settle(amazon(69.99), unconfirmed)["price"], 69.99)

    def test_a_different_listing_starts_over(self):
        other = published(89.19, 2, url="https://www.amazon.com/dp/B000000000?tag=lawndominator-20")

        self.assertEqual(settle(amazon(69.99), other)["price"], 69.99)

    def test_a_price_on_file_from_before_the_field_existed_uses_its_check_time(self):
        before = amazon(89.19, last_checked=hours_ago(2))

        self.assertEqual(settle(amazon(69.99), before)["price"], 89.19)

    def test_a_read_with_no_price_or_no_stock_passes_through(self):
        link_only = amazon(None)
        link_only.pop("featured_offer")
        sold_out = amazon(69.99, in_stock=False)

        self.assertEqual(settle(link_only, published(89.19, 2)), link_only)
        self.assertEqual(settle(sold_out, published(89.19, 2))["price"], 69.99)
        self.assertIsNone(settle(None, published(89.19, 2)))

    def test_the_seller_behind_the_featured_offer_is_recorded(self):
        product = {"id": 1, "slug": "x", "name": "X", "search_query": "x"}
        listing = {
            "price": {"money": {"amount": 89.19}},
            "is_buy_box_winner": True,
            "condition": {"value": "New"},
            "merchant_info": {"name": "Agromax, LLC"},
        }
        offer = scraper._amazon_item_offer({"offers_v2": {"listings": [listing]}}, product)

        self.assertEqual(offer["seller"], "Agromax, LLC")
        source = open(scraper.__file__).read()
        self.assertIn("GetItemsResource.OFFERS_V2_DOT_LISTINGS_DOT_MERCHANT_INFO", source)
        self.assertIn("SearchItemsResource.OFFERS_V2_DOT_LISTINGS_DOT_MERCHANT_INFO", source)

    def test_both_feed_writers_settle_the_amazon_price(self):
        source = open(scraper.__file__).read()

        self.assertEqual(source.count("settle_amazon_price(\n"), 2)

    def test_previous_amazon_offer_is_found_in_the_last_feed_entry(self):
        entry = {"offers": [{"retailer": "domyown", "price": 80.0}, published(89.19, 2)]}

        self.assertEqual(scraper.previous_amazon_offer(entry)["price"], 89.19)
        self.assertIsNone(scraper.previous_amazon_offer(None))
        self.assertIsNone(scraper.previous_amazon_offer({"offers": []}))


if __name__ == "__main__":
    unittest.main()
