"""Spend the Google Shopping searches where they matter.

The SerpApi account has a small monthly allowance. The weekly discovery run
spent it on the first products in sweep order and then failed every remaining
call: on 2026-11-15 it searched 74 of 251 products and logged "Your account
has run out of searches" 178 times. Products that already have several stores
read off their own pages do not need a web-wide search; products with no
store price at all do.
"""

import unittest

import scraper


def live(n):
    return [{"source": "saved_product_source", "price": 10.0 + i} for i in range(n)]


def on_file(n):
    return [{"source": "manual_verified_source", "price": 10.0 + i} for i in range(n)]


class NeedsWebDiscoveryTest(unittest.TestCase):
    def test_a_product_with_no_freshly_read_store_price_needs_a_search(self):
        self.assertTrue(scraper._needs_web_discovery([]))
        self.assertTrue(scraper._needs_web_discovery(on_file(5)))

    def test_one_store_is_not_a_comparison(self):
        self.assertTrue(scraper._needs_web_discovery(live(1)))

    def test_a_product_already_compared_across_stores_is_skipped(self):
        self.assertFalse(scraper._needs_web_discovery(live(2)))
        self.assertFalse(scraper._needs_web_discovery(live(6) + on_file(3)))

    def test_an_unpriced_page_read_does_not_count_as_a_store_price(self):
        self.assertTrue(scraper._needs_web_discovery([{"source": "saved_product_source", "price": None}]))


class _Response:
    def __init__(self, status_code, text="{}"):
        self.status_code = status_code
        self.text = text

    def json(self):
        return {"ok": True}


class SearchAllowanceTest(unittest.TestCase):
    def setUp(self):
        self._saved = (scraper._session.get, scraper.SERPAPI_API_KEY, scraper._serpapi_exhausted)
        scraper.SERPAPI_API_KEY = "test-key"
        scraper._serpapi_exhausted = False

    def tearDown(self):
        scraper._session.get, scraper.SERPAPI_API_KEY, scraper._serpapi_exhausted = self._saved

    def test_once_the_allowance_is_gone_no_further_calls_are_made(self):
        calls = []

        def get(url, **kwargs):
            calls.append(url)
            return _Response(429, '{"error": "Your account has run out of searches."}')

        scraper._session.get = get

        self.assertIsNone(scraper._serpapi_search({"engine": "google_shopping", "q": "a"}))
        self.assertIsNone(scraper._serpapi_search({"engine": "google_shopping", "q": "b"}))
        self.assertIsNone(scraper._serpapi_search({"engine": "google_shopping", "q": "c"}))

        self.assertEqual(len(calls), 1)
        self.assertTrue(scraper._serpapi_exhausted)

    def test_a_passing_rate_limit_does_not_end_the_run(self):
        responses = [_Response(429, '{"error": "Too many requests per hour."}'), _Response(200)]
        scraper._session.get = lambda url, **kwargs: responses.pop(0)

        self.assertIsNone(scraper._serpapi_search({"q": "a"}))
        self.assertEqual(scraper._serpapi_search({"q": "b"}), {"ok": True})
        self.assertFalse(scraper._serpapi_exhausted)


if __name__ == "__main__":
    unittest.main()
