"""One store page that never returns must not stall the whole sweep.

On 2026-11-17 a sweep logged a page at product 53 of 251 and then sat for 70
minutes until the job's 90 minute limit killed it. The time budget is only
checked between products, so nothing was published and every store price
stayed two days old. A browser call now has a hard deadline: past it, the
sweep's own browser is killed (which makes the stuck call fail at once), the
page is skipped, and a fresh browser is launched for the next one.
"""

import threading
import time
import unittest

import scraper


class DescendantBrowserPidsTest(unittest.TestCase):
    PS = """
      100     1 python
      200   100 node
      300   200 chrome
      301   300 chrome_crashpad
      302   300 headless_shell
      900     1 Google Chrome
      901   900 Google Chrome Helper
      400   100 git
    """

    def test_only_this_sweeps_own_browser_processes_are_found(self):
        self.assertEqual(scraper._descendant_browser_pids(self.PS, 100), [300, 301, 302])

    def test_someone_elses_browser_is_never_touched(self):
        pids = scraper._descendant_browser_pids(self.PS, 100)

        self.assertNotIn(900, pids)
        self.assertNotIn(901, pids)

    def test_no_browser_no_pids(self):
        self.assertEqual(scraper._descendant_browser_pids(self.PS, 400), [])


class _StuckPage:
    def __init__(self, released: threading.Event):
        self.released = released

    def goto(self, *args, **kwargs):
        # Blocks until the browser is "killed", then fails the way Playwright
        # does when its browser goes away.
        self.released.wait(timeout=10)
        raise RuntimeError("Target page, context or browser has been closed")


class _FakeContext:
    def __init__(self, page):
        self.page = page

    def new_page(self):
        return self.page

    def close(self):
        pass


class _FakeBrowser:
    def __init__(self, page=None, connected=True):
        self.page = page
        self.connected = connected

    def new_context(self, **kwargs):
        return _FakeContext(self.page)

    def is_connected(self):
        return self.connected


class BrowserHardDeadlineTest(unittest.TestCase):
    def setUp(self):
        self._saved = (
            scraper._browser,
            scraper._playwright,
            scraper._browser_needs_restart,
            scraper._kill_stuck_browser,
            scraper.BROWSER_HARD_DEADLINE_SECONDS,
        )

    def tearDown(self):
        (
            scraper._browser,
            scraper._playwright,
            scraper._browser_needs_restart,
            scraper._kill_stuck_browser,
            scraper.BROWSER_HARD_DEADLINE_SECONDS,
        ) = self._saved

    def test_a_page_that_never_returns_is_abandoned_at_the_deadline(self):
        released = threading.Event()
        kills = []

        def kill():
            kills.append(time.monotonic())
            released.set()

        scraper._browser = _FakeBrowser(_StuckPage(released))
        scraper._kill_stuck_browser = kill
        scraper.BROWSER_HARD_DEADLINE_SECONDS = 0.2

        started = time.monotonic()
        html = scraper.browser_fetch("https://store.example/stuck", timeout=100)

        self.assertIsNone(html)
        self.assertEqual(len(kills), 1)
        self.assertLess(time.monotonic() - started, 3)

    def test_a_page_that_returns_in_time_is_left_alone(self):
        kills = []

        class QuickPage:
            url = "https://store.example/ok"

            def goto(self, *a, **k):
                return None

            def title(self):
                return "OK"

            def content(self):
                return "<html>ok</html>"

            def close(self):
                pass

        scraper._browser = _FakeBrowser(QuickPage())
        scraper._kill_stuck_browser = lambda: kills.append(1)
        scraper.BROWSER_HARD_DEADLINE_SECONDS = 5

        self.assertEqual(scraper.browser_fetch("https://store.example/ok"), "<html>ok</html>")
        time.sleep(0.05)
        self.assertEqual(kills, [])

    def test_a_fresh_browser_is_launched_after_one_was_killed(self):
        fresh = _FakeBrowser()

        class FakeChromium:
            def launch(self, **kwargs):
                return fresh

        class FakePlaywright:
            chromium = FakeChromium()

        scraper._browser = _FakeBrowser(connected=False)
        scraper._playwright = FakePlaywright()
        scraper._browser_needs_restart = True

        self.assertIs(scraper.get_browser(), fresh)
        self.assertFalse(scraper._browser_needs_restart)
        self.assertIs(scraper.get_browser(), fresh)


if __name__ == "__main__":
    unittest.main()
