from playwright.sync_api import sync_playwright


def scrape_site(url):

    products = {}

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        page = browser.new_page()

        page.goto(url, wait_until="networkidle")

        page.wait_for_timeout(5000)

        # Replace with actual selector after inspection
        cards = page.locator("a")

        count = cards.count()

        for i in range(count):

            try:

                card = cards.nth(i)

                href = card.get_attribute("href")

                name = card.inner_text().strip()

                if len(name) < 3:
                    continue

                if href is None:
                    continue

                if href.startswith("/"):

                    domain = "/".join(url.split("/")[:3])

                    href = domain + href

                products[href] = {
                    "name": name,
                    "url": href
                }

            except Exception:
                pass

        browser.close()

    return products


def scrape_all(urls):

    all_products = {}

    for url in urls:

        try:

            products = scrape_site(url)

            all_products.update(products)

            print(f"{url} -> {len(products)} products")

        except Exception as e:

            print(e)

    return all_products