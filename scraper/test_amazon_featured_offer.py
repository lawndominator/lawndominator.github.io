"""The Amazon price is the offer Amazon features on the product page.

OffersV2 can return more than one listing for an item. The scraper used to
take the first one that had an amount, so it published prices nobody sees on
the page: Simazine 4L at $69.99 while the page said $89.19, and a price for
Talstar XTRA when the page had no featured offer at all ("See All Buying
Options"). Two reads minutes apart could disagree, which also produced price
drop alerts for drops that never happened.

Amazon's reference for OffersV2: IsBuyBoxWinner "is the best offer
recommended by Amazon ... This featured offer is seen on Detail Page", and
Type marks SUBSCRIBE_AND_SAVE listings, whose price is not the one-time price.
"""

import unittest

import scraper


def listing(amount, **over):
    base = {
        "price": {"money": {"amount": amount}},
        "availability": {"type": "IN_STOCK", "message": "In Stock"},
        "is_buy_box_winner": False,
        "condition": {"value": "New"},
    }
    base.update(over)
    return base


def item(*listings):
    return {"offers_v2": {"listings": list(listings)}}


class AmazonFeaturedOfferTest(unittest.TestCase):
    def test_price_is_the_featured_offer_not_the_first_listing(self):
        simazine = item(listing(69.99), listing(89.19, is_buy_box_winner=True))

        self.assertEqual(scraper._amazon_item_price(simazine), 89.19)

    def test_no_price_when_amazon_features_no_offer(self):
        talstar = item(listing(72.41), listing(80.0))

        self.assertIsNone(scraper._amazon_item_price(talstar))

    def test_a_subscribe_and_save_price_is_not_the_price(self):
        both = item(
            listing(84.73, is_buy_box_winner=True, type="SUBSCRIBE_AND_SAVE"),
            listing(89.19, is_buy_box_winner=True),
        )

        self.assertEqual(scraper._amazon_item_price(both), 89.19)

    def test_a_used_offer_is_not_the_price(self):
        used_only = item(listing(40.0, is_buy_box_winner=True, condition={"value": "Used"}))

        self.assertIsNone(scraper._amazon_item_price(used_only))

    def test_a_price_amazon_hides_is_not_published(self):
        hidden = item(listing(59.0, is_buy_box_winner=True, violates_map=True))

        self.assertIsNone(scraper._amazon_item_price(hidden))

    def test_availability_is_read_from_the_featured_offer(self):
        mixed = item(
            listing(69.99, availability={"type": "OUT_OF_STOCK", "message": "Out of stock"}),
            listing(89.19, is_buy_box_winner=True),
        )

        self.assertTrue(scraper._amazon_item_in_stock(mixed))

    def test_an_item_with_no_featured_offer_is_not_called_in_stock(self):
        self.assertIsNone(scraper._amazon_item_in_stock(item(listing(72.41))))

    def test_listings_that_carry_no_featured_flag_at_all_still_price(self):
        # If Amazon ever omits the flag entirely, do not blank every Amazon
        # price: fall back to the first new, one-time listing.
        unflagged = item(
            {"price": {"money": {"amount": 84.73}}, "type": "SUBSCRIBE_AND_SAVE"},
            {"price": {"money": {"amount": 89.19}}, "condition": {"value": "New"}},
        )

        self.assertEqual(scraper._amazon_item_price(unflagged), 89.19)

    def test_the_api_is_asked_which_offer_is_featured(self):
        source = open(scraper.__file__).read()
        for resource in ("IS_BUY_BOX_WINNER", "CONDITION", "TYPE"):
            self.assertIn(f"GetItemsResource.OFFERS_V2_DOT_LISTINGS_DOT_{resource}", source)
            self.assertIn(f"SearchItemsResource.OFFERS_V2_DOT_LISTINGS_DOT_{resource}", source)


if __name__ == "__main__":
    unittest.main()
