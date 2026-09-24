"""The publish gate must drop a bad offer, not the whole feed.

The gate runs before the commit step, so when it failed on any single finding
one bad offer out of ~1,800 froze the entire published feed. That happened: a
corroboration rule the scraper and the audit computed differently rejected one
offer of one product, no feed was committed for 13 hours, and because the
website fails closed on unverified prices it served zero prices the whole time.

Offer-level defects are now remediated by excluding that offer. Anything that
says the artifact itself is wrong, including the coverage floor, still fails.
"""

import copy
import unittest

import audit_price_feed
import scraper


def _offer(url: str, price: float, **overrides) -> dict:
    offer = {
        "retailer": "domyown",
        "retailer_name": "DoMyOwn",
        "price": price,
        "url": url,
        "in_stock": True,
        "title": "Prodiamine 65 WDG",
        "last_checked": scraper.now_iso(),
        "quality_verified": True,
        "package_quantity": 5.0,
        "package_unit": "lb",
        "package_label": "5 lb",
        "price_per_unit": round(price / 5.0, 2),
    }
    offer.update(overrides)
    return offer


class RemediationTest(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            "products": [
                {
                    "id": 1,
                    "slug": "prodiamine-65wdg",
                    "name": "Prodiamine 65WDG",
                    "category": "pre-emergent",
                }
            ]
        }
        self.feed = {
            "schema_version": "1.0",
            "generated_at": scraper.now_iso(),
            "product_count": 1,
            "products": [
                {
                    "id": 1,
                    "slug": "prodiamine-65wdg",
                    "name": "Prodiamine 65WDG",
                    "category": "pre-emergent",
                    "offers": [
                        _offer("https://www.domyown.com/prodiamine-65-wdg-p-1.html", 100.0),
                        _offer(
                            "https://www.solutionsstores.com/prodiamine-65-wdg",
                            105.0,
                            retailer="solutions",
                            retailer_name="Solutions",
                        ),
                    ],
                    "best_price": None,
                }
            ],
        }
        self.alerts = {"generated_at": scraper.now_iso(), "alerts": []}

    def test_audit_feed_still_returns_plain_issues_without_a_findings_list(self):
        issues = audit_price_feed.audit_feed(self.catalog, self.feed, self.alerts)
        self.assertIsInstance(issues, list)
        for issue in issues:
            self.assertIsInstance(issue, str)

    def test_offer_findings_point_back_at_the_offer_that_caused_them(self):
        feed = copy.deepcopy(self.feed)
        # An offer nothing can rescue: not a purchase page.
        feed["products"][0]["offers"].append(
            _offer("https://www.domyown.com/search?q=prodiamine", 99.0)
        )
        findings: list = []
        audit_price_feed.audit_feed(self.catalog, feed, self.alerts, findings)
        self.assertTrue(findings, "expected the bad offer to produce a finding")
        for finding in findings:
            self.assertEqual(finding.product_position, 0)
            self.assertEqual(finding.offer_index, 2)
            self.assertIn("offer[2]", finding.message)

    def test_one_bad_offer_is_excluded_and_the_rest_still_publishes(self):
        feed = copy.deepcopy(self.feed)
        feed["products"][0]["offers"].append(
            _offer("https://www.domyown.com/search?q=prodiamine", 99.0)
        )

        issues, removed = audit_price_feed.remediate_offer_findings(
            self.catalog, feed, self.alerts
        )

        self.assertEqual(issues, [], f"feed should publish, got: {issues}")
        self.assertTrue(removed)
        offers = feed["products"][0]["offers"]
        self.assertTrue(offers[2]["excluded"])
        self.assertEqual(
            offers[2]["exclude_reason"], audit_price_feed.REMEDIATED_OFFER_REASON
        )
        # The good offers survive and still carry the product's best price.
        self.assertFalse(offers[0].get("excluded"))
        self.assertFalse(offers[1].get("excluded"))
        self.assertIsNotNone(feed["products"][0]["best_price"])

    def test_a_broken_artifact_still_fails_the_run(self):
        feed = copy.deepcopy(self.feed)
        feed["schema_version"] = "9.9"

        issues, _ = audit_price_feed.remediate_offer_findings(
            self.catalog, feed, self.alerts
        )

        self.assertTrue(
            any("schema_version" in issue for issue in issues),
            "a structurally wrong feed must not be remediated into publishing",
        )

    def test_remediation_that_guts_the_catalog_still_fails_the_run(self):
        # Every offer unusable: remediation removes them all, and the coverage
        # floor must then stop the publish rather than ship an empty feed.
        feed = copy.deepcopy(self.feed)
        for offer in feed["products"][0]["offers"]:
            offer["url"] = "https://www.domyown.com/search?q=prodiamine"

        issues, removed = audit_price_feed.remediate_offer_findings(
            self.catalog, feed, self.alerts
        )

        self.assertTrue(removed)
        self.assertTrue(issues, "an emptied feed must still fail the audit")
        self.assertTrue(
            any(
                "no safe priced offers remain" in issue
                or "safe best price" in issue
                for issue in issues
            ),
            f"expected a coverage failure, got: {issues}",
        )


if __name__ == "__main__":
    unittest.main()
