import unittest

import discover_sources


class DiscoverSourcesTests(unittest.TestCase):
    def test_normalize_url_removes_tracking_and_fragments(self):
        url = discover_sources.normalize_url(
            "https://Example.com/products/prodiamine?srsltid=abc&utm_source=x&variant=1#reviews"
        )

        self.assertEqual(url, "https://example.com/products/prodiamine?variant=1")

    def test_score_candidate_prefers_matching_product(self):
        product = {
            "name": "Prodiamine 65WDG",
            "search_query": "Prodiamine 65WDG",
            "slug": "prodiamine-65wdg",
            "active_ingredient": "prodiamine",
            "alt_names": ["Quali-Pro Prodiamine 65WDG"],
        }

        good = discover_sources.score_candidate(
            product,
            "Quali-Pro Prodiamine 65 WDG Herbicide",
            "https://merchant.example/products/prodiamine-65wdg",
        )
        bad = discover_sources.score_candidate(
            product,
            "Generic lawn sprayer",
            "https://merchant.example/products/sprayer",
        )

        self.assertGreater(good, bad)

    def test_merge_sources_rejects_google_urls(self):
        merged = discover_sources.merge_sources([], [
            {"url": "https://www.google.com/search?q=x", "confidence": 99},
            {"url": "https://merchant.example/product", "confidence": 5},
        ], 10)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["url"], "https://merchant.example/product")


if __name__ == "__main__":
    unittest.main()
