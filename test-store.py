from scrapers import HMTStoreScraper

scraper = HMTStoreScraper()

products = scraper.scrape()

print(len(products))

for watch in products.values():

    print()

    print(watch.name)

    print(watch.price)

    print(watch.stock)

    print(watch.product_url)

    print(watch.image_url)

    break