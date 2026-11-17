"""Both feed writers must start from the tip of main.

A scheduled run checks out the commit that triggered it unless told
otherwise. The two workflows share one concurrency group, so a run can wait
behind the other writer and then start from a feed that is already out of
date. Its commit step would publish that older feed over the newer one.
"""

import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
FEED_WRITERS = ("price-scraper.yml", "price-scraper-fast-lane.yml")


def checkout_step(text: str) -> str:
    match = re.search(r"uses: actions/checkout@\S+\n(?P<body>(?:[ \t]+.*\n|\n)*?)(?=\s+- name:)", text)
    if not match:
        raise AssertionError("no actions/checkout step found")
    return match.group("body")


class FeedWriterCheckoutTest(unittest.TestCase):
    def test_feed_writers_check_out_the_tip_of_main(self):
        for name in FEED_WRITERS:
            with self.subTest(workflow=name):
                body = checkout_step((WORKFLOWS / name).read_text())
                self.assertRegex(body, r"(?m)^\s+ref: main\s*$")

    def test_feed_writers_share_one_write_queue(self):
        for name in FEED_WRITERS:
            with self.subTest(workflow=name):
                text = (WORKFLOWS / name).read_text()
                self.assertRegex(text, r"(?m)^concurrency:\n\s+group: price-feed-write\n\s+cancel-in-progress: false$")

    def test_fast_lane_never_publishes_over_a_newer_feed(self):
        text = (WORKFLOWS / "price-scraper-fast-lane.yml").read_text()
        guard = text.index("git diff --quiet HEAD origin/main -- prices.json")
        reset = text.index("git reset --hard origin/main")
        self.assertLess(guard, reset)


if __name__ == "__main__":
    unittest.main()
