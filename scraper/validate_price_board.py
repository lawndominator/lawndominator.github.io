#!/usr/bin/env python3
import json
import re
import threading
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import TCPServer

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EQUIPMENT_CATEGORIES = {
    "spreader-handheld",
    "spreader-push",
    "spreader-tow",
    "sprayer-backpack",
}
REMOVED_PRODUCT_IDS = {234, 237, 238, 239, 240, 241, 242, 243, 247, 250, 252}
BAD_VISIBLE_TEXT = (
    "Amazon linked",
    "Check price",
    "Camelcamelcamel",
    "CamelCamelCamel",
    "As an Amazon Associate",
    "qualifying purchases",
)


def load_json(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def min_equipment_price(category):
    if category == "spreader-handheld":
        return 15
    if category in {"spreader-push", "spreader-tow", "sprayer-backpack"}:
        return 100
    return 0


def assert_static_data():
    products = load_json("products.json")["products"]
    sources = load_json("product_sources.json")["products"]
    prices = load_json("prices.json")["products"]

    ids = {int(product["id"]) for product in products}
    removed = sorted(ids & REMOVED_PRODUCT_IDS)
    if removed:
        raise AssertionError(f"removed products still present: {removed}")

    equipment = [product for product in products if product.get("category") in EQUIPMENT_CATEGORIES]
    if len(equipment) < 34:
        raise AssertionError(f"expected at least 34 equipment products, found {len(equipment)}")

    missing_links = []
    missing_amazon = []
    for product in equipment:
        product_id = str(product["id"])
        source_links = [
            source.get("url")
            for source in sources.get(product_id, [])
            if source.get("manual_verified") and source.get("url")
        ]
        catalog_links = [url for url in (product.get("retailers") or {}).values() if url]
        if product.get("asin"):
            catalog_links.append(f"https://www.amazon.com/dp/{product['asin']}")
        if not source_links and not catalog_links:
            missing_links.append(f"{product['id']} {product['name']}")
        if product.get("asin"):
            amazon_urls = [*source_links, *catalog_links]
            if not any("amazon.com" in url and str(product["asin"]).upper() in url.upper() for url in amazon_urls):
                missing_amazon.append(f"{product['id']} {product['name']}")

    if missing_links:
        raise AssertionError("equipment products without any link: " + "; ".join(missing_links))
    if missing_amazon:
        raise AssertionError("equipment products with ASIN but no matching Amazon URL: " + "; ".join(missing_amazon))

    category_by_id = {int(product["id"]): product.get("category") for product in products}
    low_equipment_prices = []
    for product in prices:
        category = category_by_id.get(int(product["id"]))
        if category not in EQUIPMENT_CATEGORIES:
            continue
        floor = min_equipment_price(category)
        for offer in product.get("offers", []):
            price = offer.get("price")
            if price is not None and float(price) < floor:
                low_equipment_prices.append(
                    f"{product['id']} {product['name']} {offer.get('retailer')} ${float(price):.2f} below ${floor:.2f}"
                )
        best = product.get("best_price")
        if best and best.get("price") is not None and float(best["price"]) < floor:
            low_equipment_prices.append(
                f"{product['id']} {product['name']} best {best.get('retailer')} ${float(best['price']):.2f} below ${floor:.2f}"
            )
    if low_equipment_prices:
        raise AssertionError("low equipment prices found: " + "; ".join(low_equipment_prices))

    html = (ROOT / "price-board.html").read_text(encoding="utf-8")
    for text in BAD_VISIBLE_TEXT:
        if text in html:
            raise AssertionError(f"bad visible text found in price-board.html: {text}")
    if not re.search(r'data-scope="products"[^>]*>Products<', html):
        raise AssertionError("Products top tab missing")
    if not re.search(r'data-scope="equipment"[^>]*>Equipment<', html):
        raise AssertionError("Equipment top tab missing")

    return len(equipment)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def validate_rendered_board(expected_equipment_count):
    class ReusableTCPServer(TCPServer):
        allow_reuse_address = True

    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(ROOT), **kwargs)
    with ReusableTCPServer(("127.0.0.1", 0), handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(f"http://127.0.0.1:{port}/price-board.html", wait_until="networkidle")
            page.wait_for_selector(".price-tile", timeout=15000)

            products_view = page.evaluate(
                """() => ({
                    tabs: [...document.querySelectorAll("[data-scope]")].map(tab => tab.textContent.trim()),
                    activeTab: document.querySelector("[data-scope].active")?.textContent.trim(),
                    groups: [...document.querySelectorAll(".product-group__header h2")].map(el => el.textContent.trim()),
                    cards: document.querySelectorAll(".price-tile").length,
                    categoryOptions: [...document.querySelectorAll("#board-category option")].map(option => option.value),
                    bodyText: document.body.textContent
                })"""
            )
            if products_view["tabs"] != ["Products", "Equipment"]:
                raise AssertionError(f"unexpected scope tabs: {products_view['tabs']}")
            if products_view["activeTab"] != "Products":
                raise AssertionError(f"Products tab should be active by default: {products_view['activeTab']}")
            if "Equipment" in products_view["groups"]:
                raise AssertionError("Products tab rendered an Equipment group")
            if "spreader-push" in products_view["categoryOptions"]:
                raise AssertionError("Products tab contains equipment category options")
            for text in BAD_VISIBLE_TEXT:
                if text in products_view["bodyText"]:
                    raise AssertionError(f"bad visible text rendered: {text}")

            page.click('[data-scope="equipment"]')
            page.wait_for_timeout(250)
            equipment_view = page.evaluate(
                """() => ({
                    activeTab: document.querySelector("[data-scope].active")?.textContent.trim(),
                    groups: [...document.querySelectorAll(".product-group__header h2")].map(el => el.textContent.trim()),
                    cards: document.querySelectorAll(".price-tile").length,
                    links: document.querySelectorAll(".price-tile a.top-offer").length,
                    amazonLinks: [...document.querySelectorAll(".price-tile a.top-offer")].filter(link => /amazon\\.com/i.test(link.href)).length,
                    cardsWithoutLinks: [...document.querySelectorAll(".price-tile")].filter(card => !card.querySelector("a.top-offer")).map(card => card.querySelector(".tile-title")?.textContent.trim()),
                    categoryOptions: [...document.querySelectorAll("#board-category option")].map(option => option.value),
                    bodyText: document.body.textContent
                })"""
            )
            browser.close()

        if equipment_view["activeTab"] != "Equipment":
            raise AssertionError(f"Equipment tab did not become active: {equipment_view['activeTab']}")
        expected_groups = ["Backpack Sprayer", "Push Spreader", "Tow-Behind Spreader", "Handheld Spreader"]
        if equipment_view["groups"] != expected_groups:
            raise AssertionError(f"unexpected equipment groups: {equipment_view['groups']}")
        if equipment_view["cards"] != expected_equipment_count:
            raise AssertionError(f"expected {expected_equipment_count} equipment cards, rendered {equipment_view['cards']}")
        if equipment_view["cardsWithoutLinks"]:
            raise AssertionError("equipment cards without links: " + "; ".join(equipment_view["cardsWithoutLinks"]))
        if equipment_view["links"] < expected_equipment_count:
            raise AssertionError(f"expected at least one link per equipment card, found {equipment_view['links']} links")
        if equipment_view["amazonLinks"] < 25:
            raise AssertionError(f"expected at least 25 Amazon equipment links, found {equipment_view['amazonLinks']}")
        if "pre-emergent" in equipment_view["categoryOptions"]:
            raise AssertionError("Equipment tab contains product category options")
        for text in BAD_VISIBLE_TEXT:
            if text in equipment_view["bodyText"]:
                raise AssertionError(f"bad visible text rendered: {text}")


def main():
    expected_equipment_count = assert_static_data()
    validate_rendered_board(expected_equipment_count)
    print(f"price board validation ok: {expected_equipment_count} equipment products render with links")


if __name__ == "__main__":
    main()
