from scrapers.hmt_store import HMTStoreScraper


def make_scraper():
    return HMTStoreScraper(
        base_url="https://hmtwatches.store"
    )


def test_store_stock_buyable():
    scraper = make_scraper()

    product = {
        "currentStock": 10,
        "additionalAttributes": '{"isOOS": false}',
        "buyingOptions": {
            "singlePurchase": {
                "availability": {
                    "inStock": True,
                    "limitedStock": False,
                    "isBuyable": True,
                }
            }
        },
    }

    in_stock, count = scraper._stock(product)

    assert in_stock is True
    assert count == 10


def test_store_stock_oos_override():
    scraper = make_scraper()

    product = {
        "currentStock": 10,
        "additionalAttributes": '{"isOOS": true}',
        "buyingOptions": {
            "singlePurchase": {
                "availability": {
                    "inStock": True,
                    "isBuyable": True,
                }
            }
        },
    }

    in_stock, count = scraper._stock(product)

    assert in_stock is False
    assert count == 0


def test_store_stock_not_buyable():
    scraper = make_scraper()

    product = {
        "currentStock": 0,
        "additionalAttributes": '{"isOOS": false}',
        "buyingOptions": {
            "singlePurchase": {
                "availability": {
                    "inStock": False,
                    "isBuyable": False,
                }
            }
        },
    }

    in_stock, count = scraper._stock(product)

    assert in_stock is False
    assert count == 0


def test_extract_products_from_list():
    scraper = make_scraper()

    payload = [
        {"name": "Watch 1"},
        {"name": "Watch 2"},
    ]

    products = scraper._extract_products(payload)

    assert len(products) == 2


def test_extract_products_from_wrapper():
    scraper = make_scraper()

    payload = {
        "products": [
            {"name": "Watch 1"},
            {"name": "Watch 2"},
        ]
    }

    products = scraper._extract_products(payload)

    assert len(products) == 2


def test_deactivated_product():
    scraper = make_scraper()

    product = {
        "deactivated": True,
        "name": "Disabled Watch",
    }

    assert scraper._is_deactivated(product) is True