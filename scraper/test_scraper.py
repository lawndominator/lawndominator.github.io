import unittest

from bs4 import BeautifulSoup

import scraper


class ScraperExtractionTests(unittest.TestCase):
    def test_parse_price_requires_price_like_text(self):
        self.assertEqual(scraper.parse_price("$79.98"), 79.98)
        self.assertEqual(scraper.parse_price("As low as $81"), 81.0)
        self.assertEqual(scraper.parse_price("Min : 81.99 - Max : 81.99"), 81.99)
        self.assertIsNone(scraper.parse_price("Prodiamine 65 WDG"))

    def test_extracts_card_price_and_joins_relative_url(self):
        soup = BeautifulSoup(
            """
            <div class="product-item">
              <a class="product-item-link" href="/prodiamine-65-wdg-barricade-herbicide">
                Prodiamine 65 WDG
              </a>
              <span class="price">$75.49</span>
            </div>
            """,
            "lxml",
        )

        result = scraper._extract_from_soup(
            soup,
            "https://www.solutionsstores.com",
            "solutions",
            "Solutions Pest & Lawn",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["price"], 75.49)
        self.assertEqual(
            result["url"],
            "https://www.solutionsstores.com/prodiamine-65-wdg-barricade-herbicide",
        )

    def test_extracts_product_jsonld_offer(self):
        soup = BeautifulSoup(
            """
            <script type="application/ld+json">
            {
              "@type": "Product",
              "url": "/prodiamine-65-wdg-generic-barricade-p-2495.html",
              "offers": {
                "@type": "Offer",
                "price": "79.98",
                "availability": "https://schema.org/InStock"
              }
            }
            </script>
            """,
            "lxml",
        )

        result = scraper._extract_from_soup(
            soup,
            "https://www.domyown.com",
            "domyown",
            "DoMyOwn",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["price"], 79.98)
        self.assertEqual(
            result["url"],
            "https://www.domyown.com/prodiamine-65-wdg-generic-barricade-p-2495.html",
        )


if __name__ == "__main__":
    unittest.main()
